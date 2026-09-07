#!/bin/bash
# One arm of the donning-position A/B.
#
#   don-ab.sh <desk|propped> [worn_seconds]
#
# Hypothesis under test: the approved operator rule has the headset LYING ON THE DESK while the
# title loads, which is the one scene measured (2026-09-07) to make the tracker invent tens of
# metres of phantom motion -- and Basalt both initialises AND captures its session anchor there.
# The candidate fix is purely operational: prop it FACING THE ROOM for the same period.
#
# The script itself is identical for both arms; only where the operator puts the headset differs.
# It records a CLOCK_MONOTONIC marker at the summon so the worn segment can be separated from the
# pre-don segment in the pose CSVs afterwards.
#
# Runs TITLE_PROFILES["591360"] exactly as shipped -- no env overrides, so the answer applies to
# the booth as configured.
set -u
ARM="${1:?usage: don-ab.sh <desk|propped> [worn_seconds]}"
WORN="${2:-240}"
SETTLE=30
LOG=~/vr/jack-in-wayland.log
SPEAK=~/Documents/reverb-g2/scripts/speak.sh
MARK=/tmp/don-ab-$ARM.mark

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
    VR_DEMO_COMMENT="donning A/B arm=$ARM -- headset $ARM during load, booth profile as shipped" \
    setsid nohup python3 ./vr-launcher.py 1 6dof > "/tmp/don-ab-$ARM.out" 2>&1 < /dev/null &

b=0; a=0
for _ in $(seq 1 90); do
	a=$(grep -c "Delivered frame" "$LOG" 2>/dev/null); a=${a:-0}
	sleep 3
	b=$(grep -c "Delivered frame" "$LOG" 2>/dev/null); b=${b:-0}
	[ "$((b - a))" -ge 200 ] && break
done
if [ "$((b - a))" -lt 200 ]; then
	echo "!! never reached a steady frame rate"; tail -15 "/tmp/don-ab-$ARM.out"
	"$SPEAK" "La sesion no arranco." >/dev/null 2>&1
	exit 1
fi

# Same pre-don tracking exposure in both arms, so the only difference is WHERE the headset was.
echo "loaded; holding ${SETTLE}s with the headset $ARM"
sleep "$SETTLE"

python3 -c "import time; print(time.clock_gettime_ns(time.CLOCK_MONOTONIC))" > "$MARK"
echo "SUMMON at monotonic $(cat "$MARK")"
"$SPEAK" "Jack in. Ponete el casco." >/dev/null 2>&1

sleep "$WORN"
"$SPEAK" "Listo, sali cuando quieras." >/dev/null 2>&1
sleep 12

pkill -x DreamsOfDali 2>/dev/null
sleep 8
( cd ~/vr && ./jack-in-wayland.sh down >/dev/null 2>&1 )
sleep 5

echo "--- arm $ARM done"
grep -c "Tracker diverged" "$LOG" 2>/dev/null | sed 's/^/total guard trips (whole session): /'
echo "pre-don trips (before the summon):"
awk -v m="$(cat "$MARK")" '/Tracker diverged/ { if (match($0, /at ts=[0-9]+/)) { t = substr($0, RSTART+6, RLENGTH-6) + 0; if (t < m) n++ } } END { print "  " n+0 }' "$LOG"
