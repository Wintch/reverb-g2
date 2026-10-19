#!/bin/bash
# idle-vs-moving.sh -- does the first-fw-command silence depend on the controllers being still?
# Phase 1: N runs of the probe12 build with nobody touching the controllers. Phase 2: N runs while the
# user keeps waving them (the script asks out loud). probe12 logs "PROBE <cmd> answered=<0|1> after <ms>"
# (12 attempts, so a late reply is timed instead of cut off). Output goes to the NVMe.
#   setsid nohup bash idle-vs-moving.sh [runs-per-phase] > /dev/null 2>&1 < /dev/null &
set -u
N=${1:-5}; BIN=${COLD_BIN:-$HOME/vr/monado-2967-bin}/probe12/monado-cli
OUT=${COLD_OUT:-/mnt/resolve_test/vr-tmp}/idle-moving-$(date +%Y%m%d-%H%M%S); mkdir -p "$OUT"
say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
nodes() { local n=0 h; for h in /sys/class/hidraw/hidraw*; do grep -q "HID_ID=0005:0000045E:0000066A" "$h/device/uevent" 2>/dev/null && n=$((n + 1)); done; echo $n; }
echo "phase,run,rc,ctrls,probe" > "$OUT/results.csv"
run() { # run <phase> <i>
	local L="$OUT/$1-$2.log"
	WMR_LOG=debug XRT_LOG=info WMR_SLAM=0 WMR_HANDTRACKING=0 timeout 60 "$BIN" test > "$L" 2>&1 < /dev/null; local rc=$?
	echo "$1,$2,$rc,$(grep -cE "^\s+(left|right): HP Reverb G2 (Left|Right) Controller" "$L"),\"$(grep -o "PROBE [a-z]* answered=[01] after [0-9]* ms" "$L" | sed "s/PROBE //;s/ answered=/:/;s/ after /:/;s/ ms/ms/" | tr "\n" " ")\"" >> "$OUT/results.csv"
}
[ "$(nodes)" -ge 2 ] || { echo "status=refused controllers not up" > "$OUT.done"; exit 2; }
say "Primera fase. Dejá los joysticks quietos, sin tocarlos"; sleep 20
for i in $(seq 1 "$N"); do run idle "$i"; sleep 4; done
say "Segunda fase. Agitá los dos joysticks sin parar hasta que te avise"; sleep 6
for i in $(seq 1 "$N"); do run moving "$i"; sleep 2; done
echo "status=done out=$OUT" > "$OUT.done"; say "Terminó. Ya podés soltar los joysticks."
