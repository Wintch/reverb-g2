#!/bin/bash
# play360.sh - show a 360 / VR180 / flat video or photo in the headset.
#
#   ./play360.sh video.mp4              play it on a loop (5 minutes, then quit)
#   ./play360.sh folder/                play every video in the folder, one after another
#   ./play360.sh -t 60 video.mp4        play for 60 seconds
#   ./play360.sh -s foto.jpg            a still photo instead of a video
#   ./play360.sh -p 180 -e sbs v.mp4    force the projection / stereo layout
#   ./play360.sh -f 180x180 v.mp4       force the arc the 180 frame covers
#   ./play360.sh -w 45 v.mp4            width of the virtual screen, in degrees (flat mode)
#   ./play360.sh -q video.mp4           without the per-second timing stats
#
# The player prints what it detected before drawing anything:
#
#     MODE: VR180 3D (side-by-side)
#     File: 7680x4096  ->  3840x4096 per eye  |  59.94 fps  |  av1
#
# If that line is wrong the picture will still look plausible - a VR180 file read as 360 just
# looks like a strangely cropped panorama - so check it before blaming the footage. Override
# with -p (360 | 180 | flat) and -e (mono | sbs | tb).
#
# Transport keys (they need this script run from a real terminal, not piped or backgrounded -
# the player reads them from stdin):
#
#   space    pause / resume            (controller: trigger)
#   [  ]     slower / faster (0.125x .. 4x)
#   1        normal speed
#   h  l     seek -10s / +10s          (controller: stick X)
#   up down  zoom in / out             (controller: stick Y) - or ^ v as a keyboard fallback
#   0        zoom back to 1x (off)
#   b  d     brighter / dimmer          (controller: A/B, right hand)
#   9        brightness back to 1x (off)
#   enter    recenter "forward"        (controller: squeeze grip hard)
#   n        next video in the playlist  (controller: Y, left hand)
#   q        quit                      (controller: hold left menu ~1.5s, red bar)
#
# HELLO_XR_THEME=night paints the empty space outside the video black (default: light gray).
#
# Requires the stack to be up: ./jack-in.sh 3dof

set -u

# Where the trees live. The main system has them at ~/Documents/linux_vr_base; the lab
# (bootstrap-lab.sh) at ~/vr. Same auto-detection as jack-in.sh — until 2026-08-04 this was
# hardcoded to the main system and failed on the lab with "hello_xr needs to be built". VR_BASE=...
# forces it.
if [ -n "${VR_BASE:-}" ]; then
	:
elif [ -d "$HOME/Documents/linux_vr_base/monado/build" ]; then
	VR_BASE="$HOME/Documents/linux_vr_base"
else
	VR_BASE="$HOME/vr"
fi
MONADO_BUILD="$VR_BASE/monado/build"
HELLO_XR="$VR_BASE/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr"

SECONDS_TO_RUN=300
PHOTO=0
STATS=1
ENV_EXTRA=()

while getopts "t:sp:e:f:w:qh" opt; do
	case "$opt" in
		t) SECONDS_TO_RUN="$OPTARG" ;;
		s) PHOTO=1 ;;
		p) ENV_EXTRA+=("HELLO_XR_PROJECTION=$OPTARG") ;;
		e) ENV_EXTRA+=("HELLO_XR_STEREO=$OPTARG") ;;
		f) ENV_EXTRA+=("HELLO_XR_PANO_FOV=$OPTARG") ;;
		w) ENV_EXTRA+=("HELLO_XR_SCREEN_FOV=$OPTARG") ;;
		q) STATS=0 ;;
		h|*) sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
	esac
done
shift $((OPTIND - 1))

if [ $# -lt 1 ]; then
	echo "usage: $0 [-t SECONDS] [-s] [-p 360|180|flat] [-e mono|sbs|tb] [-f AxB] [-w DEGREES] [-q] <file>" >&2
	exit 1
fi
FILE="$1"
# A directory is a playlist: every video in it plays in turn, sorted by name, wrapping at the
# end. A single file loops forever instead.
[ -e "$FILE" ] || { echo "does not exist: $FILE" >&2; exit 1; }
[ -f "$FILE" ] || [ -d "$FILE" ] || { echo "is neither a file nor a directory: $FILE" >&2; exit 1; }
FILE=$(readlink -f "$FILE")

[ -x "$HELLO_XR" ] || { echo "hello_xr needs to be built ($HELLO_XR)" >&2; exit 1; }
if ! pgrep -f "targets/service/monado-service" >/dev/null; then
	echo "Monado isn't running. Bring the stack up first:  ./jack-in.sh 3dof" >&2
	exit 1
fi

if [ "$PHOTO" = "1" ]; then
	ENV_EXTRA+=("HELLO_XR_PHOTO360=$FILE")
else
	ENV_EXTRA+=("HELLO_XR_VIDEO360=$FILE")
fi
[ "$STATS" = "1" ] && ENV_EXTRA+=("HELLO_XR_VIDEO_STATS=1")

# IPC_IGNORE_VERSION is needed because hello_xr was built against an older Monado than the
# service (client v25.1.0-706 vs service v25.1.0-708).
#
# Two launch modes, because the transport keys need the real terminal on stdin:
#
#  - Interactive terminal: hand hello_xr the tty so espacio/[/]/n/q work, with `timeout
#    --foreground` as the time bound (--foreground keeps it in the tty's process group, so
#    it can read keys and Ctrl-C reaches it). The player puts the terminal in raw no-echo
#    mode; if it dies uncleanly (timeout's SIGTERM, Ctrl-C) the atexit restore never runs,
#    so ALWAYS run `stty sane` afterwards or the shell is left half-mute.
#
#  - Piped/backgrounded (tests, automation): no real keyboard, so hello_xr's stdin comes
#    from a `sleep infinity` via process substitution instead - never delivers EOF on its
#    own, so it can't fake a keypress, but it also doesn't block this script the way a
#    literal `sleep N | hello_xr` pipe used to (found 2026-08-09: a real pipe makes the
#    shell wait for BOTH sides, so the script used to hang until N seconds elapsed even
#    after hello_xr had already exited on its own). `timeout` on hello_xr directly is what
#    actually bounds the run now; ends whenever hello_xr does (naturally, a quit gesture,
#    HELLO_XR_ANY_KEY_QUITS, a crash) or at N seconds, whichever comes first.
RUNTIME_ENV=(
	XR_RUNTIME_JSON="$MONADO_BUILD/openxr_monado-dev.json"
	IPC_IGNORE_VERSION=1
)
if [ -t 0 ]; then
	echo "Playing $(basename "$FILE") - max ${SECONDS_TO_RUN}s."
	echo "Keys: [space] pause | [ ] speed | 1 normal | h/l -10s/+10s | up/down (or ^ v) zoom | 0 zoom off | b/d bright | 9 bright off | enter recenter | n next | q quit"
	echo "Controller: trigger pause | stick X seek | stick Y zoom | A/B (right) brightness | Y (left) next | grip recenter | left menu held ~1.5s quits"
	timeout --foreground "$SECONDS_TO_RUN" env \
		"${RUNTIME_ENV[@]}" "${ENV_EXTRA[@]}" \
		stdbuf -oL -eL "$HELLO_XR" --graphics Vulkan2
	RC=$?
	stty sane 2>/dev/null
	exit "$RC"
else
	echo "Playing $(basename "$FILE") for up to ${SECONDS_TO_RUN}s (no keyboard: stdin is not a terminal)."
	# Found 2026-08-09: this used to be `sleep N | hello_xr` - a real pipe. sleep writes
	# nothing and never notices hello_xr exiting early (Menu hold, HELLO_XR_ANY_KEY_QUITS,
	# natural end of non-looping content, a crash...), so the whole line - and this script -
	# used to block for the FULL N seconds regardless, even once the interesting part was
	# long done. `timeout` on hello_xr directly, with stdin fed by a background `sleep
	# infinity` via process substitution (not a pipe), fixes that: hello_xr still never sees
	# EOF on its own, but this script only waits on hello_xr's actual process, not on a
	# sibling sleep the shell would otherwise also wait for. The keepalive sleep DOES need
	# killing by hand afterwards, though - it never notices its reader went away (it never
	# writes, so no SIGPIPE) and orphans forever otherwise; six of them had piled up within
	# an hour of the first version of this.
	exec 3< <(exec sleep infinity)
	STDIN_KEEPALIVE_PID=$!
	timeout "$SECONDS_TO_RUN" env \
		"${RUNTIME_ENV[@]}" "${ENV_EXTRA[@]}" \
		stdbuf -oL -eL "$HELLO_XR" --graphics Vulkan2 0<&3
	RC=$?
	exec 3<&-
	[ -n "$STDIN_KEEPALIVE_PID" ] && kill "$STDIN_KEEPALIVE_PID" 2>/dev/null
	exit "$RC"
fi
