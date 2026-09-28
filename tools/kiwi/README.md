# kiwi: public KiwiSDRs as GPS-timed reference receivers

Uses [kiwiclient](https://github.com/jks-prv/kiwiclient) (`kiwirecorder.py`, cloned next to these
scripts) in IQ mode with `--kiwi-wav`: every 512-sample block carries the Kiwi's GPS time.

| file | what |
|---|---|
| `kiwi_ref.py BASE` | e-CzasPL 225 kHz: records permanently, rebuilds 10-min UTC slots from the blocks by their GPS time (reconnect gaps stay silent), converts to the 8 kHz format of the IC-705 reference pipeline (`proc.py` then decodes: frames, slots, early frames) |
| `kiwi_ref.py BASE dcf` | DCF77 77.5 kHz: same, slots as 2 kHz complex (`.c64`, the NUCLEO dump format); every hour `firmware/host/dcfsim` (coh.c + dcf.c) over the last 6 h with the GPS time base: last column = DCF77 second start - UTC second |
| `cmp_site.py KIWI.wav IFDIR` | carrier phase spread / amplitude fluctuation at the Kiwi vs our own IF recording, same UTC window |

Sites (tested 28 Sep 2026 10:20 UTC): `centralczechia.proxy.kiwisdr.com:8073` and
`21692.proxy.kiwisdr.com:8073` (Luisenfelde) give full-rate sessions and clean carriers;
`sdrplonsk.duckdns.org:8078` is clean but drops the session every ~10 s. `*.proxy.kiwisdr.com`
needs port 8073. GPS stamps: 11998.83 samples/s, 0.1 us block-to-block jitter.

Clean e-CzasPL at a good site: phase spread -22..+14 deg (5/95 %), amplitude cv ~0.14. On 28 Sep
from ~09:15 UTC our own site showed -29..+26 deg / 0.25 in the same seconds while Plonsk,
Central Czechia and Luisenfelde stayed clean: a local disturbance, not the transmitter.
