#!/bin/bash
# fw-soak.sh -- stress the WMR controller firmware reads over the host Bluetooth link.
#
# Runs `monado-cli test` (prober + builders, no compositor) in a loop, alternating two builds,
# and counts per cycle what the firmware block reads did: clean reads, stale replies discarded
# in the chunk loop, stale replies on the header request, and controller creation failures.
# Built for the !2967 header stale-reply fix (docs/146).
#
#   setsid nohup bash fw-soak.sh <cycles-per-variant> [settle_s] \
#       > ~/vr/logs/fw-soak.out 2>&1 < /dev/null &
#
# Variants: ~/vr/monado-2967-bin/<v>/monado-cli, alternated; FW_SOAK_VARIANTS="base hdrfix" by default. Needs the G2 on USB and both
# controllers awake on the host adapter; it waits (and asks out loud) when they are not.
# Results: ~/vr/logs/fw-soak-<stamp>/ (one log per cycle + results.csv), end marker
# ~/vr/logs/fw-soak-<stamp>.done. Abort with `touch ~/vr/logs/fw-soak-STOP`.
set -u

CYCLES=${1:?cycles per variant}; SETTLE=${2:-5}
BIN=${FW_SOAK_BIN:-$HOME/vr/monado-2967-bin}
STAMP=$(date +%Y%m%d-%H%M%S)
OUT=$HOME/vr/logs/fw-soak-$STAMP; DONE=$OUT.done; STOP=$HOME/vr/logs/fw-soak-STOP
mkdir -p "$OUT"; rm -f "$STOP"
say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
bt_nodes() { local n=0 h; for h in /sys/class/hidraw/hidraw*; do grep -q 'HID_ID=0005:0000045E:0000066A' "$h/device/uevent" 2>/dev/null && n=$((n + 1)); done; echo $n; }
running() { local p c; for p in /proc/[0-9]*; do c=$(cat "$p/comm" 2>/dev/null) || continue; case "$c" in monado-service|monado-cli|vrserver|hello_xr) echo "$c"; return;; esac; done; }

VARIANTS=${FW_SOAK_VARIANTS:-base hdrfix}
for v in $VARIANTS; do [ -x "$BIN/$v/monado-cli" ] || { echo "status=refused reason=missing $BIN/$v/monado-cli" > "$DONE"; exit 2; }; done
r=$(running); [ -z "$r" ] || { echo "status=refused reason=$r is running" > "$DONE"; exit 2; }

echo "cycle,variant,rc,bt_nodes,builder,ctrls_created,blocks_read,chunk_stale,header_stale,header_fail,too_many,create_fail" > "$OUT/results.csv"
for i in $(seq 1 "$CYCLES"); do
	for v in $VARIANTS; do
		[ -f "$STOP" ] && { echo "status=aborted cycle=$i" > "$DONE"; exit 1; }
		# Controllers must be awake: wait up to 60 s, ask once.
		asked=0
		for _ in $(seq 1 120); do
			[ "$(bt_nodes)" -ge 2 ] && break
			[ $asked = 0 ] && { say "Agitá los joysticks, por favor"; asked=1; }
			sleep 0.5
		done
		n=$(bt_nodes)
		L="$OUT/$(printf %03d "$i")-$v.log"
		WMR_LOG=debug XRT_LOG=info WMR_SLAM=0 WMR_HANDTRACKING=0 \
			timeout 40 "$BIN/$v/monado-cli" test > "$L" 2>&1 < /dev/null
		rc=$?
		builder=$(grep -m1 -oE 'Using builder [a-z_]+' "$L" | awk '{print $3}')
		ctrls=$(grep -cE '^\s+(left|right): HP Reverb G2 (Left|Right) Controller' "$L")
		echo "$i,$v,$rc,$n,${builder:-none},$ctrls,$(grep -c 'FW data block' "$L"),$(grep -c 'Discarding stale fw reply (block [0-9]*, ' "$L"),$(grep -c 'while reading the header of block' "$L"),$(grep -c 'stale reply for block' "$L"),$(grep -c 'too many stale replies' "$L"),$(grep -c 'Failed to create WMR controller' "$L")" >> "$OUT/results.csv"
		sleep "$SETTLE"
	done
done
echo "status=done cycles=$CYCLES out=$OUT" > "$DONE"
say "Terminó la prueba de firmware."
