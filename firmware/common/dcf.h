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
#ifndef DCF_KEEP                        /* (overridable for the host tuning bench) */
#define DCF_KEEP    0.85f               /* weight of the previous blocks in the running sums */
#endif
#ifndef DCF_MARK_MIN
#define DCF_MARK_MIN 6.0f               /* second mark accepted above this many sigma */
#endif
#ifndef DCF_PM_MIN
#define DCF_PM_MIN  8.0f                /* phase-code time used above this many sigma (5-6.5 sigma gave
                                           0.6-0.8 ms errors on the Kiwi bench, 28 Sep) */
#endif
#ifndef DCF_MIN_MIN
#define DCF_MIN_MIN 5.0f                /* minute accepted above this many sigma */
#endif
#define DCF_LAGW    120                 /* phase-code search +-60 ms around the second mark */
#ifndef DCF_AMP_MIN
#define DCF_AMP_MIN 0.3f                /* samples count only while the carrier amplitude is above this
                                           fraction of its reference level (see amp_ref): in a fade the
                                           amplitude goes to ~0 and dividing by it filled the running sums
                                           with huge values for hours (7 Oct 2026: minute sigma 3678, no
                                           second marks on the returned carrier, 0 Hz rejected) */
#endif

typedef struct {
    /* input bookkeeping */
    uint64_t n;                         /* samples seen */
    float    amp;                       /* running carrier amplitude (in-phase mean, ~20 s) */
    float    amp_ref;                   /* its reference level: follows a rise in ~20 s, a fall over ~1 h */
    uint32_t amp_n;                     /* valid samples since the start (amp is a plain mean until 20 s) */
    int      amp_low;                   /* this sample: not valid, or amp < DCF_AMP_MIN * amp_ref - not used */
    uint32_t good_run;                  /* consecutive usable samples (a dip / phase-code window needs all) */
    /* second-mark fold (this block) and running */
    float    yf[DCF_SPS];
    float    yr[DCF_SPS];
    float    nval;                      /* usable samples in this block's fold (yf holds i / amp) */
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
    float    mark_frac;                 /* sub-sample part of the mark (-0.5 .. 0.5, parabolic), for reports only */
    int      minute_s;                  /* which LSE second (mod 60) is DCF77 second 59, -1 = unknown */
    float    minute_sigma;
    float    pm_lag_ms;                 /* phase-code start relative to the second mark + 200 ms */
    float    pm_sigma;
    int      have_mark, have_minute;
    double   slip;                      /* drift of the DCF77 second through the LSE time scale, samples (fraction kept) */
    int      stage; uint64_t stage_n;   /* dcf_block_step: current step and the sample of step 1 */
    int      pm_block_done;             /* the phase code has been evaluated by a 10-min block */
    int      pm_ref;                    /* phase-code fold anchor (sample in the LSE second): set from the mark once,
                                           then moved only by the drift correction, never by mark noise; -1 = unset */
} dcf_t;

void dcf_init(dcf_t *d);
/* one derotated sample (carrier on the real axis); `valid` = carrier tracker tracking */
void dcf_push(dcf_t *d, float i, float q, int valid);
/* forget everything learned about the carrier (folds, marks, minute, phase code, amplitude), keep the
 * sample count and the block grid: for a new line, so a spur's data never mixes with DCF77's */
void dcf_restart(dcf_t *d);
/* after every DCF_BLOCK_S seconds (d->n % (DCF_SPS*DCF_BLOCK_S) == 0) */
int  dcf_block_ready(const dcf_t *d);
/* evaluate the block, update results. carrier_hz = the DCF77 carrier offset measured by the
 * DCF77 tracker in LSE time: it gives the LSE crystal's rate against DCF77 itself, and the
 * fold of past blocks is shifted by the resulting drift of the DCF77 second (no other input). */
void dcf_block(dcf_t *d, float carrier_hz);
/* The same, spread over four samples DCF_STAGE_GAP apart (the firmware: ~8 ms per step instead of
 * ~24 ms in one sample; the sample ring holds 30 ms). Call every sample; returns 1 on the sample
 * that completes the block (results valid then). */
#define DCF_STAGE_GAP 200               /* samples (0.1 s) */
int  dcf_block_step(dcf_t *d, float carrier_hz);
/* Before the first second marks: look for them in the current block's fold (>= 60 s tracked),
 * accept above min_sigma. Lets DCF77 be verified within a minute or two instead of at the first
 * 10-min block. Returns 1 when marks were found (d->mark, mark_sigma, have_mark set). */
int  dcf_quick_mark(dcf_t *d, float min_sigma);
/* The same for the minute marker (after the marks, until found) and the phase code (after the
 * minute, until the first 10-min block): evaluate the running sums without decaying them. */
int  dcf_quick_minute(dcf_t *d, float min_sigma);
int  dcf_quick_pm(dcf_t *d);

#endif
