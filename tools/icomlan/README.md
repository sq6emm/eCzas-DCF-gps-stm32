# icomlan: Icom radios over LAN / WLAN as reference receivers

Own receive-only client for the Icom network protocol (RS-BA1 style, UDP 50001-50003), written
after [kappanhang](https://github.com/nonoo/kappanhang) and [wfview](https://gitlab.com/eliggett/wfview)
(`include/packettypes.h`). Python standard library only. It never sends TX audio or PTT.

Purpose: the IC-705 (WLAN) and the IC-7610 (Ethernet, MAIN 225 kHz + SUB 77.5 kHz in parallel)
as reference receivers for e-CzasPL and DCF77, recording the radio's **12 kHz IF output**
instead of demodulated AF.

| file | what |
|---|---|
| `icomlan.py` | client: login, CI-V and audio streams, packet retransmit, 10-min WAV files (`--align`), CI-V commands at start (`--civ`) and periodic (`--civ-every`) |
| `ifconv.py` | IF -> 8 kHz "USB audio" with the carrier at 1 kHz: carrier to 0 Hz, complex low-pass +-900 Hz, back to 1 kHz, real part |
| `if2audio.py` | the same for one file (`--ch 1` = SUB of a stereo IC-7610 file) |
| `if2af_watch.py` | converts every finished IF file into the input directory of the eCzas reference pipeline |
| `cmp_usb_lan.py` | same time window, USB AF recording vs LAN IF, both through the eCzas firmware simulator |
| `spec.py` | spectrum / strongest lines of a recording |
| `eczas_proc.py` | copy of the e-CzasPL reference processor (`proc.py` of eczas-ic705-proc / eczas-ic7610-proc / kiwi-ref-proc): firmware sim + slot classifier per 10-min file; each file gets the last 30 s of the previous one in front (the frame across the join is no longer lost) |
| `dcf7610.py` | IC-7610 SUB (DCF77) -> 2 kHz complex files, hourly `dcfsim` + `dcfminsim` (the NUCLEO code) |
| `k9ay_scan.sh`, `k9ay_analyse.py` | K9AY direction / LNA scan during one IC-7610 recording, C/N0 per setting |

Run (credentials are the radio's *Network User* settings, not stored here):

    python3 icomlan.py --host <radio ip> --user <user> --password <password> --lport 50101 \
        --out rec --file-time 600 --align --civ "FE FE A4 E0 1A 05 01 14 01 FD"

Notes
- IC-705: CI-V A4. `1A 05 0114` = WLAN AF/IF output select (00 AF, 01 IF). WLAN itself, the
  network and the network user can only be set on the radio (not in the CI-V command set).
- The IF is real and not inverted: RF f appears at 12 kHz + (f - dial). Dial 224.000 kHz ->
  e-CzasPL at 13000 Hz; the passband is about 2-22 kHz.
- Codecs: 0x04 PCM16 mono, 0x10 PCM16 stereo (IC-7610: MAIN left, SUB right).
- IC-7610: CI-V 98, MAIN/SUB command prefix `29 00` / `29 01`, dual watch `07 C1` (wfview rig file).
- First result, IC-705, 28 Sep 2026 09:17:32-09:27:32 UTC, same 10 minutes: USB AF 15 frames
  decoded, WLAN IF 18 (73 vs 61 candidates). WLAN: 0 packets lost in 60001 (6 retransmitted).
  A first two-sided conversion (plain real part) gave only 7: the band below the dial folded
  onto the carrier.

IC-7610 (28 Sep 2026, Ethernet 192.168.253.4)
- The LAN IF is MIRRORED (unlike the IC-705), in USB and LSB alike: RF f -> 12 kHz - (f - dial).
  Dials 1 kHz above the stations put both carriers at 13000 Hz: MAIN 226.000 kHz (e-CzasPL),
  SUB 78.500 kHz (DCF77), USB, FIL1. `ifconv.if_to_usb(..., invert=True)` / `--invert` conjugates
  at 0 Hz; the e-CzasPL simulator decodes 27 time frames in 9 min inverted, 0 upright.
- Codec 0x10 (PCM16 stereo, 48 kHz): left = MAIN, right = SUB; -29 dB MAIN->SUB crosstalk.
- Levels, 28 Sep ~19:45-19:55 UTC, K9AY (BPF bypassed): e-CzasPL 50-55 dB-Hz in every direction
  (AGC holds it at -18 dBFS); DCF77 is receiver-noise limited (N0 flat): NW+LNA 26.8, NE+LNA 26.4,
  SW 23.7, SE 23.6 ... NW 11.7 dB-Hz. Preamp on DCF77: P2 26.2, P1 21.0, off 16.9 dB-Hz; ATT 6/12/18 dB
  costs 3/8/13 dB. Chosen: K9AY 3074 (NW+LNA), P2, ATT off.
