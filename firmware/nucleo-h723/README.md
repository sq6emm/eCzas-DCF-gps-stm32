# NUCLEO-H723ZG firmware: e-CzasPL + DCF77 receiver (M3, coherent)

Since 27 Sep 2026 22:51 UTC (M3) the receiver no longer imitates the SI4735. Two independent
stations share only the ADC samples and the time base:

```
A0 -> ADC 1 Msps -> per station: mixer phase-locked to true (LSE) time, fixed at 225.000 / 77.500 kHz
   -> sum over exactly 0.5 ms of true time -> 2 kHz complex
   -> own carrier tracker (../common/coh.c: FFT search -> PLL; same code, per-station settings)
        e-CzasPL: 2 ms steps, ~1 Hz loop, decision-directed on the two data levels
                  -> carrier-relative phase at 500 Hz -> ../common/ecz.c -> frame.c / timekeeper.c
        DCF77:    10 s steps, ~0.01 Hz loop, lines without second marks are rejected as spurs
                  -> ../common/dcf.c: second mark, minute, phase code
```

Output lines (besides FRAME / CLOCK / TIMEMAP):
- `STATUS` every 10 s: time, eCzas carrier (state, offset, loop noise, '0' level), frame
  counts, DCF77 carrier state, clock error, CPU load.
- `CARRIER` every 60 s, for each station: frequency and phase against the crystal, C/N0 and
  state. It also gives the eCzas−DCF77 difference in ppb, where the crystal's error cancels.
- `DCF77` every 10 min: the second mark (ms of the LSE second, σ), the minute and the phase
  code (σ). For the record it also gives where the DCF77 second starts relative to the e-CzasPL
  second; nothing is fed back.

LEDs: LD1 green = eCzas carrier locked, LD2 yellow = DCF77 carrier locked, LD3 red = toggles
on every decoded eCzas frame.

Dumps (`-DAUDIO_DUMP`, 921600 baud): both mixer outputs as 2 kHz complex float32 packets
(`A5 5B` DCF77, `A5 5C` e-CzasPL); `tools/nucleo_logger.py` writes `dcf_*.c64` / `ecz_*.c64`.

Host tests: `../host` (`cohsim` against the old core, `dcfsim` on recorded DCF77 data), results
in `../common/README.md`.

The description below is of M2 (SI4735 imitation), kept for the history.

A test port of the receiver: the 225 kHz signal is sampled directly by the STM32H723's
ADC, turned into the same 10 kHz "audio" (carrier at 1 kHz) that the SI4735 gives the
dsPIC, and fed to the **unchanged eCzas core** (`../../eczas/Firmware/src/core`: dsp.c,
frame.c, timekeeper.c, from the `eczas` submodule). No radio chip, only an antenna tuned to ~225 kHz.

## Hardware

- NUCLEO-H723ZG, powered and flashed through its ST-LINK V3 (USB).
- Input on **A0 (PA3)**: see [`doc/nucleo_225kHz_input.pdf`](../../doc/nucleo_225kHz_input.pdf).
  Planned: two tuned rods (225 kHz on A0, 77.5 kHz on A1) on one shared, decoupled 1.65 V bias
  node, no coupling capacitors: [`doc/nucleo_225_77kHz_input.pdf`](../../doc/nucleo_225_77kHz_input.pdf)
  (the old 10k/10k divider through 100 nF loads the tuned rod to Q about 8).
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
cd firmware/nucleo-h723
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

