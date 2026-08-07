#!/bin/bash
# Applies patch 0004 (do not clamp to 6 bpc when the EDID does not declare depth) to the
# NVIDIA driver's DKMS tree, and rebuilds the module.
#
#   sudo ./scripts/apply-bpc-patch.sh
#   sudo ./scripts/apply-bpc-patch.sh --revert     (removes the patch and rebuilds)
#
# WHY: the G2's EDID leaves the color depth undeclared (byte 0x14 = 0x80).
# nvt_edid.c parses it as bpc = 0, and nvDpyGetOutputColorFormatInfo() does `bpc < 8` ->
# clamps the display to 6 bpc. Measured: the link runs at 18 bpp and the headset itself
# reports 6. Windows uses 8 and runs fine at 90 Hz. Full detail in the patch header and
# in chapter 13.
#
# After running this you MUST REBOOT (or at least restart the graphical session) for the
# new module to be loaded.

set -eu

[ "$(id -u)" -eq 0 ] || { echo "needs root: sudo $0" >&2; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_NAME="0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch"
PATCH_SRC="$REPO/patches/nvidia/$PATCH_NAME"
[ -f "$PATCH_SRC" ] || { echo "can't find $PATCH_SRC" >&2; exit 1; }

DKMS_DIR=$(ls -d /usr/src/nvidia-* 2>/dev/null | head -1)
[ -n "$DKMS_DIR" ] || { echo "can't find the nvidia DKMS tree in /usr/src" >&2; exit 1; }
VER=$(basename "$DKMS_DIR" | sed 's/^nvidia-//')
echo "DKMS tree: $DKMS_DIR   (version $VER)"

TARGET="$DKMS_DIR/src/nvidia-modeset/src/nvkms-dpy.c"
[ -f "$TARGET" ] || { echo "can't find nvkms-dpy.c in the tree" >&2; exit 1; }

if [ "${1:-}" = "--revert" ]; then
    echo "reverting..."
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
print("  source restored")
PY
    sed -i "/$PATCH_NAME/d" "$DKMS_DIR/dkms.conf" 2>/dev/null || true
else
    # The tree is edited directly (not via dkms.conf's PATCH[]) because the other three
    # patches are already applied there and a new PATCH[] would apply against the clean tree.
    if grep -q "digital.bpc != 0" "$TARGET"; then
        echo "  the patch is ALREADY applied, doing nothing"
    else
        python3 - "$TARGET" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = "                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {"
new = ("                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&\n"
       "                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {")
if old not in s:
    sys.exit("  !! could not find the line to patch -- did the tree change?")
if s.count(old) != 1:
    sys.exit(f"  !! the line appears {s.count(old)} times, expected 1")
open(p, "w").write(s.replace(old, new))
print("  patch applied to nvkms-dpy.c")
PY
    fi
fi

echo
echo "=== line verification ==="
grep -n -A1 "digital.bpc != 0\|digital.bpc < 8" "$TARGET" | head -6

echo
echo "=== rebuilding the module (takes a few minutes) ==="
dkms remove "nvidia/$VER" --all 2>/dev/null || true
dkms install "nvidia/$VER"

echo
echo "DONE. YOU MUST REBOOT to load the new module."
echo "After the reboot, verify with:"
echo "  cat /proc/driver/nvidia/version"
echo "  and run the 90Hz test: ./scripts/hmd-test.sh 1"
echo
echo "What to look for: byte 18 of DEVICE_STATUS should go from 06 to 08."
echo "  ./scripts/panel-status.py 40   (in parallel with hmd-vk)"
