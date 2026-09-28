"""phase spread / amplitude fluctuation of the 225 kHz carrier: Kiwi IQ file vs our IF recording, same UTC window"""
import sys, glob, os, re, datetime as dt, numpy as np, scipy.io.wavfile as wf, scipy.signal as ss
def metrics(z, fs):
    z = ss.lfilter(ss.firwin(801, 150, fs=fs), 1, z)[:: max(1, int(fs // 2000))]
    ph = np.unwrap(np.angle(z)); t = np.arange(len(ph)); ph -= np.polyval(np.polyfit(t, ph, 2), t)
    ph -= ss.medfilt(ph, 2001); d = np.degrees(ph[2000:-2000]); a = np.abs(z[2000:-2000])
    return np.percentile(d, 5), np.percentile(d, 95), np.std(a) / np.mean(a)
kiwi = sys.argv[1]; ifdir = sys.argv[2]
def read_kiwi(fn):
    """kiwirecorder --kiwi-wav: RIFF with many 'kiwi' (GPS time) + 'data' chunks; returns fs, complex samples"""
    import struct
    b = open(fn, "rb").read(); i = 12; fs = None; parts = []
    while i + 8 <= len(b):
        cid, sz = b[i:i+4], struct.unpack_from("<I", b, i + 4)[0]
        if cid == b"fmt ": fs = struct.unpack_from("<I", b, i + 12)[0]
        elif cid == b"data": parts.append(np.frombuffer(b[i+8:i+8+sz], "<i2"))
        i += 8 + sz + (sz & 1)
    x = np.concatenate(parts).reshape(-1, 2).astype(float)
    return fs, x[:, 0] + 1j * x[:, 1]
fs, z = read_kiwi(kiwi)
t0 = dt.datetime.strptime(re.search(r"(\d{8}T\d{6})Z", kiwi).group(1), "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
# carrier: strongest line within +-50 Hz
n = len(z); Z = np.abs(np.fft.fft(z * np.hanning(n))); f = np.fft.fftfreq(n, 1 / fs)
m = np.abs(f) < 50; fc = f[m][np.argmax(Z[m])]; z = z * np.exp(-2j * np.pi * fc / fs * np.arange(n))
p5, p95, cv = metrics(z, fs)
print(f"KIWI {os.path.basename(kiwi)} fs {fs} dur {n/fs:.0f}s carrier {fc:+.2f} Hz: phase {p5:.1f}..{p95:.1f} deg, amp cv {cv:.3f}")
T = n / fs
for fn in sorted(glob.glob(os.path.join(ifdir, "*.wav"))):
    a = dt.datetime.strptime(re.search(r"(\d{8}_\d{6})", fn).group(1), "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
    fl, y = wf.read(fn)
    if a > t0 or a + len(y) / fl < t0 + T: continue
    y = y[int((t0 - a) * fl):int((t0 - a + T) * fl)].astype(float)
    zz = y * np.exp(-2j * np.pi * 13000.054 / fl * np.arange(len(y)))
    p5, p95, cv = metrics(zz, fl)
    print(f"OURS {os.path.basename(fn)} same window: phase {p5:.1f}..{p95:.1f} deg, amp cv {cv:.3f}")
