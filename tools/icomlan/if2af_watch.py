#!/usr/bin/env python3
"""Feed the eCzas reference pipeline (eczas-ic705-proc, reads 8 kHz WAVs in /data/claude/eczas-ic705/in)
from the WLAN IF recordings: every finished 48 kHz IF file in SRC -> 8 kHz 'USB audio' with the
carrier at 1 kHz (same conversion as if2audio.py), same file name, written as .part then renamed.
  if2af_watch.py SRC DST FIRST_NAME [--carrier 13000]"""
import os, sys, time, glob, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ifconv import if_to_usb

src, dst, first = sys.argv[1], sys.argv[2], sys.argv[3]
car = float(sys.argv[sys.argv.index("--carrier") + 1]) if "--carrier" in sys.argv else 13000.0


def convert(fn, out):
    fs, x = wf.read(fn)
    if x.ndim > 1: x = x[:, 0]
    x = x.astype(np.float64)
    y = if_to_usb(x, fs, car)
    y *= 12000 / (np.percentile(np.abs(y), 99.9) + 1e-9)
    tmp = out + ".part"
    wf.write(tmp, 8000, np.clip(y, -32767, 32767).astype("<i2"))
    os.replace(tmp, out)


while True:
    for fn in sorted(glob.glob(os.path.join(src, "*.wav"))):
        b = os.path.basename(fn)
        out = os.path.join(dst, b)
        if b < first or os.path.exists(out): continue
        try:
            convert(fn, out)
            print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "converted", b, flush=True)
        except Exception as e:
            print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "ERROR", b, e, flush=True)
    time.sleep(20)
