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

/* Frame-time offset added to every frame time; the reported second = the START of the frame's first linear
   phase ramp (GUM: "transmission starts at the beginning of the second"; the '0' of 1-0-1 starts exactly
   0.5 s later). The core's template and timing refinement model each bit change as a RAMP_BLOCKS (8 =
   16 ms) ramp starting at the bit edge, but the transmitted ramp is longer: 18.6 ms fitted on the IC-7610
   (1 Oct 2026, 60 frames), 19 ms according to GUM (Sadowski 2025, Metrol. Meas. Syst. 32(4),
   DOI 10.24425/mms.2025.155800). A too short model centres on the real ramp and puts its start late:
   measured on the NUCLEO's own dumps (tools/nucleo_timing_check.py, 18.6 ms model, five 10-min blocks
   1 Oct 16:07-16:57): firmware - true ramp start = +1.38 +- 0.04 ms -> -1380.
   History: 75340d9 (30 Sep) set 7400 with a wrong explanation ("the tracker switches in ~5 ms"); 6bd5276
   set 0 assuming a 16.6 ms ramp. For the ramp-middle convention add ~9300 (half of 18.6 ms). */
#ifndef ECZ_TEMPLATE_LAG_US
#define ECZ_TEMPLATE_LAG_US (-1380)
#endif
#endif
