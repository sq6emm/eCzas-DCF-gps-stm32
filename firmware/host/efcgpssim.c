/* Closed-loop simulation of common/efc.c with the GPS PPS phase lock (efc_minute3), second by second.
 *   efcgpssim [mode] [days] [seed] [step offset s]
 *     mode 0: GPS all the time; 1: GPS with a 6 h outage (DCF77 / e-CzasPL take over) in the middle;
 *          2: DCF77 only (the loop before the GPS lock, for comparison); 3: cold start 20 ppb off, GPS;
 *          4: spoofed GPS phase STEP of 550 ns at mid-run (+ offset s into the minute: review 3 found a
 *          mid-minute step undetected by the minute-mean check); 5: spoofed GPS FREQUENCY +20 ppb from mid-run;
 *          6: as 0, but the EFC slope calibrated at the start (efc_init slope 0) - must end locked, not FAILED
 * OCXO: y_free = offset + random-walk FM + ageing + daily temperature swing; y = y_free - slope (code - c0)
 * (> 0: slow, as in efc.c); the DAC is dithered by efc_tick as on the board. GPS PPS: jitter 20 ns rms on the
 * pulse phase (NEO-7P, 1 Oct 2026); the firmware's unwrap / 10 us glitch filter / minute mean are copied.
 * DCF77: minute frequency noise 1.3 ppb by day, 3 ppb + slow sky-wave wander (+-4 ppb, 40 min) at night;
 * e-CzasPL: -0.85 ppb offset + 0.4 ppb minute noise.
 * Output: true OCXO time error against GPS (rms, max) and the OCXO's Allan deviation at 1 min ... 6 h,
 * over the whole run after the first 3 h. */
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
    int mode = argc > 1 ? atoi(argv[1]) : 0; double days = argc > 2 ? atof(argv[2]) : 2;
    srand(argc > 3 ? atoi(argv[3]) : 1);
    long toff = argc > 4 ? atol(argv[4]) : 0;
    const double slope = 0.816e-9, c0 = 2252.0;
    long N = (long)(days * 86400);
    efc_t f; efc_init(&f, c0, mode == 6 ? 0 : slope);
    double y0 = (mode == 3 ? 20e-9 : 1.5e-9), rw = 0, tocxo = 0.37, xtrue = 0;   /* OCXO time vs GPS [s] */
    double ph_prev = 0, xun = 0, xsum = 0; int have = 0, n = 0;
    double st_avg = 0; int st_n = 0, jump = 0;                         /* main.c per-pulse jump check */
    int code = (int)c0;
    double *ym = malloc(sizeof(double) * (N / 60 + 2)); long nm = 0; double ysum_min = 0;
    double sx2 = 0, xmax = 0; long nx = 0; double skyp = 0; long nsus = 0, nj = 0, nf = 0, ngps = 0;
    for (long t = 0; t < N; t++) {
        double hour = fmod(t / 3600.0, 24.0);
        int night = hour < 5 || hour > 17;
        rw += 2e-14 * gauss();                                         /* random-walk FM */
        double yfree = y0 + rw + 1e-10 * t / 86400.0 + 0.5e-9 * sin(2 * M_PI * t / 86400.0);
        double y = yfree - slope * (code - c0);                        /* > 0: slow */
        tocxo += 1.0 - y; xtrue += y;                                   /* OCXO behind GPS by xtrue */
        ysum_min += y;
        int gps_on = mode != 2 && !(mode == 1 && t > N / 2 - 3 * 3600 && t < N / 2 + 3 * 3600);
        if (gps_on) {                                                  /* the firmware's PPS processing */
            double spoof = (mode == 4 && t > N / 2 + toff) ? 550e-9 : (mode == 5 && t > N / 2) ? -20e-9 * (t - N / 2) : 0;
            double ph = fmod(tocxo + spoof + 20e-9 * gauss(), 1.0); if (ph < 0) ph += 1;
            if (have) {
                double st = -(ph - ph_prev); st -= floor(st + 0.5);
                if (st_n >= 5 && fabs(st - st_avg) > 300e-9) jump = 1;
                else if (fabs(st) < 1e-5) { st_avg += (st - st_avg) * (st_n < 10 ? 1.0 / (st_n + 1) : 0.1); st_n++; }
                if (fabs(st) < 1e-5) { xun += st; xsum += xun; n++; ph_prev = ph; } else have = 0;
            } else { have = 1; ph_prev = ph; }
        } else have = 0;
        if (t % 60 == 59) {
            double ymin = ysum_min / 60; ysum_min = 0;
            if (t > 3 * 3600) ym[nm++] = ymin;
            skyp += 2 * M_PI * 60 / 2400.0;
            double yd = ymin + (night ? 3e-9 * gauss() + 4e-9 * sin(skyp) * 0.5 : 1.3e-9 * gauss());
            double ye = ymin - 0.85e-9 + 0.4e-9 * gauss();
            int vg = n >= 50; double xg = n ? xsum / n : 0; xsum = 0; n = 0;
            f.gjump_ext = jump; jump = 0;
            int src = efc_minute3(&f, vg, xg, 1, yd, 1, ye, 60.0);
            if (f.gsus > 0) { nsus++; if (f.gsus_why == 1) nj++; else nf++; }
            if (src == EFC_SRC_GPS) ngps++;
        }
        code = efc_tick(&f, 1.0);
        if (t > 3 * 3600) {
            static double x0 = 1e9; if (x0 > 1e8) x0 = xtrue;           /* time error from the 3 h mark */
            double x = xtrue - x0; sx2 += x * x; nx++; if (fabs(x) > xmax) xmax = fabs(x);
        }
    }
    printf("mode %d (%s), %.1f days, tau_gps %.0f s: time error vs GPS rms %.1f ns max %.1f ns | OCXO ADEV",
           mode, mode == 0 ? "GPS" : mode == 1 ? "GPS, 6 h outage" : mode == 2 ? "DCF77 only" : mode == 3 ? "GPS, cold start 20 ppb" : mode == 4 ? "GPS, spoofed 550 ns step" : mode == 5 ? "GPS, spoofed +20 ppb" : "GPS, calibrated at start",
           days, f.tau, sqrt(sx2 / nx) * 1e9, xmax * 1e9);
    int taus[] = { 1, 10, 60, 180, 360 };
    for (int k = 0; k < 5; k++) {
        int m = taus[k]; double s = 0; long c = 0;
        for (long i = 0; i + 2 * m <= nm; i += m) {
            double a = 0, b = 0;
            for (int j = 0; j < m; j++) { a += ym[i + j]; b += ym[i + m + j]; }
            a /= m; b /= m; s += (b - a) * (b - a); c++;
        }
        printf(" %d min %.1e", m, c ? sqrt(0.5 * s / c) : 0);
    }
    printf(" | GPS steering %ld min, suspended %ld min (jump %ld, disagreement %ld) | end: %s, slope %.3g\n",
           ngps, nsus, nj, nf, efc_state_txt(&f), f.slope);
    return 0;
}
