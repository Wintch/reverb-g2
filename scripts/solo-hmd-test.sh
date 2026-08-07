#!/bin/bash
# 90Hz test with the headset as the ONLY active display.
# Restores the desktop layout no matter what happens (trap EXIT).
# The user is left without a screen for the duration: the restore is automatic.

export DISPLAY=:0
LOOK_SECONDS="${1:-120}"
STAMP=/home/iam/vr/solo-hmd-test.status

log() { echo "[$(date +%H:%M:%S)] $*" >> "$STAMP"; }

restore_desktop() {
    log "RESTORE: killing VR session"
    for p in $(pgrep -f "hello[_]xr"); do kill "$p" 2>/dev/null; done
    sleep 2
    for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
    sleep 3
    rm -f /run/user/1000/monado_comp_ipc

    log "RESTORE: restoring the three monitors"
    xrandr --output HDMI-1 --mode 1920x1080 --rate 60 --pos 0x0 --rotate normal \
           --output DP-3   --mode 1920x1080 --rate 60 --pos 1920x0 --rotate right --primary \
           --output HDMI-0 --mode 1920x1080 --rate 143.98 --pos 3000x0 --rotate normal 2>>"$STAMP"
    sleep 2

    # Cycle the portrait rotation: xrandr REPORTS "right" even though the panel shows
    # landscape after a direct-mode. In KDE the one that actually applies it is kscreen-doctor.
    log "RESTORE: cycling DP-3 rotation"
    xrandr --output DP-3 --rotate normal 2>>"$STAMP"; sleep 1
    xrandr --output DP-3 --rotate right  2>>"$STAMP"; sleep 1
    if command -v kscreen-doctor >/dev/null 2>&1; then
        kscreen-doctor output.DP-3.rotation.right >>"$STAMP" 2>&1 || true
    fi
    log "RESTORE: done"
    xrandr --query 2>/dev/null | grep -E " connected" >> "$STAMP"
}
trap restore_desktop EXIT

: > "$STAMP"
log "START - the headset remains the only display for ~${LOOK_SECONDS}s"

# 1. Turn off the ENTIRE desktop: frees the last 60 Hz clock domain
xrandr --output HDMI-0 --off --output HDMI-1 --off --output DP-3 --off 2>>"$STAMP"
sleep 2
log "desktop off; active displays:"
xrandr --query 2>/dev/null | grep -E " connected [0-9]" >> "$STAMP"

# 2. Start Monado at native 90 Hz
cd /home/iam/vr || exit 1
rm -f /run/user/1000/monado_comp_ipc
XRT_COMPOSITOR_LOG=debug XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof >>"$STAMP" 2>&1
log "jack-in finished; mode taken:"
grep -E "found display mode" /home/iam/vr/jack-in.log | tail -2 >> "$STAMP"

# 3. Launch the 360 viewer
sleep 900 | XR_RUNTIME_JSON=/home/iam/vr/monado/build/openxr_monado-dev.json \
    IPC_IGNORE_VERSION=1 VK_LOADER_LAYERS_DISABLE='*' \
    HELLO_XR_PHOTO360=/home/iam/vr/media/test-equirect.jpg \
    ./OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr --graphics Vulkan2 \
    > /home/iam/vr/hello_xr.log 2>&1 &

sleep 10
log "viewer launched. LOOK INSIDE THE HEADSET NOW."
grep -cE "BEGIN_SESSION" /home/iam/vr/jack-in.log >> "$STAMP"

# 4. Window for the user to look, then automatic restore via trap
sleep "$LOOK_SECONDS"
log "end of observation window"
