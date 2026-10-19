#!/bin/bash
# cold-probe.sh -- measure how long the first fw init reply takes right after the controllers wake from idle.
# Round: wait for both BT hidraw nodes to disappear (controllers asleep), ask for a shake, then run the
# probe12 monado-cli back to back so the first cycles hit a just-woken controller. Log: ~/vr/logs/cold-<stamp>/
set -u
STAMP=$(date +%Y%m%d-%H%M%S); OUT=$HOME/vr/logs/cold-$STAMP; DONE=$OUT.done; mkdir -p "$OUT"
BIN=$HOME/vr/monado-2967-bin/probe12/monado-cli; ROUNDS=${1:-2}; CYC=${2:-5}
say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
nodes() { local n=0 h; for h in /sys/class/hidraw/hidraw*; do grep -q "HID_ID=0005:0000045E:0000066A" "$h/device/uevent" 2>/dev/null && n=$((n+1)); done; echo $n; }
echo "round,cycle,t_since_wake_s,rc,ctrls,probe" > "$OUT/results.csv"
for r in $(seq 1 "$ROUNDS"); do
	say "Dejá los joysticks quietos, sin tocarlos, hasta que te avise"
	for _ in $(seq 1 600); do [ "$(nodes)" -eq 0 ] && break; sleep 1; done
	if [ "$(nodes)" -ne 0 ]; then echo "round $r: controllers never slept" >> "$OUT/notes.txt"; continue; fi
	sleep 20; say "Ahora, agitá los dos joysticks"
	for _ in $(seq 1 120); do [ "$(nodes)" -ge 2 ] && break; sleep 0.5; done
	[ "$(nodes)" -ge 2 ] || { echo "round $r: never woke" >> "$OUT/notes.txt"; continue; }
	W=$(date +%s)
	for c in $(seq 1 "$CYC"); do
		L="$OUT/r$r-c$c.log"
		WMR_LOG=debug XRT_LOG=info WMR_SLAM=0 WMR_HANDTRACKING=0 timeout 40 "$BIN" test > "$L" 2>&1 < /dev/null; rc=$?
		echo "$r,$c,$(( $(date +%s) - W )),$rc,$(grep -cE "^\s+(left|right): HP Reverb G2 (Left|Right) Controller" "$L"),\"$(grep -o "PROBE [a-z]* answered=[01] after [0-9]* ms" "$L" | sed "s/PROBE //;s/answered=//;s/ after / /;s/ ms/ms/" | tr "\n" ";")\"" >> "$OUT/results.csv"
		sleep 3
	done
done
echo "status=done out=$OUT" > "$DONE"; say "Terminó la medición en frío."
