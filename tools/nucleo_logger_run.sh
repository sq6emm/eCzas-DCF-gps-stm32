#!/bin/bash
# (Re)creates the container nucleo-logger: tools/nucleo_logger.py on the STLINK-V3 VCP -> /data/claude/nucleo-h723/log,
# restarted 5 s after it exits. A second loop in the same container rotates the log once an hour (nice 19, ionice idle):
# .c64/.wav older than 7 days are deleted, their .idx.csv gzipped (only once the data file is gone: dcf_track.py
# reads <name>.idx.csv for every dcf_*.c64; np.loadtxt reads the .gz directly). rx.log is left alone.
# Output of both loops: docker logs nucleo-logger
ROTATE='while true; do
  n=$(find /p/log -maxdepth 1 \( -name "*.c64" -o -name "*.wav" \) -mmin +10080 -print -delete | wc -l)
  z=0
  for f in $(find /p/log -maxdepth 1 -name "*.idx.csv" -mmin +10080); do
    b=${f%.idx.csv}
    [ -e "$b.c64" ] || [ -e "$b.wav" ] || { gzip -9 "$f" && z=$((z+1)); }
  done
  echo "$(date -u +%FT%T) rotate: deleted $n data files, gzipped $z csv"
  sleep 3600
done'
CMD='nice -n 19 ionice -c3 sh -c "$ROTATE" &
while true; do python3 -u /p/rx/nucleo_logger.py /dev/serial/by-id/usb-STMicroelectronics_STLINK-V3_002B00273331510633323639-if02 921600 /p/log; echo "$(date -u +%FT%T) logger exited $?, reopening in 5 s"; sleep 5; done'
docker rm -f nucleo-logger >/dev/null 2>&1
docker run -d --restart unless-stopped --label owner=claude --name nucleo-logger --user 1001:1001 --group-add 20 \
  -v /data/claude/nucleo-h723:/p -v /dev:/dev --device-cgroup-rule 'c 166:* rmw' \
  --log-driver json-file --log-opt max-size=250m --log-opt max-file=3 \
  -e ROTATE="$ROTATE" eczas-arm:1 sh -c "$CMD"
