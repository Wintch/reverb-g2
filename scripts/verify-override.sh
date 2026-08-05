#!/bin/bash
# Verifica que nvidia_modeset.config_file cargo el EDID esperado. Junta en un solo script
# TODO lo que este experimento necesita leer con privilegios (dmesg restringido, y el EDID
# de sysfs que en este driver solo lo puede leer root) para no andar pidiendo la
# contrasena de a un comando por vez.
#
#   sudo ./scripts/verify-override.sh                 (compara contra lo que diga el .conf activo)
#   sudo ./scripts/verify-override.sh archivo.edid     (compara contra un archivo puntual)
#
# Que hace:
#   1. dmesg: confirma "Successfully read ..." y que no haya "Error in"/"Syntax error"
#   2. fuerza un detect() fresco del conector (cat status) antes de leer el EDID
#   3. compara md5 del EDID activo en sysfs contra el archivo esperado
#
# EXPECTATIVA: los tres pasos son de lectura, no tocan nada. No hace falta reboot para
# correrlo, pero para que el paso 3 cambie hace falta haber reiniciado con el .conf nuevo
# (nvkms-dpy-override.c: DpyOverrideReadEdid solo lee el archivo una vez, al cargar el modulo).

set -u

[ "$(id -u)" -eq 0 ] || { echo "necesita root: sudo $0" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$REPO/experiments/vblank/nvkms-override-candidates.conf"
CONNECTOR="/sys/class/drm/card0-DP-1"

EXPECTED="${1:-}"
if [ -z "$EXPECTED" ]; then
    EXPECTED="$(grep -oP '(?<= = )\S+\.edid' "$CONF" | tail -1)"
    [ -n "$EXPECTED" ] || { echo "no encuentro una linea 'override....edid' en $CONF" >&2; exit 1; }
fi
[ -f "$EXPECTED" ] || { echo "no existe: $EXPECTED" >&2; exit 1; }

echo "=== esperado (segun ${1:+arg}${1:-el .conf}) ==="
echo "  $EXPECTED"

echo
echo "=== dmesg: carga del config_file ==="
LOAD_LINES="$(dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read')"
if [ -z "$LOAD_LINES" ]; then
    echo "  (nada -- puede que el buffer de dmesg haya rotado desde el boot)"
else
    echo "$LOAD_LINES" | sed 's/^/  /'
fi
if echo "$LOAD_LINES" | grep -qiE 'error in|syntax error'; then
    echo "  !! hay un error de parseo -- el .conf se descarto ENTERO, no solo la linea mala"
fi

echo
echo "=== forzando detect() fresco en $CONNECTOR ==="
cat "$CONNECTOR/status"

echo
echo "=== EDID activo vs esperado ==="
ACTUAL_MD5="$(cat "$CONNECTOR/edid" | md5sum | cut -d' ' -f1)"
EXPECTED_MD5="$(md5sum "$EXPECTED" | cut -d' ' -f1)"
echo "  activo:    $ACTUAL_MD5"
echo "  esperado:  $EXPECTED_MD5"
if [ "$ACTUAL_MD5" = "$EXPECTED_MD5" ]; then
    echo "  OK -- coinciden, el override esta cargado"
    exit 0
else
    echo "  !! NO coinciden -- o falta el reboot, o el override no matcheo (ver docs/16)"
    exit 1
fi
