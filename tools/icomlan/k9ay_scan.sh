#!/bin/bash
# K9AY scan for the IC-7610 (MAIN e-CzasPL, SUB DCF77): cycles the directions/LNA while one
# continuous recording runs; switch times in switch.log. Restores the starting setting at the end.
cd /data/claude/ic7610/k9ay
K=http://192.168.253.115:59
orig=$(curl -s -m 5 $K/Get/ | sed -E 's/.*"B0":([0-9]+).*/\1/'); echo "orig $orig" > switch.log
docker run -d --rm --label owner=claude --name ic7610-k9ay-rec --network host --user $(id -u):$(id -g) \
  -v /data/claude/ic7610/icomlan:/w:ro -v $PWD/rec:/out python:3.12-slim python3 -u /w/icomlan.py \
  --host 192.168.253.4 --user claude --password claudeicom --lport 50111 --codec 0x10 --out /out \
  --file-time 3600 --seconds ${SECS:-560} --stats 60 >/dev/null
sleep 6
for r in 1 2 3; do
  for cfg in "3080 SE+LNA" "2056 SE" "3076 NE+LNA" "2052 NE" "3073 SW+LNA" "2049 SW" "3074 NW+LNA" "2050 NW"; do
    set -- $cfg; curl -s -m 5 $K/Set0/$1 >/dev/null; echo "$(date +%s.%N) $1 $2 $r" >> switch.log; sleep 22
  done
done
curl -s -m 5 $K/Set0/$orig >/dev/null; echo "$(date +%s.%N) $orig restored" >> switch.log
