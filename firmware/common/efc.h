/*
 * OCXO steering (EFC) from BOTH received carriers, combined like a GPSDO combines its inputs:
 *  - e-CzasPL's own offset against DCF77 (PTB-steered, the accuracy reference) is learned slowly
 *    (EFC_BIAS_TAU, while both are locked) and removed from e-CzasPL;
 *  - the two are then weighted by their measured minute-to-minute noise (inverse variance), so
 *    the quieter station dominates the short term while DCF77 fixes the long term;
 *  - a minute where they disagree by more than EFC_DISAGREE uses DCF77 alone;
 *  - one station lost: the other alone (e-CzasPL with the learned offset); none: holdover.
 *
 * Input once a minute: the station's mean frequency against the OCXO time base, as a fraction
 * (y = freq_hz / F; y > 0 = the OCXO runs slow). Output every block: a DAC code, rate-limited
 * (the DCF77 carrier loop is only ~0.01 Hz wide and must not slip while the OCXO moves) and
 * dithered (first-order sigma-delta) between neighbouring codes for sub-LSB resolution.
 *
 *  WAIT  3 minutes on one source -> y0 (mean of the last 2)
 *  CAL   ramp half the way (nominal slope) or >= EFC_CAL_MIN codes, settle 1 min, measure 2 min
 *        -> y1; slope = (y0 - y1) / step. Wrong sign or 0.2..5 x the nominal size is accepted
 *        (and reported); anything else = EFC not responding -> back to the start code, FAIL.
 *  LOCK  second-order PLL on the carrier phase (time error x = integral of y), time constant
 *        EFC_TAU, damping 0.7; minutes with |y| > EFC_OUTLIER are skipped, 5 in a row -> WAIT.
 */
#ifndef EFC_H
#define EFC_H

enum { EFC_SRC_NONE = 0, EFC_SRC_DCF77, EFC_SRC_ECZAS, EFC_SRC_BOTH };
enum { EFC_WAIT = 0, EFC_CAL_RAMP, EFC_CAL_MEAS, EFC_LOCK, EFC_FAIL };

typedef struct {
    int    state, src, n, skip, outliers;
    double c, target, e;           /* current code (continuous), where it moves to, dither error */
    double slope;                  /* fraction per code (> 0: higher code = faster OCXO) */
    double y0, y1, ysum, yprev, c0, cref;
    double x, integ;               /* LOCK: time error [s], integrator [fraction] */
    double y;                      /* last (combined) measurement used */
    /* combination of the two stations */
    double bias, bsum; int bn;     /* e-CzasPL - DCF77 [fraction], learned */
    double vd, ve, pyd, pye; int hd, he;   /* minute-to-minute noise variances, previous values */
    double we;                     /* weight of e-CzasPL in the last combined minute */
} efc_t;

/* slope 0: calibrate first; otherwise the known slope [fraction per code] -> straight to LOCK */
void efc_init(efc_t *f, double code, double slope);
/* once a minute (T seconds): one station's measurement (src = EFC_SRC_DCF77 / ECZAS / NONE) */
void efc_minute(efc_t *f, int src, double y, double T);
/* once a minute: both stations; vd / ve = locked, yd / ye = measured fraction. Returns EFC_SRC_* used. */
int  efc_minute2(efc_t *f, int vd, double yd, int ve, double ye, double T);
/* every dt seconds: the DAC code to write now */
int  efc_tick(efc_t *f, double dt);
const char *efc_state_txt(const efc_t *f);

#endif
