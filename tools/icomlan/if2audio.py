#!/usr/bin/env python3
"""12 kHz IF recording (48 kHz WAV from icomlan.py) -> 8 kHz 'USB audio' with the wanted carrier
near 1 kHz, the format of the IC-705 USB recordings (eczas-ic705 pipeline, cohsim -8).

  if2audio.py in.wav out.wav [--carrier 13000] [--at 1000] [--ch 0] [--raw]

The IF is real, not inverted (RF f -> 12 kHz + f - dial). Complex mix of `carrier` to `at` Hz,
low-pass (+-3.5 kHz), decimate by 6, keep the real part: identical to USB demodulation with the
carrier at `at` Hz, without the radio's AF chain. --ch picks the channel of a stereo file
(IC-7610: 0 = MAIN, 1 = SUB)."""
import argparse, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

ap = argparse.ArgumentParser()
ap.add_argument("inp"); ap.add_argument("out")
ap.add_argument("--carrier", type=float, default=13000.0)
ap.add_argument("--at", type=float, default=1000.0)
ap.add_argument("--ch", type=int, default=0)
ap.add_argument("--raw", action="store_true", help="write raw int16 (cohsim) instead of WAV")
a = ap.parse_args()
fs, x = wf.read(a.inp)
if x.ndim > 1: x = x[:, a.ch]
x = x.astype(np.float64)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ifconv import if_to_usb
y = if_to_usb(x, fs, a.carrier, a.at)
y *= 12000 / (np.percentile(np.abs(y), 99.9) + 1e-9)
y = np.clip(y, -32767, 32767).astype("<i2")
if a.raw: y.tofile(a.out)
else: wf.write(a.out, 8000, y)
