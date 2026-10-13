#!/bin/bash
# install-pmadminka-agent.sh -- installs the pmadminka reservation-hub agent as a
# systemd --user service. Nothing auto-applies: run this by hand when ready.
#
#   ./scripts/install-pmadminka-agent.sh
#
# No sudo needed -- this is a --user unit, same as status-dashboard.service.

set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HOME/.config/pmadminka-agent/config.json"

echo "=== 1/3: syntax check before installing anything ==="
python3 -m py_compile "$HERE/pmadminka-agent.py" "$HERE/wmr_usb_ids.py" "$HERE/gui_env.py"
echo "  ok."

echo
echo "=== 2/3: config ==="
if [ ! -f "$CONFIG" ]; then
    echo "  Missing $CONFIG -- required before installing the service."
    echo "  Create the directory and the file with the real hub URL, for example:"
    echo
    echo "    mkdir -p \"$(dirname "$CONFIG")\""
    echo "    cat > \"$CONFIG\" <<'EOF'"
    echo '    {"server": "http://<hub-host>:8000"}'
    echo "    EOF"
    echo
    echo "  Run this installer again after that."
    exit 1
fi
echo "  ok, $CONFIG exists:"
cat "$CONFIG"

echo
echo "=== 3/3: installing the service (systemd --user) ==="
mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/pmadminka-agent.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
echo "  ok, copied and reloaded. NOT enabled yet."

echo
echo "=== DONE -- nothing running yet ==="
echo "To try it by hand first (recommended, so you see the logs live):"
echo "  python3 $HERE/pmadminka-agent.py"
echo
echo "To really install it (starts now AND on every graphical login):"
echo "  systemctl --user enable --now pmadminka-agent.service"
echo
echo "To view logs after enabling it:"
echo "  journalctl --user -u pmadminka-agent.service -f"
echo
echo "To undo everything:"
echo "  systemctl --user disable --now pmadminka-agent.service"
echo "  rm ~/.config/systemd/user/pmadminka-agent.service"
echo "  systemctl --user daemon-reload"
