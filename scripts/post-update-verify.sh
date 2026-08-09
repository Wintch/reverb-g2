#!/bin/bash
# Run AFTER an update that touched the kernel or NVIDIA/EGL packages, and after rebooting.
# Refuses to say "OK" if any check fails. Logs passing is necessary but NOT sufficient --
# still put the headset on and run a real jack-in-wayland.sh 90Hz session before trusting
# it, per this project's core verification rule (docs/24-safe-system-updates.md).
#
#   ./scripts/post-update-verify.sh

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAIL=0

echo "=== 1/5: did the reboot actually pick up the new kernel? ==="
CURRENT=$(uname -r)
LATEST=$(dpkg -l 'linux-image-6.*-amd64' 2>/dev/null | awk '/^ii/{print $2}' | sed 's/linux-image-//' | sort -V | tail -1)
echo "  running: $CURRENT"
echo "  newest installed: $LATEST"
if [ "$CURRENT" = "$LATEST" ]; then
    echo "  OK: running the newest installed kernel."
else
    echo "  !! Running an OLDER kernel than what's installed -- the reboot may not have"
    echo "     picked the new one (stale GRUB default has bitten this project before,"
    echo "     see docs/06-known-issues.md). Check the GRUB default entry."
    FAIL=1
fi

echo
echo "=== 2/5: does DKMS show the module installed for THIS running kernel? ==="
DKMS_BIN="/usr/sbin/dkms"
[ -x "$DKMS_BIN" ] || DKMS_BIN="dkms"
if "$DKMS_BIN" status 2>&1 | grep -q "$CURRENT.*installed"; then
    echo "  OK: nvidia module installed for $CURRENT."
else
    echo "  !! No installed nvidia module found for the running kernel ($CURRENT)."
    "$DKMS_BIN" status 2>&1 | sed 's/^/     /'
    FAIL=1
fi

echo
echo "=== 3/5: all 4 patches applied cleanly in the FRESH build log? ==="
LOG=$(find /var/lib/dkms/nvidia -path "*$CURRENT*" -iname "make.log" 2>/dev/null | sort | tail -1)
if [ -z "$LOG" ]; then
    echo "  !! No build log found for $CURRENT."
    FAIL=1
else
    echo "  log: $LOG"
    for p in \
        "0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch" \
        "0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch" \
        "0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch" \
        "0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch"; do
        if grep -q "Applying patch $p" "$LOG"; then
            echo "  OK: $p"
        else
            echo "  !! MISSING: $p -- this build does NOT have the tracked patch series."
            FAIL=1
        fi
    done
    # Don't grep bare "reject|FAILED" -- it false-positives on mangled C++ symbol names
    # (messageFailed, RejectedByHW, mstEdidReadFailed...) in harmless objtool warning
    # lines, which are unrelated to whether the patches applied or the build succeeded.
    # Check the actual patch-apply and make outcomes instead.
    if grep -qiE "^[0-9]+ out of [0-9]+ hunks? FAILED|\*\*\* [Rr]eject|can't find file to patch" "$LOG"; then
        echo "  !! The build log shows a real patch-apply failure -- read it in full before trusting anything:"
        echo "     $LOG"
        FAIL=1
    elif ! grep -q "^# exit code: 0$" "$LOG"; then
        echo "  !! The build log's own exit code isn't 0 -- read it in full before trusting anything:"
        echo "     $LOG"
        FAIL=1
    fi
fi

echo
echo "=== 4/5: verify-bpc.sh (the load-bearing 90Hz patch) ==="
if [ -x "$HERE/verify-bpc.sh" ]; then
    "$HERE/verify-bpc.sh" || FAIL=1
else
    echo "  !! scripts/verify-bpc.sh not found or not executable."
    FAIL=1
fi

echo
echo "=== 5/5: preflight.sh (USB / controllers / HMD connector) ==="
if [ -x "$HERE/preflight.sh" ]; then
    "$HERE/preflight.sh" || FAIL=1
else
    echo "  !! scripts/preflight.sh not found or not executable."
    FAIL=1
fi

echo
if [ "$FAIL" = 0 ]; then
    echo "=== All automated checks passed. Logs are clean -- that's necessary, not sufficient. ==="
    echo "Put the headset on and run a real jack-in-wayland.sh 1 6dof session with real"
    echo "content before considering this update trusted. If it doesn't look right, roll"
    echo "back per docs/24-safe-system-updates.md, don't keep debugging live."
    exit 0
else
    echo "=== FAILED one or more checks above. Do NOT trust VR on this build. ==="
    echo "Roll back to the previous kernel (GRUB -> Advanced options) per docs/24, then"
    echo "debug this kernel/driver combination without time pressure."
    exit 1
fi
