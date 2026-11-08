# Results

Measurements with the NUCLEO-H723ZG receiver (`firmware/nucleo-h723`), compared slot by slot
with an ICOM IC-705 (reference) and the eCzas board in Legnica (`tools/compare3.py`).

## e-CzasPL reception, first results (27 Sep 2026, Wrocław)

Ferrite rod with 1.5 nF on the Nucleo, and the IC-705 with a frame loop in the same
room as the reference. The Legnica eCzas board (site with strong local noise since
26 Sep) is also shown. 15:09–15:17:30 UTC, 169 slots, 47 of them time frames:

| receiver | decoded | confirmed | share of time frames | wrong/off-slot |
|---|---|---|---|---|
| IC-705 + frame loop (reference) | 47 | 0 | 100 % | 0 |
| **NUCLEO-H723ZG + ferrite** | 30 | 10 | **85 %** | 0 |
| eCzas board, Legnica | 1 | 7 | 17 % | 0 |

One miscorrected frame (year 2066) was rejected by the timekeeper. The frames that
were accepted agree with the Nucleo's clock to within ±0.7 ms.

Full hour 15:10–16:10 UTC (301 time frames): IC-705 99.7 %, Nucleo 84.7 %
(137 decoded + 118 confirmed), Legnica 16.6 %. No wrong times; 8 miscorrected
low-SNR frames (nonsense years) and one early frame were rejected by the timekeeper.
The early frame was the 16:19:15 frame sent in slot 16:19:12 (−2479 ms). The IC-705
saw it independently (−2472 ms).

## Image filter (A/B test, same day)

Taking the real part of the 1 kHz-shifted complex stream folds the noise of the image
side onto the signal. A ±400 Hz complex low-pass before that step (4th-order
Butterworth, 1.03 ms flat delay, subtracted from the frame timing) gave:

| | IC-705 time frames | Nucleo got | decoded / confirmed |
|---|---|---|---|
| without, 16:10–16:42 | 155 | 84.5 % | 83 / 48 |
| with, 16:45–17:27 | 110 | **92.7 %** | 89 / 13 |

The filter also lowered carrier noise from 9–13° to 7–8°. Build with
`-DNO_IMAGE_FILTER` to leave it out.

## DCF77 on the same antenna (experiment)

A second phase-locked mixer at 77.5 kHz runs next to eCzas (CPU 12 % -> 19 %) and, in
`AUDIO_DUMP` builds, streams 2 kHz complex baseband. `TIMEMAP` lines every 10 s tie
the sample count to eCzas time. The ferrite rod is tuned to 225 kHz, so DCF77 arrives
far below the noise and no ordinary DCF77 decoder could use it. But the Nucleo knows
UTC from eCzas and can predict the whole DCF77 amplitude pattern (second marks, CEST
time code, parity). Correlating coherently over many seconds gives
(`tools/dcf_assist.py`, 27 Sep 2026, 23 min):

- the carrier line where the LSE error (+0.9 ppm, measured against eCzas time) predicts it;
- the amplitude pattern at **−9 ms** against the Nucleo's eCzas second, **20.6×** the
  off-peak rms (DCF77 propagation from Mainflingen is about 1.9 ms; the Nucleo's eCzas
  delay is not calibrated);
- the predicted bits confirmed by the dip lengths.

### 2.5 hours (17:38–20:07 UTC, 8944 s)

| check | result |
|---|---|
| carrier | line 27 dB above the 1–20 Hz median, 0.005 Hz from the LSE-based prediction (+0.81 ppm) |
| amplitude pattern | **53.3×** the rms beyond ±250 ms, best lag **−11 ms**; triangle from about −175 to +150 ms |
| data bits | seconds predicted '0' vs '1' clearly separated in the 110–190 ms window |
| **phase code** | **15.4σ** (`tools/dcf_pm.py`); for 246 k noise-only values the largest is expected at 4.5–5σ |

Phase code details:

- Method: D = mean(quadrature | bit 0) − mean(quadrature | bit 1) over all seconds with
  a known bit. The code flips with the bit and doubles; anything locked to the second
  but independent of the bit (mains, AM leakage) cancels. Without this step, structured
  interference made all candidates score alike.
- Only the x⁹+x⁵+1 sequence matches, not its reverse. The best candidates lie on one
  line, lag ≈ (shift − 145) × 1.548 ms: shifting the m-sequence by one chip is the same
  as delaying by one chip. Without PTB's exact register start state the whole-chip
  offset stays open. The fine timing is sharp: −6.0 / −11.5 / **−15.4** / −12.2 / −6.2σ
  in 0.5 ms steps, i.e. −6.98 ms modulo 1.548 ms.
- The amplitude marks put the DCF77 second about 11 ms *before* the Nucleo's eCzas
  second. Propagation (DCF77 ~1.9 ms, e-CzasPL ~0.8 ms) cannot explain it; it is the
  uncalibrated receive delay of the Nucleo's e-CzasPL timescale (or of the DCF77 path).
  To be calibrated against GPS PPS (see PLAN.md).

### Exact sequence: whole-chip offset resolved

The sequence is defined in PTB-Mitteilungen 114 (2004), Heft 4, section 4.3
("Zeit- und Normalfrequenzverbreitung mit DCF77"):
- a 9-stage register with outputs 5 and 9 fed back through XOR;
- restarted from the zero state 0.2 s into every second, with a start flip-flop;
- one full cycle of 512 chips at 645.83 Hz;
- non-inverted sequence = 0, inverted = 1;
- **seconds 0–9 always inverted** (minute marker), seconds 10–14 carry no data (not
  inverted), from second 15 the same bits as the AM time code.

The generator (register from 0, a 1 shifted in first, chip = stage 5 XOR stage 9)
follows C. Vorberg, Diplomarbeit, Hochschule Mittweida (appendix 2). Its first chips
are `00001000110000100111001010101100`, with 256 ones.

With that sequence and those bits (4449 × 0, 4425 × 1), searching ±200 ms:

| | |
|---|---|
| peak | **−19.8σ**, unique (next best anywhere 3.4σ) |
| lag | **−8.515 ms**: the DCF77 phase-code second arrives 8.5 ms *before* the Nucleo's e-CzasPL second |
| around the peak (0.5 ms steps) | −2.3 / −8.4 / −15.8 / **−19.8** / −15.3 / −6.1 |

The propagation difference (DCF77 ~1.9 ms, e-CzasPL ~0.8 ms from Solec Kujawski) is only
~1.1 ms. The remaining ~9.6 ms is the Nucleo's uncalibrated e-CzasPL receive delay (or a
transmitter offset); a GPS PPS will separate the two.

All of this comes through a ferrite rod tuned to 217 kHz, i.e. DCF77 is 20–30 dB below
what a tuned antenna would give.

### Tracking per 10 minutes (from 27 Sep 2026 evening)

`tools/dcf_track.py` runs continuously. First 2.5 h (17:40–20:10 UTC): phase code 5–8σ per
10-min block, lag −8.19 … −8.89 ms; over 30 min 9–13σ, lag **−8.42 … −8.65 ms**. One block
(19:40) was too weak (2.5σ). The amplitude pattern is only 1–2σ per block; over 10 minutes
the phase code is the useful measure. The overnight run (sky wave on both paths) follows.

## Night 27/28 Sep 2026

### e-CzasPL reception, three receivers + QDX

Share of the time frames the IC-705 saw (`tools/compare3.py`, 2-hour windows). The IC-705
switched itself off on a flat battery at 00:15–00:36 and 01:05–04:51, so those windows have
little or no reference; the NUCLEO column is then its own count against ~290 frames/h.

| window (UTC) | IC-705 (frame loop) | NUCLEO (ferrite, M3) | Legnica (eCzas board) |
|---|---|---|---|
| 20–22 | 99.7 % | 92.4 % | 38.7 % |
| 22–00 | 99.8 % | 92.2 % (reflashes, the 10-min sample-skip bug) | 24.8 % |
| 00–02 | 99.5 % (partly off) | 96.9 % | 13.3 % |
| 02–04 | off | 295–310 frames/h | – |
| 04–05:47 | 100 % | **98.9 %** | 16.1 % |

- NUCLEO: 262–310 decoded+confirmed per hour all night, 0 time steps, 0 wrong times.
  Garbled low-SNR frames with nonsense dates were all rejected.
- Legnica: 0 wrong times; short carrier losses (≤100 s) at night and dawn.
- QDX472A + K9AY (224 kHz outside its band, 630 m filter): 34 runs, C/N0 3–36 dB-Hz, best
  22:52, never a decoded frame.

### DCF77 timing against the NUCLEO's e-CzasPL second (eCzas-assisted phase code, `dcf_track.py`)

| hour (UTC) | DCF77 carrier dB | 30-min lag, ms (σ) | eCzas frames/h | eCzas noise ° |
|---|---|---|---|---|
| 18 | 26.0 | −8.47 (8–11) | 272 | 7.8 |
| 19 | 27.4 | −8.52 (8–13) | 288 | 7.9 |
| 20 | 24.0 | −8.42 (8–10) | 270 | 7.7 |
| 21 | 23.0 | −8.12 (6) | 276 | 7.8 |
| 22 | 22.7 | −8.14 (6) | 275 | 7.9 |
| 23–03 | 15.5–18.6 | below 5σ | 262–304 | 8.4–10.1 |
| 04 | 24.2 | −8.89 (6–7) | 221 (reflash) | 9.5 |
| 05 | 18.5 | −8.99 (5) | 284 | 8.9 |

- **Dusk (~20:35):** the DCF77 carrier fell by ~3 dB and the site noise rose ~1.5 dB. The lag
  moved slightly, −8.5 → −8.1 ms.
- **23–03:** too weak for the phase code at the 5σ level.
- **Dawn:** back to −8.9…−9.0 ms. The difference of about 0.8 ms between evening and dawn is at
  the edge of what 5–8σ allows, but it points to a sky-wave contribution on one of the two paths.
- **e-CzasPL was unaffected by night:** frames per hour and loop noise stayed flat, so the moves
  come from the DCF77 path.

### Standalone DCF77 on the NUCLEO (no eCzas input)

- Locked on the real carrier 02:00–03:37 (second marks 12–15σ; minute found at 02:10).
- Its second lay −6.9…−10.7 ms from the eCzas second, consistent with the assisted result.
- The first night also showed three things to fix, all fixed and flashed that night:
  - the fold did not follow the crystal's drift (fixed 03:39);
  - the spur check restarted on every re-find (fixed 04:38, spur rejected at 05:48);
  - a 10-min evaluation skipped samples (fixed 23:50).
- Carrier: 38 one-minute values of eCzas−DCF77 give **−0.5 ± 3.1 ppb**. Both carriers were
  measured against the same LSE crystal, so its error cancels: the two transmitters agree within
  about 3 ppb.

## GPS-disciplined OCXO (from 1 Oct 2026)

Firmware 67714e4 (1 Oct 18:00 UTC) locked the OCXO to the NEO-7P PPS; b6119ed added the
plausibility gate; 345584c (2 Oct) fixed three issues found in an independent review
(GPS jump checked per pulse, unbiased DCF77 phase-code peak, true ADC rate in the first
block, implausible e-CzasPL decodes ignored); later commits (8 Oct) hardened the time
base, watchdog and DCF77 fade recovery.

- **Lock:** time error against GPS 16–31 ns rms in quiet periods. The gate never
  suspended the GPS on real data; in simulation it catches a spoofed 550 ns step at any
  second of the minute and a +20 ppb frequency spoof at once.
- **OCXO episode 1 Oct 20:13 – 2 Oct 03:20:** the free-running frequency stepped −3.5 ppb
  with abrupt ~1-min jumps (EFC code unchanged, all three references agreed), then
  returned; time error up to ~1.1 µs while the loop followed. Hardware (EFC / ground /
  supply contact), not firmware.

## Carriers against GPS (Oct–Nov 2026)

Per minute from the `REFS` lines (`tools/carriers_vs_gps.py`; carrier − GPS):

| | offset | notes |
|---|---|---|
| DCF77 | 0.00 ppb | ADEV 1 h ~0.2 ppb on the rod, noisier at night |
| e-CzasPL | −0.80 ppb | daily means −0.75 … −0.83 ppb, 2–21 Oct |

**Against GUM's own monitoring** (received carrier phase vs UTC(PL), every 20 s,
20.10–02.11, shared by GUM; unwrapped with x2 − x1 + n · 4.444 µs):

- GUM: −0.806 ppb (5-s data −0.804), daily −0.822 … −0.791; 4–5 Nov −0.782 ppb.
- Ours (GPS, Wrocław) agrees within a few 1e-11 on clean days; from the carrier phase
  within ~0.5e-11. Local interference (28–30 Oct, 5 Nov) biased our minute values;
  robust (clipped) daily means are needed.
- Allan deviation from GUM's data (whole path, incl. frame modulation and propagation):
  1.2e-8 @ 20 s, 8e-11 @ 1 h, 1.0e-11 @ 9 h, ~6e-12 @ 1 d.
- GUM: the carrier and the frame timing come from one free-running OCXO for now
  (spec ±2e-9), rubidium planned (Nov–Dec 2026, spec ±5e-11).

## e-CzasPL second against GPS

Second = start of the frame's first ~19 ms phase ramp = start of the 16-bit sync
(confirmed by GUM, 2 Oct 2026), ECZ_TEMPLATE_LAG_US −1380; propagation 229.3 km =
0.765 ms removed.

- 2 Oct: 10.6 ms late; growing **+0.074 ms/day** (the −0.80 ppb carrier predicts
  +0.070 ms/day: one OCXO drives both) to 12.1 ms on 21 Oct.
- 21 Oct 06:33:43 UTC: step −10.8 ms (GUM resynchronised via an NTP server) to 1.4 ms
  late; 2.3 ms on 2 Nov; a −0.17 ms change during our outage on 2/3 Nov (cause open);
  ~2.2 ms on 4 Nov. GUM declares ±10 ms vs UTC(PL).
- DCF77 second at its transmitter (573.2 km = 1.912 ms removed): +0.19 … +0.25 ms after
  345584c, rising after sunset; the residual (rod group delay, night propagation) is open.
- TDF (IC-7610, night 1–2 Oct, transferred to GPS through the NUCLEO's e-CzasPL):
  +0.16 ms, incl. ~0.07 ms of night sky wave.

## Early e-CzasPL time frames

The time frame belonging to slot S+3 was sometimes sent in slot S, 0.50–0.60 s after its
start (2.40–2.50 s early, in exact 20 ms steps), S+3 then empty. 97 events 25 Sep – 2 Oct
on five receivers; 88 confirmed in raw recordings with an independent decoder written
from GUM's frame description; ~1 in 400 time frames, Poisson in time, no dependence on
the hour, the minute or the preceding transmission. Report:
`tools/dashboard/static/early_frames.html`. GUM reduced the frame lead to the modulator
by 0.2 s on 4 Nov 2026 ~12:00 UTC; the last early frame was 4 Nov 10:06:30 UTC
(0 in the next ~6,170 frames where ~15 were expected).

## Local interference at the Wrocław site

5 Nov from ~08:40–08:50 UTC (and weaker, intermittent on 28–30 Oct): noise up to
+12–16 dB around 222, 225 and 231 kHz on the e-CzasPL rod (DCF77 band unaffected),
C/N0 45 → ~35 dB-Hz, decoding stopped from ~09:20. Weekday daytime; source not found yet.
