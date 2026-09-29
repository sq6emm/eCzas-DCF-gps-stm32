#!/usr/bin/env python3
"""
e-CzasPL 225 kHz carrier against the DCF77 77.5 kHz carrier, from the NUCLEO's CARRIER lines
(one per minute, both carrier trackers' unwrapped NCO phase against the board's LSE time scale).

    delta = phase_e / 225000 - phase_d / 77500     [s]

The board's clock error is common to both and cancels; delta is the time drift of one transmitter
against the other (a constant slope = relative frequency offset, the scatter = both carriers'
phase noise at the receiver). DCF77's carrier is steered by PTB (< 2e-12 per day), so this
measures the e-CzasPL carrier.

  carrier_cmp.py LOGDIR OUTDIR        (runs forever: every 10 min reads new lines, hourly report)

OUTDIR/cmp.csv: utc, board uptime, phase_e, phase_d, delta_ns, segment
OUTDIR/report.txt: per segment and for the last 24 h: offset (1e-12), residual rms, overlapping
Allan deviation at 60 s .. 1 day, day (06-18 UTC) / night separately.
A segment ends when a tracker is not locked, the board restarts, or delta jumps by > 2 us in a
minute (a cycle slip of the e-CzasPL tracker is 4.4 us, of DCF77 12.9 us).
"""
import glob, os, re, sys, time
import numpy as np

LOG, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
CSV = os.path.join(OUT, "cmp.csv")
PAT = re.compile(r"^(\S+?)\+00:00 \[\s*([\d.]+)\] CARRIER eCzas [-+\d.]+ mHz C/N0 [-\d.]+ dB-Hz noise [\d.]+ deg "
                 r"phase ([-+\d.]+) cyc (\w[\w ]*?) \| DCF77 [-+\d.]+ mHz C/N0 [-\d.]+ dB-Hz phase ([-+\d.]+) cyc ([^|]+?) \|")
# (the phases carry an explicit sign; '+' was missing here until 29 Sep 13:50 - positive phases were skipped)


def printable(b):
    return re.sub(rb"[^\t\n\r\x20-\x7e]", b"", b).decode()


def read_new(state):
    """new CARRIER lines from all rx*.log files since the last byte read"""
    rows = []
    for fn in sorted(glob.glob(os.path.join(LOG, "rx*.log"))):
        pos = state.get(fn, 0)
        size = os.path.getsize(fn)
        if size < pos: pos = 0
        with open(fn, "rb") as f:
            f.seek(pos); data = f.read()
        cut = data.rfind(b"\n") + 1
        state[fn] = pos + cut
        for l in printable(data[:cut]).splitlines():
            i = l.find("CARRIER eCzas")
            if i < 0: continue
            m = PAT.match(l[l.rfind("2026-", 0, i):] if l.rfind("2026-", 0, i) >= 0 else l)
            if not m: continue
            t, up, pe, se, pd, sd = m.groups()
            rows.append((t, float(up), float(pe), se.strip(), float(pd), sd.strip()))
    return rows


def adev(x, tau0, ms):
    """overlapping Allan deviation of phase data x [s] sampled every tau0 [s]"""
    out = []
    for m in ms:
        if len(x) < 2 * m + 1: out.append(np.nan); continue
        d = x[2 * m:] - 2 * x[m:-m] + x[:-2 * m]
        out.append(np.sqrt(0.5 * np.mean(d * d)) / (m * tau0))
    return out


def report():
    if not os.path.exists(CSV): return
    a = np.genfromtxt(CSV, delimiter=",", dtype=None, encoding=None, names=True)
    if a.size < 10: return
    t = np.array([time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone for s in a["utc"]])
    dn = a["delta_ns"].astype(float); seg = a["segment"].astype(int)
    lines = [f"e-CzasPL 225 kHz vs DCF77 77.5 kHz carrier, NUCLEO Wroclaw - {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
             "offset = relative frequency e-CzasPL - DCF77 (1e-12); rms = residual after the linear fit (ns)",
             "ADEV (overlapping, from the minute series): tau 60 s / 600 s / 1 h / 3 h / 12 h", ""]
    taus = [1, 10, 60, 180, 720]
    def block(name, tt, xx):
        if len(tt) < 30: return f"{name}: too short ({len(tt)} min)"
        p = np.polyfit(tt - tt[0], xx * 1e-9, 1)
        res = xx - np.polyval(p, tt - tt[0]) * 1e9
        ad = adev(xx * 1e-9, 60.0, taus)
        return (f"{name}: {len(tt)} min, {(tt[-1]-tt[0])/3600:.1f} h, offset {p[0]*1e12:+.1f}e-12, rms {res.std():.0f} ns, "
                "ADEV " + " / ".join("-" if np.isnan(v) else f"{v:.1e}" for v in ad))
    for s in np.unique(seg):
        k = seg == s
        if k.sum() >= 30: lines.append(block(f"segment {s} from {a['utc'][k][0][:16]}", t[k], dn[k]))
    last = t > t[-1] - 86400
    lines.append("")
    for s in np.unique(seg[last]):
        k = last & (seg == s)
        h = (t[k] % 86400) / 3600
        day, night = k.copy(), k.copy()
        day[k] = (h >= 6) & (h < 18); night[k] = ~((h >= 6) & (h < 18))
        lines.append(block(f"last 24 h, segment {s}, day 06-18 UTC", t[day], dn[day]))
        lines.append(block(f"last 24 h, segment {s}, night", t[night], dn[night]))
    open(os.path.join(OUT, "report.txt"), "w").write("\n".join(lines) + "\n")


state = {}
seg, last = -1, None
if os.path.exists(CSV):                       # continue after a restart: skip what is already there
    for fn in sorted(glob.glob(os.path.join(LOG, "rx*.log"))): state[fn] = os.path.getsize(fn)
    with open(CSV) as f:
        rows = f.read().splitlines()[1:]
    if rows: seg = int(rows[-1].split(",")[-1])
else:
    open(CSV, "w").write("utc,uptime,phase_e,phase_d,delta_ns,segment\n")
    # first run: only from the 14:17:02 firmware (new input and dual ADC) on
    for fn in sorted(glob.glob(os.path.join(LOG, "rx*.log"))):
        state[fn] = 0
next_report = 0
while True:
    rows = read_new(state)
    with open(CSV, "a") as f:
        for t, up, pe, se, pd, sd in rows:
            if t < "2026-09-28T14:17:30": continue
            ok = se == "locked" and sd.startswith("locked")
            if not ok: last = None; continue
            d = (pe / 225000.0 - pd / 77500.0) * 1e9
            if last is None or up < last[0] or up - last[0] > 300 or abs(d - last[1]) > 2000:
                seg += 1                                      # unlock, restart, logger gap or slip
            last = (up, d)
            f.write(f"{t},{up:.1f},{pe:.3f},{pd:.3f},{d:.1f},{seg}\n")
    if time.time() >= next_report:
        try: report()
        except Exception as e: print("report:", e, flush=True)
        next_report = time.time() + 3600
    time.sleep(600)
