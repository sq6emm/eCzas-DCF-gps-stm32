"""K9AY scan analysis: per switch segment (skip 4 s, 16 s), per channel (0 MAIN e-CzasPL,
1 SUB DCF77; both carriers at ~13000 Hz): carrier power (+-0.25 Hz of the peak), noise density
(10-80 Hz from the carrier, median), C/N0 dB-Hz, total level. Mean over the rounds per setting."""
import glob, re, datetime as dt, numpy as np, scipy.io.wavfile as wf, collections
fn = sorted(glob.glob("/k/rec/*.wav"))[0]
t0 = dt.datetime.strptime(re.search(r"(\d{8}_\d{6})", fn).group(1), "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
fs, x = wf.read(fn); x = x.astype(float) / 32768
sw = [l.split() for l in open("/k/switch.log") if l[0].isdigit() and len(l.split()) == 4]
res = collections.defaultdict(list)
for t, code, name, r in sw:
    a = int((float(t) - t0 + 4) * fs); b = a + 16 * fs
    if b > len(x): continue
    row = []
    for c in range(2):
        y = x[a:b, c]; N = len(y)
        Y = np.abs(np.fft.rfft(y * np.hanning(N))) ** 2 / (fs * (np.hanning(N) ** 2).sum()); f = np.fft.rfftfreq(N, 1 / fs)
        k = (f > 12995) & (f < 13005); i = np.where(k)[0][np.argmax(Y[k])]
        pc = Y[np.abs(f - f[i]) <= 0.25].sum() * (f[1] - f[0])
        n0 = np.median(Y[(np.abs(f - f[i]) > 10) & (np.abs(f - f[i]) < 80)])
        row.append((10 * np.log10(pc / n0), 10 * np.log10(pc), 10 * np.log10(n0)))
    res[(code, name)].append(row)
    print(f"round {r} {name:7s} eCzas C/N0 {row[0][0]:5.1f} (C {row[0][1]:6.1f} N0 {row[0][2]:6.1f}) | DCF77 C/N0 {row[1][0]:5.1f} (C {row[1][1]:6.1f} N0 {row[1][2]:6.1f})")
print("\nmean over rounds (dB-Hz; C and N0 in dBFS, dBFS/Hz):")
for (code, name), rows in sorted(res.items(), key=lambda kv: -np.mean([r[0][0] for r in kv[1]])):
    m = np.mean(np.array(rows), axis=0); s = np.std(np.array(rows)[:, :, 0], axis=0)
    print(f"{name:7s} ({code}) eCzas {m[0][0]:5.1f} +-{s[0]:3.1f}  C {m[0][1]:6.1f} N0 {m[0][2]:6.1f} | DCF77 {m[1][0]:5.1f} +-{s[1]:3.1f}  C {m[1][1]:6.1f} N0 {m[1][2]:6.1f}")
