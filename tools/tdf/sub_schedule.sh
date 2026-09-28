#!/bin/bash
# IC-7610 SUB test schedule (MAIN stays on e-CzasPL): restarts the recorder with another SUB dial.
# Log: /data/claude/ic7610/lf/sub_schedule.log (UTC switch time, station, dial). The DCF77 SUB
# pipeline (ic7610-dcf) is paused and recreated afterwards starting at the first DCF77 file again.
LOG=/data/claude/ic7610/lf/sub_schedule.log
rec() {   # $1 station $2 dial BCD
  docker stop -t 15 ic7610-lan-rec >/dev/null 2>&1; docker rm ic7610-lan-rec >/dev/null 2>&1   # SIGTERM: the recorder closes its file
  docker run -d --restart unless-stopped --label owner=claude --name ic7610-lan-rec --network host --user $(id -u):$(id -g) \
    -v /data/claude/ic7610/icomlan:/w:ro -v /data/claude/ic7610/rec7610:/out python:3.12-slim python3 -u /w/icomlan.py \
    --host 192.168.253.4 --user claude --password claudeicom --lport 50121 --codec 0x10 --out /out --file-time 600 --align --stats 600 \
    --civ "FE FE 98 E0 25 00 00 60 22 00 00 FD" --civ "FE FE 98 E0 25 01 $2 FD" \
    --civ "FE FE 98 E0 26 00 01 00 01 FD" --civ "FE FE 98 E0 26 01 01 00 01 FD" >/dev/null
  echo "$(date -u '+%Y-%m-%d %H:%M:%S') $1 $2" >> $LOG
}
until_utc() { local t=$(date -u -d "$1" +%s); while [ $(date +%s) -lt $t ]; do sleep 20; done; }
docker stop ic7610-dcf >/dev/null 2>&1
[ "$1" = resume ] || rec TDF "00 30 16 00 00"
until_utc "2026-09-28 23:40:00"
rec MSF "00 10 06 00 00"; until_utc "2026-09-29 00:10:00"
rec RBU "67 76 06 00 00"; until_utc "2026-09-29 00:40:00"
rec DCF77 "00 85 07 00 00"
# DCF77 SUB pipeline again, from the first whole DCF77 file on
docker rm -f ic7610-dcf >/dev/null
docker run -d --restart unless-stopped --label owner=claude --name ic7610-dcf --user $(id -u):$(id -g) -v /data/claude/ic7610:/i:ro \
  -v /data/claude/ic7610-dcf:/o -v /data/claude/git/eCzas-DCF-gps-stm32:/r:ro dcfbench:1 python3 -u /i/dcf7610.py /i/rec7610 /o 20260929_005000 >/dev/null
echo "$(date -u '+%Y-%m-%d %H:%M:%S') ic7610-dcf restarted from 20260929_005000" >> $LOG
