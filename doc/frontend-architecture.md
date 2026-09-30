# Receiver front end: antenna head + cable + main board

Design direction after the NUCLEO tests (30 Sep 2026). Rods: `rod-antenna-spec.md`; stations and rod
layout: `three-station-design.md`.
Drawing (top view to scale + signal chain): `antenna_head.pdf` (source `antenna_head.py`).

Why a separate antenna head: a ferrite rod is a magnetic-field antenna and picks up the currents on its
own board - switch-mode regulators (100 kHz - 2 MHz), the OCXO heater (250-600 mA with regulation ripple),
USB and the STM32's current pulses (incl. the 1 MS/s ADC rhythm). Measured: the NUCLEO's DCF77 rod shows a
local-noise hump and loses DCF77 at night while the IC-7610's K9AY at the same site keeps 27-33 dB-Hz. The
field of a small current loop falls with the cube of the distance: every doubling of the distance gains
~18 dB. So the rods go into a head, metres away from the electronics.

## 1. Architecture

```
ANTENNA HEAD (plastic box, attic / roof / window)                   MAIN BOARD (STM32, OCXO, GPS rx, USB)
 per station: rod L1 + C + R (Q ~ 30) at the rod                     per line: differential receiver
   -> low-noise amplifier, 20-26 dB, high input impedance              -> anti-alias low-pass ~400 kHz
   -> band limit (low-pass ~300-400 kHz)                               -> ADC input (1.65 V bias, 16 bit)
   -> differential line driver                                         clean linear supply for the head
 LDO supply (no switching regulator in the head)                       ESD/TVS at the cable entry
 ESD/TVS at the cable entry
 GPS: a separate active antenna with its own coax (section 4)
            ============ CAT5e/CAT6, twisted pairs, up to tens of metres ============
```

Gain sits in the head, so the signal on the cable is far above what the cable picks up; the main board
only filters, biases and samples.

Why an amplifier: measured on the NUCLEO, the antenna noise of a rod connected directly (high-impedance
tank) is ~15 dB above the ADC noise floor (~0.16 uV/sqrt(Hz), 16 bit). That margin is needed to be
limited by what the antenna picks up rather than by the ADC. Through the rod's 7-turn link winding
(turns ratio ~8, -18 dB) the antenna noise would fall below the ADC floor, and a cable longer than a few
tens of cm in parallel with the tank detunes it (most likely what detuned the current DCF77 rod) - so:
amplifier at the rod, cable after the amplifier.

Amplifier per rod (guideline, parts to be chosen):
- input directly on the tuned circuit (high impedance, e.g. non-inverting op-amp stage biased to mid-rail
  through a resistor that is part of the Q-setting R), or on the 7-turn link winding with more gain;
- low noise: input voltage noise well below the rod's ~0.1-1 uV/sqrt(Hz) - any op-amp <= 10 nV/sqrt(Hz);
- gain 20-26 dB (x10-20); gain-bandwidth >= 50 MHz for x20 at 225 kHz, or two stages;
- output: a fully differential amplifier / differential line driver onto the twisted pair;
- the head's supply: +5 V from the main board over one pair, LDO in the head.

## 2. Cable: CAT5e / CAT6 (preferred) or coax

CAT6, 4 twisted pairs, differential: rejects the interference picked up along the cable (common mode);
cheap; the STM32's ADCs also take differential inputs.

| pair | variant A: three lines | variant B: one line (see 3) (+ GPS in the head, 4b) |
|---|---|---|
| 1 | DCF77 77.5 kHz | the three stations summed |
| 2 | TDF 162 kHz | GPS PPS (RS-422) |
| 3 | e-CzasPL 225 kHz | GPS UART TX (RS-422) |
| 4 | +5 V / GND | +5 V / GND |

Coax alternative: one coax per station (single-ended, 50 Ohm drivers) plus power (separate wire or a
bias-T; at LF the bias-T chokes are bulky), a common-mode choke (coax through a toroid) per line at the
main board.

## 3. Option: one line for all three stations

Sum the three amplified rod outputs in the head onto one line / one ADC input. The stations are far apart
(77.5 / 162 / 225 kHz), each rod's tuned circuit already suppresses the other bands, and the firmware's
phase-locked digital mixers separate the stations as they do now. Then one 16-bit ADC does everything
(the cheap STM32H730, see the MCU notes) and two cable pairs are free (GPS PPS + UART, variant B).
Cost: less flexibility (no per-station gain at the main board; one overloaded station affects all).
Test first on the NUCLEO: two rods summed into A0.

## 4. GPS

Chosen (30 Sep): (a) - a separate active GPS antenna with sky view on its own coax to the GPS receiver on
the main board; the head then needs no sky view and no 15 cm keep-out, and fits a small box (section 6).
The options considered:


GPS L1 (1575 MHz) and the rods (77-225 kHz) do not interfere, so a GPS antenna can share the head, with:
- distance >= 15 cm from every rod: "mouse" antennas contain a magnet (shifts the ferrite's permeability)
  and a metal ground plate (a shorted turn near a rod: lower sensitivity and Q) - or use an antenna
  without a magnet;
- sky view: the head then goes to the roof or a window (which suits "far from home electronics").

Two ways:
- (a) GPS antenna in the head, its own coax (RG174/RG58) to the GPS receiver on the main board; the CAT6
  stays as in variant A;
- (b) GPS receiver module (e.g. LEA-M8T) in the head, PPS and UART over CAT6 pairs as RS-422 (variant B,
  needs the one-line option); the module in a small shielded box, >= 15 cm from the rods. Cable delay of
  the PPS: ~5 ns per metre, constant, negligible against the us-level calibration.

The GPS is needed for calibration (OCXO vs GPS, each station's second vs GPS); a permanent GPS makes it
continuous. Variant (a) keeps the GPS receiver's digital noise on the main board.

## 5. Main board

- per line: differential receiver / ADC driver, anti-alias low-pass (~400 kHz at 1 MS/s), bias 1.65 V;
- STM32 (H730 with one line, H743 with three 16-bit lines), OCXO, GPS receiver (variant a), USB;
- a clean linear +5 V for the head; ESD/TVS at the cable entry.

## 6. Head layout and box

Drawing to scale: `antenna_head.pdf`. Box: **Hammond 1554VAL2GY**, polycarbonate, IP68, UV-stable, 240 x 160
x 60 mm outside, ~232 x 152 x 53 mm inside (distributor listing; check the Hammond drawing; lid-screw bosses
in the corners). Rods 10 x 100 mm (`rod-antenna-spec.md`).

- Rods at 90 deg: DCF77 + TDF parallel along the long side, ~45 mm apart; e-CzasPL crosswise below them.
  Box long side to ~182 deg (~north-south): off broadside DCF77 11 deg, TDF 18 deg, e-CzasPL 18 deg - at
  most -0.45 dB. (Exactly broadside would need ~60 deg between the rods; the 90 deg layout fits the box.)
- The head board lies under the rods; the rods on plastic standoffs / clips 15-20 mm above it. No copper
  under the rods except narrow traces; ground plane only in the amplifier strip and the supply corner; no
  closed copper loops (a shorted turn near a rod lowers its sensitivity and Q).
- Amplifier + C + R per rod next to the rod; LDO, TVS and the CAT6 gland in one corner.
- Tune in place with all three rods mounted and the lid on.
- 150 mm rods: the same layout in a 1554X2GY (300 x 200 x 90 mm).
- Round boxes: no off-the-shelf round IP66/67 box of ~200 mm diameter found (round junction boxes are
  smaller; antenna radomes are larger). A DIY option: PVC/KG pipe 200 mm with two end caps; a round box
  also wastes space around three straight rods.

## 7. Prototype test (before any PCB)

When the rods arrive: a head on perfboard (3 rods, 3 op-amp stages, LDO, CAT6) connected to A0/A1 of the
NUCLEO. The `SPECTRUM` lines (noise floor per band, every 10 min) show directly:
1. each rod's resonance (the hump) at its station's frequency;
2. the antenna noise above the ADC floor (the margin);
3. the noise floor with the head at 0.1 / 1 / 5 m from the NUCLEO + OCXO (how far is far enough);
   each rod's resonance and Q with and without the board / the neighbouring rods (layout of section 6);
4. the one-line option: two rods summed into A0, each station's C/N0 against separate lines.
