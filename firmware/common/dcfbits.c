/* DCF77 time code, decoded every minute: see dcfbits.h. */
#include <math.h>
#include <string.h>
#include "dcfbits.h"

#ifndef DCFB_PRED_MIN
#define DCFB_PRED_MIN    20.0f       /* expected frame: minimum fit (sum of agreeing LLRs) */
#endif
#ifndef DCFB_PRED_MARGIN
#define DCFB_PRED_MARGIN 10.0f       /* ... and its lead over the minutes +-1, +-2 */
#endif
#ifndef DCFB_GRID_TOL
#define DCFB_GRID_TOL    0.5         /* a reference minute counts only while the minute ends stay on its */
#endif                               /* grid: whole minutes after it, +-0.5 s (+DCFB_GRID_PPM of the time since) */
#ifndef DCFB_GRID_PPM
#ifdef OCXO_REF
#define DCFB_GRID_PPM    1.0         /* the sample clock is the OCXO: 20 ppm let the grid grow to +-30 s in 17 days */
#else
#define DCFB_GRID_PPM    20.0        /* LSE crystal */
#endif
#endif

extern uint8_t dcf_prn_bits[512];          /* the PTB sequence, built by dcf_init() */

void dcfbits_init(dcfbits_t *b)
{
    memset(b, 0, sizeof *b);
    b->lev_red = 0.15f; b->var_am = 0.1f; b->var_pm = 1.0f; b->amp_pm = 0.0f; b->amp_pmk = 0.27f;
}

void dcfbits_restart(dcfbits_t *b)
{
    b->am0 = b->am1 = b->ref = b->pm = 0; b->n0 = b->n1 = b->nr = b->npm = 0;
    b->ii2 = b->qq2 = 0; b->nii = b->nqq = 0;
    memset(b->have, 0, sizeof b->have);
}

static int bcd(const uint8_t *x, int from, int n, int *v)
{
    static const int w[8] = { 1, 2, 4, 8, 10, 20, 40, 80 };
    int s = 0, u = 0, k;
    for (k = 0; k < n; k++) s += x[from + k] ? w[k] : 0;
    for (k = 0; k < 4 && k < n; k++) u += x[from + k] << k;
    if (u > 9) return 0;                                       /* units digit 0..9 */
    *v = s;
    return 1;
}

static int parity_ok(const uint8_t *x, int from, int to)   /* bits from..to inclusive, even parity */
{
    int s = 0, k;
    for (k = from; k <= to; k++) s ^= x[k];
    return s == 0;
}

static int64_t days_from_civil(int y, int m, int d)   /* days since 1970-01-01 */
{
    y -= m <= 2;
    int64_t era = (y >= 0 ? y : y - 399) / 400;
    int64_t yoe = y - era * 400;
    int64_t doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    int64_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

static void civil_from_days(int64_t z, int *y, int *m, int *d)   /* days since 1970-01-01 */
{
    z += 719468;
    int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    int64_t doe = z - era * 146097;
    int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    int64_t mp = (5 * doy + 2) / 153;
    *d = (int)(doy - (153 * mp + 2) / 5 + 1);
    *m = (int)(mp < 10 ? mp + 3 : mp - 9);
    *y = (int)(yoe + era * 400 + (*m <= 2));
}

/* summer time (CEST) in force in the minute utc_min (minutes since 2000-01-01 UTC)? EU rule:
   from the last Sunday of March to the last Sunday of October, 01:00 UTC */
static int eu_cest(int64_t utc_min)
{
    int64_t t = utc_min + days_from_civil(2000, 1, 1) * 1440;      /* minutes since 1970 */
    int y, mo, d;
    civil_from_days(t / 1440, &y, &mo, &d);
    int64_t mar = days_from_civil(y, 3, 31), oct = days_from_civil(y, 10, 31);
    mar -= (mar + 4) % 7; oct -= (oct + 4) % 7;                   /* back to Sunday (1970-01-01 = Thursday) */
    return t >= mar * 1440 + 60 && t < oct * 1440 + 60;
}

static void put_bcd(uint8_t *x, int from, int n, int v)
{
    static const int w[8] = { 1, 2, 4, 8, 10, 20, 40, 80 };
    int k;
    for (k = n - 1; k >= 0; k--) { x[from + k] = v >= w[k]; if (x[from + k]) v -= w[k]; }
}

/* the 59 bits DCF77 sends for the minute starting at utc_min (minutes since 2000-01-01 UTC);
   bits 1..16 and 19 (weather, call, announcements) are left 0 and not used for scoring */
static void encode(int64_t utc_min, int cest, uint8_t *x)
{
    int64_t lm = utc_min + (cest ? 120 : 60);
    int64_t days = lm / 1440 + days_from_civil(2000, 1, 1);
    int mi = (int)(lm % 1440) % 60, hr = (int)(lm % 1440) / 60, y, mo, d, k, p;
    civil_from_days(days, &y, &mo, &d);
    int wd = (int)(((days % 7) + 7 + 3) % 7) + 1;              /* 1970-01-01 was a Thursday (4) */
    for (k = 0; k < 59; k++) x[k] = 0;
    x[17] = cest ? 1 : 0; x[18] = cest ? 0 : 1; x[20] = 1;
    put_bcd(x, 21, 7, mi); put_bcd(x, 29, 6, hr); put_bcd(x, 36, 6, d);
    x[42] = wd & 1; x[43] = (wd >> 1) & 1; x[44] = (wd >> 2) & 1;
    put_bcd(x, 45, 5, mo); put_bcd(x, 50, 8, y % 100);
    for (p = 0, k = 21; k < 28; k++) p ^= x[k];
    x[28] = p;
    for (p = 0, k = 29; k < 35; k++) p ^= x[k];
    x[35] = p;
    for (p = 0, k = 36; k < 58; k++) p ^= x[k];
    x[58] = p;
}

static float fit(const float *z, const uint8_t *x)       /* sum of LLRs agreeing with x, bits 17..58 */
{
    float s = 0; int k;
    for (k = 17; k < 59; k++) if (k != 19) s += x[k] ? -z[k] : z[k];
    return s;
}

/* check a 59-bit frame and fill the fields; 0 = invalid */
static int check(dcfbits_t *b, const uint8_t *x)
{
    int mi, hr, dy, wd, mo, yr;
    if (x[0] != 0 || x[20] != 1) return 0;
    if (x[17] == x[18]) return 0;                              /* exactly one of CEST / CET */
    if (!parity_ok(x, 21, 28) || !parity_ok(x, 29, 35) || !parity_ok(x, 36, 58)) return 0;
    if (!bcd(x, 21, 7, &mi) || mi > 59) return 0;
    if (!bcd(x, 29, 6, &hr) || hr > 23) return 0;
    if (!bcd(x, 36, 6, &dy) || dy < 1 || dy > 31) return 0;
    wd = x[42] | x[43] << 1 | x[44] << 2; if (wd < 1 || wd > 7) return 0;
    if (!bcd(x, 45, 5, &mo) || mo < 1 || mo > 12) return 0;
    if (!bcd(x, 50, 8, &yr) || yr > 99) return 0;      /* two digits: 2000-2099. (The weekday could tell the
                                                          century, but a check on it lost correct minutes whose
                                                          weekday bits alone were wrong - replay 6-8 Oct) */
    b->minute = mi; b->hour = hr; b->day = dy; b->weekday = wd; b->month = mo; b->year = 2000 + yr;
    b->cest = x[17];
    int64_t days = days_from_civil(b->year, mo, dy) - days_from_civil(2000, 1, 1);
    b->utc_min = days * 1440 + hr * 60 + mi - (b->cest ? 120 : 60);
    return 1;
}

/* whole minutes from n0 to n_end; 0 when n_end is off n0's minute grid (the minute marker moved:
   the minutes could then be rounded to the wrong count, and each accepted expected frame would
   carry the error on - seen on 29 Sep 2026 with a marker 30 s off after an input gap) */
static int on_grid(uint64_t n_end, uint64_t n0, int64_t *el)
{
    double dn = (double)(n_end - n0);
    *el = (int64_t)llround(dn / (60.0 * DCF_SPS));
    return fabs(dn - (double)*el * 60.0 * DCF_SPS) <= (DCFB_GRID_TOL + DCFB_GRID_PPM * 1e-6 * dn / DCF_SPS) * DCF_SPS;
}

/* a leap second ends this minute: DCF77 announces it with bit 19 in the hour before, and it is
   inserted before 00:00 UTC on the 1st of a month; the minute then has 61 s, so the grid of minute
   ends moves by one second (dcf.c moves its second count: dcf_leap_second) */
static void leap_check(dcfbits_t *b)
{
    int y, mo, d;
    b->leap_next = 0;
    if (b->status != DCFT_CONFIRMED && b->status != DCFT_PREDICTED) return;
    if (!(b->z_am[19] + b->z_pm[19] < 0) || b->utc_min % 1440 != 0) return;
    civil_from_days(b->utc_min / 1440 + days_from_civil(2000, 1, 1), &y, &mo, &d);
    if (d != 1) return;
    b->leap_next = 1;
    b->ref_n_end += DCF_SPS; b->last_n_end += DCF_SPS;
}

static void decode(dcfbits_t *b, uint64_t n_end)
{
    uint8_t x[59]; float r[59];
    int k, g, am_pm = 0, npm = 0;
    for (k = 0; k < 59; k++) {
        float z = b->z_am[k] + b->z_pm[k];
        x[k] = z < 0 ? 1 : 0; r[k] = fabsf(z);
        if (b->z_pm[k] != 0) { npm++; if ((b->z_am[k] < 0) == (b->z_pm[k] < 0)) am_pm++; }
    }
    b->flips = 0;
    if (!check(b, x)) {                                       /* one flip per failing parity group */
        static const int grp[3][2] = { { 21, 28 }, { 29, 35 }, { 36, 58 } };
        for (g = 0; g < 3; g++) {
            if (parity_ok(x, grp[g][0], grp[g][1])) continue;
            int w = grp[g][0];
            for (k = grp[g][0]; k <= grp[g][1]; k++) if (r[k] < r[w]) w = k;
            x[w] ^= 1; r[w] = 0; b->flips++;
        }
    }
    b->bits_pm = npm; b->am_pm_agree = am_pm;
    b->weakest = 1e9f;
    for (k = 20; k < 59; k++) if (r[k] < b->weakest) b->weakest = r[k];
    b->n_end = n_end;
    b->ready = 1;
    int ok = check(b, x);
    b->pred_score = b->pred_margin = 0;
    int64_t el;
    if (b->have_ref && !on_grid(n_end, b->ref_n_end, &el)) b->have_ref = 0;   /* start again from standalone decodes */
    if (b->have_ref) {                                        /* expected-frame confirmation */
        int64_t te = b->ref_utc_min + el;
        float sc[5]; uint8_t y[59]; int d;
        float zz[59];
        for (k = 0; k < 59; k++) zz[k] = b->z_am[k] + b->z_pm[k];
        for (d = -2; d <= 2; d++) { encode(te + d, eu_cest(te + d), y); sc[d + 2] = fit(zz, y); }
        float other = sc[0];
        for (d = 1; d < 5; d++) if (d != 2 && sc[d] > other) other = sc[d];
        b->pred_score = sc[2]; b->pred_margin = sc[2] - other;
        if (ok && b->utc_min == te) {                         /* standalone decode = expectation */
            b->status = DCFT_CONFIRMED; b->n_decoded++; b->n_confirmed++;
            b->ref_utc_min = te; b->ref_n_end = n_end;
        } else if (sc[2] > DCFB_PRED_MIN && b->pred_margin > DCFB_PRED_MARGIN) {
            b->cest = eu_cest(te);                            /* fill the fields from te */
            int64_t lm = te + (b->cest ? 120 : 60), days = lm / 1440;
            civil_from_days(days + days_from_civil(2000, 1, 1), &b->year, &b->month, &b->day);
            b->hour = (int)(lm % 1440) / 60; b->minute = (int)(lm % 1440) % 60;
            b->utc_min = te;
            b->status = DCFT_PREDICTED; b->n_predicted++;
            b->ref_utc_min = te; b->ref_n_end = n_end;
        } else {
            b->status = ok ? DCFT_UNCONFIRMED : DCFT_FAILED;
            if (ok) b->n_decoded++; else b->n_failed++;
        }
        if (ok) { b->last_utc_min = b->utc_min; b->last_n_end = n_end; b->have_last = 1; }
        leap_check(b);
        return;
    }
    if (!ok) { b->status = DCFT_FAILED; b->n_failed++; b->leap_next = 0; return; }
    b->n_decoded++;
    /* first confirmation: two standalone decodes that agree with the minutes elapsed */
    b->status = DCFT_UNCONFIRMED;
    if (b->have_last && on_grid(n_end, b->last_n_end, &el)) {
        if (b->utc_min == b->last_utc_min + el) {
            b->status = DCFT_CONFIRMED; b->n_confirmed++;
            b->have_ref = 1; b->ref_utc_min = b->utc_min; b->ref_n_end = n_end;
        }
    }
    b->last_utc_min = b->utc_min; b->last_n_end = n_end; b->have_last = 1;
    leap_check(b);
}

int dcfbits_push(dcfbits_t *b, const dcf_t *d, float i, float q, uint64_t n, int valid)
{
    if (!d->have_mark) return 0;
    int p = (int)((n + DCF_SPS - d->mark) % DCF_SPS);      /* position in the DCF77 second, 0 = drop */
    float a = d->amp;
    if (valid && !d->amp_low) {
        if (p >= 20 && p < 180) { b->am0 += i / a; b->n0++; }        /* 10..90 ms: always reduced (not in s59) */
        else if (p >= 220 && p < 380) { b->am1 += i / a; b->n1++; }  /* 110..190 ms: reduced only for bit 1 */
        else if (p >= 600 && p < 1800) { b->ref += i / a; b->nr++; b->ii2 += (i / a) * (i / a); b->nii++; } /* 300..900 ms: full carrier */
        b->qq2 += (q / a) * (q / a); b->nqq++;
        if (d->pm_sigma > DCF_PM_MIN) {                               /* phase code: known chips, inverted for 1 */
            float s = ((float)p - d->pm_lag_ms * 2.0f + 0.5f) / DCF_SPS - 0.2f;
            if (s >= 0) {
                int c = (int)floorf(s * 77500.0f / 120.0f);
                if (c < 512) { b->pm += (dcf_prn_bits[c] ? -q : q) / a; b->npm++; }
            }
        }
    }
    if (p != DCF_SPS - 1) return 0;
    /* end of a DCF77 second */
    int done = 0;
    if (b->n0 > 100 && b->n1 > 100 && b->nr > 600) {
        float am0 = b->am0 / b->n0, am1 = b->am1 / b->n1, ref = b->ref / b->nr;
        float pm = b->npm > 800 ? b->pm / b->npm : 0;
        int sm = -1;
        if (d->have_minute) {
            uint64_t sd = (n - d->mark) / DCF_SPS;               /* this DCF77 second on the LSE scale */
            sm = (int)((sd + 60 - (uint64_t)d->minute_s - 1) % 60);
        }
        /* statistics from seconds that are clearly not second 59 */
        if (sm != 59 && am0 < 0.5f * ref) {
            float mid = 0.5f * (ref + b->lev_red);
            float lev = am1 < mid ? b->lev_red : ref;              /* decision-directed AM noise */
            b->lev_red += 0.02f * (am0 - b->lev_red);
            b->var_am += 0.02f * ((am1 - lev) * (am1 - lev) - b->var_am);
            if (pm != 0) {
                b->amp_pm += 0.02f * (fabsf(pm) - b->amp_pm);
                float e = fabsf(pm) - b->amp_pm;
                b->var_pm += 0.02f * (e * e - b->var_pm);
            }
            b->nsec_stats++;
        }
        if (sm >= 0 && sm < 59 && b->nsec_stats > 30 && b->nii > 100 && b->nqq > 1000) {
            /* noise per sample from this second's samples: in-phase around its mean (300..900 ms),
               quadrature (the PM part, ~0.07 of the carrier power, is small against the noise) */
            float vi = b->ii2 / b->nii - ref * ref; if (vi < 1e-6f) vi = 1e-6f;
            float vq = b->qq2 / b->nqq;              if (vq < 1e-6f) vq = 1e-6f;
            /* AM: am1 is the mean of n1 samples at level ref (bit 0) or lev_red (bit 1) */
            float s2 = vi / b->n1;
            b->z_am[sm] = ((am1 - b->lev_red) * (am1 - b->lev_red) - (am1 - ref) * (am1 - ref)) / (2 * s2);
            /* PM: seconds 0..9 are always inverted (bit 1), 10..14 never (bit 0) - 15 known bits per
               minute give the polarity and the amplitude; seconds 15..58 carry the same bits as AM */
            if (sm < 15) {
                if (pm != 0) {
                    float e = sm >= 10 ? pm : -pm;                 /* > 0 if the polarity is +1 */
                    b->pm_sign_votes += e > 0 ? 1 : -1;
                    b->pm_known += e; b->pm_known_n++;
                    if (b->pm_known_n >= 15) {                     /* amplitude from the known bits */
                        float m = fabsf(b->pm_known / b->pm_known_n);
                        if (m > 0.05f && m < 0.6f) b->amp_pmk += 0.2f * (m - b->amp_pmk);
                        b->pm_known = 0; b->pm_known_n = 0;
                    }
                    if (b->pm_sign_votes > 200) b->pm_sign_votes = 200;
                    if (b->pm_sign_votes < -200) b->pm_sign_votes = -200;
                }
                pm = 0;
            }
            int sgn = b->pm_sign_votes > 20 ? 1 : b->pm_sign_votes < -20 ? -1 : 0;
            b->pm_raw[sm] = sgn * pm;
            b->z_pm[sm] = (sgn && pm != 0) ? 2 * b->amp_pmk * sgn * pm / (vq / b->npm) : 0;
            b->have[sm] = 1;
            if (sm == 58) {                                        /* the minute is complete */
                int k, all = 1;
                for (k = 0; k < 59; k++) if (!b->have[k]) all = 0;
                if (all) { decode(b, n); done = 1; }
                memset(b->have, 0, sizeof b->have);
            }
        }
    }
    b->am0 = b->am1 = b->ref = b->pm = 0; b->n0 = b->n1 = b->nr = b->npm = 0;
    b->ii2 = b->qq2 = 0; b->nii = b->nqq = 0;
    return done;
}
