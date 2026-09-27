#!/usr/bin/env python3
"""Slot-by-slot comparison of three e-CzasPL receivers.
  compare3.py FROM_UTC TO_UTC nucleo_rx.log legnica_pecz.log ic705_slots.csv
FROM/TO like 2026-09-27T15:09:00. Output: summary + per-slot csv (compare3.csv)."""
import csv, datetime as dt, re, sys

def ts(s): return dt.datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
def iso(u): return dt.datetime.fromtimestamp(u, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

t_from, t_to = ts(sys.argv[1]), ts(sys.argv[2])
RX = re.compile(r"^(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?).*?FRAME.*?(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC")

def parse(fn):
    """slot -> (kind, arrival - slot seconds); kind decoded/confirmed; others ignored"""
    out, snr = {}, {}
    for l in open(fn, errors="replace"):
        m = RX.search(l)
        if not m: continue
        host = ts(m[1]) + float("0" + m[1][19:23].replace(",", ".")) if "." in m[1][19:] else ts(m[1])
        slot = ts(m[2])
        kind = "confirmed" if "agrees" in l else "decoded"
        lag = host - slot
        if not (1.0 < lag < 5.0):          # not its own slot (early frame / miscorrection / host lag)
            kind = "odd"
        out.setdefault(slot, (kind, lag))
    return out

nuc = parse(sys.argv[3]); leg = parse(sys.argv[4])
ic = {}
for r in csv.reader(open(sys.argv[5])):
    try: ic[ts(r[0])] = r
    except ValueError: pass

rows = []
tot = dict(slots=0, ic_time=0)
cnt = {}
u = 3 * int(t_from // 3 + 1)
while u < t_to:
    r = ic.get(u)
    icc = r[1] if r else "-"
    icr = r[4] if r else "-"
    n = nuc.get(u, ("-",))[0]; g = leg.get(u, ("-",))[0]
    rows.append((iso(u), icc, icr, n, g))
    tot["slots"] += 1
    if icc == "time": tot["ic_time"] += 1
    key = (icc, "ic705:" + (icr if icr in ("decoded", "confirmed") else "no"),
           "nucleo:" + (n if n != "-" else "no"), "legnica:" + (g if g != "-" else "no"))
    cnt[key] = cnt.get(key, 0) + 1
    u += 3
with open("compare3.csv", "w") as f:
    f.write("slot_utc,ic705_content,ic705_decoder,nucleo,legnica\n")
    for r in rows: f.write(",".join(r) + "\n")

def rate(name, pred):
    k = sum(v for kk, v in cnt.items() if pred(kk))
    return k
T = lambda k: k[0] == "time"
print(f"window {iso(t_from)} .. {iso(t_to)} UTC: {tot['slots']} slots, IC-705 saw a time frame in {tot['ic_time']}")
for name, idx in (("IC-705 ", 1), ("Nucleo ", 2), ("Legnica", 3)):
    d = rate(name, lambda k: T(k) and k[idx].endswith("decoded"))
    c = rate(name, lambda k: T(k) and k[idx].endswith("confirmed"))
    o = rate(name, lambda k: k[idx].endswith("odd"))
    extra = rate(name, lambda k: not T(k) and (k[idx].endswith("decoded") or k[idx].endswith("confirmed")))
    print(f"  {name}: decoded {d:4d}, confirmed {c:4d} -> {100*(d+c)/max(1,tot['ic_time']):5.1f}% of time frames"
          f"   (outside IC-705 time slots: {extra}, off-slot/odd: {o})")
both = rate("", lambda k: T(k) and not k[2].endswith("no") and not k[3].endswith("no"))
only_n = rate("", lambda k: T(k) and not k[2].endswith("no") and k[3].endswith("no"))
only_l = rate("", lambda k: T(k) and k[2].endswith("no") and not k[3].endswith("no"))
print(f"  Nucleo vs Legnica on IC-705 time slots: both {both}, Nucleo only {only_n}, Legnica only {only_l}")
for l in (l for l in open(sys.argv[3], errors="replace") if "REJECTED" in l or "STEPPED" in l):
    t = l[:19]
    if t_from <= ts(t) <= t_to: print("  nucleo clock event:", l.strip()[:160])
