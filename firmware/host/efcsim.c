/* Host test of common/efc.c against a simulated OCXO.
 *   efcsim [slope_true_ppb_per_code] [offset_ppb] [noise_ppb] [hours] [dropout]
 * Two stations (env): EFC2=1 feeds DCF77 (noise_ppb) and e-CzasPL (ECZ_NOISE ppb, ECZ_BIAS ppb
 * offset) through efc_minute2; EFC2=0 DCF77 alone. NIGHT=1: after 2 h DCF77 gets 3x the noise and
 * a slow +-300 ns sky-wave phase wander (period 40 min). KNOWN=slope starts in LOCK (no calibration).
 * dropout 3: DCF77 missing 30 min every 3 h (e-CzasPL continues).
 * OCXO: y_true(t) = offset + drift t - slope (code - 2048); the DAC output is averaged per minute
 * exactly as the tracker sees it; the measurement adds white PHASE noise (the tracker's phase is
 * continuous): noise_ppb is the resulting minute-to-minute scatter (DCF77 ~1.3 ppb, e-CzasPL ~2 ppb). Prints a line every 10 min and a summary:
 * max rate of change (must stay <= EFC_RATE), final |y|, rms time error in the last half. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "efc.h"

static double gauss(void)
{
    double u = (rand() + 1.0) / (RAND_MAX + 2.0), v = (rand() + 1.0) / (RAND_MAX + 2.0);
    return sqrt(-2 * log(u)) * cos(2 * M_PI * v);
}

int main(int argc, char **argv)
{
    double slope = (argc > 1 ? atof(argv[1]) : 0.604) * 1e-9;
    double off = (argc > 2 ? atof(argv[2]) : 162) * 1e-9;
    double noise = (argc > 3 ? atof(argv[3]) : 1.5) * 1e-9;
    double hours = argc > 4 ? atof(argv[4]) : 12;
    int dropout = argc > 5 ? atoi(argv[5]) : 0;
    double drift = 0.5e-9 / 86400;                  /* aging 0.5 ppb/day */
    int two = getenv("EFC2") ? atoi(getenv("EFC2")) : 0, night = getenv("NIGHT") ? atoi(getenv("NIGHT")) : 0;
    double enoise = (getenv("ECZ_NOISE") ? atof(getenv("ECZ_NOISE")) : 0.8) * 1e-9;
    double ebias = (getenv("ECZ_BIAS") ? atof(getenv("ECZ_BIAS")) : -1.0) * 1e-9;
    double known = getenv("KNOWN") ? atof(getenv("KNOWN")) * 1e-9 : 0;
    efc_t f; efc_init(&f, 2048, known);
    double sfe = 0; long nfe = 0;
    srand(1);
    double dt = 0.005, t = 0, maxrate = 0, prev_y = 0, tx = 0, sx2 = 0; long nx = 0;
    int minutes = (int)(hours * 60);
    for (int m = 0; m < minutes; m++) {
        double ysum = 0;
        for (int k = 0; k < 12000; k++) {
            int q = efc_tick(&f, dt);
            double yt = off + drift * t - slope * (q - 2048);
            ysum += yt; t += dt;
        }
        double ytrue = ysum / 12000;
        if (m > 0) { double r = fabs(ytrue - prev_y) / 60; if (r > maxrate) maxrate = r; }
        prev_y = ytrue;
        tx += ytrue * 60;                          /* true time error of the OCXO */
        int src = EFC_SRC_DCF77;
        if ((dropout == 1 || dropout == 2) && (m % 180) >= 150) src = EFC_SRC_NONE;      /* 30 min without DCF77 every 3 h */
        if (dropout == 2 && (m % 180) >= 120 && (m % 180) < 150) src = EFC_SRC_ECZAS;
        static double pn_prev, pe_prev, sw_prev;
        int ngt = night && m >= 120;
        double pn = noise * (ngt ? 3 : 1) * 60 / sqrt(2) * gauss();       /* phase noise [s] */
        double sw = ngt ? 300e-9 * sin(2 * M_PI * m / 40.0) : 0;          /* sky-wave phase */
        double yd = ytrue + (pn - pn_prev) / 60 + (sw - sw_prev) / 60;
        double pe = enoise * 60 / sqrt(2) * gauss();
        double ye = ytrue + ebias + (pe - pe_prev) / 60;
        pn_prev = pn; pe_prev = pe; sw_prev = sw;
        if (two) efc_minute2(&f, src != EFC_SRC_NONE && !(dropout == 3 && (m % 180) >= 150), yd, 1, ye, 60);
        else efc_minute(&f, src, src == EFC_SRC_ECZAS ? ye : yd, 60);
        if (m >= minutes / 2) { sfe += ytrue; nfe++; }
        if (m >= minutes / 2) { static double tx0; static int first = 1; if (first) { tx0 = tx; first = 0; }
            sx2 += (tx - tx0) * (tx - tx0); nx++; }
        if (m % 10 == 9)
            printf("%6.1f min  %-22s code %8.2f  y %+7.2f ppb  x %+9.1f ns  slope %.3f ppb/code\n",
                   (m + 1.0), efc_state_txt(&f), f.c, ytrue * 1e9, f.x * 1e9, f.slope * 1e9);
    }
    printf("SUMMARY slope %.3f off %.0f: state %s, final y %+.2f ppb, max rate %.2e /s, rms time wander (2nd half) %.1f ns, mean freq error (2nd half) %+.3f ppb, bias %+.3f ppb, w_e %.2f\n",
           slope * 1e9, off * 1e9, efc_state_txt(&f), prev_y * 1e9, maxrate, sqrt(sx2 / (nx ? nx : 1)) * 1e9,
           sfe / (nfe ? nfe : 1) * 1e9, f.bias * 1e9, f.we);
    return 0;
}
