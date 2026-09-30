#!/usr/bin/env python3
"""Per-minute inputs of the OCXO loop from a NUCLEO log (OCXO build), for firmware/host/efcreplay.

  efc_replay_extract.py RX.LOG FROM_ISO TO_ISO > minutes.txt

Each line: t vd yd ve ye code cn0  (y as a fraction, y > 0 = the OCXO runs slow; code = logged EFC;
  cn0 = DCF77 C/N0 of the minute in dB-Hz, -99 when not logged)
  ye from the e-CzasPL carrier phase (unwrapped, 0.001 cycle) over the minute,
  yd = ye - (e-CzasPL - DCF77) as logged (0.1 ppb); vd / ve = carrier locked.
The measurements were taken with the OCXO as steered then; efcreplay removes that steering."""
import re, sys
F_E = 225000.0
C = re.compile(r"^(\S+)\+00:00 .*\] CARRIER eCzas ([-+\d.]+) mHz .*?phase ([-+\d.]+) cyc (\w+).*\| DCF77 ([-+\d.]+) mHz C/N0 ([-+\d.]+|-) dB-Hz .*?cyc (\w+).*\| eCzas-DCF77 ([-+\d.]+) ppb")
O = re.compile(r"^(\S+)\+00:00 .*\] OCXO    EFC ([\d.]+) ")
log, t0, t1 = sys.argv[1], sys.argv[2], sys.argv[3]
prev = None; code = None; row = None
for raw in open(log, "rb"):
    l = re.sub(rb"[^\t\x20-\x7e]", b"", raw).decode(errors="ignore")
    if not (t0 <= l[:19] < t1): continue
    m = O.match(l)
    if m and row:
        print(*row[:5], m.group(2), row[5]); row = None; continue
    m = C.match(l)
    if not m: continue
    t, fe, ph, le, fd, cn, ld, diff = m.groups()
    ph = float(ph)
    if prev is not None and le == "locked":
        ye = (ph - prev) / (F_E * 60.0)
        yd = ye - float(diff) * 1e-9
        row = (t[:19], int(ld == "locked"), f"{yd:.4e}", int(le == "locked"), f"{ye:.4e}", cn if cn != "-" else "-99")
    else:
        row = None
    prev = ph if le == "locked" else None
