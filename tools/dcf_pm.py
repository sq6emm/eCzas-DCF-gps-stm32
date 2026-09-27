#!/usr/bin/env python3
"""DCF77 phase-code search on per-second quadrature rows saved by dcf_assist.py (DCF_SAVE=...).

The code is inverted for data bit 1, so D = mean(q | bit 0) - mean(q | bit 1) doubles it,
while anything locked to the second but independent of the bit (mains, AM leakage)
cancels. D is then correlated with every shift of the 511-chip m-sequence (both
polynomial directions) over lags of -60..+60 ms.
  dcf_pm.py dcf_q.npz"""
import sys, numpy as np

FS = 2000.0
d = np.load(sys.argv[1])
q, bit = d["q"].astype(np.float64), d["bit"]
q -= q.mean(axis=1, keepdims=True)
D = q[bit == 0].mean(0) - q[bit == 1].mean(0)
S = q[bit >= 0].mean(0)                                   # bit-independent part, for comparison
print(f"{(bit == 0).sum()} '0' seconds, {(bit == 1).sum()} '1' seconds; rms of D {D[450:1980].std():.4f}, "
      f"of the bit-independent average {S[450:1980].std():.4f}")

def mseq(taps):
    st = [1] * 9; out = []
    for _ in range(511):
        out.append(st[-1]); fb = 0
        for t in taps: fb ^= st[t - 1]
        st = [fb] + st[:-1]
    return np.array(out)

chip = 120 / 77500.0
tt = (np.arange(int(FS)) + 0.5) / FS                      # sample centres (each sample sums 0.5 ms)
k = np.floor((tt - 0.2) / chip).astype(int)
ok = (tt >= 0.2) & (k < 511)
FD = np.fft.rfft(D, 4096)
res = []
for name, taps in (("x9+x5+1", (9, 5)), ("x9+x4+1", (9, 4))):
    m = 1 - 2 * mseq(taps)
    for sh in range(511):
        w = np.zeros(int(FS)); w[ok] = np.roll(m, -sh)[k[ok]]; w -= w.mean()
        cc = np.fft.irfft(FD * np.conj(np.fft.rfft(w, 4096)), 4096)
        cc = np.r_[cc[-120:], cc[:121]] / np.sqrt(np.dot(w, w))
        res.append((name, sh, cc))
allcc = np.array([r[2] for r in res])
sigma = 1.4826 * np.median(np.abs(allcc - np.median(allcc)))
best = sorted(((np.max(np.abs(r[2])) / sigma, r[0], r[1], (np.argmax(np.abs(r[2])) - 120) / FS * 1e3,
                np.sign(r[2][np.argmax(np.abs(r[2]))])) for r in res), reverse=True)
print("top candidates (peak in sigma of all 1022 x 241 correlations):")
for b in best[:6]:
    print(f"  {b[1]} shift {b[2]:3d}: {b[0]:5.1f} sigma at lag {b[3]:+5.1f} ms, sign {b[4]:+.0f}")
print(f"  (for 246k noise-only values the largest is expected near 4.5-5 sigma)")
nm, sh = best[0][1], best[0][2]
cc = [r[2] for r in res if r[0] == nm and r[1] == sh][0]
L = np.argmax(np.abs(cc))
print("  best candidate around its peak, 0.5 ms steps:", " ".join(f"{v/sigma:+.1f}" for v in cc[max(0, L - 6):L + 7]))
