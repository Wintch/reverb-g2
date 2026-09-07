#!/bin/bash
# Static drift trace, through the path that provably writes SLAM CSVs.
#
#   static-recorded.sh [seconds]
#
# The hand-rolled static-drift.sh reproduces the finding (4 guard trips in 180 s with nobody
# touching the headset) but leaves SLAM_CSV_PATH empty, so there is no trace to read the SHAPE of
# the drift from. vr-launcher + VR_DEMO_RECORD=1 is the one path observed to produce
# tracking/filtering/prediction CSVs today, so use it and simply do not wear the headset.
#
# No env overrides on purpose: this runs exactly TITLE_PROFILES["591360"] as now shipped
# (scale 85, density 30/2, 6 threads, anchor 300), so the trace describes the booth config.
set -u
SECS="${1:-180}"
LOG=~/vr/jack-in-wayland.log
SPEAK=~/Documents/reverb-g2/scripts/speak.sh

DASH_PID=$(pgrep -f "status-dashboard.py" | head -1)
[ -n "$DASH_PID" ] || { echo "dashboard not running, cannot borrow the GUI env"; exit 2; }
while IFS= read -r -d '' kv; do
	case "$kv" in
		WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|DISPLAY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_SESSION_TYPE=*|XAUTHORITY=*)
			export "${kv?}" ;;
	esac
done < "/proc/$DASH_PID/environ"

pkill -x hello_xr 2>/dev/null
( cd ~/vr && ./jack-in-wayland.sh down >/dev/null 2>&1 )
sleep 3
: > "$LOG"

cd ~/vr
env VR_LAUNCH_APPID=591360 \
    U_PACING_APP_LOG=debug \
    VIT_COLLAPSE_LOG=1 \
    VR_DEMO_RECORD=1 \
    VR_DEMO_COMMENT="STATIC drift trace -- headset untouched on the desk, booth profile as shipped" \
    setsid nohup python3 ./vr-launcher.py 1 6dof > /tmp/static-recorded.out 2>&1 < /dev/null &

for _ in $(seq 1 90); do
	a=$(grep -c "Delivered frame" "$LOG" 2>/dev/null); a=${a:-0}
	sleep 3
	b=$(grep -c "Delivered frame" "$LOG" 2>/dev/null); b=${b:-0}
	[ "$((b - a))" -ge 200 ] && break
done
if [ "$((b - a))" -lt 200 ]; then
	echo "!! never reached a steady frame rate"; tail -15 /tmp/static-recorded.out; exit 1
fi

echo "TRACKING (recorded). Headset must stay untouched for ${SECS}s"
"$SPEAK" "No toques el casco." >/dev/null 2>&1
sleep "$SECS"

# Let the recorder close the session so it persists the CSVs.
pkill -x DreamsOfDali 2>/dev/null
sleep 8
( cd ~/vr && ./jack-in-wayland.sh down >/dev/null 2>&1 )
sleep 5
grep -c "Tracker diverged" "$LOG" 2>/dev/null | sed 's/^/guard trips: /'
ls -dt ~/vr/logs/demo-sessions/*/ | head -1
"$SPEAK" "Listo." >/dev/null 2>&1
