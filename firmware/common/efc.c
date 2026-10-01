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
#ifndef EFC_V10REF
#define EFC_V10REF   6.25e-20      /* (0.25 ppb)^2: 10-min Allan variance of e-CzasPL - DCF77 by day (rod,
                                      29-30 Sep 06-17 UTC: 0.09-0.29 ppb). The loop also slows by
                                      sqrt(v10 / EFC_V10REF): the night's slow DCF77 wander (sky wave, tens of
                                      minutes) hardly shows in the minute differences. 0 = off */
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
#ifndef EFC_DBAD_HOLD
#define EFC_DBAD_HOLD 15          /* minutes e-CzasPL steers after DCF77 was grossly wrong */
#endif
#ifndef EFC_DBAD_BIG
#define EFC_DBAD_BIG  20e-9       /* ... i.e. this far off (white night noise stays below: efcsim) */
#endif
#ifndef EFC_TAU_GPS
#define EFC_TAU_GPS  600.0         /* PLL time constant while the GPS PPS steers: the NEO-7P PPS jitters
                                      ~15-20 ns per pulse (1 Oct 2026); shorter copies it into the OCXO,
                                      longer lets the OCXO's own wander through. Replay on the real OCXO
                                      (host/efcgpsreplay, 1 Oct 14:53-17:43): time error rms 300 s 17 ns,
                                      600 s 36 ns, 1000 s 97 ns, 2000 s 187 ns; simulation (host/efcgpssim,
                                      2 days): 600 s 16 ns, 1000 s 40-47 ns, 3000 s 619 ns */
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
    f->dbad = 0;
    f->r10sum = f->r10prev = f->v10 = 0; f->r10n = f->r10gap = 0; f->h10 = 0;
    f->gx_off = f->gx = 0; f->vg = 0; f->pyg = 0;
    if (slope != 0) { f->slope = slope; f->state = EFC_LOCK; f->skip = 0; }
}

/* the two stations: noise estimates, e-CzasPL's learned offset, which of them would steer (and with what y);
   nothing is steered here */
static int stations(efc_t *f, int vd, double yd, int ve, double ye, double T, double *yout)
{
    /* minute-to-minute noise of each station (Allan-like: half the squared first difference) */
    if (vd) { if (f->hd) { double d = yd - f->pyd; f->vd += (0.5 * d * d - f->vd) / EFC_NOISE_N; } f->pyd = yd; }
    if (ve) { if (f->he) { double d = ye - f->pye; f->ve += (0.5 * d * d - f->ve) / EFC_NOISE_N; } f->pye = ye; }
    f->hd = vd; f->he = ve;
    /* 10-min noise of e-CzasPL - DCF77 (independent of the OCXO steering): Allan variance of 10-min means,
       ~1 h average; a gap of more than 2 minutes starts a new pair of blocks */
    if (vd && ve) {
        f->r10gap = 0; f->r10sum += ye - yd;
        if (++f->r10n == 10) {
            double m = f->r10sum / 10;
            if (f->h10) { double d = m - f->r10prev; f->v10 += (0.5 * d * d - f->v10) / 6.0; }
            else if (f->v10 == 0) f->v10 = EFC_V10REF;
            f->r10prev = m; f->h10 = 1; f->r10sum = 0; f->r10n = 0;
        }
    } else if (++f->r10gap > 2) { f->r10sum = 0; f->r10n = 0; f->h10 = 0; }
    f->veff = vd ? f->vd : f->ve;                     /* noise of what steers (DCF77 alone / e-CzasPL alone) */
    int src = EFC_SRC_NONE; double y = 0;
    f->we = 0;
    if (f->dbad > 0) f->dbad--;
    if (vd && ve) {
        double r = ye - yd;
        if (f->bn < EFC_BIAS_INIT) {                  /* learning the offset first: DCF77 alone */
            f->bsum += r;
            if (++f->bn == EFC_BIAS_INIT) f->bias = f->bsum / EFC_BIAS_INIT;
            src = EFC_SRC_DCF77; y = yd;
        } else if (fabs(r - f->bias) > EFC_DISAGREE) {    /* one of them is wrong this minute */
            if (f->state == EFC_LOCK && fabs(yd) > EFC_DBAD_BIG && fabs(yd) > fabs(ye - f->bias))
                f->dbad = EFC_DBAD_HOLD;              /* DCF77 grossly off, further from y ~ 0 than e-CzasPL */
            if (f->dbad) { src = EFC_SRC_ECZAS; y = ye - f->bias; f->we = 1; f->veff = f->ve; }
            else { src = EFC_SRC_DCF77; y = yd; }
        } else if (f->dbad) {                         /* DCF77 was wrong recently: e-CzasPL steers */
            src = EFC_SRC_ECZAS; y = ye - f->bias; f->we = 1; f->veff = f->ve;
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
    *yout = y;
    return src;
}

int efc_minute2(efc_t *f, int vd, double yd, int ve, double ye, double T)
{
    double y; int src = stations(f, vd, yd, ve, ye, T, &y);
    efc_minute(f, src, y, T);
    return src;
}

int efc_minute3(efc_t *f, int vg, double xg, int vd, double yd, int ve, double ye, double T)
{
    double y; int src = stations(f, vd, yd, ve, ye, T, &y);   /* DCF77 / e-CzasPL stay ready as fallbacks */
    if (!vg) { efc_minute(f, src, y, T); return src; }
    /* the GPS PPS steers: xg = the measured phase (OCXO second behind the GPS second, > 0) with an arbitrary
       constant; when the GPS (re)takes over, that constant is set so the loop's phase continues smoothly */
    if (f->src != EFC_SRC_GPS || f->state != EFC_LOCK) f->gx_off = f->x - xg;
    double x = xg + f->gx_off;
    double yg = (x - f->x) / T;                       /* frequency of this minute (for the log / WAIT / CAL) */
    if (f->src == EFC_SRC_GPS) { double d = yg - f->pyg; f->vg += (0.5 * d * d - f->vg) / EFC_NOISE_N; }
    f->pyg = yg; f->gx = x;
    f->we = 0; f->veff = f->vg;
    efc_minute(f, EFC_SRC_GPS, yg, T);
    return EFC_SRC_GPS;
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
        if (src == EFC_SRC_GPS) {                      /* phase measured directly: PI on it */
            f->tau = EFC_TAU_GPS;
            const double wn = 1.0 / f->tau, kp = 2 * 0.7 * wn, ki = wn * wn;
            f->x = f->gx;
            f->integ += ki * f->x * T;
            f->target = clampc(f->cref + (kp * f->x + f->integ) / f->slope);
            break;
        }
        {
            double r = f->veff > 0 ? sqrt(f->veff / EFC_VREF) : 1;
            if (EFC_V10REF > 0 && f->we < 0.5 && f->v10 > 0) {      /* DCF77 steers */
                double r10 = sqrt(f->v10 / EFC_V10REF);
                if (r10 > r) r = r10;
            }
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
