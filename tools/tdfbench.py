#!/usr/bin/env python3
"""
TDF decoder bench: firmware/host/tdfsim (coh.c + tdf.c) on a clean 2 kHz TDF recording with complex
white noise added for a target C/N0, scored against the file clock minute by minute.

  tdfbench.py CLEAN.c64 START_UTC OUTDIR [--cn0 30,25,22,20,18,16] [--seeds 3] [--exe /tmp/tdfsim]

Per level (summed over the seeds): minutes evaluated, confirmed, confirmed by the expected frame, unconfirmed,
failed; WRONG confirmed and WRONG by expected frame (both must be 0), wrong unconfirmed (allowed: never used).
"""
import argparse, os, subprocess, datetime as dt, numpy as np
from multiprocessing import Pool

ap = argparse.ArgumentParser()
ap.add_argument("clean"); ap.add_argument("start"); ap.add_argument("out")
ap.add_argument("--cn0", default="30,25,22,20,18,16"); ap.add_argument("--seeds", type=int, default=3)
ap.add_argument("--exe", default="/tmp/tdfsim")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
T0 = dt.datetime.strptime(a.start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
z = np.fromfile(a.clean, np.complex64).astype(complex)
fs = 2000.0
seg = z[: int(fs * 120)]; w = np.hanning(len(seg)); f = np.fft.fftfreq(len(seg), 1 / fs)
P = np.abs(np.fft.fft(seg * w)) ** 2 / (fs * (w ** 2).sum())
k = np.abs(f) < 2; i = np.where(k)[0][np.argmax(P[k])]
pc = P[np.abs(f - f[i]) <= 0.25].sum() * (f[1] - f[0])
n0 = np.median(P[(np.abs(f - f[i]) > 10) & (np.abs(f - f[i]) < 80)])
print(f"clean: carrier {f[i]*1000:+.1f} mHz, C/N0 {10*np.log10(pc/n0):.1f} dB-Hz, {len(z)/fs:.0f} s")

def make(args):
    cn0, seed = args
    fn = f"{a.out}/in_{cn0}_{seed}.c64"
    if not os.path.exists(fn):
        n0t = pc / 10 ** (cn0 / 10)
        s = np.sqrt(max(n0t - n0, 0) * fs / 2)
        r = np.random.default_rng(seed)
        (z + s * (r.standard_normal(len(z)) + 1j * r.standard_normal(len(z)))).astype(np.complex64).tofile(fn)
    o = subprocess.run([a.exe, fn, repr(T0)], capture_output=True, text=True).stdout
    c = dict(C=0, U=0, F=0, P=0, wC=0, wU=0, wP=0)
    for l in o.splitlines():
        p = l.split()
        if len(p) < 5 or p[0] != "MIN": continue
        c[p[3]] = c.get(p[3], 0) + 1
        if p[3] in ("C", "U", "P") and p[2] != p[4]: c["w" + p[3]] += 1
    return cn0, seed, c

jobs = [(float(c), s) for c in a.cn0.split(",") for s in range(a.seeds)]
with Pool(min(len(jobs), 12)) as pool:
    res = pool.map(make, jobs)
import collections
agg = collections.defaultdict(collections.Counter)
for cn0, seed, c in res: agg[cn0].update(c)
print("  C/N0 | minutes | confirmed + by expected frame = total | unconfirmed failed | WRONG conf WRONG exp | wrong unconf")
for cn0 in sorted(agg, reverse=True):
    c = agg[cn0]; n = c["C"] + c["P"] + c["U"] + c["F"]
    print(f"  {cn0:4.0f} | {n:7d} | {c['C']:9d} + {c['P']:3d} = {c['C'] + c['P']:3d} ({100 * (c['C'] + c['P']) / max(n, 1):3.0f} %) | {c['U']:11d} {c['F']:6d} | {c['wC']:10d} {c['wP']:9d} | {c['wU']:12d}")
