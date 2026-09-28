/* DCF77 timing on its own, see dcf.h. */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "dcf.h"

#define WIN (DCF_SPS + 2 * DCF_LAGW)
#define QRING 4096                          /* > WIN, power of 2 */

static float W[DCF_SPS];                    /* phase-code template (mean 0, unit energy) */
static float T[DCF_SPS];                    /* second-mark template (mean 0) */
static float qring[QRING];
uint8_t dcf_prn_bits[512];                  /* the PTB sequence (also used by dcfbits.c) */

static void build(void)
{
    int sr = 0, b1 = 1, k, t, n = 0; uint8_t *prn = dcf_prn_bits; float m = 0, e = 0;
    for (k = 0; k < 512; k++) {             /* 9-stage register from 0, a 1 shifted in first */
        sr = ((sr << 1) | b1) & 0x1FF;
        b1 = ((sr >> 4) & 1) ^ ((sr >> 8) & 1);
        prn[k] = (uint8_t)b1;
    }
    for (t = 0; t < DCF_SPS; t++) {
        float s = (t + 0.5f) / DCF_SPS - 0.2f;
        int c = (int)floorf(s * 77500.0f / 120.0f);
        W[t] = (s >= 0 && c < 512) ? 1.0f - 2.0f * prn[c] : 0.0f;
        m += W[t];
    }
    m /= DCF_SPS;
    for (t = 0; t < DCF_SPS; t++) { W[t] -= m; e += W[t] * W[t]; }
    e = 1.0f / sqrtf(e);
    for (t = 0; t < DCF_SPS; t++) W[t] *= e;
    m = 0;
    for (t = 0; t < DCF_SPS; t++) { T[t] = t < 200 ? -1.0f : t < 400 ? -0.5f : 0.0f; m += T[t]; n++; }
    m /= n;
    for (t = 0; t < DCF_SPS; t++) T[t] -= m;
}

void dcf_init(dcf_t *d)
{
    memset(d, 0, sizeof *d);
    memset(qring, 0, sizeof qring);
    build();
    d->minute_s = -1;
    d->pm_ref = -1;
    d->amp = 0;
}

static float kth(float *a, int n, int k)      /* quickselect, reorders a[] */
{
    int lo = 0, hi = n - 1;
    while (lo < hi) {
        float p = a[(lo + hi) / 2]; int i = lo, j = hi;
        while (i <= j) {
            while (a[i] < p) i++;
            while (a[j] > p) j--;
            if (i <= j) { float t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; }
        }
        if (k <= j) hi = j; else if (k >= i) lo = i; else break;
    }
    return a[k];
}

static float robust_sigma(const float *v, int n, int skip_lo, int skip_hi, float *med)
{
    /* median and 1.4826 * MAD of v[] outside [skip_lo, skip_hi] (indices may wrap); O(n) */
    static float tmp[DCF_SPS + 2 * DCF_LAGW];
    int i, m = 0;
    for (i = 0; i < n; i++) {
        int in = skip_lo <= skip_hi ? (i >= skip_lo && i <= skip_hi) : (i >= skip_lo || i <= skip_hi);
        if (!in) tmp[m++] = v[i];
    }
    if (!m) { *med = 0; return 1.0f; }
    *med = kth(tmp, m, m / 2);
    for (i = 0; i < m; i++) tmp[i] = fabsf(tmp[i] - *med);
    return 1.4826f * kth(tmp, m, m / 2) + 1e-12f;
}

void dcf_push(dcf_t *d, float i, float q, int valid)
{
    uint64_t n = d->n++;
    int k = (int)(n % DCF_SPS);
    if (!valid) { if (k == DCF_SPS - 1) d->nsec += 0; return; }
    d->amp += (i - d->amp) * (1.0f / 40000);            /* ~20 s */
    d->yf[k] += i;
    if (k == DCF_SPS - 1) d->nsec++;
    qring[n & (QRING - 1)] = q;

    if (!d->have_mark || d->amp <= 0) return;
    {
        int p = (int)((n + DCF_SPS - d->mark) % DCF_SPS);  /* position in the DCF77 second */
        if (p >= 10 && p < 190) { d->sec_y0 += i; d->sec_k0++; }
        else if (p >= 400 && p < 1900) { d->sec_y1 += i; d->sec_k1++; }
        if (p == DCF_SPS - 1) {
            uint64_t sd = (n - d->mark) / DCF_SPS;       /* DCF77 second count on the LSE scale */
            if (d->sec_k0 > 100 && d->sec_k1 > 1000) {
                float dip = (d->sec_y1 / d->sec_k1 - d->sec_y0 / d->sec_k0) / d->amp;
                d->dip[sd % 60] += dip; d->dipn[sd % 60] += 1;
            }
            d->sec_y0 = d->sec_y1 = 0; d->sec_k0 = d->sec_k1 = 0;
        }
        /* phase code: DCF_LAGW samples after a DCF77 second ended, its window is complete.
           The fold is anchored at pm_ref (not at the mark: the mark is quantised to 0.5 ms and
           steps with the drift correction, which smeared the fold by 0.5-1 ms) */
        int pr = d->pm_ref >= 0 ? (int)((n + DCF_SPS - d->pm_ref) % DCF_SPS) : -1;
        if (pr == DCF_LAGW - 1 && d->have_minute && n >= (uint64_t)(WIN + DCF_SPS)) {
            uint64_t sd = (n - d->pm_ref) / DCF_SPS - 1; /* the second just completed */
            int sm = (int)((sd + 60 - (uint64_t)d->minute_s - 1) % 60), j;
            float sg = sm <= 9 ? -1.0f : sm <= 14 ? 1.0f : 0.0f;
            if (sg != 0) {
                uint64_t start = n + 1 - WIN;            /* window = second start - LAGW .. end + LAGW */
                for (j = 0; j < WIN; j++) d->pmf[j] += sg * qring[(start + j) & (QRING - 1)] / d->amp;
                d->pmn += 1;
            }
        }
    }
}

int dcf_block_ready(const dcf_t *d)
{
    return d->n > 0 && d->n % ((uint64_t)DCF_SPS * DCF_BLOCK_S) == 0;
}

void dcf_block(dcf_t *d, float carrier_hz)
{
    static float sc[DCF_SPS];
    static float y2[2 * DCF_SPS];                   /* yr twice: no modulo in the inner loops */
    float med, sg; int m, k, best;
    /* second mark (running) */
    /* the DCF77 second lasts (1 - carrier_hz/77500) * 2000 LSE samples: over one block its start
     * moves by -carrier_hz/77500 * block samples through the LSE second; shift the running
     * fold (and the mark) by the whole samples of that drift, keep the fraction */
    d->slip += -(double)carrier_hz / 77500.0 * (double)DCF_SPS * DCF_BLOCK_S;
    {
        int sh = (int)floor(d->slip + 0.5);
        if (sh > 50 || sh < -50) sh = 0, d->slip = 0;          /* implausible: ignore */
        if (sh != 0) {
            static float t[DCF_SPS];
            for (k = 0; k < DCF_SPS; k++) t[(k + sh + DCF_SPS) % DCF_SPS] = d->yr[k];
            memcpy(d->yr, t, sizeof t);
            if (d->have_mark) d->mark = (d->mark + sh + DCF_SPS) % DCF_SPS;
            if (d->pm_ref >= 0) d->pm_ref = (d->pm_ref + sh + DCF_SPS) % DCF_SPS;
            d->slip -= sh;
        }
    }
    if (d->nsec > 0 && d->amp > 0)
        for (k = 0; k < DCF_SPS; k++) d->yr[k] = DCF_KEEP * d->yr[k] + d->yf[k] / (d->nsec * d->amp);
    memcpy(y2, d->yr, sizeof d->yr); memcpy(y2 + DCF_SPS, d->yr, sizeof d->yr);
    /* coarse (every 4th offset, 2 ms), then all offsets within +-2 ms of the best:
     * ~1.1 M multiply-adds instead of 4 M, keeps the 10-min evaluation to a few ms */
    for (m = 0; m < DCF_SPS; m += 4) {
        const float *y = y2 + m; float s = 0;
        for (k = 0; k < DCF_SPS; k++) s += y[k] * T[k];
        sc[m / 4] = s;
    }
    best = 0;
    for (m = 1; m < DCF_SPS / 4; m++) if (sc[m] > sc[best]) best = m;
    sg = robust_sigma(sc, DCF_SPS / 4, (best - 125 + DCF_SPS / 4) % (DCF_SPS / 4), (best + 125) % (DCF_SPS / 4), &med);
    {
        int c = best * 4, bb = c; float bs = sc[best];
        for (m = c - 4; m <= c + 4; m++) {
            int mm = (m + DCF_SPS) % DCF_SPS; float s = 0; const float *y = y2 + mm;
            if (m == c) continue;
            for (k = 0; k < DCF_SPS; k++) s += y[k] * T[k];
            if (s > bs) { bs = s; bb = mm; }
        }
        sc[best] = bs; best = bb;
    }
    {
        float s = 0; const float *y = y2 + best;
        for (k = 0; k < DCF_SPS; k++) s += y[k] * T[k];
        d->mark_sigma = (s - med) / sg;
    }
    if (d->mark_sigma > DCF_MARK_MIN) {
        if (d->have_mark && abs(best - d->mark) > 20 && abs(best - d->mark) < DCF_SPS - 20) {
            memset(d->pmf, 0, sizeof d->pmf); d->pmn = 0;       /* the mark moved: restart the fold */
            memset(d->dip, 0, sizeof d->dip); memset(d->dipn, 0, sizeof d->dipn);
            d->have_minute = 0; d->pm_ref = -1;
        }
        d->mark = best; d->have_mark = 1;
    }
    memset(d->yf, 0, sizeof d->yf); d->nsec = 0;

    /* minute: the second-of-minute without a reduction (DCF77 second 59) */
    {
        float v[60]; int c, lo = 0, ok = 1;
        for (c = 0; c < 60; c++) { if (d->dipn[c] < 3) ok = 0; v[c] = d->dipn[c] > 0 ? d->dip[c] / d->dipn[c] : 0; }
        if (ok) {
            for (c = 1; c < 60; c++) if (v[c] < v[lo]) lo = c;
            sg = robust_sigma(v, 60, lo, lo, &med);
            d->minute_sigma = (med - v[lo]) / sg;
            if (d->minute_sigma > DCF_MIN_MIN) {
                if (d->have_minute && d->minute_s != lo) { memset(d->pmf, 0, sizeof d->pmf); d->pmn = 0; }
                if (d->pm_ref < 0) d->pm_ref = d->mark;
                d->minute_s = lo; d->have_minute = 1;
            }
        }
        for (c = 0; c < 60; c++) { d->dip[c] *= DCF_KEEP; d->dipn[c] *= DCF_KEEP; }
    }

    /* phase code: correlate the running fold with the exact sequence over +-DCF_LAGW */
    if (d->pmn > 20) {
        static float cc[2 * DCF_LAGW + 1];
        int L, kb = 0;
        for (L = -DCF_LAGW; L <= DCF_LAGW; L++) {
            float s = 0;
            for (k = 0; k < DCF_SPS; k++) s += d->pmf[DCF_LAGW + k + L] * W[k];
            cc[L + DCF_LAGW] = s;
            if (fabsf(s) > fabsf(cc[kb])) kb = L + DCF_LAGW;
        }
        sg = robust_sigma(cc, 2 * DCF_LAGW + 1, kb - 4 < 0 ? 0 : kb - 4, kb + 4 > 2 * DCF_LAGW ? 2 * DCF_LAGW : kb + 4, &med);
        d->pm_sigma = (fabsf(cc[kb]) - fabsf(med)) / sg;
        {
            float fr = 0;
            if (kb > 0 && kb < 2 * DCF_LAGW) {
                float y1 = fabsf(cc[kb - 1]), y2 = fabsf(cc[kb]), y3 = fabsf(cc[kb + 1]), den = y1 - 2 * y2 + y3;
                if (den != 0) fr = 0.5f * (y1 - y3) / den;
            }
            int off = ((d->pm_ref - d->mark + DCF_SPS + DCF_SPS / 2) % DCF_SPS) - DCF_SPS / 2;   /* anchor - mark, samples */
            d->pm_lag_ms = (kb - DCF_LAGW + fr + off) * 1000.0f / DCF_SPS;
        }
        for (k = 0; k < WIN; k++) d->pmf[k] *= DCF_KEEP;
        d->pmn *= DCF_KEEP;
    }
}
