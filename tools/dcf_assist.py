#!/usr/bin/env python3
"""DCF77 from the NUCLEO's 77.5 kHz channel, assisted by eCzas time.

The antenna is tuned to 225 kHz, so DCF77 arrives far below the noise. But the
Nucleo knows UTC from eCzas, so the whole DCF77 amplitude pattern (second marks,
CEST time code, parity) is predictable: correlating coherently over many seconds
finds the carrier, and the delay of DCF77 against the eCzas timescale.

  dcf_assist.py LOGDIR [SINCE_UTC]      (SINCE: skip data before, e.g. 2026-09-27T17:38:10)
"""
import datetime as dt, glob, os, re, sys
import numpy as np, scipy.signal as ss

LOG = sys.argv[1]
SINCE = sys.argv[2] if len(sys.argv) > 2 else "2000"
FS = 2000.0

# --- eCzas time of dcf samples, from the TIMEMAP lines of the latest boot
tm = []
for l in open(os.path.join(LOG, "rx.log"), errors="replace"):
    if "TIMEMAP" not in l or l[:19] < SINCE[:19]: continue
    m = re.search(r"= eCzas (\d+)\.(\d+) \(unix\), dcf sample (\d+)", l)
    if m: tm.append((int(m[3]), int(m[1]) + int(m[2]) * 1e-6))
tm = np.array(tm)
tm = tm[np.r_[True, np.diff(tm[:, 0]) > 0]]                 # one boot only (increasing)
p = np.polyfit(tm[:, 0] / FS, tm[:, 1], 1)
res = tm[:, 1] - np.polyval(p, tm[:, 0] / FS)
b = p[0]                                                  # real seconds per labelled second
print(f"TIMEMAP: {len(tm)} points; sample clock (LSE) error {(1/b-1)*1e6:+.2f} ppm; fit residual {np.std(res)*1e6:.0f} us rms")
f_exp = 77500.0 * (b - 1)
print(f"-> the DCF77 carrier must appear at {f_exp:+.3f} Hz in the stream")

# --- assemble the 2 kHz stream by sample index (packets of 200)
n_lo = int(tm[0, 0])
chunks = {}
for fn in sorted(glob.glob(os.path.join(LOG, "dcf_*.c64"))):
    idx = np.loadtxt(fn.replace(".c64", ".idx.csv"), delimiter=",", skiprows=1, ndmin=2)
    raw = np.fromfile(fn, dtype="<f4")
    npk = min(len(idx), len(raw) // 400)
    for k in range(npk):
        n0 = int(idx[k, 0])
        if n0 >= n_lo - 200000 and n0 <= tm[-1, 0] + 20000:
            chunks[n0] = raw[400 * k: 400 * k + 400]
if not chunks: sys.exit("no DCF data for this boot")
n0 = min(chunks); n1 = max(chunks) + 200
z = np.full(n1 - n0, np.nan + 0j, dtype=complex)
for k, v in chunks.items():
    z[k - n0: k - n0 + 200] = v[0::2] + 1j * v[1::2]
good = ~np.isnan(z)
print(f"stream: {len(z)/FS:.0f} s, {100*good.mean():.1f} % present")
z[~good] = 0
t_utc = np.polyval(p, (np.arange(len(z)) + n0) / FS)       # eCzas UTC of every sample

# --- carrier: power spectrum near f_exp
zz = z * np.exp(-2j * np.pi * f_exp * np.arange(len(z)) / FS)
N = 1 << int(np.ceil(np.log2(len(zz))))
S = np.abs(np.fft.fftshift(np.fft.fft(zz, N))) ** 2
f = np.fft.fftshift(np.fft.fftfreq(N, 1 / FS))
near = np.abs(f) < 0.5; ref = (np.abs(f) > 1) & (np.abs(f) < 20)
k = np.argmax(S * near)
print(f"carrier: strongest line within +-0.5 Hz of the prediction at {f[k]:+.4f} Hz, "
      f"{10*np.log10(S[k]/np.median(S[ref])):.1f} dB above the median of 1..20 Hz "
      f"(bin {f[1]-f[0]:.4f} Hz)")
f_c = f_exp + f[k]

# --- predicted DCF77 amplitude for each second (1 = full, 0.15 = reduced)
def cest_bits(u_next_minute):
    t = dt.datetime.fromtimestamp(u_next_minute, dt.timezone.utc) + dt.timedelta(hours=2)   # CEST
    bits = [None] * 59
    bits[0] = 0
    for i in range(1, 15): bits[i] = None            # weather/civil data, encrypted
    bits[15] = 0; bits[16] = 0; bits[17] = 1; bits[18] = 0; bits[19] = 0; bits[20] = 1
    def bcd(v, n): return [((v // 10 ** (i // 4)) % 10 >> (i % 4)) & 1 for i in range(n)]
    def put(pos, vals): bits[pos:pos + len(vals)] = vals
    mi = [(t.minute % 10 >> i) & 1 for i in range(4)] + [(t.minute // 10 >> i) & 1 for i in range(3)]
    ho = [(t.hour % 10 >> i) & 1 for i in range(4)] + [(t.hour // 10 >> i) & 1 for i in range(2)]
    da = [(t.day % 10 >> i) & 1 for i in range(4)] + [(t.day // 10 >> i) & 1 for i in range(2)]
    wd = [(t.isoweekday() >> i) & 1 for i in range(3)]
    mo = [(t.month % 10 >> i) & 1 for i in range(4)] + [(t.month // 10) & 1]
    y = t.year % 100
    yr = [(y % 10 >> i) & 1 for i in range(4)] + [(y // 10 >> i) & 1 for i in range(4)]
    put(21, mi); bits[28] = sum(mi) % 2
    put(29, ho); bits[35] = sum(ho) % 2
    put(36, da); put(42, wd); put(45, mo); put(50, yr); bits[58] = sum(da + wd + mo + yr) % 2
    return bits

def model(t_utc):
    """expected amplitude (0.15/1, or 0.575 where the bit is unknown), and PM sign"""
    a = np.ones(len(t_utc))
    cache = {}
    for i in range(int(np.floor(t_utc[0])), int(np.floor(t_utc[-1])) + 1):   # t_utc is increasing
        s = i % 60
        if s == 59: continue
        mnext = i - s + 60
        if mnext not in cache: cache[mnext] = cest_bits(mnext)
        bit = cache[mnext][s]
        j0, j1, j2 = np.searchsorted(t_utc, [i, i + 0.1, i + 0.2])
        a[j0:j1] = 0.15
        if bit is None: a[j1:j2] = 0.575
        elif bit == 1: a[j1:j2] = 0.15
    return a

# --- coherent detection: carrier phase from a 20 s running average, then correlate
# the in-phase signal with the predicted amplitude over lags of -60..+60 ms
zc = z * np.exp(-2j * np.pi * f_c * np.arange(len(z)) / FS)
win = int(20 * FS)
cs = np.r_[0, np.cumsum(zc)]
i0 = np.clip(np.arange(len(zc)) - win // 2, 0, len(zc)); i1 = np.clip(np.arange(len(zc)) + win // 2, 0, len(zc))
ph = cs[i1] - cs[i0]                                     # 20 s running sum (phase only)
y = np.real(zc * np.exp(-1j * np.angle(ph))) * good
a0 = model(t_utc)
LMAX = 800                                                  # +-400 ms in 0.5 ms samples
lags = np.arange(-LMAX, LMAX + 1, 2) / FS
sc = []
for L in range(-LMAX, LMAX + 1, 2):
    a = np.roll(a0, L)                                     # DCF arrives L samples later than eCzas
    a = (a - a[good].mean()) * good
    sc.append(np.dot(y, a) / np.sqrt(np.dot(a, a)))
sc = np.array(sc)
kb = np.argmax(sc)
off = np.abs(lags - lags[kb]) > 0.25                       # outside the +-100..200 ms triangle
noise = np.std(sc[off]) if off.sum() > 20 else 1
print(f"AM correlation: best lag {lags[kb]*1e3:+.1f} ms, peak {(sc[kb]-np.mean(sc[off]))/noise:.1f} x the rms beyond +-250 ms")
print("  " + "  ".join(f"{lags[i]*1e3:+.0f}:{(sc[i]-np.mean(sc[off]))/noise:.1f}" for i in range(0, len(lags), 25)))

# --- phase code: fold the quadrature signal over seconds with a known data bit,
# sign-corrected by the bit, then correlate with every shift of the m-sequence
amp = np.abs(ph) / win + 1e-12
q = np.imag(zc * np.exp(-1j * np.angle(ph))) / amp * good
sec0 = int(np.ceil(t_utc[0])); sec1 = int(np.floor(t_utc[-1])) - 1
fold = np.zeros(int(FS)); nf = 0
cache = {}
for i in range(sec0, sec1):
    s_ = i % 60
    if s_ == 59 or (1 <= s_ <= 14): continue
    mnext = i - s_ + 60
    if mnext not in cache: cache[mnext] = cest_bits(mnext)
    bit = cache[mnext][s_]
    j = np.searchsorted(t_utc, i)
    if j + int(FS) > len(q) or not good[j:j + int(FS)].all(): continue
    fold += (1 - 2 * bit) * q[j:j + int(FS)]; nf += 1
fold /= max(nf, 1)
print(f"phase code: {nf} seconds folded")

def mseq(taps):
    st = [1] * 9; out = []
    for _ in range(511):
        out.append(st[-1])
        fb = 0
        for t in taps: fb ^= st[t - 1]
        st = [fb] + st[:-1]
    return np.array(out)
chip = 120 / 77500.0
tt = np.arange(int(FS)) / FS
best = None
F = np.fft.rfft(fold, 4096)
for name, taps in (("x9+x5+1", (9, 5)), ("x9+x4+1", (9, 4))):
    m = 1 - 2 * mseq(taps)                                 # +-1
    for sh in range(511):
        mm = np.roll(m, -sh)
        w = np.zeros(int(FS))
        k = ((tt - 0.2) / chip).astype(int)
        ok = (tt >= 0.2) & (k < 511)
        w[ok] = mm[k[ok]]
        w -= w.mean()
        cc = np.fft.irfft(F * np.conj(np.fft.rfft(w, 4096)), 4096)
        cc = np.r_[cc[-120:], cc[:121]]                    # lags -60..+60 ms (DCF later = +)
        kk = np.argmax(np.abs(cc))
        if best is None or abs(cc[kk]) > best[0]:
            best = (abs(cc[kk]), name, sh, (kk - 120) / FS, np.abs(cc))
        if sh == 0 and name == "x9+x5+1": ref_all = []
        ref_all.append(np.max(np.abs(cc)))
ref_all = np.array(ref_all)
print(f"phase code: best {best[1]} shift {best[2]}, lag {best[3]*1e3:+.1f} ms; peak {best[0]/np.median(ref_all):.2f} x the median best-peak of all 1022 candidates "
      f"(noise-only ~1.3-1.5; a real detection stands clearly above)")
print("  top candidates:", np.round(np.sort(ref_all)[-5:] / np.median(ref_all), 2))

# --- check of the predicted data bits: amplitude 100..200 ms after the (lag-corrected)
# second, relative to 300..900 ms, per predicted bit
lagA = lags[kb]
r0, r1 = [], []
for i in range(sec0, sec1):
    s_ = i % 60
    if s_ < 15 or s_ >= 59: continue
    bit = cache.get(i - s_ + 60, cest_bits(i - s_ + 60))[s_]
    j = np.searchsorted(t_utc, i + lagA)
    if j + int(FS) > len(y): continue
    mid = y[j + 200 + 20: j + 400 - 20].mean(); full = y[j + 600: j + 1800].mean()
    (r1 if bit else r0).append(mid / full)
print(f"bit check (amplitude at 110..190 ms / at 300..900 ms): predicted 0 -> {np.mean(r0):.2f} (n={len(r0)}), "
      f"predicted 1 -> {np.mean(r1):.2f} (n={len(r1)}); a correct prediction gives ~1 vs ~0.15")

# --- the Nucleo's eCzas timescale against the host (NTP) clock, via packet arrival
d = []
for fn in sorted(glob.glob(os.path.join(LOG, "dcf_*.idx.csv"))):
    idx = np.loadtxt(fn, delimiter=",", skiprows=1, ndmin=2)
    m = (idx[:, 0] >= tm[0, 0]) & (idx[:, 0] <= tm[-1, 0])
    last = idx[m, 0] + 199                                 # last sample of the packet
    d += list(idx[m, 1] - np.polyval(p, (last + 1) / FS))  # host arrival - eCzas time of packet end
d = np.array(d)
print(f"host arrival - eCzas time at the packet end: min {d.min()*1e3:+.1f} ms, 1st percentile {np.percentile(d,1)*1e3:+.1f} ms, "
      f"median {np.median(d)*1e3:+.1f} ms (UART 1606 bytes = 17.4 ms + USB; the host is NTP-synced)")

# --- expected phase-code SNR from the noise of the fold (q is normalised to the carrier)
seg = fold[int(0.2 * FS) + 30: int(0.99 * FS)]
sd = np.std(seg)
exp_snr = np.sin(np.radians(15.6)) * np.sqrt(len(seg)) / sd
print(f"fold noise {sd:.4f} (carrier = 1) per sample -> a +-15.6 deg code would correlate at ~{exp_snr:.1f} sigma "
      f"over {len(seg)} samples; the in-phase (AM) fold for comparison:")
yf = np.zeros(int(FS)); n2 = 0
for i in range(sec0, sec1):
    j = np.searchsorted(t_utc, i)
    if j + int(FS) <= len(y): yf += y[j:j + int(FS)]; n2 += 1
yf /= n2 * np.mean(np.abs(ph) / win)
print("  in-phase fold, 20 ms steps from the eCzas second:", " ".join(f"{v:.2f}" for v in yf[::40]))
