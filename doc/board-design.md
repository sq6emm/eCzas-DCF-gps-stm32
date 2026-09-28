# LF time & frequency receiver board — design draft (v0.3, 28 Sep 2026)

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

### 3.4 OCXO: CTI OSC5A2B02 (the user has many)
Datasheet (scan, e.g. dl6gl.de/media/files/ocxo-cti-osc5a2b02-datasheet.pdf):

| parameter | value |
|---|---|
| frequency | 10.00 MHz, initial accuracy <= +-200 ppb (Vc = 2.0 V, 25 C, 15 min after power-on) |
| supply | +5.0 V +-5 %, <= 600 mA at start, <= 250 mA stable; within +-100 ppb after <= 5 min |
| output | HCMOS, VOH >= 4.5 V, VOL <= 0.5 V, 15 pF load, rise/fall <= 6 ns, duty 45/55 % |
| control ("Vref" pin = EFC input) | 2.0 +- 2.0 V, positive slope; -2.0..-1.0 ppm at 0 V, -0.2..+0.2 at 2 V, +1.0..+2.0 at 4 V (~0.75 ppm/V), linearity < +-10 %, input >= 100 kOhm, bandwidth > 10 kHz |
| stability | ageing <= +-0.5 ppb/day (after 30 days), <= +-100 ppb first year; temperature <= +-10 ppb (0..75 C); short term <= 0.05 ppb/s; supply +-5 % -> <= +-2 ppb; load +-5 % -> <= +-2 ppb |
| phase noise | -80 dBc/Hz @1 Hz, -120 @10 Hz, -140 @100 Hz, -145 @1 kHz, -150 @10 kHz |
| package | 25.4 x 25.4 x 12.5 mm, 5 pins: 1 Out, 2 GND, 3 Vref (EFC), 4 NC, 5 Vcc |

Enough? **Yes.** A steered OCXO only has to beat the reference over the loop time constant: the
station carriers need hours to reach 1e-11...1e-12 (first comparison: 1.4e-8 at 60 s), so the loop
runs at 1000-10000 s and this OCXO (5e-11 at 1 s, ageing 0.5 ppb/day, 10 ppb over 0-75 C) is far
better over that time; the loop removes ageing and temperature. Holdover: ageing alone adds
~20 us per day of time error. With many units: burn in a few against the GPS PPS, fit the best.

Design consequences:
- **Supply**: own low-noise linear 5 V for 0.6 A warm-up / 0.25 A running (e.g. buck to ~6 V, then
  a 1 A LDO such as TPS7A4701); 2 ppb per 5 % supply change -> the supply must be quiet and stable.
- **Clock to the MCU**: 5 V HCMOS -> 74LVC1G17 (3.3 V supply, input tolerant to 5.5 V) -> OSC_IN
  (HSE bypass). Short trace, series 33 Ohm, ground guard.
- **10 MHz outputs**: separate buffer(s) from the OCXO pin (e.g. 74AC04 / 74LVC2G14 on 5 V for
  the square output; + 50 Ohm, attenuator and LPF footprint for a sine-ish output to the IC-7610
  REF IN), so a load on an output cannot disturb the MCU clock.
- **EFC**: 16-bit DAC (DAC8551 / AD5541A) + REF5040 (4.096 V). Full 0-4.096 V gives 62.5 uV =
  ~4.7e-11 per LSB (0.75 ppm/V) - coarse against the 1e-11 goal, so the DAC output goes through a
  divider/offset network to ~1.0-3.0 V (still +-0.75 ppm, covers the +-200 ppb initial offset
  and years of ageing): ~2.3e-11 per LSB, finer by dithering inside the loop time constant.
  Alternative: 18-bit DAC (DAC9881 / AD5781). 2-pole RC after the DAC (corner ~1-10 Hz).
- Temperature sensor next to the OCXO (TMP117); foam cover in the enclosure, away from the regulators.
- Footprint for the OSC5A2B02 **and** an SMA/header input for an external 10 MHz (other OCXO / GPSDO).

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

## 5. Decisions (28 Sep 2026)
| topic | decision | consequence |
|---|---|---|
| OCXO | CTI OSC5A2B02, 5 V, many units | section 3.4; hand-soldered (through-hole), not by JLCPCB |
| GPS | **u-blox LEA-M8T** (the user has one), standard active "mouse" antenna (SMA) | LEA footprint (17 x 22.4 mm, 28-pin castellated), hand-soldered; antenna bias from the module's VCC_RF (~3 V) through a ferrite + current limit; PPS = TIMEPULSE, TIMEPULSE2 to a second capture; UART + UBX (TIM-TP for qErr), V_BCKP from a supercap |
| Ethernet | **yes** | LAN8742A (RMII) + RJ45 with integrated magnetics; 50 MHz RMII clock from the PHY's own 25 MHz crystal (keeps the OCXO clock tree clean) |
| power | **12 V DC in** | reverse/over-voltage protection, buck 12 -> 6 V (OCXO warm-up 0.6 A + GPS + digital), then low-noise LDOs: 5.0 V OCXO, 3.3 V digital, 3.3 V analog, VREF for the ADC |
| CAD | **KiCad** (8.x) | project in `hardware/` of this repo; ERC/DRC and fabrication outputs (Gerber, BOM, CPL) generated in a KiCad container |
| fab | **JLCPCB, assembled** | parts chosen from the JLCPCB/LCSC library where possible (basic parts preferred); OCXO, LEA-M8T and connectors hand-soldered |
| defaults (change if you like) | 4 layers, ~100 x 80 mm, fits a standard aluminium extrusion case; rods on 2-pin 5.08 mm screw terminals; gain stage footprints present, not populated (jumpered through) | |

## 6. Implementation plan (proposal)
1. Prototype the two new blocks on the NUCLEO with parts the user has:
   a. LEA-M8T: PPS -> TIM2 CH1 capture, UART -> USART (UBX TIM-TP qErr): "GPS" lines, e-CzasPL
      frame and DCF77 second offsets against UTC (calibrates the ~18 ms / +3 ms / ~6 ms questions).
   b. OSC5A2B02: 5 V HCMOS -> divider/buffer -> HSE (X3 is empty) ; EFC from the H7's 12-bit DAC
      (PA4) for a first loop test (coarse, fine for proving the loop).
2. KiCad schematic in hardware/, block by block (power, MCU+clock, AFE x2, GPS, OCXO+DAC,
   Ethernet, USB/outputs), each reviewed by the user; LCSC part numbers checked for JLCPCB.
3. Layout (analog corner + shield, OCXO corner, RF edge), DRC, JLCPCB assembly order.
4. Bring-up plan with test points; firmware port (OCXO time base, GPS, steering loop).
