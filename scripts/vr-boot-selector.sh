#!/bin/bash
# vr-boot-selector.sh -- runs on a bare text console (multi-user.target), before
# any desktop session exists. Two options, safe default:
#
#   [a] Auto     -- run power-on.py --pre-login now, in the console, no desktop
#                    running yet (the minimal-services path).
#   [m] Manual   -- (default, on timeout too) -- boots into the normal graphical
#                    login (SDDM), the classic path this whole project is built on.
#
# The timeout-defaults-to-manual behavior is load-bearing: if the auto path
# ever hangs or breaks, the machine still reaches a normal login screen on its
# own, unattended. Never remove that default.
#
# DRY RUN: this script is safe to run by hand in any terminal right now --
# it doesn't touch systemd targets unless you explicitly pick [a] and the
# diagnostic passes (power-on.py --pre-login does that part, see there).
# Nothing here is installed as a boot-time service yet; that's a separate,
# deliberate step (see the .service file next to this script).
#
#   ./scripts/vr-boot-selector.sh [timeout_seconds, default 10]

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT="${1:-10}"

echo "=================================================="
echo "  HP Reverb G2 -- selector de arranque"
echo "=================================================="
echo "  [a] Auto    -- diagnostico ahora mismo, en consola, sin escritorio"
echo "  [m] Manual  -- arranque normal (login grafico), como siempre"
echo
echo "  Sin elegir nada en ${TIMEOUT}s -> Manual (default seguro)."
echo

CHOICE=""
read -r -t "$TIMEOUT" -n 1 -p "Elegí [a/m]: " CHOICE || true
echo

case "$CHOICE" in
    a|A)
        echo "=== AUTO -- corriendo power-on.py --pre-login ==="
        # No 'exec' here on purpose: power-on.py already hands off to
        # graphical.target on both its success AND failure paths, but this
        # wrapper is the actual safety net if the script crashes before
        # reaching either -- recoverability shouldn't depend on power-on.py
        # behaving correctly.
        python3 "$HERE/power-on.py" --pre-login 1 3dof
        rc=$?
        echo
        echo "diagnostico termino (rc=$rc). Subiendo a login grafico en 3s..."
        sleep 3
        ;;
    *)
        echo "=== MANUAL (o timeout) -- arranque grafico normal ==="
        ;;
esac

exec systemctl isolate graphical.target
