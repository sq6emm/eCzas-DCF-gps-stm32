/* DCF77 timing on its own, see dcf.h. */
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "dcf.h"

#define WIN (DCF_SPS + 2 * DCF_LAGW)
#define QRING 4096                          /* > WIN, power of 2 */
#ifndef DCF_PM_BIAS_US
#define DCF_PM_BIAS_US (-6.3f)              /* mean bias of the sub-sample peak estimate (simulated), removed */
#endif

static float W[DCF_SPS];                    /* phase-code template (mean 0, unit energy) */
static float T[DCF_SPS];                    /* second-mark template (mean 0) */
static float qring[QRING];
uint8_t dcf_prn_bits[512];                  /* the PTB sequence (also used by dcfbits.c) */

static void build(void)
{
    int sr = 0, b1 = 1, k, t, n = 0; uint8_t *prn = dcf_prn_bits; float m = 0, e = 0;
    /* PTB's sequence begins 00000100011000010011100101010110000... (chip 0 = 0); the register
       below yields it from chip 1 on. Without the leading 0 every phase-code time came out one
       chip (120 cycles = 1.548 ms) late - found 1 Oct 2026 against a GPS PPS */
    prn[0] = 0;
    for (k = 1; k < 512; k++) {             /* 9-stage register from 0, a 1 shifted in first */
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

void dcf_restart(dcf_t *d)
{
    uint64_t n = d->n, stage_n = d->stage_n; int stage = d->stage;
    memset(d, 0, sizeof *d);
    d->n = n; d->stage = stage; d->stage_n = stage_n;
    d->minute_s = -1;
    d->pm_ref = -1;
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
    if (valid) {
        d->amp_n++;
        d->amp += (i - d->amp) / (float)(d->amp_n < 40000 ? d->amp_n : 40000);   /* mean, then ~20 s */
        if (d->amp_n >= 2000)
            d->amp_ref += (d->amp - d->amp_ref) * (d->amp > d->amp_ref ? 1.0f / 40000 : 1.0f / 7200000);
    }
    /* usable: tracking, the amplitude settled (1 s) and not faded below DCF_AMP_MIN of its reference */
    d->amp_low = !valid || d->amp_n < 2000 || d->amp <= 0 || d->amp < DCF_AMP_MIN * d->amp_ref;
    d->good_run = d->amp_low ? 0 : d->good_run + 1;
    qring[n & (QRING - 1)] = q;
    if (d->amp_low) {                                    /* the current second's dip is incomplete */
        d->sec_y0 = d->sec_y1 = 0; d->sec_k0 = d->sec_k1 = 0;
        return;
    }
    d->yf[k] += i / d->amp; d->nval += 1;

    if (!d->have_mark) return;
    {
        int p = (int)((n + DCF_SPS - d->mark) % DCF_SPS);  /* position in the DCF77 second */
        if (p >= 10 && p < 190) { d->sec_y0 += i; d->sec_k0++; }
        else if (p >= 400 && p < 1900) { d->sec_y1 += i; d->sec_k1++; }
        if (p == DCF_SPS - 1) {
            uint64_t sd = (n - d->mark) / DCF_SPS;       /* DCF77 second count on the LSE scale */
            if (d->good_run >= DCF_SPS && d->sec_k0 > 100 && d->sec_k1 > 1000) {
                float dip = (d->sec_y1 / d->sec_k1 - d->sec_y0 / d->sec_k0) / d->amp;
                d->dip[sd % 60] += dip; d->dipn[sd % 60] += 1;
            }
            d->sec_y0 = d->sec_y1 = 0; d->sec_k0 = d->sec_k1 = 0;
        }
        /* phase code: DCF_LAGW samples after a DCF77 second ended, its window is complete.
           The fold is anchored at pm_ref (not at the mark: the mark is quantised to 0.5 ms and
           steps with the drift correction, which smeared the fold by 0.5-1 ms) */
        int pr = d->pm_ref >= 0 ? (int)((n + DCF_SPS - d->pm_ref) % DCF_SPS) : -1;
        if (pr == DCF_LAGW - 1 && d->have_minute && d->good_run >= WIN && n >= (uint64_t)(WIN + DCF_SPS)) {
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

/* second mark in a fold normalised by the carrier amplitude: sample index of the best match with
   the 100 (+100) ms reduction, and its significance. Split in two parts (coarse correlation over a
   range of offsets, then the finish) so the 10-min block can spread the work over several samples;
   each caller has its own buffers (the early check and the staged block never share them). */
typedef struct { float sc[DCF_SPS / 4]; float y2[2 * DCF_SPS]; } markbuf_t;
static markbuf_t mb_quick, mb_block;

static void mark_coarse(markbuf_t *mb, const float *yr, int m0, int m1)
{
    int m, k;
    if (m0 == 0) { memcpy(mb->y2, yr, DCF_SPS * sizeof *yr); memcpy(mb->y2 + DCF_SPS, yr, DCF_SPS * sizeof *yr); }
    /* coarse (every 4th offset, 2 ms); the finish tries all offsets within +-2 ms of the best:
     * ~1.1 M multiply-adds instead of 4 M */
    for (m = m0; m < m1; m += 4) {
        const float *y = mb->y2 + m; float s = 0;
        for (k = 0; k < DCF_SPS; k++) s += y[k] * T[k];
        mb->sc[m / 4] = s;
    }
}

static float mark_frac_last;             /* parabolic sub-sample offset of the last mark_finish */
static float mark_score(const markbuf_t *mb, int m)
{
    const float *y = mb->y2 + (m + DCF_SPS) % DCF_SPS; float s = 0; int k;
    for (k = 0; k < DCF_SPS; k++) s += y[k] * T[k];
    return s;
}

static int mark_finish(markbuf_t *mb, float *sigma)
{
    float med, sg, *sc = mb->sc; int m, k, best = 0;
    for (m = 1; m < DCF_SPS / 4; m++) if (sc[m] > sc[best]) best = m;
    sg = robust_sigma(sc, DCF_SPS / 4, (best - 125 + DCF_SPS / 4) % (DCF_SPS / 4), (best + 125) % (DCF_SPS / 4), &med);
    {
        int c = best * 4, bb = c; float bs = sc[best];
        for (m = c - 4; m <= c + 4; m++) {
            int mm = (m + DCF_SPS) % DCF_SPS; float s = 0; const float *y = mb->y2 + mm;
            if (m == c) continue;
            for (k = 0; k < DCF_SPS; k++) s += y[k] * T[k];
            if (s > bs) { bs = s; bb = mm; }
        }
        sc[best] = bs; best = bb;
    }
    {
        float s = 0; const float *y = mb->y2 + best;
        for (k = 0; k < DCF_SPS; k++) s += y[k] * T[k];
        *sigma = (s - med) / sg;
        {   /* sub-sample position: parabola through the neighbours (the mark itself stays an integer) */
            float sm = mark_score(mb, best - 1), sp = mark_score(mb, best + 1), den = sm - 2 * s + sp;
            float f = den < 0 ? 0.5f * (sm - sp) / den : 0.0f;
            mark_frac_last = f > 0.5f ? 0.5f : f < -0.5f ? -0.5f : f;
        }
    }
    return best;
}

static int mark_find(markbuf_t *mb, const float *yr, float *sigma)
{
    mark_coarse(mb, yr, 0, DCF_SPS);
    return mark_finish(mb, sigma);
}

int dcf_quick_mark(dcf_t *d, float min_sigma)
{
    static float t[DCF_SPS];
    float s; int k, best;
    if (d->have_mark || d->nval < 60.0f * DCF_SPS) return 0;
    for (k = 0; k < DCF_SPS; k++) t[k] = d->yf[k] * DCF_SPS / d->nval;
    best = mark_find(&mb_quick, t, &s);
    if (s < min_sigma) return 0;
    d->mark = best; d->mark_frac = mark_frac_last; d->mark_sigma = s; d->have_mark = 1;
    return 1;
}

int dcf_block_ready(const dcf_t *d)
{
    return d->n > 0 && d->n % ((uint64_t)DCF_SPS * DCF_BLOCK_S) == 0;
}

/* minute marker from the running per-second dip depths (no decay here) */
static void minute_eval(dcf_t *d, float min_sigma)
{
    float med, sg;
    /* minute: the second-of-minute without a reduction (DCF77 second 59) */
    {
        float v[60]; int c, lo = 0, ok = 1;
        for (c = 0; c < 60; c++) { if (d->dipn[c] < 3) ok = 0; v[c] = d->dipn[c] > 0 ? d->dip[c] / d->dipn[c] : 0; }
        if (ok) {
            for (c = 1; c < 60; c++) if (v[c] < v[lo]) lo = c;
            sg = robust_sigma(v, 60, lo, lo, &med);
            d->minute_sigma = (med - v[lo]) / sg;
            if (d->minute_sigma > min_sigma) {
                if (d->have_minute && d->minute_s != lo) { memset(d->pmf, 0, sizeof d->pmf); d->pmn = 0; }
                if (d->pm_ref < 0) d->pm_ref = d->mark;
                d->minute_s = lo; d->have_minute = 1;
            }
        }
    }

}

/* phase code from the running fold (no decay here) */
static void pm_eval(dcf_t *d)
{
    float med, sg; int k;
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
            /* sub-sample peak. The correlation of the 0.5 ms sums with the chip template is a triangle
               (+-1 chip = +-3.1 samples) convolved with the 0.5 ms box: parabolic near the top (|x| < 0.5
               sample), linear outside. A parabola through the three top points was biased by -42..+30 us
               depending on where the second falls in the sample grid (review 3, 2 Oct 2026; fixed per boot ->
               30-50 us steps at reboots). For that shape, with D = y3 - y1 and M = y2 - (y1 + y3) / 2:
               D / M = 2p / (0.75 - p^2) -> p = (sqrt(4 + 3 r^2) - 2) / (2 r), r = D / M. Simulated
               (tools/dcf_peak_sim.py: the PTB sequence, 0.5 ms sums): -7.3..-5.2 us instead of -42..+30 us; the mean
               -6.3 us is removed by DCF_PM_BIAS_US */
            float fr = 0;
            if (kb > 0 && kb < 2 * DCF_LAGW) {
                float y1 = fabsf(cc[kb - 1]), y2 = fabsf(cc[kb]), y3 = fabsf(cc[kb + 1]);
                float D = y3 - y1, M = y2 - 0.5f * (y1 + y3);
                if (M > 0 && fabsf(D) > 1e-9f * M) {
                    float r = D / M;
                    fr = (sqrtf(4.0f + 3.0f * r * r) - 2.0f) / (2.0f * r);
                    if (fr > 0.5f) fr = 0.5f;
                    if (fr < -0.5f) fr = -0.5f;
                }
            }
            int off = ((d->pm_ref - d->mark + DCF_SPS + DCF_SPS / 2) % DCF_SPS) - DCF_SPS / 2;   /* anchor - mark, samples */
            d->pm_lag_ms = (kb - DCF_LAGW + fr + off) * 1000.0f / DCF_SPS - DCF_PM_BIAS_US / 1000.0f;
        }
    }
}

int dcf_quick_minute(dcf_t *d, float min_sigma)
{
    if (!d->have_mark || d->have_minute) return 0;
    minute_eval(d, min_sigma);
    return d->have_minute;
}

int dcf_quick_pm(dcf_t *d)
{
    if (!d->have_minute || d->pm_block_done || d->pmn <= 20) return 0;
    pm_eval(d);
    return d->pm_sigma > DCF_PM_MIN;
}

/* stage 1: drift shift of the running fold, fold update; the new block's fold starts empty */
static void block_update(dcf_t *d, float carrier_hz)
{
    int k;
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
    /* yf holds i / amp per usable sample: the mean per second-sample; a block without (enough)
       usable samples only decays the running fold */
    if (d->nval >= DCF_SPS)
        for (k = 0; k < DCF_SPS; k++) d->yr[k] = DCF_KEEP * d->yr[k] + d->yf[k] * DCF_SPS / d->nval;
    memset(d->yf, 0, sizeof d->yf); d->nval = 0;
}

/* after the mark search: accept it (a moved mark restarts the minute and phase-code folds) */
static void block_mark(dcf_t *d, int best)
{
    if (d->mark_sigma > DCF_MARK_MIN) {
        if (d->have_mark && abs(best - d->mark) > 20 && abs(best - d->mark) < DCF_SPS - 20) {
            memset(d->pmf, 0, sizeof d->pmf); d->pmn = 0;       /* the mark moved: restart the fold */
            memset(d->dip, 0, sizeof d->dip); memset(d->dipn, 0, sizeof d->dipn);
            d->have_minute = 0; d->pm_ref = -1;
        }
        d->mark = best; d->mark_frac = mark_frac_last; d->have_mark = 1;
    }
}

static void block_minute(dcf_t *d)
{
    int c;
    minute_eval(d, DCF_MIN_MIN);
    for (c = 0; c < 60; c++) { d->dip[c] *= DCF_KEEP; d->dipn[c] *= DCF_KEEP; }
}

static void block_pm(dcf_t *d)
{
    int k;
    if (d->pmn > 20) {
        pm_eval(d);
        d->pm_block_done = 1;
        for (k = 0; k < WIN; k++) d->pmf[k] *= DCF_KEEP;
        d->pmn *= DCF_KEEP;
    }
}

void dcf_block(dcf_t *d, float carrier_hz)
{
    block_update(d, carrier_hz);
    block_mark(d, mark_find(&mb_block, d->yr, &d->mark_sigma));
    block_minute(d);
    block_pm(d);
}

/* the same work in four steps DCF_STAGE_GAP samples apart (~8 ms each instead of ~24 ms at once) */
int dcf_block_step(dcf_t *d, float carrier_hz)
{
    uint64_t dn = d->n - d->stage_n;
    if (dcf_block_ready(d)) {
        block_update(d, carrier_hz);
        mark_coarse(&mb_block, d->yr, 0, DCF_SPS / 2);
        d->stage = 1; d->stage_n = d->n;
        return 0;
    }
    if (d->stage == 1 && dn == DCF_STAGE_GAP) {
        mark_coarse(&mb_block, d->yr, DCF_SPS / 2, DCF_SPS);
        block_mark(d, mark_finish(&mb_block, &d->mark_sigma));
        d->stage = 2; return 0;
    }
    if (d->stage == 2 && dn == 2 * DCF_STAGE_GAP) { block_minute(d); d->stage = 3; return 0; }
    if (d->stage == 3 && dn == 3 * DCF_STAGE_GAP) { block_pm(d); d->stage = 0; return 1; }
    return 0;
}
