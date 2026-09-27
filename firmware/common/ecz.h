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

#endif
