#!/bin/bash
# Captures what the NVIDIA driver says while it programs the display, in the TWO modes:
# the 60Hz one that works and the 90Hz one that doesn't. This is the report's central
# artifact.
#
#   sudo ./scripts/collect-nv.sh
#
# No one needs to look inside the headset: the physical results are already measured
# (chapter 04). This captures the driver side.
#
# Why this can be done without restarting anything: /sys/module/nvidia_modeset/parameters/debug
# is -rw------- , meaning root can write it LIVE. There is no need to reload the module or
# tear down the graphical session.
#
# The display test runs as the USER (it needs their Wayland session); only the log
# capture runs as root.

set -u

if [ "$(id -u)" -ne 0 ]; then
    echo "This needs root:  sudo $0" >&2
    exit 1
fi
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Figure out who owns the graphical session. SUDO_USER is empty if you started from a
# shell that was ALREADY root, so there are several fallbacks. Can be forced with HMD_USER=.
USER_NAME="${HMD_USER:-${SUDO_USER:-}}"
[ -z "$USER_NAME" ] && USER_NAME="$(logname 2>/dev/null || true)"
[ -z "$USER_NAME" ] && USER_NAME="$(stat -c %U "$REPO" 2>/dev/null || true)"
[ -z "$USER_NAME" ] && USER_NAME="$(loginctl list-sessions --no-legend 2>/dev/null | awk '$3!="root"{print $3; exit}')"
if [ -z "$USER_NAME" ] || [ "$USER_NAME" = "root" ]; then
    echo "Could not deduce the graphical session user." >&2
    echo "Run:  HMD_USER=your_user $0" >&2
    exit 1
fi
UID_N=$(id -u "$USER_NAME") || { echo "user '$USER_NAME' does not exist" >&2; exit 1; }
echo "session user: $USER_NAME (uid $UID_N)"
OUT="$REPO/nv-report-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "Artifacts -> $OUT"

DBG=/sys/module/nvidia_modeset/parameters/debug
PREV_DBG=$(cat "$DBG" 2>/dev/null || echo "?")
echo "nvidia_modeset debug: previous value = $PREV_DBG"

cleanup() {
    [ "$PREV_DBG" != "?" ] && echo "$PREV_DBG" > "$DBG" 2>/dev/null
    for p in $(pgrep -f "hmd[-]vk"); do kill "$p" 2>/dev/null; done
    for p in $(pgrep -f "dmesg -w"); do kill "$p" 2>/dev/null; done
}
trap cleanup EXIT

# --- build the repro, as the user ---
BUILD="$OUT/build"
mkdir -p "$BUILD"
chown -R "$USER_NAME" "$OUT"
XML=/usr/share/wayland-protocols/staging/drm-lease/drm-lease-v1.xml
sudo -u "$USER_NAME" wayland-scanner client-header "$XML" "$BUILD/drm-lease-v1-client-protocol.h" || exit 1
sudo -u "$USER_NAME" wayland-scanner private-code  "$XML" "$BUILD/drm-lease-v1-protocol.c" || exit 1
sudo -u "$USER_NAME" gcc -O2 -o "$BUILD/hmd-vk" "$REPO/scripts/hmd-vk.c" \
        "$BUILD/drm-lease-v1-protocol.c" -I"$BUILD" \
        $(pkg-config --cflags --libs wayland-client vulkan) || exit 1
echo "repro compiled: $BUILD/hmd-vk"

# --- system context ---
{
    echo "=== date ==="; date -Is
    echo; echo "=== kernel ==="; uname -a
    echo; echo "=== driver ==="; cat /proc/driver/nvidia/version
    echo; echo "=== session ==="
    echo "XDG_SESSION_TYPE(user)=$(sudo -u "$USER_NAME" printenv XDG_SESSION_TYPE 2>/dev/null)"
    echo "compositor: $(pgrep -a 'gnome-shell|kwin_wayland|sway' | head -1)"
    echo; echo "=== GPU ==="; nvidia-smi -q | head -40
    echo; echo "=== headset connector ==="
    for f in status enabled dpms modes; do
        echo "--- $f"; cat "/sys/class/drm/card0-DP-1/$f" 2>/dev/null
    done
    echo; echo "=== headset USB ==="; lsusb | grep -E "03f0:0580|045e:0659|04b4:650|0bda:4c15"
} > "$OUT/contexto.txt" 2>&1
cp /sys/class/drm/card0-DP-1/edid "$OUT/hmd.edid" 2>/dev/null
command -v edid-decode >/dev/null && edid-decode "$OUT/hmd.edid" > "$OUT/edid-decode.txt" 2>&1

run_mode() {   # $1 = Vulkan mode index, $2 = tag
    local idx="$1" tag="$2"
    echo
    echo "=== running mode $idx ($tag) ==="
    echo 1 > "$DBG" 2>/dev/null || echo "  (could not enable debug)"
    dmesg -w > "$OUT/dmesg-$tag.txt" 2>&1 &
    local DPID=$!
    sleep 1
    sudo -u "$USER_NAME" env \
        XDG_RUNTIME_DIR="/run/user/$UID_N" \
        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
        HMD_PANEL_CMD="$REPO/scripts/panel.py activate" \
        HMD_PANEL_ON_CMD="$REPO/scripts/panel.py on" \
        "$BUILD/hmd-vk" native "$idx" 25 > "$OUT/hmd-vk-$tag.log" 2>&1
    sleep 2
    kill "$DPID" 2>/dev/null
    echo 0 > "$DBG" 2>/dev/null
    echo "  fps: $(grep -oE '[0-9.]+ fps presented' "$OUT/hmd-vk-$tag.log" | tail -1)"
    echo "  dmesg lines captured: $(wc -l < "$OUT/dmesg-$tag.txt")"
}

# CONTROL runs first and the failure after, so that any difference in the log cannot be
# attributed to the setup degrading with use.
run_mode 2 "60hz-CONTROL-works"
sleep 3
run_mode 0 "90hz-2880x1440-FAILS"
sleep 3
run_mode 1 "90hz-4320x2160-FAILS"

# --- the artifact NVIDIA always asks for ---
echo
echo "=== nvidia-bug-report.sh (takes a while) ==="
( cd "$OUT" && nvidia-bug-report.sh --output-file "$OUT/nvidia-bug-report" >/dev/null 2>&1 )
ls -la "$OUT" | sed 's/^/  /'

chown -R "$USER_NAME" "$OUT"
echo
echo "DONE. Everything in: $OUT"
echo "What matters: diff dmesg-60hz-CONTROL-works.txt against dmesg-90hz-*-FAILS.txt"
