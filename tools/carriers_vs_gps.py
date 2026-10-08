#!/usr/bin/env python3
"""
What are the DCF77 and e-CzasPL carriers worth? Their frequency against GPS, from the NUCLEO's per-minute
'REFS' lines (firmware with the GPS PPS phase lock, efc_minute3):

  REFS  GPS g ppb, phase p ns (n pulses) | DCF77 d ppb | e-CzasPL e ppb

g, d, e: the OCXO's frequency error against each reference over the minute (> 0: the OCXO runs slow
against it). A station's carrier error against GPS is therefore  (its value) - g  (> 0: the carrier is
above its nominal frequency as seen through GPS time; the OCXO's own residual cancels).

  carriers_vs_gps.py RX.LOG [--from YYYY-MM-DDTHH:MM] [--to ...]

Output per station (and e-CzasPL - DCF77): mean and median offset [ppb], minute scatter, Allan deviation
of the minute series at 1, 10, 30, 60, 180, 360 min (pairs across gaps are skipped), for all minutes and
for day (06-18 UTC) / night separately; plus an hourly table.
"""
import re, sys, argparse, math, statistics as st, collections, datetime as dt

ap = argparse.ArgumentParser(); ap.add_argument("log"); ap.add_argument("--from", dest="t0", default="")
ap.add_argument("--to", dest="t1", default="9999"); a = ap.parse_args()
PAT = re.compile(r"^(\S+)\+00:00 .*\] REFS +GPS ([-+\d.]+) ppb, phase ([-+\d.]+) ns \((\d+) pulses\) \| DCF77 ([-+\d.]+|-) ppb \| e-CzasPL ([-+\d.]+|-) ppb")
rows = []
for raw in open(a.log, "rb"):
    l = re.sub(rb"[^\x20-\x7e]", b"", raw).decode(errors="ignore")
    m = PAT.search(l)
    if not m or not (a.t0 <= m.group(1) < a.t1): continue
    t = dt.datetime.fromisoformat(m.group(1)[:19]).replace(tzinfo=dt.timezone.utc)
    if m.group(2) == "-": continue                 # no GPS value that minute (fewer than 50 pulses)
    g = float(m.group(2)); d = None if m.group(5) == "-" else float(m.group(5)); e = None if m.group(6) == "-" else float(m.group(6))
    rows.append((t, g, d, e))
if not rows: sys.exit("no REFS lines with a GPS value (firmware with the GPS lock?)")


def series(sel, k):
    """minute-indexed dict of the carrier error vs GPS: k = 'd', 'e' or 'e-d'"""
    out = {}
    for t, g, d, e in sel:
        mi = int(t.timestamp() // 60)
        if k == "d" and d is not None: out[mi] = d - g
        elif k == "e" and e is not None: out[mi] = e - g
        elif k == "e-d" and d is not None and e is not None: out[mi] = e - d
    return out


def adev(s, m):
    keys = sorted(s); ks = set(keys); acc, n = 0.0, 0
    for k0 in keys[::m]:
        blk1 = [s.get(k0 + j) for j in range(m)]; blk2 = [s.get(k0 + m + j) for j in range(m)]
        if None in blk1 or None in blk2: continue
        acc += (sum(blk2) / m - sum(blk1) / m) ** 2; n += 1
    return (math.sqrt(0.5 * acc / n), n) if n else (float("nan"), 0)


def report(sel, name):
    print(f"\n== {name}: {len(sel)} minutes")
    for k, lab in (("d", "DCF77 carrier - GPS"), ("e", "e-CzasPL carrier - GPS"), ("e-d", "e-CzasPL - DCF77")):
        s = series(sel, k)
        if len(s) < 3: print(f"  {lab:24s}: too few minutes"); continue
        v = list(s.values())
        ad = " ".join(f"{m}m {adev(s, m)[0]:.2e}({adev(s, m)[1]})" for m in (1, 10, 30, 60, 180, 360))
        print(f"  {lab:24s}: n {len(v):5d}  mean {st.mean(v):+8.3f} ppb  median {st.median(v):+8.3f}  sd(1 min) {st.pstdev(v):7.3f} ppb | ADEV [ppb] {ad}")


print(f"{len(rows)} REFS minutes {rows[0][0]:%Y-%m-%d %H:%M} .. {rows[-1][0]:%Y-%m-%d %H:%M} UTC; GPS (OCXO vs GPS) mean {st.mean(r[1] for r in rows):+.3f} ppb")
report(rows, "all")
report([r for r in rows if 6 <= r[0].hour < 18], "day 06-18 UTC")
report([r for r in rows if not 6 <= r[0].hour < 18], "night 18-06 UTC")
print("\nhourly (median ppb; carrier - GPS): hour  DCF77  e-CzasPL  e-CzasPL-DCF77  (minutes)")
by = collections.defaultdict(list)
for r in rows: by[r[0].strftime("%m-%d %H")].append(r)
for h in sorted(by):
    sel = by[h]; ds = list(series(sel, "d").values()); es = list(series(sel, "e").values()); xs = list(series(sel, "e-d").values())
    f = lambda v: f"{st.median(v):+7.3f}" if v else "      -"
    print(f"  {h}  {f(ds)}  {f(es)}  {f(xs)}  ({len(sel)})")
