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
#define EFC_MAX 4095.0

static double clampc(double c) { return c < 0 ? 0 : c > EFC_MAX ? EFC_MAX : c; }

void efc_init(efc_t *f, double code)
{
    f->state = EFC_WAIT; f->src = EFC_SRC_NONE; f->n = f->skip = f->outliers = 0;
    f->c = f->target = f->c0 = f->cref = clampc(code); f->e = 0;
    f->slope = EFC_SLOPE_NOM;
    f->y0 = f->y1 = f->ysum = f->yprev = f->x = f->integ = f->y = 0;
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
            const double wn = 1.0 / EFC_TAU, kp = 2 * 0.7 * wn, ki = wn * wn;
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
