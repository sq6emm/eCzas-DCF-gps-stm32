#!/usr/bin/env python3
"""
TDF / ALS162 time-code decoder, version 3: per-second complex least-squares fit with the learned
modulation shapes (no phase unwrapping, so it keeps working in noise).

  tdf_decode3.py --learn LEARN.wav [...] --test TEST.wav [...] [--cn0 dB-Hz] [--seed n]

Model for each second (window -100..+220 ms around the second start, 1 kHz complex baseband u,
amplitude-normalised by the carrier): u(t) = g * exp(j T(t)) + noise, g an unknown complex gain
(absorbs the phase offset the pseudo-random part leaves in each second, and fading). Three shapes:
T0 (bit 0: one +-0.8 rad cycle in 0..100 ms), T1 (bit 1: two cycles, 0..200 ms), TM (no
modulation: DCF77-like minute marker). err_k = |u|^2 - |<u, e^{jT_k}>|^2 / |e^{jT_k}|^2.
LLR(bit) = (err0 - err1) / sigma^2; minute marker when TM fits best.
Shapes are learned (phase domain) from the LEARN files at full strength, where the phase can be
read directly; the TEST files can have noise added (--cn0) for a sensitivity bench.
Minute decode: DCF77 layout, parity repair (least confident bit per failing group), BCD range
checks; the code gives the NEXT minute in French legal time; compared with the file clock.
"""
import sys, re, datetime as dt, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

args = sys.argv[1:]
def opt(name, conv, default):
    global args
    if name in args:
        i = args.index(name); v = conv(args[i + 1]); args = args[:i] + args[i + 2:]; return v
    return default
CN0 = opt("--cn0", float, None); SEED = opt("--seed", int, 1)
learn = args[args.index("--learn") + 1: args.index("--test")]
test = args[args.index("--test") + 1:]
t_name = lambda fn: dt.datetime.strptime(re.search(r"(\d{8}_\d{6})", fn).group(1), "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
W1 = [1, 2, 4, 8, 10, 20, 40, 80]
A, B = 100, 220                                  # window: -A .. +B ms around the second start


PROFILE = None                                  # activity fold of the learn data, second start at index 0
SHAPE = None                                    # learned bit-0 phase shape (set after learning)


def front(files, cn0=None):
    xs = []
    for fn in files:
        fs, x = wf.read(fn); xs.append(x[:, 1].astype(float) / 32768)
    y = np.concatenate(xs); T0 = t_name(files[0]); N = len(y)
    seg = y[: fs * 60]; w = np.hanning(len(seg)); f = np.fft.rfftfreq(len(seg), 1 / fs)
    P = np.abs(np.fft.rfft(seg * w)) ** 2 / (fs * (w ** 2).sum())
    k = np.abs(f - 13000) < 5; f0 = f[k][np.argmax(P[k])]
    pc = P[np.abs(f - f0) <= 0.25].sum() * (f[1] - f[0]); n0 = np.median(P[(np.abs(f - f0) > 10) & (np.abs(f - f0) < 80)])
    msg = f"C/N0 {10*np.log10(pc/n0):.1f} dB-Hz"
    if cn0 is not None:
        n0_t = pc / 10 ** (cn0 / 10)
        if n0_t > n0: y = y + np.random.default_rng(SEED).normal(0, np.sqrt((n0_t - n0) * fs / 2), N)
        msg += f" -> noise added to {cn0:.1f}"
    z = np.conj(y * np.exp(-2j * np.pi * f0 * np.arange(N) / fs))       # mirrored IF
    b, a = ss.butter(4, 300 / (fs / 2)); z = ss.filtfilt(b, a, z)[::fs // 1000]
    sos = ss.butter(2, 0.5, fs=1000, output="sos")
    amp = np.abs(ss.sosfiltfilt(sos, z.real) + 1j * ss.sosfiltfilt(sos, z.imag))
    u = z / (amp + 1e-30)                        # amplitude-normalised, phase untouched
    # second start: activity |u - u(25 ms mean)|^2 folded modulo 1 s, after the quietest 100 ms
    v = u - np.convolve(u, np.ones(25) / 25, mode="same")
    d = np.abs(v) ** 2; n = len(d) // 1000 * 1000
    fold = d[:n].reshape(-1, 1000).mean(0)
    if SHAPE is not None:                       # matched filter with the learned burst: |<u(t..), e^{jT0} - mean>|^2 folded
        h = np.exp(1j * SHAPE[A:A + 100]); h = h - h.mean()
        c = np.abs(np.convolve(u, np.conj(h[::-1]), mode="full")[99:99 + len(u)]) ** 2   # c[t] = |sum_k u[t+k] conj(h[k])|^2
        fm = c[:n].reshape(-1, 1000).mean(0)
        start = int(np.argmax(fm))
    elif PROFILE is None:                         # learn data (strong): after the quietest 100 ms
        qq = np.array([np.roll(fold, -j)[:100].mean() for j in range(1000)])
        start = (int(np.argmin(qq)) + 100) % 1000
    else:                                       # matched filter: circular cross-correlation with the learned profile
        fz = fold - fold.mean(); pz = PROFILE - PROFILE.mean()
        cc = np.real(np.fft.ifft(np.fft.fft(fz) * np.conj(np.fft.fft(pz))))
        start = int(np.argmax(cc))
    front.fold = np.roll(fold, -start)
    secs = [(T0 + s0 / 1000.0, u[s0 - A: s0 + B]) for s0 in range(start + 1000, n - 1000, 1000)]
    return f0, start, secs, msg


def decode_minutes(bits, conf, marks, t_of, label, verbose):
    res = dict(ok=0, repaired=0, wrong=0, failed=0, confirmed=0, confirmed_wrong=0)
    out = []
    groups = [(21, 29), (29, 36), (36, 59)]
    for i0, i1 in zip(marks[:-1], marks[1:]):
        if i1 - i0 != 60: continue
        b = list(bits[i0 + 1:i1]); c = list(conf[i0 + 1:i1]); flips = 0
        for lo, hi in groups:
            if sum(b[lo:hi]) % 2: j = lo + int(np.argmin(c[lo:hi])); b[j] ^= 1; flips += 1
        dig = lambda lo: sum(b[lo + k] << k for k in range(4))
        val = lambda lo, hi: sum(v * w for v, w in zip(b[lo:hi], W1))
        mi, hr, dy, mo, yr = val(21, 28), val(29, 35), val(36, 42), val(45, 50), val(50, 58)
        valid = (all(sum(b[lo:hi]) % 2 == 0 for lo, hi in groups) and b[20] == 1 and b[17] != b[18]
                 and mi < 60 and hr < 24 and 1 <= dy <= 31 and 1 <= mo <= 12
                 and all(dig(lo) < 10 for lo in (21, 29, 36, 45, 50, 54)))
        utc = dt.datetime.fromtimestamp(round(t_of[i0 + 1] / 60) * 60 + 60, dt.timezone.utc)
        loc = utc + dt.timedelta(hours=2 if b[17] else 1)
        right = (mi, hr, dy, mo, yr) == (loc.minute, loc.hour, loc.day, loc.month, loc.year % 100)
        t_code = (dt.datetime(2000 + yr, mo, dy, hr, mi, tzinfo=dt.timezone.utc) - dt.timedelta(hours=2 if b[17] else 1)).timestamp() if valid else None
        out.append((utc.timestamp(), t_code, right))
        if not valid: res["failed"] += 1; st = "failed"
        elif right: res["ok"] += 1; res["repaired"] += flips > 0; st = "CORRECT" + (f" ({flips} repaired)" if flips else "")
        else: res["wrong"] += 1; st = "WRONG"
        if verbose: print(f"  {label} {utc - dt.timedelta(minutes=1):%H:%M} UTC: 20{yr:02d}-{mo:02d}-{dy:02d} {hr:02d}:{mi:02d} -> {st}")
    # confirmation (as dcfbits): a decoded minute counts only if a neighbouring decode agrees
    for k, (tu, tc, right) in enumerate(out):
        if tc is None: continue
        nb = [out[j] for j in (k - 1, k + 1) if 0 <= j < len(out) and out[j][1] is not None]
        if any(abs((n[1] - tc) - (n[0] - tu)) < 1 for n in nb):
            res["confirmed"] += 1; res["confirmed_wrong"] += not right
    return res


# ---- learn the shapes (phase domain, full strength)
f0, st, L, msg = front(learn)
PROFILE = front.fold
ph = []
for t, u in L:
    ref = u[:A].mean(); ph.append(np.angle(u * np.conj(ref)))            # referred to the quiet 100 ms
ph = np.array(ph)
e1 = np.array([np.mean(np.abs(np.diff(p[A + 100:A + 200]))) for p in ph])  # activity 100..200 ms
eb = np.array([np.mean(np.abs(np.diff(p[A:A + 100]))) for p in ph])        # activity 0..100 ms
burst = eb > 0.5 * np.median(eb)
lo1, hi1 = np.percentile(e1[burst], 20), np.percentile(e1[burst], 80)
T0 = ph[burst & (e1 < lo1)].mean(0); T1 = ph[burst & (e1 > hi1)].mean(0); TM = np.zeros_like(T0)
print(f"LEARN {len(L)} s ({msg}), second start {st} ms; shapes from {int((burst & (e1 < lo1)).sum())} / {int((burst & (e1 > hi1)).sum())} seconds")
print("  bit0 " + " ".join(f"{v:+.2f}" for v in T0[::20]))
print("  bit1 " + " ".join(f"{v:+.2f}" for v in T1[::20]))
E = [np.exp(1j * T) for T in (T0, T1, TM)]
SHAPE = T0

# ---- test
f0, st, S, msg = front(test, CN0)
U = np.array([u for t, u in S]); tt = [t for t, u in S]
err = np.array([[np.sum(np.abs(u) ** 2) - np.abs(np.vdot(e, u)) ** 2 / np.real(np.vdot(e, e)) for e in E] for u in U])
sig2 = np.median(err.min(1)) / (A + B - 1)
llr = (err[:, 0] - err[:, 1]) / sig2
# minute marker: the second-of-minute where "no modulation" fits best, summed over all minutes
msc = (err[:, :2].min(1) - err[:, 2]) / sig2
ph60 = int(np.argmax([msc[p::60].sum() for p in range(60)]))
marks = list(range(ph60, len(U), 60))
print(f"  second start {st} ms; mean err T0/T1/TM {err.mean(0).round(1)}; sigma2*n {sig2*(A+B-1):.1f}")
bits = (llr > 0).astype(int)
print(f"TEST {len(S)} s ({msg}), {len(marks)} minute markers, |LLR| median {np.median(np.abs(llr)):.1f}")
r = decode_minutes(bits, np.abs(llr), marks, tt, "shape", "-v" in sys.argv)
print("SUMMARY", r)
