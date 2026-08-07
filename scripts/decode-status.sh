#!/bin/bash
# Automated matrix to decode the companion's DEVICE_STATUS (0x05) message.
#
# The headset reports its panel state over HID. We know byte 5 is the refresh rate in decimal
# (0x3c=60, 0x5a=90, confirmed at two different resolutions). Bytes 9, 10 and 12 also
# change between modes and we do NOT know what they are. This gathers enough samples to
# narrow them down.
#
# Deliberately alternates modes in both directions: if a byte depends on the TRANSITION
# rather than the final state, this exposes it.
#
#   ./decode-status.sh          (needs no root, and no one has to wear the headset)

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
OUT="${TMPDIR:-/tmp}/status-matrix-$$"
mkdir -p "$OUT"

BIN=$(ls -t "$REPO"/nv-report-*/build/hmd-vk 2>/dev/null | head -1)
[ -x "$BIN" ] || { echo "can't find a compiled hmd-vk" >&2; exit 1; }
echo "repro: $BIN"
echo "output: $OUT"

# Mode 2 = 4320x2160@60 (WORKS) | 0 = 2880x1440@90 (fails) | 1 = 4320x2160@90 (fails)
TRIALS="2 0 2 1 0 2 1"
i=0
for m in $TRIALS; do
    i=$((i+1))
    case "$m" in
        0) desc="2880x1440@90-FAILS" ;;
        1) desc="4320x2160@90-FAILS" ;;
        2) desc="4320x2160@60-WORKS"  ;;
    esac
    echo
    echo "--- trial $i: mode $m ($desc) ---"
    ./scripts/panel-status.py 26 > "$OUT/t$i-m$m.txt" 2>&1 &
    SNIFF=$!
    sleep 2
    timeout 34 "$BIN" native "$m" 18 > /dev/null 2>&1
    wait $SNIFF 2>/dev/null
    grep -c DEVICE_STATUS "$OUT/t$i-m$m.txt" | sed 's/^/    messages: /'
    sleep 2
done

echo
echo "################ TABLE ################"
printf "%-4s %-22s %s\n" "mode" "description" "DEVICE_STATUS message"
i=0
for m in $TRIALS; do
    i=$((i+1))
    case "$m" in
        0) desc="2880x1440@90 FAILS" ;;
        1) desc="4320x2160@90 FAILS" ;;
        2) desc="4320x2160@60 WORKS"  ;;
    esac
    grep DEVICE_STATUS "$OUT/t$i-m$m.txt" 2>/dev/null | sed 's/.*len=[0-9]* //' | \
      while read -r hexline; do
        printf "%-4s %-22s %s\n" "$m" "$desc" "$hexline"
      done
done
echo
echo "raw output in: $OUT"
