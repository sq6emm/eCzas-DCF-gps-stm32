"""
Bias-free timing models for the fit tools (tdf_vs_eczas_timing.py, eczas_transition_shape.py,
nucleo_timing_check.py). Written 1 Oct 2026 after an independent review found the old fits biased by
-0.2 ... -0.45 ms: they sampled step models at the sample instants (the score is then piecewise constant
in the time offset and the argmax lands on a plateau edge) and took the argmax of a grid.

Here every model sample is the AVERAGE of the continuous signal over the sample's own interval, so the
score is continuous in the offset, and the best offset is refined by a parabola through the grid
neighbours.
  sample intervals: box=True  -> [n, n+1) / fs   (the NUCLEO's 0.5 ms sums, sample n starts at n/fs)
                    box=False -> [n - 0.5, n + 0.5) / fs   (point samples after a zero-phase filter, IC-7610)
"""
import numpy as np

E_RAMP = 0.0166          # e-CzasPL phase ramp per bit change [s] (NUCLEO dumps 1 Oct: linear, 16.6 ms)
E_BIT = 0.020            # e-CzasPL bit [s]
D_CHIP = 120.0 / 77500.0 # DCF77 phase-code chip [s]


def intervals(n, fs, box):
    n = np.asarray(n, float)
    t0 = n / fs if box else (n - 0.5) / fs
    return t0, t0 + 1.0 / fs


def piecewise_const_avg(t0, t1, edges, levels):
    """mean over [t0, t1) of a function that is levels[i] on [edges[i], edges[i+1]) and 0 outside"""
    edges = np.asarray(edges, float); levels = np.asarray(levels, float)
    cum = np.concatenate([[0.0], np.cumsum(levels * np.diff(edges))])
    F = lambda x: np.interp(x, edges, cum, left=0.0, right=cum[-1])
    return (F(t1) - F(t0)) / (t1 - t0)


def dcf_code(t0, t1, start, prn):
    """DCF77 phase code (+1 for chip 0, -1 for chip 1; 512 chips from `start`), interval averages"""
    edges = start + np.arange(len(prn) + 1) * D_CHIP
    return piecewise_const_avg(t0, t1, edges, 1.0 - 2.0 * np.asarray(prn, float))


def eczas_phase(tc, start, bits, pre=0.040):
    """e-CzasPL phase levels (+-1) of a frame whose first bit change (out of the idle phase, which sits at
    the opposite level of bit 0) STARTS at `start`; each change is a linear E_RAMP ramp starting at the bit
    edge. Evaluated at the interval centres tc (exact for the linear parts; the ramps are 33 samples long).
    Returns (model, mask) - mask marks the samples inside [start - pre, end of the frame)."""
    bits = np.asarray(bits, float)
    lev = np.concatenate([[-bits[0]], bits])
    kx, ky = [start - pre], [lev[0]]
    for k in range(len(bits)):
        kx += [start + k * E_BIT, start + k * E_BIT + E_RAMP]; ky += [lev[k], lev[k + 1]]
    end = start + len(bits) * E_BIT
    m = np.interp(tc, kx, ky)
    mask = (tc >= start - pre) & (tc < end)
    return m, mask


def refine(score, grid):
    """best grid point of |score| refined by a parabola through its neighbours; None at the grid edge"""
    s = np.abs(np.asarray(score, float)); j = int(np.argmax(s))
    if j == 0 or j == len(s) - 1: return None
    den = s[j - 1] - 2 * s[j] + s[j + 1]
    f = 0.5 * (s[j - 1] - s[j + 1]) / den if den < 0 else 0.0
    return grid[j] + f * (grid[1] - grid[0])
