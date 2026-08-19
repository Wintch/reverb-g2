#!/usr/bin/env bash
# Force the G2's companion device to re-enumerate, on demand.
#
# WHY: the companion sits on the headset's USB2 branch, which re-enumerates by itself several
# times a minute (docs/60 -- measured at the same rate on Windows, so it is the link, not us).
# Every re-enumeration invalidates the hidraw fd Monado holds, and until patch 0090 that killed
# panel control, IPD and XR_EXT_user_presence for the rest of the session. Waiting for a natural
# storm event to test that recovery is slow and unrepeatable; this reproduces the fault in one
# command, which is what makes it a regression test instead of an anecdote.
#
# It does the same thing the fault does: de-authorize the USB device, wait, re-authorize. The
# kernel tears the device down and enumerates it again with a NEW hidraw node -- exactly the
# condition the driver has to survive.
#
# USAGE:
#   sudo ./scripts/usb-companion-reset.sh            # one cycle, 3 s down (the measured p50)
#   sudo ./scripts/usb-companion-reset.sh -d 10      # a long outage
#   sudo ./scripts/usb-companion-reset.sh -n 5 -i 20 # 5 cycles, 20 s apart -- a synthetic storm
#
# WHAT TO WATCH, in the service log:
#   "Error reading from companion (HMD control) device"   -> the fault landed
#   "Companion device RECONNECTED on /dev/hidrawN after"  -> the recovery worked, with a number
# and, physically: the panel must stay on and presence must keep working.

set -euo pipefail

VID=03f0
PID=0580
DOWN_S=3
COUNT=1
INTERVAL_S=15

usage() { sed -n '2,26p' "$0" | sed 's/^# \?//'; exit "${1:-0}"; }

while getopts "d:n:i:v:p:h" opt; do
	case "$opt" in
	d) DOWN_S=$OPTARG ;;
	n) COUNT=$OPTARG ;;
	i) INTERVAL_S=$OPTARG ;;
	v) VID=$OPTARG ;;
	p) PID=$OPTARG ;;
	h) usage 0 ;;
	*) usage 1 ;;
	esac
done

find_device() {
	local d v p
	for d in /sys/bus/usb/devices/*; do
		[ -r "$d/idVendor" ] || continue
		v=$(cat "$d/idVendor")
		p=$(cat "$d/idProduct")
		if [ "$v" = "$VID" ] && [ "$p" = "$PID" ]; then
			echo "$d"
			return 0
		fi
	done
	return 1
}

hidraw_node() {
	# The node the driver would find. Printing it before and after is the point: if it does
	# not change, the device did not really re-enumerate and the test proved nothing.
	local h id want
	want=$(printf 'HID_ID=0003:%08X:%08X' "0x$VID" "0x$PID")
	for h in /sys/class/hidraw/hidraw*; do
		[ -r "$h/device/uevent" ] || continue
		if grep -qF "$want" "$h/device/uevent"; then
			basename "$h"
			return 0
		fi
	done
	echo "(absent)"
}

if [ "$(id -u)" -ne 0 ]; then
	echo "This needs root to write sysfs 'authorized'. Re-run with sudo." >&2
	exit 1
fi

DEV=$(find_device) || {
	echo "No USB device $VID:$PID found -- is the headset connected?" >&2
	exit 1
}

echo "companion: $DEV (bus $(cat "$DEV/busnum") dev $(cat "$DEV/devnum")), currently $(hidraw_node)"

for i in $(seq 1 "$COUNT"); do
	before=$(hidraw_node)
	echo "[$i/$COUNT] $(date +%H:%M:%S.%3N) de-authorizing for ${DOWN_S}s (was $before)"
	echo 0 >"$DEV/authorized"
	sleep "$DOWN_S"
	echo 1 >"$DEV/authorized"

	# Give udev time to create the node and apply permissions before reporting.
	for _ in $(seq 1 40); do
		sleep 0.25
		node=$(hidraw_node)
		[ "$node" != "(absent)" ] && break
	done
	echo "[$i/$COUNT] $(date +%H:%M:%S.%3N) back as $node$([ "$node" = "$before" ] && echo '  <-- SAME node, weak test' || true)"

	if [ "$i" -lt "$COUNT" ]; then
		sleep "$INTERVAL_S"
	fi
done

echo "done. Check the service log for 'Companion device RECONNECTED'."
