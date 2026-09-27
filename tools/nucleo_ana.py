#!/usr/bin/env python3
"""Compare a NUCLEO audio dump (10 kHz, carrier ~1 kHz) with the IC-705 slot table.
Usage: nucleo_ana.py nucleo_X.wav [ic705 slots.csv]"""
import csv, datetime as dt, subprocess, sys
import numpy as np, scipy.signal as ss, scipy.io.wavfile as wf

PRE = np.array([int(b) for b in "0101010101010101" + "01100000"])
fn = sys.argv[1]
slots_fn = sys.argv[2] if len(sys.argv) > 2 else "/data/claude/eczas-ic705/out/slots.csv"
fs, x = wf.read(fn); x = x.astype(float)
idx = np.loadtxt(fn.replace(".wav", ".idx.csv"), delimiter=",", skiprows=1)
n = idx[:, 0] - idx[0, 0]; h = idx[:, 1]
p = np.polyfit(n / fs, h, 1)
res = h - np.polyval(p, n / fs)
t0 = p[1] + np.percentile(res, 2) - 0.0245            # UTC of sample 0: min latency, minus packet + UART time
print(f"{fn}: {len(x)/fs:.0f} s, host clock vs sample clock {(p[0]-1)*1e6:+.0f} ppm, latency spread {np.ptp(res)*1e3:.0f} ms")

# spectrum around the carrier
f, P = ss.welch(x, fs, nperseg=1 << 15)
def band(a, b): m = (f > a) & (f < b); return 10 * np.log10(P[m].mean())
fc = f[(f > 950) & (f < 1050)][np.argmax(P[(f > 950) & (f < 1050)])]
print(f"carrier {fc:.2f} Hz; density dB: carrier bin {10*np.log10(P[np.argmin(abs(f-fc))]):.1f}, "
      f"+-20..60 Hz {band(fc+20, fc+60):.1f}/{band(fc-60, fc-20):.1f}, 1.3-2 kHz {band(1300, 2000):.1f}, "
      f"image 0-0.5 kHz {band(50, 500):.1f}, 3-4.5 kHz {band(3000, 4500):.1f}")

# phase track, 1 ms steps
t = np.arange(len(x)) / fs
z = x * np.exp(-2j * np.pi * fc * t)
b, a = ss.butter(4, 100 / (fs / 2)); z = ss.filtfilt(b, a, z)[:: fs // 1000]
ph = np.unwrap(np.angle(z)); amp = np.abs(z)

ic = {}
for r in csv.reader(open(slots_fn)):
    ic[r[0]] = r
def iso(u): return dt.datetime.fromtimestamp(u, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def slot_dev(u, off):
    i0 = int(round((u - t0 + off) * 1000))
    if i0 < 1000 or i0 + 2950 > len(ph): return None
    pre = np.median(ph[i0 - 900:i0 - 100]); post = np.median(ph[i0 + 2050:i0 + 2900])
    tt = np.arange(-100, 2000)
    ref = pre + (post - pre) * (tt + 500) / 2975.0
    return np.degrees(ph[i0 - 100:i0 + 2000] - ref)

u0 = 3 * int(np.ceil((t0 + 2) / 3)); u1 = t0 + len(x) / fs - 4
times = [u for u in range(u0, int(u1), 3) if iso(u) in ic and ic[iso(u)][1] == "time"]
print(f"{len(times)} slots with an IC-705 time frame in this file")
# timing: search the offset that maximises preamble agreement over all such slots
best = None
for off in np.arange(-0.3, 0.3, 0.002):
    sc = 0
    for u in times:
        d = slot_dev(u, off)
        if d is None: continue
        bits = (d[100 + 20 * np.arange(24) + 10] > -22).astype(int)
        sc += (bits == PRE).sum()
    if best is None or sc > best[0]: best = (sc, off)
off = best[1]
print(f"best time offset {off*1e3:+.0f} ms, preamble bits right {best[0]}/{24*len(times)}")
v0, v1 = [], []
for u in times:
    d = slot_dev(u, off)
    if d is None: continue
    m = d[100 + 20 * np.arange(24)[:, None] + np.arange(4, 17)[None, :]].mean(1)   # bit centres
    v0 += list(m[PRE == 0]); v1 += list(m[PRE == 1])
    bits = (m > -22).astype(int)
    print(f"  {iso(u)} IC-705 {ic[iso(u)][2]:>10} snr {ic[iso(u)][3]:>5} | nucleo preamble {(bits==PRE).sum():2d}/24, "
          f"'1' {np.mean(m[PRE==1]):+6.1f}  '0' {np.mean(m[PRE==0]):+6.1f} deg, spread {np.std(np.r_[m[PRE==1]-np.mean(m[PRE==1]), m[PRE==0]-np.mean(m[PRE==0])]):5.1f}")
if v0:
    sep = np.mean(v1) - np.mean(v0); sd = np.sqrt((np.var(v0) + np.var(v1)) / 2)
    print(f"ALL: '1' {np.mean(v1):+.1f} deg, '0' {np.mean(v0):+.1f} deg, separation {sep:.1f} deg, noise {sd:.1f} deg "
          f"-> {20*np.log10(sep/2/sd):+.1f} dB (need about +6 dB)")
