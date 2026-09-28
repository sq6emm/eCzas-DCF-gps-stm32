import sys, numpy as np, scipy.io.wavfile as wf
fs, x = wf.read(sys.argv[1]); x = x.astype(float)
if x.ndim > 1: x = x[:, 0]
x = x[fs:]                                      # skip the switch-over second
print("fs", fs, "len s", len(x)/fs, "rms", np.sqrt(np.mean(x**2)).round(1), "peak", np.abs(x).max())
n = 1 << int(np.log2(len(x))); X = np.abs(np.fft.rfft(x[:n] * np.hanning(n)))**2; f = np.fft.rfftfreq(n, 1/fs)
band = lambda a, b: 10*np.log10(np.median(X[(f > a) & (f < b)]) + 1e-30)
for a in range(0, 24000, 2000): print(f"  {a:5d}-{a+2000:5d} Hz median {band(a, a+2000):6.1f} dB")
m = (f > 200) & (f < 23800); idx = np.argsort(X * m)[::-1]
seen = []
for i in idx:
    if all(abs(f[i]-s) > 30 for s in seen): seen.append(f[i]); print(f"  line {f[i]:9.3f} Hz  {10*np.log10(X[i]):6.1f} dB  ({10*np.log10(X[i])-band(f[i]-300, f[i]+300):5.1f} dB over local)")
    if len(seen) == 10: break
