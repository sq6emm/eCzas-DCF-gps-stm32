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

All of this comes through a ferrite rod tuned to 217 kHz, i.e. DCF77 is 20–30 dB below
what a tuned antenna would give.
