/* e-CzasPL preamble detector; template, correlator and detector as in the eCzas
 * firmware's dsp.c (build_template, correlate, detector), on a phase stream that now
 * comes from the coherent carrier tracker instead of the SI4735-audio PLL. */
#include <math.h>
#include <string.h>
#include "ecz.h"

static int16_t tpl[TPL_LEN];
static float tpl_norm;
static const uint8_t PREAMBLE[PREAMBLE_BITS] = {
    0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1, 0,1,1,0,0,0,0,0, 1,0,1
};

static void build_template(void)
{
    int16_t v[TPL_LEN];
    int32_t s = 0; int64_t tt = 0; uint8_t prev = 1; int k, i, n = 0;
    for (k = 0; k < PREAMBLE_BITS; k++) {
        int16_t a = prev ? 0 : -16, c = PREAMBLE[k] ? 0 : -16;
        for (i = 0; i < SPB; i++) {
            int16_t f = (int16_t)(2 * i + 1);
            if (f > 2 * RAMP_BLOCKS) f = 2 * RAMP_BLOCKS;
            v[n] = (int16_t)(a + (c - a) * f / (2 * RAMP_BLOCKS));
            s += v[n++];
        }
        prev = PREAMBLE[k];
    }
    for (n = 0; n < TPL_LEN; n++) { tpl[n] = (int16_t)(TPL_LEN * v[n] - s); tt += (int32_t)tpl[n] * tpl[n]; }
    tpl_norm = (float)tt;
}

void ecz_init(ecz_t *e)
{
    memset(e, 0, sizeof *e);
    build_template();
}

static int16_t correlate(const ecz_t *d, uint32_t start)
{
    int32_t num = 0, e; int64_t en; float c; int k;
    for (k = 0; k < TPL_LEN; k++) num += (int32_t)tpl[k] * (d->ring[(start + k) & (DSP_RING - 1)] >> 4);
    if (num <= 0) return 0;
    en = (int64_t)TPL_LEN * d->sum_x2 - (int64_t)d->sum_x * d->sum_x;
    if (en <= 0) return 0;
    c = (float)num / sqrtf(tpl_norm * (float)en / TPL_LEN);
    e = (int32_t)(c * 1024.0f);
    return (int16_t)(e > 1024 ? 1024 : e);
}

static void detector(ecz_t *d)
{
    uint64_t n = d->block, s; int16_t c;
    if (n < TPL_LEN) return;
    s = n - (TPL_LEN - 1);
    c = correlate(d, (uint32_t)s);
    switch (d->det_state) {
    case 0:
        if (c >= DET_THRESHOLD_Q10) {
            d->det_state = 1; d->det_count = 0; d->c_best = c; d->c_best_prev = d->c_prev;
            d->best_start = s; d->best_next_pending = 1;
        }
        break;
    case 1:
        if (d->best_next_pending) { d->c_best_next = c; d->best_next_pending = 0; }
        if (c > d->c_best) { d->c_best_prev = d->c_prev; d->c_best = c; d->best_start = s; d->best_next_pending = 1; }
        if (++d->det_count >= TPL_LEN && !d->best_next_pending) d->det_state = 2;
        break;
    default:
        if (n >= d->best_start + CAND_LEN - CAND_PRE - 1) {
            if (!d->cand_ready) {
                dsp_cand_t *cd = &d->cand;
                uint32_t first = (uint32_t)(d->best_start - CAND_PRE);
                int32_t den = 2L * (d->c_best_prev - 2L * d->c_best + d->c_best_next), frac = 0; int k;
                if (den < 0) frac = ((int32_t)(d->c_best_prev - d->c_best_next) << 15) / den;
                if (frac > 16384) frac = 16384;
                if (frac < -16384) frac = -16384;
                for (k = 0; k < CAND_LEN; k++) cd->ph[k] = d->ring[(first + k) & (DSP_RING - 1)];
                cd->start_block = d->best_start; cd->frac_q15 = (int16_t)frac; cd->corr_q10 = d->c_best;
                d->cand_ready = 1;
            } else d->cand_overrun++;
            d->det_state = 0;
        }
        break;
    }
    d->c_prev = c;
}

void ecz_push(ecz_t *d, int16_t ph)
{
    uint32_t idx; int16_t xs, old;
    d->block++;
    idx = (uint32_t)d->block & (DSP_RING - 1);
    d->ring[idx] = ph;
    xs = ph >> 4;
    d->sum_x += xs; d->sum_x2 += (int32_t)xs * xs;
    if (d->block >= TPL_LEN) {
        old = d->ring[(idx - TPL_LEN) & (DSP_RING - 1)] >> 4;
        d->sum_x -= old; d->sum_x2 -= (int32_t)old * old;
    }
    detector(d);
}
