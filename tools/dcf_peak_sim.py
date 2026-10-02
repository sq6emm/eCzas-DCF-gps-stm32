#!/usr/bin/env python3
"""DCF77 phase-code sub-sample peak: bias of the old parabolic interpolation vs the triangle-convolved-with-box
estimator now in common/dcf.c pm_eval (review 3, 2 Oct 2026). Simulates 0.5 ms sums of the PTB chip sequence
delayed by sub-sample amounts and correlates with the same template as dcf.c build(). numpy only."""
import numpy as np
SPS = 2000; CH = 120 / 77500.0
prn = [0]; sr = 0; b1 = 1
for k in range(1, 512):
    sr = ((sr << 1) | b1) & 0x1FF; b1 = ((sr >> 4) & 1) ^ ((sr >> 8) & 1); prn.append(b1)
prn = np.array(prn)
def chip(t):                       # +-1 chip value at time t (s) from the second start; code starts at 0.2 s
    s = t - 0.2; c = np.floor(s / CH).astype(int); ok = (s >= 0) & (c < 512)
    return np.where(ok, 1.0 - 2.0 * prn[np.clip(c, 0, 511)], 0.0)
tc = (np.arange(SPS) + 0.5) / SPS
W = chip(tc); W -= W.mean(); W /= np.sqrt((W ** 2).sum())
LAGW = 120
def q_box(tau, sub=64):            # 0.5 ms sums of the chip signal delayed by tau, over WIN samples starting at -LAGW
    n = np.arange(-LAGW, SPS + LAGW)
    t = (n[:, None] + (np.arange(sub)[None, :] + 0.5) / sub) / SPS - tau
    return chip(t).mean(1)
def est(tau):
    q = q_box(tau)
    cc = np.array([np.dot(q[LAGW + L: LAGW + L + SPS], W) for L in range(-LAGW, LAGW + 1)])
    kb = int(np.argmax(np.abs(cc))); y1, y2, y3 = np.abs(cc[kb - 1:kb + 2])
    den = y1 - 2 * y2 + y3; fr_old = 0.5 * (y1 - y3) / den if den else 0.0
    D, M = y3 - y1, y2 - 0.5 * (y1 + y3)
    r = D / M if M else 0.0
    fr_new = 0.0 if abs(r) < 1e-12 else (-2 + np.sqrt(4 + 3 * r * r)) / (2 * r)
    base = kb - LAGW
    return (base + fr_old) / SPS, (base + fr_new) / SPS
eo, en = [], []
for f in np.linspace(0, 1, 21)[:-1]:
    tau = (7 + f) / SPS
    o, n = est(tau); eo.append((o - tau) * 1e6); en.append((n - tau) * 1e6)
print(f"old parabolic: bias {min(eo):+.1f} .. {max(eo):+.1f} us over the sub-sample position")
print(f"new (triangle convolved with the 0.5 ms box): bias {min(en):+.2f} .. {max(en):+.2f} us")
