#!/bin/bash
# One night with the IC-7610 SUB on TDF (162 kHz; dial 163.000 USB, mirrored IF -> ~13 kHz), MAIN stays on
# e-CzasPL; back to DCF77 at $1 (UTC, e.g. "2026-10-02 05:00:00"). The DCF77 SUB pipeline (ic7610-dcf) is
# paused and recreated from the first whole DCF77 file afterwards. Log: /data/claude/ic7610/lf/sub_schedule.log
LOG=/data/claude/ic7610/lf/sub_schedule.log
rec() {   # $1 label $2 SUB dial BCD
  docker stop -t 15 ic7610-lan-rec >/dev/null 2>&1; docker rm ic7610-lan-rec >/dev/null 2>&1
  docker run -d --restart unless-stopped --label owner=claude --name ic7610-lan-rec --network host --user 1001:1001 \
    -v /data/claude/ic7610/icomlan:/w:ro -v /data/claude/ic7610/rec7610:/out python:3.12-slim python3 -u /w/icomlan.py \
    --host 192.168.253.4 --user claude --password claudeicom --lport 50121 --codec 0x10 --out /out --file-time 600 --align --stats 600 \
    --civ "FE FE 98 E0 25 00 00 60 22 00 00 FD" --civ "FE FE 98 E0 25 01 $2 FD" \
    --civ "FE FE 98 E0 26 00 01 00 01 FD" --civ "FE FE 98 E0 26 01 01 00 01 FD" >/dev/null
  echo "$(date -u '+%Y-%m-%d %H:%M:%S') $1 MAIN 00 60 22 00 00 SUB $2" >> $LOG
}
docker stop ic7610-dcf >/dev/null 2>&1
rec night-TDF "00 30 16 00 00"
t=$(date -u -d "$1" +%s); while [ $(date +%s) -lt $t ]; do sleep 20; done
rec normal "00 85 07 00 00"
first=$(date -u -d "@$(( ( $(date +%s) / 600 + 1 ) * 600 ))" +%Y%m%d_%H%M00)
docker rm -f ic7610-dcf >/dev/null
docker run -d --restart unless-stopped --label owner=claude --name ic7610-dcf --user 1001:1001 -v /data/claude/ic7610:/i:ro \
  -v /data/claude/ic7610-dcf:/o -v /data/claude/git/eCzas-DCF-gps-stm32:/r:ro dcfbench:1 python3 -u /i/dcf7610.py /i/rec7610 /o $first >/dev/null
echo "$(date -u '+%Y-%m-%d %H:%M:%S') ic7610-dcf restarted from $first" >> $LOG
