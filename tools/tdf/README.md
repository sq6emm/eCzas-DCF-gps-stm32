# TDF / ALS162 (Allouis, France, 162 kHz): offline decoder on IC-7610 recordings

Third LF time station for the receiver project (besides e-CzasPL 225 kHz and DCF77 77.5 kHz).
IC-7610 SUB at 163.000 kHz USB; its LAN IF is mirrored, so TDF sits at ~13000 Hz, channel 1 of
the stereo files (`tools/icomlan`). Received at 48 dB-Hz with the K9AY (28 Sep 2026, 22:20 UTC),
20 dB above DCF77 on the same antenna.

Signal as measured: +-0.8 rad phase modulation. Per second a quiet 100 ms, then one ~100 ms phase
cycle (bit 0) or two (bit 1), no burst in the minute-marker second; the rest of the second carries
a denser pseudo-random phase modulation (not used yet). Time code: DCF77 layout (bits 17/18
CEST/CET, 20 start, 21-58 BCD minute/hour/day/weekday/month/year with three even parities),
giving the NEXT minute in French legal time.

| file | what |
|---|---|
| `tdf_decode.py` | first version: phase unwrapped, bit = phase activity in 100-200 ms. Fine at full strength, fails with noise (unwrap slips) |
| `tdf_decode3.py` | per-second complex least-squares fit u = g exp(jT) with learned shapes (bit 0 / bit 1 / none), second start by a matched filter with the learned burst, minute marker folded over all minutes, parity repair + BCD range checks, confirmation by a neighbouring minute; `--cn0` adds calibrated noise |
| `sub_schedule.sh` | IC-7610 SUB test schedule (TDF / MSF / RBU / back to DCF77) |

Python bench, 28 Sep 22:40-22:50 (learn on 22:34-22:40, test on the next file, noise added):
confirmed minutes of 9: 9 (49 dB-Hz), 8 (25), 8 (22), 4 (20), 0 (<= 18); WRONG confirmed 0 at every level.
CORRECTION (29 Sep): the Python bench added real noise with half the intended power, so its C/N0
labels are ~3 dB optimistic (its '20 dB-Hz' is really ~23 dB-Hz). The C bench below adds complex noise
correctly.

## C decoder (firmware/common/tdf.c, host/tdfsim.c, tools/tdfbench.py)

The same method as streaming C for the NUCLEO (behind a 162 kHz mixer and the carrier tracker, like
DCF77): fixed shapes (tdf_shape.h, learned on 22:34-22:40), second start by a folded matched filter,
per-second complex fit, minute marker folded over minutes, parity repair, BCD/range/date checks,
confirmation by the next minute, and confirmation by the expected frame (score >= 30 and >= 15 ahead of
the frames +-1/+-2 min). Without a confirmed reference, an unconfirmed decode without parity repair can
become one only if the next minute agrees with its prediction on nearly all confident bits (>= 0.8 of
sum |LLR|) - a looser test let wrong hours/dates through at 20-22 dB-Hz.
Input: tools/tdf/tdf_c64.py makes 2 kHz complex files from the IC-7610 recordings.

Bench, 22:40-23:26 (46 min), complex noise, 3 seeds per level:

| C/N0 | confirmed (standalone + expected frame) | WRONG confirmed |
|---|---|---|
| 49 (clean) | 42 + 0 of 43 | 0 |
| 30 dB-Hz | 98 % | 0 |
| 25 dB-Hz | 96 % | 0 |
| 22 dB-Hz | 46 % | 0 |
| <= 20 dB-Hz | 0 % | 0 |


### On real signal: IC-7610, 30 Sep 2026 19:10-21:00 UTC (no noise added)

IC-7610 SUB on 163.000 USB (TDF at IF 13 kHz, K9AY NW+LNA), MAIN stayed on e-CzasPL; TDF at ~66 dB-Hz
by night (by day at 10:54 UTC the same setup gave no TDF carrier at all: ground wave only, 1162 km).
11 ten-minute files converted with `tdf_c64.py` to `/data/claude/tdfbench/tdf_ic7610_20260930_1910.c64`
(6600 s), run through `tdfsim` (coh.c + tdf.c, the chain a NUCLEO 162 kHz mixer would feed); truth = the
recorder's file clock (NTP):

| minutes evaluated | confirmed | decoded, unconfirmed | failed | WRONG | parity repairs |
|---|---|---|---|---|---|
| 107 | 106 | 1 (the first, 21:14 CEST) | 0 | 0 | 0 |

First decoded minute ~4 min after the start (second start + minute marker have to be found first).
The second-start estimate moved 3 -> 7 -> 11 ms over the 2 h: the recording's clock (~48000.1 samples/s
against the nominal 48000, ~1 ms per 10-min file), not TDF. At this level the test proves the decoder on
real ALS162 transmissions, not its weak-signal margin: for that see the noise bench above (0 % below
~20 dB-Hz); TDF on the existing NUCLEO rods was only 7-11 dB-Hz, so a 162 kHz rod is needed.

## Second timing: TDF vs DCF77 vs e-CzasPL on one radio (30 Sep 2026, `tools/tdf_vs_eczas_timing.py`)

Both IC-7610 receivers in the same stereo file (one sample clock). Seconds found by model fits on the raw
carrier phase: TDF = zero crossing of the first triangular element (the ALS162 definition of the UTC
second, 50 ms after the element start; per-second scatter 70-90 us); DCF77 = phase-code start - 200 ms
(quadrature against a 1-s carrier reference; 115-160 us by day); e-CzasPL = frame start from the ideal
frame of the decoded N (0.2 ms per frame). Radio MAIN - SUB delay with both on 226.000 for 10 min:
0.00 +- 0.05 ms (IF and envelope cross-correlation, frame fits).

| arrival at Wroclaw | result | when |
|---|---|---|
| e-CzasPL - DCF77 | +16.61 ms (steady files +-0.1) | 16:00-17:30 UTC, day |
| e-CzasPL - TDF | +16.48 ms (11 files, spread 0.13) | 19:10-21:00 UTC, night |
| TDF - DCF77 direct (MAIN DCF77, SUB TDF) | -0.10 / -3.05 ms | 22:17-22:28 UTC, night: DCF77 unsteady |
| TDF - DCF77 from the two above | +0.14 ms | |

At night the DCF77 timing on this radio moves by several ms (evening files +12.4 ... +20.7 against
+16.6 by day, sky wave); TDF at night and DCF77 by day are steady.

At the transmitters (CORRECTED 1 Oct; the first version subtracted the path difference instead of
adding it): a station further away must have sent earlier, so emission difference = arrival difference
+ (its path delay - e-CzasPL's). Ground-wave delays: DCF77 580 km 1.93 ms, TDF 1162 km 3.87 ms, e-CzasPL
234 km 0.78 ms. e-CzasPL's fitted second leaves **~17.8 ms after DCF77's** (16.61 + 1.15) and **~19.6 ms
after TDF's** (16.48 + 3.09); TDF - DCF77 at the transmitters -1.8 ms, which is within what the TDF
second definition (zero crossing, from secondary sources only) and the night path allow. The NUCLEO
(after the +7.4 ms fix, 75340d9) prints the same quantity: "at the transmitters -17.4 ms".

### Why ~17 ms? (1 Oct 2026)

> **CORRECTION 1 Oct 2026, ~12:40 (GPS PPS, NEO-7P):** all DCF77 phase-code times above (IC-7610 and
> NUCLEO) were **1.548 ms late**: our PRN generator missed PTB's chip 0 (sequence 00000100011...,
> fixed in 16fd3b4). Corrected: e-CzasPL - DCF77 at the receiver **+18.15 ms** (16.61 + 1.55), at the
> transmitters **~19.3 ms**; e-CzasPL - TDF unchanged (+16.48 receiver, ~19.6 ms at the transmitters);
> TDF - DCF77 at the transmitters **~-0.3 ms** (not -1.8). GPS directly: the NUCLEO's e-CzasPL second
> arrives 25.18 - 5.00 (PPS anchor bug, a03170e) = ~20.2 ms after UTC -> ~19.4 ms late at the
> transmitter. **e-CzasPL is ~19.3-19.6 ms late.**
>
> **Strength of the evidence (independent review, 1 Oct):**
> - Sequence: the new one is bit-identical to Wikipedia's Galois code; Hetzel 1988 (PTB, the original
>   description) has the generator start from the all-zero state and visit all 512 states once, which
>   matches the new sequence, but prints no bits - strong, not formal proof. Best direct evidence: on
>   the NUCLEO the AM second mark (-7.265 ms vs GPS) and the corrected phase code (-7.15 ms) now agree;
>   with the old sequence the phase code came 1.45 ms after the AM mark (physically odd).
> - NOT evidence (stated wrongly in commit 16fd3b4): the "256 ones / 256 zeros" balance - the old
>   sequence was balanced too; and the IC-7610 rerun +16.50 -> +18.05 ms, which is the same template
>   shift on the same data (circular).
> - TDF - DCF77 -1.8 -> -0.3 ms: real but weak support (IC-7610 MAIN/SUB path delays at 78.5/163 kHz
>   uncalibrated, TDF antenna delay unknown, the -1.8 ms was known before the fix).
> - Still unexplained: ~0.27 ms (DCF77 vs GPS -2.20 ms after both fixes vs -1.93 expected); not the
>   receiver's sample timing (simulated: no half-sample bias); candidates: DCF77 antenna bandwidth,
>   ground-wave delay beyond the straight-line value, peak-interpolation bias. To settle: a GPS-locked
>   synthetic DCF77 signal into the antenna input (receiver delay end to end), and the sequence in
>   writing (PTB-Mitteilungen 114 (2004), Meinberg PZF docs, or PTB).
> The ramp-start convention below (~9 ms earlier) and the drift (~0.1 ms/day) still apply.

- **Not a time scale.** TAI/GPS/UTC differ by whole seconds. UT1 - UTC is -19.3 ms (28 Sep) ... -21.6 ms
  (30 Sep) (IERS Bulletin A), close in size, but it moves ~1.1 ms/day; e-CzasPL - DCF77 moved ~0.1 ms/day
  (below), so e-CzasPL does not follow UT1.
- **Part of it is the modulation shape** (`tools/eczas_transition_shape.py`, 30 Sep 16:00-17:20, 2550
  isolated bit changes): every bit change is a linear phase ramp of ~18 ms, from -9 to +9 ms around the
  edge the ideal-NRZ fit finds, i.e. the fit (and all numbers above) mark the ramp's middle. The frame's
  1010... preamble leaves the idle phase 9.3 ms before the fitted start. If "the beginning of the second"
  is where the first ramp starts (a causal ramp starting at the bit clock), e-CzasPL is late by
  16.6 - 9.3 = 7.3 ms at Wroclaw, **~8.5 ms at the transmitter**; if the ramp is meant to be centred on
  the bit clock, ~17.8 ms. Either way at least ~8 ms remain.
- **It drifts.** e-CzasPL's second moves later against DCF77 by **~0.1 ms/day**: NUCLEO tracker
  28 Sep 14:00 - 30 Sep 22:30, -0.117 +- 0.010 ms/day (313 10-min values, 2.35 days); IC-7610
  +16.50 ms (29 Sep 12-15, 18 files, spread 0.07) -> +16.61 ms (30 Sep 16-17:30), +0.10 ms/day. Same
  sign and size as e-CzasPL's carrier being ~0.85 ppb low against DCF77 (0.073 ms/day if the seconds were
  counted on the carrier's oscillator; measured ~1.4 ppb equivalent). A transmitter whose seconds were
  disciplined to UTC (GNSS) would not drift at all; a clock that is only set now and then would - at
  0.1 ms/day, 17 ms accumulate in ~5-6 months. Earlier outside reports of 10-25 ms late (PA3FWM) fit a
  value that changes.
- So most likely: the frame timing comes from a clock that is not continuously steered to UTC at the
  ms level (free-running or rarely corrected), plus the ramp convention and an uncompensated chain delay.
  GUM's own stated accuracy is "kilku lub kilkunastu milisekund" (a few to over a dozen ms), so ~17 ms is
  at the limit of what they promise. Watching the drift for weeks (and any step) tells which: a slow
  steady drift = free running; a sudden step = a correction.
