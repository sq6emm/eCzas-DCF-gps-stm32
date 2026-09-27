/*
 * DCF77 timing on its own (no e-CzasPL input): works on the carrier-derotated 2 kHz baseband
 * of the DCF77 carrier tracker (coh.c). Time base = the 2 kHz sample count, i.e. true (LSE)
 * time; one "second" = 2000 samples.
 *
 *  - second mark: in-phase signal folded modulo 1 s, correlated with the always-present
 *    100 ms carrier reduction (the 100..200 ms part depends on the bit, taken as half)
 *  - minute: per second-of-minute the dip depth; second 59 has no reduction
 *  - phase code: the seconds whose code sign is fixed (0-9 inverted = minute marker,
 *    10-14 not inverted) folded coherently and correlated with the exact PTB sequence
 *    (PTB-Mitteilungen 114 (2004) 4.3); running over ~1 h (factor DCF_KEEP per block)
 */
#ifndef DCF_H
#define DCF_H

#include <stdint.h>

#define DCF_SPS     2000                /* samples per second */
#define DCF_BLOCK_S 600                 /* report period [s] */
#define DCF_KEEP    0.85f               /* weight of the previous blocks in the running sums */
#define DCF_LAGW    120                 /* phase-code search +-60 ms around the second mark */

typedef struct {
    /* input bookkeeping */
    uint64_t n;                         /* samples seen */
    float    amp;                       /* running carrier amplitude (in-phase mean) */
    /* second-mark fold (this block) and running */
    float    yf[DCF_SPS];
    float    yr[DCF_SPS];
    int      nsec;                      /* complete seconds in this block */
    /* per second-of-minute dip depth, running */
    float    dip[60], dipn[60];
    float    sec_y0, sec_y1; int sec_k0, sec_k1;   /* current second's dip / level sums */
    /* phase code: fold of the fixed-sign seconds, running */
    float    pmf[DCF_SPS + 2 * DCF_LAGW];
    float    pmn;
    float    qbuf[DCF_SPS + 2 * DCF_LAGW];         /* quadrature of the current second (+margins) */
    /* results (valid after the first blocks) */
    int      mark;                      /* second mark: sample index within the LSE second */
    float    mark_sigma;
    int      minute_s;                  /* which LSE second (mod 60) is DCF77 second 59, -1 = unknown */
    float    minute_sigma;
    float    pm_lag_ms;                 /* phase-code start relative to the second mark + 200 ms */
    float    pm_sigma;
    int      have_mark, have_minute;
} dcf_t;

void dcf_init(dcf_t *d);
/* one derotated sample (carrier on the real axis); `valid` = carrier tracker tracking */
void dcf_push(dcf_t *d, float i, float q, int valid);
/* after every DCF_BLOCK_S seconds (d->n % (DCF_SPS*DCF_BLOCK_S) == 0) */
int  dcf_block_ready(const dcf_t *d);
void dcf_block(dcf_t *d);               /* evaluate the block, update results */

#endif
