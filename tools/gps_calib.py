#!/usr/bin/env python3
"""
GPS calibration of the NUCLEO receiver from the 'GPS  PPS' log lines (firmware with PPS capture on PC8).

  gps_calib.py RX.LOG [--from 'YYYY-MM-DDTHH:MM'] [--to ...]

Each PPS line: 'PPS #n | OCXO x ppb (1 s) | e-CzasPL clock y ms | DCF77 second z ms (phase code|second mark)'
  x > 0: the OCXO ran slow over that GPS second (frequency error, ~20 ppb noise per second from the PPS jitter)
  y > 0: the e-CzasPL clock (eCzas core) is ahead of the GPS second by y ms
  z > 0: the DCF77 second (as the NUCLEO sees it) began z ms before the GPS second

Output, per hour and in total (day 06-18 UTC / night separately):
  - OCXO frequency vs GPS (mean, ppb) - checks the DCF77-steered OCXO against GPS
  - e-CzasPL clock offset: mean, sd; a clock behind the GPS second (y < 0) means e-CzasPL's second
    arrives -y ms after UTC; minus the 0.78 ms ground-wave delay (Solec Kujawski - Wroclaw) = how late
    e-CzasPL's second is at the transmitter as recovered by this receiver (incl. the decoder's delay)
  - DCF77 second: mean, sd (phase-code values only); expected -1.93 ms (arrival 1.93 ms after UTC at
    Mainflingen); measured - expected = the receiver's own DCF77 delay (the calibration constant)
GPS time and UTC differ by an integer number of seconds (18 s), which does not affect sub-second values.
"""
import re, sys, argparse, collections, statistics as st

ap = argparse.ArgumentParser()
ap.add_argument("log"); ap.add_argument("--from", dest="t0", default=""); ap.add_argument("--to", dest="t1", default="9999")
a = ap.parse_args()
PAT = re.compile(r"^(\S+)\+00:00 .*\] GPS +PPS #(\d+) \| OCXO ([-+\d.]+|-) ppb \(1 s\) \| e-CzasPL clock ([-+\d.]+|-) ms \| DCF77 second ([-+\d.]+|-) ms \((phase code|second mark)\)")
P_E, P_D = 0.78, 1.93                       # ground-wave delays [ms] from Wroclaw

rows = []
with open(a.log, "rb") as f:
    for raw in f:
        l = re.sub(rb"[^\t\n\r\x20-\x7e]", b"", raw).decode(errors="ignore")
        m = PAT.search(l)
        if not m or not (a.t0 <= m.group(1) < a.t1): continue
        t, n, fo, ez, dc, how = m.groups()
        num = lambda v: None if v == "-" else float(v)
        rows.append((t, num(fo), num(ez), num(dc) if how == "phase code" else None))
if not rows: sys.exit("no GPS PPS lines")

def summary(sel, name):
    fo = [r[1] for r in sel if r[1] is not None and abs(r[1]) < 1000]
    ez = [r[2] for r in sel if r[2] is not None]
    dc = [r[3] for r in sel if r[3] is not None]
    def ms(v): return f"{st.mean(v):+8.3f} ms (sd {st.pstdev(v):.3f}, n {len(v)})" if v else "        -"
    print(f"{name:14s} | OCXO {st.mean(fo):+7.2f} ppb (n {len(fo)}) | e-CzasPL clock {ms(ez)} | DCF77 second {ms(dc)}" if fo else f"{name:14s} | no data")
    return ez, dc

print(f"{len(rows)} PPS lines, {rows[0][0][:16]} .. {rows[-1][0][:16]} UTC\n")
hours = collections.OrderedDict()
for r in rows: hours.setdefault(r[0][:13], []).append(r)
for h, sel in hours.items(): summary(sel, h.replace("T", " ") + " h")
print()
day = [r for r in rows if "06" <= r[0][11:13] < "18"]; night = [r for r in rows if not ("06" <= r[0][11:13] < "18")]
for name, sel in (("day 06-18", day), ("night", night), ("all", rows)):
    if not sel: continue
    ez, dc = summary(sel, name)
    if ez: print(f"{'':14s}   e-CzasPL: its second arrives {-st.mean(ez):+.3f} ms after UTC at the receiver; minus the {P_E} ms path -> "
                 f"{-st.mean(ez) - P_E:+.3f} ms late at the transmitter (incl. the eCzas decoder's own delay)")
    if dc: print(f"{'':14s}   DCF77: expected -{P_D} ms (path), measured {st.mean(dc):+.3f} ms -> receiver's DCF77 delay {-(st.mean(dc) + P_D):+.3f} ms")
