#!/bin/bash
# Verifies that nvidia_modeset.config_file loaded the expected EDID. Gathers into a single script
# everything this experiment needs to read with privileges (restricted dmesg, and the EDID
# from sysfs that in this driver only root can read) so as not to keep asking for the
# password one command at a time.
#
#   sudo ./scripts/verify-override.sh                 (compares against what the active .conf says)
#   sudo ./scripts/verify-override.sh file.edid        (compares against a specific file)
#
# What it does:
#   1. dmesg: confirms "Successfully read ..." and that there's no "Error in"/"Syntax error"
#   2. forces a fresh detect() of the connector (cat status) before reading the EDID
#   3. compares md5 of the active EDID in sysfs against the expected file
#
# EXPECTATION: all three steps are read-only, they don't touch anything. No reboot is needed to
# run it, but for step 3 to change you need to have rebooted with the new .conf
# (nvkms-dpy-override.c: DpyOverrideReadEdid only reads the file once, when the module loads).

set -u

[ "$(id -u)" -eq 0 ] || { echo "needs root: sudo $0" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$REPO/experiments/vblank/nvkms-override-candidates.conf"
CONNECTOR="/sys/class/drm/card0-DP-1"

EXPECTED="${1:-}"
if [ -z "$EXPECTED" ]; then
    EXPECTED="$(grep -oP '(?<= = )\S+\.edid' "$CONF" | tail -1)"
    [ -n "$EXPECTED" ] || { echo "can't find a line 'override....edid' in $CONF" >&2; exit 1; }
fi
[ -f "$EXPECTED" ] || { echo "doesn't exist: $EXPECTED" >&2; exit 1; }

echo "=== expected (per ${1:+arg}${1:-the .conf}) ==="
echo "  $EXPECTED"

echo
echo "=== dmesg: config_file load ==="
LOAD_LINES="$(dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read')"
if [ -z "$LOAD_LINES" ]; then
    echo "  (nothing -- the dmesg buffer may have rotated since boot)"
else
    echo "$LOAD_LINES" | sed 's/^/  /'
fi
if echo "$LOAD_LINES" | grep -qiE 'error in|syntax error'; then
    echo "  !! there's a parse error -- the ENTIRE .conf was discarded, not just the bad line"
fi

echo
echo "=== forcing a fresh detect() on $CONNECTOR ==="
cat "$CONNECTOR/status"

echo
echo "=== active vs expected EDID ==="
ACTUAL_MD5="$(cat "$CONNECTOR/edid" | md5sum | cut -d' ' -f1)"
EXPECTED_MD5="$(md5sum "$EXPECTED" | cut -d' ' -f1)"
echo "  active:    $ACTUAL_MD5"
echo "  expected:  $EXPECTED_MD5"
if [ "$ACTUAL_MD5" = "$EXPECTED_MD5" ]; then
    echo "  OK -- they match, the override is loaded"
    exit 0
else
    echo "  !! they DON'T match -- either the reboot is missing, or the override didn't match (see docs/16)"
    exit 1
fi
