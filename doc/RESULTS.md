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
