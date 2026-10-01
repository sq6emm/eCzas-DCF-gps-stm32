#!/usr/bin/env python3
"""Track the DCF77 timing against the Nucleo's e-CzasPL timescale per 10-minute UTC block.

For every complete block it writes one line to OUT (csv):
  block_utc, seconds, dcf_carrier_db, pm_sigma, pm_lag_ms, pm30_sigma, pm30_lag_ms,
  am_sigma, am_lag_ms, lse_ppm, timemap_resid_us, eczas_decoded, eczas_confirmed, eczas_noise_deg
pm = exact PTB phase code (19.8 sigma / -8.5 ms over 2.5 h on 27 Sep); pm30 = the same over
the last three blocks; lags: + = DCF77 later than the Nucleo's e-CzasPL second.
  dcf_track.py LOGDIR OUT.csv [--once]"""
import datetime as dt, glob, os, re, sys, time
import numpy as np

LOG, OUT = sys.argv[1], sys.argv[2]
ONCE = "--once" in sys.argv
FS, BLK, CHIP = 2000.0, 600, 120 / 77500.0
LAG_C, LAG_W = -8.5e-3, 15e-3                      # search window around the known lag

def iso(u): return dt.datetime.fromtimestamp(u, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")

def prn():
    sr, b1, out = 0, 1, [0]  # PTB chip 0 is 0 (sequence 00000100011...); the register gives chips 1-511
    for _ in range(511):
        sr = ((sr << 1) | b1) & 0x1FF
        b1 = ((sr >> 4) & 1) ^ ((sr >> 8) & 1)
        out.append(b1)
    return np.array(out)
PRN = prn()
tt = (np.arange(int(FS)) + 0.5) / FS
kc = np.floor((tt - 0.2) / CHIP).astype(int)
okc = (tt >= 0.2) & (kc < 512)
W = np.zeros(int(FS)); W[okc] = 1 - 2 * PRN[kc[okc]]; W -= W.mean(); W /= np.sqrt(np.dot(W, W))

_bits = {}
def last_sunday_0100(year, month):
    d = dt.datetime(year, month, 31 if month in (3, 10) else 30, 1, tzinfo=dt.timezone.utc)
    return (d - dt.timedelta(days=(d.weekday() + 1) % 7)).timestamp()

def is_cest(u):
    y = dt.datetime.fromtimestamp(u, dt.timezone.utc).year
    return last_sunday_0100(y, 3) <= u < last_sunday_0100(y, 10)

def cest_bits(u_next):
    """DCF77 time-code bits for the minute starting at UTC u_next (CET/CEST)"""
    if u_next in _bits: return _bits[u_next]
    summer = is_cest(u_next)
    t = dt.datetime.fromtimestamp(u_next, dt.timezone.utc) + dt.timedelta(hours=2 if summer else 1)
    b = [None] * 60
    b[0] = 0; b[15] = 0; b[16] = 0
    b[17], b[18] = (1, 0) if summer else (0, 1)
    b[19] = 0; b[20] = 1
    mi = [(t.minute % 10 >> i) & 1 for i in range(4)] + [(t.minute // 10 >> i) & 1 for i in range(3)]
    ho = [(t.hour % 10 >> i) & 1 for i in range(4)] + [(t.hour // 10 >> i) & 1 for i in range(2)]
    da = [(t.day % 10 >> i) & 1 for i in range(4)] + [(t.day // 10 >> i) & 1 for i in range(2)]
    wd = [(t.isoweekday() >> i) & 1 for i in range(3)]
    mo = [(t.month % 10 >> i) & 1 for i in range(4)] + [(t.month // 10) & 1]
    y = t.year % 100
    yr = [(y % 10 >> i) & 1 for i in range(4)] + [(y // 10 >> i) & 1 for i in range(4)]
    b[21:28] = mi; b[28] = sum(mi) % 2; b[29:35] = ho; b[35] = sum(ho) % 2
    b[36:42] = da; b[42:45] = wd; b[45:50] = mo; b[50:58] = yr; b[58] = sum(da + wd + mo + yr) % 2
    _bits[u_next] = b
    return b

def pm_bit(u):
    s = u % 60
    if s <= 9: return 1                                # minute marker: inverted
    if s <= 14: return 0
    if s == 59: return None
    return cest_bits(u - s + 60)[s]

def am_level(u):
    """expected amplitude profile of second u, 2000 samples (0.15 = reduced, 0.575 = unknown)"""
    s = u % 60
    a = np.ones(int(FS))
    if s == 59: return a
    a[:200] = 0.15
    b = cest_bits(u - s + 60)[s]
    if b is None: a[200:400] = 0.575
    elif b == 1: a[200:400] = 0.15
    return a

def timemap():
    """(dcf_sample, eczas_unix) of the latest boot, plus e-CzasPL frames and noise per line"""
    tm, ev = [], []
    for l in open(os.path.join(LOG, "rx.log"), errors="replace"):
        if "TIMEMAP" in l:
            m = re.search(r"= eCzas (\d+)\.(\d+) \(unix\), dcf sample (\d+)", l)
            if m: tm.append((int(m[3]), int(m[1]) + int(m[2]) * 1e-6))
        elif "] FRAME" in l or "] STATUS" in l:
            ev.append(l)
    tm = np.array(tm)
    if len(tm) == 0: return tm, ev
    brk = np.where(np.diff(tm[:, 0]) < 0)[0]
    if len(brk): tm = tm[brk[-1] + 1:]
    return tm, ev

def load_block(tm, u0, u1):
    """complex 2 kHz samples mapped to e-CzasPL time for [u0-30 s, u1+30 s)"""
    near = (tm[:, 1] > u0 - 900) & (tm[:, 1] < u1 + 900)
    if near.sum() < 20: return None
    p = np.polyfit(tm[near, 0] / FS, tm[near, 1], 1)
    res = tm[near, 1] - np.polyval(p, tm[near, 0] / FS)
    n_lo = int((u0 - 30 - p[1]) / p[0] * FS); n_hi = int((u1 + 30 - p[1]) / p[0] * FS)
    z = np.zeros(n_hi - n_lo, complex); good = np.zeros(n_hi - n_lo, bool)
    for fn in sorted(glob.glob(os.path.join(LOG, "dcf_*.c64"))):
        idx = np.loadtxt(fn.replace(".c64", ".idx.csv"), delimiter=",", skiprows=1, ndmin=2)
        if len(idx) == 0 or idx[-1, 0] + 200 < n_lo or idx[0, 0] > n_hi: continue
        if idx[0, 0] > idx[-1, 0]: continue
        raw = np.fromfile(fn, dtype="<f4")
        for k in range(min(len(idx), len(raw) // 400)):
            n0 = int(idx[k, 0])
            if n0 + 200 <= n_lo or n0 >= n_hi: continue
            v = raw[400 * k:400 * k + 400]; zz = v[0::2] + 1j * v[1::2]
            a, b = max(n0, n_lo), min(n0 + 200, n_hi)
            z[a - n_lo:b - n_lo] = zz[a - n0:b - n0]; good[a - n_lo:b - n_lo] = True
    t = np.polyval(p, (np.arange(n_lo, n_hi)) / FS)
    return z, good, t, (1 / p[0] - 1) * 1e6, np.std(res) * 1e6

def analyse(z, good, t, u0, u1):
    f_exp = 0.0                                        # stream is in LSE time; refine the line
    N = 1 << 22
    Z = np.abs(np.fft.fftshift(np.fft.fft(z * good, N))) ** 2
    f = np.fft.fftshift(np.fft.fftfreq(N, 1 / FS))
    m = np.abs(f) < 0.3; k = np.argmax(Z * m)
    carrier_db = 10 * np.log10(Z[k] / np.median(Z[(np.abs(f) > 1) & (np.abs(f) < 20)]))
    zc = z * np.exp(-2j * np.pi * f[k] * np.arange(len(z)) / FS)
    win = int(20 * FS); cs = np.r_[0, np.cumsum(zc * good)]
    i = np.arange(len(zc)); ph = cs[np.clip(i + win // 2, 0, len(zc))] - cs[np.clip(i - win // 2, 0, len(zc))]
    rot = np.exp(-1j * np.angle(ph)); amp = np.abs(ph) / win + 1e-12
    q = np.imag(zc * rot) / amp; y = np.real(zc * rot) / amp
    D = np.zeros(int(FS)); n0 = n1 = 0
    Ay = 0.0; rows = []
    for u in range(int(u0), int(u1)):
        j = np.searchsorted(t, u)
        if j < 0 or j + int(FS) > len(q) or not good[j:j + int(FS)].all(): continue
        rows.append((u, j))
        b = pm_bit(u)
        if b == 0: D += q[j:j + int(FS)]; n0 += 1
        elif b == 1: D -= q[j:j + int(FS)]; n1 += 1
    if not rows: return None
    D = D / max(1, n0 + n1) * 2
    return carrier_db, D, rows, y, len(rows)

def pm_peak(D):
    lags = np.arange(int((LAG_C - 60e-3) * FS), int((LAG_C + 60e-3) * FS) + 1)
    cc = np.array([np.dot(np.roll(D, -L), W) for L in lags])
    sig = 1.4826 * np.median(np.abs(cc - np.median(cc)))
    inw = np.abs(lags / FS - LAG_C) <= LAG_W
    kb = np.where(inw)[0][np.argmax(np.abs(cc[inw]))]
    frac = 0.0
    if 0 < kb < len(cc) - 1:
        y1, y2, y3 = np.abs(cc[kb - 1:kb + 2]); den = y1 - 2 * y2 + y3
        frac = 0.5 * (y1 - y3) / den if den else 0.0
    return abs(cc[kb]) / sig, (lags[kb] + frac) / FS * 1e3

def am_peak(y, rows):
    best = None; sc = []
    L_all = np.arange(-60, 41, 2)                   # samples, 1 ms steps
    for L in L_all:
        s = 0.0; nn = 0.0
        for u, j in rows:
            if j + L < 0 or j + L + int(FS) > len(y): continue
            a = am_level(u) - 0.87
            s += np.dot(y[j + L:j + L + int(FS)], a); nn += np.dot(a, a)
        sc.append(s / np.sqrt(nn))
    sc = np.array(sc)
    kb = np.argmax(sc)
    return (sc[kb] - np.median(sc)) / (1.4826 * np.median(np.abs(sc - np.median(sc))) + 1e-12), L_all[kb] / FS * 1e3

def eczas_stats(ev, u0, u1):
    dec = conf = 0; noise = []
    for l in ev:
        try: ts = dt.datetime.fromisoformat(l[:23]).replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError: continue
        if not (u0 <= ts < u1): continue
        if "] FRAME" in l:
            if "confirmed" in l: conf += 1
            elif "UTC" in l: dec += 1
        m = re.search(r"noise ([\d.]+) deg", l)
        if m: noise.append(float(m[1]))
    return dec, conf, (np.median(noise) if noise else float("nan"))

def main():
    done = set()
    if os.path.exists(OUT):
        done = {l.split(",")[0] for l in open(OUT) if l[:2] == "20"}
    else:
        open(OUT, "w").write("block_utc,seconds,dcf_carrier_db,pm_sigma,pm_lag_ms,pm30_sigma,pm30_lag_ms,"
                             "am_sigma,am_lag_ms,lse_ppm,timemap_resid_us,eczas_decoded,eczas_confirmed,eczas_noise_deg\n")
    hist = {}
    while True:
        tm, ev = timemap()
        if len(tm) > 20:
            u_first = tm[0, 1]; u_last = tm[-1, 1]
            u = int(np.ceil(u_first / BLK) * BLK)
            while u + BLK + 60 <= u_last:
                key = iso(u)
                if key not in done:
                    try:
                        blk = load_block(tm, u, u + BLK)
                        r = analyse(*blk[:3], u, u + BLK) if blk else None
                        if r:
                            cdb, D, rows, y, nsec = r
                            hist[u] = D * nsec
                            np.save(os.path.join(os.path.dirname(OUT), f"D_{u}.npy"), hist[u])
                            for v in (u - 2 * BLK, u - BLK):          # survive restarts
                                fn = os.path.join(os.path.dirname(OUT), f"D_{v}.npy")
                                if v not in hist and os.path.exists(fn): hist[v] = np.load(fn)
                            ps, pl = pm_peak(D)
                            prev = [hist[v] for v in (u - 2 * BLK, u - BLK, u) if v in hist]
                            p3s, p3l = pm_peak(sum(prev) / sum(1 for _ in prev) / nsec) if len(prev) == 3 else (float("nan"), float("nan"))
                            asg, alg = am_peak(y, rows)
                            d, c, nz = eczas_stats(ev, u, u + BLK)
                            line = (f"{key},{nsec},{cdb:.1f},{ps:.1f},{pl:+.3f},{p3s:.1f},{p3l:+.3f},{asg:.1f},{alg:+.1f},"
                                    f"{blk[3]:+.3f},{blk[4]:.0f},{d},{c},{nz:.1f}\n")
                        else:
                            line = f"{key},0,,,,,,,,,,,,\n"
                    except Exception as e:
                        line = f"{key},error {type(e).__name__}: {e},,,,,,,,,,,,\n"
                    open(OUT, "a").write(line); print(line, end="", flush=True); done.add(key)
                u += BLK
        if ONCE: break
        time.sleep(120)

main()
