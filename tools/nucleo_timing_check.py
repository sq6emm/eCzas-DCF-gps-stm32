#!/usr/bin/env python3
"""
Where the NUCLEO's seconds sit, checked against model fits on its own mixer outputs (2 kHz dumps).

  nucleo_timing_check.py LOGDIR STAMP        (e.g. /n/log 20260930_140019: ecz_/dcf_STAMP.c64 + .idx.csv, rx.log)

Both dumps are on the same 2 kHz sample index (n2k). Per 10-min block:
 e-CzasPL: raw = frame starts from a fit of the ideal frame (N from the FRAME lines, eczas_codec.make_frame)
           to the unwrapped carrier phase; firmware = the eCzas core's second boundary from the TIMEMAP lines
           (sample n = eCzas time t -> boundary at n - frac(t) * 2000).
 DCF77:    raw = phase-code start - 200 ms from a fit of the PTB chip sequence to the quadrature component
           (as tools/tdf_vs_eczas_timing.py); firmware = second mark + phase-code lag from the DCF77 lines.
All as ms of the n2k second (n2k mod 2000 / 2). The chain whose firmware value is off its raw fit has the delay.
"""
import sys, re, glob, datetime as dt, numpy as np
sys.path.insert(0, "/codec"); from eczas_codec import make_frame
D, ST = sys.argv[1], sys.argv[2]
FS = 2000
EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)


def load(kind):
    z = np.fromfile(f"{D}/{kind}_{ST}.c64", np.complex64).astype(complex)
    n0 = int(open(f"{D}/{kind}_{ST}.idx.csv").readlines()[1].split(",")[0])
    return z, n0


ze, ne0 = load("ecz"); zd, nd0 = load("dcf")
n1 = ne0 + len(ze)
# the log lines of this block
t0 = dt.datetime.strptime(ST, "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc)
lo, hi = (t0 - dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"), (t0 + dt.timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M")
tm, fr, dl = [], [], []
for raw in open(f"{D}/rx.log", "rb"):
    l = raw.decode(errors="ignore")
    if not (lo <= l[:16] <= hi): continue
    m = re.search(r"TIMEMAP audio sample (\d+) = eCzas (\d+\.\d+)", l)
    if m: tm.append((int(m.group(1)), float(m.group(2))))
    m = re.search(r"FRAME .*fixed \d+(?: \+ soft retry)?: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC", l)
    if m and "CLOCK" not in l: fr.append(m.group(1))
    m = re.search(r"DCF77   carrier .*second mark ([\d.]+) ms of the \w+ second.*phase code ([-+\d.]+) ms \(([\d.]+) sigma\)", l)
    if m: dl.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
# firmware e-CzasPL second (ms of the n2k second)
fe = [((n - (t % 1) * FS) % FS) / 2 for n, t in tm if ne0 <= n < n1]
print(f"e-CzasPL firmware (TIMEMAP, {len(fe)} lines): second at {np.median(fe):.2f} ms of the n2k second (sd {np.std(fe):.2f})")
ref = [(n, t) for n, t in tm if ne0 <= n < n1][0]
# raw e-CzasPL frame starts
ph = np.unwrap(np.angle(ze))
raws = []
for s in sorted(set(fr)):
    ts = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    N = int((ts - EPOCH).total_seconds()) // 3
    n_est = ref[0] + ((ts - EPOCH).total_seconds() + 946684800 - ref[1]) * FS - ne0   # index in ze (core's clock)
    a, b = int(n_est - 0.2 * FS), int(n_est + 2.2 * FS)
    if a < 0 or b > len(ph): continue
    seg = ph[a:b]; tt = np.arange(a, b) / FS
    seg = seg - np.polyval(np.polyfit(tt, seg, 1), tt)
    bits = np.array(make_frame(N, 2), float) * 2 - 1
    def score(T):
        idx = np.floor((tt - T) / 0.020).astype(int)
        m = np.where((idx >= 0) & (idx < 96), bits[np.clip(idx, 0, 95)], 0.0)
        m = m - m[m != 0].mean() * (m != 0)
        return float(np.dot(seg, m))
    c0 = n_est / FS
    cand = np.arange(-0.1, 0.1001, 0.0005); s1 = np.array([score(c0 + c) for c in cand]); j = int(np.argmax(np.abs(s1)))
    fine = np.arange(cand[j] - 0.0005, cand[j] + 0.00051, 0.00005); s2 = np.array([score(c0 + c) for c in fine])
    T = c0 + fine[int(np.argmax(np.abs(s2)))]
    raws.append(((T * FS + ne0) % FS) / 2)
raws = np.array(raws)
print(f"e-CzasPL raw fit ({len(raws)} frames): second at {np.median(raws):.2f} ms of the n2k second (sd {np.std(raws):.2f})")
# raw DCF77: phase code
ref1 = np.convolve(zd, np.ones(FS) / FS, mode="same")
q = np.imag(zd * np.conj(ref1)) / (np.abs(ref1) ** 2 + 1e-30)
sr, b1, prn = 0, 1, [0]  # PTB chip 0 is 0 (sequence 00000100011...); the register gives chips 1-511
for _ in range(511):
    sr = ((sr << 1) | b1) & 0x1FF; b1 = ((sr >> 4) & 1) ^ ((sr >> 8) & 1); prn.append(b1)
prn = 1.0 - 2.0 * np.array(prn); L = int(0.8 * FS); chip = 120.0 / 77500.0
def model(o):
    t = np.arange(L) / FS - o; c = np.floor(t / chip).astype(int)
    return np.where((c >= 0) & (c < 512), prn[np.clip(c, 0, 511)], 0.0)
m0 = model(0); m0 -= m0.mean(); n = len(q) // FS; acc = np.zeros(FS)
for s in range(n - 1):
    seg = q[s * FS: s * FS + FS + L]; seg = seg - seg.mean()
    acc += np.abs(np.correlate(seg, m0, mode="valid")[:FS])
i0 = int(np.argmax(acc)); offs = np.arange(-1, 1.0001, 0.05) / 1000
M = np.array([model(o) for o in offs]); M -= M.mean(axis=1, keepdims=True)
sec = []
for s in range(n - 1):
    a = s * FS + i0; seg = q[a:a + L]
    if len(seg) < L: break
    seg = seg - np.polyval(np.polyfit(np.arange(L), seg, 1), np.arange(L))
    sc = np.abs(M @ seg); j = int(np.argmax(sc))
    if 0 < j < len(offs) - 1: sec.append((((a + nd0) / FS + offs[j] - 0.2) * 1000) % 1000)
sec = np.array(sec)
print(f"DCF77 raw phase-code fit ({len(sec)} s, peak/median {acc[i0] / np.median(acc):.1f}): second at {np.median(sec):.2f} ms of the n2k second (sd {np.std(sec):.2f})")
for mk, pm, sg in dl:
    print(f"DCF77 firmware line: second mark {mk} ms + phase code {pm:+.1f} ms ({sg} sigma) = {mk + pm:.2f} ms")
e = np.median(raws); d = np.median(sec)
print(f"\nraw: e-CzasPL - DCF77 = {((e - d + 500) % 1000) - 500:+.2f} ms   (IC-7610: +16.6)")
if dl:
    fd = dl[-1][0] + dl[-1][1]; fe_ = np.median(fe)
    print(f"firmware: e-CzasPL - DCF77 = {((fe_ - fd + 500) % 1000) - 500:+.2f} ms   (the NUCLEO's DCF77 line: ~ +8.9)")
    print(f"firmware - raw: e-CzasPL {((fe_ - e + 500) % 1000) - 500:+.2f} ms, DCF77 {((fd - d + 500) % 1000) - 500:+.2f} ms")
