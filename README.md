# eCzas-DCF-gps-stm32

Time and frequency reception on an STM32 (NUCLEO-H723ZG): e-CzasPL (225 kHz) and
DCF77 (77.5 kHz) sampled directly by the ADC, with GPS as the third reference. The
goal is to compare the three and discipline an OCXO with them.

The e-CzasPL frame decoder and timekeeper are the unchanged core of the eCzas receiver
firmware ([sq6emm/eCzasPL-TimeReceiver225kHz](https://github.com/sq6emm/eCzasPL-TimeReceiver225kHz)),
included as the `eczas` submodule.

## Status (27 Sep 2026)

- **e-CzasPL:** works. With a ferrite rod on the ADC, the Nucleo decodes **~93 %** of
  time frames next to an IC-705 reference, against ~17 % for the eCzas board at the
  noisy Legnica site. No wrong times.
- **DCF77:** found through the same (225 kHz-tuned) antenna, assisted by eCzas time:
  amplitude pattern 53× and the exact 512-chip phase code at 19.8σ in 2.5 h,
  8.5 ms ahead of the Nucleo's (uncalibrated) eCzas second.
- **GPS, OCXO:** planned, see [PLAN.md](PLAN.md).

Details: [doc/RESULTS.md](doc/RESULTS.md).

## Layout

| path | content |
|---|---|
| [`firmware/nucleo-h723/`](firmware/nucleo-h723/README.md) | receiver firmware: hardware, signal path, clock, build, output |
| `tools/` | serial/audio logger and analysis scripts (below) |
| `doc/` | input schematic, [results](doc/RESULTS.md) |
| [`PLAN.md`](PLAN.md) | next steps: DCF77 antenna, carrier-phase lock, OCXO, GPS |
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

