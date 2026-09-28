#!/usr/bin/env python3
"""
DCF77 tuning bench: GPS-timed Kiwi DCF77 (tools/kiwi, 2 kHz .c64 slots) made as weak as the
NUCLEO's reception, run through dcfsim variants (coh.c + dcf.c with -D overrides), scored
against the truth from the clean signal.

  dcfbench.py C64DIR START_UTC HOURS OUTDIR [--cn0 20,0,-10,-15,-20,-25] [--seeds 3]
              [--ppm -1.8] [--variants NAME=CFLAGS ...]

Truth: GPS time base (sample 0 = START_UTC); the clean run gives the DCF77 second start from
the second mark alone (x_mark) and with the phase code (x_pm); the DCF77 minute must be at
LSE second 59. Noisy runs: complex white noise for the wanted C/N0 (carrier power measured
on the clean data), time base scaled by the NUCLEO's crystal error (--ppm) and the carrier
offset that goes with it; dcfsim gets B = 1 + ppm so its DCF-UTC column stays comparable.
Per 10-min block: mark ok = |x_mark - truth| < 2 ms at sigma > threshold, wrong = sigma above
threshold but off; the same for the phase code (< 0.5 ms) and the minute.
"""
import argparse, glob, os, subprocess, sys, time, itertools, datetime as dt
from multiprocessing import Pool
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("c64"); ap.add_argument("start"); ap.add_argument("hours", type=float); ap.add_argument("out")
ap.add_argument("--cn0", default="20,0,-10,-15,-20,-25")
ap.add_argument("--seeds", type=int, default=3)
ap.add_argument("--ppm", type=float, default=-1.8)
ap.add_argument("--variants", nargs="*", default=["base="])
ap.add_argument("--src", default="/r/firmware")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
T0 = dt.datetime.strptime(a.start, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp()
N = int(a.hours * 3600 * 2000)

# ---- data ----
z = np.zeros(N, np.complex64); have = 0
for k in range(int(a.hours * 6)):
    fn = os.path.join(a.c64, time.strftime("%Y%m%d_%H%M%S", time.gmtime(T0 + 600 * k)) + ".c64")
    if os.path.exists(fn):
        z[k * 1200000:(k + 1) * 1200000] = np.fromfile(fn, np.complex64)[:1200000]; have += 1
print(f"{have}/{int(a.hours * 6)} slots from {a.start}", flush=True)
blk = z[: (N // 2000) * 2000].reshape(-1, 2000).mean(1)          # 1-s means: carrier (AM dips average in)
C = np.mean(np.abs(blk[np.abs(blk) > 0]) ** 2)
noise_in = np.var(z[: 2000 * 600] - np.repeat(blk[:600], 2000))    # rough noise of the clean data


def build(v):
    name, flags = v.split("=", 1)
    exe = f"{a.out}/dcfsim_{name}"
    src = a.src
    cmd = (f"gcc -O2 -Wall {flags} -I{src}/common -o {exe} {src}/host/dcfsim.c {src}/common/coh.c {src}/common/dcf.c -lm")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode: sys.exit(f"build {name}: {r.stderr}")
    return name, exe


def make(cn0, seed):
    """noisy, crystal-scaled copy of the data as .c64 file"""
    fn = f"{a.out}/in_{cn0}_{seed}.c64"
    if os.path.exists(fn): return fn
    y = z
    if a.ppm:
        e = a.ppm * 1e-6
        k = np.arange(N) * (1 + e)                                # LSE sample k is at true time k(1+e)/2000
        y = (np.interp(k, np.arange(N), z.real) + 1j * np.interp(k, np.arange(N), z.imag))
        y = y * np.exp(-2j * np.pi * 77500 * e * np.arange(N) / 2000)   # mixer at nominal 77.5 kHz of LSE time
    if cn0 is not None:
        rng = np.random.default_rng(seed)
        s2 = C * 2000 / 10 ** (cn0 / 10)                          # complex noise variance at 2 kHz
        y = y + (rng.normal(0, np.sqrt(s2 / 2), N) + 1j * rng.normal(0, np.sqrt(s2 / 2), N))
        y[z == 0] = 0                                             # keep the gaps
    y.astype(np.complex64).tofile(fn)
    return fn


def run(args):
    name, exe, cn0, seed = args
    fn = make(cn0, seed) if cn0 is not None else make(None, 0)
    B = 1 + (a.ppm * 1e-6 if a.ppm else 0)
    o = subprocess.run([exe, fn, "0", repr(T0), repr(B)], capture_output=True, text=True).stdout
    rows = []
    for l in o.splitlines():
        if not l[:1].isdigit(): continue
        f = l.replace("|", " ").split()
        n, st, fr, cn, err, mk, mks, mn, mns, pl, pls, x = f[:12]
        n = int(n); mk, mks, mns, pl, pls = map(float, (mk, mks, mns, pl, pls))
        # x_mark: second start from the mark alone (same formula as dcfsim, without the phase code)
        ns = (n - n % 2000) + mk * 2.0
        t = T0 + B * ns / 2000.0; xm = (t - np.floor(t + 0.5)) * 1000
        rows.append(dict(n=n, st=int(st), cn0=float(cn), mark_sig=mks, xm=xm, minute=int(mn), min_sig=mns,
                         pm_sig=pls, x=float(x)))
    return name, cn0, seed, rows


if __name__ == "__main__":
    exes = [build(v) for v in a.variants]
    base_exe = exes[0][1]
    _, _, _, clean = run(("clean", base_exe, None, 0))
    good = [r for r in clean if r["mark_sig"] > 20]
    xm_true = float(np.median([r["xm"] for r in good])) if good else float("nan")
    pmr = [r["x"] for r in clean if r["pm_sig"] > 10]
    x_true = float(np.median(pmr)) if pmr else float("nan")
    print(f"clean: {len(clean)} blocks, C/N0 {np.median([r['cn0'] for r in clean]):.1f} dB-Hz (dcfsim), "
          f"x_mark {xm_true:+.3f} ms, x_pm {x_true:+.3f} ms ({len(pmr)} blocks), minutes "
          f"{sorted(set(r['minute'] for r in clean if r['min_sig'] > 5))}", flush=True)
    cns = [float(c) for c in a.cn0.split(",")]
    jobs = [(nm, ex, c, s) for (nm, ex) in exes for c in cns for s in range(a.seeds)]
    for c in cns:
        for s in range(a.seeds): make(c, s)
    with Pool(min(len(jobs), 24)) as p:
        res = p.map(run, jobs)
    wrap = lambda d: (d + 500) % 1000 - 500
    print(f"{'variant':10s} {'C/N0':>6s} | {'reported':>8s} | {'mark ok':>7s} {'wrong':>5s} {'1st ok h':>8s} | "
          f"{'minute ok':>9s} {'wrong':>5s} | {'pm ok':>5s} {'wrong':>5s} {'pm rms us':>9s}")
    summary = []
    for (nm, _), c in itertools.product(exes, cns):
        R = [r for (n2, c2, s, rows) in res if n2 == nm and c2 == c for r in rows]
        nb = len(R) or 1
        mok = [r for r in R if r["mark_sig"] > 6 and abs(wrap(r["xm"] - xm_true)) < 2]
        mwr = [r for r in R if r["mark_sig"] > 6 and abs(wrap(r["xm"] - xm_true)) >= 2]
        first = [min([r["n"] for r in rows if r["mark_sig"] > 6 and abs(wrap(r["xm"] - xm_true)) < 2] or [np.nan]) / 2000 / 3600
                 for (n2, c2, s, rows) in res if n2 == nm and c2 == c]
        nok = [r for r in R if r["min_sig"] > 5 and r["minute"] == 59]
        nwr = [r for r in R if r["min_sig"] > 5 and r["minute"] != 59]
        pok = [r for r in R if r["pm_sig"] > 5 and abs(wrap(r["x"] - x_true)) < 0.5]
        pwr = [r for r in R if r["pm_sig"] > 5 and abs(wrap(r["x"] - x_true)) >= 0.5]
        rms = np.sqrt(np.mean([wrap(r["x"] - x_true) ** 2 for r in pok])) * 1000 if pok else float("nan")
        rep = np.median([r["cn0"] for r in R]) if R else float("nan")
        line = (f"{nm:10s} {c:+6.0f} | {rep:+8.1f} | {len(mok)/nb:7.0%} {len(mwr):5d} {np.nanmedian(first):8.2f} | "
                f"{len(nok)/nb:9.0%} {len(nwr):5d} | {len(pok)/nb:5.0%} {len(pwr):5d} {rms:9.0f}")
        print(line, flush=True); summary.append(line)
    open(f"{a.out}/summary.txt", "w").write("\n".join(summary) + "\n")
