#!/bin/bash
# vr-boot-selector.sh -- runs on a bare text console (multi-user.target), before
# any desktop session exists. Two options, DEFAULT IS NOW AUTO (changed
# 2026-08-09 after T129/T130 validated live, with real failing hardware, that
# the diagnostic hands off to graphical.target no matter what happens --
# success or failure -- so every unattended boot doubles as a live health
# check instead of silently skipping straight to login):
#
#   [a] Auto     -- (default, on timeout too) -- run power-on.py --pre-login
#                    now, in the console, no desktop running yet.
#   [m] Manual   -- skip the diagnostic, boot straight into the normal
#                    graphical login (SDDM).
#
# Hard ceiling below (coreutils `timeout`) is the actual safety net now that
# auto is unattended-default: power-on.py's own per-call timeouts (run()'s
# default 10s) bound individual subprocess calls, but there was never an
# overall ceiling on the whole diagnostic -- this adds one, so a stuck
# console still can't happen even if some future change breaks that
# per-call bounding.
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
    m|M)
        echo "=== MANUAL -- arranque grafico normal ==="
        ;;
    *)
        echo "=== AUTO (default, o timeout) -- corriendo power-on.py --pre-login ==="
        # No 'exec' here on purpose: power-on.py already hands off to
        # graphical.target on both its success AND failure paths, but this
        # wrapper is the actual safety net if the script crashes before
        # reaching either -- recoverability shouldn't depend on power-on.py
        # behaving correctly. `timeout` (coreutils) is the hard ceiling on
        # top of that -- 120s is generous (T129/T130's real runs took
        # 10-38s) but guarantees this console can never hang indefinitely.
        timeout 120 python3 "$HERE/power-on.py" --pre-login 1 3dof
        rc=$?
        echo
        if [ "$rc" -eq 124 ]; then
            echo "diagnostico se colgo (timeout de 120s, rc=124) -- forzado a login grafico."
        else
            echo "diagnostico termino (rc=$rc). Subiendo a login grafico en 3s..."
        fi
        sleep 3
        ;;
esac

exec systemctl isolate graphical.target
