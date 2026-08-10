#!/bin/bash
set -u
LOG=/tmp/diag-production-chain.log
exec > >(tee "$LOG") 2>&1

echo "=== exact production chain: runuser -> bash -c -> systemd-run --user --scope -> id ==="
runuser -u iam -- bash -c '
    export HOME=/home/iam USER=iam LOGNAME=iam
    export XDG_RUNTIME_DIR=/run/user/1000
    export WAYLAND_DISPLAY=wayland-0
    export XDG_SESSION_TYPE=wayland
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
    exec systemd-run --user --quiet --scope -- id
'

echo
echo "=== can that read+write hidraw2 (RDWR, real test not just read)? ==="
runuser -u iam -- bash -c '
    export XDG_RUNTIME_DIR=/run/user/1000
    exec systemd-run --user --quiet --scope -- python3 -c "import os; f=os.open(\"/dev/hidraw2\", os.O_RDWR); os.close(f); print(\"RDWR open OK\")"
'
