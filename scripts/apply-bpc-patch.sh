#!/bin/bash
# Aplica el parche 0004 (no clavar 6 bpc cuando el EDID no declara profundidad) al arbol
# DKMS del driver NVIDIA, y reconstruye el modulo.
#
#   sudo ./scripts/apply-bpc-patch.sh
#   sudo ./scripts/apply-bpc-patch.sh --revert     (saca el parche y reconstruye)
#
# POR QUE: el EDID del G2 deja la profundidad de color sin declarar (byte 0x14 = 0x80).
# nvt_edid.c la parsea como bpc = 0, y nvDpyGetOutputColorFormatInfo() hace `bpc < 8` ->
# clava el display en 6 bpc. Medido: el enlace corre a 18 bpp y el propio casco reporta 6.
# Windows usa 8 y a 90 Hz anda. Detalle completo en el encabezado del parche y en el cap. 13.
#
# Despues de correr esto HAY QUE REINICIAR (o al menos reiniciar la sesion grafica) para que
# el modulo nuevo quede cargado.

set -eu

[ "$(id -u)" -eq 0 ] || { echo "necesita root: sudo $0" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_NAME="0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch"
PATCH_SRC="$REPO/patches/nvidia/$PATCH_NAME"
[ -f "$PATCH_SRC" ] || { echo "no encuentro $PATCH_SRC" >&2; exit 1; }

DKMS_DIR=$(ls -d /usr/src/nvidia-* 2>/dev/null | head -1)
[ -n "$DKMS_DIR" ] || { echo "no encuentro el arbol DKMS de nvidia en /usr/src" >&2; exit 1; }
VER=$(basename "$DKMS_DIR" | sed 's/^nvidia-//')
echo "arbol DKMS: $DKMS_DIR   (version $VER)"

TARGET="$DKMS_DIR/src/nvidia-modeset/src/nvkms-dpy.c"
[ -f "$TARGET" ] || { echo "no encuentro nvkms-dpy.c en el arbol" >&2; exit 1; }

if [ "${1:-}" = "--revert" ]; then
    echo "revirtiendo..."
    sed -i 's/} else if (pDpyEvo->parsedEdid\.info\.input\.u\.digital\.bpc != 0 \&\&\n/X/' "$TARGET" || true
    python3 - "$TARGET" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = s.replace(
"""                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {""",
"""                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {""")
open(p, "w").write(s)
print("  fuente restaurada")
PY
    sed -i "/$PATCH_NAME/d" "$DKMS_DIR/dkms.conf" 2>/dev/null || true
else
    # Se edita el arbol directamente (no via PATCH[] de dkms.conf) porque los otros tres
    # parches ya estan aplicados ahi y un PATCH[] nuevo se aplicaria sobre el arbol limpio.
    if grep -q "digital.bpc != 0" "$TARGET"; then
        echo "  el parche YA esta aplicado, no hago nada"
    else
        python3 - "$TARGET" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = "                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {"
new = ("                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&\n"
       "                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {")
if old not in s:
    sys.exit("  !! no encontre la linea a parchear -- el arbol cambio?")
if s.count(old) != 1:
    sys.exit(f"  !! la linea aparece {s.count(old)} veces, esperaba 1")
open(p, "w").write(s.replace(old, new))
print("  parche aplicado a nvkms-dpy.c")
PY
    fi
fi

echo
echo "=== verificacion de la linea ==="
grep -n -A1 "digital.bpc != 0\|digital.bpc < 8" "$TARGET" | head -6

echo
echo "=== reconstruyendo el modulo (tarda unos minutos) ==="
dkms remove "nvidia/$VER" --all 2>/dev/null || true
dkms install "nvidia/$VER"

echo
echo "LISTO. HAY QUE REINICIAR para cargar el modulo nuevo."
echo "Despues del reboot, verificar con:"
echo "  cat /proc/driver/nvidia/version"
echo "  y correr el test de 90Hz: ./scripts/hmd-test.sh 1"
echo
echo "Lo que hay que mirar: el byte 18 del DEVICE_STATUS tiene que pasar de 06 a 08."
echo "  ./scripts/panel-status.py 40   (en paralelo con hmd-vk)"
