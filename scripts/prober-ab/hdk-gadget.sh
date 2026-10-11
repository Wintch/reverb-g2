#!/bin/bash
# Emulate an OSVR HDK on a virtual USB bus (dummy_hcd + configfs gadget) so Monado's
# HDK prober can be exercised without the hardware.
#
#   sudo bash hdk-gadget.sh up     create the device and start feeding tracker reports
#   sudo bash hdk-gadget.sh down   remove everything (device, feeder, modules)
#   sudo bash hdk-gadget.sh status
#
# Device layout mirrors the real HDK: VID:PID 1532:0b00, CDC ACM on interfaces 0+1,
# HID on interface 2 (the one hdk_found() opens), 32-byte vendor input reports.
# Override the product string with PRODUCT="OSVR  HDK 1.x" (two spaces) to hit the 1.x variant.
set -euo pipefail

G=/sys/kernel/config/usb_gadget/osvr_hdk_emu
PIDFILE=/run/osvr-hdk-emu-feeder.pid
PRODUCT="${PRODUCT:-OSVR HDK 2}"

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

feeder_stop() {
	if [ -f "$PIDFILE" ]; then
		kill "$(cat "$PIDFILE")" 2>/dev/null || true
		rm -f "$PIDFILE"
	fi
}

down() {
	feeder_stop
	if [ -d "$G" ]; then
		echo "" > "$G/UDC" 2>/dev/null || true
		rm -f "$G"/configs/c.1/acm.usb0 "$G"/configs/c.1/hid.usb0
		rmdir "$G"/configs/c.1/strings/0x409 "$G"/configs/c.1 2>/dev/null || true
		rmdir "$G"/functions/acm.usb0 "$G"/functions/hid.usb0 2>/dev/null || true
		rmdir "$G"/strings/0x409 2>/dev/null || true
		rmdir "$G"
	fi
	modprobe -r usb_f_hid usb_f_acm u_serial dummy_hcd libcomposite 2>/dev/null || true
	echo "down: gadget removed, modules unloaded"
	lsmod | grep -E '^(dummy_hcd|libcomposite|usb_f_hid)' || true
}

status() {
	echo "--- gadget"
	[ -d "$G" ] && { echo "UDC=$(cat "$G/UDC")"; echo "product=$(cat "$G/strings/0x409/product")"; } || echo "(none)"
	echo "--- host side"
	lsusb -d 1532:0b00 || echo "(no 1532:0b00 on the bus)"
	for d in /sys/bus/usb/devices/*; do
		[ -f "$d/idVendor" ] && [ "$(cat "$d/idVendor")" = 1532 ] && [ "$(cat "$d/idProduct")" = 0b00 ] || continue
		echo "usb node: /dev/bus/usb/$(printf %03d "$(cat "$d/busnum")")/$(printf %03d "$(cat "$d/devnum")")"
		for i in "$d":*; do
			echo "  if $(cat "$i/bInterfaceNumber") class $(cat "$i/bInterfaceClass") driver $(basename "$(readlink "$i/driver" 2>/dev/null)" 2>/dev/null)"
		done
	done
	for h in /sys/class/hidraw/hidraw*; do
		grep -q 'HID_ID=0003:00001532:00000B00' "$h/device/uevent" 2>/dev/null || continue
		n=/dev/$(basename "$h")
		echo "hidraw: $n (iface $(basename "$(readlink -f "$h/device/..")" | sed 's/.*\.//'))"
		getfacl -p "$n" 2>/dev/null | grep -E '^user:' || ls -l "$n"
	done
	echo "--- feeder"
	[ -f "$PIDFILE" ] && ps -o pid,etime,cmd -p "$(cat "$PIDFILE")" || echo "(not running)"
}

up() {
	[ -d "$G" ] && { echo "already up; run down first"; exit 1; }
	modprobe libcomposite
	modprobe dummy_hcd
	mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config

	mkdir "$G"
	echo 0x1532 > "$G/idVendor"
	echo 0x0b00 > "$G/idProduct"
	echo 0x0100 > "$G/bcdDevice"
	echo 0x0200 > "$G/bcdUSB"
	# Composite with IAD (needed for CDC ACM next to another function)
	echo 0xEF > "$G/bDeviceClass"
	echo 0x02 > "$G/bDeviceSubClass"
	echo 0x01 > "$G/bDeviceProtocol"
	mkdir "$G/strings/0x409"
	echo "Sensics (emulated)" > "$G/strings/0x409/manufacturer"
	printf '%s' "$PRODUCT" > "$G/strings/0x409/product"
	echo "EMU-HDK-0001" > "$G/strings/0x409/serialnumber"

	mkdir -p "$G/configs/c.1/strings/0x409"
	echo "HDK emulation" > "$G/configs/c.1/strings/0x409/configuration"
	echo 100 > "$G/configs/c.1/MaxPower"

	mkdir "$G/functions/acm.usb0"
	mkdir "$G/functions/hid.usb0"
	echo 0 > "$G/functions/hid.usb0/protocol"
	echo 0 > "$G/functions/hid.usb0/subclass"
	echo 32 > "$G/functions/hid.usb0/report_length"
	# Vendor page, one 32-byte input report, no report ID (byte 0 = version, as on the HDK)
	printf '\x06\x00\xff\x09\x01\xa1\x01\x09\x01\x15\x00\x26\xff\x00\x75\x08\x95\x20\x81\x02\xc0' \
		> "$G/functions/hid.usb0/report_desc"

	# Link order sets interface numbers: acm -> 0,1 ; hid -> 2
	ln -s "$G/functions/acm.usb0" "$G/configs/c.1/"
	ln -s "$G/functions/hid.usb0" "$G/configs/c.1/"

	udc=$(ls /sys/class/udc | grep -m1 dummy_udc)
	echo "$udc" > "$G/UDC"
	udevadm settle -t 5 || true
	sleep 1

	# Feed version-3 reports at 100 Hz: identity orientation (w = 1.0 in 1.14 fixed point), zero angular velocity.
	hidg=/dev/$(ls /sys/class/hidg 2>/dev/null | head -1)
	setsid python3 -I -c '
import os, sys, time
fd = os.open(sys.argv[1], os.O_WRONLY)
seq = 0
while True:
    rep = bytes([0x03, seq & 0xff, 0, 0, 0, 0, 0, 0, 0x00, 0x40]) + bytes(22)
    os.write(fd, rep)
    seq += 1
    time.sleep(0.01)
' "$hidg" > /dev/null 2>&1 < /dev/null &
	echo $! > "$PIDFILE"

	echo "up: product='$PRODUCT' on $udc, feeder pid $(cat "$PIDFILE") -> $hidg"
	status
}

case "${1:-}" in
up) up ;;
down) down ;;
status) status ;;
*) echo "usage: $0 up|down|status"; exit 1 ;;
esac
