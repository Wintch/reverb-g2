#!/bin/bash
# Captura el trafico HID del companion (03f0:0580) durante el arranque de Monado,
# una vez por cada modo de video, para diffear la secuencia de activacion.
#
# El companion es 'hid_control_dev' en el driver WMR de Monado (wmr_hmd.c:771): por ahi
# van la secuencia de activacion (0x50 x4, 0x09, 0x08, 0x06) y el screen_enable. El
# 'Hololens Sensors' (045e:0659) NO se captura a proposito: escupe IMU a alta frecuencia
# y ahoga el archivo.
#
# CORRER COMO ROOT:  sudo ./scripts/capture-hid.sh
# Salida: ~/vr/hid-mode{2,0,1}.txt  (formato texto de usbmon, legible y diffeable)

set -u

REAL_USER=${SUDO_USER:-iam}
VR=/home/$REAL_USER/vr
OUT=$VR

if [ "$(id -u)" -ne 0 ]; then
    echo "Este script necesita root: sudo $0" >&2
    exit 1
fi

# --- entorno grafico ------------------------------------------------------------------
# 'su - user' resetea el entorno y se lleva DISPLAY/XDG_SESSION_TYPE: jack-in.sh aborta
# con "Not in an X11 session" y Monado nunca arranca (no habria nada que capturar).
# Lo sacamos del proceso real de la sesion del usuario.
SESSION_PID=""
for proc in plasmashell kwin_x11 xfce4-session gnome-shell; do
    SESSION_PID=$(pgrep -u "$REAL_USER" -x "$proc" 2>/dev/null | head -1)
    [ -n "$SESSION_PID" ] && break
done
if [ -z "$SESSION_PID" ]; then
    echo "No encontre un proceso de sesion grafica de $REAL_USER. Logueate en X11 primero." >&2
    exit 1
fi

mapfile -t USERENV < <(tr '\0' '\n' < "/proc/$SESSION_PID/environ" | grep -E \
    '^(DISPLAY|XAUTHORITY|XDG_SESSION_TYPE|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS|HOME|USER|PATH)=')

if ! printf '%s\n' "${USERENV[@]}" | grep -q '^XDG_SESSION_TYPE=x11'; then
    echo "La sesion de $REAL_USER no es X11. jack-in.sh necesita X11." >&2
    printf '%s\n' "${USERENV[@]}" >&2
    exit 1
fi
echo "entorno tomado de PID $SESSION_PID ($(printf '%s\n' "${USERENV[@]}" | grep ^DISPLAY=))"

# --- usbmon ---------------------------------------------------------------------------
modprobe usbmon || { echo "no se pudo cargar usbmon" >&2; exit 1; }

BUS=$(lsusb | grep "03f0:0580" | sed -E 's/^Bus 0*([0-9]+).*/\1/' | head -1)
if [ -z "$BUS" ]; then
    echo "El companion 03f0:0580 no esta presente. Revisa el puerto USB (cap. 00)." >&2
    exit 1
fi
MON=/sys/kernel/debug/usb/usbmon/${BUS}u
[ -r "$MON" ] || { echo "no puedo leer $MON" >&2; exit 1; }
echo "companion en bus $BUS -> $MON"

kill_monado() {
    for p in $(pgrep -f "hello[_]xr"); do kill "$p" 2>/dev/null; done
    sleep 1
    for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
    sleep 3
    rm -f /run/user/1000/monado_comp_ipc
}

# mode 2 = 4320x2160@60 (el que ENCIENDE el panel) — es la referencia del diff.
# mode 0 = 2880x1440@90 nativo (falla).  mode 1 = 4320x2160@90 (falla).
FAILED=0
for MODE in 2 0 1; do
    echo
    echo "=== capturando modo $MODE ==="
    kill_monado

    DEV=$(lsusb | grep "03f0:0580" | sed -E 's/^Bus [0-9]+ Device 0*([0-9]+).*/\1/' | head -1)
    echo "companion device address al arrancar: $DEV"

    # jack-in.log se sobreescribe en cada arranque; lo borramos para no leer el modo
    # del run anterior si jack-in llegara a fallar.
    rm -f "$VR/jack-in.log"

    # stdbuf -o0: sin esto 'cat' bufferea por bloques al escribir a un archivo y una
    # captura chica se pierde entera cuando lo matamos.
    stdbuf -o0 cat "$MON" > "$OUT/hid-mode${MODE}.txt" &
    CATPID=$!
    sleep 1

    runuser -u "$REAL_USER" -- env "${USERENV[@]}" \
        XRT_COMPOSITOR_LOG=debug XRT_COMPOSITOR_DESIRED_MODE="$MODE" \
        bash -c "cd '$VR' && ./jack-in.sh 3dof" > "$OUT/jack-mode${MODE}.log" 2>&1

    # Dejar correr un poco: el segundo screen_enable de wmr_hmd.c:818 llega tarde.
    sleep 8
    kill $CATPID 2>/dev/null
    wait $CATPID 2>/dev/null

    MODE_TAKEN=$(grep -E "found display mode" "$VR/jack-in.log" 2>/dev/null | tail -1)
    LINES=$(wc -l < "$OUT/hid-mode${MODE}.txt")

    if [ -z "$MODE_TAKEN" ]; then
        echo "  !! jack-in NO arranco Monado. Ultimas lineas:" >&2
        tail -4 "$OUT/jack-mode${MODE}.log" >&2
        FAILED=1
    else
        echo "  modo tomado: $MODE_TAKEN"
    fi
    echo "  lineas capturadas: $LINES"
    [ "$LINES" -eq 0 ] && { echo "  !! captura vacia" >&2; FAILED=1; }

    { echo "$MODE_TAKEN"; echo "companion_device=$DEV"; echo "lineas=$LINES"; } \
        > "$OUT/hid-mode${MODE}.meta"
done

kill_monado
chown "$REAL_USER":"$REAL_USER" "$OUT"/hid-mode*.txt "$OUT"/hid-mode*.meta "$OUT"/jack-mode*.log 2>/dev/null

echo
if [ "$FAILED" -eq 1 ]; then
    echo "=== TERMINO CON PROBLEMAS: revisa los mensajes de arriba ==="
else
    echo "=== listo ==="
fi
ls -l "$OUT"/hid-mode*.txt
