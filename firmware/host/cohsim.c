/*
 * Host test of the coherent e-CzasPL receiver (coh.c + ecz.c + the eCzas frame.c /
 * timekeeper.c), scored exactly like the eCzas firmware's host/sim.c.
 *
 *   cohsim [-8] [-n SNR_dB] [-s SEED] [-r T0 N0] [-q] [-b BW] file.raw
 *     file.raw  signed 16-bit mono with the carrier near 1 kHz: 10 kHz (NUCLEO audio dump,
 *               sim.c input) or, with -8, 8 kHz (IC-705 recordings)
 *     -n SNR    add white noise relative to the input RMS (as sim.c)
 *     -r T0 N0  truth: the frame starting at T0 s is number N0 (wrong times are counted)
 *     -b BW     tracking loop bandwidth [Hz] (default 1)
 *   cohsim -c [-n SNR_dB] ... file.c64
 *     file.c64  the NUCLEO's own e-CzasPL dump (2 kHz complex float32 mixer output, ecz_*.c64): fed to
 *               the tracker as it is, the firmware's chain exactly (-n: complex noise relative to |z| rms)
 * Per decoded frame (not -q): "t=<s from the start> N=<n3>" with the core's frame start time.
 * The input is turned into the chip's 2 kHz complex baseband (mix by 1 kHz, sum over 0.5 ms).
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "coh.h"
#include "ecz.h"
#include "frame.h"
#include "timekeeper.h"

static uint64_t rng = 88172645463325252ULL;
static double urand(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return (rng >> 11) * (1.0 / 9007199254740992.0); }
static double grand(void) { double u = urand() + 1e-300, v = urand(); return sqrt(-2 * log(u)) * cos(2 * M_PI * v); }

/* expected-frame confirmation, as in sim.c / main.c */
static int confirm(ecz_t *ez, tk_t *tk, const frame_info_t *last, int64_t tick,
                   double ref_t0, uint32_t ref_n0, double tsec, int *wrong, frame_info_t *synced_fi)
{
    uint32_t n3p; uint8_t bits[FRAME_BITS]; int32_t tq = 0; frame_info_t fe;
    if (!tk->synced) {
        uint8_t tz, flags, idx;
        if (!tk_candidate_expected(tk, tick, &n3p, &tz, &flags, &idx)) return 0;
        frame_build(n3p, tz, flags, bits);
        if (frame_confirm(ez->cand.ph + CAND_PRE, bits, &tq) < CONFIRM_MIN_Q10) return 0;
        if (tk_candidate_confirmed(tk, idx, tick + (int64_t)tq * TICKS_PER_BLOCK / 32768, n3p) == TK_SYNCED) {
            memset(synced_fi, 0, sizeof *synced_fi);
            synced_fi->n3 = n3p; synced_fi->tz = tz;
            synced_fi->ls = flags & 1; synced_fi->lss = (flags >> 1) & 1; synced_fi->tzc = (flags >> 2) & 1;
            synced_fi->sk = (uint8_t)((flags >> 3) & 3);
            if (ref_t0 >= 0 && n3p != ref_n0 + (uint32_t)lround((tsec - ref_t0) / 3.0)) (*wrong)++;
            return 2;
        }
        return 1;
    }
    if (!last) return 0;
    if (!tk_expected_n3(tk, tick, &n3p)) return 0;
    frame_build(n3p, last->tz, (uint8_t)(last->ls | last->lss << 1 | last->tzc << 2 |
                (last->sk & 1) << 3 | (last->sk >> 1) << 4), bits);
    if (frame_confirm(ez->cand.ph + CAND_PRE, bits, &tq) < CONFIRM_MIN_Q10) return 0;
    fe = *last; fe.n3 = n3p;
    if (tk_frame(tk, tick + (int64_t)tq * TICKS_PER_BLOCK / 32768, &fe) != TK_ACCEPTED) return 0;
    if (ref_t0 >= 0 && n3p != ref_n0 + (uint32_t)lround((tsec - ref_t0) / 3.0)) (*wrong)++;
    return 1;
}

int main(int argc, char **argv)
{
    static coh_trk_t trk; static ecz_t ez; tk_t tk;
    int fs_in = 10000, quiet = 0, c64 = 0, a; double snr = 1e9, bw = 1.0, rms = 0, ref_t0 = -1; uint32_t ref_n0 = 0;
    const char *path = NULL; FILE *f; long n = 0, cap = 1 << 20, i; int16_t *x;
    int n_cand = 0, n_ok = 0, n_nottime = 0, n_fail = 0, n_tk[5] = { 0 }, clock_wrong = 0, n_conf = 0, conf_wrong = 0, cr;
    int n_presync = 0, have_last = 0, ever = 0, n_unl = 0; long unl = 0, run = 0, maxrun = 0;
    double sum_err = 0, sum_err2 = 0, first_sync = -1; int n_err = 0; frame_info_t last_fi, sfi;

    for (a = 1; a < argc; a++) {
        if (!strcmp(argv[a], "-8")) fs_in = 8000;
        else if (!strcmp(argv[a], "-n")) snr = atof(argv[++a]);
        else if (!strcmp(argv[a], "-s")) rng ^= (uint64_t)atoll(argv[++a]) * 0x9E3779B97F4A7C15ULL;
        else if (!strcmp(argv[a], "-r")) { ref_t0 = atof(argv[++a]); ref_n0 = (uint32_t)atol(argv[++a]); }
        else if (!strcmp(argv[a], "-b")) bw = atof(argv[++a]);
        else if (!strcmp(argv[a], "-q")) quiet = 1;
        else if (!strcmp(argv[a], "-c")) c64 = 1;
        else path = argv[a];
    }
    if (!path || !(f = fopen(path, "rb"))) { fprintf(stderr, "usage: cohsim [-8] [-n snr] file.raw\n"); return 2; }
    float *zc = NULL;
    if (c64) {                                      /* 2 kHz complex: n = complex samples */
        zc = malloc(cap * 2 * sizeof *zc);
        while (fread(&zc[2 * n], sizeof(float), 2, f) == 2) {
            rms += (double)zc[2 * n] * zc[2 * n] + (double)zc[2 * n + 1] * zc[2 * n + 1];
            if (++n == cap) { cap *= 2; zc = realloc(zc, cap * 2 * sizeof *zc); }
        }
        fclose(f); rms = sqrt(rms / n); x = NULL;
    } else {
    x = malloc(cap * sizeof *x);
    while (fread(&x[n], 2, 1, f) == 1) { rms += (double)x[n] * x[n]; if (++n == cap) { cap *= 2; x = realloc(x, cap * sizeof *x); } }
    fclose(f); rms = sqrt(rms / n);
    }

    coh_cfg_t cfg = { COH_ECZAS, 4, 3.0f, (float)bw, 1500, 4, 1024, 40.0f, 25.0f, 30.0f };
    coh_init(&trk, &cfg); ecz_init(&ez); tk_init(&tk);
    int dec = fs_in / 2000; float sr = 0, si = 0; int k = 0; long n2k = 0;
    for (i = 0; i < n; i++) {
        if (c64) {
            sr = zc[2 * i]; si = zc[2 * i + 1];
            if (snr < 1e8) { double s = rms / pow(10, snr / 20) / sqrt(2.0); sr += (float)(grand() * s); si += (float)(grand() * s); }
            n2k++;
        } else {
        double v = x[i];
        if (snr < 1e8) v += grand() * rms / pow(10, snr / 20);
        double ph = 2 * M_PI * 1000.0 * i / fs_in;
        sr += (float)(v * cos(ph)); si -= (float)(v * sin(ph));
        if (++k < dec) continue;
        k = 0; n2k++;
        }
        float dr, di, ir, ii;
        if (coh_push(&trk, sr, si, &dr, &di, &ir, &ii)) {
            ecz_push(&ez, (int16_t)lrintf(atan2f(ii, ir) * (32768.0f / (float)M_PI)));
            if (trk.state == COH_TRACK && trk.err_avg * 360 < 25) { ever = 1; if (run > maxrun) maxrun = run; run = 0; }
            else if (ever) { unl++; if (run++ == 0) n_unl++; }
        }
        sr = si = 0;
        if (ez.cand_ready) {
            frame_info_t fi; frame_status_t st = frame_decode(ez.cand.ph + CAND_PRE, &fi);
            int64_t base = (int64_t)(ez.cand.start_block - 1) * TICKS_PER_BLOCK + (int64_t)ECZ_TEMPLATE_LAG_US * (FCY_HZ / 1000000L);
            int64_t tick = base + (int64_t)(st == FR_OK ? fi.timing_q15 : ez.cand.frac_q15) * TICKS_PER_BLOCK / 32768;
            double tsec = (double)tick / FCY_HZ;
            n_cand++;
            if (st == FR_OK) {
                tk_result_t r = tk_frame(&tk, tick, &fi);
                if (r == TK_ACCEPTED || r == TK_SYNCED || r == TK_STEPPED) {
                    last_fi = fi; have_last = 1; if (first_sync < 0) first_sync = tsec;
                    if (ref_t0 >= 0 && fi.n3 != ref_n0 + (uint32_t)lround((tsec - ref_t0) / 3.0)) clock_wrong++;
                }
                n_ok++; n_tk[r]++;
                coh_level_hint(&trk, -fi.lvl_sep / 65536.0f);
                if (r == TK_ACCEPTED) { sum_err += tk.last_err_us; sum_err2 += (double)tk.last_err_us * tk.last_err_us; n_err++; }
                if (!quiet) printf("%9.4f corr=%.2f N=%u rs=%d chase=%d snr=%ddB tk=%d err=%dus f=%+.3fHz\n", tsec,
                                   ez.cand.corr_q10 / 1024.0, fi.n3, fi.rs_fixed, fi.chase_flips, fi.snr_db, r, tk.last_err_us, trk.hz);
            } else if (st == FR_UNCORRECTABLE && (cr = confirm(&ez, &tk, have_last ? &last_fi : NULL, base,
                                                              ref_t0, ref_n0, tsec, &conf_wrong, &sfi)) != 0) {
                n_conf++;
                if (!quiet) printf("%9.4f corr=%.2f confirmed\n", tsec, ez.cand.corr_q10 / 1024.0);
                if (cr == 2) { last_fi = sfi; have_last = 1; if (first_sync < 0) first_sync = tsec; n_presync++; }
            } else if (st == FR_NOT_TIME) n_nottime++;
            else { n_fail++; if (!quiet) printf("%9.4f corr=%.2f decode failed (%d) snr=%d\n", tsec, ez.cand.corr_q10 / 1024.0, st, fi.snr_db); }
            ez.cand_ready = 0;
        }
        if (n2k % 4 == 0) tk_maintain(&tk, (int64_t)(n2k / 4) * TICKS_PER_BLOCK);
    }
    if (run > maxrun) maxrun = run;
    coh_report_t rp; coh_report(&trk, &rp);
    printf("LOCK unlocks=%d unlocked_s=%.0f longest_unlock_s=%.0f searches=%d lvl0=%.1fdeg f_end=%+.3fHz\n", n_unl,
           unl * 0.002, maxrun * 0.002, trk.searches, trk.lvl0 * 360, trk.hz);
    printf("SUMMARY snr=%g cand=%d time_ok=%d other=%d failed=%d accept=%d sync=%d step=%d cand=%d reject=%d "
           "jitter_rms=%.0fus err_mean=%.0fus rate=%dppb first_sync=%.0fs clock_wrong=%d confirmed=%d confirm_wrong=%d presync=%d\n",
           snr, n_cand, n_ok, n_nottime, n_fail, n_tk[0], n_tk[1], n_tk[2], n_tk[3], n_tk[4],
           n_err ? sqrt(sum_err2 / n_err - (sum_err / n_err) * (sum_err / n_err)) : 0.0, n_err ? sum_err / n_err : 0.0,
           tk_rate_ppb(&tk), first_sync, clock_wrong, n_conf, conf_wrong, n_presync);
    free(x); free(zc);
    return 0;
}
