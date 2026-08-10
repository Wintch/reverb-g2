#!/bin/bash
set -u
LOG=/tmp/diag-subprocess-groups.log
exec > >(tee "$LOG") 2>&1

echo "=== is hidraw2 free right now? ==="
fuser -v /dev/hidraw2 2>&1 || echo "  (nobody has it open)"

echo
echo "=== cleanup any stale monado-service first ==="
for p in $(pgrep -f "monado[-]service"); do kill -9 "$p"; done
rm -f /run/user/1000/monado_comp_ipc
sleep 1

echo
echo "=== running jack-in-wayland.sh via python3 subprocess.run, EXACT same call vr-launcher.py makes ==="
runuser -u iam -- bash -c '
    export HOME=/home/iam USER=iam LOGNAME=iam
    export XDG_RUNTIME_DIR=/run/user/1000
    export WAYLAND_DISPLAY=wayland-0
    export XDG_SESSION_TYPE=wayland
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
    exec systemd-run --user --quiet --scope -- python3 -c "
import subprocess
r = subprocess.run([\"/home/iam/vr/jack-in-wayland.sh\", \"1\", \"3dof\"], capture_output=True, text=True, timeout=180)
print(\"returncode:\", r.returncode)
print(r.stdout)
print(\"STDERR:\", r.stderr)
"
'
