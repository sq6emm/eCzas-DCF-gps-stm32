#!/usr/bin/env python3
"""
Permanent KiwiSDR reference for e-CzasPL (225 kHz): a second, independent receiving site.

  kiwi_ref.py BASE [dcf]  (BASE/raw: Kiwi IQ files, BASE/in: 10-min 8 kHz WAVs for proc.py, BASE/log)

  dcf: DCF77 instead (77.5 kHz): the slots become 2 kHz complex files (BASE/c64, the format of
  the NUCLEO's DCF77 dumps) and every hour dcfsim (coh.c + dcf.c, the NUCLEO code) runs over
  the last 6 h with the GPS time base: its last column = DCF77 second start - UTC second [ms],
  i.e. the propagation delay from Mainflingen (~1.3-1.6 ms for these sites) if dcf.c is right.

1. recorder: kiwirecorder (IQ, 225 kHz, +-3 kHz, --kiwi-wav = a GPS timestamp before every
   512-sample block) on the first site that answers; when a session ends (Kiwi time limit,
   busy, network) it reconnects, after repeated failures it moves to the next site.
2. stitcher: every finished 10-min UTC slot is rebuilt from ALL raw blocks by their GPS
   timestamps (gaps from reconnects stay silent, nothing shifts), then turned into the
   8 kHz 'USB audio' format of the IC-705 pipeline: carrier to 0 Hz, complex low-pass
   +-900 Hz, 12 -> 8 kHz, carrier to 1 kHz, real part. proc.py (copy of the IC-705
   reference processing) decodes it: frames.csv / slots.csv / hourly.csv / alerts.log.
"""
import glob, os, re, struct, subprocess, sys, threading, time
import numpy as np, scipy.io.wavfile as wf, scipy.signal as ss

BASE = sys.argv[1]
DCF = len(sys.argv) > 2 and sys.argv[2] == "dcf"
FREQ = "77.5" if DCF else "225"
RAW, IN, LOG, C64, OUT = BASE + "/raw", BASE + "/in", BASE + "/log", BASE + "/c64", BASE + "/out"
DCFSIM = "/r/firmware/host/dcfsim"
KIWI = "/k/kiwiclient/kiwirecorder.py"
# tested 28 Sep 10:20 UTC: clean 225 kHz carrier and full-rate sessions (Plonsk: clean but drops every ~10 s)
SITES = [("centralczechia.proxy.kiwisdr.com", 8073, "czechia"),     # MLA-30+, 453 km from Solec Kujawski
         ("21692.proxy.kiwisdr.com", 8073, "luisenfelde"),          # MegaLoop FX, 309 km
         ("sdrplonsk.duckdns.org", 8078, "plonsk")]                 # 130 km
if DCF:                         # spread the load: DCF77 from another Kiwi than e-CzasPL
    SITES = [SITES[1], SITES[0], SITES[2]]
SLOT = 600
FS = 12000                      # nominal Kiwi IQ rate; blocks are placed by GPS time
GPS0 = 315964800                # 1980-01-06 UTC
LEAP = 18
KEEP_DAYS = 7
for d in (RAW, IN, LOG, C64, OUT): os.makedirs(d, exist_ok=True)


def log(*a):
    with open(LOG + "/kiwi_ref.log", "a") as f:
        print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), *a, file=f, flush=True)


# ---------------- recorder ----------------
def recorder():
    i, fails = 0, 0
    while True:
        host, port, name = SITES[i]
        t0 = time.time()
        log(f"connect {name} {host}:{port}")
        try:
            p = subprocess.run(["python3", KIWI, "-q", "-s", host, "-p", str(port), "-f", FREQ, "-m", "iq",
                                "-L", "-3000", "-H", "3000", "--kiwi-wav", "--station", name, "--user", "eczas-research",
                                "-d", RAW, "--tlimit", "3600", "--connect-retries", "2", "--busy-retries", "2"],
                               capture_output=True, text=True, timeout=3700)
            tail = (p.stdout + p.stderr).strip().splitlines()[-1:] if (p.stdout or p.stderr) else []
        except subprocess.TimeoutExpired:
            tail = ["timeout"]
        dt = time.time() - t0
        log(f"session {name} ended after {dt:.0f} s {tail}")
        if dt < 60:
            fails += 1
            if fails >= 3: i, fails = (i + 1) % len(SITES), 0
            time.sleep(20)
        else:
            fails = 0
            if i != 0 and dt > 1800: i = 0        # back to the preferred site now and then


# ---------------- stitcher ----------------
def read_blocks(fn, now):
    """[(utc of first sample, complex samples)] from a --kiwi-wav file (may still be growing)"""
    b = open(fn, "rb").read(); i = 12; out = []; ts = None; last_t = None; nlast = 0
    wk = int((now + LEAP - GPS0) // 604800)
    while i + 8 <= len(b):
        cid, sz = b[i:i + 4], struct.unpack_from("<I", b, i + 4)[0]
        if i + 8 + sz > len(b): break
        if cid == b"kiwi" and sz >= 10:
            sol, _, gs, gn = struct.unpack_from("<BBII", b, i + 8)
            if gs:
                t = GPS0 + wk * 604800 + gs + gn * 1e-9 - LEAP
                if t > now + 3600: t -= 604800            # week boundary
                elif t < now - 604800 + 3600: t += 604800
                ts = t
            else:
                ts = None
        elif cid == b"data":
            x = np.frombuffer(b[i + 8:i + 8 + sz], "<i2").astype(np.float32).reshape(-1, 2)
            z = x[:, 0] + 1j * x[:, 1]
            if ts is None and last_t is not None: ts = last_t + nlast / FS
            if ts is not None: out.append((ts, z)); last_t, nlast = ts, len(z)
            ts = None
        i += 8 + sz + (sz & 1)
    return out


def build(slot):
    """complex 12 kHz array of the slot from all raw blocks, coverage fraction, sites"""
    z = np.zeros(SLOT * FS, np.complex64); got = np.zeros(SLOT * FS, bool); sites = set()
    for fn in glob.glob(RAW + "/*.wav"):
        if os.path.getmtime(fn) < slot: continue
        m = re.search(r"(\d{8}T\d{6})Z", fn)
        if m and time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S")) - time.timezone > slot + SLOT: continue
        for t, x in read_blocks(fn, slot + SLOT):
            k = int(round((t - slot) * FS))
            if k + len(x) <= 0 or k >= len(z): continue
            a, b = max(k, 0), min(k + len(x), len(z))
            z[a:b] = x[a - k:b - k]; got[a:b] = True
            sites.add(os.path.basename(fn).split("_")[-2])
    return z, got.mean(), sites


def to_usb(z):
    n = len(z)
    seg = z[: FS * 120]
    Z = np.abs(np.fft.fft(seg * np.hanning(len(seg)))); f = np.fft.fftfreq(len(seg), 1 / FS)
    m = np.abs(f) < 20; fc = f[m][np.argmax(Z[m])] if np.any(Z[m]) else 0.0
    y = z * np.exp(-2j * np.pi * fc / FS * np.arange(n))
    y = ss.lfilter(ss.firwin(601, 900, fs=FS), 1, y)
    y = ss.resample_poly(y, 2, 3)
    y = (y * np.exp(2j * np.pi * 1000 / 8000 * np.arange(len(y)))).real
    y *= 12000 / (np.percentile(np.abs(y), 99.9) + 1e-9)
    return np.clip(y, -32767, 32767).astype("<i2"), fc


def to_c64(z):
    """12 kHz complex (DCF77 at 0 Hz, Kiwi GPS-locked) -> 2 kHz complex64"""
    return ss.resample_poly(z, 1, 6).astype(np.complex64)


def dcf_runner():
    """every hour: dcfsim over the last 6 h of 2 kHz slots, GPS time base"""
    last = None
    while True:
        now = time.time()
        end = int(now // SLOT) * SLOT                    # end of the last finished slot
        if now - end > 150 and end % 3600 == 0 and end != last:
            last = end; start = end - 6 * 3600
            # begin at the first recorded slot: a zero-filled lead-in lets the tracker lock on
            # "nothing" and the spur rule then rejects 0 Hz, i.e. DCF77 itself (12:00 run, 28 Sep)
            while start < end and not os.path.exists(C64 + "/" + time.strftime("%Y%m%d_%H%M%S", time.gmtime(start)) + ".c64"):
                start += SLOT
            tmp = "/tmp/dcf6h.c64"; have = 0
            with open(tmp, "wb") as f:
                for t in range(start, end, SLOT):
                    fn = C64 + "/" + time.strftime("%Y%m%d_%H%M%S", time.gmtime(t)) + ".c64"
                    if os.path.exists(fn): f.write(open(fn, "rb").read()); have += 1
                    else: f.write(np.zeros(SLOT * 2000, np.complex64).tobytes())
            if have:
                o = subprocess.run([DCFSIM, tmp, "0", str(start), "1"], capture_output=True, text=True).stdout
                name = time.strftime("%Y%m%d_%H%M", time.gmtime(end))
                open(OUT + f"/dcfsim_{name}.txt", "w").write(o)
                rows = [l for l in o.splitlines() if l and l[0].isdigit()]
                if rows:
                    with open(OUT + "/dcf.csv", "a") as f:
                        f.write(time.strftime("%Y-%m-%d %H:%M", time.gmtime(end)) + f",{have}," + ",".join(rows[-1].replace("|", " ").split()) + "\n")
                log(f"dcfsim {name}: {have}/{(end - start) // SLOT} slots from {time.strftime('%H:%M', time.gmtime(start))}; last: {rows[-1] if rows else '-'}")
        time.sleep(30)


def stitcher():
    done = set(os.path.basename(f)[:-4] + ".wav" for f in glob.glob((C64 + "/*.c64") if DCF else (IN + "/*.wav")))
    while True:
        now = time.time()
        slot = int(now // SLOT) * SLOT - SLOT            # the last finished slot
        if now - slot - SLOT >= 90:                       # blocks of the slot's end are on disk
            name = time.strftime("%Y%m%d_%H%M%S", time.gmtime(slot)) + ".wav"
            if name not in done:
                done.add(name)
                try:
                    z, cov, sites = build(slot)
                    if cov < 0.05:
                        log(f"{name}: no data ({cov:.1%})")
                    elif DCF:
                        fn = C64 + "/" + name[:-4] + ".c64"; to_c64(z).tofile(fn + ".part"); os.replace(fn + ".part", fn)
                        log(f"{name}: coverage {cov:.1%} from {','.join(sorted(sites))} -> c64")
                    else:
                        y, fc = to_usb(z)
                        tmp = IN + "/" + name + ".part"; wf.write(tmp, 8000, y); os.replace(tmp, IN + "/" + name)
                        log(f"{name}: coverage {cov:.1%} from {','.join(sorted(sites))}, carrier {fc:+.3f} Hz")
                except Exception as e:
                    log(f"{name}: ERROR {e!r}")
            # prune raw files
            for fn in glob.glob(RAW + "/*.wav") + glob.glob(C64 + "/*.c64"):
                if now - os.path.getmtime(fn) > KEEP_DAYS * 86400: os.remove(fn)
        time.sleep(30)


threading.Thread(target=recorder, daemon=True).start()
if DCF: threading.Thread(target=dcf_runner, daemon=True).start()
stitcher()
