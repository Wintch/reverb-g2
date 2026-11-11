#!/bin/bash
# Answers ONE question, without starting Monado: does the Wayland compositor offer the
# headset's connector for DRM lease? That's what discriminates whether the culprit is the
# compositor (KWin offered none) or the NVIDIA driver.
#
# Run INSIDE the Wayland session, as a regular user.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== session ==="
echo "  XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset}   XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-unset}"
if [ "${XDG_SESSION_TYPE:-}" != "wayland" ]; then
    echo "  !! This needs a Wayland session. Log out and pick 'GNOME on Wayland'"
    echo "     in SDDM (watch out: there are TWO entries called 'GNOME', one is X11)."
    exit 1
fi

echo
echo "=== kernel/NVIDIA side: non-desktop connector ==="
# Patch 0002 marks the headset's connector as non-desktop=1 and exposes the 3 modes.
BIN="${TMPDIR:-/tmp}/drmprops.$$"
if gcc -o "$BIN" "$HERE/drmprops.c" -ldrm -I/usr/include/libdrm 2>/dev/null; then
    "$BIN" | awk '/^connector/{c=$0; nd=""} /non-desktop  = 1/{print c; nd=1} nd&&/mode:/{print}'
    rm -f "$BIN"
else
    echo "  (couldn't compile drmprops.c -- missing libdrm-dev?)"
fi

echo
echo "=== compositor side: does it publish the DRM lease global? ==="
if ! command -v wayland-info >/dev/null; then
    echo "  wayland-info is not installed (apt install wayland-utils)"; exit 1
fi
INFO="$(wayland-info 2>/dev/null)"
if echo "$INFO" | grep -q wp_drm_lease_device_v1; then
    echo "  YES: $(echo "$INFO" | grep -m1 wp_drm_lease_device_v1 | sed 's/^ *//')"
else
    echo "  NO -- the compositor doesn't even announce wp_drm_lease_device_v1."
    echo "     Without that there's no possible lease; no point running jack-in-wayland.sh."
    exit 2
fi

echo
echo "=== how many connectors does it offer on that device? ==="
# KWin 6.3.6 announced the device and offered ZERO connectors: that was the exact symptom.
# NOTE: wayland-info prints "connector:" bare, with no space or id on the same line.
# Counting "connector: " (with a space) always gives 0 and turns a success into a false failure.
BLOCK="$(echo "$INFO" | sed -n '/wp_drm_lease_device_v1/,/^interface/p')"
N=$(echo "$BLOCK" | grep -cE '^[[:space:]]*connector:[[:space:]]*$' || true)
echo "$BLOCK" | head -30
echo
if [ "$N" -gt 0 ]; then
    echo "  --> Offers connectors. Continue with: ./jack-in-wayland.sh 1"
else
    echo "  --> ZERO connectors, same as KWin. If unpatched mutter doesn't offer any either,"
    echo "      the culprit isn't the compositor: it's NVIDIA."
fi
