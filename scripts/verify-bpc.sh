#!/bin/bash
# Verifies patch 0004 (don't clamp to 6 bpc when the EDID doesn't declare bit depth).
# Run AFTER rebooting. Doesn't need root.
#
#   ./scripts/verify-bpc.sh [mode-index]      (default 1 = 4320x2160@90)
#
# Two signals, and both are needed:
#   1. byte 18 of DEVICE_STATUS has to go from 06 to 08          <- measurement from the HEADSET side
#   2. PHYSICAL verification at 90 Hz                            <- the one that decides it

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
MODE="${1:-1}"
S="${TMPDIR:-/tmp}/verify-bpc-$$"
mkdir -p "$S"

echo "=== driver in memory ==="
head -1 /proc/driver/nvidia/version | sed 's/^/  /'

echo
echo "=== is the patch applied? ==="
if grep -q "digital.bpc != 0" /usr/src/nvidia-*/src/nvidia-modeset/src/nvkms-dpy.c 2>/dev/null; then
    echo "  YES, edited directly in the source tree (lines 3456-3457 of nvkms-dpy.c)"
elif grep -q "0004-nvkms-do-not-clamp-to-6bpc" /usr/src/nvidia-*/dkms.conf 2>/dev/null; then
    echo "  YES, via PATCH[] in dkms.conf (the source tree is kept clean on purpose -"
    echo "  DKMS applies it to a copy at build time, see docs/13-bug-6bpc.md)"
else
    echo "  !! NO -- the patch is not present through any path. Run apply-bpc-patch.sh or"
    echo "  bootstrap-lab.sh patch-nv first."
    exit 1
fi

# The repro is built fresh each time: the scratchpad gets wiped on every reboot.
BUILD="$S/build"; mkdir -p "$BUILD"
XML=/usr/share/wayland-protocols/staging/drm-lease/drm-lease-v1.xml
wayland-scanner client-header "$XML" "$BUILD/drm-lease-v1-client-protocol.h" || exit 1
wayland-scanner private-code  "$XML" "$BUILD/drm-lease-v1-protocol.c" || exit 1
gcc -O2 -o "$BUILD/hmd-vk" scripts/hmd-vk.c "$BUILD/drm-lease-v1-protocol.c" -I"$BUILD" \
    $(pkg-config --cflags --libs wayland-client vulkan) || exit 1

echo
echo "=== waking up the panel (the connector appears a few seconds later) ==="
./scripts/panel.py activate >/dev/null 2>&1
for i in $(seq 1 8); do
    sleep 3
    st=$(cat /sys/class/drm/card0-DP-1/status 2>/dev/null)
    [ "$st" = "connected" ] && { echo "  DP-1 connected at $((i*3))s"; break; }
done
[ "$(cat /sys/class/drm/card0-DP-1/status 2>/dev/null)" = "connected" ] || {
    echo "  !! the connector never showed up. Check the USB (all five, cap. 00)."; exit 1; }

ID=$(./scripts/testlog.py open "post-patch-0004 mode $MODE" "verify byte18 06->08 and panel at 90Hz")
echo
echo "=== TEST $ID: listening to the headset and presenting ==="
setsid nohup ./scripts/panel-status.py 90 > "$S/status.txt" 2>&1 < /dev/null & disown
sleep 2
setsid nohup "$BUILD/hmd-vk" native "$MODE" 0 > "$S/vk.log" 2>&1 < /dev/null & disown

sleep 25
grep -E "NATIVE mode|fps presented" "$S/vk.log" | tail -2 | sed 's/^/  /'

echo
echo "=== what the headset reports ==="
python3 - "$S/status.txt" <<'PY'
import sys
rows=[]
for line in open(sys.argv[1]):
    if "DEVICE_STATUS" not in line: continue
    b=[int(x,16) for x in line.split("len=")[1].split(" ",1)[1].strip().split()]
    if len(b)>=23: rows.append(b)
if not rows:
    print("  (no messages -- the panel was already in that state)"); sys.exit()
for b in rows:
    ht=b[19]|(b[20]<<8); vt=b[21]|(b[22]<<8)
    print(f"  refresh={b[5]:<4} htotal={ht:<6} vtotal={vt:<6} bpc(byte18)={b[18]}  backlight(b1)={b[1]}")
bpc=[b[18] for b in rows if b[5]>0]
print()
if any(v==8 for v in bpc):
    print("  >>> THE PATCH WORKED: the headset reports 8 bits per component.")
elif any(v==6 for v in bpc):
    print("  >>> byte 18 is STILL at 6. Either the patch never reached the module, or there's another clamp.")
else:
    print(f"  >>> byte 18 values seen: {sorted(set(bpc))}")
PY

echo
echo "  The run keeps going indefinitely. PUT ON THE HEADSET AND LOOK."
echo "  Close with:  ./scripts/testlog.py close $ID \"what you saw\""
echo "  Kill with:  kill \$(pgrep -f 'hmd-vk')"
echo "  raw output in: $S"
