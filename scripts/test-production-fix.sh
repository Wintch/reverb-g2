#!/bin/bash
# test-production-fix.sh -- verifies the runuser+systemd-run--user--scope fix
# just applied to vr-launcher-console.sh actually resolves plugdev correctly
# in the real production path (not the bare-mutter test path), and cleans up
# the orphaned monado-service left by the earlier TimeoutExpired crash.
set -u
LOG=/tmp/test-production-fix.log
exec > >(tee "$LOG") 2>&1

echo "=== cleaning up any orphaned monado-service ==="
for p in $(pgrep -f "monado[-]service"); do kill -9 "$p"; done
rm -f /run/user/1000/monado_comp_ipc
sleep 1

echo
echo "=== restarting vr-launcher-console.service with the fixed script ==="
systemctl restart vr-launcher-console.service
sleep 1

echo
echo "=== writing simulated READY_FILE: mode=1 tracking=3dof CTRL_OK=0 GAMEPAD_OK=1 ==="
echo "1 3dof 0 1" > /run/vr-ready

echo
echo "=== waiting for jack-in-wayland.sh to run (up to 30s) ==="
for i in $(seq 1 30); do
    if grep -q "Sent activation report\|hidraw2" /home/iam/vr/jack-in-wayland.log 2>/dev/null; then
        break
    fi
    sleep 1
done

echo
echo "=== jack-in-wayland.log tail ==="
tail -30 /home/iam/vr/jack-in-wayland.log 2>/dev/null

echo
echo "=== did the HID open cleanly this time (no EACCES)? ==="
if grep -q "Failed to open device '/dev/hidraw2' got '-13'" /home/iam/vr/jack-in-wayland.log 2>/dev/null; then
    echo "  STILL BROKEN -- EACCES again"
else
    echo "  no EACCES this time"
fi
