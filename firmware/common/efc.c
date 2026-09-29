/* OCXO steering from the received carriers - see efc.h */
#include "efc.h"
#include <math.h>

#ifndef EFC_SLOPE_NOM
#define EFC_SLOPE_NOM 0.604e-9     /* CTI OSC5A2B02: 0.75 ppm/V x 3.3 V / 4096 codes */
#endif
#ifndef EFC_TAU
#define EFC_TAU      600.0         /* PLL natural period / 2 pi [s] */
#endif
#ifndef EFC_RATE
#define EFC_RATE     1.0e-10       /* max OCXO change [fraction per second] (DCF77 loop limit) */
#endif
#ifndef EFC_CAL_MIN
#define EFC_CAL_MIN  80.0          /* smallest calibration step [codes] */
#endif
#ifndef EFC_OUTLIER
#define EFC_OUTLIER  50e-9
#endif
#ifndef EFC_BIAS_TAU
#define EFC_BIAS_TAU 10800.0       /* e-CzasPL - DCF77 offset: 3 h average */
#endif
#ifndef EFC_BIAS_INIT
#define EFC_BIAS_INIT 10           /* minutes with both stations before e-CzasPL is used */
#endif
#ifndef EFC_DISAGREE
#define EFC_DISAGREE 10e-9
#endif
#define EFC_NOISE_N  60.0          /* noise estimates: 1 h average */
#ifndef EFC_TAU_MAXF
#define EFC_TAU_MAXF 6.0           /* adaptive loop: tau = EFC_TAU x sqrt(noise / EFC_VREF), at most this
                                      many times EFC_TAU (1 = fixed tau). efcsim night: 332 -> 98 ns */
#endif
#ifndef EFC_VREF
#define EFC_VREF     1.7e-18       /* (1.3 ppb)^2: DCF77's minute noise on the rod by day */
#endif
#ifndef EFC_BIAS_VMAX
#define EFC_BIAS_VMAX 4e-18        /* learn e-CzasPL's offset only while DCF77's minute noise is below
                                      2 ppb (daytime ground wave); frozen when DCF77 is noisy (night):
                                      a noisy reference leaks into the offset and the OCXO integrates it */
#endif
#ifndef EFC_WE_MAX
#define EFC_WE_MAX   0.0           /* cap on e-CzasPL's weight while DCF77 is there (0 = lock to DCF77 only;
                                      e-CzasPL's offset is still learned and it steers alone when DCF77 is lost) */
#endif
#define EFC_MAX 4095.0

static double clampc(double c) { return c < 0 ? 0 : c > EFC_MAX ? EFC_MAX : c; }

void efc_init(efc_t *f, double code, double slope)
{
    f->state = EFC_WAIT; f->src = EFC_SRC_NONE; f->n = f->skip = f->outliers = 0;
    f->c = f->target = f->c0 = f->cref = clampc(code); f->e = 0;
    f->slope = EFC_SLOPE_NOM;
    f->y0 = f->y1 = f->ysum = f->yprev = f->x = f->integ = f->y = 0;
    f->bias = f->bsum = 0; f->bn = 0;
    f->vd = f->ve = 2e-18; f->pyd = f->pye = 0; f->hd = f->he = 0; f->we = 0; f->veff = 0; f->tau = EFC_TAU;
    if (slope != 0) { f->slope = slope; f->state = EFC_LOCK; f->skip = 0; }
}

int efc_minute2(efc_t *f, int vd, double yd, int ve, double ye, double T)
{
    /* minute-to-minute noise of each station (Allan-like: half the squared first difference) */
    if (vd) { if (f->hd) { double d = yd - f->pyd; f->vd += (0.5 * d * d - f->vd) / EFC_NOISE_N; } f->pyd = yd; }
    if (ve) { if (f->he) { double d = ye - f->pye; f->ve += (0.5 * d * d - f->ve) / EFC_NOISE_N; } f->pye = ye; }
    f->hd = vd; f->he = ve;
    f->veff = vd ? f->vd : f->ve;                     /* noise of what steers (DCF77 alone / e-CzasPL alone) */
    int src = EFC_SRC_NONE; double y = 0;
    f->we = 0;
    if (vd && ve) {
        double r = ye - yd;
        if (f->bn < EFC_BIAS_INIT) {                  /* learning the offset first: DCF77 alone */
            f->bsum += r;
            if (++f->bn == EFC_BIAS_INIT) f->bias = f->bsum / EFC_BIAS_INIT;
            src = EFC_SRC_DCF77; y = yd;
        } else if (fabs(r - f->bias) > EFC_DISAGREE) {
            src = EFC_SRC_DCF77; y = yd;              /* one of them is wrong this minute */
        } else {
            if (f->vd < EFC_BIAS_VMAX) f->bias += (r - f->bias) * T / EFC_BIAS_TAU;
            double wd = 1 / f->vd, we = 1 / f->ve;
            f->we = we / (wd + we);
            if (f->we > EFC_WE_MAX) f->we = EFC_WE_MAX;
            y = f->we * (ye - f->bias) + (1 - f->we) * yd;
            f->veff = (1 - f->we) * (1 - f->we) * f->vd + f->we * f->we * f->ve;
            src = EFC_SRC_BOTH;
        }
    } else if (vd) { src = EFC_SRC_DCF77; y = yd; }
    else if (ve) { src = EFC_SRC_ECZAS; y = f->bn >= EFC_BIAS_INIT ? ye - f->bias : ye; f->we = 1; }
    efc_minute(f, src, y, T);
    return src;
}

static void to_wait(efc_t *f) { f->state = EFC_WAIT; f->n = 0; f->src = EFC_SRC_NONE; }

void efc_minute(efc_t *f, int src, double y, double T)
{
    f->y = y;
    switch (f->state) {
    case EFC_WAIT:
        if (src == EFC_SRC_NONE || src != f->src) { f->src = src; f->n = src ? 1 : 0; f->yprev = y; break; }
        f->n++;
        if (f->n >= 3) {
            f->y0 = 0.5 * (f->yprev + y);
            double step = 0.5 * f->y0 / EFC_SLOPE_NOM;
            if (fabs(step) < EFC_CAL_MIN) step = f->y0 < 0 ? -EFC_CAL_MIN : EFC_CAL_MIN;
            f->c0 = f->c;
            f->target = clampc(f->c + step);
            if (fabs(f->target - f->c0) < 0.5 * EFC_CAL_MIN) f->target = clampc(f->c - step);   /* at a rail */
            f->state = EFC_CAL_RAMP;
        }
        f->yprev = y;
        break;
    case EFC_CAL_RAMP:
    case EFC_CAL_MEAS:
        if (src == EFC_SRC_NONE) {                    /* source lost: start again */
            f->target = f->c0; to_wait(f); break;
        }
        f->src = src;                                 /* DCF77 <-> e-CzasPL: ~1 ppb, keep going */
        if (f->state == EFC_CAL_RAMP) {
            if (fabs(f->c - f->target) < 1e-6) { f->state = EFC_CAL_MEAS; f->skip = 1; f->n = 0; f->ysum = 0; }
            break;
        }
        if (f->skip) { f->skip--; break; }            /* the ramp may have ended inside that minute */
        f->ysum += y;
        if (++f->n < 2) break;
        f->y1 = f->ysum / 2;
        {
            double s = (f->y0 - f->y1) / (f->target - f->c0), r = s / EFC_SLOPE_NOM;
            if (fabs(r) >= 0.2 && fabs(r) <= 5) {
                f->slope = s;
                f->cref = clampc(f->target + f->y1 / s);
                f->target = f->cref;
                f->x = f->integ = 0; f->outliers = 0;
                f->skip = 1;                          /* settle: ramp to cref, then one more minute */
                f->state = EFC_LOCK;
            } else {
                f->slope = s;
                f->target = f->c0;
                f->state = EFC_FAIL;
            }
        }
        break;
    case EFC_LOCK:
        if (src == EFC_SRC_NONE) { f->src = src; break; }          /* holdover */
        f->src = src;
        if (f->skip) {                                /* still moving to the calibrated code */
            if (fabs(f->c - f->target) < 1e-6) f->skip--;
            break;
        }
        if (fabs(y) > EFC_OUTLIER) {
            if (++f->outliers >= 5) to_wait(f);
            break;
        }
        f->outliers = 0;
        {
            double r = f->veff > 0 ? sqrt(f->veff / EFC_VREF) : 1;
            if (r < 1) r = 1;
            if (r > EFC_TAU_MAXF) r = EFC_TAU_MAXF;
            f->tau += (EFC_TAU * r - f->tau) * T / 1800;  /* changes slowly (30 min) */
            if (f->tau < EFC_TAU) f->tau = EFC_TAU;
            const double wn = 1.0 / f->tau, kp = 2 * 0.7 * wn, ki = wn * wn;
            f->x += y * T;
            f->integ += ki * f->x * T;
            f->target = clampc(f->cref + (kp * f->x + f->integ) / f->slope);
        }
        break;
    case EFC_FAIL:
        f->src = src;
        break;
    }
}

int efc_tick(efc_t *f, double dt)
{
    double step = EFC_RATE / fabs(f->slope) * dt, d = f->target - f->c;
    f->c = fabs(d) <= step ? f->target : f->c + (d > 0 ? step : -step);
    double v = f->c + f->e;
    int q = (int)floor(v + 0.5);
    if (q < 0) q = 0;
    if (q > (int)EFC_MAX) q = (int)EFC_MAX;
    f->e = v - q;
    if (f->e > 1) f->e = 1;                           /* at a rail */
    if (f->e < -1) f->e = -1;
    return q;
}

const char *efc_state_txt(const efc_t *f)
{
    static const char *S[] = { "waiting", "calibrating (ramp)", "calibrating (measure)", "locked", "FAILED (EFC not responding)" };
    if (f->state == EFC_LOCK && f->skip) return "moving to the calibrated code";
    if (f->state == EFC_LOCK && f->src == EFC_SRC_NONE) return "holdover";
    return S[f->state];
}
