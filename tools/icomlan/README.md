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
