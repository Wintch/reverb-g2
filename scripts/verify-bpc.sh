#!/bin/bash
# Verifica el parche 0004 (no clavar 6 bpc cuando el EDID no declara profundidad).
# Correr DESPUES de reiniciar. No necesita root.
#
#   ./scripts/verify-bpc.sh [indice-de-modo]      (default 1 = 4320x2160@90)
#
# Dos señales, y hacen falta las dos:
#   1. el byte 18 del DEVICE_STATUS tiene que pasar de 06 a 08   <- medicion del lado del CASCO
#   2. verificacion FISICA a 90 Hz                               <- la que manda

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
MODE="${1:-1}"
S="${TMPDIR:-/tmp}/verify-bpc-$$"
mkdir -p "$S"

echo "=== driver en memoria ==="
head -1 /proc/driver/nvidia/version | sed 's/^/  /'

echo
echo "=== el parche esta en el arbol fuente? ==="
if grep -q "digital.bpc != 0" /usr/src/nvidia-*/src/nvidia-modeset/src/nvkms-dpy.c 2>/dev/null; then
    echo "  SI (lineas 3456-3457 de nvkms-dpy.c)"
else
    echo "  !! NO -- el parche no esta. Corre apply-bpc-patch.sh primero."
    exit 1
fi

# El repro se compila fresco: el scratchpad se limpia con cada reboot.
BUILD="$S/build"; mkdir -p "$BUILD"
XML=/usr/share/wayland-protocols/staging/drm-lease/drm-lease-v1.xml
wayland-scanner client-header "$XML" "$BUILD/drm-lease-v1-client-protocol.h" || exit 1
wayland-scanner private-code  "$XML" "$BUILD/drm-lease-v1-protocol.c" || exit 1
gcc -O2 -o "$BUILD/hmd-vk" scripts/hmd-vk.c "$BUILD/drm-lease-v1-protocol.c" -I"$BUILD" \
    $(pkg-config --cflags --libs wayland-client vulkan) || exit 1

echo
echo "=== despertando el panel (el conector aparece unos segundos despues) ==="
./scripts/panel.py activate >/dev/null 2>&1
for i in $(seq 1 8); do
    sleep 3
    st=$(cat /sys/class/drm/card0-DP-1/status 2>/dev/null)
    [ "$st" = "connected" ] && { echo "  DP-1 connected a los $((i*3))s"; break; }
done
[ "$(cat /sys/class/drm/card0-DP-1/status 2>/dev/null)" = "connected" ] || {
    echo "  !! el conector no aparecio. Revisa el USB (los cinco, cap. 00)."; exit 1; }

ID=$(./scripts/testlog.py open "post-parche-0004 modo $MODE" "verificar byte18 06->08 y panel a 90Hz")
echo
echo "=== PRUEBA $ID: escuchando al casco y presentando ==="
setsid nohup ./scripts/panel-status.py 90 > "$S/status.txt" 2>&1 < /dev/null & disown
sleep 2
setsid nohup "$BUILD/hmd-vk" native "$MODE" 0 > "$S/vk.log" 2>&1 < /dev/null & disown

sleep 25
grep -E "modo NATIVO|fps presentados" "$S/vk.log" | tail -2 | sed 's/^/  /'

echo
echo "=== lo que reporta el casco ==="
python3 - "$S/status.txt" <<'PY'
import sys
rows=[]
for line in open(sys.argv[1]):
    if "DEVICE_STATUS" not in line: continue
    b=[int(x,16) for x in line.split("len=")[1].split(" ",1)[1].strip().split()]
    if len(b)>=23: rows.append(b)
if not rows:
    print("  (sin mensajes -- el panel ya estaba en ese estado)"); sys.exit()
for b in rows:
    ht=b[19]|(b[20]<<8); vt=b[21]|(b[22]<<8)
    print(f"  refresh={b[5]:<4} htotal={ht:<6} vtotal={vt:<6} bpc(byte18)={b[18]}  backlight(b1)={b[1]}")
bpc=[b[18] for b in rows if b[5]>0]
print()
if any(v==8 for v in bpc):
    print("  >>> EL PARCHE FUNCIONO: el casco reporta 8 bits por componente.")
elif any(v==6 for v in bpc):
    print("  >>> el byte 18 SIGUE en 6. O el parche no llego al modulo, o hay otro clamp.")
else:
    print(f"  >>> valores de byte 18 vistos: {sorted(set(bpc))}")
PY

echo
echo "  La corrida se mantiene indefinidamente. PONETE EL CASCO Y MIRA."
echo "  Cerrar con:  ./scripts/testlog.py close $ID \"lo que viste\""
echo "  Cortar con:  kill \$(pgrep -f 'hmd-vk')"
echo "  crudo en: $S"
