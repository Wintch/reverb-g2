#!/bin/bash
# power-log.sh - sample real power draw (GPU via nvidia-smi, CPU package via RAPL) to a
# CSV, and report session averages in watts and Wh/h on exit.
#
#   ./power-log.sh [interval_s] [duration_s]     defaults: 5s interval, until killed
#
# Written 2026-08-18 (T209): the power CAP is a ceiling; what the arcade actually COSTS
# is the measured draw over a real session. These numbers are the machine-side half;
# the user's wall wattmeter later validates the system total (PSU efficiency, board,
# peripherals) against them. GPU draw comes from nvidia-smi power.draw; CPU package
# power is derived from RAPL energy counter deltas (/sys/class/powercap, microjoules,
# handles counter wraparound by dropping negative deltas).
set -u
INTERVAL="${1:-5}"
DURATION="${2:-0}"
OUT="$HOME/vr/logs/power-$(date +%Y%m%d-%H%M%S).csv"
RAPL=/sys/class/powercap/intel-rapl:0/energy_uj
if [ ! -r "$RAPL" ]; then
	echo "NOTE: RAPL not readable, CPU watts will read 0 -- run vr-power-setup.sh --apply with RAPL_PUBLIC=1" >&2
fi
echo "ts,gpu_w,cpu_pkg_w" > "$OUT"
echo "Sampling every ${INTERVAL}s -> $OUT (Ctrl-C or duration end to stop)"
start_ts=$(date +%s)
prev_e=$(cat "$RAPL" 2>/dev/null || echo 0)
prev_t=$(date +%s.%N)
total_gpu=0; total_cpu=0; n=0
trap 'echo; awk -F, -v n="$n" -v tg="$total_gpu" -v tc="$total_cpu" "BEGIN{if(n>0) printf \"session avg: GPU %.1f W + CPU pkg %.1f W = %.1f W machine-side (~%.0f Wh per hour of play)\n\", tg/n, tc/n, (tg+tc)/n, (tg+tc)/n}"; exit 0' INT TERM
while :; do
	sleep "$INTERVAL"
	now_t=$(date +%s.%N)
	gpu=$(nvidia-smi --query-gpu=power.draw --format=csv,noheader,nounits 2>/dev/null || echo 0)
	e=$(cat "$RAPL" 2>/dev/null || echo "$prev_e")
	cpu=$(awk -v e1="$prev_e" -v e2="$e" -v t1="$prev_t" -v t2="$now_t" \
		'BEGIN{d=(e2-e1)/1e6/(t2-t1); print (d<0||d>500)?0:d}')
	prev_e=$e; prev_t=$now_t
	echo "$(date +%s),$gpu,$cpu" >> "$OUT"
	total_gpu=$(awk -v a="$total_gpu" -v b="$gpu" 'BEGIN{print a+b}')
	total_cpu=$(awk -v a="$total_cpu" -v b="$cpu" 'BEGIN{print a+b}')
	n=$((n+1))
	if [ "$DURATION" -gt 0 ] && [ $(( $(date +%s) - start_ts )) -ge "$DURATION" ]; then
		kill -TERM $$
	fi
done
