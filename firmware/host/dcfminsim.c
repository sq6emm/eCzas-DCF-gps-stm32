/*
 * Host test of the per-minute DCF77 time-code decoder (dcfbits.c) on top of the standalone DCF77
 * receiver (coh.c + dcf.c), the same chain as the NUCLEO.
 *   dcfminsim file.c64 A B
 *     file.c64  2 kHz complex float32 (gaps zero-filled), sample 0 at unix time A, B = seconds per
 *               sample / (1/2000) (1 + crystal error), as dcfsim
 * One line per decoded minute:
 *   MIN n_end utc_of_next_minute_by_samples status decoded_utc_min local_time flips pm_bits agree weakest
 * status: F = failed checks, U = decoded, C = confirmed (previous decoded minute + elapsed minutes)
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "coh.h"
#include "dcf.h"
#include "dcfbits.h"

#ifndef DCF_COH
#define DCF_COH { COH_PLAIN, 20000, 0.03f, 0.01f, 6, 500, 512, 2.0f, 40.0f, 600.0f }   /* as main.c */
#endif

int main(int argc, char **argv)
{
    static coh_trk_t trk; static dcf_t dcf; static dcfbits_t bits;
    if (argc < 4) { fprintf(stderr, "usage: dcfminsim file.c64 A B\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) return 2;
    double A = atof(argv[2]), B = atof(argv[3]);
    coh_cfg_t cfg = DCF_COH;
    coh_init(&trk, &cfg); dcf_init(&dcf); dcfbits_init(&bits);
    /* as the OCXO firmware: DCF_QUICK=1 early second-mark check; DCF_BLIND=hz pull in without a search */
    int quick = getenv("DCF_QUICK") ? atoi(getenv("DCF_QUICK")) : 0, blind = getenv("DCF_BLIND") != 0;
    if (blind) coh_pull_at(&trk, (float)atof(getenv("DCF_BLIND")));
    float z[2]; uint64_t n = 0;
    while (fread(z, 4, 2, f) == 2) {
        float dr, di, ir, ii;
        coh_push(&trk, z[0], z[1], &dr, &di, &ir, &ii);
        int valid = trk.state == COH_TRACK && (z[0] != 0 || z[1] != 0);
        dcf.n = n;
        dcf_push(&dcf, dr, di, valid);
        if (dcfbits_push(&bits, &dcf, dr, di, n, valid)) {
            /* the code is valid at the second 0 after second 59: ~2 s after the end of second 58 */
            double t_next = A + B * (double)(n + 1 + 2000) / 2000.0;
            int64_t tm = (int64_t)floor((t_next - 946684800.0) / 60.0 + 0.5);
            printf("MIN %llu %lld %c %lld %04d-%02d-%02d %02d:%02d %s flips %d pm %d agree %d weakest %.2f pred %.1f margin %.1f\n",
                   (unsigned long long)n, (long long)tm, "NFUCP"[bits.status], (long long)bits.utc_min,
                   bits.year, bits.month, bits.day, bits.hour, bits.minute, bits.cest ? "CEST" : "CET",
                   bits.flips, bits.bits_pm, bits.am_pm_agree, bits.weakest, bits.pred_score, bits.pred_margin);
            if (getenv("DCFMIN_DEBUG")) {
                for (int k = 0; k < 59; k++) printf("%s%d:%+.1f/%+.1f", k % 10 ? " " : "\n  ", k, bits.z_am[k], bits.z_pm[k]);
                printf("\n  lev_red %.3f var_am %.4f amp_pm %.4f var_pm %.6f votes %d | dcf pm_sigma %.1f lag %.2f\n",
                       bits.lev_red, bits.var_am, bits.amp_pm, bits.var_pm, bits.pm_sign_votes, dcf.pm_sigma, dcf.pm_lag_ms);
            }
            fflush(stdout);
        }
        n++;
        if (quick && !dcf.have_mark && trk.state == COH_TRACK && n % 20000 == 0 && dcf_quick_mark(&dcf, 10.0f))
            fprintf(stderr, "quick mark at %.0f s\n", n / 2000.0);
        if (quick > 1 && n % 20000 == 6000 && !dcf_block_ready(&dcf)) dcf_quick_minute(&dcf, getenv("DCF_QMIN") ? (float)atof(getenv("DCF_QMIN")) : 8.0f);   /* samples as main.c */
        if (quick > 1 && n % 20000 == 13000 && !dcf_block_ready(&dcf)) dcf_quick_pm(&dcf);
        if (blind && n == 360000 && !dcf.have_mark) coh_search(&trk);
        if (dcf_block_ready(&dcf)) {
            coh_report_t r; coh_report(&trk, &r);
            dcf_block(&dcf, trk.state == COH_TRACK ? (float)trk.hz : 0.0f);
        }
    }
    fprintf(stderr, "decoded %lu confirmed %lu failed %lu\n", bits.n_decoded, bits.n_confirmed, bits.n_failed);
    return 0;
}
