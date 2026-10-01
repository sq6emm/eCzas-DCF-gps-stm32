/* Closed-loop replay of common/efc.c on logged minutes (tools/efc_replay_extract.py).
 *   efcreplay MINUTES.txt [slope_ppb_per_code 0.816] [bias_ppb -0.84] [window start YYYY-MM-DDTHH:MM for the window stats]
 * env CN0_MIN: DCF77 counts only in minutes with at least this C/N0 [dB-Hz] (and, as in main.c, only
 * after 2 whole such minutes); without it the logged lock state is used as it is.
 * The logged station frequencies were measured with the OCXO as it was steered then; with the
 * slope that steering is removed (y_free = y + slope (code_logged - c0)) and the code this
 * efc.c chooses is applied instead. Truth for the result: e-CzasPL minus its learned offset (45 dB-Hz,
 * ~1e-10 over minutes): per minute the OCXO frequency error and its integral (time error; in the
 * window counted from its start, so that the offset's own uncertainty does not dominate). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "efc.h"

int main(int argc, char **argv)
{
    FILE *fp = fopen(argv[1], "r"); if (!fp) return 1;
    double s = (argc > 2 ? atof(argv[2]) : 0.816) * 1e-9, bias = (argc > 3 ? atof(argv[3]) : -0.84) * 1e-9;
    const char *wfrom = argc > 4 ? argv[4] : "9999";
    char t[32]; int vd, ve, nd = 0; double yd, ye, cl, cn, clp = -1, c0 = -1;
    const char *cm = getenv("CN0_MIN"); double cn0_min = cm ? atof(cm) : -1e9;
    efc_t f; double csum = 0, cprev_avg = 0;
    double tsum = 0, tmax = 0;
    double x = 0, sx2 = 0, xmax = 0, ymax = 0, wx = 0, wx2 = 0, wxmax = 0, wymax = 0; long n = 0, wn = 0, nsrc[4] = { 0 };
    while (fscanf(fp, "%31s %d %lf %d %lf %lf %lf", t, &vd, &yd, &ve, &ye, &cl, &cn) == 7) {
        if (cm) { nd = (vd && cn >= cn0_min) ? nd + 1 : 0; vd = nd > 2; }
        if (c0 < 0) {
            c0 = clp = cl; efc_init(&f, cl, s);
            f.bias = bias; f.bn = 10; f.vd = f.ve = 1.7e-18; cprev_avg = cl;
        }
        double clavg = 0.5 * (clp + cl);                /* logged code over the measured minute */
        double adj = s * (clavg - cprev_avg);            /* this code instead of the logged one */
        double yds = yd + adj, yes = ye + adj;
        int src = efc_minute2(&f, vd, yds, ve, yes, 60.0);
        nsrc[src]++;
        tsum += f.tau; if (f.tau > tmax) tmax = f.tau;
        double yt = yes - bias;                          /* truth: OCXO error by e-CzasPL */
        x += yt * 60; n++; sx2 += x * x;
        if (fabs(x) > xmax) xmax = fabs(x);
        if (fabs(yt) > ymax) ymax = fabs(yt);
        if (strcmp(t, wfrom) >= 0) { wn++; wx += yt * 60; wx2 += wx * wx; if (fabs(wx) > wxmax) wxmax = fabs(wx); if (fabs(yt) > wymax) wymax = fabs(yt); }
        if (getenv("TRACE") && strcmp(t, wfrom) >= 0)
            printf("%s src %d code %.1f (logged %.1f) yd %+6.1f ye %+6.1f -> ocxo %+6.2f ppb, time %+8.1f ns\n",
                   t + 11, src, f.c, cl, yds * 1e9, yes * 1e9, yt * 1e9, wx * 1e9);
        csum = 0;
        for (int k = 0; k < 60; k++) { csum += f.c; efc_tick(&f, 1.0); }
        cprev_avg = csum / 60; clp = cl;
    }
    printf("minutes %ld (src none/DCF77/e-CzasPL/both %ld/%ld/%ld/%ld) | all: time rms %.0f ns max %.0f ns, freq max %.1f ppb | from %s: %ld min, time rms %.0f max %.0f ns, freq max %.1f ppb | loop mean %.0f max %.0f s\n",
           n, nsrc[0], nsrc[1], nsrc[2], nsrc[3], sqrt(sx2 / n) * 1e9, xmax * 1e9, ymax * 1e9, wfrom, wn,
           wn ? sqrt(wx2 / wn) * 1e9 : 0, wxmax * 1e9, wymax * 1e9, tsum / n, tmax);
    return 0;
}
