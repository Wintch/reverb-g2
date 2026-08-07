#!/bin/bash
# At debug=1, nvidia-modeset only logs attach/detach and says nothing about link rate,
# lane count, or DSC. This script sweeps higher values of the parameter and reports which
# one produces the most information, so it can be captured with the best one afterward.
#
#   sudo ./scripts/nv-debug-more.sh
#
# Safe: the parameter is written LIVE (it's -rw-------) and restored via trap EXIT.
# It does not reload modules or touch the graphical session.

set -u
[ "$(id -u)" -eq 0 ] || { echo "needs root: sudo $0" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${HMD_USER:-${SUDO_USER:-}}"
[ -z "$USER_NAME" ] && USER_NAME="$(logname 2>/dev/null || true)"
[ -z "$USER_NAME" ] && USER_NAME="$(stat -c %U "$REPO")"
UID_N=$(id -u "$USER_NAME")
echo "session user: $USER_NAME"

DBG=/sys/module/nvidia_modeset/parameters/debug
PREV=$(cat "$DBG")
OUT="$REPO/nv-debug-$(date +%H%M%S)"
mkdir -p "$OUT"

cleanup() {
    echo "$PREV" > "$DBG" 2>/dev/null
    for p in $(pgrep -f "hmd[-]vk"); do kill "$p" 2>/dev/null; done
    for p in $(pgrep -f "dmesg -w"); do kill "$p" 2>/dev/null; done
    chown -R "$USER_NAME" "$OUT" 2>/dev/null
}
trap cleanup EXIT

BIN=$(ls -t "$REPO"/nv-report-*/build/hmd-vk 2>/dev/null | head -1)
[ -x "$BIN" ] || { echo "can't find compiled hmd-vk; run collect-nv.sh first" >&2; exit 1; }
echo "repro: $BIN"

# Mode 0 is 2880x1440@90: the one that fails and requires the least bandwidth.
try_level() {
    local lvl="$1"
    if ! echo "$lvl" > "$DBG" 2>/dev/null; then
        echo "  debug=$lvl : REJECTED by the module"
        return
    fi
    local got
    got=$(cat "$DBG")
    dmesg -C 2>/dev/null
    dmesg -w > "$OUT/lvl$lvl.txt" 2>&1 &
    local D=$!
    sleep 1
    sudo -u "$USER_NAME" env XDG_RUNTIME_DIR="/run/user/$UID_N" \
        WAYLAND_DISPLAY=wayland-0 \
        HMD_PANEL_CMD="$REPO/scripts/panel.py activate" \
        HMD_PANEL_ON_CMD="$REPO/scripts/panel.py on" \
        "$BIN" native 0 10 >/dev/null 2>&1
    sleep 1
    kill "$D" 2>/dev/null
    local n
    n=$(grep -c "nvidia" "$OUT/lvl$lvl.txt" 2>/dev/null || echo 0)
    echo "  debug=$lvl (stayed at $got) : $n nvidia lines"
}

echo
echo "=== sweeping verbosity levels (mode 0 = 2880x1440@90, the one that fails) ==="
for lvl in 1 2 3 4 5 7 15 31 255; do
    try_level "$lvl"
done

echo
echo "=== most verbose one found ==="
BEST=$(for f in "$OUT"/lvl*.txt; do echo "$(grep -c nvidia "$f" 2>/dev/null || echo 0) $f"; done | sort -rn | head -1)
echo "  $BEST"
BESTF=${BEST#* }
echo
echo "=== sample of what it logs ==="
grep "nvidia" "$BESTF" 2>/dev/null | tail -40

echo
echo "artifacts in: $OUT"
