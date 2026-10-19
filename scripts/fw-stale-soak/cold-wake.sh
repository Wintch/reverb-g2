#!/bin/bash
# cold-wake.sh -- provoke the "controller just reconnected" regime on demand and time the first fw replies.
# Per round: disconnect both controllers over BlueZ, wait for them to reconnect (hidraw nodes back), then
# run monado-cli (default: the probe12 build, which logs "PROBE <cmd> answered=<0|1> after <ms>") right away
# (cycle 1, "cold") and again 3 s later (cycle 2, "warm"). Output goes to the NVMe, never the root SSD.
#   setsid nohup bash cold-wake.sh [rounds] [variant ...] > /dev/null 2>&1 < /dev/null &
# Marker: <out>.done. Abort: touch <out>-STOP.
set -u
ROUNDS=${1:-10}; shift || true; VARIANTS=${*:-probe12}
BIN=${COLD_BIN:-$HOME/vr/monado-2967-bin}; ROOT=${COLD_OUT:-/mnt/resolve_test/vr-tmp}
STAMP=$(date +%Y%m%d-%H%M%S); OUT=$ROOT/cold-wake-$STAMP; mkdir -p "$OUT"
say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
nodes() { local n=0 h; for h in /sys/class/hidraw/hidraw*; do grep -q "HID_ID=0005:0000045E:0000066A" "$h/device/uevent" 2>/dev/null && n=$((n + 1)); done; echo $n; }
CTRL="B4:A9:FC:B2:2D:07 B4:A9:FC:B2:26:2D"
echo "round,variant,cycle,since_up_s,rc,ctrls,probe" > "$OUT/results.csv"
for r in $(seq 1 "$ROUNDS"); do
	for v in $VARIANTS; do
		[ -e "$OUT-STOP" ] && { echo "status=aborted round=$r" > "$OUT.done"; exit 1; }
		[ -x "$BIN/$v/monado-cli" ] || { echo "status=refused missing $BIN/$v/monado-cli" > "$OUT.done"; exit 2; }
		for a in $CTRL; do bluetoothctl disconnect "$a" >/dev/null 2>&1; done
		for _ in $(seq 1 20); do [ "$(nodes)" -eq 0 ] && break; sleep 0.5; done
		asked=0
		for _ in $(seq 1 100); do
			[ "$(nodes)" -ge 2 ] && break
			[ $asked = 0 ] && [ "$SECONDS" -gt 0 ] && { sleep 12; [ "$(nodes)" -ge 2 ] || { say "Agitá los joysticks, por favor"; asked=1; }; }
			sleep 0.5
		done
		[ "$(nodes)" -ge 2 ] || { echo "$r,$v,-,-,noctrl,0," >> "$OUT/results.csv"; continue; }
		UP=$(date +%s.%N)
		for c in 1 2; do
			L="$OUT/r$r-$v-c$c.log"
			WMR_LOG=debug XRT_LOG=info WMR_SLAM=0 WMR_HANDTRACKING=0 timeout 40 "$BIN/$v/monado-cli" test > "$L" 2>&1 < /dev/null; rc=$?
			echo "$r,$v,$c,$(printf %.1f "$(echo "$(date +%s.%N) - $UP" | bc)"),$rc,$(grep -cE "^\s+(left|right): HP Reverb G2 (Left|Right) Controller" "$L"),\"$(grep -o "PROBE [a-z]* answered=[01] after [0-9]* ms" "$L" | sed "s/PROBE //;s/ answered=/:/;s/ after /:/;s/ ms/ms/" | tr "\n" " ")\"" >> "$OUT/results.csv"
			sleep 3
		done
	done
done
echo "status=done out=$OUT" > "$OUT.done"; say "Terminó la prueba de arranque en frío."
