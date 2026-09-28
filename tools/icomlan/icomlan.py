#!/usr/bin/env python3
"""
Icom LAN / WLAN remote client (IC-705, IC-7610, IC-9700 ...): receive audio (or the 12 kHz IF
output), send / read CI-V. Protocol after kappanhang (github.com/nonoo/kappanhang) and wfview
(gitlab.com/eliggett/wfview, include/packettypes.h). Receive only: we never send TX audio or PTT.

  icomlan.py --host 192.168.12.163 --user U --password P [--codec 0x04] [--rate 48000]
             [--out DIR] [--file-time 600] [--civ 'FE FE A4 E0 03 FD' ...] [--civ-every 60 CMD]
             [--seconds N]

Streams: control 50001, CI-V 50002, audio 50003 (UDP). Every stream: "are you there" (type 3)
-> "I am here" (4, gives the radio's id) -> "are you ready" (6) -> 6. Pings (type 7) both ways,
tracked packets (login, token, conninfo, CI-V) keep a send sequence and can be re-requested by
the radio (type 1). Audio packets: header 0x18 bytes, then PCM; sequence at 0x06.

Codecs (rxcodec): 0x01 uLaw 1ch, 0x02 PCM8 1ch, 0x04 PCM16 1ch, 0x08 PCM8 2ch, 0x10 PCM16 2ch,
0x20 uLaw 2ch. IC-7610 with a 2-channel codec: MAIN left, SUB right.
"""
import argparse, os, random, select, socket, struct, sys, time, wave

PASSCODE = {32: 0x47, 33: 0x5d, 34: 0x4c, 35: 0x42, 36: 0x66, 37: 0x20, 38: 0x23, 39: 0x46, 40: 0x4e, 41: 0x57,
            42: 0x45, 43: 0x3d, 44: 0x67, 45: 0x76, 46: 0x60, 47: 0x41, 48: 0x62, 49: 0x39, 50: 0x59, 51: 0x2d,
            52: 0x68, 53: 0x7e, 54: 0x7c, 55: 0x65, 56: 0x7d, 57: 0x49, 58: 0x29, 59: 0x72, 60: 0x73, 61: 0x78,
            62: 0x21, 63: 0x6e, 64: 0x5a, 65: 0x5e, 66: 0x4a, 67: 0x3e, 68: 0x71, 69: 0x2c, 70: 0x2a, 71: 0x54,
            72: 0x3c, 73: 0x3a, 74: 0x63, 75: 0x4f, 76: 0x43, 77: 0x75, 78: 0x27, 79: 0x79, 80: 0x5b, 81: 0x35,
            82: 0x70, 83: 0x48, 84: 0x6b, 85: 0x56, 86: 0x6f, 87: 0x34, 88: 0x32, 89: 0x6c, 90: 0x30, 91: 0x61,
            92: 0x6d, 93: 0x7b, 94: 0x2f, 95: 0x4b, 96: 0x64, 97: 0x38, 98: 0x2b, 99: 0x2e, 100: 0x50, 101: 0x40,
            102: 0x3f, 103: 0x55, 104: 0x33, 105: 0x37, 106: 0x25, 107: 0x77, 108: 0x24, 109: 0x26, 110: 0x74,
            111: 0x6a, 112: 0x28, 113: 0x53, 114: 0x4d, 115: 0x69, 116: 0x22, 117: 0x5c, 118: 0x44, 119: 0x31,
            120: 0x36, 121: 0x58, 122: 0x3b, 123: 0x7a, 124: 0x51, 125: 0x5f, 126: 0x52}


def passcode(s):
    r = bytearray(16)
    for i, ch in enumerate(s.encode()[:16]):
        p = ch + i
        if p > 126: p = 32 + p % 127
        r[i] = PASSCODE[p]
    return bytes(r)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), *a, flush=True)


class Stream:
    """one UDP stream: handshake, pings, tracked sends, retransmits"""

    def __init__(self, name, host, rport, lport):
        self.name, self.addr = name, (host, rport)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self.sock.bind(("", lport))
        self.sock.connect(self.addr)
        ip = socket.inet_aton(self.sock.getsockname()[0])
        self.my = ip[2:4] + struct.pack(">H", self.sock.getsockname()[1])   # as kappanhang: ip.lo16 << 16 | port
        self.rid = b"\0\0\0\0"
        self.seq = 1                      # tracked send sequence
        self.ping_seq = 1
        self.sent = {}                    # seq -> packet, for the radio's retransmit requests
        self.ready = False
        self.last_rx = time.time()
        self.last_tracked = 0.0
        self.next_idle = 0.0
        self.next_ping = 0.0
        self.idle_on = False

    def hdr(self, length, typ, seq):
        return struct.pack("<IHH", length, typ, seq) + self.my + self.rid

    def ctl(self, typ, seq=0):
        p = self.hdr(0x10, typ, seq)
        self.sock.send(p); self.sock.send(p)

    def tracked(self, p):
        p = bytearray(p)
        p[6:8] = struct.pack("<H", self.seq)
        self.sent[self.seq] = bytes(p)
        self.sent.pop((self.seq - 300) & 0xffff, None)
        self.seq = (self.seq + 1) & 0xffff
        self.sock.send(bytes(p))
        if len(p) != 0x10: self.last_tracked = time.time()

    def ping(self):
        t = struct.pack("<I", int(time.monotonic() * 1000) & 0xffffffff)
        self.sock.send(self.hdr(0x15, 7, self.ping_seq) + b"\0" + t)
        self.ping_seq = (self.ping_seq + 1) & 0xffff

    def handshake(self, timeout=5.0):
        """are you there -> I am here -> are you ready -> ready"""
        t0 = time.time(); step = 3; last = 0
        while time.time() - t0 < timeout:
            if time.time() - last > 0.5:
                self.ctl(step, 1 if step == 6 else 0); last = time.time()
            r, _, _ = select.select([self.sock], [], [], 0.1)
            if not r: continue
            d = self.sock.recv(65536)
            if len(d) == 0x10:
                typ = struct.unpack_from("<H", d, 4)[0]
                if typ == 4 and step == 3:
                    self.rid = d[8:12]; step = 6; last = 0
                elif typ == 6 and step == 6:
                    self.ready = True
                    log(f"{self.name}: connected, radio id {self.rid.hex()}")
                    return True
        raise RuntimeError(f"{self.name}: no answer from {self.addr} (WLAN / network control on?)")

    def common(self, d):
        """handle pings / retransmit requests; True if consumed"""
        self.last_rx = time.time()
        n = len(d)
        if n == 21 and d[4] == 7 and d[5] == 0:
            if d[16] == 0:                                   # the radio pings us: answer
                self.sock.send(struct.pack("<IHH", 0x15, 7, struct.unpack_from("<H", d, 6)[0]) + self.my + self.rid + b"\x01" + d[17:21])
            return True
        if n == 0x10 and d[4] == 1:                          # retransmit one
            self.resend(struct.unpack_from("<H", d, 6)[0]); return True
        if n >= 0x18 and d[4] == 1 and d[0] == 0x18:         # retransmit ranges
            for k in range(0x10, n - 3, 4):
                a, b = struct.unpack_from("<HH", d, k)
                while True:
                    self.resend(a)
                    if a == b: break
                    a = (a + 1) & 0xffff
            return True
        if n == 0x10:
            return True                                      # idle / ready / here
        return False

    def resend(self, s):
        p = self.sent.get(s)
        if p: self.sock.send(p); self.sock.send(p)
        else:
            q = self.hdr(0x10, 0, s); self.sock.send(q); self.sock.send(q)

    def tick(self, now):
        if now >= self.next_ping:
            self.ping(); self.next_ping = now + 0.5
        if self.idle_on and now >= self.next_idle:
            self.tracked(self.hdr(0x10, 0, 0))
            self.next_idle = now + (0.1 if now - self.last_tracked < 1 else 1.0)


class Radio:
    def __init__(self, a):
        self.a = a
        self.ctl = Stream("control", a.host, a.port, a.lport)
        self.inner = 0
        self.auth = b"\0" * 6
        self.guid = b"\0" * 16
        self.rname = b""
        self.civ = self.aud = None
        self.civ_seq = 0
        self.civ_rx = []                                     # received CI-V frames (bytes)
        self.next_token = 0

    # ---- control stream packets ----
    def inner_bytes(self):
        b = bytes([0, self.inner & 0xff, self.inner >> 8 & 0xff, 0])
        self.inner = (self.inner + 1) & 0xffff
        return b

    def login(self):
        p = bytearray(0x80)
        p[0:16] = self.ctl.hdr(0x80, 0, 0)
        p[0x10:0x14] = struct.pack(">I", 0x70); p[0x14] = 1; p[0x15] = 0
        p[0x16:0x1a] = self.inner_bytes()
        p[0x1a:0x1c] = os.urandom(2)
        p[0x40:0x50] = passcode(self.a.user); p[0x50:0x60] = passcode(self.a.password)
        p[0x60:0x67] = b"icom-pc"
        self.ctl.tracked(p)

    def token(self, magic):
        p = bytearray(0x40)
        p[0:16] = self.ctl.hdr(0x40, 0, 0)
        p[0x10:0x14] = struct.pack(">I", 0x30); p[0x14] = 1; p[0x15] = magic
        p[0x16:0x1a] = self.inner_bytes(); p[0x1a:0x20] = self.auth
        self.ctl.tracked(p)

    def conninfo(self):
        a = self.a
        p = bytearray(0x90)
        p[0:16] = self.ctl.hdr(0x90, 0, 0)
        p[0x10:0x14] = struct.pack(">I", 0x80); p[0x14] = 1; p[0x15] = 3
        p[0x16:0x1a] = self.inner_bytes(); p[0x1a:0x20] = self.auth
        p[0x20:0x30] = self.guid
        p[0x40:0x40 + len(self.rname[:32])] = self.rname[:32]
        p[0x60:0x70] = passcode(a.user)
        p[0x70] = 1; p[0x71] = 1; p[0x72] = a.codec; p[0x73] = 0x04
        p[0x74:0x78] = struct.pack(">I", a.rate); p[0x78:0x7c] = struct.pack(">I", a.rate)
        p[0x7c:0x80] = struct.pack(">I", a.lport + 1); p[0x80:0x84] = struct.pack(">I", a.lport + 2)
        p[0x84:0x88] = struct.pack(">I", 150); p[0x88] = 1
        self.ctl.tracked(p)

    def connect(self):
        c = self.ctl
        c.handshake()
        self.login()
        t0 = time.time(); state = "login"; auth_ok = have_cap = asked = False
        while time.time() - t0 < 10:
            r, _, _ = select.select([c.sock], [], [], 0.1)
            now = time.time()
            if state != "login": c.tick(now)
            if not r: continue
            d = c.sock.recv(65536)
            if c.common(d): continue
            n = len(d)
            if n == 0x60 and state == "login":
                if d[0x30:0x34] == b"\xff\xff\xff\xfe":
                    raise RuntimeError("login refused: wrong user / password")
                self.auth = d[0x1a:0x20]
                log(f"control: login ok ({d[0x40:0x50].rstrip(bytes(1)).decode(errors='replace')})")
                self.token(0x02); c.idle_on = True; c.next_ping = 0
                self.token(0x05); state = "token"
            elif n == 0x40 and d[0x15] == 0x05:
                if not auth_ok: log("control: token ok")
                auth_ok = True
            elif n >= 0xa8 and (n - 0x42) % 0x66 == 0 and d[4] == 0:      # capabilities, 0x66 per radio
                nr = struct.unpack_from("<H", d, 0x40)[0]
                cap = d[0x42:0x42 + 0x66]
                self.guid = cap[0:16]; self.rname = cap[0x10:0x30].rstrip(bytes(1))
                self.civ_addr = cap[0x52]
                log(f"control: {nr} radio(s): {self.rname.decode(errors='replace')} CI-V {self.civ_addr:02X} "
                    f"audio '{cap[0x30:0x50].rstrip(bytes(1)).decode(errors='replace')}' "
                    f"rx-sample caps {struct.unpack_from('>H', cap, 0x53)[0]:04x}")
                have_cap = True
            elif n == 0x90:
                log(f"control: stream request answered (busy={d[0x60]}, "
                    f"{d[0x64:0x74].rstrip(bytes(1)).decode(errors='replace')})")
            elif n == 0x50:
                err = d[0x30:0x34]
                if err[:3] == b"\xff\xff\xff":
                    raise RuntimeError("control: stream request refused (radio busy? another client connected?)")
                if err == b"\0\0\0\0" and d[0x40] == 1:
                    raise RuntimeError("control: radio says disconnected")
                if not asked:
                    continue
                cp, ap = struct.unpack_from(">H", d, 0x42)[0], struct.unpack_from(">H", d, 0x46)[0]
                log(f"control: status civ port {cp} audio port {ap}")
                self.cport, self.aport = cp or self.a.port + 1, ap or self.a.port + 2
                break
            if auth_ok and have_cap and not asked:
                self.conninfo(); asked = True
        else:
            raise RuntimeError(f"control: login sequence stuck in state {state}")
        self.next_token = time.time() + 60
        # CI-V and audio streams
        self.civ = Stream("civ", self.a.host, self.cport, self.a.lport + 1)
        self.civ.handshake(); self.civ.idle_on = True
        p = bytearray(0x16); p[0:16] = self.civ.hdr(0x16, 0, 0)
        p[0x10] = 0xc0; p[0x11] = 1; p[0x12] = 0; p[0x13:0x15] = struct.pack(">H", self.civ_seq); p[0x15] = 0x05
        self.civ_seq += 1
        self.civ.tracked(p)
        self.aud = Stream("audio", self.a.host, self.aport, self.a.lport + 2)
        self.aud.handshake()

    def civ_send(self, frame):
        n = len(frame)
        p = self.civ.hdr(0x15 + n, 0, 0) + bytes([0xc1, n, 0]) + struct.pack(">H", self.civ_seq) + frame
        self.civ_seq = (self.civ_seq + 1) & 0xffff
        self.civ.tracked(p)

    def close(self):
        try:
            if self.civ:
                p = bytearray(0x16); p[0:16] = self.civ.hdr(0x16, 0, 0)
                p[0x10] = 0xc0; p[0x11] = 1; p[0x13:0x15] = struct.pack(">H", self.civ_seq); p[0x15] = 0
                self.civ.tracked(p)
            self.token(0x01)
            time.sleep(0.3)
            for s in (self.aud, self.civ, self.ctl):
                if s: s.ctl(5)
        except OSError:
            pass


class Recorder:
    """audio packets -> in-order PCM (lost packets -> zeros) -> WAV files of file_time seconds"""

    def __init__(self, a):
        self.a = a
        ch = 2 if a.codec in (0x08, 0x10, 0x20, 0x80) else 1
        self.ch, self.bps = ch, (2 if a.codec in (0x04, 0x10) else 1)
        self.expect = None; self.hold = {}; self.hold_t = {}
        self.lost = self.pkts = self.rtx = 0; self.samples = 0; self.t_first = None
        self.w = None; self.w_end = 0; self.last_len = 0

    def add(self, seq, pcm, stream):
        self.pkts += 1
        if self.t_first is None: self.t_first = time.time()
        if self.expect is None: self.expect = seq
        dist = (seq - self.expect) & 0xffff
        if dist >= 0x8000: return                            # late duplicate
        self.hold[seq] = pcm; self.hold_t[seq] = time.time()
        if dist > 0:                                         # gap: ask again once
            s = self.expect
            while s != seq:
                if s not in self.hold and s not in self.hold_t:
                    q = stream.hdr(0x10, 1, s); stream.sock.send(q); self.rtx += 1
                    self.hold_t[s] = time.time()
                s = (s + 1) & 0xffff
        self.flush(False)

    def flush(self, force):
        now = time.time()
        while self.hold or force:
            if self.expect in self.hold:
                pcm = self.hold.pop(self.expect); self.hold_t.pop(self.expect, None)
                self.last_len = len(pcm); self.write(pcm)
            elif self.hold and min(t for s, t in self.hold_t.items() if s in self.hold) < now - 0.3:
                self.hold_t.pop(self.expect, None)
                self.lost += 1; self.write(bytes(self.last_len))
            else:
                break
            self.expect = (self.expect + 1) & 0xffff
            force = False

    def write(self, pcm):
        a = self.a
        if a.out is None: self.samples += len(pcm) // (self.bps * self.ch); return
        now = time.time()
        if self.w is None or now >= self.w_end:
            if self.w: self.w.close(); os.replace(self.tmp, self.fn)
            name = time.strftime("%Y%m%d_%H%M%S", time.gmtime(now)) + ".wav"
            self.fn = os.path.join(a.out, name); self.tmp = self.fn + ".part"
            self.w = wave.open(self.tmp, "wb"); self.w.setnchannels(self.ch)
            self.w.setsampwidth(self.bps); self.w.setframerate(a.rate)
            self.w_end = (now // a.file_time + 1) * a.file_time if a.align else now + a.file_time
        if self.bps == 1: pcm = bytes((b + 128) & 0xff for b in pcm)   # signed 8 bit -> WAV unsigned
        self.w.writeframesraw(pcm)
        self.samples += len(pcm) // (self.bps * self.ch)

    def close(self):
        if self.w: self.w.close(); os.replace(self.tmp, self.fn); self.w = None


def civ_frames(buf):
    out = []
    while True:
        i = buf.find(b"\xfe\xfe")
        j = buf.find(b"\xfd", i + 2) if i >= 0 else -1
        if i < 0 or j < 0: return out, (buf[i:] if i >= 0 else b"")
        out.append(buf[i:j + 1]); buf = buf[j + 1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True); ap.add_argument("--port", type=int, default=50001)
    ap.add_argument("--lport", type=int, default=50001, help="local ports lport..lport+2")
    ap.add_argument("--user", required=True); ap.add_argument("--password", required=True)
    ap.add_argument("--codec", type=lambda s: int(s, 0), default=0x04)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--out"); ap.add_argument("--file-time", type=int, default=600)
    ap.add_argument("--align", action="store_true", help="cut files on multiples of file-time (UTC)")
    ap.add_argument("--civ", action="append", default=[], help="CI-V frame (hex) sent after connecting")
    ap.add_argument("--civ-every", nargs=2, action="append", default=[], metavar=("SEC", "HEX"))
    ap.add_argument("--seconds", type=float, default=0, help="stop after N s (0 = run)")
    ap.add_argument("--stats", type=float, default=60)
    a = ap.parse_args()
    if a.out: os.makedirs(a.out, exist_ok=True)
    rad = Radio(a)
    rec = Recorder(a)
    civbuf = b""
    try:
        rad.connect()
        for h in a.civ:
            rad.civ_send(bytes.fromhex(h.replace(" ", "")))
        periodic = [[float(s), bytes.fromhex(h.replace(" ", "")), 0.0] for s, h in a.civ_every]
        t0 = time.time(); next_stats = t0 + a.stats; st0 = (t0, 0, 0)
        socks = {rad.ctl.sock: rad.ctl, rad.civ.sock: rad.civ, rad.aud.sock: rad.aud}
        while not a.seconds or time.time() - t0 < a.seconds:
            r, _, _ = select.select(list(socks), [], [], 0.05)
            now = time.time()
            for so in r:
                s = socks[so]
                try:
                    d = so.recv(65536)
                except ConnectionRefusedError:
                    continue
                if s.common(d): continue
                if s is rad.aud:
                    if len(d) >= 0x20 and d[4] != 1:
                        rec.add(struct.unpack_from("<H", d, 6)[0], d[0x18:], s)
                elif s is rad.civ:
                    if len(d) > 0x15 and d[0x10] == 0xc1:
                        fr, civbuf = civ_frames(civbuf + d[0x15:])
                        for f in fr:
                            if f[2] == 0xe0 or f[2] == 0x00:    # to us (or broadcast transceive)
                                log("CI-V <", f.hex(" "))
                elif s is rad.ctl:
                    if len(d) == 0x50 and d[0x30:0x33] == b"\xff\xff\xff":
                        raise RuntimeError("control: radio ended the session")
            for s in socks.values(): s.tick(now)
            rec.flush(False)
            if now >= rad.next_token:
                rad.token(0x05); rad.next_token = now + 60
            for p in periodic:
                if now >= p[2]: rad.civ_send(p[1]); p[2] = now + p[0]
            if now - rad.aud.last_rx > 10:
                raise RuntimeError("audio: nothing received for 10 s")
            if now >= next_stats:
                dt = now - st0[0]
                rate = (rec.samples - st0[1]) / dt
                log(f"stats: {rec.pkts} packets, lost {rec.lost}, retransmit asked {rec.rtx}, "
                    f"{rate:.1f} samples/s over {dt:.0f} s, buffered {len(rec.hold)}")
                st0 = (now, rec.samples, 0); next_stats = now + a.stats
    except KeyboardInterrupt:
        pass
    finally:
        rec.flush(True); rec.close(); rad.close()
        log(f"end: {rec.pkts} packets, lost {rec.lost}, samples {rec.samples}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        log("ERROR", e); sys.exit(1)
