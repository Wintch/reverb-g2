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

echo "=== 1/3: chequeo de sintaxis antes de instalar nada ==="
python3 -m py_compile "$HERE/pmadminka-agent.py" "$HERE/wmr_usb_ids.py" "$HERE/gui_env.py"
echo "  ok."

echo
echo "=== 2/3: config ==="
if [ ! -f "$CONFIG" ]; then
    echo "  Falta $CONFIG -- necesario antes de instalar el service."
    echo "  Creá el directorio y el archivo con la URL real del hub, por ejemplo:"
    echo
    echo "    mkdir -p \"$(dirname "$CONFIG")\""
    echo "    cat > \"$CONFIG\" <<'EOF'"
    echo '    {"server": "http://<hub-host>:8000"}'
    echo "    EOF"
    echo
    echo "  Corré este instalador de nuevo despues de eso."
    exit 1
fi
echo "  ok, existe $CONFIG:"
cat "$CONFIG"

echo
echo "=== 3/3: instalando el service (systemd --user) ==="
mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/pmadminka-agent.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
echo "  ok, copiado y recargado. NO habilitado todavia."

echo
echo "=== LISTO -- nada corriendo aun ==="
echo "Para probarlo a mano primero (recomendado, así ves los logs en vivo):"
echo "  python3 $HERE/pmadminka-agent.py"
echo
echo "Para instalarlo de verdad (arranca ahora Y en cada login gráfico):"
echo "  systemctl --user enable --now pmadminka-agent.service"
echo
echo "Para ver logs despues de habilitarlo:"
echo "  journalctl --user -u pmadminka-agent.service -f"
echo
echo "Para deshacer todo:"
echo "  systemctl --user disable --now pmadminka-agent.service"
echo "  rm ~/.config/systemd/user/pmadminka-agent.service"
echo "  systemctl --user daemon-reload"
