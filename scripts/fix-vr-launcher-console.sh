#!/bin/bash
# fix-vr-launcher-console.sh -- one-shot deploy of the tty4 + $HOME crash fix
# for vr-launcher-console.service (found live 2026-08-09: the service
# crash-looped because it referenced $HOME under `set -u`, unset in a root
# systemd context with no login shell). Copies the corrected files in, reloads
# systemd, restarts the service, and prints its status so you can see
# immediately whether it's actually fixed.
#
#   sudo ./scripts/fix-vr-launcher-console.sh

set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Needs root. Run: sudo $0" >&2
    exit 1
fi

echo "=== copying the fixed .service (the .sh is already in place, ExecStart references it directly) ==="
cp "$HERE/vr-launcher-console.service" /etc/systemd/system/vr-launcher-console.service
chmod +x "$HERE/vr-launcher-console.sh"
echo "  ok."

echo
echo "=== daemon-reload + restart ==="
systemctl daemon-reload
systemctl restart vr-launcher-console.service
echo "  ok."

echo
echo "=== status (should say 'activating', waiting for ~/.vr-ready, NOT crash-looping) ==="
sleep 2
systemctl status vr-launcher-console.service --no-pager || true

echo
echo "=== if it still fails, this shows the real error ==="
journalctl -u vr-launcher-console.service --no-pager -n 10
