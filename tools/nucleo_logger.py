#!/usr/bin/env python3
"""Log the NUCLEO receiver's serial port: text lines with host UTC time, and
(AUDIO_DUMP builds) the core's 10 kHz input as 10-minute WAV files plus an index
of (first sample number, host time) per packet for alignment with other receivers."""
import datetime, os, serial, struct, sys, time, wave

DEV, BAUD, OUT = sys.argv[1], int(sys.argv[2]), sys.argv[3]
PK = 2 + 4 + 400
os.makedirs(OUT, exist_ok=True)
s = serial.Serial(DEV, BAUD, timeout=0.2)
log = open(os.path.join(OUT, "rx.log"), "a", buffering=1)
wav = idx = None
wav_t0 = 0
last_n = None
buf = b""
line = b""


def utc():
    return datetime.datetime.now(datetime.timezone.utc)


def open_wav(now):
    global wav, idx, wav_t0
    if wav:
        wav.close(); idx.close()
    name = now.strftime("nucleo_%Y%m%d_%H%M%S")
    wav = wave.open(os.path.join(OUT, name + ".wav"), "wb")
    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(10000)
    idx = open(os.path.join(OUT, name + ".idx.csv"), "w", buffering=1)
    idx.write("sample_n,host_unix\n")
    wav_t0 = time.time()


while True:
    buf += s.read(8192)
    now_t = time.time()
    i = 0
    while i < len(buf):
        if buf[i] == 0xA5 and i + 1 < len(buf) and buf[i + 1] == 0x5A:
            if len(buf) - i < PK:
                break
            n0 = struct.unpack_from("<I", buf, i + 2)[0]
            data = buf[i + 6:i + PK]
            now = utc()
            if wav is None or time.time() - wav_t0 >= 600:
                open_wav(now)
            if last_n is not None and n0 != (last_n + 200) & 0xFFFFFFFF:
                log.write(f"{now.isoformat(timespec='milliseconds')} LOGGER gap: sample {last_n + 200} -> {n0}\n")
                open_wav(now)
            last_n = n0
            wav.writeframes(data)
            idx.write(f"{n0},{now_t:.3f}\n")
            i += PK
            continue
        c = buf[i:i + 1]
        i += 1
        if c == b"\n":
            txt = line.decode(errors="replace").strip()
            if txt:
                log.write(f"{utc().isoformat(timespec='milliseconds')} {txt}\n")
            line = b""
        elif c != b"\r":
            line += c
            if len(line) > 1000:
                line = b""
    buf = buf[i:]
