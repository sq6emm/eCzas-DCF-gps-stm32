"""eCzas reference receiver: processes the IC-705 recordings (10-min WAV files
in /w/in, named by UTC start) with the firmware simulator and an independent
slot classifier. Output in /w/out:
  slots.csv   one line per 3-s slot: what was transmitted (time frame / other
              message / idle) and whether the firmware decoder got it
  frames.csv  every frame the firmware decoder found, with its time offset
  hourly.csv  per-hour summary       alerts.log  early frames, problems"""
import os, re, sys, json, time, glob, subprocess, datetime as dt, traceback
from math import gcd
import numpy as np, scipy.io.wavfile as wf, scipy.signal as ss
sys.path.insert(0, "/w/proc")
from eczas_codec import check_frame

W = "/w"; OUT = W + "/out"; ST = OUT + "/state.json"
EPOCH = 946684800                      # 2000-01-01 UTC
PRE = np.array([0, 1] * 8 + [0, 1, 1, 0, 0, 0, 0, 0])
os.makedirs(OUT, exist_ok=True)

def now(): return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def iso(u): return dt.datetime.fromtimestamp(u, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def alert(msg):
    with open(OUT + "/alerts.log", "a") as f: f.write(msg + "\n")

def load_state():
    try: return json.load(open(ST))
    except Exception: return {"done": [], "med": -0.06}
def save_state(s):
    json.dump(s, open(ST + ".tmp", "w")); os.replace(ST + ".tmp", ST)

def name_utc(fn):
    m = re.search(r"(\d{8}_\d{6})\.wav$", fn)
    return dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()

def run_sim(x, fs):
    g = gcd(10000, fs); y = ss.resample_poly(x, 10000 // g, fs // g)
    (y / (np.max(np.abs(y)) + 1e-9) * 20000).astype("<i2").tofile("/tmp/cur.raw")
    out = subprocess.run(["/w/proc/sim", "/tmp/cur.raw"], capture_output=True, text=True, timeout=900).stdout
    dec, fail, conf = [], [], []
    for l in out.splitlines():
        m = re.match(r"\s*([\d.]+) corr=([\d.]+) N=(\d+) .*? rs=(\d+) chase=(\d+) .*?snr=(-?\d+)dB (\w+)", l)
        if m:
            dec.append(dict(t=float(m[1]), corr=float(m[2]), N=int(m[3]), rs=int(m[4]), chase=int(m[5]), snr=int(m[6]), tk=m[7]))
            continue
        m = re.match(r"\s*([\d.]+) corr=([\d.]+) confirmed", l)
        if m: conf.append(float(m[1])); continue
        m = re.match(r"\s*([\d.]+) corr=([\d.]+) decode failed", l)
        if m: fail.append(float(m[1]))
    return dec, fail, conf

def carrier(x, fs):
    t = np.arange(len(x)) / fs
    z = x * np.exp(-2j * np.pi * 1000 * t)
    b, a = ss.butter(4, 60 / (fs / 2)); z = ss.filtfilt(b, a, z)[:: fs // 200]
    N = 1 << int(np.ceil(np.log2(len(z) * 8)))
    Z = np.abs(np.fft.fft(z * np.hanning(len(z)), N)); f = np.fft.fftfreq(N, 1 / 200)
    Z[np.abs(f) > 40] = 0
    return 1000 + f[np.argmax(Z)]

def phase(x, fs, f0):
    t = np.arange(len(x)) / fs
    z = x * np.exp(-2j * np.pi * f0 * t)
    b, a = ss.butter(4, 100 / (fs / 2)); z = ss.filtfilt(b, a, z)[:: fs // 1000]
    return np.unwrap(np.angle(z))                       # 1 ms steps

def classify(ph, s):
    i0 = int(round(s * 1000))
    if i0 < 1000 or i0 + 2950 > len(ph): return None
    pre = np.median(ph[i0 - 900:i0 - 100]); post = np.median(ph[i0 + 2050:i0 + 2900])
    tt = np.arange(-100, 2000)
    ref = pre + (post - pre) * (tt + 500) / 2975.0      # linear between the two idle gaps
    d = np.degrees(ph[i0 - 100:i0 + 2000] - ref)
    act = float(np.std(d[100:2020]))
    if act < 8: return "idle", act, ""
    best = None
    for off in range(60, 141):                          # frame start within +-40 ms
        bits = (d[off + 20 * np.arange(96) + 12] > -18).astype(int)
        sc = int((bits[:24] == PRE).sum())
        if best is None or sc > best[0]: best = (sc, bits)
    bits = best[1]
    if (bits[:16] == PRE[:16]).sum() >= 14 and (bits[16:24] == PRE[16:24]).sum() >= 7:
        return "time", act, "crc_ok" if check_frame([int(b) for b in bits]) else "bit_errors"
    if (bits[:16] == PRE[:16]).sum() >= 14:
        return "other", act, ""                         # another message type
    return "unclear", act, ""                           # modulated, but too noisy to tell

PRE_S = 30          # seconds of the previous file put in front (boundary frame + decoder warm-up)

def prev_tail(fn, fs):
    """the last PRE_S s of the previous 10-min file if it ends exactly where this one starts"""
    p = os.path.join(os.path.dirname(fn), dt.datetime.fromtimestamp(name_utc(fn) - 600, dt.timezone.utc).strftime("%Y%m%d_%H%M%S") + ".wav")
    if not os.path.exists(p): return None
    try:
        fp, y = wf.read(p)
    except Exception:
        return None
    y = y.astype(float); y = y[:, 0] if y.ndim > 1 else y
    if fp != fs or abs(name_utc(p) + len(y) / fs - name_utc(fn)) > 0.05: return None   # gap: no join
    return y[-PRE_S * fs:]

def process(fn, st):
    fs, x = wf.read(fn)
    x = x.astype(float); x = x[:, 0] if x.ndim > 1 else x
    t_own = name_utc(fn)                                # this file's own span starts here
    pre = prev_tail(fn, fs)
    if pre is not None:
        x = np.concatenate([pre, x]); t0 = t_own - len(pre) / fs
    else:
        skip = int(0.1 * fs); x = x[skip:]
        t0 = t_own + skip / fs                          # UTC of x[0] (by the file name)
    dec, fail, conf = run_sim(x, fs)
    offs = [d["t"] - (EPOCH + 3 * d["N"] - t0) for d in dec]
    # the name has whole seconds and the audio clock drifts slowly (~11 ms per
    # 10 min), so follow the previous file's offset; frames 2.4 s early stay out
    good = [o for o in offs if abs(o - st["med"]) < 0.4]
    if len(good) < 2:                                   # lost track: re-centre on the frames
        m0 = float(np.median(offs)) if offs else st["med"]
        good = [o for o in offs if abs(o - m0) < 0.4]
    if len(good) >= 2: st["med"] = float(np.median(good))
    med = st["med"]
    # a slot belongs to the file in which it ends: slots ending before t_own were the previous file's
    mine = lambda u: u + med + 2.95 > t_own
    with open(OUT + "/frames.csv", "a") as f:
        for d, o in zip(dec, offs):
            if not mine(EPOCH + 3 * d["N"] + (o - med)): continue       # where it actually arrived
            dev = o - med
            f.write(f"{iso(EPOCH + 3 * d['N'])},{d['N']},{dev * 1000:+.1f},{d['rs']},{d['chase']},{d['snr']},{d['corr']:.2f},{os.path.basename(fn)}\n")
            if abs(dev) > 10:
                st["miscorr"] = st.get("miscorr", 0) + 1       # wrong time, the timekeeper rejects these
            elif abs(dev) > 0.5:
                alert(f"{now()} frame {iso(EPOCH + 3 * d['N'])} (N={d['N']}) arrived {dev:+.3f} s off its slot "
                      f"(file {os.path.basename(fn)} at {d['t']:.3f} s, snr {d['snr']} dB, rs {d['rs']})")
    f0 = carrier(x, fs); ph = phase(x, fs, f0)
    decN = {EPOCH + 3 * d["N"] for d, o in zip(dec, offs) if abs(o - med) < 0.5}
    dur = len(x) / fs; n = 0
    with open(OUT + "/slots.csv", "a") as f:
        u = 3 * int(np.ceil((t0 - med + 1.0) / 3))
        while not mine(u): u += 3
        while u - t0 + med + 2.95 <= dur:
            s = u - t0 + med
            c = classify(ph, s)
            if c:
                sim = ("decoded" if u in decN else
                       "confirmed" if any(abs(t - s) < 0.3 for t in conf) else
                       "failed" if any(abs(t - s) < 0.3 for t in fail) else "none")
                kind = "time" if sim in ("decoded", "confirmed") else c[0]
                f.write(f"{iso(u)},{kind},{c[2]},{c[1]:.1f},{sim},{f0:.3f}\n"); n += 1
            u += 3
    return len(dec), n

def hourly():
    H = {}
    for l in open(OUT + "/slots.csv"):
        p = l.strip().split(",")
        if len(p) < 5: continue
        h = H.setdefault(p[0][:13], dict(slots=0, time=0, crc_ok=0, other=0, unclear=0, idle=0, dec=0, dec_time=0, conf_time=0))
        h["slots"] += 1; h[p[1]] += 1
        if p[2] == "crc_ok": h["crc_ok"] += 1
        if p[4] == "decoded":
            h["dec"] += 1
            if p[1] == "time": h["dec_time"] += 1
        if p[4] == "confirmed" and p[1] == "time": h["conf_time"] += 1
    with open(OUT + "/hourly.csv.tmp", "w") as f:
        f.write("hour_utc,slots,time_frames_sent,of_which_clean,other_msgs,unclear,idle,firmware_decoded,decoded_of_sent,confirmed_of_sent\n")
        for k in sorted(H):
            h = H[k]
            f.write(f"{k},{h['slots']},{h['time']},{h['crc_ok']},{h['other']},{h['unclear']},{h['idle']},{h['dec']},{h['dec_time']},{h['conf_time']}\n")
    os.replace(OUT + "/hourly.csv.tmp", OUT + "/hourly.csv")

if __name__ == "__main__":
    print(now(), "eczas-ic705 processor started", flush=True)
    while True:
        st = load_state()
        for fn in sorted(glob.glob(W + "/in/*.wav")):
            b = os.path.basename(fn)
            if b in st["done"] or time.time() - os.path.getmtime(fn) < 30: continue
            try:
                nd, ns = process(fn, st)
                print(now(), b, f"{nd} frames decoded, {ns} slots, offset {st['med'] * 1000:+.0f} ms", flush=True)
                if nd == 0: alert(f"{now()} {b}: no frame decoded (signal? IC-705 settings?)")
            except Exception:
                alert(f"{now()} {b}: processing error"); traceback.print_exc()
            st["done"].append(b); save_state(st)
            try: hourly()
            except Exception: traceback.print_exc()
        time.sleep(60)
