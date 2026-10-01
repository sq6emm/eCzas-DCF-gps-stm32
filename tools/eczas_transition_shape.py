#!/usr/bin/env python3
"""
Shape of e-CzasPL's phase transitions, from IC-7610 recordings (MAIN 226.000 = e-CzasPL, SUB 78.500 = DCF77).

  eczas_transition_shape.py FRAMES.csv FILE...        (in the eczas-ic705-proc image, codec in /codec)

Per decoded time frame: the frame start T from the ideal-NRZ fit (as tools/tdf_vs_eczas_timing.py) and
the DCF77 second (phase code - 200 ms). Averaged over isolated bit changes (two equal bits before, two
after; sign-normalised): the detrended carrier phase around T + 20 ms x k, as a fraction of the step.
Prints the 5/10/50/90/95 % points relative to the fitted edge and the median T - DCF77 second.
Result 30 Sep 16:00-17:20 (2550 transitions, 371 frames): a linear ramp of ~18 ms, -9 ... +9 ms around
the fitted edge (the NRZ fit finds the ramp's middle), step 31 deg; the frame's preamble (1010...) leaves
the idle phase 9.3 ms before the fitted start.
"""
import sys, os, csv, datetime as dt, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss
sys.path.insert(0, "/codec"); from eczas_codec import make_frame


import sys
FS2 = 4000
EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
frames = {}
for r in csv.reader(open(sys.argv[1])):
    if r[0].startswith("time"): continue
    if abs(float(r[2])) < 50: frames.setdefault(r[7], []).append(int(r[1]))

def baseband(y, fs):
    n = np.arange(len(y))
    z = np.conj(y * np.exp(-2j * np.pi * 13000.0 / fs * n))                   # mirrored IF
    return ss.resample_poly(z, 1, fs // FS2)                                   # zero-delay FIR


def tri(tp):                                        # ALS162 element, tp in ms from its start
    return np.where(tp < 0, 0, np.where(tp < 25, tp / 25, np.where(tp < 75, 1 - 2 * (tp - 25) / 50,
                    np.where(tp < 100, -1 + (tp - 75) / 25, 0))))


def tdf_seconds(z):
    k = np.arange(-40 * FS2 // 1000, 110 * FS2 // 1000)
    best = None
    for sgn in (1, -1):                              # coarse: fold |matched filter| over the file
        h = np.exp(1j * sgn * tri(k * 1000.0 / FS2))
        c = np.abs(np.convolve(z, np.conj(h[::-1]), mode="valid")) ** 2
        fold = c[: len(c) // FS2 * FS2].reshape(-1, FS2).sum(0)
        i = int(np.argmax(fold))
        if best is None or fold[i] > best[0]: best = (fold[i], sgn, i)
    _, sgn, i0 = best
    taus = np.arange(-1.0, 1.0001, 0.05)
    M = np.array([np.exp(1j * sgn * tri(k * 1000.0 / FS2 - tu)) for tu in taus])
    out = []
    for s in range(1, len(z) // FS2 - 1):
        c0 = s * FS2 + i0                            # window start (k[0]) of this second's element
        seg = z[c0: c0 + len(k)]
        if len(seg) < len(k): break
        sc = np.abs(M.conj() @ seg)
        j = int(np.argmax(sc))
        if 0 < j < len(taus) - 1 and sc[j] > 0.5 * np.abs(seg).sum():         # minute-marker second: no element
            out.append((c0 - k[0]) / FS2 + taus[j] / 1000.0 + 0.050)       # zero crossing = UTC second
    return np.array(out)


def dcf_prn():
    sr, b1, prn = 0, 1, [0]  # PTB chip 0 is 0 (sequence 00000100011...); the register gives chips 1-511
    for _ in range(511):
        sr = ((sr << 1) | b1) & 0x1FF
        b1 = ((sr >> 4) & 1) ^ ((sr >> 8) & 1)
        prn.append(b1)
    return np.array(prn)


def dcf_seconds(z):
    # the code's phase deviation as the quadrature component against a 1-s smoothed carrier (as dcf.c
    # does with the tracked carrier); the unwrapped phase wanders too much at ~25 dB-Hz: no correlation
    ref = np.convolve(z, np.ones(FS2) / FS2, mode="same")
    ph = np.imag(z * np.conj(ref)) / (np.abs(ref) ** 2 + 1e-30)
    chip = 120.0 / 77500.0
    prn = 1.0 - 2.0 * dcf_prn()
    n = len(ph) // FS2
    L = int(0.800 * FS2)
    def model(off_s):                                # code over 0..800 ms from the code start + off_s
        t = np.arange(L) / FS2 - off_s
        c = np.floor(t / chip).astype(int)
        return np.where((c >= 0) & (c < 512), prn[np.clip(c, 0, 511)], 0.0)
    m0 = model(0.0); m0 = m0 - m0.mean()
    acc = np.zeros(FS2)
    for s in range(n - 1):                           # coarse: fold |corr| over the file
        seg = ph[s * FS2: s * FS2 + FS2 + L]; seg = seg - seg.mean()
        c = np.correlate(seg, m0, mode="valid")[:FS2]
        acc += np.abs(c)
    i0 = int(np.argmax(acc))                         # code start, samples into each second of the file
    offs = np.arange(-1.0, 1.0001, 0.05) / 1000.0
    M = np.array([model(o) for o in offs]); M = M - M.mean(axis=1, keepdims=True)
    out = []
    for s in range(n - 1):
        a = s * FS2 + i0
        seg = ph[a: a + L]
        if len(seg) < L: break
        seg = seg - np.polyval(np.polyfit(np.arange(L), seg, 1), np.arange(L))
        sc = np.abs(M @ seg)
        j = int(np.argmax(sc))
        if 0 < j < len(offs) - 1:
            out.append(a / FS2 + offs[j] - 0.200)    # second = code start - 200 ms
    return np.array(out)


def eczas_frames(ze, name, t_name):
    ph = np.unwrap(np.angle(ze))
    out = []
    for N in frames.get(name, []):
        slot = EPOCH + dt.timedelta(seconds=3 * N)
        t0 = (slot - t_name).total_seconds() + 0.05                    # ~50 ms recorder latency
        a = int((t0 - 0.2) * FS2); b = int((t0 + 2.2) * FS2)
        if a < 0 or b > len(ph): continue
        seg = ph[a:b]; tt = np.arange(a, b) / FS2
        seg = seg - np.polyval(np.polyfit(tt, seg, 1), tt)
        bits = np.array(make_frame(N, 2), float) * 2 - 1
        def score(T):
            idx = np.floor((tt - T) / 0.020).astype(int)
            m = np.where((idx >= 0) & (idx < 96), bits[np.clip(idx, 0, 95)], 0.0)
            m = m - m[m != 0].mean() * (m != 0)
            return float(np.dot(seg, m))
        cand = np.arange(-0.100, 0.1001, 0.0005)
        s1 = np.array([score(t0 + c) for c in cand]); j = int(np.argmax(np.abs(s1)))
        fine = np.arange(cand[j] - 0.0005, cand[j] + 0.00051, 0.00005)
        s2 = np.array([score(t0 + c) for c in fine])
        out.append(t0 + fine[int(np.argmax(np.abs(s2)))])
    return np.array(out)


def eczas_frames_one(ze, ph, name, t_name, N):
    slot = EPOCH + dt.timedelta(seconds=3 * N)
    t0 = (slot - t_name).total_seconds() + 0.05
    a = int((t0 - 0.2) * FS2); b = int((t0 + 2.2) * FS2)
    if a < 0 or b > len(ph): return None
    seg = ph[a:b]; tt = np.arange(a, b) / FS2
    seg = seg - np.polyval(np.polyfit(tt, seg, 1), tt)
    bits = np.array(make_frame(N, 2), float) * 2 - 1
    def score(T):
        idx = np.floor((tt - T) / 0.020).astype(int)
        m = np.where((idx >= 0) & (idx < 96), bits[np.clip(idx, 0, 95)], 0.0)
        m = m - m[m != 0].mean() * (m != 0)
        return float(np.dot(seg, m))
    cand = np.arange(-0.100, 0.1001, 0.0005)
    s1 = np.array([score(t0 + c) for c in cand]); j = int(np.argmax(np.abs(s1)))
    fine = np.arange(cand[j] - 0.0005, cand[j] + 0.00051, 0.00005)
    s2 = np.array([score(t0 + c) for c in fine])
    return t0 + fine[int(np.argmax(np.abs(s2)))]

W0, W1 = -0.040, 0.040
K = np.arange(int(W0*FS2), int(W1*FS2))
acc = np.zeros(len(K)); nacc = 0; offs = []
for fn in sys.argv[2:]:
    name = os.path.basename(fn)
    t_name = dt.datetime.strptime(name[:15], "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc)
    fs, x = wf.read(fn); x = x.astype(float) / 32768
    zs = baseband(x[:, 1], fs); ze = baseband(x[:, 0], fs)
    sub = dcf_seconds(zs)
    ph = np.unwrap(np.angle(ze))
    for N in frames.get(name, []):
        Ts = eczas_frames_one(ze, ph, name, t_name, N)
        if Ts is None: continue
        j = int(np.argmin(np.abs(sub - Ts))); offs.append(((Ts - sub[j]) * 1000 + 500) % 1000 - 500)
        bits = np.array(make_frame(N, 2), float) * 2 - 1
        a = int((Ts - 0.1) * FS2); b = int((Ts + 2.1) * FS2)
        seg = ph[a:b]; tt = np.arange(a, b)
        seg = seg - np.polyval(np.polyfit(tt, seg, 1), tt)
        for k in range(2, 94):
            if not (bits[k-2] == bits[k-1] != bits[k] == bits[k+1]): continue
            c = int(round((Ts + 0.020 * k) * FS2)) - a
            w = seg[c + K[0]: c + K[-1] + 1]
            if len(w) != len(K): continue
            acc += w * (bits[k] - bits[k-1]) / 2; nacc += 1
    print(name, len(offs), "frames so far", flush=True)
m = acc / nacc
lo = m[int(-0.038*FS2) - K[0]:int(-0.026*FS2) - K[0]].mean(); hi = m[int(0.026*FS2) - K[0]:int(0.038*FS2) - K[0]].mean()   # levels away from the edge
s = (m - lo) / (hi - lo)
def cross(p): i = int(np.argmax(s > p)); return (K[i-1] + (p - s[i-1]) / (s[i] - s[i-1])) / FS2 * 1000
print(f"transitions averaged {nacc}, frames {len(offs)}; fitted frame start (step model) - DCF77 second at the receiver: median {np.median(offs):+.2f} ms")
print("phase transition around the fitted bit edge (0 ms): 5% {:+.2f}, 10% {:+.2f}, 50% {:+.2f}, 90% {:+.2f}, 95% {:+.2f} ms".format(*[cross(p) for p in (0.05,0.1,0.5,0.9,0.95)]))
print("shape (ms : fraction):", " ".join(f"{K[i]/FS2*1000:+.0f}:{s[i]:.2f}" for i in range(0, len(K), 8)) + '\nlevels: lo %.3f hi %.3f rad (step %.1f deg)' % (lo, hi, np.degrees(hi - lo)))
