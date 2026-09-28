#!/usr/bin/env python3
"""
TDF / ALS162 (Allouis, 162 kHz) time-code decoder, first version, on IC-7610 SUB recordings
(dial 163.000 kHz USB, mirrored LAN IF: the carrier at ~13000 Hz, channel 1 of the stereo files).

What the signal showed (28 Sep 2026 22:20, 48 dB-Hz): +-1 rad phase modulation; per second a
quiet ~100 ms, then a burst of 100 ms (bit 0) or 200 ms (bit 1), the rest of the second a denser
pseudo-random modulation. This decoder is data-driven:
  1. carrier -> 1 kHz complex baseband (conjugated: mirrored IF), phase detrended per 10 s
  2. |d phase| folded modulo 1 s -> the second start = the edge after the quiet gap
  3. per second: modulation energy in 0-100 ms (burst present?) and 100-200 ms (bit 1?)
  4. minute: the second without a burst (like DCF77's second 59)
  5. bits 0..58 decoded with the DCF77 layout (BCD minute/hour/day/weekday/month/year, parities),
     compared with the file-name clock (UTC; the code is expected in French legal time, CET/CEST)

  tdf_decode.py FILE.wav [FILE2.wav ...]   (consecutive 10-min files, stitched)
"""
import sys, re, datetime as dt, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

files = sys.argv[1:]
t_name = lambda fn: dt.datetime.strptime(re.search(r"(\d{8}_\d{6})", fn).group(1), "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
xs = []
for fn in files:
    fs, x = wf.read(fn); xs.append(x[:, 1].astype(float) / 32768)
y = np.concatenate(xs); T0 = t_name(files[0]); N = len(y)

# carrier: strongest line near 13 kHz
seg = y[: fs * 60]; S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))); f = np.fft.rfftfreq(len(seg), 1 / fs)
k = np.abs(f - 13000) < 5; f0 = f[k][np.argmax(S[k])]
z = np.conj(y * np.exp(-2j * np.pi * f0 * np.arange(N) / fs))
b, a = ss.butter(4, 300 / (fs / 2)); z = ss.filtfilt(b, a, z)[::fs // 1000]          # 1 kHz
ph = np.unwrap(np.angle(z))
for i in range(0, len(ph), 10000):                                                  # detrend per 10 s
    s = ph[i:i + 10000]; t = np.arange(len(s)); ph[i:i + 10000] = s - np.polyval(np.polyfit(t, s, 1), t)
d = np.abs(np.diff(ph, prepend=ph[0]))
n = len(d) // 1000 * 1000
D = d[:n].reshape(-1, 1000)
fold = D.mean(0)
# second start: after the quietest 100 ms window, the strongest rise
q = np.array([np.roll(fold, -j)[:100].mean() for j in range(1000)])
quiet = int(np.argmin(q)); start = (quiet + 100) % 1000
print(f"carrier {f0:.3f} Hz; quiet window {quiet}-{quiet+100} ms, second starts at {start} ms of the file second")

# per second: burst (0-100 ms), bit window (100-200 ms), quiet reference (-100..0 ms)
secs = []
for s0 in range(start, n - 1000, 1000):
    w = d[s0 - 100 if s0 >= 100 else 0: s0 + 300]
    if len(w) < 400: continue
    e_q, e_b, e_1 = w[:100].mean(), w[100:200].mean(), w[200:300].mean()
    secs.append((T0 + s0 / 1000.0, e_q, e_b, e_1))
secs = np.array(secs)
thr_b = 0.5 * (np.median(secs[:, 1]) + np.median(secs[:, 2]))
has_burst = secs[:, 2] > thr_b
thr_1 = 0.5 * (np.median(secs[has_burst, 1]) + np.median(secs[has_burst, 2]))
bit = (secs[:, 3] > thr_1).astype(int)
mm = np.where(~has_burst)[0]
print(f"{len(secs)} seconds, {len(mm)} without a burst (minute markers?) at", [dt.datetime.fromtimestamp(secs[i, 0], dt.timezone.utc).strftime('%H:%M:%S') for i in mm][:12])

def bcd(b, w):
    return sum(v * wt for v, wt in zip(b, w))

W1, W2 = [1, 2, 4, 8, 10, 20, 40, 80], None
ok = bad = 0
for i0, i1 in zip(mm[:-1], mm[1:]):
    if i1 - i0 != 60: continue
    bits = bit[i0 + 1:i1]                      # seconds 0..58 of the minute that follows the marker
    if len(bits) != 59: continue
    minute = bcd(bits[21:28], W1); hour = bcd(bits[29:35], W1); day = bcd(bits[36:42], W1)
    wd = bcd(bits[42:45], W1); mon = bcd(bits[45:50], W1); yr = bcd(bits[50:58], W1)
    par = [sum(bits[21:29]) % 2 == 0, sum(bits[29:36]) % 2 == 0, sum(bits[36:59]) % 2 == 0]
    tz = "CEST" if bits[17] else "CET" if bits[18] else "?"
    t_start = secs[i0 + 1, 0]                   # UTC of this minute's second 0 by the file clock
    utc = dt.datetime.fromtimestamp(round(t_start / 60) * 60 + 60, dt.timezone.utc)   # the code gives the NEXT minute (as DCF77)
    loc = utc + dt.timedelta(hours=2 if tz == "CEST" else 1)
    good = all(par) and bits[20] == 1 and (hour, minute) == (loc.hour, loc.minute) and day == loc.day and mon == loc.month and yr == loc.year % 100
    ok += good; bad += (all(par) and not good)
    print(f"received {utc - dt.timedelta(minutes=1):%H:%M} UTC: 20{yr:02d}-{mon:02d}-{day:02d} {hour:02d}:{minute:02d} {tz} wd{wd} parity {''.join('ok ' if p else 'BAD ' for p in par)}"
          f"bit20={bits[20]} bits15-19={''.join(map(str, bits[15:20]))} -> {'CORRECT' if good else 'no'}")
print(f"minutes correct {ok}, parity-ok but different {bad}")
