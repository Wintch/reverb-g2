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
    echo "  -> USB gate failed; skipping controller HID and DP checks."
    exit 1
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
echo "=== 3/3: HMD's own DP connector (real G2 EDID fingerprint + non-desktop=1, not just 'connected') ==="
echo "  Note: the HP logo lighting is a separate power+HID signal (panel.py's activation"
echo "  handshake) and is NOT checked here -- it can light with the panel/DP still dead."
echo "  This step reads the actual DRM connector state, which is what really matters."
PANEL_PY="$HERE/panel.py"
[ -f "$PANEL_PY" ] || PANEL_PY="$VR/panel.py"
if ! ACTIVATE_OUT="$(python3 "$PANEL_PY" activate 2>&1)"; then
    echo "  !! panel.py activate FAILED (fix this first, it's not a hardware symptom):"
    echo "$ACTIVATE_OUT" | sed 's/^/     /'
fi
if echo "$ACTIVATE_OUT" | grep -qE "OSError|Errno"; then
    echo "  !! companion control-channel read errors during activation (docs/22 storm pattern):"
    echo "$ACTIVATE_OUT" | grep -E "OSError|Errno" | sed 's/^/     /'
fi

DRMPROPS_BIN="${TMPDIR:-/tmp}/drmprops.$$"
DP_STATE=none   # none | connected-fake-edid | ready
LAST_DUMP=""
if gcc -o "$DRMPROPS_BIN" "$HERE/drmprops.c" -ldrm -I/usr/include/libdrm 2>/dev/null; then
    for _i in $(seq 1 20); do
        LAST_DUMP="$("$DRMPROPS_BIN" 2>/dev/null)"
        # Identify the visor's connector by its EDID FINGERPRINT (drmprops.c checks it
        # against a known-good G2 capture), not by byte count or connector id -- those
        # aren't stable across boots and, worse, a plain 128-byte base-block EDID is
        # completely normal on this rig's real desktop monitors too (verified live: it
        # is NOT a truncation signal by itself). A connector with no real G2 EDID but a
        # single 640x480@60 fallback mode is the kernel's synthetic "sink present,
        # nothing readable" default -- CONNECTED electrically, but no real panel identity.
        STATE="$(echo "$LAST_DUMP" | awk '
            /^connector/ {
                conn = $0; nd = ""; is_g2 = 0; first_mode = ""
                split($0, parts, "modes="); modes = parts[2] + 0
            }
            /non-desktop  = / { nd = $NF }
            /fingerprint matches the G2 panel/ { is_g2 = 1 }
            /mode:/ {
                if (first_mode == "") first_mode = $2
                if (conn ~ /CONNECTED/) {
                    rank = 0; label = "none"
                    if (is_g2 && nd == "1" && modes > 1)               { rank = 3; label = "ready" }
                    else if (is_g2 || (modes == 1 && first_mode == "640x480@60")) {
                        rank = 1; label = "connected-fake-edid"
                    }
                    if (rank > best) { best = rank; beststr = label }
                }
            }
            END { print (beststr == "" ? "none" : beststr) }
        ')"
        [ -n "$STATE" ] && DP_STATE="$STATE"
        [ "$DP_STATE" = "ready" ] && break
        sleep 0.5
    done
    rm -f "$DRMPROPS_BIN"
else
    echo "  !! couldn't compile drmprops.c (missing libdrm-dev?) -- can't run this check."
fi

case "$DP_STATE" in
    ready)
        echo "  READY: HMD connector up -- EDID fingerprint confirmed the G2, non-desktop=1, real modes."
        ;;
    connected-fake-edid)
        echo "  NOT READY: a connector is electrically CONNECTED where the visor should be, but its"
        echo "  EDID does NOT match the G2's real fingerprint -- it's a synthetic placeholder the"
        echo "  kernel falls back to when the AUX channel never returns real panel data (confirmed"
        echo "  by hex-dumping it: all zero bytes past the mandatory EDID header). This means the"
        echo "  DP link sees SOME sink present but never gets the panel's actual identity -- this is"
        echo "  functionally the same physical-layer failure as a full disconnect, NOT partial"
        echo "  progress. Don't read it as 'closer to working.'"
        echo "  -> Same as always (docs/22): reseat the cable at the VISOR end next. If that doesn't"
        echo "     help, check the 18.5 V brick."
        echo "$LAST_DUMP" | sed 's/^/     /'
        OVERALL_READY=0
        ;;
    none)
        echo "  NOT READY: the HMD's own connector never came up after activation (waited 10s)."
        echo "  -> This is the docs/22 T046 pattern (HID/USB healthy, DP/panel-power path dead)."
        echo "     Next: reseat the cable at the VISOR end (behind the magnetic face gasket)."
        echo "     If that doesn't help, check the 18.5 V brick. Don't re-diagnose this in software"
        echo "     again -- this check already rules out compositor/Monado-side causes."
        OVERALL_READY=0
        ;;
esac

echo
if [ "$OVERALL_READY" = 1 ]; then
    echo "=== READY. Run: ./jack-in-wayland.sh 1 6dof ==="
else
    echo "=== NOT READY -- fix the item(s) above before running jack-in-wayland.sh ==="
    exit 1
fi
