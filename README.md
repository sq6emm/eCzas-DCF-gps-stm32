# eCzas-DCF-gps-stm32

Time and frequency reception on an STM32 (NUCLEO-H723ZG): e-CzasPL (225 kHz) and
DCF77 (77.5 kHz) sampled directly by the ADC, with GPS as the third reference. The
goal is to compare the three and discipline an OCXO with them.

The e-CzasPL frame decoder and timekeeper are the unchanged core of the eCzas receiver
firmware ([sq6emm/eCzasPL-TimeReceiver225kHz](https://github.com/sq6emm/eCzasPL-TimeReceiver225kHz)),
included as the `eczas` submodule.

## Status (8 Nov 2026)

- **e-CzasPL:** decodes ~300 of ~400 time frames per hour on a ferrite rod at the noisy
  Wrocław site (C/N0 ~45 dB-Hz); a frame is accepted only after a CRC and plausibility checks
  (2025–2045, Reed–Solomon fixes vs SNR); the first sync needs three agreeing frames.
- **DCF77:** standalone receiver (second marks, minute, PRN phase code, full time code)
  on its own rod; weak at this site (~10–15 dB-Hz), so it is a fallback, not the main reference.
- **OCXO:** a 10 MHz OCXO (CTI OSC5A2B02) is the time reference: its edges are captured
  on PA0, and the sample times and mixers are computed against it. EFC from the internal
  12-bit DAC (PA5, dithered, 0.816 ppb/code).
- **GPS:** u-blox NEO-7P (stationary mode, 25 ns cable delay), PPS on PC8 (TIM3 capture).
  **The OCXO is phase-locked to the GPS PPS** (PI loop, 600 s) while the GPS is locked
  and plausible; a gate suspends the GPS on a phase jump (> 300 ns, checked per pulse) or
  when its frequency disagrees with both stations (> 10 ppb); holdover 60 min, then
  DCF77 / e-CzasPL steer. Time error against GPS: tens of ns.
- **Carriers against GPS** (Oct–Nov 2026): DCF77 0.00 ppb; e-CzasPL −0.80 ppb. GUM's own
  monitoring against UTC(PL) (20.10–02.11, shared by GUM) gives −0.806 ppb; the two agree
  within a few 1e-11. GUM: the carrier and the frame timing come from an OCXO for now,
  rubidium planned (Nov–Dec 2026).
- **e-CzasPL second against GPS:** 10.6 ms late (2 Oct) drifting +0.074 ms/day (= the
  carrier offset) to 12.1 ms; GUM resynchronised via NTP on 21 Oct 06:33:43 UTC
  (−10.8 ms), ~2.2 ms late on 4 Nov. Reference point = start of the 16-bit sync (GUM).
- **Early frames:** a time frame sent 2.4 s early (in slot S instead of S+3), ~1 in 400,
  verified in raw recordings; gone since GUM reduced the frame lead by 0.2 s on
  4 Nov 2026 ~12:00 UTC.
- **Live page:** `tools/dashboard` (container `nucleo-dashboard`): carriers and time
  against GPS, Allan deviation, OCXO, decodes per hour, the early-frame report.

Details: [doc/RESULTS.md](doc/RESULTS.md).

## Layout

| path | content |
|---|---|
| [`firmware/nucleo-h723/`](firmware/nucleo-h723/README.md) | receiver firmware: hardware, signal path, clock, build, output |
| `tools/` | serial/audio logger and analysis scripts (below) |
| `doc/` | input schematics, GPS PPS wiring (`nucleo_gps_pps.pdf`), antenna head, [results](doc/RESULTS.md) |
| `firmware/host/` | host builds of the firmware's C code: `efcgpssim` / `efcgpsreplay` (OCXO loop, GPS gate), `dcfsim` / `dcfminsim`, `tdfsim`, `cohsim` |
| [`PLAN.md`](PLAN.md) | plan and status: antennas, OCXO, GPS, disciplining |
| `eczas/` | submodule: the eCzas receiver repo (the core is `eczas/Firmware/src/core`) |

```
git clone --recurse-submodules git@github.com:sq6emm/eCzas-DCF-gps-stm32.git
```

## Tools

| file | purpose |
|---|---|
| `tools/nucleo_logger.py` | serial logger: text lines with host UTC time to `rx.log`; for `AUDIO_DUMP` builds, 10-min 10 kHz WAVs plus an index (sample number ↔ host time) |
| `tools/nucleo_logger_run.sh` | (re)creates the container `nucleo-logger`: the logger plus an hourly rotation (`.c64`/`.wav` older than 7 days deleted, their `.idx.csv` gzipped) |
| `tools/prof.py` | carrier spectrum profile (dBc/Hz at 0.5–600 Hz offset); shows clock phase noise |
| `tools/nucleo_ana.py` | phase of the known preamble bits in slots where the IC-705 saw a time frame: true bit separation and noise |
| `tools/dcf_track.py` | per 10-min UTC block: exact phase-code lag and σ (also over 30 min), amplitude-pattern lag, DCF77 carrier, LSE ppm, e-CzasPL frames/noise (runs as container `nucleo-dcf-track`) |
| `tools/dcf_pm.py` | DCF77 phase-code search on per-second rows saved by `dcf_assist.py` (`DCF_SAVE=file.npz`) |
| `tools/dcf_assist.py` | DCF77 from the 77.5 kHz channel, assisted by eCzas time: carrier, amplitude-pattern correlation, bit check, phase-code search |
| `tools/compare3.py` | slot-by-slot comparison of the Nucleo, the Legnica eCzas board and the IC-705 reference |
| `tools/carriers_vs_gps.py` | DCF77 and e-CzasPL carrier frequency against GPS from the `REFS` lines: offset, scatter, Allan deviation, day/night, hourly (container `carriers-vs-gps`) |
| `tools/gps_monitor.py` | GPS receiver status every second (NAV-STATUS, NAV-TIMEUTC, TIM-TP, GGA): lock, satellites, tAcc, qErr; alerts on lock lost (container `gps-monitor`) |
| `tools/gps_calib.py` | e-CzasPL and DCF77 seconds against the GPS PPS from the `GPS PPS` lines |
| `tools/dashboard/` | web page (container `nucleo-dashboard`, port 8077): charts from `rx.log`, static early-frame report in `static/` |
| `tools/efc_replay_extract.py` | per-minute OCXO-loop inputs from a log, for `firmware/host/efcreplay` |
| `tools/carrier_cmp.py` | e-CzasPL carrier against the DCF77 carrier from the `CARRIER` lines |
| `tools/timing_models.py` | bias-free timing models (18.6 ms e-CzasPL ramp, DCF77 chips) for the fit tools below |
| `tools/nucleo_timing_check.py` | where the NUCLEO's seconds sit, checked with model fits on its own 2 kHz dumps |
| `tools/tdf_vs_eczas_timing.py` | TDF (or DCF77) second against e-CzasPL in one IC-7610 stereo recording; see `tools/tdf/` |
| `tools/eczas_transition_shape.py` | shape of e-CzasPL phase transitions (ramp length) from IC-7610 recordings |
| `tools/dcf_peak_sim.py` | bias of the DCF77 phase-code sub-sample peak estimator |
| `tools/dcfbench.py`, `dcfminbench.py`, `tdfbench.py` | decoder benches on GPS-timed Kiwi / IC-7610 recordings with calibrated noise |
| `tools/icomlan/`, `tools/kiwi/` | IC-7610 LAN recorder and KiwiSDR reference recorder with their processors |

