/* Closed-loop replay of the GPS PPS phase lock (efc_minute3) on a real OCXO.
 *   efcgpsreplay FILE [slope_ppb_per_code 0.816]
 * FILE: per second "time y_ppb code" from the NUCLEO log (GPS PPS lines: the OCXO's 1-s error against GPS as
 * steered then; code = the EFC code then). The steering is removed (y_free = y + slope (code - c0)), this
 * efc.c steers instead, second by second; the PPS phase is the integral of y (the logged values already
 * contain the PPS jitter). Output: time error vs GPS (1-min means, after 30 min), the OCXO's Allan deviation. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "efc.h"
int main(int argc, char **argv)
{
    FILE *fp = fopen(argv[1], "r"); if (!fp) return 1;
    double s = (argc > 2 ? atof(argv[2]) : 0.816) * 1e-9;
    char t[32]; double y, cl, c0 = -1; efc_t f; int code = 0;
    double ph_prev = 0, xun = 0, xsum = 0, tocxo = 0.37, xtrue = 0, ysum = 0, xmsum = 0; int have = 0, n = 0, k = 0;
    double ym[100000]; long nm = 0; double sx2 = 0, xmax = 0, x0 = 0; long nx = 0;
    while (fscanf(fp, "%31s %lf %lf", t, &y, &cl) == 3) {
        if (c0 < 0) { c0 = cl; code = (int)c0; efc_init(&f, c0, s); }
        double yfree = y * 1e-9 + s * (cl - c0);
        double yy = yfree - s * (code - c0);
        tocxo += 1.0 - yy; xtrue += yy; ysum += yy; xmsum += xtrue;
        double ph = fmod(tocxo, 1.0); if (ph < 0) ph += 1;
        if (have) { double st = -(ph - ph_prev); st -= floor(st + 0.5);
            if (fabs(st) < 1e-5) { xun += st; xsum += xun; n++; ph_prev = ph; } else have = 0; }
        else { have = 1; ph_prev = ph; }
        if (++k % 60 == 0) {
            double xmin = xmsum / 60; xmsum = 0;
            if (k > 1800) { if (nx == 0) x0 = xmin; double x = xmin - x0; sx2 += x * x; nx++; if (fabs(x) > xmax) xmax = fabs(x); ym[nm++] = ysum / 60; }
            ysum = 0;
            efc_minute3(&f, n >= 50, n ? xsum / n : 0, 0, 0, 0, 0, 60.0); xsum = 0; n = 0;
        }
        code = efc_tick(&f, 1.0);
    }
    printf("%ld s, tau_gps %.0f s: time error vs GPS (1-min means, after 30 min) rms %.1f ns max %.1f ns | ADEV", (long)k, f.tau, sqrt(sx2 / nx) * 1e9, xmax * 1e9);
    int taus[] = { 1, 10, 30, 60 };
    for (int q = 0; q < 4; q++) { int m = taus[q]; double a2 = 0; long c = 0;
        for (long i = 0; i + 2 * m <= nm; i += m) { double a = 0, b = 0; for (int j = 0; j < m; j++) { a += ym[i + j]; b += ym[i + m + j]; } a /= m; b /= m; a2 += (b - a) * (b - a); c++; }
        printf(" %d min %.1e", m, c ? sqrt(0.5 * a2 / c) : 0); }
    printf("\n"); return 0;
}
