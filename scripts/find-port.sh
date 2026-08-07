#!/usr/bin/env bash
# find-port.sh — identifies which xHCI controller each physical port belongs to.
#
# Usage: run it and PLUG/UNPLUG any USB device (thumb drive, Logitech receiver,
# mouse) into the case's ports, one at a time. Every time something new appears
# it prints the bus and the PCI controller.
#
# We're looking for a port that reports  ctrl=0000:02:00.0  (A520 chipset).
# The root SSD is NOT touched hot: first the port is found with this
# script, then the machine is powered off and the cable is moved.
#
# Ctrl-C to exit.

snapshot() {
  for d in /sys/bus/usb/devices/[0-9]*-[0-9]*; do
    [ -f "$d/idVendor" ] || continue
    echo "$(basename "$d")"
  done | sort
}

describe() {
  local d="/sys/bus/usb/devices/$1"
  local ctrl
  ctrl=$(readlink -f "$d" | grep -o '0000:[0-9a-f]*:[0-9a-f]*\.[0-9a-f]*' | tail -1)
  printf '  %-10s %s:%s  %-6s speed=%sM  ctrl=%s' \
    "$1" "$(cat "$d/idVendor")" "$(cat "$d/idProduct")" \
    "$(cat "$d/version" 2>/dev/null | tr -d ' ')" \
    "$(cat "$d/speed" 2>/dev/null)" "$ctrl"
  if [ "$ctrl" = "0000:02:00.0" ]; then
    printf '   <<< THIS PORT WORKS\n'
  else
    printf '   (same xHCI as the headset, does NOT work)\n'
  fi
}

echo "Watching USB. Plug/unplug a test device into each port."
echo "Goal: ctrl=0000:02:00.0 . Ctrl-C to exit."
echo
prev=$(snapshot)
while true; do
  sleep 1
  cur=$(snapshot)
  if [ "$cur" != "$prev" ]; then
    while read -r dev; do
      [ -n "$dev" ] && { echo "[+] connected:"; describe "$dev"; }
    done < <(comm -13 <(echo "$prev") <(echo "$cur"))
    while read -r dev; do
      [ -n "$dev" ] && echo "[-] disconnected: $dev"
    done < <(comm -23 <(echo "$prev") <(echo "$cur"))
    prev="$cur"
  fi
done
