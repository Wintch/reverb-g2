#!/bin/bash
# Levanta Monado en una sesion WAYLAND usando DRM lease, en vez del NVIDIA Direct-Mode
# de X11. Es la via por la que Project-VR reporta el G2 corriendo a 4320x2160@90.
#
#   ./jack-in-wayland.sh [modo]     modo: 0 = 2880x1440@90
#                                         1 = 4320x2160@90  (el que usa Project-VR)
#                                         2 = 4320x2160@60  (el unico que anda hoy en X11)
#
# Por que es MUCHO mas simple que jack-in.sh: en X11 hay que pelearle el display a X
# (liberar DP-0, ciclar CRTC, restaurar la rotacion del portrait). Con DRM lease el
# compositor Wayland nunca toma el HMD -- lo ve marcado como non-desktop y lo deja
# arrendable. No se toca ningun monitor del escritorio.

set -u

MODE="${1:-1}"
VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$HOME/vr/monado" ] && VR="$HOME/vr"
SERVICE="$VR/monado/build/src/xrt/targets/service/monado-service"
LOG="$VR/jack-in-wayland.log"
SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/monado_comp_ipc"

if [ "${XDG_SESSION_TYPE:-}" != "wayland" ]; then
    echo "Esto necesita una sesion WAYLAND (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset})." >&2
    echo "Cerra sesion y elegi 'Plasma' (no 'Plasma (X11)') en SDDM." >&2
    exit 1
fi

[ -x "$SERVICE" ] || { echo "No encuentro monado-service en $SERVICE" >&2; exit 1; }

# Los cinco del casco (cap. 00). Si falta el companion, es el puerto USB, no Monado.
FOUND=$(lsusb | grep -cE "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15")
echo "Dispositivos USB del casco: $FOUND/5"
if [ "$FOUND" -lt 5 ]; then
    echo "  !! Faltan dispositivos. Revisa el puerto USB antes de seguir (cap. 00)." >&2
    lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15" >&2
fi

# SIGKILL no limpia el socket, y un socket viejo hace fallar el arranque.
for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
sleep 2
rm -f "$SOCKET"

echo "Arrancando Monado (modo $MODE) por DRM lease... log: $LOG"

# WMR_DISPLAY_INIT_SLEEP_SECONDS=2 es load-bearing igual que en X11: el panel se apaga
# solo a los ~3s si no le llega senal de video, y con el default de 4s Monado despierta
# cuando ya se apago.
XRT_COMPOSITOR_FORCE_WAYLAND_DIRECT=1 \
XRT_COMPOSITOR_DESIRED_MODE="$MODE" \
XRT_COMPOSITOR_LOG=debug \
WMR_SLAM=0 WMR_CAMERAS=0 \
WMR_DISPLAY_INIT_SLEEP_SECONDS=2 \
    "$SERVICE" > "$LOG" 2>&1 &

SVC=$!
for _i in $(seq 1 30); do
    [ -S "$SOCKET" ] && break
    kill -0 "$SVC" 2>/dev/null || break
    sleep 1
done

echo
echo "=== backend de compositor elegido ==="
# ESTO es lo que hay que mirar. En X11 decia "Selected NVIDIA Direct-Mode backend!".
# Si en Wayland sigue diciendo lo mismo, el DRM lease NO se uso y el test no vale.
grep -iE "Selected .* backend|direct wayland|drm.?lease|lease" "$LOG" | head -8 \
    || echo "  (nada -- revisa el log entero)"

echo
echo "=== modo de video tomado ==="
grep -E "found display mode|frame interval" "$LOG" | tail -3 \
    || echo "  (no encontro modo -- el HMD puede no estar arrendable)"

echo
if [ -S "$SOCKET" ]; then
    echo "Socket listo. Lanza una app OpenXR con:"
    echo "  XR_RUNTIME_JSON=$VR/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 <app> --graphics Vulkan2"
else
    echo "!! El socket no aparecio. Ultimas lineas del log:" >&2
    tail -15 "$LOG" >&2
fi
