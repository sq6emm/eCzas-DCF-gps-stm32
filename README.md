# e-CzasPL receiver on a NUCLEO-H723ZG

A test port of the receiver: the 225 kHz signal is sampled directly by the STM32H723's
ADC, turned into the same 10 kHz "audio" (carrier at 1 kHz) that the SI4735 gives the
dsPIC, and fed to the **unchanged eCzas core** (`../src/core`: dsp.c, frame.c,
timekeeper.c). No radio chip, only an antenna tuned to ~225 kHz.

## Hardware

- NUCLEO-H723ZG, powered and flashed through its ST-LINK V3 (USB).
- Input on **A0 (PA3)**: see [`doc/nucleo_225kHz_input.pdf`](doc/nucleo_225kHz_input.pdf).
  Bias to 1.65 V with 10k/10k from 3V3, 100 nF coupling, antenna tuned to ~225 kHz.
  Tested: ferrite rod (12 cm, 360 µH) with 1.5 nF across it (resonance about 217 kHz),
  20 cm twisted pair to the board. An untuned antenna mostly brings in aliased
  medium-wave noise.
- LED LD1 shows carrier lock. Output is on the ST-LINK virtual COM port.

## Signal path

```
A0 -> ADC1 16 bit, 1 Msps (TIM6) -> DMA ring (8 x 5 ms)
   -> mixer at 225 kHz (phase-locked to the LSE crystal, see below)
   -> sum over exactly 100 us of true time -> 10 kHz complex
   -> complex low-pass +-400 Hz (no image noise) -> shift to +1 kHz, real part, AGC
   -> eCzas core (PLL, frame decoder, timekeeper)
```

An FFT search (8192 points at 1 kHz, ±450 Hz) finds the carrier at start and after
30 s without lock. An outer loop keeps the carrier at 1 kHz once a second, because
the core's own loop only follows ±40 Hz.

## Clock: why the LSE crystal matters

The board has no HSE crystal fitted. The ST-LINK's 8 MHz MCO turned out to be about
0.9 % fast and wandering ±700 ppm, so the CPU runs on the internal HSI instead. HSI is
about +6500 ppm and wanders about 100 ppm, which is still far too much for PSK at
225 kHz. The 32.768 kHz **LSE crystal (X2)** is the reference:

- TIM16 captures every 8th LSE edge (TI1 = LSE), i.e. true time in 1/4096 s steps,
  counted in 200 MHz timer ticks.
- Every ADC sample is exactly 200 of the same ticks, so the **true time of every sample**
  follows by interpolation between captures.
- The mixer **phase** is set to −2π·F·t_true at every 5 ms block, and the decimator
  sums exactly 100 µs of true time per output.

The first version only corrected the mixer frequency from the measured clock ratio.
The residual errors then added up as phase noise: about 25° rms in the data band
(5–80 Hz from the carrier), as large as the PSK deviation itself. Frames were "heard"
but never decoded (SNR −3 to −12 dB). With the phase-locked mixer, carrier noise
dropped from 13° to 8° and frames decode with SNR 0 to +4 dB. The same antenna,
setup and core were used in both cases.

## Build, flash, log

Libraries (put them in `lib/` or pass `LIB=`):

```
git clone https://github.com/ARM-software/CMSIS_5.git                    # tested at 55b1983
git clone https://github.com/STMicroelectronics/cmsis_device_h7.git      # 81db1ec
git clone https://github.com/STMicroelectronics/stm32h7xx_hal_driver.git # e3c518e
```

```
make LIB=/path/to/lib                          # text output, 115200 baud
make LIB=/path/to/lib CFLAGS_EXTRA=-DAUDIO_DUMP  # + raw 10 kHz core input, 921600 baud
st-flash --reset write build/rx.bin 0x08000000
```

Other build options: `-DUSE_MCO` uses the ST-LINK clock instead of HSI (not
recommended); `-DCLOCK_TEST` prints 64 LSE clock measurements.

The output uses the same words as the dsPIC firmware (`FRAME`, `CLOCK`, `SEARCH`),
plus a `STATUS` line every 10 s:

```
[  127.4] FRAME   #20 corr 60% snr 4 dB, fixed 3: 2026-09-27 15:11:00 UTC
[  127.4] CLOCK   frame agrees with clock, error +0.2 ms
[  130.0] STATUS  2026-09-27 15:11:04 UTC | carrier locked, noise 9.2 deg | mixer 223530 Hz, clock +6576 ppm (LSE) | heard 20, decoded 9, confirmed 2, rejected 0 | cpu 12%, max lag 0 ms
```

`mixer` is where the carrier appears on the Nucleo's own clock scale, and `clock` is
the HSI error measured against the LSE. `cpu` is the load of the signal path.

## Tools

| file | purpose |
|---|---|
| `tools/nucleo_logger.py` | serial logger: text lines with host UTC time to `rx.log`; for `AUDIO_DUMP` builds, 10-min 10 kHz WAVs plus an index (sample number ↔ host time) |
| `tools/prof.py` | carrier spectrum profile (dBc/Hz at 0.5–600 Hz offset); shows clock phase noise |
| `tools/nucleo_ana.py` | phase of the known preamble bits in slots where the IC-705 saw a time frame: true bit separation and noise |
| `tools/dcf_assist.py` | DCF77 from the 77.5 kHz channel, assisted by eCzas time: carrier, amplitude-pattern correlation, bit check, phase-code search |
| `tools/compare3.py` | slot-by-slot comparison of the Nucleo, the Legnica eCzas board and the IC-705 reference |

## First results (27 Sep 2026, Wrocław)

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

### Image filter (A/B test, same day)

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
