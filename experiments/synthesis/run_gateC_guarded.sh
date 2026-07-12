#!/usr/bin/env bash
# Gate C launcher with a memory + wall-time watchdog so a thrashing synth is
# stopped safely instead of taking down the 12 GB host.
set -u
cd "$(dirname "$0")/../.." || exit 1
VIV=/tools/AMD/2025.2/Vivado/bin/vivado
PART=xc7z020clg400-1
MAXTHREADS=${MAXTHREADS:-2}   # cap parallel synth workers (memory-bounded host)
DIR=experiments/synthesis/results/gateC_decoder_core
mkdir -p "$DIR"
LOG="$DIR/synth.log"
RSS_LIMIT_MB=9000      # abort above this total vivado RSS (host has ~12 GB)
WALL_LIMIT_S=3600      # abort after 1 h

"$VIV" -mode batch -nojournal -notrace -log "$LOG" -journal "$DIR/synth.jou" \
  -source experiments/synthesis/synth_decoder_core.tcl -tclargs "$PART" "$MAXTHREADS" \
  >"$DIR/console.log" 2>&1 &
VPID=$!
echo "vivado pid=$VPID  maxThreads=$MAXTHREADS (RSS limit ${RSS_LIMIT_MB}MB, wall ${WALL_LIMIT_S}s)"

start=$(date +%s)
peak_mb=0
while kill -0 "$VPID" 2>/dev/null; do
  sleep 15
  # Sum RSS across ALL vivado processes (parent + parallel_synth_helper workers).
  rss_mb=$(ps -eo rss,comm 2>/dev/null | awk '/vivado/{s+=$1} END{printf "%d", s/1024}')
  [ "$rss_mb" -gt "$peak_mb" ] && peak_mb=$rss_mb
  now=$(date +%s); elapsed=$(( now - start ))
  swap_mb=$(free -m | awk '/Swap/{print $3}')
  echo "[watchdog] t=${elapsed}s vivado_rss=${rss_mb}MB peak=${peak_mb}MB swap=${swap_mb}MB"
  abort=""
  [ "$rss_mb" -gt "$RSS_LIMIT_MB" ] && abort="MEM rss=${rss_mb}MB"
  [ "$elapsed" -gt "$WALL_LIMIT_S" ] && abort="TIME t=${elapsed}s"
  if [ -n "$abort" ]; then
    echo "[watchdog] ABORTING synth ($abort)"
    pkill -TERM -i vivado 2>/dev/null; kill -TERM "$VPID" 2>/dev/null
    sleep 5; pkill -KILL -i vivado 2>/dev/null; kill -KILL "$VPID" 2>/dev/null
    echo "GATEC_RESULT=ABORTED_${abort} peak=${peak_mb}MB"; exit 42
  fi
done
wait "$VPID"; rc=$?
now=$(date +%s); elapsed=$(( now - start ))
echo "GATEC_RESULT=EXIT_${rc} t=${elapsed}s peak_rss=${peak_mb}MB"
grep -h "INFERENCE SUMMARY" "$DIR/console.log" 2>/dev/null
exit $rc
