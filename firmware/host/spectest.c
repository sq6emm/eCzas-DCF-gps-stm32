/* Host test of common/spec.c: synthetic dual-ADC words (A0: tone 225 kHz of amplitude 300 LSB + white
   noise sigma 5 LSB; A1: tone 77.5 kHz amplitude 40 LSB + white noise sigma 20 LSB), fs = 1 MS/s.
   Expected: tone mean-square a^2/2 in the peak bin (Hann, <= 1.4 dB low), PSD 2 sigma^2 / fs. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "spec.h"
static double gauss(void) { double u = (rand() + 1.0) / (RAND_MAX + 2.0), v = (rand() + 1.0) / (RAND_MAX + 2.0); return sqrt(-2 * log(u)) * cos(2 * M_PI * v); }
int main(void)
{
    static spec_t s; static uint32_t b[SPEC_N]; double fs = 1e6;
    spec_init(); spec_clear(&s); srand(1);
    long t = 0;
    for (int blk = 0; blk < 64; blk++) {
        for (int n = 0; n < SPEC_N; n++, t++) {
            double a0 = 32768 + 300 * cos(2 * M_PI * 225000 * t / fs) + 5 * gauss();
            double a1 = 32768 + 40 * cos(2 * M_PI * 77500 * t / fs + 1) + 20 * gauss();
            b[n] = (uint32_t)lround(a0) | (uint32_t)lround(a1) << 16;
        }
        spec_add(&s, b, 32768, 32768);
    }
    int k0 = (int)lround(225000 / fs * SPEC_N), k1 = (int)lround(77500 / fs * SPEC_N);
    for (int d = -1; d <= 1; d++) { if (s.acc0[k0 + d] > s.acc0[k0]) k0 += d; if (s.acc1[k1 + d] > s.acc1[k1]) k1 += d; }
    double n0 = 0, n1 = 0; int c = 0;
    for (int k = 400; k < 800; k++)       /* clear of both tones (bins 317, 922) */ { n0 += spec_psd(&s, 0, k, fs); n1 += spec_psd(&s, 1, k, fs); c++; }
    printf("A0 tone bin %d (%.1f kHz) %.1f dB expect %.1f..%.1f | noise %.2f dB expect %.2f\n", k0, k0 * fs / SPEC_N / 1e3,
           10 * log10(spec_tone(&s, 0, k0)), 10 * log10(300.0 * 300 / 2) - 1.4, 10 * log10(300.0 * 300 / 2), 10 * log10(n0 / c), 10 * log10(2 * 25 / fs + 2 / 12.0 / fs));
    printf("A1 tone bin %d (%.1f kHz) %.1f dB expect %.1f..%.1f | noise %.2f dB expect %.2f\n", k1, k1 * fs / SPEC_N / 1e3,
           10 * log10(spec_tone(&s, 1, k1)), 10 * log10(40.0 * 40 / 2) - 1.4, 10 * log10(40.0 * 40 / 2), 10 * log10(n1 / c), 10 * log10(2 * 400 / fs + 2 / 12.0 / fs));
    printf("cross-talk: A0 at the A1 tone bin %.1f dB, A1 at the A0 tone bin %.1f dB (noise-level expected)\n",
           10 * log10(spec_psd(&s, 0, k1, fs)), 10 * log10(spec_psd(&s, 1, k0, fs)));
    return 0;
}
