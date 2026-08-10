#!/bin/bash
# test-gamepad-fallback.sh -- live test of the 2026-08-10 gamepad-fallback fix:
# no VR controllers but a gamepad present should still auto-launch the tty4
# picker, instead of falling back to a plain desktop/console.
set -eu
LOG=/tmp/test-gamepad-fallback.log
exec > >(tee "$LOG") 2>&1

echo "=== gamepad present? ==="
lsusb | grep -i "045e:028e" || { echo "No gamepad detected -- plug it in first."; exit 1; }

echo
echo "=== restarting vr-launcher-console.service with the updated script ==="
systemctl restart vr-launcher-console.service
sleep 1
systemctl status vr-launcher-console.service --no-pager | head -8

echo
echo "=== writing a simulated READY_FILE: mode=1 tracking=3dof CTRL_OK=0 GAMEPAD_OK=1 ==="
echo "1 3dof 0 1" > /run/vr-ready

echo
echo "=== waiting a few seconds for the service to pick it up ==="
sleep 5

echo
echo "=== did vr-launcher.py actually get launched? (StandardOutput=tty hides this from journalctl) ==="
pgrep -af "vr-launcher.py" || echo "  NOT running -- fell back to plain console (fix did not take effect)"

echo
echo "=== is it a plain agetty instead (meaning it fell back)? ==="
ps aux | grep "agetty tty4" | grep -v grep || echo "  no plain agetty on tty4 (good sign, consistent with launching)"
