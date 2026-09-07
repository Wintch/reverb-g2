#!/bin/bash
# Does the VIO drift while the headset is COMPLETELY STILL?
#
#   static-drift.sh [seconds]
#
# 2026-09-07: every worn session that day showed physically impossible position ranges (up to
# 6.7 m of VERTICAL travel), bounded only by the session-anchor guard. This splits that in two
# without costing a wearer pass:
#   * drifts while stationary -> IMU bias / gravity alignment / integration, nothing to do with
#     the wearer or the room
#   * stays put -> the drift is produced by motion, so extrinsics or scale
#
# Runs the SAME tracking config the booth profile now ships (density 30/2 through the
# SLAM_G2_CONFIG_FILE hook, 6 threads, anchor 300) so the answer applies to the booth, and drives
# it with hello_xr because Basalt only processes frames while an OpenXR client holds a session.
# SLAM_WRITE_CSVS gives the pose trace to measure afterwards.
set -u
SECS="${1:-180}"
HELLO=~/vr/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr
PHOTO=~/Documents/linux_vr_base/photo360/testgrid.png
LOG=~/vr/jack-in-wayland.log
OUT=/mnt/vrtmp/static-drift-$(date +%Y%m%d-%H%M%S)
SPEAK=~/Documents/reverb-g2/scripts/speak.sh

DASH_PID=$(pgrep -f "status-dashboard.py" | head -1)
[ -n "$DASH_PID" ] || { echo "dashboard not running, cannot borrow the GUI env"; exit 2; }
while IFS= read -r -d '' kv; do
	case "$kv" in
		WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|DISPLAY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_SESSION_TYPE=*|XAUTHORITY=*)
			export "${kv?}" ;;
	esac
done < "/proc/$DASH_PID/environ"

cleanup() {
	pkill -x hello_xr 2>/dev/null
	sleep 1
	( cd ~/vr && ./jack-in-wayland.sh down >/dev/null 2>&1 )
}
cleanup
sleep 3
: > "$LOG"
mkdir -p "$OUT"

cd ~/vr
env VIT_COLLAPSE_LOG=1 \
    SLAM_G2_CONFIG_FILE="$HOME/vr/basalt-g2-config-d30x2.json" \
    SLAM_THREADS=6 \
    SLAM_SESSION_ANCHOR_RADIUS_CM=300 \
    SLAM_QUAT_NORM_CHECK=1 \
    SLAM_WRITE_CSVS=1 \
    SLAM_CSV_PATH="$OUT/" \
    WMR_CONSTELLATION_CONTROLLERS=0 \
    setsid nohup ./jack-in-wayland.sh dev 1 6dof > /tmp/static-drift.out 2>&1 < /dev/null &

for _ in $(seq 1 60); do
	[ -S /run/user/1000/monado_comp_ipc ] && break
	sleep 2
done
[ -S /run/user/1000/monado_comp_ipc ] || { echo "!! compositor never came up"; tail -15 /tmp/static-drift.out; exit 1; }

XR_RUNTIME_JSON=~/vr/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 \
	HELLO_XR_PHOTO360="$PHOTO" \
	setsid nohup "$HELLO" --graphics Vulkan2 > /tmp/static-drift-client.out 2>&1 < /dev/null &

for _ in $(seq 1 45); do
	grep -q "vit_of " "$LOG" 2>/dev/null && break
	sleep 2
done
grep -q "vit_of " "$LOG" 2>/dev/null || {
	echo "!! no vit_of lines -- client out:"; tail -12 /tmp/static-drift-client.out; cleanup; exit 1; }

echo "TRACKING, do not touch the headset for ${SECS}s"
"$SPEAK" "Tracking en marcha. No toques el casco." >/dev/null 2>&1
sleep "$SECS"

cleanup
echo "CSV: $OUT"
grep -c "Tracker diverged" "$LOG" 2>/dev/null | sed 's/^/guard trips: /'
"$SPEAK" "Prueba estatica terminada." >/dev/null 2>&1
