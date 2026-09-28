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

Bench, 28 Sep 22:40-22:50 (learn on 22:34-22:40, test on the next file, noise added):
confirmed minutes of 9: 9 (49 dB-Hz), 8 (25), 8 (22), 4 (20), 0 (<= 18); WRONG confirmed 0 at every level.
