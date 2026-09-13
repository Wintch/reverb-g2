#!/bin/bash
# record-euroc.sh -- capture ONE reference EuRoC dataset (cameras + IMU) so that every future
# SLAM/prediction config can be compared offline, headless, against the SAME head motion.
#
#   record-euroc.sh [name]
#
# Why this exists (2026-09-13): tuning SLAM_PRED_* knobs used to cost one worn session PER VALUE,
# and each session had different head motion, so the arms were never a controlled A/B -- the
# 4-arm SLAM_PRED_NECK_ARM_MM sweep that day had to bin by angular rate just to be comparable at
# all. Monado's euroc player (EUROC_PATH + EUROC_HMD) replays a recorded dataset through the REAL
# tracker, so one recording feeds unlimited headless config runs with identical input. Offline
# reimplementation of the prediction math is NOT an option: it consumes the raw gyro FIFO, which
# no CSV contains.
#
# The routine below is spoken over the machine's own speakers, so the wearer just follows the
# voice. Segments are chosen to cover every regime the prediction knobs act on: rest (error
# floor), yaw at three speeds (the neck-arm overshoot regime), pitch (the vertical-swing regime),
# and real translation (the FREEZE_POSITION / SLAM_PRED_POSITION_HORIZON_MS regime, which the
# 09-13 sweep never exercised deliberately).
#
# Wear it for this one recording if at all possible: the neck-arm model is about rotation around
# a real neck pivot, and hand-held motion does not reproduce that geometry.
set -u
NAME="${1:-headref}"
HELLO=~/vr/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr
PHOTO=~/Documents/linux_vr_base/photo360/testgrid.png
LOG=~/vr/jack-in-wayland.log
SPEAK=~/Documents/reverb-g2/scripts/speak.sh
DSDIR=/mnt/resolve_test/g2-datasets
CSV=/mnt/vrtmp/record-euroc-$(date +%Y%m%d-%H%M%S)
# The routine does not start on a timer: the wearer may still be donning, and a rushed start
# wastes the take (2026-09-13, first attempt). It blocks here until this file is non-empty.
GO=/tmp/record-euroc.go

mkdir -p "$DSDIR" "$CSV"

say() { echo ">> $*"; "$SPEAK" "$*" >/dev/null 2>&1; }

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

cd ~/vr
# Same tracking config the booth profile ships, so the dataset is representative of it. The
# prediction knobs are deliberately left at their defaults here -- they act AFTER the tracker and
# do not affect what gets recorded; they are what the replays will sweep.
env VIT_COLLAPSE_LOG=1 \
    SLAM_G2_CONFIG_FILE="$HOME/vr/basalt-g2-config-d30x2.json" \
    SLAM_THREADS=6 \
    SLAM_SESSION_ANCHOR_RADIUS_CM=300 \
    SLAM_QUAT_NORM_CHECK=1 \
    SLAM_WRITE_CSVS=1 \
    SLAM_CSV_PATH="$CSV/" \
    EUROC_RECORD=1 \
    EUROC_RECORD_PATH="$DSDIR/$NAME" \
    EUROC_RECORDER_USE_JPG=1 \
    WMR_CONSTELLATION_CONTROLLERS=0 \
    setsid nohup ./jack-in-wayland.sh dev 1 6dof > /tmp/record-euroc.out 2>&1 < /dev/null &

for _ in $(seq 1 60); do
	[ -S /run/user/1000/monado_comp_ipc ] && break
	sleep 2
done
[ -S /run/user/1000/monado_comp_ipc ] || { echo "!! compositor never came up"; tail -15 /tmp/record-euroc.out; exit 1; }

XR_RUNTIME_JSON=~/vr/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 \
	HELLO_XR_PHOTO360="$PHOTO" \
	setsid nohup "$HELLO" --graphics Vulkan2 > /tmp/record-euroc-client.out 2>&1 < /dev/null &

for _ in $(seq 1 45); do
	grep -q "vit_of " "$LOG" 2>/dev/null && break
	sleep 2
done
grep -q "vit_of " "$LOG" 2>/dev/null || {
	echo "!! no vit_of lines -- client out:"; tail -12 /tmp/record-euroc-client.out; cleanup; exit 1; }

> "$GO"
say "Jack in. Ponete el casco tranquilo. Espero tu senal."
echo ">> WAITING: touch $GO when the wearer is ready (recording is live, keep it short)"
for _ in $(seq 1 600); do
	[ -s "$GO" ] && break
	sleep 1
done
[ -s "$GO" ] || { say "Se acabo la espera."; cleanup; echo "!! never got the go signal"; exit 1; }

say "Empezamos en tres. Dos. Uno."
sleep 3

# phase <seconds> <spoken instruction>
phase() { say "$2"; sleep "$1"; }

phase 12 "Quieto, mirando al frente."
phase 20 "Giros lentos a izquierda y derecha."
phase 20 "Giros moderados, mas rapido."
phase 20 "Giros rapidos, sacudi la cabeza a los costados."
phase 15 "Ahora mira arriba y abajo, lento."
phase 15 "Arriba y abajo, rapido."
phase 30 "Camina hacia adelante y hacia atras, tranquilo."
phase 20 "Camina de costado, izquierda y derecha."
phase 25 "Movimiento libre, mezcla todo."
phase 12 "Ultimo tramo. Quieto otra vez."

say "Listo. Grabacion terminada, ya podes sacarte el casco."
cleanup
sleep 2

DS=$(ls -dt "$DSDIR/${NAME}"_* 2>/dev/null | head -1)
echo
echo "dataset: $DS"
[ -n "$DS" ] && du -sh "$DS" && ls "$DS"
echo "session CSVs: $CSV"
grep -c "Tracker diverged" "$LOG" 2>/dev/null | sed 's/^/guard trips: /'
