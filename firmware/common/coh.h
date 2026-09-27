/*
 * Coherent carrier tracker, the same code for e-CzasPL (225 kHz) and DCF77 (77.5 kHz).
 * Each station has its own instance; the two never exchange data, so either one keeps
 * working if the other station is off the air or its signal is lost.
 *
 * Input: complex baseband at COH_FS (2 kHz), produced by a mixer that is phase-locked
 * to TRUE time (the LSE crystal on the NUCLEO), so a carrier sits within a few Hz of 0
 * (the crystal's own error) and does not wander with the MCU clock.
 *
 *  1. SEARCH: FFT of `acq_n` samples decimated by `acq_dec` -> strongest line in range.
 *     eCzas: 500 Hz x 1024 (2 s, 0.5 Hz bins); DCF77: 4 Hz x 512 (128 s, 0.008 Hz bins).
 *  2. PULL / TRACK: second-order PLL in baseband. Each update uses the sum of `integ`
 *     samples: eCzas 4 (2 ms, decision-directed on the two data levels, ~1 Hz loop);
 *     DCF77 20000 (10 s, plain phase detector, ~0.01 Hz loop).
 *  3. Lost for `lost_s` seconds -> SEARCH again.
 *
 * Phases are in cycles, frequencies in Hz of true time.
 */
#ifndef COH_H
#define COH_H

#include <stdint.h>

#define COH_FS      2000.0f          /* input rate, samples per second of true time */
#define COH_ACQ_MAX 1024             /* largest search FFT */

typedef enum { COH_PLAIN = 0, COH_ECZAS = 1 } coh_mode_t;
typedef enum { COH_SEARCH = 0, COH_PULL, COH_TRACK } coh_state_t;

typedef struct {
    coh_mode_t mode;
    int    integ;                   /* input samples per loop update */
    float  bw_pull, bw_track;       /* loop noise bandwidths [Hz] */
    int    pull_upd;                /* updates spent pulling in before tracking */
    int    acq_dec, acq_n;          /* search: decimation and FFT length */
    float  max_hz;                  /* search range +- [Hz] */
    float  lock_deg;                /* loop noise below this = locked */
    float  lost_s;                  /* unlocked this long -> search again */
} coh_cfg_t;

typedef struct {
    coh_cfg_t c;
    coh_state_t state;
    double nco_ph;                  /* cycles, unwrapped */
    double hz;                      /* loop frequency [Hz] */
    float  g_f, g_p;                /* loop gains for the current state */
    int    timer;                   /* updates in the current state */
    float  acc_re, acc_im; int acc_n;
    float  lvl0;                    /* eCzas '0' level [cycles], negative */
    float  err_avg;                 /* IIR of |phase error| [cycles] */
    float  unlocked_s;              /* seconds with a noisy loop */
    /* search */
    float  aq_re[COH_ACQ_MAX], aq_im[COH_ACQ_MAX];
    float  aq_sr, aq_si; int aq_k, aq_n;
    float  last_snr_db;             /* line / mean power of the last search */
    int    searches;
    float  excl[4]; int n_excl;     /* frequencies rejected by the caller (not this carrier) */
    /* report-period statistics */
    double s_re, s_im, s_dif, s_hz; float last_re, last_im; long s_n, s_upd;
} coh_trk_t;

typedef struct {
    float  cn0_dbhz;                /* carrier / noise density over the period */
    float  freq_hz;                 /* mean loop frequency over the period */
    double phase_cyc;               /* NCO phase at the end, unwrapped */
    float  err_deg;                 /* loop noise */
    int    state;                   /* coh_state_t */
    int    searches;
} coh_report_t;

void coh_init(coh_trk_t *t, const coh_cfg_t *cfg);
/* Push one input sample. The derotated sample (carrier at 0 phase) goes to *dr, *di.
 * Returns 1 after a loop update; then *ir, *ii hold that update's derotated sum. */
int  coh_push(coh_trk_t *t, float re, float im, float *dr, float *di, float *ir, float *ii);
void coh_report(coh_trk_t *t, coh_report_t *r);   /* and start a new period */
/* eCzas: the '0' level measured by the frame decoder on a decoded frame [cycles, < 0] */
void coh_level_hint(coh_trk_t *t, float lvl0_cycles);
/* The line being tracked is not the wanted carrier (e.g. DCF77: no second marks): never
 * pick it again (+-width) and search anew. */
void coh_reject(coh_trk_t *t, float width_hz);

#endif
