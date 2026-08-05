#!/bin/bash
# Prueba un modo y da VEREDICTO AUTOMATICO, sin que nadie se ponga el casco.
#
#   ./hmd-test.sh <indice-de-modo> [segundos]
#   ./hmd-test.sh 2      -> 4320x2160@60  (el control que anda)
#   ./hmd-test.sh 0      -> 2880x1440@90
#   ./hmd-test.sh 1      -> 4320x2160@90
#
# COMO FUNCIONA, y por que se le puede creer:
# El companion manda DEVICE_STATUS (0x05) cuando cambia el estado de pantalla. Decodificado
# por nosotros (matriz de 7 ensayos, cap. 04):
#     byte 5      refresh en decimal        (0x3c=60, 0x5a=90)
#     bytes 19-20 htotal  little-endian
#     bytes 21-22 vtotal  little-endian
#     byte 1      1 = el backlight PRENDIO  <- el veredicto
# El byte 1 aparecio en 3 de 3 corridas del modo que funciona y en 0 de 8 de los que fallan.
# Coincide con el comentario de Monado en wmr_hmd.c para el Reverb G1: ese mensaje llega
# "once the HMD screen backlight visibly powers on".
#
# OJO: el detector esta validado contra DOS observaciones fisicas del usuario (T001 y T002 en
# docs/pruebas.jsonl). Es solido pero no infalible: cada tanto conviene revalidarlo con un
# humano mirando, sobre todo si aparece un resultado sorprendente. La regla del proyecto sigue
# siendo que lo fisico manda.

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
MODE="${1:?uso: $0 <indice-de-modo> [segundos]}"
SECS="${2:-18}"

BIN=$(ls -t "$REPO"/nv-report-*/build/hmd-vk 2>/dev/null | head -1)
[ -x "$BIN" ] || { echo "no encuentro hmd-vk compilado" >&2; exit 1; }

LOG="${TMPDIR:-/tmp}/hmd-test-$$.txt"
./scripts/panel-status.py $((SECS + 8)) > "$LOG" 2>&1 &
SNIFF=$!
sleep 2
timeout $((SECS + 16)) "$BIN" native "$MODE" "$SECS" > "${LOG}.vk" 2>&1
wait $SNIFF 2>/dev/null

echo
python3 - "$LOG" <<'PY'
import re, sys
rows = []
for line in open(sys.argv[1]):
    if "DEVICE_STATUS" not in line:
        continue
    hx = line.split("len=")[1].split(" ", 1)[1].strip().split()
    b = [int(x, 16) for x in hx]
    if len(b) >= 23:
        rows.append(b)

if not rows:
    print("  SIN VEREDICTO: el casco no mando ningun DEVICE_STATUS.")
    print("  (puede ser que el panel ya estuviera en ese estado y no hubo cambio)")
    sys.exit(2)

print(f"  {'refresh':>8} {'htotal':>7} {'vtotal':>7}  backlight")
lit = False
for b in rows:
    ht = b[19] | (b[20] << 8)
    vt = b[21] | (b[22] << 8)
    on = (b[1] == 1)
    lit = lit or on
    print(f"  {b[5]:>8} {ht:>7} {vt:>7}  {'PRENDIO' if on else '-'}")

print()
if lit:
    print("  >>> VEREDICTO: ANDA  (el casco reporta backlight encendido)")
else:
    print("  >>> VEREDICTO: FALLA (timing recibido correcto, pero el backlight nunca prendio)")
sys.exit(0 if lit else 1)
PY
