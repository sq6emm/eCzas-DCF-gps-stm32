#!/usr/bin/env python3
"""Same time window, two paths: IC-705 USB AF recording (8 kHz, carrier ~1 kHz) vs the WLAN
IF recording (48 kHz, carrier ~13 kHz) converted to the same format. Both through the eCzas
firmware sim (10 kHz input, as proc.py).
  cmp_usb_lan.py usb.wav LAN_DIR [--carrier 13000]"""
import sys, os, glob, re, subprocess, datetime as dt, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

usb, landir = sys.argv[1], sys.argv[2]
car = float(sys.argv[sys.argv.index("--carrier") + 1]) if "--carrier" in sys.argv else 13000.0
t = lambda fn: dt.datetime.strptime(re.search(r"(\d{8}_\d{6})", fn).group(1), "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
fs_u, xu = wf.read(usb); t0 = t(usb); T = len(xu) / fs_u
# LAN: stitch the files covering [t0, t0+T]
parts = []
for fn in sorted(glob.glob(os.path.join(landir, "*.wav"))):
    fs_l, x = wf.read(fn); a = t(fn)
    if a + len(x) / fs_l < t0 or a > t0 + T: continue
    parts.append((a, x))
start = parts[0][0]; xl = np.concatenate([p[1] for p in parts]).astype(float)
if xl.ndim > 1: xl = xl[:, 0]
xl = xl[int((t0 - start) * fs_l):][: int(T * fs_l)]
print(f"USB {os.path.basename(usb)} {T:.0f} s; LAN {len(xl)/fs_l:.0f} s from {len(parts)} file(s)")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ifconv import if_to_usb
y = if_to_usb(xl, fs_l, car)

def sim(x, fs, tag):
    g = np.gcd(10000, fs); z = ss.resample_poly(x.astype(float), 10000 // g, fs // g)
    z = np.clip(z * 12000 / (np.percentile(np.abs(z), 99.9) + 1e-9), -32767, 32767).astype("<i2")
    z.tofile(f"/tmp/{tag}.raw")
    o = subprocess.run(["/w/proc/sim", f"/tmp/{tag}.raw"], capture_output=True, text=True).stdout
    s = [l for l in o.splitlines() if l.startswith("SUMMARY")]
    dec = len([l for l in o.splitlines() if " N=" in l]); conf = o.count("confirmed")
    print(f"{tag:4s} decoded {dec:4d} confirmed {conf:4d} | {s[0][:160] if s else ''}")

sim(xu, fs_u, "usb")
sim(y, 8000, "lan")
