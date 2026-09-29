/* TDF / ALS162 time-code decoder - see tdf.h */
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include "tdf.h"
#include "tdf_shape.h"

#define A 100                              /* window: A ms before the second start ... */
#define B (TDF_WIN - A)                    /* ... B ms after it */
#define HL 100                             /* matched filter: the first 100 ms of the burst */
#ifndef FOLD_KEEP
#define FOLD_KEEP 0.99f                    /* per second: ~100 s memory of the second-start fold */
#endif
#ifndef TDF_PRED_MIN
#define TDF_PRED_MIN 30.0f                 /* expected-frame score (sum of signed LLRs) needed */
#endif
#ifndef TDF_PRED_MARGIN
#define TDF_PRED_MARGIN 15.0f              /* and its lead over the frames +-1, +-2 minutes */
#endif
#ifndef TDF_CAND_AGREE
#define TDF_CAND_AGREE 0.8f                /* proving a candidate: score / sum |LLR| over the scored bits */
#endif
#ifndef MFOLD_KEEP
#define MFOLD_KEEP 0.8f                    /* per minute: ~5 min memory of the marker fold */
#endif

static float e0r[TDF_WIN], e0i[TDF_WIN], e1r[TDF_WIN], e1i[TDF_WIN];
static float hr[HL], hi[HL];
static int built;

static void build(void)
{
    int k; float mr = 0, mi = 0;
    for (k = 0; k < TDF_WIN; k++) {
        e0r[k] = cosf(TDF_T0[k]); e0i[k] = sinf(TDF_T0[k]);
        e1r[k] = cosf(TDF_T1[k]); e1i[k] = sinf(TDF_T1[k]);
    }
    for (k = 0; k < HL; k++) { hr[k] = e0r[A + k]; hi[k] = e0i[A + k]; mr += hr[k]; mi += hi[k]; }
    for (k = 0; k < HL; k++) { hr[k] -= mr / HL; hi[k] -= mi / HL; }   /* orthogonal to the plain carrier */
    built = 1;
}

void tdf_init(tdf_t *t)
{
    memset(t, 0, sizeof *t);
    t->start = -1; t->phase60 = -1; t->sig2 = 0;
    if (!built) build();
}

static int64_t days_from_civil(int y, int m, int d)   /* days since 1970-01-01 */
{
    y -= m <= 2;
    int64_t era = (y >= 0 ? y : y - 399) / 400;
    int yoe = (int)(y - era * 400);
    int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

/* squared error of the best fit g * exp(jT) to the window, and of g * 1 (no modulation) */
static float fit_err(const float *wr, const float *wi, const float *er, const float *ei, float e_tot)
{
    float cr = 0, ci = 0; int k;
    for (k = 0; k < TDF_WIN; k++) { cr += wr[k] * er[k] + wi[k] * ei[k]; ci += wi[k] * er[k] - wr[k] * ei[k]; }
    return e_tot - (cr * cr + ci * ci) / TDF_WIN;
}

/* the 59 time-code bits (DCF77 layout) for UTC minute m (minutes since 2000) */
static void encode(int64_t m, int cest, int *b)
{
    static const int W[8] = { 1, 2, 4, 8, 10, 20, 40, 80 };
    int64_t loc = m + (cest ? 120 : 60), days = loc / 1440 + days_from_civil(2000, 1, 1);
    int mi = (int)(loc % 60), hr_ = (int)(loc / 60 % 24), k;
    /* civil date from days since 1970 */
    int64_t z = days + 719468, era = (z >= 0 ? z : z - 146096) / 146097;
    int doe = (int)(z - era * 146097), yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int doy = doe - (365 * yoe + yoe / 4 - yoe / 100), mp = (5 * doy + 2) / 153;
    int d = doy - (153 * mp + 2) / 5 + 1, mo = mp + (mp < 10 ? 3 : -9), y = (int)(yoe + era * 400) + (mo <= 2);
    int wd = (int)((days % 7 + 7 + 3) % 7) + 1;          /* 1970-01-01 = Thursday; 1 = Monday */
    for (k = 0; k < 59; k++) b[k] = 0;
    b[17] = cest; b[18] = !cest; b[20] = 1;
    #define PUT(lo, v, n) { int v_ = (v), i_; for (i_ = (n) - 1; i_ >= 0; i_--) if (v_ >= W[i_]) { b[(lo) + i_] = 1; v_ -= W[i_]; } }
    PUT(21, mi, 7); PUT(29, hr_, 6); PUT(36, d, 6); PUT(42, wd, 3); PUT(45, mo, 5); PUT(50, y % 100, 8);
    int p;
    p = 0; for (k = 21; k < 28; k++) p ^= b[k]; b[28] = p;
    p = 0; for (k = 29; k < 35; k++) p ^= b[k]; b[35] = p;
    p = 0; for (k = 36; k < 58; k++) p ^= b[k]; b[58] = p;
}

static float score(const tdf_t *t, uint64_t s0, int64_t m, int cest, float *abs_sum)
{
    int b[59], k; float s = 0, a = 0;
    encode(m, cest, b);
    for (k = 17; k < 59; k++) {                           /* bits 15, 16, 19 (announcements) are not predictable */
        if (k == 19) continue;
        float l = t->llr[(s0 + k) % 60];
        s += b[k] ? l : -l; a += fabsf(l);
    }
    if (abs_sum) *abs_sum = a;
    return s;
}

/* confirmation by the expected frame; on success the result fields describe the expected minute */
static void predict(tdf_t *t, uint64_t s0)
{
    t->status = TDF_FAILED;
    int from_cand = !t->have_ref && t->have_cand;          /* no confirmed reference yet: try the candidate */
    if (!t->have_ref && !from_cand) return;
    int64_t r = from_cand ? t->cand_utc : t->ref_utc; uint64_t rs = from_cand ? t->cand_sec : t->ref_sec;
    int cest = from_cand ? t->cand_cest : t->ref_cest;
    if (from_cand && t->sec - rs > 90) { t->have_cand = 0; return; }   /* the candidate must be proven by the next minute */
    int64_t e = r + (int64_t)((t->sec - rs + 30) / 60);
    float asum, se = score(t, s0, e, cest, &asum), best = -1e30f; int d;
    for (d = -2; d <= 2; d++) if (d) { float x = score(t, s0, e + d, cest, 0); if (x > best) best = x; }
    t->pred_score = se; t->pred_margin = se - best;
    /* a candidate (never confirmed) must match nearly every confident bit, not only beat its neighbours:
       a wrong hour or date passes the +-2 minute comparison (28 Sep bench) */
    if (from_cand && se < TDF_CAND_AGREE * asum) return;
    if (se >= TDF_PRED_MIN && se - best >= TDF_PRED_MARGIN) {
        if (from_cand) { t->have_ref = 1; t->ref_utc = e; t->ref_cest = cest; t->ref_sec = t->sec; t->have_cand = 0; }
        t->ref_cest = cest;
        int b[59];
        t->status = TDF_PREDICTED; t->n_predicted++;
        t->utc_min = e; t->cest = t->ref_cest; encode(e, t->cest, b);
        int64_t loc = e + (t->cest ? 120 : 60);
        t->minute = (int)(loc % 60); t->hour = (int)(loc / 60 % 24);
        t->day = 10 * b[40] + 20 * b[41] + b[36] + 2 * b[37] + 4 * b[38] + 8 * b[39];
        t->month = b[45] + 2 * b[46] + 4 * b[47] + 8 * b[48] + 10 * b[49];
        t->year = 2000 + b[50] + 2 * b[51] + 4 * b[52] + 8 * b[53] + 10 * b[54] + 20 * b[55] + 40 * b[56] + 80 * b[57];
        t->have_prev = 1; t->prev_utc = e;
    }
}

static void decode_minute(tdf_t *t)
{
    int b[59], k, flips = 0; float c[59];
    static const int W[8] = { 1, 2, 4, 8, 10, 20, 40, 80 };
    static const int G[3][2] = { { 21, 29 }, { 29, 36 }, { 36, 59 } };
    uint64_t s0 = t->sec - 60;                         /* seconds 0..58: the 59 seconds before the marker (index sec-1) */
    for (k = 0; k < 59; k++) { float l = t->llr[(s0 + k) % 60]; b[k] = l > 0; c[k] = fabsf(l); }
    for (k = 0; k < 3; k++) {
        int j, par = 0, jm = G[k][0];
        for (j = G[k][0]; j < G[k][1]; j++) { par ^= b[j]; if (c[j] < c[jm]) jm = j; }
        if (par) { b[jm] ^= 1; flips++; }
    }
    int ok = b[20] == 1 && b[17] != b[18];
    #define VAL(lo, n) ({ int v_ = 0, i_; for (i_ = 0; i_ < (n); i_++) v_ += b[(lo) + i_] * W[i_]; v_; })
    #define DIG(lo) (b[lo] | b[(lo) + 1] << 1 | b[(lo) + 2] << 2 | b[(lo) + 3] << 3)
    int mi = VAL(21, 7), hr_ = VAL(29, 6), dy = VAL(36, 6), mo = VAL(45, 5), yr = VAL(50, 8);
    if (DIG(21) > 9 || DIG(29) > 9 || DIG(36) > 9 || DIG(45) > 9 || DIG(50) > 9 || DIG(54) > 9) ok = 0;
    if (mi > 59 || hr_ > 23 || dy < 1 || dy > 31 || mo < 1 || mo > 12) ok = 0;
    for (k = 0; k < 3 && ok; k++) { int j, par = 0; for (j = G[k][0]; j < G[k][1]; j++) par ^= b[j]; if (par) ok = 0; }
    t->flips = flips;
    static const int MDAYS[12] = { 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
    if (ok && dy > MDAYS[mo - 1]) ok = 0;
    if (!ok) { t->have_prev = 0; predict(t, s0); if (t->status == TDF_FAILED) t->n_failed++; return; }
    t->year = 2000 + yr; t->month = mo; t->day = dy; t->hour = hr_; t->minute = mi; t->cest = b[17];
    int64_t days = days_from_civil(t->year, mo, dy) - days_from_civil(2000, 1, 1);
    t->utc_min = days * 1440 + hr_ * 60 + mi - (t->cest ? 120 : 60);
    t->n_decoded++;
    if (t->have_prev && t->utc_min == t->prev_utc + 1) {
        t->status = TDF_CONFIRMED; t->n_confirmed++;
        t->have_ref = 1; t->ref_utc = t->utc_min; t->ref_cest = t->cest; t->ref_sec = t->sec;
        t->have_prev = 1; t->prev_utc = t->utc_min;
        return;
    }
    t->have_prev = 1; t->prev_utc = t->utc_min;
    predict(t, s0);                                       /* decoded but not (yet) confirmed */
    if (t->status != TDF_PREDICTED) {
        t->status = TDF_UNCONFIRMED;
        if (!t->have_ref && flips == 0) { t->have_cand = 1; t->cand_utc = t->utc_min; t->cand_cest = t->cest; t->cand_sec = t->sec; }
    }
}

int tdf_push(tdf_t *t, float re, float im, int valid)
{
    int k, ret = 0;
    t->n2++;
    if (!valid) re = im = 0;
    if (!t->pv) { t->pr = re; t->pi = im; t->pv = 1; return 0; }
    t->pv = 0;
    uint64_t n = t->n++;
    t->ur[n & (TDF_RING - 1)] = 0.5f * (t->pr + re);
    t->ui[n & (TDF_RING - 1)] = 0.5f * (t->pi + im);
    /* matched filter on the burst, for the window that started HL-1 samples ago */
    if (n >= HL) {
        uint64_t s = n - (HL - 1);
        float cr = 0, ci = 0;
        for (k = 0; k < HL; k++) {
            float xr = t->ur[(s + k) & (TDF_RING - 1)], xi = t->ui[(s + k) & (TDF_RING - 1)];
            cr += xr * hr[k] + xi * hi[k]; ci += xi * hr[k] - xr * hi[k];
        }
        t->fold[s % 1000] += cr * cr + ci * ci;
    }
    /* once per second (1 kHz index multiple of 1000): age the fold, pick the second start */
    if (n % 1000 == 999 && n > 2000) {
        int best = 0; float sum = 0;
        for (k = 0; k < 1000; k++) { if (t->fold[k] > t->fold[best]) best = k; sum += t->fold[k]; t->fold[k] *= FOLD_KEEP; }
        t->start_q = sum > 0 ? t->fold[best] / FOLD_KEEP / (sum / 1000) : 0;
        int dmov = abs(best - t->start);
        if (dmov > 500) dmov = 1000 - dmov;              /* circular distance */
        if (n > 30000 && (t->start < 0 || dmov > 3)) {                     /* after 30 s of fold; follow the peak (3 ms hysteresis) */
            t->start = best;
            uint64_t s = n - n % 1000 + (uint64_t)best;  /* a second start in this second */
            while (s + B - 1 <= n) s += 1000;
            t->next_sec = s + B - 1;                      /* its window's last sample */
        }
    }
    /* evaluate the second whose window just completed */
    if (t->start >= 0 && n == t->next_sec) {
        static float wr[TDF_WIN], wi[TDF_WIN];
        uint64_t s0 = n - (TDF_WIN - 1);
        float etot = 0;
        for (k = 0; k < TDF_WIN; k++) {
            wr[k] = t->ur[(s0 + k) & (TDF_RING - 1)]; wi[k] = t->ui[(s0 + k) & (TDF_RING - 1)];
            etot += wr[k] * wr[k] + wi[k] * wi[k];
        }
        float er0 = fit_err(wr, wi, e0r, e0i, etot), er1 = fit_err(wr, wi, e1r, e1i, etot);
        float cr = 0, ci = 0;
        for (k = 0; k < TDF_WIN; k++) { cr += wr[k]; ci += wi[k]; }
        float erm = etot - (cr * cr + ci * ci) / TDF_WIN;
        float best = er0 < er1 ? er0 : er1;
        float s2 = best / (TDF_WIN - 1);
        t->sig2 = t->sig2 > 0 ? t->sig2 + 0.02f * (s2 - t->sig2) : s2;
        uint64_t i = t->sec++;
        t->llr[i % 60] = (er0 - er1) / (t->sig2 + 1e-30f);
        t->mscore[i % 60] = (best - erm) / (t->sig2 + 1e-30f);
        t->mfold[i % 60] = MFOLD_KEEP * t->mfold[i % 60] + t->mscore[i % 60];
        t->next_sec = n + 1000;
        if (t->sec >= 180) {                              /* marker phase after 3 minutes */
            int p = 0;
            for (k = 1; k < 60; k++) if (t->mfold[k] > t->mfold[p]) p = k;
            t->phase60 = p;
        }
        if (t->phase60 >= 0 && (int)(i % 60) == t->phase60 && t->sec >= 60) { decode_minute(t); ret = 1; }
    }
    return ret;
}
