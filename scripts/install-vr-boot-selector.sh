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
    echo "Needs root. Run: sudo $0" >&2
    exit 1
fi

echo "=== 1/4: syntax check before installing anything ==="
bash -n "$HERE/vr-boot-selector.sh"
python3 -m py_compile "$HERE/power-on.py"
echo "  ok."

echo
echo "=== 2/4: copying the service ==="
cp "$HERE/vr-boot-selector.service" /etc/systemd/system/vr-boot-selector.service
systemctl daemon-reload
echo "  ok."

echo
echo "=== 3/4: enabling the rescue console (tty2) BEFORE the selector (tty1) ==="
systemctl enable getty@tty2.service
echo "  ok. Ctrl+Alt+F2 will always give you a normal login, whatever happens on tty1."

echo
echo "=== 4/4: enabling the selector (tty1) ==="
systemctl enable vr-boot-selector.service
echo "  ok."

echo
echo "=== DONE ==="
echo "The default target is STILL graphical.target -- nothing changes yet in the"
echo "normal boot. To try the selector without committing to anything:"
echo
echo "  1. Try it by hand right now, without rebooting:"
echo "       sudo ./scripts/vr-boot-selector.sh"
echo
echo "  2. Real, reversible test on the next reboot (GRUB menu, press 'e',"
echo "     add 'systemd.unit=multi-user.target' to the 'linux' line, Ctrl+X):"
echo "       this boots ONCE in minimal mode -- a normal reboot without the edit"
echo "       puts everything back as it was; nothing persistent is touched."
echo
echo "  3. Only after step 2 has passed cleanly (success AND a simulated failure), the"
echo "     final real step is:"
echo "       sudo systemctl set-default multi-user.target"
echo "     this DOES change the default boot -- do it only once test 2 is already"
echo "     validated, and only when you really mean it."
echo
echo "To undo all of this:"
echo "  sudo systemctl disable vr-boot-selector.service getty@tty2.service"
echo "  sudo rm /etc/systemd/system/vr-boot-selector.service"
echo "  sudo systemctl daemon-reload"
