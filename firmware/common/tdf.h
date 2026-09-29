/*
 * TDF / ALS162 (Allouis, 162 kHz) time-code decoder - portable C, the method of tools/tdf/tdf_decode3.py.
 *
 * Input: the carrier tracker's derotated 2 kHz complex samples (as dcf.c), TDF at ~0 Hz.
 * Signal (measured 28 Sep 2026): +-0.8 rad phase modulation; per second a quiet ~100 ms, then one
 * ~100 ms phase cycle (bit 0) or two (bit 1); the minute-marker second has none; the rest of the
 * second carries a pseudo-random phase modulation (not used). Time code in the DCF77 layout
 * (bits 17/18 CEST/CET, 20 start, BCD 21-58 with three even parities), for the NEXT minute, French
 * legal time.
 *
 *  1. 1 kHz (pairs averaged); ring of 2 s
 *  2. second start: matched filter with the learned bit-0 burst, |corr|^2 folded modulo 1 s
 *     (running, ~100 s memory) -> argmax
 *  3. each second (window -100..+219 ms): complex least-squares fit u = g exp(jT) with the shapes for
 *     bit 0, bit 1 and none (g absorbs the phase the pseudo-random part leaves and fading);
 *     LLR(bit) = (err0 - err1) / sigma^2
 *  4. minute marker: "none fits best" score folded modulo 60 s (~10 min memory) -> argmax
 *  5. at each marker: the 59 bits since the previous one, parity repair (least confident bit per
 *     failing group), BCD / range checks; confirmed when the previous decoded minute is exactly one
 *     minute earlier;
 *  6. otherwise, after a confirmed minute: the soft bits are scored against the frame expected from
 *     the reference (+ the elapsed minutes) and against the same frame +-1, +-2 minutes; accepted
 *     ("confirmed by the expected frame") when the score and its lead over the others are high enough.
 */
#ifndef TDF_H
#define TDF_H

#include <stdint.h>

#define TDF_RING 2048                     /* 1 kHz samples (power of 2) */

enum { TDF_NONE = 0, TDF_FAILED, TDF_UNCONFIRMED, TDF_CONFIRMED, TDF_PREDICTED };

typedef struct {
    /* input */
    uint64_t n2;                          /* 2 kHz samples pushed */
    float    pr, pi; int pv;              /* first sample of the current pair */
    uint64_t n;                           /* 1 kHz samples */
    float    ur[TDF_RING], ui[TDF_RING];
    /* second start */
    float    fold[1000];                  /* matched-filter power folded modulo 1 s */
    int      start;                       /* second start, 1 kHz sample index modulo 1000; -1 = not yet */
    float    start_q;                     /* fold peak / fold median */
    uint64_t next_sec;                    /* 1 kHz index at which the next second is evaluated */
    /* seconds */
    uint64_t sec;                         /* seconds evaluated */
    float    llr[60], mscore[60];         /* by second index modulo 60 */
    float    mfold[60];                   /* marker score folded modulo 60 */
    float    sig2;                        /* noise per complex sample (running) */
    int      phase60;                     /* second index modulo 60 of the marker; -1 = not yet */
    /* result of the last decode */
    int      status, flips;
    int      year, month, day, hour, minute, cest;
    int64_t  utc_min;                     /* the decoded minute (the one that starts after the marker), minutes since 2000 UTC */
    int      have_prev; int64_t prev_utc;
    /* confirmation by the expected frame (as dcfbits): reference = the last confirmed minute */
    int      have_ref, ref_cest; int64_t ref_utc; uint64_t ref_sec;
    int      have_cand, cand_cest; int64_t cand_utc; uint64_t cand_sec;   /* an unconfirmed decode, to be proven by the next minute */
    float    pred_score, pred_margin;
    unsigned long n_decoded, n_confirmed, n_failed, n_predicted;
} tdf_t;

void tdf_init(tdf_t *t);
/* one derotated 2 kHz sample; valid = carrier tracker locked. Returns 1 when a minute was just
   evaluated (t->status: TDF_FAILED / TDF_UNCONFIRMED / TDF_CONFIRMED) */
int  tdf_push(tdf_t *t, float re, float im, int valid);

#endif
