# Coherent receiver core (shared by e-CzasPL and DCF77)

Replaces the SI4735 imitation (complex -> 1 kHz real audio -> AGC -> the dsPIC core's audio PLL).
The same code runs on the NUCLEO and in the host tests (`../host`).

- `coh.c` – carrier tracker, one instance per station, no shared state between them. The input is
  2 kHz complex baseband from a mixer phase-locked to true (LSE) time. Stages:
  1. FFT search (eCzas ±40 Hz in 2 s; DCF77 ±2 Hz in 128 s).
  2. PLL pull-in, then tracking. The same code serves both, with different integration:
     eCzas 2 ms steps, ~1 Hz loop, decision-directed on the two data levels;
     DCF77 10 s steps, ~0.01 Hz loop.
  3. Lost for a set time → search again.

  Every period it reports carrier frequency and phase against the crystal, C/N0, loop noise and state.
- `ecz.c` – e-CzasPL preamble detector on the carrier-relative phase (500 Hz). Correlator and
  detector are those of the eCzas firmware's `dsp.c`. Candidates go to the unchanged `frame.c` and
  `timekeeper.c` (from the `eczas` submodule).

The eCzas '0' level (`lvl0`) is learned from bit centres only; the 16 ms slews would bias it
towards 0 and the loop would follow the data. Each decoded frame also gives the measured level
(`coh_level_hint` with `frame_info_t.lvl_sep`).

## Host test against the old core (27 Sep 2026)

`host/compare_old_new.py` runs the eCzas firmware's `sim` (old core, SI4735-style audio path) and
`host/cohsim` (this chain) on the same recordings. It adds the same noise to both and takes the
truth from the majority of decoded frames. The table shows decoded + confirmed time frames; wrong
times were 0 in every run.

| set, noise added | old core | coherent chain |
|---|---|---|
| 7 files (IC-705 ferrite/frame loop, NUCLEO audio), none | 276 + 17 = 293 | 290 + 4 = 294 |
| same, 0 dB | 86 + 113 = 199 | 175 + 64 = **239** (+20 %) |
| same, −2 dB | 44 + 89 = 133 | 88 + 88 = **176** (+32 %) |
| 8 other files (IC-705 night 01–05 UTC, NUCLEO), none | 260 + 24 = 284 | 276 + 2 = 278 |
| same, 0 dB | 57 + 131 = 188 | 157 + 78 = **235** (+25 %) |
| same, −4 dB | 10 + 33 = 43 | 13 + 24 = 37 |

The coherent chain decodes more frames outright at every level. In moderately weak signals it gets
20–32 % more time frames. At the extreme (−4 dB) it is slightly behind. The NUCLEO files here are
the old firmware's audio (after its image filter and AGC); live, the chain gets the raw baseband.
