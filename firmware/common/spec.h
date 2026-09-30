/*
 * Spectrum diagnostic of the two ADC inputs (A0 in bits 15:0, A1 in bits 31:16 of the dual-ADC words):
 * Hann-windowed 4096-point FFTs of both inputs at once (A0 real part, A1 imaginary part of one complex
 * FFT, separated by symmetry), power averaged over the blocks added. Used to see the tuned rods'
 * resonance in the noise floor and the carriers around it.
 */
#ifndef SPEC_H
#define SPEC_H
#include <stdint.h>

#define SPEC_N 4096
typedef struct {
    float acc0[SPEC_N / 2 + 1], acc1[SPEC_N / 2 + 1];   /* summed |X_k|^2 of A0 and A1 */
    int   nblk;
} spec_t;

void spec_init(void);                                  /* twiddle table (once) */
void spec_clear(spec_t *s);
/* the first SPEC_N words of a DMA block; m0 / m1 = the inputs' mean (ADC counts) */
void spec_add(spec_t *s, const uint32_t *b, float m0, float m1);
/* power spectral density of input ch (0 = A0, 1 = A1) in bin k, in LSB^2/Hz (fs = sample rate) */
double spec_psd(const spec_t *s, int ch, int k, double fs);
/* mean-square of a carrier whose peak is in bin k, in LSB^2 (Hann peak bin, up to 1.4 dB low between bins) */
double spec_tone(const spec_t *s, int ch, int k);
#endif
