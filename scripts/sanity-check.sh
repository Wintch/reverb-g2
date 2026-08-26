#!/bin/bash
# Layered environment sanity check. Three independent stages, run separately so a failure
# in one doesn't get blamed on the wrong layer -- "OS+drivers is fine but Steam's runtime
# order is wrong" is a very different problem from "OS+drivers is broken", and mixing them
# in one pass/fail wastes a debugging session (see docs/73-nvidia-symlink-drift.md, T174 in
# CLAUDE.md's traps section, and docs/20 -- all three were previously diagnosed by hand,
# this turns those into a repeatable check).
#
#   ./scripts/sanity-check.sh            all three stages
#   ./scripts/sanity-check.sh os         kernel/dkms/NVIDIA packaging/GLX only
#   ./scripts/sanity-check.sh soft       Steam + OpenXR/OpenVR runtime routing only
#   ./scripts/sanity-check.sh vr         headset/controllers/Monado/Basalt only (needs hardware)
#
# Doesn't start Monado, doesn't need root. Safe to run repeatedly and at any time.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VR="$(cd "$HERE/.." && pwd)"
[ -d "$HOME/vr/monado" ] && VR="$HOME/vr"

STAGE="${1:-all}"
FAIL=0

stage_os() {
echo "############ STAGE 1/3: OS + drivers ############"

echo
echo "=== kernel / DKMS ==="
CURRENT="$(uname -r)"
echo "  running: $CURRENT"
if command -v dkms >/dev/null 2>&1; then DKMS_BIN=dkms; else DKMS_BIN=/usr/sbin/dkms; fi
if "$DKMS_BIN" status 2>&1 | grep -q "$CURRENT.*installed"; then
    echo "  READY: nvidia module installed for the running kernel."
else
    echo "  NOT READY: no nvidia module installed for $CURRENT."
    "$DKMS_BIN" status 2>&1 | sed 's/^/    /'
    FAIL=1
fi

echo
echo "=== the 4 project patches (90Hz fix included) ==="
DKMS_CONF="/usr/src/nvidia-$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)/dkms.conf"
MISSING=0
for p in \
    "0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch" \
    "0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch" \
    "0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch" \
    "0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch"; do
    grep -q "$p" "$DKMS_CONF" 2>/dev/null || MISSING=1
done
if [ -f "$DKMS_CONF" ] && [ "$MISSING" = 0 ]; then
    echo "  READY: all 4 PATCH[] lines present in $DKMS_CONF."
else
    echo "  NOT READY: $DKMS_CONF missing or missing patch lines. See docs/04-lab-90hz.md."
    echo "  -> DO NOT 'apt-get install --reinstall nvidia-kernel-open-dkms' to fix this --"
    echo "     that restores Debian's stock dkms.conf and DELETES these lines. Re-run"
    echo "     'bootstrap-lab.sh patch-nv' instead."
    FAIL=1
fi

echo
echo "=== package integrity (dpkg -V), non-conffile drift ==="
DRIFT=$(dpkg -V 2>&1 | grep -v '^..5?????? c ' | grep -v '^????????? c ' | grep -v '/usr/src/nvidia-.*/dkms.conf$')
if [ -z "$DRIFT" ]; then
    echo "  READY: no unexplained drift."
else
    echo "$DRIFT" | sed 's/^/    /'
    echo "  NOT READY: files above are owned by a package per dpkg but missing/corrupted on"
    echo "  disk. Find the owner with 'dpkg -S <path>', reinstall with"
    echo "  'apt-get install --reinstall <pkg>'. See docs/73-nvidia-symlink-drift.md."
    FAIL=1
fi

echo
echo "=== display session + GLX ==="
SESSION_TYPE="${XDG_SESSION_TYPE:-}"
if [ -z "$SESSION_TYPE" ]; then
    SID=$(loginctl list-sessions --no-legend 2>/dev/null | awk '$3=="seat0"{print $1}' | head -1)
    [ -n "$SID" ] && SESSION_TYPE=$(loginctl show-session "$SID" -p Type --value 2>/dev/null)
fi
echo "  session type: ${SESSION_TYPE:-unknown}"
if [ "$SESSION_TYPE" = "x11" ]; then
    if [ -r /var/log/Xorg.0.log ] && grep -q "Module glxserver_nvidia: vendor=\"NVIDIA Corporation\"" /var/log/Xorg.0.log \
       && ! grep -q "Failed to load module \"glxserver_nvidia\"" /var/log/Xorg.0.log; then
        echo "  READY: NVIDIA GLX module loaded in the current Xorg session."
    else
        echo "  NOT READY: NVIDIA GLX module did not load cleanly. Check /var/log/Xorg.0.log"
        echo "  for '(EE) NVIDIA: Failed to load module \"glxserver_nvidia\"'."
        echo "  See docs/73-nvidia-symlink-drift.md."
        FAIL=1
    fi
elif [ "$SESSION_TYPE" = "wayland" ]; then
    echo "  Wayland session -- GLX is X11-only, not applicable. Use check-lease.sh for the"
    echo "  Wayland DRM-lease path instead."
else
    echo "  Could not determine session type -- skipping GLX check."
fi

echo
echo "=== GPU visible to the driver ==="
if nvidia-smi --query-gpu=driver_version --format=csv,noheader >/dev/null 2>&1; then
    echo "  READY: nvidia-smi reports driver $(nvidia-smi --query-gpu=driver_version --format=csv,noheader)."
else
    echo "  NOT READY: nvidia-smi failed."
    FAIL=1
fi
}

stage_soft() {
echo "############ STAGE 2/3: general software (Steam / OpenXR-OpenVR routing) ############"

echo
echo "=== Steam installed ==="
if command -v steam >/dev/null 2>&1; then
    echo "  READY: $(command -v steam)"
else
    echo "  NOT READY: steam not found on PATH."
    FAIL=1
fi

echo
echo "=== OpenVR runtime routing (openvrpaths.vrpath) ==="
# The T174 trap (CLAUDE.md): OpenVR takes the FIRST entry of "runtime". If SteamVR-native
# ends up ahead of xrizer, every OpenVR title silently falls back to flat rendering with
# audio still routed to the headset -- looks alive, isn't tracked.
VRPATH="$HOME/.config/openvr/openvrpaths.vrpath"
if [ -f "$VRPATH" ]; then
    FIRST_RUNTIME=$(jq -r '.runtime[0] // empty' "$VRPATH" 2>/dev/null)
    echo "  first runtime entry: ${FIRST_RUNTIME:-<none>}"
    if echo "$FIRST_RUNTIME" | grep -qi "xrizer"; then
        echo "  READY: xrizer is first -- OpenVR titles will render in the headset."
    else
        echo "  NOT READY: xrizer is NOT first (or missing). OpenVR titles will silently"
        echo "  render flat/2D while audio still plays in the headset. Fix: edit $VRPATH"
        echo "  so xrizer's path is runtime[0], or reinstall/re-register it ahead of SteamVR."
        FAIL=1
    fi
else
    echo "  NOT READY: $VRPATH does not exist -- no OpenVR runtime registered at all."
    FAIL=1
fi
}

stage_vr() {
echo "############ STAGE 3/3: VR stack (headset/controllers/Monado/Basalt) ############"
echo "  Needs the headset physically connected and powered."
echo

echo "=== Monado build (SteamVR driver) ==="
if [ -x "$VR/monado/build/steamvr-monado/bin/linux64/monado-service" ] || [ -f "$VR/monado/build/steamvr-monado/driver.vrdrivermanifest" ]; then
    echo "  READY: $VR/monado/build/steamvr-monado present."
else
    echo "  NOT READY: no steamvr-monado build found under $VR/monado/build."
    FAIL=1
fi

echo
echo "=== Basalt build (SLAM/6dof) ==="
if [ -e "$VR/basalt/build/libbasalt.so" ]; then
    echo "  READY: $VR/basalt/build/libbasalt.so present (checked as a real file, not just"
    echo "  the directory -- docs/06's T060 trap)."
else
    echo "  NOT READY: $VR/basalt/build/libbasalt.so missing. 6dof will not be available"
    echo "  even if 3dof works. See docs/06-known-issues.md, T060."
    FAIL=1
fi

echo
echo "=== USB / controllers / DP connector (delegating to preflight.sh) ==="
if [ -x "$HERE/preflight.sh" ]; then
    "$HERE/preflight.sh" || FAIL=1
else
    echo "  NOT READY: $HERE/preflight.sh not found."
    FAIL=1
fi
}

case "$STAGE" in
    os)   stage_os ;;
    soft) stage_soft ;;
    vr)   stage_vr ;;
    all)  stage_os; echo; stage_soft; echo; stage_vr ;;
    *) echo "Usage: $0 [os|soft|vr|all]" >&2; exit 2 ;;
esac

echo
if [ "$FAIL" = 0 ]; then
    echo "=== OVERALL: READY ==="
else
    echo "=== OVERALL: NOT READY -- see NOT READY lines above ==="
fi
exit "$FAIL"
