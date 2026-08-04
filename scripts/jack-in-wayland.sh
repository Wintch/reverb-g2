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
    echo "Cerra sesion y elegi 'GNOME on Wayland' en SDDM." >&2
    echo "OJO: hay DOS entradas llamadas solo 'GNOME' -- una es Wayland y la otra X11." >&2
    echo "     KWin no sirve para esto: no ofrece el conector para lease (cap. 04)." >&2
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
#
# XRT_NO_STDIN=1 tambien es obligatorio: sin eso Monado registra stdin en epoll y, lanzado
# en background, muere con 'epoll_ctl(stdin) failed' -> IPC_MAINLOOP_FAILED_TO_INIT antes
# de llegar siquiera al compositor. setsid + stdbuf -oL mantienen el log vivo (usar
# `script` para darle un pty bufferea tanto que las fallas se vuelven ilegibles).
env XRT_COMPOSITOR_FORCE_WAYLAND_DIRECT=1 \
    XRT_COMPOSITOR_DESIRED_MODE="$MODE" \
    XRT_COMPOSITOR_LOG=debug \
    XRT_NO_STDIN=1 \
    WMR_SLAM=0 WMR_CAMERAS=0 \
    WMR_DISPLAY_INIT_SLEEP_SECONDS=2 \
    setsid stdbuf -oL -eL "$SERVICE" < /dev/null > "$LOG" 2>&1 &

SVC=$!
for _i in $(seq 1 30); do
    [ -S "$SOCKET" ] && break
    kill -0 "$SVC" 2>/dev/null || break
    sleep 1
done

# El socket aparece ANTES de que el compositor termine de loguear el backend y el modo,
# asi que grepear apenas lo vemos sale vacio y parece un fallo. Esperamos al marcador.
for _i in $(seq 1 20); do
    grep -q "found display mode" "$LOG" && break
    sleep 1
done

echo
echo "=== backend de compositor elegido ==="
# ESTO es lo que hay que mirar. El string correcto lo emite compositor_try_window:
#   "Target backend wayland-direct initialized!"   <- se uso DRM lease, el test vale
# En X11 decia "Selected NVIDIA Direct-Mode backend!". Si aparece eso, el lease NO se uso.
# Nada de `| head` aca: head sale 0 siempre y se come el `|| echo` de la rama vacia.
OUT="$(grep -iE "Target backend|Selected .* backend|lease|Found no connectors" "$LOG")"
[ -n "$OUT" ] && echo "$OUT" || echo "  (nada -- revisa el log entero)"

echo
echo "=== modo de video tomado ==="
OUT="$(grep -E "found display mode|frame interval" "$LOG" | tail -3)"
[ -n "$OUT" ] && echo "$OUT" || echo "  (no encontro modo -- el HMD puede no estar arrendable)"

echo
if [ -S "$SOCKET" ]; then
    echo "Socket listo. Lanza una app OpenXR con:"
    echo "  XR_RUNTIME_JSON=$VR/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 <app> --graphics Vulkan2"
else
    echo "!! El socket no aparecio. Ultimas lineas del log:" >&2
    tail -15 "$LOG" >&2
fi
