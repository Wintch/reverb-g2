#!/bin/bash
# Tests a mode and gives an AUTOMATIC VERDICT, without anyone putting on the headset.
#
#   ./hmd-test.sh <mode-index> [seconds]
#   ./hmd-test.sh 2      -> 4320x2160@60  (the control that works)
#   ./hmd-test.sh 0      -> 2880x1440@90
#   ./hmd-test.sh 1      -> 4320x2160@90
#
# HOW IT WORKS, and why it can be trusted:
# The companion sends DEVICE_STATUS (0x05) when the display state changes. Decoded
# by us (matrix of 7 trials, chap. 04):
#     byte 5      refresh in decimal        (0x3c=60, 0x5a=90)
#     bytes 19-20 htotal  little-endian
#     bytes 21-22 vtotal  little-endian
#     byte 1      1 = the backlight TURNED ON  <- the verdict
# Byte 1 appeared in 3 of 3 runs of the mode that works and in 0 of 8 of the ones that fail.
# This matches Monado's comment in wmr_hmd.c for the Reverb G1: that message arrives
# "once the HMD screen backlight visibly powers on".
#
# NOTE: the detector is validated against TWO physical observations from the user (T001 and T002 in
# docs/pruebas.jsonl). It's solid but not infallible: it's worth periodically revalidating it with a
# human watching, especially if a surprising result appears. The project's rule remains
# that physical observation has the final say.

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
MODE="${1:?usage: $0 <mode-index> [seconds]}"
SECS="${2:-18}"

BIN=$(ls -t "$REPO"/nv-report-*/build/hmd-vk 2>/dev/null | head -1)
[ -x "$BIN" ] || { echo "cannot find compiled hmd-vk" >&2; exit 1; }

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
    print("  NO VERDICT: the headset didn't send any DEVICE_STATUS.")
    print("  (it's possible the panel was already in that state and there was no change)")
    sys.exit(2)

print(f"  {'refresh':>8} {'htotal':>7} {'vtotal':>7}  backlight")
lit = False
for b in rows:
    ht = b[19] | (b[20] << 8)
    vt = b[21] | (b[22] << 8)
    on = (b[1] == 1)
    lit = lit or on
    print(f"  {b[5]:>8} {ht:>7} {vt:>7}  {'ON' if on else '-'}")

print()
if lit:
    print("  >>> VERDICT: WORKS  (the headset reports backlight on)")
else:
    print("  >>> VERDICT: FAILS (timing received correctly, but the backlight never turned on)")
sys.exit(0 if lit else 1)
PY
