"""IC-7610 SUB TDF recordings (48 kHz stereo, channel 1, mirrored IF, TDF at ~13000 Hz) -> one 2 kHz complex
float32 file with TDF near 0 Hz, the input format of the NUCLEO's second mixer (tdfsim). Conjugated
(mirrored IF). Also prints the learned shapes (1 ms steps, window -100..+220 ms around the second start)
from tdf_decode3's method as a C table.
  tdf_c64.py OUT.c64 IN1.wav [IN2.wav ...]"""
import sys, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss
out, files = sys.argv[1], sys.argv[2:]
zs = []
for fn in files:
    fs, x = wf.read(fn); y = x[:, 1].astype(float) / 32768; n = np.arange(len(y))
    z = np.conj(y * np.exp(-2j * np.pi * 13000.0 / fs * n))
    zs.append(ss.resample_poly(z, 1, fs // 2000))
z = np.concatenate(zs).astype(np.complex64); z.tofile(out)
print(f"{out}: {len(z)/2000:.0f} s at 2 kHz")
