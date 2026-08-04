#!/bin/bash
# Contesta UNA pregunta, sin levantar Monado: ¿el compositor Wayland ofrece el conector
# del casco para DRM lease? Es lo que discrimina si el culpable es el compositor (KWin
# no ofrecía ninguno) o el driver NVIDIA.
#
# Correr DENTRO de la sesión Wayland, como usuario.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== sesión ==="
echo "  XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset}   XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-unset}"
if [ "${XDG_SESSION_TYPE:-}" != "wayland" ]; then
    echo "  !! Esto necesita una sesión Wayland. Cerrá sesión y elegí 'GNOME on Wayland'"
    echo "     en SDDM (ojo: hay DOS entradas llamadas 'GNOME', una es X11)."
    exit 1
fi

echo
echo "=== lado kernel/NVIDIA: conector non-desktop ==="
# El parche 0002 marca el conector del casco como non-desktop=1 y expone los 3 modos.
BIN="${TMPDIR:-/tmp}/drmprops.$$"
if gcc -o "$BIN" "$HERE/drmprops.c" -ldrm -I/usr/include/libdrm 2>/dev/null; then
    "$BIN" | awk '/^connector/{c=$0; nd=""} /non-desktop  = 1/{print c; nd=1} nd&&/mode:/{print}'
    rm -f "$BIN"
else
    echo "  (no pude compilar drmprops.c -- falta libdrm-dev?)"
fi

echo
echo "=== lado compositor: ¿publica el global de DRM lease? ==="
if ! command -v wayland-info >/dev/null; then
    echo "  wayland-info no está (apt install wayland-utils)"; exit 1
fi
INFO="$(wayland-info 2>/dev/null)"
if echo "$INFO" | grep -q wp_drm_lease_device_v1; then
    echo "  SÍ: $(echo "$INFO" | grep -m1 wp_drm_lease_device_v1 | sed 's/^ *//')"
else
    echo "  NO -- el compositor ni siquiera anuncia wp_drm_lease_device_v1."
    echo "     Sin eso no hay lease posible; no tiene sentido correr jack-in-wayland.sh."
    exit 2
fi

echo
echo "=== ¿cuántos conectores ofrece en ese device? ==="
# KWin 6.3.6 anunciaba el device y ofrecía CERO conectores: ese era el síntoma exacto.
# OJO: wayland-info imprime "connector:" a secas, sin espacio ni id en la misma linea.
# Contar "connector: " (con espacio) da 0 SIEMPRE y hace pasar por fallo un exito.
BLOCK="$(echo "$INFO" | sed -n '/wp_drm_lease_device_v1/,/^interface/p')"
N=$(echo "$BLOCK" | grep -cE '^[[:space:]]*connector:[[:space:]]*$' || true)
echo "$BLOCK" | head -30
echo
if [ "$N" -gt 0 ]; then
    echo "  --> Ofrece conectores. Seguí con: ./jack-in-wayland.sh 1"
else
    echo "  --> CERO conectores, igual que KWin. Si mutter SIN parchear tampoco los ofrece,"
    echo "      el culpable no es el compositor: es NVIDIA."
fi
