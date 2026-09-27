#!/usr/bin/env python3
"""Old eCzas core (sim, SI4735-style audio path) vs the coherent chain (cohsim) on the same
recordings. Truth per file = the majority N - round(t/3) of all decoded frames of both.
  compare_old_new.py SIM COHSIM file.wav [file.wav ...] [--noise dB]"""
import re, subprocess, sys, collections, os
import numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

sim, coh = sys.argv[1], sys.argv[2]
noise = None
files = []
args = sys.argv[3:]
while args:
    a = args.pop(0)
    if a == "--noise": noise = args.pop(0)
    else: files.append(a)
LINE = re.compile(r"^\s*([\d.]+) corr=[\d.]+ N=(\d+)")

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout

tot = collections.Counter()
print(f"{'file':28s} {'noise':>5s} | {'old: dec conf wrong unl':>26s} | {'new: dec conf wrong unl':>26s}")
for fn in files:
    fs, x = wf.read(fn)
    x = x.astype(float)
    if noise is not None:                                    # the same noise for both chains
        rng = np.random.default_rng(1)
        x = x + rng.normal(0, np.sqrt(np.mean(x ** 2)) / 10 ** (float(noise) / 20), len(x))
    x = np.clip(x * (20000 / (np.max(np.abs(x)) + 1e-9)), -32767, 32767).astype(np.int16)
    base = "/tmp/" + os.path.basename(fn)[:-4]
    if fs == 10000:
        x.tofile(base + "_10k.raw"); old_in = base + "_10k.raw"; new_in = [base + "_10k.raw"]
    else:                                                    # 8 kHz IC-705: the old sim needs 10 kHz
        y = ss.resample_poly(x.astype(float), 5, 4)
        (y / (np.max(np.abs(y)) + 1e-9) * 20000).astype("<i2").tofile(base + "_10k.raw")
        x.tofile(base + "_8k.raw")
        old_in = base + "_10k.raw"; new_in = ["-8", base + "_8k.raw"]
    nz = []
    o1 = run([sim] + nz + [old_in]); o2 = run([coh] + nz + new_in)
    pairs = [(float(m[1]), int(m[2])) for o in (o1, o2) for l in o.splitlines() for m in [LINE.match(l)] if m]
    if not pairs: print(f"{os.path.basename(fn):28s} no frames"); continue
    off = collections.Counter(n - round(t / 3) for t, n in pairs).most_common(1)[0][0]
    t0 = 0.0; n0 = off
    res = []
    for cmd in ([sim] + nz + ["-r", str(t0), str(n0), old_in], [coh] + nz + ["-r", str(t0), str(n0)] + new_in):
        o = run(cmd)
        s = dict(re.findall(r"(\w+)=([\-\d.]+)", [l for l in o.splitlines() if l.startswith("SUMMARY")][0]))
        u = dict(re.findall(r"(\w+)=([\-\d.]+)", [l for l in o.splitlines() if l.startswith("LOCK")][0]))
        res.append((int(s["time_ok"]), int(s["confirmed"]), int(s["clock_wrong"]) + int(s["confirm_wrong"]), float(u["unlocked_s"])))
    for tag, r in zip(("old", "new"), res):
        tot[tag + "_dec"] += r[0]; tot[tag + "_conf"] += r[1]; tot[tag + "_wrong"] += r[2]
    print(f"{os.path.basename(fn):28s} {noise or '-':>5s} | {res[0][0]:6d} {res[0][1]:5d} {res[0][2]:5d} {res[0][3]:6.0f}s | "
          f"{res[1][0]:6d} {res[1][1]:5d} {res[1][2]:5d} {res[1][3]:6.0f}s")
print(f"{'TOTAL':28s} {noise or '-':>5s} | {tot['old_dec']:6d} {tot['old_conf']:5d} {tot['old_wrong']:5d}        | "
      f"{tot['new_dec']:6d} {tot['new_conf']:5d} {tot['new_wrong']:5d}")
