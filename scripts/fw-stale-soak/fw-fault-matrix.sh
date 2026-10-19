#!/bin/bash
# fw-fault-matrix.sh -- deterministic A/B for the !2967 firmware-read recovery paths (docs/150).
#
# The soaks in docs/146 could not discriminate the init-command retry (no slow reply ever showed up
# on demand). This drops the read of chosen firmware commands so the reply arrives late, exactly
# like a >250 ms reply, using the test-only patch fault-inject.patch (never upstreamed):
#   WMR_FWFAULT=cmd,blk,addr_min,addr_max,count    (-1 = any)
# Variants are ~/vr/monado-2967-bin/<v>/monado-cli; the "-inj" twins carry the patch.
#
#   setsid nohup bash fw-fault-matrix.sh [repeats] [variants...] > ~/vr/logs/fw-fault.out 2>&1 < /dev/null &
#
# Needs the G2 on USB and both controllers awake on the host adapter. Results:
# ~/vr/logs/fw-fault-<stamp>/ (one log per run + results.csv), marker ~/vr/logs/fw-fault-<stamp>.done.
# Abort with `touch ~/vr/logs/fw-fault-STOP`.
set -u

REPS=${1:-3}; shift || true
VARIANTS=${*:-mbase-inj mfix2-inj}
BIN=$HOME/vr/monado-2967-bin; SETTLE=5
STAMP=$(date +%Y%m%d-%H%M%S)
OUT=$HOME/vr/logs/fw-fault-$STAMP; DONE=$OUT.done; STOP=$HOME/vr/logs/fw-fault-STOP
mkdir -p "$OUT"; rm -f "$STOP"
say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
bt_nodes() { local n=0 h; for h in /sys/class/hidraw/hidraw*; do grep -q "HID_ID=0005:0000045E:0000066A" "$h/device/uevent" 2>/dev/null && n=$((n + 1)); done; echo $n; }
running() { local p c; for p in /proc/[0-9]*; do c=$(cat "$p/comm" 2>/dev/null) || continue; case "$c" in monado-service|monado-cli|vrserver|hello_xr) echo "$c"; return;; esac; done; }

# name:WMR_FWFAULT. A controller only reads two blocks: 0 (67 bytes, header reply only) and 3 (450 bytes).
# hdr-stale: the block 0 header reply goes missing, is resent, and the duplicate lands on block 3 header.
# FW_ONLY="none hdr-stale" restricts the run to those scenario names.
SCENARIOS=(
	"none:"
	"zero1:0,-1,-1,-1,1"
	"quiesce1:4,-1,-1,-1,1"
	"zero2:0,-1,-1,-1,2"
	"hdr-stale:2,0,-1,-1,1"
	"chunk-mid:2,1,200,300,1"
	"zero3-neg:0,-1,-1,-1,3"
	"chunk3-neg:2,3,1,500,3"
)
for v in $VARIANTS; do [ -x "$BIN/$v/monado-cli" ] || { echo "status=refused reason=missing $BIN/$v/monado-cli" > "$DONE"; exit 2; }; done
r=$(running); [ -z "$r" ] || { echo "status=refused reason=$r is running" > "$DONE"; exit 2; }

echo "scenario,rep,variant,rc,bt_nodes,builder,ctrls_created,injected,retries,chunk_stale,header_stale,header_fail,create_fail" > "$OUT/results.csv"
for sc in "${SCENARIOS[@]}"; do
	name=${sc%%:*}; spec=${sc#*:}
	[ -n "${FW_ONLY:-}" ] && [[ " $FW_ONLY " != *" $name "* ]] && continue
	for i in $(seq 1 "$REPS"); do
		for v in $VARIANTS; do
			[ -f "$STOP" ] && { echo "status=aborted scenario=$name rep=$i" > "$DONE"; exit 1; }
			asked=0
			for _ in $(seq 1 120); do
				[ "$(bt_nodes)" -ge 2 ] && break
				[ $asked = 0 ] && { say "Agitá los joysticks, por favor"; asked=1; }
				sleep 0.5
			done
			n=$(bt_nodes)
			L="$OUT/$name-$(printf %02d "$i")-$v.log"
			if [ -n "$spec" ]; then export WMR_FWFAULT="$spec"; else unset WMR_FWFAULT; fi
			WMR_LOG=debug XRT_LOG=info WMR_SLAM=0 WMR_HANDTRACKING=0 \
				timeout 40 "$BIN/$v/monado-cli" test > "$L" 2>&1 < /dev/null
			rc=$?
			builder=$(grep -m1 -oE "Using builder [a-z_]+" "$L" | awk "{print \$3}")
			ctrls=$(grep -cE "^\s+(left|right): HP Reverb G2 (Left|Right) Controller" "$L")
			echo "$name,$i,$v,$rc,$n,${builder:-none},$ctrls,$(grep -c FAULT-INJECT "$L"),$(grep -c "fw cmd failed" "$L"),$(grep -c "Discarding stale fw reply (block [0-9]*, " "$L"),$(grep -c "while reading the header of block" "$L"),$(grep -c "stale reply for block" "$L"),$(grep -c "Failed to create WMR controller" "$L")" >> "$OUT/results.csv"
			sleep "$SETTLE"
		done
	done
done
echo "status=done out=$OUT" > "$DONE"
say "Terminó la matriz de fallos de firmware."
