# LF time & frequency receiver board — design draft (v0.1, 28 Sep 2026)

One board that does what the NUCLEO + rods do today, plus a GPS timing receiver as the truth
reference and an OCXO steered from e-CzasPL and/or DCF77. Draft for discussion; nothing is
fixed. Everything below is a proposal with the reason next to it.

## 1. Goals

| # | Goal | How we know it works |
|---|---|---|
| G1 | receive e-CzasPL 225 kHz and DCF77 77.5 kHz at the same time, independently | same results as the NUCLEO today (e-CzasPL frames, DCF77 time every minute, phase code) |
| G2 | OCXO steered to a station carrier (DCF77 first, e-CzasPL once its carrier is characterised) | OCXO vs GPS PPS: < 1e-11 over a day, holdover behaviour known |
| G3 | GPS PPS as an independent truth for calibration and monitoring | offsets of e-CzasPL frames and DCF77 seconds against UTC, to < 10 us |
| G4 | outputs: 10 MHz (e.g. IC-7610 REF IN), 1PPS, time/data over USB and Ethernet | a counter / the IC-7610 locks to it; NTP later |
| G5 | reuse the NUCLEO firmware unchanged where possible | same STM32H723 family, same ADC scheme |

Non-goals for v1: transmitting anything, sub-ns timing (that is a GPSDO job), battery operation.

## 2. Block diagram

```
 ROD 1 (225 kHz) ─tw.pair─┐                         ┌──────────────── STM32H723 ────────────────┐
 ROD 2 (77.5 kHz)─tw.pair─┤  AFE x2:                │ ADC1 ◄─ AFE1   ADC2 ◄─ AFE2  (1-3.6 Msps)  │
                          ├► tuning C at the board  │ OSC_IN ◄─ OCXO 10 MHz (HSE bypass)         │
                          │  shared 1.65 V bias     │ TIMx CH ◄─ GPS PPS  (capture, 2.5-5 ns)    │
                          │  protection, anti-alias │ USARTy ◄─► GPS UBX (qErr, time)            │
                          │  (optional gain stage)  │ SPI ─► EFC DAC 16 bit ─► OCXO tuning       │
 GPS antenna (SMA) ──► u-blox timing module ──PPS──►│ TIMz CH ─► 1PPS out (SMA)                  │
 OCXO 10 MHz ───────────┬──► MCU clock              │ USB-C (CDC)   Ethernet RMII ─► PHY ─► RJ45 │
   (on board or         └──► buffer ─► 10 MHz out x2 (SMA)                                       │
    external via SMA)                               └────────────────────────────────────────────┘
 12 V in ─► buck 5 V (OCXO, GPS) ─► LDOs: 3.3 V digital, 3.3 V analog (low noise), VREF for the ADC
```

Key idea: **the OCXO clocks everything** (CPU, ADC sample timer, PPS capture timer). Then the
carrier trackers measure the OCXO directly against the station (phase in OCXO time), the GPS
PPS capture measures it against GPS, and the steering loop closes on either — with no LSE
interpolation any more (the LSE crystal becomes unnecessary; keep a footprint).

## 3. Blocks

### 3.1 Antenna front ends (x2)
What we learned on the NUCLEO:
- Direct sampling works. With the tuned rod the ADC is **not** the limit: the DCF77 carrier sits
  about 40 dB below full scale and the 16-bit ADC's own noise would allow C/N0 far above the
  16-17 dB-Hz we get — the limit is the received noise (local interference, the rod). So no LNA
  is needed for sensitivity; a gain stage only helps with long cables or low-level rods.
- The tuning capacitor belongs at the board end, both cold ends on one decoupled bias node.

Proposal per channel:
- 2-pin connector (screw terminal or JST-XH) for the twisted pair; rod alone at the far end.
- Tuning: C0G fixed capacitor + a **footprint for a small trimmer / plug-in pair** so each rod can
  be trimmed without soldering (225 kHz: ~1.4 nF; 77.5 kHz: ~11.2 nF for 375 uH).
- Protection: 330 Ohm series (as now) + low-capacitance dual diode (BAV99 / BAT54S) to the rails
  + a TVS on the connector (PESD-type, < 5 pF) — outdoor rods see ESD and nearby lightning.
- **Anti-alias filter** (new): at 1 Msps, medium-wave broadcasters alias onto our bands
  (e.g. 775 kHz -> 225 kHz). The tuned rod gives ~25-30 dB of rejection; add a 2-3 pole LC/RC
  low-pass (~400 kHz) or sample faster (the H7 ADC does 16 bit at up to ~3.6 Msps; the firmware
  decimates anyway).
- **Optional gain stage** (populate if needed): JFET (BF862) or low-noise op-amp (e.g. OPA1611 /
  ADA4898) non-inverting, gain 1-20, between tank and ADC, with a jumper to bypass. It also
  isolates the tank from the ADC's sampling kick-back.
- A small shield can over both front ends; analog ground island under them.

### 3.2 MCU: STM32H723VGT6 (LQFP-100) — or ZGT6 (LQFP-144) as on the NUCLEO
- Same core, ADCs, HAL and firmware as now (G5). 2 x 16-bit ADC (ADC1/ADC2) in dual
  simultaneous mode, exactly as the current firmware.
- Clock: **HSE in bypass mode from the OCXO** (10 MHz square / clipped sine -> needs a clean
  3.3 V square; a comparator/squarer if the OCXO gives sine). PLL -> 400-550 MHz core,
  ADC kernel clock from PLL2, all timers from the OCXO.
- **ADC reference**: dedicated low-noise VREF+ (REF3030/REF3330, 3.0/3.3 V) instead of the
  digital supply — the NUCLEO uses VDDA; a clean reference lowers the ADC noise floor further.
- Ethernet MAC (RMII) + USB OTG FS on-chip.

### 3.3 GPS timing receiver
Options (u-blox):

| module | PPS accuracy | qErr (sawtooth) correction | notes | approx. price |
|---|---|---|---|---|
| **ZED-F9T** | ~5 ns (dual band) | yes | best, dual-band antenna needed | high (~200 EUR) |
| **LEA-M8T / NEO-M8T** | ~20 ns | yes (TIM-TP) | timing firmware, single band, survey-in / fixed position | ~50-90 EUR |
| NEO-M8N / M9N | ~30-60 ns | no | navigation module, PPS OK for our ms/us questions | ~15-30 EUR |

Recommendation: **NEO-M8T or LEA-M8T** — timing firmware (fixed-position mode, qErr), far
beyond what we need (our questions are at 0.1 ms and 1e-11). ZED-F9T only if we later want
a GPSDO-grade reference.
- PPS -> 32-bit timer input capture clocked from the OCXO PLL (2.5-5 ns resolution); the qErr
  from UBX-TIM-TP corrects each edge.
- UART for UBX; backup supply (supercap) for fast restarts; SMA antenna input with 3.3/5 V
  antenna bias through a current limiter (active antenna, short-circuit safe).

### 3.4 OCXO
**Will the CTI OCXOs be enough? Very likely yes.** A steered OCXO only has to be better than the
reference over the loop time constant: the station carriers are measured with ~1e-8 at 1 min
(today's first data) and only reach 1e-11...1e-12 after hours, so the loop time constant is
1000-10000 s and the OCXO must hold ~1e-11 over that time — typical 10 MHz OCXOs (ADEV ~1e-11
from 1 to 100 s, aging ~1e-9/day, temperature ~1e-9 over the range) do. The loop removes aging
and temperature drift. Needed from you: **the exact CTI model / markings** (e.g. OSC5A2B02-type:
supply 5 V or 12 V, square or sine output, EFC range and slope, warm-up current).

Proposal:
- On-board footprint for the CTI package **and** an SMA/header input so any other OCXO or a
  GPSDO can be plugged instead (and to compare OCXOs).
- Own low-noise supply (LDO like LT3045 from 5 V, or 12 V rail if a 12 V OCXO), sized for the
  warm-up current (often 0.3-0.6 A for a few minutes).
- EFC: **16-bit DAC** (DAC8551 / AD5541A) + precision reference (REF5040, 4.096 V) + RC/2-pole
  filter + divider matched to the OCXO's EFC range. With a typical +-0.5 ppm over 4 V the step
  is ~1.5e-11 per LSB (dithering / 18-20-bit AD5781 if finer steps are needed).
- Temperature sensor next to the OCXO (TMP117) — for the loop and the holdover model.
- Thermal: OCXO away from the regulators, under a foam cover in the enclosure.

### 3.5 Outputs and interfaces
- **10 MHz out x2 (SMA)**: buffered from the OCXO; one 50-Ohm sine-ish (LPF) for the IC-7610
  REF IN, one square (for a counter / other gear).
- **1PPS out (SMA)**: from a timer output-compare, aligned to UTC (via GPS, or DCF77/e-CzasPL
  when GPS is absent).
- **USB-C**: CDC serial (the text lines as now) + firmware update (DFU).
- **Ethernet (LAN8742A PHY + RJ45 with magnetics)**: logging without USB, later an NTP server
  (the H7 has hardware timestamping for PTP too).
- SWD (Tag-Connect or 10-pin), UART debug header, LEDs (e-CzasPL lock, DCF77 lock, GPS fix,
  OCXO locked/holdover), one push button.

### 3.6 Power
- 12 V DC barrel/terminal (the OCXO warm-up needs it; USB alone is too weak) -> buck 5 V (3 A)
  -> LDOs: 3.3 V digital, 3.3 V analog (low noise, separate), VREF for the ADC, OCXO supply.
- Reverse-polarity and over-voltage protection on the input.

### 3.7 PCB
- 4 layers (signal / GND / power / signal), about 100 x 80 mm, fits a standard aluminium case.
- Zones: analog front end (shielded, one corner, next to the rod connectors), OCXO + clock
  (other corner, short clock trace to OSC_IN), digital/MCU in the middle, power at the input.
- All RF connectors on one edge.

## 4. Firmware changes (from the NUCLEO firmware)
1. Time base: OCXO instead of LSE interpolation (simpler: every sample is exactly N OCXO ticks).
2. GPS: PPS capture + UBX qErr -> "GPS" lines; offsets of e-CzasPL frames / DCF77 seconds vs UTC.
3. Steering loop: carrier phase (DCF77, later e-CzasPL) -> PI loop -> DAC; states: warm-up,
   acquire, locked, holdover; GPS as monitor (or as a third selectable reference).
4. Outputs: 1PPS output compare; NMEA/text; Ethernet later.
The e-CzasPL and DCF77 receivers (coh.c, ecz.c, eCzas core, dcf.c, dcfbits.c) stay as they are.

## 5. Open questions (for the user)
1. CTI OCXO: exact model/markings, supply voltage, output type, EFC range; how many, same type?
2. GPS module: NEO-M8T/LEA-M8T (recommended) or ZED-F9T? Antenna type you have?
3. Ethernet on v1: yes / later?
4. Board size / enclosure you have in mind; connectors (screw terminals vs JST for the rods)?
5. Power: 12 V available where it will run?
6. Tools: KiCad for schematic/layout? Who assembles (JLCPCB/PCBWay assembly or hand)?
7. Rod cable length at the final site (decides whether the gain stage is populated).

## 6. Implementation plan (proposal)
1. Answer the open questions -> freeze the block diagram (v0.2 of this document).
2. Schematic in KiCad (I can prepare it as KiCad files block by block; review each block).
3. Before the PCB: prove the two new blocks on the NUCLEO — GPS PPS capture (a GPS module on a
   timer pin) and OCXO as HSE + EFC DAC on a breadboard — so the board only integrates proven parts.
4. Layout, DRC, order (assembled), bring-up plan with test points.
