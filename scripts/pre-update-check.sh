#!/bin/bash
# Run BEFORE `apt upgrade`. Records the current known-good state and flags loudly if the
# pending upgrade queue touches the kernel or NVIDIA/EGL packages -- that's the signal to
# read docs/24-safe-system-updates.md before continuing, not just upgrading on autopilot.
#
#   ./scripts/pre-update-check.sh

set -u

echo "=== current kernel ==="
uname -r

echo
echo "=== nvidia driver package + DKMS status ==="
dpkg -l nvidia-kernel-open-dkms 2>/dev/null | grep -E "^ii" | awk '{print "  " $2, $3}'
DKMS_BIN="/usr/sbin/dkms"
[ -x "$DKMS_BIN" ] || DKMS_BIN="dkms"
"$DKMS_BIN" status 2>&1 | sed 's/^/  /'

echo
echo "=== are all 4 patches applied in the CURRENT build log? ==="
LOG=$(find /var/lib/dkms/nvidia -iname "make.log" 2>/dev/null | sort | tail -1)
if [ -z "$LOG" ]; then
    echo "  !! No DKMS build log found at all -- can't confirm patch state."
else
    echo "  log: $LOG"
    OK=1
    for p in \
        "0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch" \
        "0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch" \
        "0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch" \
        "0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch"; do
        if grep -q "Applying patch $p" "$LOG"; then
            echo "  OK: $p"
        else
            echo "  !! MISSING: $p"
            OK=0
        fi
    done
    [ "$OK" = 1 ] && echo "  All 4 patches confirmed applied in the current build." \
                  || echo "  !! Not all patches confirmed -- don't trust this as a known-good baseline."
fi

echo
echo "=== rollback kernel readiness ==="
CURRENT=$(uname -r)
OTHER=$(dpkg -l 'linux-image-6.*-amd64' 2>/dev/null | awk '/^ii/{print $2}' | sed 's/linux-image-//' | grep -v "^$CURRENT\$")
if [ -z "$OTHER" ]; then
    echo "  Only one kernel installed -- no rollback kernel exists at all."
    echo "  -> See docs/24-safe-system-updates.md, 'One-time prep', before relying on a rollback."
else
    for k in $OTHER; do
        if "$DKMS_BIN" status 2>/dev/null | grep -q "$k"; then
            echo "  OK: $k has a DKMS build ready (real rollback available)."
        else
            echo "  !! $k is installed but has NO DKMS build -- rebooting into it would leave"
            echo "     you without an NVIDIA driver. See docs/24, 'One-time prep'."
        fi
    done
fi

echo
echo "=== pending upgrades ==="
PENDING=$(apt list --upgradable 2>/dev/null | tail -n +2)
if [ -z "$PENDING" ]; then
    echo "  Nothing pending."
else
    echo "$PENDING" | sed 's/^/  /'
    echo
    if echo "$PENDING" | grep -qiE "^linux-(image|headers|libc-dev)|nvidia|libegl-nvidia"; then
        echo "  !! This upgrade touches the kernel and/or NVIDIA/EGL packages."
        echo "     Read docs/24-safe-system-updates.md before running 'apt upgrade' --"
        echo "     this is not a routine update, run post-update-verify.sh after rebooting."
    else
        echo "  None of this touches the kernel or NVIDIA/EGL -- routine, safe to upgrade anytime."
    fi
fi
