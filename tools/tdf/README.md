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
+16.6 by day, sky wave); TDF at night and DCF77 by day are steady. With ground-wave delays (DCF77 580 km
1.93 ms, TDF 1162 km 3.87 ms, e-CzasPL 234 km 0.78 ms) e-CzasPL's second leaves ~15.5 ms after DCF77's and
~13.4 ms after TDF's; the ~2 ms between those two is within what the path assumptions (night sky wave for
TDF) and the conventions allow, but not below. NOTE: the NUCLEO reports e-CzasPL - DCF77 = +8.9 ms at the
board - 7.7 ms less than this; one of the NUCLEO's chains (ecz.c / eCzas core or dcf.c) has an
uncompensated delay; the GPS PPS test measures each against GPS separately.
