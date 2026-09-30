#!/usr/bin/env python3
"""
Carrier frequency difference of the IC-7610's MAIN and SUB stations, both on one radio clock.

  ic7610_carrier_cmp.py F_MAIN F_SUB FILE...      (10-min stereo 48 kHz WAVs of icomlan.py: ch 0 MAIN, ch 1 SUB)

Both stations are tuned so that the carrier lands at IF 13 kHz (mirrored IF: IF = 12 kHz - (f - dial)).
Per file and channel: carrier phase in 1-s means (the stations' data modulation averages out), linear fit
-> the IF offset delta (Hz, sample-clock units). With the radio's common clock error eps, a station's
fractional offset is y = eps - delta / f; eps cancels in y_MAIN - y_SUB = delta_SUB / F_SUB - delta_MAIN / F_MAIN.
Recorder gaps (lost packets) shift both channels alike; files with a phase-fit residual above 0.3 rad or
less than 5 min are left out. Printed per file and as the median.

NOT an absolute comparison (checked 30 Sep 2026): e-CzasPL (MAIN 226.000) - DCF77 (SUB 78.500) came out
+1.98e-8 (sd 0.4e-9 over 5 files, 16-17 UTC) where the NUCLEO measures -0.85e-9. The radio adds a constant
offset per dial setting of ~1e-8 (the direct-sampling radio tunes in finite digital steps; both IF offsets
~+61 / +23 mHz from its ~0.27 ppm clock, not in the exact station-frequency ratio). Usable only for
changes over time at fixed dial settings, not for station offsets at the 1e-9 level.
"""
import sys, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

FM, FS_ = float(sys.argv[1]), float(sys.argv[2])
IF = 13000.0
rows = []
for fn in sys.argv[3:]:
    try: fs, x = wf.read(fn)
    except Exception as e: print(fn, "unreadable:", e); continue
    if x.ndim != 2 or len(x) < fs * 300: continue
    d = []
    for ch in (0, 1):
        s = x[:, ch].astype(float)
        n = np.arange(len(s))
        z = s * np.exp(-2j * np.pi * IF / fs * n)                    # IF 13 kHz -> 0 Hz
        z = ss.resample_poly(z, 1, 48)                              # 1 kHz (FIR low-pass)
        m = len(z) // 1000
        zz = z[:m * 1000].reshape(m, 1000).mean(axis=1)             # 1-s means
        ph = np.unwrap(np.angle(zz))
        t = np.arange(m) + 0.5
        p = np.polyfit(t, ph, 1)
        res = np.std(ph - np.polyval(p, t))
        d.append((p[0] / (2 * np.pi), res, 20 * np.log10(np.abs(zz).mean() + 1e-9)))
    (dm, rm, lm), (dsub, rs, ls_) = d
    ok = rm < 0.3 and rs < 0.3
    y = dsub / FS_ - dm / FM
    rows.append((fn.split("/")[-1], dm, dsub, y, ok))
    print(f"{fn.split('/')[-1]}: MAIN delta {dm*1e3:+8.3f} mHz (res {rm:.2f} rad)  SUB delta {dsub*1e3:+8.3f} mHz (res {rs:.2f} rad)"
          f"  -> MAIN - SUB {y:+.3e}{'' if ok else '  (left out)'}")
good = [r[3] for r in rows if r[4]]
if good:
    print(f"\n{len(good)} files: MAIN - SUB median {np.median(good):+.3e}, mean {np.mean(good):+.3e}, "
          f"sd {np.std(good):.2e}, standard error {np.std(good)/np.sqrt(len(good)):.1e}")
