#!/bin/bash
# A debug=1, nvidia-modeset sólo loguea attach/detach y no dice nada de link rate, lane
# count ni DSC. Este script barre valores más altos del parámetro y reporta cuál produce
# más información, para después capturar con el mejor.
#
#   sudo ./scripts/nv-debug-more.sh
#
# Seguro: el parámetro se escribe EN CALIENTE (es -rw-------) y se restaura con trap EXIT.
# No recarga módulos ni toca la sesión gráfica.

set -u
[ "$(id -u)" -eq 0 ] || { echo "necesita root: sudo $0" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${HMD_USER:-${SUDO_USER:-}}"
[ -z "$USER_NAME" ] && USER_NAME="$(logname 2>/dev/null || true)"
[ -z "$USER_NAME" ] && USER_NAME="$(stat -c %U "$REPO")"
UID_N=$(id -u "$USER_NAME")
echo "usuario de la sesion: $USER_NAME"

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
[ -x "$BIN" ] || { echo "no encuentro hmd-vk compilado; corre collect-nv.sh primero" >&2; exit 1; }
echo "repro: $BIN"

# El modo 0 es 2880x1440@90: el que falla y el que menos ancho de banda pide.
try_level() {
    local lvl="$1"
    if ! echo "$lvl" > "$DBG" 2>/dev/null; then
        echo "  debug=$lvl : RECHAZADO por el modulo"
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
    echo "  debug=$lvl (quedo en $got) : $n lineas de nvidia"
}

echo
echo "=== barriendo niveles de verbosidad (modo 0 = 2880x1440@90, el que falla) ==="
for lvl in 1 2 3 4 5 7 15 31 255; do
    try_level "$lvl"
done

echo
echo "=== el mas verboso encontrado ==="
BEST=$(for f in "$OUT"/lvl*.txt; do echo "$(grep -c nvidia "$f" 2>/dev/null || echo 0) $f"; done | sort -rn | head -1)
echo "  $BEST"
BESTF=${BEST#* }
echo
echo "=== muestra de lo que loguea ==="
grep "nvidia" "$BESTF" 2>/dev/null | tail -40

echo
echo "artefactos en: $OUT"
