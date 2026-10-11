#!/bin/bash
# pc-soak.sh -- firmware reads right after a controller power-cycle (the docs/143 "R5" case).
#
# For each variant in ORDER: ask (out loud) for both controllers to be switched off, wait until
# their host-Bluetooth hidraw nodes are gone, ask for them to be switched on, wait until both are
# back, then run fw-soak.sh with that single variant for CYCLES cycles. Each block therefore starts
# on freshly woken controllers, and every variant gets the same number of "first after power-on"
# runs.
#
#   PC_ORDER="base fix2 base fix2" setsid nohup bash pc-soak.sh [cycles] \
#       > ~/vr/logs/pc-soak.out 2>&1 < /dev/null &
#
# End marker ~/vr/logs/pc-soak-<stamp>.done lists the fw-soak result dir of each block, in order.
set -u

CYCLES=${1:-3}
ORDER=${PC_ORDER:-base fix2 base fix2}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STAMP=$(date +%Y%m%d-%H%M%S)
DONE=$HOME/vr/logs/pc-soak-$STAMP.done
say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
bt_nodes() { local n=0 h; for h in /sys/class/hidraw/hidraw*; do grep -q 'HID_ID=0005:0000045E:0000066A' "$h/device/uevent" 2>/dev/null && n=$((n + 1)); done; echo $n; }
wait_nodes() { # wait_nodes <op> <count> <prompt>: poll up to 10 min, repeat the prompt every 30 s
	local i
	for i in $(seq 0 1200); do
		[ "$(bt_nodes)" "$1" "$2" ] && return 0
		[ $((i % 60)) = 0 ] && say "$3"
		sleep 0.5
	done
	return 1
}

: > "$DONE.tmp"
blk=0
for v in $ORDER; do
	blk=$((blk + 1))
	wait_nodes -eq 0 "Bloque $blk. Apagá los dos joysticks." || { echo "status=failed block=$blk reason=controllers never went off" >> "$DONE.tmp"; break; }
	wait_nodes -ge 2 "Ahora prendé los dos joysticks." || { echo "status=failed block=$blk reason=controllers never came back" >> "$DONE.tmp"; break; }
	sleep 3
	before=$(ls -d "$HOME"/vr/logs/fw-soak-2*/ 2>/dev/null | tail -1)
	FW_SOAK_VARIANTS=$v bash "$HERE/fw-soak.sh" "$CYCLES" 5 > /dev/null 2>&1 < /dev/null
	after=$(ls -d "$HOME"/vr/logs/fw-soak-2*/ 2>/dev/null | tail -1)
	[ "$after" != "$before" ] || after="(none)"
	echo "block=$blk variant=$v dir=$after" >> "$DONE.tmp"
done
say "Terminamos la prueba de reinicio. Gracias."
{ echo "status=done order=$ORDER cycles=$CYCLES"; cat "$DONE.tmp"; } > "$DONE"; rm -f "$DONE.tmp"
