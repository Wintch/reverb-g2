#!/bin/bash
# Matriz automatizada para decodificar el mensaje DEVICE_STATUS (0x05) del companion.
#
# El casco reporta su estado de panel por HID. Sabemos que el byte 5 es el refresh en decimal
# (0x3c=60, 0x5a=90, confirmado en dos resoluciones distintas). Los bytes 9, 10 y 12 tambien
# cambian entre modos y NO sabemos que son. Esto junta muestras suficientes para acotarlos.
#
# Alterna modos en los dos sentidos a proposito: si un byte depende de la TRANSICION y no del
# estado final, sale a la luz.
#
#   ./decode-status.sh          (no necesita root, ni que nadie se ponga el casco)

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
OUT="${TMPDIR:-/tmp}/status-matrix-$$"
mkdir -p "$OUT"

BIN=$(ls -t "$REPO"/nv-report-*/build/hmd-vk 2>/dev/null | head -1)
[ -x "$BIN" ] || { echo "no encuentro hmd-vk compilado" >&2; exit 1; }
echo "repro: $BIN"
echo "salida: $OUT"

# Modo 2 = 4320x2160@60 (ANDA) | 0 = 2880x1440@90 (falla) | 1 = 4320x2160@90 (falla)
TRIALS="2 0 2 1 0 2 1"
i=0
for m in $TRIALS; do
    i=$((i+1))
    case "$m" in
        0) desc="2880x1440@90-FALLA" ;;
        1) desc="4320x2160@90-FALLA" ;;
        2) desc="4320x2160@60-ANDA"  ;;
    esac
    echo
    echo "--- ensayo $i: modo $m ($desc) ---"
    ./scripts/panel-status.py 26 > "$OUT/t$i-m$m.txt" 2>&1 &
    SNIFF=$!
    sleep 2
    timeout 34 "$BIN" native "$m" 18 > /dev/null 2>&1
    wait $SNIFF 2>/dev/null
    grep -c DEVICE_STATUS "$OUT/t$i-m$m.txt" | sed 's/^/    mensajes: /'
    sleep 2
done

echo
echo "################ TABLA ################"
printf "%-4s %-22s %s\n" "modo" "descripcion" "mensaje DEVICE_STATUS"
i=0
for m in $TRIALS; do
    i=$((i+1))
    case "$m" in
        0) desc="2880x1440@90 FALLA" ;;
        1) desc="4320x2160@90 FALLA" ;;
        2) desc="4320x2160@60 ANDA"  ;;
    esac
    grep DEVICE_STATUS "$OUT/t$i-m$m.txt" 2>/dev/null | sed 's/.*len=[0-9]* //' | \
      while read -r hexline; do
        printf "%-4s %-22s %s\n" "$m" "$desc" "$hexline"
      done
done
echo
echo "crudo en: $OUT"
