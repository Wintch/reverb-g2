#!/bin/bash
# install-vr-boot-selector.sh -- Stage 2 of the boot-selector plan (docs/pruebas.jsonl,
# plan: boot selector + standby + voice-guided diagnostics), all in one run.
#
# Does NOT change the default boot target (systemctl set-default) -- that's Stage 4,
# a separate, bigger, explicit-confirmation-required step. This script only installs
# the selector service and its tty1/tty2 wiring so it's ready to test.
#
#   sudo ./scripts/install-vr-boot-selector.sh

set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Necesita root. Corré: sudo $0" >&2
    exit 1
fi

echo "=== 1/4: chequeo de sintaxis antes de instalar nada ==="
bash -n "$HERE/vr-boot-selector.sh"
python3 -m py_compile "$HERE/power-on.py"
echo "  ok."

echo
echo "=== 2/4: copiando el service ==="
cp "$HERE/vr-boot-selector.service" /etc/systemd/system/vr-boot-selector.service
systemctl daemon-reload
echo "  ok."

echo
echo "=== 3/4: habilitando la consola de rescate (tty2) ANTES que el selector (tty1) ==="
systemctl enable getty@tty2.service
echo "  ok. Ctrl+Alt+F2 siempre te va a dar un login normal, pase lo que pase en tty1."

echo
echo "=== 4/4: habilitando el selector (tty1) ==="
systemctl enable vr-boot-selector.service
echo "  ok."

echo
echo "=== LISTO ==="
echo "El target por defecto SIGUE siendo graphical.target -- nada cambia todavia en el"
echo "arranque normal. Para probar el selector sin comprometerte a nada:"
echo
echo "  1. Probalo a mano ahora mismo, sin reiniciar:"
echo "       sudo ./scripts/vr-boot-selector.sh"
echo
echo "  2. Prueba real, reversible, en el proximo reinicio (menu de GRUB, tecla 'e',"
echo "     agregar 'systemd.unit=multi-user.target' a la linea 'linux', Ctrl+X):"
echo "       eso arranca UNA vez en modo minimo -- un reinicio normal sin la edicion"
echo "       vuelve todo como estaba, no toca nada persistente."
echo
echo "  3. Recien despues de probar el paso 2 limpio (exito Y fallo simulado), el"
echo "     ultimo paso real es:"
echo "       sudo systemctl set-default multi-user.target"
echo "     eso SI cambia el arranque por defecto -- hacelo solo con la prueba 2 ya"
echo "     validada, y solo cuando quieras de verdad."
echo
echo "Para deshacer todo esto:"
echo "  sudo systemctl disable vr-boot-selector.service getty@tty2.service"
echo "  sudo rm /etc/systemd/system/vr-boot-selector.service"
echo "  sudo systemctl daemon-reload"
