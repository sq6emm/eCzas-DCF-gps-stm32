import sys, numpy as np, scipy.signal as ss, scipy.io.wavfile as wf
for fn in sys.argv[1:]:
    fs, x = wf.read(fn); x = x.astype(float); x = x[:, 0] if x.ndim > 1 else x
    x = x[: fs * 100]
    f, P = ss.welch(x, fs, nperseg=1 << int(np.log2(fs * 8)))       # ~0.12 Hz bins
    m = (f > 950) & (f < 1050); fc = f[m][np.argmax(P[m])]
    df = f[1] - f[0]; pc = P[np.abs(f - fc) < 1].sum() * df
    out = []
    for o in [0.5, 1, 2, 3, 5, 10, 20, 35, 50, 80, 150, 300, 600]:
        k = np.abs(np.abs(f - fc) - o) < max(0.1, o * 0.1)
        out.append(f"{o:g}:{10*np.log10(P[k].mean()/pc):.0f}")
    print(fn.split('/')[-1], f"fc {fc:.2f}", "dBc/Hz at offset Hz ->", " ".join(out))
