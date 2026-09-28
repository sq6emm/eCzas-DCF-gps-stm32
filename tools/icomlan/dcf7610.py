#!/usr/bin/env python3
"""IC-7610 SUB receiver (dial 78.500 kHz USB, mirrored LAN IF: DCF77 at 13000 Hz) -> DCF77 analysis
with the NUCLEO's own code (coh.c + dcf.c + dcfbits.c via firmware/host/dcfsim, dcfminsim).

  dcf7610.py REC OUT FIRST_NAME
REC: 10-min stereo 48 kHz WAVs from icomlan.py (channel 1 = SUB). Each finished file becomes
OUT/c64/<name>.c64 (2 kHz complex float32, DCF77 at 0 Hz). Every hour (at hh:01) dcfsim and dcfminsim
run over the last 6 h (gaps zero-filled, starting at the first file); OUT/dcfmin.csv gets one line per
hour: minutes decoded / confirmed / failed and confirmed minutes that differ from the file-name clock
(host time, chrony; the LAN adds ~0.05-0.1 s, far below a minute). OUT/dcfsim_*.txt keep the full output.
The time base is the host clock, not GPS: second-mark and phase-code timing are only relative."""
import os, sys, re, glob, time, subprocess, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

REC, OUT, FIRST = sys.argv[1], sys.argv[2], sys.argv[3]
C64 = OUT + "/c64"; os.makedirs(C64, exist_ok=True)
SIM, MINSIM = "/r/firmware/host/dcfsim", "/r/firmware/host/dcfminsim"
SLOT = 600


def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), *a, flush=True)


def t_of(name):
    return int(time.mktime(time.strptime(name[:15], "%Y%m%d_%H%M%S")) - time.timezone)


def convert(fn, out):
    fs, x = wf.read(fn)
    x = x[:, 1].astype(np.float64) / 32768
    n = np.arange(len(x))
    z = x * np.exp(-2j * np.pi * 13000.0 / fs * n)          # DCF77 to 0 Hz
    z = np.conj(z)                                          # the IF is mirrored
    z = ss.resample_poly(z, 1, fs // 2000)                  # 2 kHz (its own anti-alias filter)
    want = SLOT * 2000
    z = np.concatenate([z, np.zeros(max(0, want - len(z)), complex)])[:want]
    z.astype(np.complex64).tofile(out + ".part"); os.replace(out + ".part", out)


def hourly(end):
    start = end - 6 * 3600
    while start < end and not os.path.exists(f"{C64}/{time.strftime('%Y%m%d_%H%M%S', time.gmtime(start))}.c64"):
        start += SLOT
    if start >= end: return
    tmp, have = "/tmp/dcf6h.c64", 0
    with open(tmp, "wb") as f:
        for t in range(start, end, SLOT):
            fn = f"{C64}/{time.strftime('%Y%m%d_%H%M%S', time.gmtime(t))}.c64"
            if os.path.exists(fn): f.write(open(fn, "rb").read()); have += 1
            else: f.write(np.zeros(SLOT * 2000, np.complex64).tobytes())
    name = time.strftime("%Y%m%d_%H%M", time.gmtime(end))
    o = subprocess.run([SIM, tmp, "0", str(start), "1"], capture_output=True, text=True).stdout
    open(f"{OUT}/dcfsim_{name}.txt", "w").write(o)
    m = subprocess.run([MINSIM, tmp, str(start), "1"], capture_output=True, text=True)
    open(f"{OUT}/dcfminsim_{name}.txt", "w").write(m.stdout + m.stderr)
    last_h = end - 3600
    cnt = {"C": 0, "P": 0, "U": 0, "F": 0}; wrong = 0
    for l in m.stdout.splitlines():
        p = l.split()
        if len(p) < 5 or p[0] != "MIN": continue
        n_end, truth, st, dec = int(p[1]), int(p[2]), p[3], int(p[4])
        if start + n_end / 2000 < last_h: continue            # only the last hour
        cnt[st] = cnt.get(st, 0) + 1
        if st in ("C", "P") and dec != truth: wrong += 1
    rows = [l for l in o.splitlines() if l and l[0].isdigit()]
    last = " ".join(rows[-1].replace("|", " ").split()) if rows else "-"
    line = f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(end))},{have},{cnt['C']},{cnt['P']},{cnt['U']},{cnt['F']},{wrong},{last.replace(' ', ',')}"
    new = not os.path.exists(OUT + "/dcfmin.csv")
    with open(OUT + "/dcfmin.csv", "a") as f:
        if new: f.write("hour_end,slots_6h,confirmed,confirmed_pred,unconfirmed,failed,confirmed_wrong,last_dcfsim_row...\n")
        f.write(line + "\n")
    log("hour", line)


done_hour = None
while True:
    for fn in sorted(glob.glob(REC + "/*.wav")):
        b = os.path.basename(fn)[:-4]
        out = f"{C64}/{b}.c64"
        if b < FIRST or os.path.exists(out) or t_of(b) % SLOT: continue
        try: convert(fn, out); log("c64", b)
        except Exception as e: log("ERROR", b, e)
    now = time.time(); end = int(now // 3600) * 3600
    if now - end > 60 and end != done_hour:
        done_hour = end
        try: hourly(end)
        except Exception as e: log("ERROR hourly", e)
    time.sleep(20)
