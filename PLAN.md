# Plan

Target: an OCXO disciplined by three independent references (e-CzasPL, DCF77, GPS),
which the STM32 measures against each other and against the OCXO.

## 1. Receiver: from "SI4735 emulation" to direct demodulation

Today the Nucleo builds the same 10 kHz "audio" the SI4735 gives the dsPIC and feeds
the unchanged eCzas core, on purpose, to test the radio side alone. With raw ADC
access more is possible:

- **Coherent demodulation on the complex baseband**: the mixer is locked to the
  reference clock, so the carrier frequency is known to ppm level; a much narrower
  carrier loop, no 1 kHz tone, no image.
- **Slot-synchronous decoding**: once synchronised, the 3-s slot grid is known;
  correlate every slot with the expected frame instead of first detecting a preamble.
- **Timing**: time-stamp the phase transitions of all 96 bits against the crystal
  (µs level per frame instead of the ~0.6–0.9 ms scatter of today), and track the
  225 kHz **carrier phase** itself as a frequency reference.
- Limits: accuracy against UTC needs a delay calibration (propagation Solec
  Kujawski–Wrocław ~0.8 ms, Mainflingen–Wrocław ~1.9 ms); at night the sky wave
  moves the carrier phase.

## 2. DCF77

- Now: second phase-locked mixer at 77.5 kHz on the eCzas antenna (tuned to ~217 kHz).
  DCF77 is 20–30 dB below what a tuned antenna would give; eCzas-assisted correlation
  finds it anyway (doc/RESULTS.md).
- **Phase code** (512-chip PRN, x^9+x^5+1, 120 carrier cycles per chip, from 200 ms,
  inverted for data bit 1): detected at 15σ in 2.5 h (doc/RESULTS.md). Next: resolve
  the whole-chip offset (PTB's register start state), then track the timing per
  ~10 min block against eCzas.
- Proper antenna (when available): second ferrite rod with **10 nF + 1.5 nF** in
  parallel (≈78 kHz on a 360 µH rod) on **A1 (PC0)**, same 10k/10k bias and 100 nF
  coupling; firmware: ADC2 in parallel with ADC1.
- A mini-whip (broadband, 10 kHz–30 MHz) would cover both signals with one antenna,
  but needs an outdoor mount, a bias-T and a ~300 kHz anti-alias low-pass (medium
  wave at 775 / 922.5 kHz aliases onto 225 / 77.5 kHz at 1 Msps). Not now.

## 3. Clock: OCXO

- The Nucleo has **no HSE crystal** (X3 is an empty footprint); the default HSE is the
  ST-LINK's MCO, measured ~0.9 % off and wandering ±700 ppm. Today the CPU runs on
  HSI and the 32.768 kHz LSE crystal (X2) is the time reference (+0.9…1.0 ppm,
  untunable, temperature-dependent).
- OCXO on hand: **Wenzel 500-06769, 100 MHz "high level"** (supply, output level and
  EFC range: read from the label; typical Wenzel: +12/+15 V, sine ~+13 dBm, EFC 0–10 V).
- Interface:
  ```
  OCXO 100 MHz -> splitter (keep a clean 100 MHz output)
               -> sine-to-CMOS squarer (e.g. LTC6957-3) -> /4 = 25 MHz (or /10 = 10 MHz)
               -> NUCLEO HSE bypass (PH0; solder bridges per UM2407)
  EFC <- low-noise op-amp <- 16–20-bit DAC (e.g. AD5683R, AD5541) + quiet reference
  ```
  The H723 HSE input takes at most 50 MHz; the internal 12-bit DAC is too coarse.
- With the OCXO as HSE, CPU, timers and the ADC sample clock are all coherent with it:
  the LSE work-around goes away and the eCzas/DCF77 carrier phases are measured
  directly against the OCXO.

## 4. GPS

- A **timing** receiver: survey-in / fixed position, qErr (`UBX-TIM-TP`) sawtooth
  correction, PPS into a 32-bit timer capture (5 ns at 200 MHz).
- **u-blox NEO-M8T / LEA-M8T** (~20 ns, sawtooth-correctable): enough, because e-CzasPL
  and DCF77 are good to µs at best. **ZED-F9T** (dual band, ~5 ns): if the setup should
  become a lab reference. Avoid navigation modules (NEO-6M/M8N/M10) and clones.
- Active antenna with sky view (L1, or L1/L5 / L1/L2 for the F9T).

## 5. Disciplining

| reference | best at | weakness |
|---|---|---|
| GPS | hours–days (~1e-13/day) | noisy second to second |
| e-CzasPL carrier phase | minutes–hours by day (strong ground wave) | night sky wave; carrier traceability to confirm |
| DCF77 carrier / phase code | independent, PTB-traceable | weak on the current antenna; night sky wave |

The OCXO holds the short term (s–min); a weighted loop uses each reference at its
best time scale, and the three-way comparison shows which one misbehaves.

## Order

1. DCF77 phase code on the current setup.
2. Interface PDF for the OCXO (after the label specs), Nucleo on the OCXO with EFC fixed;
   measure its drift against e-CzasPL and DCF77.
3. GPS + DAC, close the loop.
