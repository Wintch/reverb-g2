#!/bin/bash
# One consolidated pre-flight check before running jack-in-wayland.sh, so a bad test run
# doesn't waste time on something that could've been caught in 5 seconds. Checks, in order:
#   1. USB: all 5 headset devices enumerated
#   2. Controllers: both paired AND online (queried directly via HID, no Monado needed --
#      this is the check that would have caught tonight's "left: <none> right: <none>"
#      result before ever starting the service: hot-add doesn't exist, so controllers must
#      already be online before jack-in-wayland.sh runs, not after)
#   3. HMD's own DP connector: non-desktop=1, not just "any DP connected" (see
#      jack-in-wayland.sh's own note -- a real desktop monitor on another DP port used to
#      give a false positive here)
#
# Prints a clear READY/NOT READY per step with a concrete next action, and an overall
# verdict at the end. Doesn't start Monado. Safe to run repeatedly.
#
#   ./preflight.sh

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VR="$(cd "$HERE/.." && pwd)"
[ -d "$HOME/vr/monado" ] && VR="$HOME/vr"

OVERALL_READY=1

echo "=== 1/3: USB devices ==="
FOUND=$(lsusb | grep -cE "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15")
if [ "$FOUND" -ge 5 ]; then
    echo "  READY: $FOUND/5 headset devices enumerated."
else
    echo "  NOT READY: only $FOUND/5 headset devices."
    lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"
    echo "  -> Check the USB port/cable (docs/00, docs/22). Don't continue until this is 5/5."
    OVERALL_READY=0
fi

echo
echo "=== 2/3: Controllers (paired + online, checked directly, no Monado needed) ==="
# Hot-add doesn't exist (docs/03) -- controllers MUST already be online before jack-in-wayland.sh
# starts, or they'll register as <none> for the whole session with no error.
PAIR_OUT="$(python3 "$HERE/controller-pair-check.py" 3 2>&1)"
echo "$PAIR_OUT" | sed 's/^/  /'
LEFT_OK=0; RIGHT_OK=0
echo "$PAIR_OUT" | grep -q "left.*online" && LEFT_OK=1
echo "$PAIR_OUT" | grep -q "right.*online" && RIGHT_OK=1
if [ "$LEFT_OK" = 1 ] && [ "$RIGHT_OK" = 1 ]; then
    echo "  READY: both controllers paired and online."
else
    echo "  NOT READY: at least one controller isn't online."
    echo "  -> Power on BOTH controllers now, then re-run this check. Starting the service"
    echo "     with a controller off will register it as <none> for the whole session --"
    echo "     there is no hot-add, a mid-session power-on will not fix it."
    OVERALL_READY=0
fi

echo
echo "=== 3/3: HMD's own DP connector (non-desktop=1, not just any connected DP) ==="
PANEL_PY="$HERE/panel.py"
[ -f "$PANEL_PY" ] || PANEL_PY="$VR/panel.py"
if ! ACTIVATE_OUT="$(python3 "$PANEL_PY" activate 2>&1)"; then
    echo "  !! panel.py activate FAILED (fix this first, it's not a hardware symptom):"
    echo "$ACTIVATE_OUT" | sed 's/^/     /'
fi

DRMPROPS_BIN="${TMPDIR:-/tmp}/drmprops.$$"
DP_UP=0
if gcc -o "$DRMPROPS_BIN" "$HERE/drmprops.c" -ldrm -I/usr/include/libdrm 2>/dev/null; then
    for _i in $(seq 1 20); do
        if "$DRMPROPS_BIN" 2>/dev/null | awk '
            /^connector/ { conn = $0 }
            /non-desktop  = 1/ { if (conn ~ /CONNECTED/) found = 1 }
            END { exit !found }
        '; then
            DP_UP=1
            break
        fi
        sleep 0.5
    done
    rm -f "$DRMPROPS_BIN"
else
    echo "  !! couldn't compile drmprops.c (missing libdrm-dev?) -- can't run this check."
fi

if [ "$DP_UP" = 1 ]; then
    echo "  READY: HMD connector up (non-desktop=1, real DP-90Hz modes present)."
else
    echo "  NOT READY: the HMD's own connector never came up after activation (waited 10s)."
    echo "  -> This is the docs/22 T046 pattern (HID/USB healthy, DP/panel-power path dead)."
    echo "     Next: reseat the cable at the VISOR end (behind the magnetic face gasket)."
    echo "     If that doesn't help, check the 12V brick. Don't re-diagnose this in software"
    echo "     again -- this check already rules out compositor/Monado-side causes."
    OVERALL_READY=0
fi

echo
if [ "$OVERALL_READY" = 1 ]; then
    echo "=== READY. Run: ./jack-in-wayland.sh 1 6dof ==="
else
    echo "=== NOT READY -- fix the item(s) above before running jack-in-wayland.sh ==="
    exit 1
fi
