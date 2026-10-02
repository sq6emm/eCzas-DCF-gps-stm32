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

## Second timing: e-CzasPL vs DCF77, TDF and GPS (status 2 Oct 2026: three reviews, GPS-locked OCXO, GUM's statement)

**Definitions used.** DCF77: the second = start of the carrier reduction (PTB); the phase code starts
0.2 s later (sequence 00000100011..., chip 0 = 0). TDF: zero crossing of the first triangular element,
50 ms after its start (secondary sources). **e-CzasPL: the second = START of the first linear phase ramp**
of the frame, i.e. the start of bit 0 of the 16-bit synchronisation 0x55 0x55 (GUM: "transmisja rozpoczyna
się od początku sekundy"; **GUM to the author, 2 Oct 2026: the moment a receiver loads the time is the
beginning of the frame transmission = the start of the 16-bit sync, not the 1-0-1 marker**). The '0' of the
1-0-1 bits (bit 25) starts exactly 0.5 s later (measured 500.04 ms). The PSK is one-sided (idle carrier = one
level, the other -36 deg) and every bit change is a **linear ramp of ~19 ms**: 18.6 ms fitted on the
IC-7610 (60 frames), 19 ms according to GUM (stated to J. Sadowski, see below; not in the
specification).

Distances from the receiver's GPS fix (Wroclaw), ground wave at c: DCF77 Mainflingen 573.2 km 1.912 ms,
TDF Allouis 1156.1 km 3.856 ms, e-CzasPL Solec Kujawski 229.3 km 0.765 ms.

**IC-7610, both receivers in one stereo file** (`tools/tdf_vs_eczas_timing.py`, bias-free models of
`tools/timing_models.py` with the 18.6 ms ramp; 30 Sep recordings; MAIN - SUB delay 0.00 +- 0.05 ms):

| arrival at Wroclaw | result | files |
|---|---|---|
| e-CzasPL - DCF77 | **+8.86 ms** | 30 Sep 16:00-17:20 (9 files, 8 good) |
| e-CzasPL - TDF | **+7.24 ms** | 30 Sep 19:10-21:00, 11 files, spread 0.10 |
| TDF - DCF77 from the two above | +1.61 ms | |

At the transmitters (a station further away must have sent earlier): **e-CzasPL 10.00 ms after DCF77,
10.33 ms after TDF**; TDF - DCF77 = -0.33 ms.

**GPS PPS on the NUCLEO** (u-blox NEO-7P, cable delay 25 ns; 1 Oct afternoon, firmware 6bd5276):
DCF77 second -2.09 ... -2.18 ms (physics -1.912: **0.18-0.27 ms receiver/path residual**, likely the DCF77
rod's group delay - open). e-CzasPL -12.65 ms as reported by 6bd5276, whose second is 1.38 ms after the
true ramp start (16 ms ramp model in the eCzas core; corrected by -1380 us in c4613a2, not yet flashed)
-> ramp start 11.27 ms after UTC -> **10.51 ms late at the transmitter**.

**Result (1 Oct): e-CzasPL's second (ramp start) left the transmitter ~10.0-10.5 ms after UTC** (DCF77 10.00,
TDF 10.33, GPS 10.51; the spread is the receivers' uncalibrated per-frequency delays). GUM's web page
states "<0,01 s" end-receiver synchronisation accuracy. With the ramp-middle convention add ~9.3 ms.

**GPS-locked OCXO, night 1-2 Oct** (NUCLEO b6119ed, OCXO phase-locked to the NEO-7P PPS; 1 Oct 20:10 -
2 Oct 08:04, one boot): e-CzasPL second **10.60 ms late** at the transmitter (median of 40117 PPS seconds,
10-min medians 10.43-10.71, no step > 0.21 ms), drifting **+0.093 +- 0.048 ms/day** later. TDF (IC-7610 SUB
22:20-04:50, 40 files, transferred to GPS through the NUCLEO's e-CzasPL): TDF second **+0.156 ms** after UTC
(sd 0.129 per file - the files are not independent; night sky wave ~+0.07 ms not removed; contains the
NUCLEO's 225 kHz path delay). DCF77 (NUCLEO rod): +0.29..+0.34 ms in that boot, day and night alike.
Review 3 (2 Oct) showed the DCF77 residual stepping at REBOOTS (+0.21 / +0.25 / +0.29 ms), not at dusk: the
parabolic sub-sample peak of the phase-code correlation was biased -42..+30 us by the sample-grid position,
and the first phase-locked block put ~32 us on all station timings. Both fixed in 345584c (flashed 2 Oct
08:04): DCF77 then +0.19 ms, e-CzasPL ~10.6 ms (unchanged within its 10-min spread). Whether DCF77 is now
boot-independent needs a few more boots.

**Independent work:** J. Sadowski, "Receiver network for assessing the accuracy of time distribution in
e-Czas Radio service", Metrol. Meas. Syst. 32(4), 2025, DOI 10.24425/mms.2025.155800 (Gdansk University
of Technology). GNSS-disciplined direct-sampling receivers; same reading of the 1-0-1 reference and the
same ramp-start convention; GUM gave the author the 19 ms ramp; arrival-time jitter 18 us at 150 km.
It deliberately publishes no absolute offset against UTC ("emission parameters are changed within small
limits by the system operator") - the ~10 ms above is, as far as we know, the first such measurement.

History (superseded; kept so old notes can be read):
- 1 Oct afternoon: ~11.0-11.9 ms (ramp start) with a 16.6 ms ramp model - ~0.8-1.0 ms late (the ramp is ~19 ms).
- 30 Sep: +16.61 / +16.48 ms (e-CzasPL - DCF77 / - TDF at the receiver) - a step-model fit that marked the
  ramp MIDDLE with a ~-0.2 ms bias, and (DCF77 only) a phase-code sequence missing chip 0 (1.548 ms).
- "~17.8 ms" and "~19.3-19.6 ms late" (30 Sep / 1 Oct): ramp middle, built on those errors.
- The NUCLEO's ECZ_TEMPLATE_LAG_US 7400 (75340d9) was explained as a receiver delay ("tracker switches in
  ~5 ms") - wrong: it moved the reported second from the ramp start to ~0.5 ms before the ramp middle.
  Set to 0 (ramp start) in 6bd5276. The GPS anchor bug (5 ms, a03170e) affected only the PPS lines.
- Reviews: (1) the PRN and anchor fixes - correct; Hetzel 1988 supports the new sequence; the "256/256"
  balance and the IC-7610 rerun +16.50 -> +18.05 were NOT evidence (commit 16fd3b4 overstated them).
  (2) the timing chain - DCF77 chain right (AM onset and phase code agree within 0.05 ms), the fixes of
  6bd5276, and the definitions above.

### Why is e-CzasPL ~10 ms late? (answered by GUM, 2 Oct 2026)

- **GUM to the author, 2 Oct 2026: today the 225 kHz carrier AND the start of the frame are both taken
  from an OCXO (temporarily); it will soon be replaced by a rubidium source.** So the carrier offset and
  the lateness of the second are one effect: a free-running clock.
- **The numbers agree on the rate.** Carrier against GPS -0.82 ppb (NUCLEO REFS, and review 3 from the raw
  dumps before the trackers: -0.81 ppb; e-CzasPL - DCF77 -0.825 ppb needs neither OCXO nor GPS) -> each
  second 0.82 ns too long -> **+0.071 ms/day** later. Measured: +0.093 +- 0.048 ms/day (GPS, night 1-2 Oct),
  ~+0.10..+0.12 ms/day (vs DCF77, 28 Sep - 1 Oct; those include the DCF77 boot steps found in review 3).
- **The total (~10.5 ms) is the drift since the clock was last set**: at 0.071 ms/day about 150 days
  (around early May 2026) if it was set exactly and the OCXO's frequency stayed constant - unknown; an
  OCXO ages. It is not a time scale (TAI/GPS/UTC differ by whole seconds; UT1 - UTC moves ~1.1 ms/day) and
  not a definition offset. Expected, if nothing changes: ~+0.5 ms per week (~11.1 ms around 9 Oct).
- **Watch for the rubidium switch-over**: the e-CzasPL carrier offset going from -0.8 ppb to ~0, and the
  second's drift stopping (or a step if the clock is reset). Outside reports of 10-25 ms late (PA3FWM) fit
  a value that changes.
- Open: when the frame timing was last set / whether it is steered (question for GUM); the remaining
  DCF77 residual (~+0.19 ms after 345584c: rod group delay?); per-frequency receiver delays (a GPS-locked
  synthetic test signal at the antenna input would measure them end to end).
