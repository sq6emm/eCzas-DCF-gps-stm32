#!/usr/bin/env python3
"""
Per-minute DCF77 decoder bench: firmware/host/dcfminsim (coh.c + dcf.c + dcfbits.c) on the noisy
inputs that dcfbench.py made (in_<cn0>_<seed>.c64: Kiwi Luisenfelde, GPS time base, crystal error,
calibrated noise), scored against the GPS truth minute by minute.

  dcfminbench.py RUNDIR START_UTC [--ppm -1.8] [--exe /r/firmware/host/dcfminsim]

Per level: minutes in the data, decoded (checks passed), confirmed, failed checks, WRONG decoded
(time != truth) and WRONG confirmed (must be 0), first confirmed minute after the start.
"""
import argparse, glob, os, re, subprocess, datetime as dt
from collections import defaultdict
from multiprocessing import Pool

ap = argparse.ArgumentParser()
ap.add_argument("run"); ap.add_argument("start")
ap.add_argument("--ppm", type=float, default=-1.8)
ap.add_argument("--exe", default="/r/firmware/host/dcfminsim")
a = ap.parse_args()
T0 = dt.datetime.strptime(a.start, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp()
B = 1 + a.ppm * 1e-6


def run(fn):
    o = subprocess.run([a.exe, fn, repr(T0), repr(B)], capture_output=True, text=True).stdout
    m = re.search(r"in_([-\d.]+)_(\d+)\.c64", fn)
    rows = []
    for l in o.splitlines():
        if not l.startswith("MIN "): continue
        f = l.split()
        rows.append(dict(n=int(f[1]), truth=int(f[2]), st=f[3], dec=int(f[4]), flips=int(f[9])))
    size = os.path.getsize(fn) // 8
    return float(m.group(1)), int(m.group(2)), size, rows


files = sorted(f for f in glob.glob(os.path.join(a.run, "in_*.c64")) if re.search(r"in_[-\d.]+_\d+\.c64$", f))
with Pool(min(len(files), 24)) as p:
    res = p.map(run, files)
agg = defaultdict(lambda: defaultdict(float))
for cn0, seed, size, rows in res:
    g = agg[cn0]
    g["runs"] += 1; g["minutes"] += size / 2000 / 60
    for r in rows:
        if r["st"] == "F": g["failed"] += 1; continue
        g["decoded"] += 1
        ok = r["dec"] == r["truth"]
        if not ok: g["wrong_dec"] += 1
        if r["st"] in ("C", "P"):
            g["confirmed"] += 1
            if r["st"] == "P": g["predicted"] += 1
            if not ok: g["wrong_conf"] += 1
        if r["flips"]: g["repaired"] += 1
    first = [r["n"] / 2000 / 60 for r in rows if r["st"] in ("C", "P")]
    g["first"] += min(first) if first else float("nan")
print(f"{'C/N0':>6s} | {'minutes':>7s} {'decoded':>8s} {'confirmed':>9s} {'failed':>6s} {'repaired':>8s} | "
      f"{'WRONG dec':>9s} {'WRONG conf':>10s} | {'1st conf min':>12s} {'by pred':>7s}")
for cn0 in sorted(agg, reverse=True):
    g = agg[cn0]; n = g["minutes"]
    print(f"{cn0:+6.0f} | {n / g['runs']:7.0f} {g['decoded'] / n:8.0%} {g['confirmed'] / n:9.0%} {g['failed'] / n:6.0%} "
          f"{g['repaired'] / n:8.0%} | {int(g['wrong_dec']):9d} {int(g['wrong_conf']):10d} | {g['first'] / g['runs']:12.1f} {g['predicted'] / n:7.0%}")
