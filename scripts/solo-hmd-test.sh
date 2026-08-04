#!/bin/bash
# Test 90Hz con el casco como UNICO display activo.
# Restaura el layout del escritorio pase lo que pase (trap EXIT).
# El usuario se queda sin pantalla mientras dura: el restore es automatico.

export DISPLAY=:0
LOOK_SECONDS="${1:-120}"
STAMP=/home/iam/vr/solo-hmd-test.status

log() { echo "[$(date +%H:%M:%S)] $*" >> "$STAMP"; }

restore_desktop() {
    log "RESTORE: matando sesion VR"
    for p in $(pgrep -f "hello[_]xr"); do kill "$p" 2>/dev/null; done
    sleep 2
    for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
    sleep 3
    rm -f /run/user/1000/monado_comp_ipc

    log "RESTORE: reponiendo los tres monitores"
    xrandr --output HDMI-1 --mode 1920x1080 --rate 60 --pos 0x0 --rotate normal \
           --output DP-3   --mode 1920x1080 --rate 60 --pos 1920x0 --rotate right --primary \
           --output HDMI-0 --mode 1920x1080 --rate 143.98 --pos 3000x0 --rotate normal 2>>"$STAMP"
    sleep 2

    # Ciclar la rotacion del portrait: xrandr REPORTA "right" aunque el panel muestre
    # landscape tras un direct-mode. En KDE el que realmente la aplica es kscreen-doctor.
    log "RESTORE: ciclando rotacion de DP-3"
    xrandr --output DP-3 --rotate normal 2>>"$STAMP"; sleep 1
    xrandr --output DP-3 --rotate right  2>>"$STAMP"; sleep 1
    if command -v kscreen-doctor >/dev/null 2>&1; then
        kscreen-doctor output.DP-3.rotation.right >>"$STAMP" 2>&1 || true
    fi
    log "RESTORE: listo"
    xrandr --query 2>/dev/null | grep -E " connected" >> "$STAMP"
}
trap restore_desktop EXIT

: > "$STAMP"
log "INICIO - el casco queda como unico display por ~${LOOK_SECONDS}s"

# 1. Apagar TODO el escritorio: libera el ultimo dominio de reloj de 60 Hz
xrandr --output HDMI-0 --off --output HDMI-1 --off --output DP-3 --off 2>>"$STAMP"
sleep 2
log "escritorio apagado; displays activos:"
xrandr --query 2>/dev/null | grep -E " connected [0-9]" >> "$STAMP"

# 2. Arrancar Monado a 90 Hz nativo
cd /home/iam/vr || exit 1
rm -f /run/user/1000/monado_comp_ipc
XRT_COMPOSITOR_LOG=debug XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof >>"$STAMP" 2>&1
log "jack-in termino; modo tomado:"
grep -E "found display mode" /home/iam/vr/jack-in.log | tail -2 >> "$STAMP"

# 3. Lanzar el visor 360
sleep 900 | XR_RUNTIME_JSON=/home/iam/vr/monado/build/openxr_monado-dev.json \
    IPC_IGNORE_VERSION=1 VK_LOADER_LAYERS_DISABLE='*' \
    HELLO_XR_PHOTO360=/home/iam/vr/media/test-equirect.jpg \
    ./OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr --graphics Vulkan2 \
    > /home/iam/vr/hello_xr.log 2>&1 &

sleep 10
log "visor lanzado. MIRAR ADENTRO DEL CASCO AHORA."
grep -cE "BEGIN_SESSION" /home/iam/vr/jack-in.log >> "$STAMP"

# 4. Ventana para que el usuario mire, y despues restore automatico via trap
sleep "$LOOK_SECONDS"
log "fin de la ventana de observacion"
