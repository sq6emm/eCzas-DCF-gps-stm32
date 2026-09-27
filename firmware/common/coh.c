/* Coherent carrier tracker, see coh.h. */
#include <math.h>
#include <string.h>
#include "coh.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#define TWO_PI 6.28318530717958647692

static void fft(float *re, float *im, int n)     /* in place, radix 2, n = 2^k */
{
    int i, j, k, m;
    for (i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (m = 2; m <= n; m <<= 1) {
        float wr = cosf((float)(-TWO_PI / m)), wi = sinf((float)(-TWO_PI / m));
        for (k = 0; k < n; k += m) {
            float cr = 1, ci = 0;
            for (j = 0; j < m / 2; j++) {
                float ur = re[k + j], ui = im[k + j];
                float vr = re[k + j + m / 2] * cr - im[k + j + m / 2] * ci;
                float vi = re[k + j + m / 2] * ci + im[k + j + m / 2] * cr;
                re[k + j] = ur + vr; im[k + j] = ui + vi;
                re[k + j + m / 2] = ur - vr; im[k + j + m / 2] = ui - vi;
                float t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t;
            }
        }
    }
}

static void set_gains(coh_trk_t *t, float bw)
{
    /* second order, damping 0.707: noise bandwidth Bn = 0.53 wn */
    float T = t->c.integ / COH_FS, wn = bw / 0.53f;
    t->g_f = wn * wn * T;              /* Hz per cycle of error */
    t->g_p = 2 * 0.707f * wn * T;      /* cycles per cycle of error */
}

static void start_search(coh_trk_t *t)
{
    t->state = COH_SEARCH;
    t->hz = 0;
    t->aq_sr = t->aq_si = 0; t->aq_k = t->aq_n = 0;
    t->timer = 0; t->unlocked_s = 0; t->err_avg = 0.25f;
}

void coh_init(coh_trk_t *t, const coh_cfg_t *cfg)
{
    memset(t, 0, sizeof *t);
    t->c = *cfg;
    t->lvl0 = -45.0f / 360;
    start_search(t);
}

static void search_done(coh_trk_t *t)
{
    int n = t->c.acq_n, k, best = -1;
    float fs = COH_FS / t->c.acq_dec, sum = 0, p[3];
    fft(t->aq_re, t->aq_im, n);
    for (k = 0; k < n; k++) {
        float f = (k < n / 2 ? k : k - n) * fs / n, pw = t->aq_re[k] * t->aq_re[k] + t->aq_im[k] * t->aq_im[k];
        sum += pw;
        if (fabsf(f) <= t->c.max_hz && (best < 0 || pw > t->aq_re[best] * t->aq_re[best] + t->aq_im[best] * t->aq_im[best]))
            best = k;
    }
    t->searches++;
    for (k = 0; k < 3; k++) {
        int j = (best - 1 + k + n) % n;
        p[k] = t->aq_re[j] * t->aq_re[j] + t->aq_im[j] * t->aq_im[j];
    }
    t->last_snr_db = 10 * log10f(p[1] / (sum / n) + 1e-20f);
    if (t->last_snr_db < 12.0f) { start_search(t); return; }       /* no clear line: search again */
    {
        float den = p[0] - 2 * p[1] + p[2], d = den != 0 ? 0.5f * (p[0] - p[2]) / den : 0;
        t->hz = ((best < n / 2 ? best : best - n) + d) * fs / n;
    }
    t->state = COH_PULL; t->timer = 0; t->unlocked_s = 0;
    set_gains(t, t->c.bw_pull);
}

int coh_push(coh_trk_t *t, float re, float im, float *dr, float *di, float *ir, float *ii)
{
    double fr;
    float c, s, zr, zi;

    /* derotate by the NCO (the carrier's current frequency and phase) */
    t->nco_ph += t->hz / COH_FS;
    fr = t->nco_ph - floor(t->nco_ph);
    c = cosf((float)(TWO_PI * fr)); s = sinf((float)(TWO_PI * fr));
    zr = re * c + im * s; zi = im * c - re * s;
    *dr = zr; *di = zi;

    /* statistics: carrier = mean of the derotated samples, noise from first differences */
    t->s_re += zr; t->s_im += zi;
    t->s_dif += (zr - t->last_re) * (zr - t->last_re) + (zi - t->last_im) * (zi - t->last_im);
    t->last_re = zr; t->last_im = zi; t->s_n++;

    /* updates stay on a fixed grid of `integ` samples in every state, so the caller's
     * sample count (time) and the update count never slip against each other */
    t->acc_re += zr; t->acc_im += zi;
    if (++t->acc_n < t->c.integ) {
        if (t->state == COH_SEARCH) goto search;
        return 0;
    }
    if (t->state == COH_SEARCH) {
        *ir = t->acc_re; *ii = t->acc_im;
        t->acc_re = t->acc_im = 0; t->acc_n = 0;
        search:
        t->aq_sr += zr; t->aq_si += zi;
        if (++t->aq_k == t->c.acq_dec) {
            t->aq_re[t->aq_n] = t->aq_sr; t->aq_im[t->aq_n] = t->aq_si;
            t->aq_sr = t->aq_si = 0; t->aq_k = 0;
            if (++t->aq_n == t->c.acq_n) search_done(t);
        }
        return t->acc_n == 0;
    }
    {
        float T = t->c.integ / COH_FS, e, ph = atan2f(t->acc_im, t->acc_re) / (float)TWO_PI, a;
        if (t->c.mode == COH_ECZAS) {
            /* decision-directed on the two data levels (idle / bit 1 = 0, bit 0 = lvl0).
             * lvl0 is learned from bit centres only: the 16 ms slews between the levels
             * would pull it towards 0 and the loop would then follow the data. */
            if (ph < t->lvl0 / 2) {
                e = ph - t->lvl0;
                if (t->state == COH_TRACK && t->err_avg * 360 < 15.0f && ph < t->lvl0 * 0.75f) {
                    t->lvl0 += (ph - t->lvl0) * (1.0f / 256);
                    if (t->lvl0 > -30.0f / 360) t->lvl0 = -30.0f / 360;
                    if (t->lvl0 < -60.0f / 360) t->lvl0 = -60.0f / 360;
                }
            } else e = ph;
        } else e = ph;
        t->hz += t->g_f * e;
        t->nco_ph += t->g_p * e;
        if (t->hz > t->c.max_hz * 1.2f) t->hz = t->c.max_hz * 1.2f;
        if (t->hz < -t->c.max_hz * 1.2f) t->hz = -t->c.max_hz * 1.2f;
        a = T / (T * 3 > 1.0f ? T * 3 : 1.0f);             /* ~1 s (eCzas) / ~30 s (DCF77) */
        t->err_avg += (fabsf(e) - t->err_avg) * a;
        t->s_hz += t->hz; t->s_upd++;
        *ir = t->acc_re; *ii = t->acc_im;
        t->acc_re = t->acc_im = 0; t->acc_n = 0;

        t->timer++;
        if (t->state == COH_PULL && t->timer >= t->c.pull_upd) {
            t->state = COH_TRACK; t->timer = 0; set_gains(t, t->c.bw_track);
        }
        if (t->err_avg * 360 > t->c.lock_deg) {
            t->unlocked_s += T;
            if (t->unlocked_s > t->c.lost_s) start_search(t);
        } else t->unlocked_s = 0;
    }
    return 1;
}

void coh_report(coh_trk_t *t, coh_report_t *r)
{
    double n = t->s_n > 0 ? (double)t->s_n : 1, cr = t->s_re / n, ci = t->s_im / n;
    double noise = t->s_dif / (2 * n);                    /* per complex sample */
    r->cn0_dbhz = (float)(10 * log10((cr * cr + ci * ci) * COH_FS / (noise + 1e-30) + 1e-30));
    r->freq_hz = t->s_upd ? (float)(t->s_hz / t->s_upd) : (float)t->hz;
    r->phase_cyc = t->nco_ph;
    r->err_deg = t->err_avg * 360;
    r->state = t->state;
    r->searches = t->searches;
    t->s_re = t->s_im = t->s_dif = t->s_hz = 0; t->s_n = t->s_upd = 0;
}

void coh_level_hint(coh_trk_t *t, float lvl0)
{
    if (lvl0 > -60.0f / 360 && lvl0 < -20.0f / 360) t->lvl0 += (lvl0 - t->lvl0) * 0.5f;
}
