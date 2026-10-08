/* Spectrum diagnostic - see spec.h */
#include "spec.h"
#include <math.h>
#include <string.h>

#ifndef SPEC_SECTION
#if defined(__arm__)
#define SPEC_SECTION __attribute__((section(".dtcm")))
#else
#define SPEC_SECTION
#endif
#endif

static float tw_c[SPEC_N / 2] SPEC_SECTION, tw_s[SPEC_N / 2] SPEC_SECTION;   /* exp(-2 pi i k / N) */
static float buf[2 * SPEC_N] SPEC_SECTION;

void spec_init(void)
{
    for (int k = 0; k < SPEC_N / 2; k++) {
        double a = -2.0 * M_PI * k / SPEC_N;
        tw_c[k] = (float)cos(a); tw_s[k] = (float)sin(a);
    }
}

void spec_clear(spec_t *s) { memset(s, 0, sizeof *s); }

static void fft(float *x)                  /* in place, radix 2, x = interleaved re, im */
{
    int n = SPEC_N, j = 0;
    for (int i = 0; i < n - 1; i++) {      /* bit reversal */
        if (i < j) { float t = x[2*i]; x[2*i] = x[2*j]; x[2*j] = t; t = x[2*i+1]; x[2*i+1] = x[2*j+1]; x[2*j+1] = t; }
        int m = n >> 1;
        while (m >= 1 && j >= m) { j -= m; m >>= 1; }
        j += m;
    }
    for (int len = 2; len <= n; len <<= 1) {
        int half = len >> 1, step = n / len;
        for (int i = 0; i < n; i += len)
            for (int k = 0; k < half; k++) {
                float wr = tw_c[k * step], wi = tw_s[k * step];
                float *a = x + 2 * (i + k), *b = x + 2 * (i + k + half);
                float tr = b[0] * wr - b[1] * wi, ti = b[0] * wi + b[1] * wr;
                b[0] = a[0] - tr; b[1] = a[1] - ti;
                a[0] += tr; a[1] += ti;
            }
    }
}

void spec_add(spec_t *s, const uint32_t *b, float m0, float m1)
{
    for (int n = 0; n < SPEC_N; n++) {
        /* Hann: 0.5 - 0.5 cos(2 pi n / N); cos from the twiddles (symmetric about N/2) */
        float c = n < SPEC_N / 2 ? tw_c[n] : tw_c[SPEC_N - n < SPEC_N / 2 ? SPEC_N - n : 0];
        if (n == SPEC_N / 2) c = -1.0f;
        float w = 0.5f - 0.5f * c;
        buf[2 * n]     = ((float)(b[n] & 0xFFFF) - m0) * w;
        buf[2 * n + 1] = ((float)(b[n] >> 16) - m1) * w;
    }
    fft(buf);
    for (int k = 0; k <= SPEC_N / 2; k++) {
        int m = (SPEC_N - k) % SPEC_N;
        float xr = buf[2 * k], xi = buf[2 * k + 1], yr = buf[2 * m], yi = buf[2 * m + 1];
        float ar = 0.5f * (xr + yr), ai = 0.5f * (xi - yi);       /* A = (X_k + conj X_{N-k}) / 2 */
        float br = 0.5f * (xi + yi), bi = 0.5f * (yr - xr);       /* B = (X_k - conj X_{N-k}) / 2j */
        s->acc0[k] += ar * ar + ai * ai;
        s->acc1[k] += br * br + bi * bi;
    }
    s->nblk++;
}

/* Hann: sum w^2 = 3N/8, sum w = N/2 */
double spec_psd(const spec_t *s, int ch, int k, double fs)
{
    double p = (ch ? s->acc1[k] : s->acc0[k]) / (s->nblk ? s->nblk : 1);
    double one = (k == 0 || k == SPEC_N / 2) ? 1.0 : 2.0;        /* one-sided: DC and Nyquist have no mirror */
    return one * p / (0.375 * SPEC_N) / fs;                     /* LSB^2/Hz */
}
double spec_tone(const spec_t *s, int ch, int k)
{
    double p = (ch ? s->acc1[k] : s->acc0[k]) / (s->nblk ? s->nblk : 1);
    return 8.0 * p / ((double)SPEC_N * SPEC_N);                  /* a^2/2 for a tone of amplitude a */
}
