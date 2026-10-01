#!/usr/bin/env python3
"""
NUCLEO receiver dashboard: carrier frequency stability against GPS and hourly decodes vs expected, from
the NUCLEO's log (rx.log, written by the nucleo-logger container). Serves a web page on PORT (default 8077).

  REFS lines (every minute, firmware with the GPS PPS lock):
    GPS g ppb, phase p ns (n pulses) | DCF77 d ppb | e-CzasPL e ppb [| GPS SUSPENDED (why), k min]
    g, d, e: the OCXO's frequency error against each reference over the minute (> 0: OCXO slow).
    carrier - GPS = d - g, e - g (the OCXO cancels); OCXO vs GPS = g.
  OCXO lines: EFC code and the steering source.
  STATS lines (every hour): e-CzasPL guaranteed :03 time frame expected / heard / correct, all time frames,
    DCF77 minutes (confirmed / by expected frame / unconfirmed / not decodable), C/N0.

The log is read incrementally (only new bytes); the charts are redrawn at most every REDRAW seconds.
Environment: LOG (/log/rx.log), PORT (8077), GPS_FROM (first minute with the GPS lock, 2026-10-01T18:10).
"""
import io, os, re, time, math, threading, datetime as dt, html
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

LOG = os.environ.get("LOG", "/log/rx.log")
PORT = int(os.environ.get("PORT", "8077"))
GPS_FROM = os.environ.get("GPS_FROM", "2026-10-01T18:10")
REDRAW = 120
SLOPE_PPB, CODE_REF = 0.816, 2252.5     # EFC slope [ppb/code] (measured 28 Sep) and the reference code
RANGES = {"6": 6, "24": 24, "72": 72, "all": None}

NUM = r"([-+]?\d+(?:\.\d+)?|-)"
P_REFS = re.compile(r"^(\S+?)\+00:00 .*\] REFS +GPS " + NUM + r" ppb, phase " + NUM + r" ns \((\d+) pulses\) \| DCF77 "
                    + NUM + r" ppb \| e-CzasPL " + NUM + r" ppb(.*)$")
P_OCXO = re.compile(r"^(\S+?)\+00:00 .*\] OCXO +EFC ([\d.]+) .*?source (\S+)")
P_STATS = re.compile(r"^(\S+?)\+00:00 .*\] STATS +(\d+) UTC \| e-CzasPL time frame at :03 \(guaranteed\): expected (\d+), heard (\d+), "
                     r"correct (\d+), confirmed (\d+) \| all time frames: correct (\d+), confirmed (\d+), heard (\d+), early (\d+) \| "
                     r"DCF77 minutes: confirmed (\d+), by expected frame (\d+), unconfirmed (\d+), not decodable (\d+) \| "
                     r"C/N0 e-CzasPL ([\d.]+), DCF77 ([\d.]+)")

lock = threading.Lock()
refs = {}        # minute (int, unix // 60) -> dict(g, ph, n, d, e, sus)
ocxo = {}        # minute -> (efc, source)
stats = {}       # hour start (datetime) -> dict
pos = 0
cache = {}       # range -> (time, {name: png bytes}, summary html)


def ts(s):
    return dt.datetime.fromisoformat(s[:19]).replace(tzinfo=dt.timezone.utc)


def f(x):
    return None if x == "-" else float(x)


def read_log():
    """parse the bytes appended since the last call (restart from 0 if the log was truncated)"""
    global pos
    try:
        size = os.path.getsize(LOG)
    except OSError:
        return
    if size < pos: pos = 0
    with open(LOG, "rb") as fh:
        fh.seek(pos); data = fh.read(size - pos)
    cut = data.rfind(b"\n")
    if cut < 0: return
    pos += cut + 1
    for raw in data[:cut].split(b"\n"):
        l = re.sub(rb"[^\x20-\x7e]", b"", raw).decode(errors="ignore")
        if "] REFS" in l:
            m = P_REFS.match(l)
            if m:
                t = ts(m.group(1)); mi = int(t.timestamp() // 60)
                rest = m.group(7); sus = None
                if "GPS SUSPENDED" in rest:
                    sus = "phase jump" if "phase jump" in rest else "disagreement"
                with lock:
                    refs[mi] = dict(g=f(m.group(2)), ph=f(m.group(3)), n=int(m.group(4)), d=f(m.group(5)), e=f(m.group(6)), sus=sus)
        elif "] OCXO" in l:
            m = P_OCXO.match(l)
            if m:
                t = ts(m.group(1))
                with lock: ocxo[int(t.timestamp() // 60)] = (float(m.group(2)), m.group(3).rstrip(","))
        elif "] STATS" in l:
            m = P_STATS.match(l)
            if m:
                t = ts(m.group(1)) - dt.timedelta(minutes=1)
                h = t.replace(minute=0, second=0, microsecond=0)
                v = [int(x) for x in m.groups()[2:14]]
                with lock:
                    stats[h] = dict(exp=v[0], heard=v[1], correct=v[2], all_correct=v[4], all_heard=v[6], early=v[7],
                                    d_conf=v[8], d_exp=v[9], d_unconf=v[10], d_bad=v[11],
                                    cn_e=float(m.group(15)), cn_d=float(m.group(16)))


def series(r0, r1):
    """minute arrays over [r0, r1): time, OCXO-GPS, DCF77-GPS, e-CzasPL-GPS, phase, pulses, suspended, source"""
    with lock:
        keys = [k for k in sorted(refs) if r0 <= k < r1]
        rows = [refs[k] for k in keys]; src = [ocxo.get(k, (None, None))[1] for k in keys]
        code = np.array([ocxo.get(k, (np.nan, None))[0] for k in keys], float)
    t = np.array([dt.datetime.fromtimestamp(k * 60, dt.timezone.utc) for k in keys])
    nan = float("nan")
    g = np.array([r["g"] if r["g"] is not None and r["n"] >= 50 else nan for r in rows])
    d = np.array([r["d"] - r["g"] if r["d"] is not None and r["g"] is not None and r["n"] >= 50 else nan for r in rows])
    e = np.array([r["e"] - r["g"] if r["e"] is not None and r["g"] is not None and r["n"] >= 50 else nan for r in rows])
    ph = np.array([r["ph"] if r["ph"] is not None and r["n"] >= 50 else nan for r in rows])
    for a in (g, d, e): a[np.abs(a) > 200] = nan            # corrupted log lines
    sus = np.array([r["sus"] is not None for r in rows])
    free = g + SLOPE_PPB * (code - CODE_REF)               # OCXO frequency without the steering
    return np.array(keys), t, g, d, e, ph, sus, src, free


def adev(keys, y, taus):
    """overlapping Allan deviation of a minute-sampled frequency series with gaps (NaN); tau in minutes"""
    if len(keys) < 3: return [], []
    k0 = keys[0]; arr = np.full(keys[-1] - k0 + 1, np.nan); arr[keys - k0] = y
    ok = ~np.isnan(arr); c = np.concatenate([[0], np.cumsum(np.where(ok, arr, 0))]); n = np.concatenate([[0], np.cumsum(ok)])
    out_t, out_a = [], []
    for m in taus:
        if 2 * m >= len(arr): break
        i = np.arange(len(arr) - 2 * m + 1)
        full1 = (n[i + m] - n[i]) == m; full2 = (n[i + 2 * m] - n[i + m]) == m; v = full1 & full2
        if v.sum() < 3: continue
        b1 = (c[i + m] - c[i]) / m; b2 = (c[i + 2 * m] - c[i + m]) / m
        out_t.append(m); out_a.append(math.sqrt(0.5 * np.mean((b2[v] - b1[v]) ** 2)))
    return out_t, out_a


def rolling(y, w=10, need=7):
    ok = ~np.isnan(y); c = np.concatenate([[0], np.cumsum(np.where(ok, y, 0))]); n = np.concatenate([[0], np.cumsum(ok)])
    out = np.full(len(y), np.nan); h = w // 2
    for i in range(len(y)):
        a, b = max(0, i - h), min(len(y), i - h + w)
        if n[b] - n[a] >= need: out[i] = (c[b] - c[a]) / (n[b] - n[a])
    return out


def png(fig):
    b = io.BytesIO(); fig.savefig(b, format="png", dpi=100, bbox_inches="tight"); plt.close(fig); return b.getvalue()


def shade_night(ax, t0, t1):
    d = t0.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)
    while d < t1:
        ax.axvspan(d + dt.timedelta(hours=18), d + dt.timedelta(hours=30), color="0.92", zorder=0, lw=0)
        d += dt.timedelta(days=1)
    ax.set_xlim(t0, t1)


def stat_line(y):
    y = y[~np.isnan(y)]
    if len(y) < 3: return "-"
    return f"mean {y.mean():+.3f} ppb, median {np.median(y):+.3f} ppb, 1-min sd {y.std():.3f} ppb (n {len(y)})"


def render(rng):
    now = dt.datetime.now(dt.timezone.utc)
    gps0 = int(ts(GPS_FROM).timestamp() // 60)
    hours = RANGES[rng]
    r0 = gps0 if hours is None else max(gps0, int(now.timestamp() // 60) - hours * 60)
    keys, t, g, d, e, ph, sus, src, free = series(r0, 1 << 40)
    out = {}
    t0 = ts(GPS_FROM) if hours is None else now - dt.timedelta(hours=hours)
    t0 = max(t0, ts(GPS_FROM)) if hours is None else t0
    xfmt = mdates.DateFormatter("%d %H:%M", tz=dt.timezone.utc)

    # 1) carriers - GPS, minute values + 10-min means
    fig, axs = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True)
    for ax, y, name, col in ((axs[0], d, "DCF77", "tab:blue"), (axs[1], e, "e-CzasPL", "tab:red")):
        shade_night(ax, t0, now)
        if len(t):
            ax.plot(t, y, ".", ms=2.5, color=col, alpha=0.35, label=f"{name} - GPS, 1-min")
            ax.plot(t, rolling(y), "-", lw=1.6, color=col, label="10-min mean")
            v = y[~np.isnan(y)]
            if len(v) > 10:
                lo, hi = np.percentile(v, [1, 99]); pad = 0.3 * (hi - lo) + 0.2; ax.set_ylim(lo - pad, hi + pad)
        ax.axhline(0, color="k", lw=0.8)
        ax.set_ylabel("ppb"); ax.grid(alpha=0.3); ax.legend(loc="upper left", fontsize=8)
        ax.set_title(f"{name} carrier frequency - GPS: {stat_line(y)}", fontsize=10, loc="left")
    axs[1].xaxis.set_major_formatter(xfmt); fig.autofmt_xdate()
    out["carriers"] = png(fig)

    # 2) Allan deviation
    fig, ax = plt.subplots(figsize=(12, 5))
    taus = sorted({int(round(x)) for x in np.logspace(0, 4, 30)})
    for y, name, col in ((d, "DCF77 carrier vs GPS", "tab:blue"), (e, "e-CzasPL carrier vs GPS", "tab:red"),
                         (g, "OCXO (GPS-locked) vs GPS", "tab:green")):
        tt, aa = adev(keys, y, taus)
        if tt: ax.loglog(np.array(tt) * 60, np.array(aa) * 1e-9, "o-", ms=4, color=col, label=name)
    ax.set_xlabel("averaging time tau [s]"); ax.set_ylabel("Allan deviation (fractional)")
    ax.grid(True, which="both", alpha=0.3); ax.legend(fontsize=9)
    sec = ax.secondary_yaxis("right", functions=(lambda x: x * 1e9, lambda x: x * 1e-9)); sec.set_ylabel("ppb")
    ax.set_title("Frequency stability against the GPS PPS (overlapping Allan deviation of the minute frequencies)", fontsize=10, loc="left")
    out["adev"] = png(fig)

    # 3) OCXO phase vs GPS + steering source
    fig, ax = plt.subplots(figsize=(12, 3.6))
    shade_night(ax, t0, now)
    if len(t):
        ax.plot(t, ph, "-", lw=0.9, color="tab:green", label="OCXO second - GPS second (loop phase) [ns]")
        bad = np.array([s != "GPS" for s in src]) | sus
        if bad.any():
            ax.plot(t[bad], np.zeros(bad.sum()), "|", color="red", ms=14, label="minutes NOT steered by GPS / GPS suspended")
        v = ph[~np.isnan(ph)]
        if len(v) > 10:
            lo, hi = np.percentile(v, [0.5, 99.5]); pad = 0.2 * (hi - lo) + 10; ax.set_ylim(lo - pad, hi + pad)
    ax.set_ylabel("ns"); ax.grid(alpha=0.3); ax.legend(loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(xfmt); fig.autofmt_xdate()
    ax.set_title("OCXO time error against GPS", fontsize=10, loc="left")
    out["phase"] = png(fig)

    # 3b) the OCXO's own frequency (steering removed): what the loop has to correct
    fig, ax = plt.subplots(figsize=(12, 3.6))
    shade_night(ax, t0, now)
    if len(t):
        ax.plot(t, free, ".", ms=2.5, color="tab:purple", alpha=0.35, label=f"OCXO vs GPS at EFC code {CODE_REF} (1-min)")
        ax.plot(t, rolling(free), "-", lw=1.6, color="tab:purple", label="10-min mean")
    ax.set_ylabel("ppb"); ax.grid(alpha=0.3); ax.legend(loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(xfmt); fig.autofmt_xdate()
    ax.set_title("OCXO free-running frequency (GPS-measured frequency + EFC slope x code offset; > 0: slow)", fontsize=10, loc="left")
    out["free"] = png(fig)

    # 4) hourly decodes vs expected
    with lock:
        hs = sorted(h for h in stats if (hours is None or h >= now - dt.timedelta(hours=hours + 1)))
        S = [stats[h] for h in hs]
    fig, axs = plt.subplots(3, 1, figsize=(12, 8.5), sharex=True)
    if hs:
        x = np.array(hs) + dt.timedelta(minutes=30); w = 0.8 / 24          # bar width in days (date axis)
        ex = np.array([s["exp"] for s in S])
        a = axs[0]
        a.bar(x, ex, width=w, color="none", edgecolor="k", label="expected (one per minute)")
        a.bar(x, [s["heard"] for s in S], width=w * 0.7, color="tab:orange", alpha=0.6, label="heard")
        a.bar(x, [s["correct"] for s in S], width=w * 0.4, color="tab:red", label="correct")
        a.set_title("e-CzasPL guaranteed time frame at :03 of every minute", fontsize=10, loc="left")
        a = axs[1]
        b1 = np.array([s["d_conf"] for s in S]); b2 = np.array([s["d_exp"] for s in S]); b3 = np.array([s["d_unconf"] for s in S])
        a.bar(x, ex, width=w, color="none", edgecolor="k", label="expected (minutes)")
        a.bar(x, b1, width=w * 0.6, color="tab:blue", label="confirmed")
        a.bar(x, b2, width=w * 0.6, bottom=b1, color="tab:cyan", label="by expected frame")
        a.bar(x, b3, width=w * 0.6, bottom=b1 + b2, color="tab:gray", label="unconfirmed")
        a.set_title("DCF77 minutes decoded", fontsize=10, loc="left")
        a = axs[2]
        a.bar(x, [s["all_heard"] for s in S], width=w * 0.7, color="tab:orange", alpha=0.6, label="heard")
        a.bar(x, [s["all_correct"] for s in S], width=w * 0.4, color="tab:red", label="correct")
        er = [(xi, s["early"]) for xi, s in zip(x, S) if s["early"]]
        if er: a.plot([p[0] for p in er], [0] * len(er), "v", color="k", ms=8, label="hour with an early frame")
        a.set_title("e-CzasPL all time frames (the station sends a varying number per hour)", fontsize=10, loc="left")
        for a in axs: a.grid(alpha=0.3, axis="y"); a.legend(loc="lower left", fontsize=8, ncol=4)
        axs[2].xaxis.set_major_formatter(xfmt); fig.autofmt_xdate()
    out["decodes"] = png(fig)

    # summary + hourly table
    rows = []
    for h, s in reversed(list(zip(hs, S))[-48:]):
        dsum = s["d_conf"] + s["d_exp"] + s["d_unconf"]
        rows.append(f"<tr><td>{h:%m-%d %H} UTC</td><td>{s['exp']}</td><td>{s['correct']}</td><td>{100*s['correct']/max(1,s['exp']):.0f}%</td>"
                    f"<td>{dsum}</td><td>{100*dsum/max(1,s['exp']):.0f}%</td><td>{s['d_conf']}/{s['d_exp']}/{s['d_unconf']}/{s['d_bad']}</td>"
                    f"<td>{s['all_correct']}/{s['all_heard']}</td><td>{s['early']}</td><td>{s['cn_e']:.1f}</td><td>{s['cn_d']:.1f}</td></tr>")
    cur = ""
    if len(keys):
        k = keys[-1]; r = refs[k]; o = ocxo.get(k, (None, "?"))
        age = int(now.timestamp() // 60) - k
        cur = (f"last minute {dt.datetime.fromtimestamp(k*60, dt.timezone.utc):%Y-%m-%d %H:%M} UTC ({age} min ago): "
               f"steering source <b>{html.escape(str(o[1]))}</b>, EFC {o[0]}, GPS pulses {r['n']}/60, time error {r['ph']} ns"
               + (f", <b style='color:#c00'>GPS SUSPENDED ({r['sus']})</b>" if r["sus"] else ""))
        if age > 5: cur += " <b style='color:#c00'>- NO NEW DATA</b>"
    nsteer = sum(1 for s_ in src if s_ == "GPS"); nsus = int(sus.sum())
    summ = (f"<p>{cur}</p><p>range: {len(keys)} minutes; GPS steering {nsteer}, suspended {nsus}</p>"
            "<table><tr><th>hour</th><th>expected</th><th>e-CzasPL :03 correct</th><th>%</th><th>DCF77 decoded</th><th>%</th>"
            "<th>DCF77 conf / by frame / unconf / not dec.</th><th>all frames correct/heard</th><th>early</th><th>C/N0 e-CzasPL</th><th>C/N0 DCF77</th></tr>"
            + "".join(rows) + "</table>")
    return out, summ


render_lock = threading.Lock()


def get(rng):
    with render_lock:                                    # one reader of the log / one matplotlib user at a time
        c = cache.get(rng)
        if c and time.time() - c[0] < REDRAW: return c
        read_log()
        out, summ = render(rng)
        c = (time.time(), out, summ); cache[rng] = c
        return c


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><title>NUCLEO vs GPS</title>
<style>body{{font-family:sans-serif;margin:16px;max-width:1250px;background:#fff;color:#111}} img{{max-width:100%;height:auto}}
table{{border-collapse:collapse;font-size:13px}} td,th{{border:1px solid #ccc;padding:2px 6px;text-align:right}} th{{background:#eee}}
a.on{{font-weight:bold}} h2{{margin-top:28px}}</style></head><body>
<h1>NUCLEO receiver: carriers against GPS, decodes per hour</h1>
<p>range: {links} &middot; updated {upd} UTC (charts redrawn at most every {redraw} s, page reloads every 5 min) &middot; source: rx.log, GPS lock since {gps_from} UTC; grey = night 18-06 UTC</p>
{summary_cur}
<h2>Carrier frequency against GPS</h2><img src="/carriers.png?r={r}&v={v}">
<h2>Stability (Allan deviation)</h2><img src="/adev.png?r={r}&v={v}">
<h2>OCXO time error against GPS</h2><img src="/phase.png?r={r}&v={v}">
<h2>OCXO free-running frequency</h2><img src="/free.png?r={r}&v={v}">
<h2>Decodes vs expected, per hour</h2><img src="/decodes.png?r={r}&v={v}">
<h2>Hourly table (latest first)</h2>{table}
</body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); rng = q.get("r", ["24"])[0]
        if rng not in RANGES: rng = "24"
        try:
            c = get(rng)
        except Exception as ex:
            self.send_response(500); self.end_headers(); self.wfile.write(f"error: {ex}".encode()); return
        name = u.path.strip("/").removesuffix(".png")
        if u.path.endswith(".png") and name in c[1]:
            body, ctype = c[1][name], "image/png"
        elif u.path in ("/", "/index.html"):
            links = " ".join(f'<a class="{"on" if k == rng else ""}" href="/?r={k}">{"all" if k == "all" else k + " h"}</a>' for k in RANGES)
            cur, table = c[2].split("<table>", 1) if "<table>" in c[2] else (c[2], "")
            body = PAGE.format(links=links, upd=dt.datetime.fromtimestamp(c[0], dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                               redraw=REDRAW, gps_from=GPS_FROM, summary_cur=cur, r=rng, v=int(c[0]),
                               table="<table>" + table).encode()
            ctype = "text/html; charset=utf-8"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache"); self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    read_log()
    print(f"parsed {len(refs)} REFS minutes, {len(stats)} STATS hours; serving on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
