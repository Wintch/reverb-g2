#!/bin/bash
# handlab-session.sh -- one worn session on Aperture Hand Lab that answers three questions at once.
#
#   handlab-session.sh            # then touch /tmp/handlab.go when the wearer is ready
#
# docs/125. Aperture Hand Lab is Valve's own hand-tracking demo: both hands visible the whole
# time, at varying distances, with tasks that demand real precision. Its only previous run
# (2026-08-21) died to the companion USB2 re-enumeration that lab patch 0090 has since fixed
# (13/13 recoveries), so the title has never actually been evaluated on a working stack.
#
# What this session collects:
#   1. lab patch 0107's per-solve heading/gyro-bias telemetry -> scripts/slam-analysis/heading-bias.py
#      decides whether the heading noise is a stale bias (fixable) or white noise (branch dead).
#   2. A POSTURE A/B. docs/23's Blast the Past row: an aim-low title parks the hands with
#      IMU-only orientation WHILE constellation solves keep flowing in the log, because the
#      controllers sit under the cameras' FOV cone -- hands-up content on the same stack tracked
#      clean. Combined with the 50-75 cm range cliff, geometry may dominate the whole complaint.
#   3. The title's own real verdict on the current stack.
#
# The still phases are not padding. heading-bias.py fits its drift slope inside the quietest
# motion bin, and m_imu_3dof's bias estimator only ever fires while the controller is still --
# with no still stretches there is nothing to fit and nothing to re-estimate against.
set -u

APPID=868020
TS=$(date +%Y%m%d-%H%M%S)
OUT=/mnt/vrtmp/handlab-$TS
LOG=~/vr/logs/handlab-$TS.log
GO=/tmp/handlab.go
SEG=$OUT/segments.csv

mkdir -p "$OUT"
rm -f "$GO"

DASH_PID=$(pgrep -f "status-dashboard.py" | head -1)
[ -n "$DASH_PID" ] || { echo "dashboard not running, cannot borrow the GUI env"; exit 2; }
while IFS= read -r -d '' kv; do
	case "$kv" in
		WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|DISPLAY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_SESSION_TYPE=*|XAUTHORITY=*)
			export "${kv?}" ;;
	esac
done < "/proc/$DASH_PID/environ"

say() { espeak-ng -v es -s 145 "$*" >/dev/null 2>&1; }
mono_ns() { python3 -c 'import time;print(time.clock_gettime_ns(time.CLOCK_MONOTONIC))'; }
mark() { echo "$(mono_ns),$1" >> "$SEG"; }

# A dark room is the documented root cause of every runaway this project chased for weeks
# (see the Dali/Aircar drift work). Refuse to collect a session that will have to be thrown out.
if [ -x ~/Documents/reverb-g2/scripts/light-preflight.sh ]; then
	echo "== light preflight"
	bash ~/Documents/reverb-g2/scripts/light-preflight.sh 2>&1 | tail -6
fi

( cd ~/vr && ./jack-in-wayland.sh down >/dev/null 2>&1 )
sleep 3
: > "$LOG"
echo "ts,segment" > "$SEG"

export WMR_CONSTELLATION_CONTROLLERS=1
export WMR_CONTROLLER_HEADING_CSV="$OUT/heading"
export VR_DEMO_RECORD=1
export VR_LAUNCH_APPID=$APPID
export VR_DEMO_COMMENT="Aperture Hand Lab -- docs/125 posture A/B + heading telemetry"

{
	echo "=== Hand Lab session $TS ==="
	env | grep -E "^WMR_|^SLAM_|^VR_" | sort
	echo
	# 6dof explicitly: vr-launcher.py defaults argv[2] to "3dof", and in 3dof the controllers
	# have no position at all -- the entire session would measure nothing.
	python3 ~/Documents/reverb-g2/scripts/vr-launcher.py 1 6dof
	echo "=== launcher returned $? ==="
} >> "$LOG" 2>&1

# Controllers that registered as <none> mean Monado never saw them -- it has no hot-add, so
# plugging them in now would not help and the whole session would be zeros. Zeros from absent or
# sleeping controllers are NOT a result; this project has thrown out windows for exactly that.
# 2026-09-13: the first version of this guard grepped for a message format the launcher does
# not print, so it sailed past a session with only ONE controller registered. Match the line the
# launcher actually emits, and match the battery warning too -- LED brightness is a function of
# charge state (docs/46 measured the cell sagging under sustained constellation load), so a
# controller in the battery cliff zone makes every range and scale number unrepeatable.
if grep -q "Controles NO registrados" "$LOG" 2>/dev/null; then
	echo "!! Monado did not register every controller -- there is no hot-add, so this session"
	echo "   would be all zeros for the missing hand. Fresh batteries, both on, then re-run."
	grep -m1 "Controles NO registrados" "$LOG"
	exit 1
fi
if grep -qiE "BATTERY LOW|cliff zone" "$LOG" 2>/dev/null; then
	echo "!! A controller is in the battery cliff zone. LED brightness follows charge, so the"
	echo "   range and scale numbers this session exists to collect would not be repeatable."
	grep -m1 -iE "BATTERY LOW" "$LOG"
	exit 1
fi
grep -m1 "controles:" "$LOG" || true

say "Listo. Ponete el casco y avisame."
echo
echo "waiting for the wearer: touch $GO when the headset is on and Hand Lab is responding"
while [ ! -e "$GO" ]; do sleep 2; done

phase() { # phase <seconds> <name> <spoken>
	mark "start:$2"; say "$3"; sleep "$1"; mark "end:$2"; say "Pausa. Quedate quieto."; sleep 5
}

say "Empezamos. Cinco tramos, te voy diciendo."
sleep 3
phase 30 still-face   "Primero. Manos a la altura de la cara, delante tuyo, y quedate lo mas quieto que puedas."
phase 30 near-face    "Ahora. Manos a la altura de la cara, cerca, movelas despacio."
phase 30 far-reach    "Ahora. Estira los brazos todo lo que puedas, manos lejos. Movelas despacio."
phase 30 low-waist    "Ahora. Manos a la altura de la cintura, abajo. Movelas despacio."
phase 30 still-low    "Ahora. Manos abajo otra vez, pero quietas."
mark "start:free"
say "Ultimo tramo. Jugá el demo normal, hacé lo que te pida. Avisame cuando termines."
echo "free-play segment started; stop it with: vr-launcher.py stop all"
echo
echo "heading CSVs: $OUT/heading-left.csv  $OUT/heading-right.csv"
echo "segments:     $SEG"
