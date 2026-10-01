#!/usr/bin/env python3
"""
Second timing of the IC-7610's SUB station (TDF or DCF77) against e-CzasPL on MAIN (226.000), both at
IF 13 kHz (mirrored) in the same stereo 48 kHz file: the recorder clock is common to both.

  tdf_vs_eczas_timing.py FRAMES.csv FILE...          SUB = TDF (dial 163.000)
  tdf_vs_eczas_timing.py --dcf FRAMES.csv FILE...    SUB = DCF77 (dial 78.500): the calibration run
  tdf_vs_eczas_timing.py --dcf-tdf FRAMES.csv FILE... MAIN = DCF77 (78.500), SUB = TDF (163.000): TDF - DCF77
  (FRAMES.csv: eczas-ic7610 out/frames.csv - which e-CzasPL time frames are in which file)

TDF: every second begins with a triangular phase element (+1 rad in 25 ms, -2 rad in 50 ms, +1 rad in
25 ms); the zero crossing in the middle, 50 ms after the element start, is the top of the UTC second
(ALS162 definition). Per second: fit of exp(j phi(t - tau)) with a free complex gain, tau on a 0.05 ms grid.
DCF77: the phase code (512 chips of 120 carrier cycles = 1.548 ms, the PTB sequence as in dcf.c) starts
200 ms after the second; per second the fit of |correlation| (the data bit inverts the sequence) of the
carrier phase with the chip sequence, tau on a 0.05 ms grid -> second = code start - 200 ms.
e-CzasPL: every regular time frame the processor decoded: the ideal frame from its N (make_frame), each bit
change a 18.6 ms linear phase ramp STARTING at the bit edge (measured, GUM: 19 ms); fit of the start to the
carrier phase with a linear trend removed -> the slot's start = the ramp start (GUM: 'transmission starts at
the beginning of the second'). Since 1 Oct 2026 (review): continuous models (tools/timing_models.py),
parabolic peak interpolation; the old step-model fit marked the ramp MIDDLE with a -0.2 ms bias.
Output per file: e-CzasPL second - SUB second (ms, mod 1 s); positive = e-CzasPL's second comes later.
The --dcf run checks the method against the NUCLEO (DCF77 second ~8.9 ms before e-CzasPL's at the board):
any difference is the method's / the radio's MAIN-SUB offset and is to be removed from the TDF result.
"""
import sys, os, csv, datetime as dt, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss
sys.path.insert(0, "/codec"); from eczas_codec import make_frame
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import timing_models as tm

DCF = sys.argv[1] == "--dcf"
DT = sys.argv[1] == "--dcf-tdf"
if DCF or DT: sys.argv.pop(1)
FS2 = 4000                                          # baseband rate
EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
frames = {}
for r in csv.reader(open(sys.argv[1])):
    if r[0].startswith("time"): continue
    if abs(float(r[2])) < 50: frames.setdefault(r[7], []).append(int(r[1]))   # regular frames only


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
        tau = tm.refine(sc, taus)                    # continuous model; parabolic peak (review 1 Oct)
        if tau is not None and sc.max() > 0.5 * np.abs(seg).sum():         # minute-marker second: no element
            out.append((c0 - k[0]) / FS2 + tau / 1000.0 + 0.050)           # zero crossing = UTC second
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
    prn = dcf_prn()
    n = len(ph) // FS2
    L = int(0.800 * FS2)
    t0, t1 = tm.intervals(np.arange(L), FS2, box=False)   # point samples (zero-phase FIR)
    def model(off_s):                                # code over 0..800 ms from the code start + off_s,
        return tm.dcf_code(t0, t1, off_s, prn)       # each sample = average over its interval (no plateaus)
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
        o = tm.refine(sc, offs)
        if o is not None:
            out.append(a / FS2 + o - 0.200)          # second = code start - 200 ms
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
        def score(T):                                # 18.6 ms linear ramps (timing_models.E_RAMP) STARTING at the bit edges
            m, mk = tm.eczas_phase(tt, T, bits)
            m = (m - m[mk].mean()) * mk
            return float(np.dot(seg, m))
        cand = np.arange(-0.100, 0.1001, 0.0005)
        s1 = np.array([score(t0 + c) for c in cand]); j = int(np.argmax(np.abs(s1)))
        fine = np.arange(cand[j] - 0.0006, cand[j] + 0.00061, 0.00005)
        s2 = np.array([score(t0 + c) for c in fine])
        T = tm.refine(s2, fine)
        if T is not None: out.append(t0 + T)         # = ramp START of the first bit change = the second
    return np.array(out)


res = []
for fn in sys.argv[2:]:
    name = os.path.basename(fn)
    t_name = dt.datetime.strptime(name[:15], "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc)
    fs, x = wf.read(fn); x = x.astype(float) / 32768
    zs = baseband(x[:, 1], fs); ze = baseband(x[:, 0], fs)
    if DT:                                           # MAIN DCF77, SUB TDF: TDF second - DCF77 second
        dc, td = dcf_seconds(ze), tdf_seconds(zs)
        d = np.array([((td[int(np.argmin(np.abs(td - T)))] - T) * 1000 + 500) % 1000 - 500 for T in dc])
        d = d[np.abs(d - np.median(d)) < 5]
        print(f"{name}: DCF77 {len(dc)} s, TDF {len(td)} s: TDF - DCF77 median {np.median(d):+.3f} ms, sd {np.std(d):.3f} ms "
              f"(per pair), standard error {np.std(d) / np.sqrt(len(d)):.3f} ms")
        res.append(np.median(d)); continue
    sub = dcf_seconds(zs) if DCF else tdf_seconds(zs)
    ecz = eczas_frames(ze, name, t_name)
    if len(sub) < 50 or not len(ecz):
        print(name, "too little:", len(sub), "SUB seconds,", len(ecz), "e-CzasPL frames"); continue
    k = np.round(sub - sub[0]); p = np.polyfit(k, sub, 1); r = (sub - np.polyval(p, k)) * 1e6
    good = np.abs(r) < 5 * np.median(np.abs(r)) + 50
    d = []
    for T in ecz:
        j = int(np.argmin(np.abs(sub - T)))
        d.append(((T - sub[j]) * 1000.0 + 500) % 1000 - 500)
    d = np.array(d)
    print(f"{name}: {'DCF77' if DCF else 'TDF'} {len(sub)} s (per-second sd {r[good].std():.0f} us), e-CzasPL {len(ecz)} frames: "
          f"e-CzasPL - {'DCF77' if DCF else 'TDF'} median {np.median(d):+.3f} ms, sd {np.std(d):.3f} ms")
    res.append(np.median(d))
if res:
    print(f"\n{len(res)} files: e-CzasPL second - {'DCF77' if DCF else 'TDF'} second at the receiver: "
          f"median {np.median(res):+.3f} ms, spread of file medians {np.std(res):.3f} ms" if not DT else
          f"\n{len(res)} files: TDF second - DCF77 second at the receiver: median {np.median(res):+.3f} ms, spread {np.std(res):.3f} ms")
