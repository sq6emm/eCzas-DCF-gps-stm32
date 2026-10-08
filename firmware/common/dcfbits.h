/*
 * DCF77 time code, decoded every minute (next to dcf.c, which measures the timing).
 *
 * Every second carries one bit twice:
 *   AM: the carrier drops to ~15 % for 100 ms (bit 0) or 200 ms (bit 1) at the start of the second;
 *       second 59 has no drop (minute marker).
 *   PM: 512 chips of a known pseudo-random sequence from 200 ms on, inverted for bit 1
 *       (PTB-Mitteilungen 114 (2004)); about 4x the energy of the AM bit.
 * Per second both are turned into soft values (z-scores) and added; the 59 bits of a minute are
 * checked (bit 20 = 1, parities P1 P2 P3, one of CEST/CET, valid BCD). A parity group that fails
 * may have its least reliable bit flipped once. A decoded minute is CONFIRMED only when it is
 * exactly the previous decoded minute plus the minutes elapsed; nothing from e-CzasPL is used.
 * The code sent during a minute is the time of the NEXT minute (valid at the following second 0).
 *
 * Needs dcf.c's second mark (have_mark) and minute (have_minute); uses its phase-code timing
 * (pm_lag_ms) when pm_sigma > DCF_PM_MIN, otherwise AM only.
 */
#ifndef DCFBITS_H
#define DCFBITS_H

#include <stdint.h>
#include "dcf.h"

typedef enum { DCFT_NONE = 0, DCFT_FAILED, DCFT_UNCONFIRMED, DCFT_CONFIRMED, DCFT_PREDICTED } dcft_status_t;
/* PREDICTED: the minute's soft bits fit the time expected from the last confirmed minute clearly
   better than the neighbouring minutes (+-1, +-2) - confirmed without a standalone decode */

typedef struct {
    /* the current second */
    float am0, am1, ref; int n0, n1, nr;
    float pm; int npm;
    float ii2, qq2; int nii, nqq;           /* sample energies: in-phase over 300..900 ms, quadrature all second */
    /* running levels and noise (normalised to the full carrier level) */
    float lev_red;                        /* reduced level (0..100 ms of seconds 0..58), ~0.15 */
    float var_am, var_pm, amp_pm;         /* (kept for the report) */
    float amp_pmk;                        /* PM amplitude (normalised), learned from decoded minutes */
    int   nsec_stats;
    int   pm_sign_votes;                 /* PM polarity from the known seconds 0..14 (clamped +-200) */
    float pm_known; int pm_known_n;       /* PM of the known seconds, for the amplitude */
    /* the minute being collected */
    float z_am[60], z_pm[60];             /* log-likelihood ratios, > 0 = bit 0 */
    float pm_raw[60];                     /* PM correlation per second (for the amplitude update) */
    uint8_t have[60];
    /* result of the last decode (valid after ready = 1) */
    int   ready;
    dcft_status_t status;
    int   year, month, day, weekday, hour, minute, cest;   /* local time (CET / CEST) as sent */
    int64_t utc_min;                      /* minutes since 2000-01-01 00:00 UTC of that time */
    int   flips, bits_pm, am_pm_agree;    /* repaired bits; seconds with PM; AM and PM hard bits equal */
    float weakest;                        /* smallest |z| of bits 20..58 after repair */
    uint64_t n_end;                       /* sample count at the end of second 58 of the decoded minute */
    /* confirmation */
    int64_t last_utc_min; uint64_t last_n_end; int have_last;   /* last standalone decode */
    int64_t ref_utc_min; uint64_t ref_n_end; int have_ref; /* last confirmed minute */
    float pred_score, pred_margin;        /* expected-frame fit of the last minute and its lead */
    int   leap_next;                      /* the minute just decoded is a leap minute (61 s): announced (bit 19)
                                             and the next minute is 00:00 UTC on the 1st - see dcf_leap_second */
    unsigned long n_predicted;
    unsigned long n_decoded, n_confirmed, n_failed;
} dcfbits_t;

void dcfbits_init(dcfbits_t *b);
/* drop the minute being collected (after dcf_restart: its seconds were on another line or mark);
   levels, polarity, counters and the last confirmed minute stay */
void dcfbits_restart(dcfbits_t *b);
/* one 2 kHz sample: i = in-phase (carrier on the real axis, as for dcf_push), q = quadrature;
   n = dcf's sample count of THIS sample; only samples dcf_push found usable (d->amp_low == 0) count.
   Returns 1 when a minute was just decoded (see b->status). */
int  dcfbits_push(dcfbits_t *b, const dcf_t *d, float i, float q, uint64_t n, int valid);

#endif
