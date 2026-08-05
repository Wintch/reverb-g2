#!/bin/bash
# Captura lo que el driver NVIDIA dice mientras programa el display, en los DOS modos:
# el de 60Hz que funciona y el de 90Hz que no. Es el artefacto central del reporte.
#
#   sudo ./scripts/collect-nv.sh
#
# No hace falta que nadie mire adentro del casco: los resultados fisicos ya estan medidos
# (cap. 04). Esto captura el lado del driver.
#
# Por que se puede sin reiniciar nada: /sys/module/nvidia_modeset/parameters/debug es
# -rw------- , o sea que root lo escribe EN CALIENTE. No hay que recargar el modulo ni
# tirar la sesion grafica.
#
# El test de display corre como el USUARIO (necesita su sesion Wayland); solo la captura
# de logs corre como root.

set -u

if [ "$(id -u)" -ne 0 ]; then
    echo "Esto necesita root:  sudo $0" >&2
    exit 1
fi
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Averiguar de quien es la sesion grafica. SUDO_USER esta vacio si arrancaste desde una
# shell que YA era root, asi que hay varios respaldos. Se puede forzar con HMD_USER=.
USER_NAME="${HMD_USER:-${SUDO_USER:-}}"
[ -z "$USER_NAME" ] && USER_NAME="$(logname 2>/dev/null || true)"
[ -z "$USER_NAME" ] && USER_NAME="$(stat -c %U "$REPO" 2>/dev/null || true)"
[ -z "$USER_NAME" ] && USER_NAME="$(loginctl list-sessions --no-legend 2>/dev/null | awk '$3!="root"{print $3; exit}')"
if [ -z "$USER_NAME" ] || [ "$USER_NAME" = "root" ]; then
    echo "No pude deducir el usuario de la sesion grafica." >&2
    echo "Corre:  HMD_USER=tu_usuario $0" >&2
    exit 1
fi
UID_N=$(id -u "$USER_NAME") || { echo "usuario '$USER_NAME' no existe" >&2; exit 1; }
echo "usuario de la sesion: $USER_NAME (uid $UID_N)"
OUT="$REPO/nv-report-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "Artefactos -> $OUT"

DBG=/sys/module/nvidia_modeset/parameters/debug
PREV_DBG=$(cat "$DBG" 2>/dev/null || echo "?")
echo "nvidia_modeset debug: valor previo = $PREV_DBG"

cleanup() {
    [ "$PREV_DBG" != "?" ] && echo "$PREV_DBG" > "$DBG" 2>/dev/null
    for p in $(pgrep -f "hmd[-]vk"); do kill "$p" 2>/dev/null; done
    for p in $(pgrep -f "dmesg -w"); do kill "$p" 2>/dev/null; done
}
trap cleanup EXIT

# --- build del repro, como el usuario ---
BUILD="$OUT/build"
mkdir -p "$BUILD"
chown -R "$USER_NAME" "$OUT"
XML=/usr/share/wayland-protocols/staging/drm-lease/drm-lease-v1.xml
sudo -u "$USER_NAME" wayland-scanner client-header "$XML" "$BUILD/drm-lease-v1-client-protocol.h" || exit 1
sudo -u "$USER_NAME" wayland-scanner private-code  "$XML" "$BUILD/drm-lease-v1-protocol.c" || exit 1
sudo -u "$USER_NAME" gcc -O2 -o "$BUILD/hmd-vk" "$REPO/scripts/hmd-vk.c" \
        "$BUILD/drm-lease-v1-protocol.c" -I"$BUILD" \
        $(pkg-config --cflags --libs wayland-client vulkan) || exit 1
echo "repro compilado: $BUILD/hmd-vk"

# --- contexto del sistema ---
{
    echo "=== fecha ==="; date -Is
    echo; echo "=== kernel ==="; uname -a
    echo; echo "=== driver ==="; cat /proc/driver/nvidia/version
    echo; echo "=== sesion ==="
    echo "XDG_SESSION_TYPE(usuario)=$(sudo -u "$USER_NAME" printenv XDG_SESSION_TYPE 2>/dev/null)"
    echo "compositor: $(pgrep -a 'gnome-shell|kwin_wayland|sway' | head -1)"
    echo; echo "=== GPU ==="; nvidia-smi -q | head -40
    echo; echo "=== conector del casco ==="
    for f in status enabled dpms modes; do
        echo "--- $f"; cat "/sys/class/drm/card0-DP-1/$f" 2>/dev/null
    done
    echo; echo "=== USB del casco ==="; lsusb | grep -E "03f0:0580|045e:0659|04b4:650|0bda:4c15"
} > "$OUT/contexto.txt" 2>&1
cp /sys/class/drm/card0-DP-1/edid "$OUT/hmd.edid" 2>/dev/null
command -v edid-decode >/dev/null && edid-decode "$OUT/hmd.edid" > "$OUT/edid-decode.txt" 2>&1

run_mode() {   # $1 = indice de modo Vulkan, $2 = etiqueta
    local idx="$1" tag="$2"
    echo
    echo "=== corriendo modo $idx ($tag) ==="
    echo 1 > "$DBG" 2>/dev/null || echo "  (no pude activar debug)"
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
    echo "  fps: $(grep -oE '[0-9.]+ fps presentados' "$OUT/hmd-vk-$tag.log" | tail -1)"
    echo "  lineas de dmesg capturadas: $(wc -l < "$OUT/dmesg-$tag.txt")"
}

# El CONTROL va primero y el fallo despues, para que cualquier diferencia en el log no se
# pueda atribuir a que el setup se degrado con el uso.
run_mode 2 "60hz-CONTROL-anda"
sleep 3
run_mode 0 "90hz-2880x1440-FALLA"
sleep 3
run_mode 1 "90hz-4320x2160-FALLA"

# --- el artefacto que NVIDIA pide siempre ---
echo
echo "=== nvidia-bug-report.sh (tarda un rato) ==="
( cd "$OUT" && nvidia-bug-report.sh --output-file "$OUT/nvidia-bug-report" >/dev/null 2>&1 )
ls -la "$OUT" | sed 's/^/  /'

chown -R "$USER_NAME" "$OUT"
echo
echo "LISTO. Todo en: $OUT"
echo "Lo que importa: diffear dmesg-60hz-CONTROL-anda.txt contra dmesg-90hz-*-FALLA.txt"
