/*
 * Host test of the standalone DCF77 receiver (coh.c + dcf.c) on the NUCLEO's 2 kHz DCF77 dumps.
 *   dcfsim file.c64 N0 [A B]
 *     file.c64  contiguous complex float32 samples (gaps zero-filled), first sample index N0
 *     A B       optional cross-check only: e-CzasPL unix time = A + B * n / 2000 (TIMEMAP fit);
 *               then the DCF77 second start is also printed against the e-CzasPL second
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "coh.h"
#include "dcf.h"

int main(int argc, char **argv)
{
    static coh_trk_t trk; static dcf_t dcf;
    if (argc < 3) { fprintf(stderr, "usage: dcfsim file.c64 N0 [A B]\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) return 2;
    unsigned long long n0 = strtoull(argv[2], 0, 10);
    double A = argc > 4 ? atof(argv[3]) : 0, B = argc > 4 ? atof(argv[4]) : 0;
#ifndef DCF_COH
#define DCF_COH { COH_PLAIN, 20000, 0.03f, 0.01f, 6, 500, 512, 2.0f, 40.0f, 600.0f }   /* as main.c */
#endif
    coh_cfg_t cfg = DCF_COH;
    coh_init(&trk, &cfg); dcf_init(&dcf);
    /* the chip's DCF77 stream starts at boot: skip to the next whole LSE second */
    float z[2]; unsigned long long n = n0;
    printf("block_end_n  state  f_mHz  cn0  err  | mark_ms sigma | minute(LSE s mod 60) sigma | pm_lag_ms sigma | dcf-eczas_ms\n");
    while (fread(z, 4, 2, f) == 2) {
        float dr, di, ir, ii;
        coh_push(&trk, z[0], z[1], &dr, &di, &ir, &ii);
        dcf.n = n;                                   /* keep dcf's clock = the chip's sample count */
        dcf_push(&dcf, dr, di, trk.state == COH_TRACK && (z[0] != 0 || z[1] != 0));
        n++;
        if (dcf_block_ready(&dcf)) {
            coh_report_t r; coh_report(&trk, &r);
            dcf_block(&dcf, trk.state == COH_TRACK ? (float)trk.hz : 0.0f);
            /* carrier check: a DCF77 carrier has second marks. No mark 60 min after locking
             * -> this line is something else (a local spur): reject it and search again. */
            static int blocks_locked = 0, proven = 0; static float line_hz = 1e9;
            if (trk.state == COH_SEARCH) ;                                  /* keep counting through re-searches */
            else {
                if (fabsf((float)trk.hz - line_hz) > 0.15f) { line_hz = (float)trk.hz; blocks_locked = 1; proven = 0; }
                else blocks_locked++;
                if (dcf.mark_sigma >= 6) proven = 1;                        /* marks seen: DCF77, keep it */
            }
            if (!proven && blocks_locked >= 6 && dcf.mark_sigma < 6) {
                printf("# reject %.3f Hz (no second marks after %d blocks)\n", trk.hz, blocks_locked);
                coh_reject(&trk, 0.05f); blocks_locked = 0; memset(dcf.yr, 0, sizeof dcf.yr);
            }
            double x = 0;
            if (B != 0 && dcf.have_mark) {
                double ns = (double)(n - (n % 2000)) + dcf.mark + (dcf.pm_sigma > 5 ? dcf.pm_lag_ms * 2.0 : 0);  /* a DCF77 second start */
                double t = A + B * ns / 2000.0;
                x = (t - floor(t + 0.5)) * 1000.0;
            }
            printf("%llu  %d  %+7.1f  %5.1f  %4.1f | %7.1f %5.1f | %3d %5.1f | %+7.3f %5.1f | %+8.3f\n", n, r.state,
                   r.freq_hz * 1000, r.cn0_dbhz, r.err_deg, dcf.mark / 2.0, dcf.mark_sigma, dcf.minute_s, dcf.minute_sigma,
                   dcf.pm_lag_ms, dcf.pm_sigma, x);
            fflush(stdout);
        }
    }
    return 0;
}
