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

The 512-chip phase code (±15.6°) should correlate at only ~3.6σ with 23 min, so it
needs about 2 h of data.
