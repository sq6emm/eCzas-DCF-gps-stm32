# e-CzasPL + DCF77 + TDF + GPS + OCXO: three-station receiver design (draft, 29 Sep 2026)

Status: proposal after the 28 Sep night tests. Nothing here is built yet. Numbers marked *estimate*
are not measured.

## 1. The three stations seen from Wrocław

| station | frequency | transmitter | distance | bearing | ground-wave delay | time code | measured here |
|---|---|---|---|---|---|---|---|
| e-CzasPL | 225 kHz | Solec Kujawski | 234 km | 20° | 0.78 ms | 3-s frames (PM) | NUCLEO rod 44-47 dB-Hz, IC-7610 55 |
| DCF77 | 77.5 kHz | Mainflingen | 580 km | 261° | 1.93 ms | AM + phase code, 1 min | NUCLEO rod 13-21 dB-Hz (night-day), IC-7610 28 |
| TDF (ALS162) | 162 kHz | Allouis | 1162 km | 254° | 3.88 ms | PM bursts, DCF77 layout, 1 min | IC-7610 48 dB-Hz; NUCLEO: A0 rod 7-11, A1 rod none (no 162 kHz rod yet) |

Rejected after the tests: MSF 60 kHz (1418 km, 295°: keying visible, 13.6-15.7 dB-Hz at night, time
code not decodable), RBU 66.67 kHz (carrier only, 14 dB-Hz).

## 2. Three ferrite rods: a triangle?

A rod receives the horizontal magnetic field of the ground wave: maximum broadside (the station
perpendicular to the rod axis), a null along the axis, the pattern is cos(angle) (a figure 8).

| rod | station bearing | best rod axis | loss if the rod is 30° / 60° off |
|---|---|---|---|
| 225 kHz | 20° | 110° / 290° | -1.2 dB / -6 dB |
| 77.5 kHz | 261° | 171° / 351° | -1.2 dB / -6 dB |
| 162 kHz | 254° | 164° / 344° | -1.2 dB / -6 dB |

**The geometry decides the layout, not symmetry.** DCF77 and TDF both come from the west (7° apart),
so their rods should be nearly parallel (both ~N-S, axis ~168°); the e-CzasPL rod at ~110° is ~60°
from them. An equilateral triangle (rods 60° apart) would put one of the two western rods 60° off
its station: -6 dB. So: **a "V" / "L" layout, not a triangle** (drawing: `three_rods_layout.pdf`).

Coupling between the rods (they are tuned to 77.5 / 162 / 225 kHz, ratios 1.39 and 2.1):
- Off its own resonance a tuned rod is a low impedance (below resonance inductive, above
  capacitive): a nearby rod then behaves like a loaded loop - it can detune a neighbour and take a
  little of its field. The effect falls with the mutual coupling k (roughly with distance cubed).
- **Parallel rods (DCF77 + TDF)**: the strongest coupling. Keep them >= 2 rod lengths apart side by
  side (~25-30 cm for 12 cm rods), or on one line end to end with a gap >= 1 rod length.
- **The e-CzasPL rod at ~60°** couples about half as much as a parallel one would (cos 60°); 20-30 cm
  from the others is enough.
- Retune every rod with the others in place (the probe build below measures each one in minutes).
- Coaxial feed and the tuning capacitors near the board, as in `nucleo_225_77kHz_input.pdf`.

Tuning capacitors (C = 1 / (4 pi^2 f^2 L)):

| rod | L | f | C |
|---|---|---|---|
| ROD 1 (existing) | 360 µH | 225 kHz | 1.39 nF (1.5 nF used) |
| ROD 2 (existing) | 375 µH | 77.5 kHz | 11.2 nF (10 + 1.2 nF used) |
| ROD 3 (new) | ~360 µH (*estimate*, measure it) | 162 kHz | ~2.7 nF (e.g. 2.2 nF + 470 pF, trimmed) |

## 3. Inputs on the NUCLEO (and the future board)

The ADCs sample 0-500 kHz directly; one input can carry several stations. Options for TDF:
1. **A0: 225 kHz and 162 kHz tanks in series ("stacked tanks")**. Each rod keeps its own parallel
   capacitor; the two tanks are connected in series to A0 (bias/protection unchanged). At 225 kHz the
   162 kHz tank is above its resonance: ~0.55 kOhm (capacitive) against ~25 kOhm of the resonant
   225 kHz tank (Q ~50, *estimate*); at 162 kHz the 225 kHz tank is ~0.76 kOhm (inductive) against
   ~18 kOhm. Each station's voltage reaches the ADC with ~3-4 % loss. 16-bit ADC1, no change in the
   sampling. **Recommended.**
2. ADC3 (third, independent ADC, 12-bit) on a free pin: simplest wiring, but 12 bits - its noise
   floor against the (small) rod signals must be checked first.
3. One broadband active antenna for all stations (for comparison with the rods; spare ADC input).

Firmware for a third station (the sampling stays as it is):
- third phase-locked mixer (162 kHz) on the A0 samples + a third carrier tracker (coh.c, COH_PLAIN)
- the TDF decoder ported from `tools/tdf/tdf_decode3.py` (learned shapes -> fixed shapes in C,
  per-second complex fit, minute fold, parity/BCD checks, neighbour confirmation), host-tested on
  the IC-7610 recordings with the noise bench first (0 wrong confirmed, as for DCF77)
- CPU: today 20 % for two stations; a third mixer + tracker a few % more. The real limit is the
  30 ms sample ring: the per-block / per-minute evaluations of all three decoders must be spread
  over different samples (the 28 Sep 21:38 OVERRUN lesson).

## 4. What three independent radio sources give (and two do not)

1. **Majority instead of doubt.** With two stations a disagreement cannot be resolved; with three,
   the odd one out is identified. Examples from this week: e-CzasPL's early frames (-2.4 s) and its
   carrier ~1e-9 below DCF77 - a third station says which one is off.
2. **Independent time institutes.** DCF77 is steered by PTB (Germany). ALS162 is the French legal time
   signal (operated by TDF for ANFR, with the time reference from the French time laboratory
   LNE-SYRTE - *to be confirmed*). e-CzasPL is the Polish system (GUM, Polish Radio carrier).
   Three national chains checking each other.
3. **Diversity.** Different directions (N vs W), distances (234 / 580 / 1162 km) and frequencies:
   night-time sky-wave interference does not hit all three the same way. At our site DCF77 on the
   rod falls to 13-16 dB-Hz at night, TDF at 1162 km arrives at 48 dB-Hz (IC-7610).
4. **Better holdover / OCXO steering.** Three carriers, each with its learned offset, weighted by
   their noise; any one can drop out without holdover. Two PTB/SYRTE-traceable anchors (DCF77, TDF)
   fix the long term; e-CzasPL (strongest here) the short term.
5. **The GUM finding gets a second reference.** "e-CzasPL is ~1e-9 low against DCF77 AND against TDF"
   is a much stronger statement than against one foreign station.
6. **Time and (coarse) position.** Three seconds with known transmitter delays: timing cross-checks
   at the 0.1 ms level; with GPS calibration of the fixed offsets, a TDOA position fix (km level) as
   a by-product.

## 5. GPS and the OCXO

- **GPS (LEA-M8T) as calibration reference, not for daily use** (user decision): header + PPS to a
  timer input capture on the OCXO time base (~100 ns). Measures each station's second against UTC
  once (propagation + transmitter + decoder offsets) -> calibration constants; afterwards UTC from
  the radio stations alone.
- **OCXO as the MCU clock** (next hardware step on the NUCLEO): the 10 MHz CTI OSC5A2B02 into HSE
  bypass (OSC_IN, 3.3 V level) instead of the ST-LINK clock, so the ADC sampling is exactly locked to
  the OCXO and the software rate correction disappears. A 100 MHz OCXO brings no gain here.
- EFC: today the DAC (12-bit, dithered, 0.816 ppb per code measured); the board: 16-bit DAC +
  reference + divider (board-design.md).

## 6. Proposed order

1. Measure ROD 3's inductance, tune it to 162 kHz, try it alone on A1 with the TDF probe build
   (`-DF_DCF=162000`): C/N0 in ten minutes.
2. Stacked tanks on A0 (225 + 162), check e-CzasPL is unchanged and TDF's C/N0.
3. TDF decoder in C, bench on the IC-7610 TDF recordings (28 Sep 22:33-23:26), then third mixer +
   tracker on the NUCLEO.
4. Three-station OCXO steering (efc.c generalised to N stations).
5. GPS PPS capture for the one-off calibration; OCXO as MCU clock.
