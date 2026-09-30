/*
 * e-CzasPL frame detector on the coherent receiver: carrier-relative phase at 500 Hz
 * (one sample per loop update of the eCzas carrier tracker) -> preamble correlator ->
 * frame candidates for the unchanged frame.c / timekeeper.c of the eCzas firmware.
 * The correlator and detector are those of the eCzas firmware's dsp.c.
 */
#ifndef ECZ_H
#define ECZ_H

#include <stdint.h>
#include "dsp.h"                    /* dsp_cand_t, DSP_RING, TPL_LEN, CAND_* (types only) */

typedef struct {
    int16_t  ring[DSP_RING];
    uint64_t block;                 /* 500 Hz samples processed */
    int32_t  sum_x;
    uint32_t sum_x2;
    uint8_t  det_state;
    uint16_t det_count;
    int16_t  c_prev, c_best, c_best_prev, c_best_next;
    uint64_t best_start;
    uint8_t  best_next_pending;
    volatile uint8_t cand_ready;
    uint8_t  cand_overrun;
    dsp_cand_t cand;
} ecz_t;

void ecz_init(ecz_t *e);
void ecz_push(ecz_t *e, int16_t ph);        /* phase, 65536 = 360 deg */

/* Frame-time correction for this receiver: the core's template and timing refinement model each bit
   transition as a RAMP_BLOCKS (8 = 16 ms) ramp starting at the bit edge - the slew of the SI4735 + audio
   PLL chain. The coherent tracker here switches in ~5 ms, so the template lands ~7.4 ms early: measured
   30 Sep 2026 on the NUCLEO's own dumps (tools/nucleo_timing_check.py: -7.31 ms on the board, host/cohsim -c:
   -7.53 ms). Kept at RAMP_BLOCKS 8 (lowest timing jitter) and corrected here; added to every frame time. */
#ifndef ECZ_TEMPLATE_LAG_US
#define ECZ_TEMPLATE_LAG_US 7400
#endif
#endif
