/*
 * Host test of the TDF decoder (common/tdf.c) on top of the carrier tracker (coh.c, DCF77 settings),
 * the chain a NUCLEO third mixer at 162 kHz would feed.
 *   tdfsim file.c64 A        file: 2 kHz complex float32, TDF near 0 Hz; A = unix time of sample 0
 * One line per evaluated minute: MIN n truth_utc_min status decoded_utc_min local time flips start_ms q
 * status: F failed checks, U decoded, C confirmed. Truth: the minute after the marker second by the file clock.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "coh.h"
#include "tdf.h"

int main(int argc, char **argv)
{
    static coh_trk_t trk; static tdf_t td;
    if (argc < 3) { fprintf(stderr, "usage: tdfsim file.c64 A\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) return 2;
    double A = atof(argv[2]);
    coh_cfg_t cfg = { COH_PLAIN, 20000, 0.03f, 0.01f, 6, 500, 512, 2.0f, 40.0f, 600.0f };
    coh_init(&trk, &cfg); tdf_init(&td);
    float z[2]; uint64_t n = 0;
    while (fread(z, 4, 2, f) == 2) {
        float dr, di, ir, ii;
        coh_push(&trk, z[0], z[1], &dr, &di, &ir, &ii);
        int valid = trk.state == COH_TRACK && (z[0] != 0 || z[1] != 0);
        if (tdf_push(&td, dr, di, valid)) {
            double t = A + (double)(n + 1) / 2000.0;
            long long truth = (long long)floor((t - 946684800.0 + 30.0) / 60.0);
            printf("MIN %llu %lld %c %lld %04d-%02d-%02d %02d:%02d %s flips %d start %d q %.1f pred %.1f margin %.1f\n",
                   (unsigned long long)n, truth, "NFUCP"[td.status], (long long)td.utc_min,
                   td.year, td.month, td.day, td.hour, td.minute, td.cest ? "CEST" : "CET", td.flips, td.start, td.start_q, td.pred_score, td.pred_margin);
            fflush(stdout);
        }
        n++;
        if (getenv("TDF_DEBUG") && n % 120000 == 0)
            fprintf(stderr, "t %4llu s: trk state %d hz %+.3f | start %d q %.1f | sec %llu phase60 %d sig2 %.3g llr %+.1f\n",
                    (unsigned long long)(n / 2000), trk.state, trk.hz, td.start, td.start_q, (unsigned long long)td.sec, td.phase60,
                    td.sig2, td.sec ? td.llr[(td.sec - 1) % 60] : 0.0f);
    }
    fprintf(stderr, "decoded %lu confirmed %lu by expected frame %lu failed %lu\n", td.n_decoded, td.n_confirmed, td.n_predicted, td.n_failed);
    return 0;
}
