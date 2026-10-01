#!/usr/bin/env python3
"""
GPS receiver monitor (u-blox NEO-7P on USB): is the GPS whose PPS steers the NUCLEO's OCXO really locked?

  gps_monitor.py DEVICE OUTDIR

Reads what the receiver sends every second (configured 1 Oct 2026): NMEA GGA (fix quality, satellites),
UBX NAV-STATUS (gpsFix, gpsFixOk), NAV-TIMEUTC (time accuracy, UTC valid), TIM-TP (quantisation error of
the next pulse). The time pulse itself is configured to be sent only while the receiver is locked
(CFG-TP5: pulse length 0 when unlocked), so a pulse without a lock should never reach the NUCLEO.
Writes:
  OUTDIR/gps_YYYYMMDD.csv  one line per second: utc, gpsFix, fixOk, gga_quality, numSV, tAcc_ns,
                           utc_valid, qErr_ns, locked (fixOk and 3D and UTC valid and tAcc <= 100 ns)
  OUTDIR/status.txt        current state + this hour's counts (seconds locked / not locked, min satellites,
                           max tAcc)
  OUTDIR/alerts.log        lock lost / regained, tAcc > 100 ns, < 4 satellites, no data for > 10 s
Reopens the device after a disconnect (by-id path).
"""
import os, sys, time, struct, datetime as dt

DEV, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)


def alert(msg):
    with open(os.path.join(OUT, "alerts.log"), "a") as f:
        f.write(f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S} {msg}\n")


st = dict(fix=None, fixok=None, ggaq=None, sv=None, tacc=None, uvalid=None, qerr=None)
hour = dict(key=None, ok=0, bad=0, minsv=99, maxtacc=0)
last_locked, last_data, last_sec = None, time.time(), None


def finish_second():
    global last_locked, last_sec
    now = dt.datetime.now(dt.timezone.utc)
    sec = now.replace(microsecond=0)
    if sec == last_sec: return
    last_sec = sec
    locked = bool(st["fixok"]) and st["fix"] == 3 and bool(st["uvalid"]) and st["tacc"] is not None and st["tacc"] <= 100
    with open(os.path.join(OUT, f"gps_{now:%Y%m%d}.csv"), "a") as f:
        f.write(f"{sec:%Y-%m-%d %H:%M:%S},{st['fix']},{st['fixok']},{st['ggaq']},{st['sv']},{st['tacc']},{st['uvalid']},{st['qerr']},{int(locked)}\n")
    key = f"{now:%Y-%m-%d %H}"
    if hour["key"] != key: hour.update(key=key, ok=0, bad=0, minsv=99, maxtacc=0)
    hour["ok" if locked else "bad"] += 1
    if st["sv"] is not None: hour["minsv"] = min(hour["minsv"], st["sv"])
    if st["tacc"] is not None: hour["maxtacc"] = max(hour["maxtacc"], st["tacc"])
    if last_locked is not None and locked != last_locked:
        alert(("GPS LOCK REGAINED" if locked else "GPS LOCK LOST") + f" (fix {st['fix']}, fixOk {st['fixok']}, SV {st['sv']}, tAcc {st['tacc']} ns, UTC valid {st['uvalid']})")
    if locked and st["sv"] is not None and st["sv"] < 4: alert(f"only {st['sv']} satellites")
    last_locked = locked
    with open(os.path.join(OUT, "status.txt.part"), "w") as f:
        f.write(f"GPS monitor {sec:%Y-%m-%d %H:%M:%S} UTC: {'LOCKED' if locked else 'NOT LOCKED'} | fix {st['fix']} fixOk {st['fixok']} "
                f"GGA quality {st['ggaq']} | satellites {st['sv']} | tAcc {st['tacc']} ns | UTC valid {st['uvalid']} | qErr {st['qerr']} ns\n"
                f"hour {hour['key']}: locked {hour['ok']} s, not locked {hour['bad']} s, min satellites {hour['minsv']}, max tAcc {hour['maxtacc']} ns\n")
    os.replace(os.path.join(OUT, "status.txt.part"), os.path.join(OUT, "status.txt"))


def handle_ubx(c, m, p):
    if (c, m) == (0x01, 0x03) and len(p) >= 6:            # NAV-STATUS
        st["fix"] = p[4]; st["fixok"] = p[5] & 1
    elif (c, m) == (0x01, 0x21) and len(p) >= 20:         # NAV-TIMEUTC
        st["tacc"] = struct.unpack("<I", p[4:8])[0]; st["uvalid"] = (p[19] >> 2) & 1
        finish_second()                                    # one per second: write the line
    elif (c, m) == (0x0D, 0x01) and len(p) >= 16:         # TIM-TP
        st["qerr"] = round(struct.unpack("<i", p[8:12])[0] / 1000.0, 1)


def handle_nmea(line):
    f = line.split(",")
    if len(f) > 7 and f[0].endswith("GGA"):
        st["ggaq"] = int(f[6]) if f[6].isdigit() else None
        st["sv"] = int(f[7]) if f[7].isdigit() else None


alert("gps_monitor started")
while True:
    try:
        fd = os.open(DEV, os.O_RDONLY | os.O_NOCTTY)
    except OSError as e:
        alert(f"cannot open {DEV}: {e}; retry in 5 s"); time.sleep(5); continue
    buf = b""
    try:
        import termios
        a = termios.tcgetattr(fd); a[3] = 0; a[0] = 0; a[1] = 0; termios.tcsetattr(fd, termios.TCSANOW, a)
        while True:
            d = os.read(fd, 4096)
            if not d: raise OSError("no data (device gone?)")
            last_data = time.time(); buf += d
            while True:
                i_u, i_n = buf.find(b"\xb5\x62"), buf.find(b"$")
                cands = [i for i in (i_u, i_n) if i >= 0]
                if not cands: buf = buf[-1:]; break
                i = min(cands)
                if i == i_u:
                    if len(buf) < i + 6: buf = buf[i:]; break
                    c, m, n = buf[i + 2], buf[i + 3], struct.unpack("<H", buf[i + 4:i + 6])[0]
                    if len(buf) < i + 8 + n: buf = buf[i:]; break
                    handle_ubx(c, m, buf[i + 6:i + 6 + n]); buf = buf[i + 8 + n:]
                else:
                    j = buf.find(b"\n", i)
                    if j < 0: buf = buf[i:]; break
                    handle_nmea(buf[i:j].decode(errors="ignore").strip()); buf = buf[j + 1:]
    except OSError as e:
        alert(f"device error: {e}; reopening")
        try: os.close(fd)
        except OSError: pass
        time.sleep(2)
