#!/bin/bash
# playlist-session.sh - one-shot session: bring the VR stack up over the DRM-lease path,
# play a directory of videos in the headset one after another, then shut the headset down
# cleanly.
#
#   ./playlist-session.sh folder/            4320x2160@90 (mode 1), until Ctrl-C, controller
#                                             quit, or 5 minutes (play360.sh's own default)
#   ./playlist-session.sh -t 1800 folder/    cap the whole session at 30 minutes
#   ./playlist-session.sh -M 0 folder/       force a mode: 0=2880x1440@90 native,
#                                             1=4320x2160@90 (default), 2=4320x2160@60
#
# Uses jack-in-wayland.sh, NOT jack-in.sh. The only 90Hz path confirmed clean with the bpc
# patch (docs/19-nvidia-bug-5923212-followup.md) is DRM lease under a GNOME/mutter Wayland
# session - X11 Direct-Mode (jack-in.sh) has never been retested at 90Hz since the patch,
# and its own default mode is still hardcoded to 60Hz, a leftover workaround from before the
# fix existed. hello_xr/play360.sh don't care which one brought Monado up - they only speak
# OpenXR to whatever service is running - so this is a launcher choice, not a player choice.
#
# REQUIRES the "GNOME" (Wayland) entry at the SDDM login screen - not Plasma, not GNOME's
# X11 entry. KWin does not offer the headset's connector for lease at all (chapter 04).
#
# Verified 2026-08-07 (T041 in docs/pruebas.jsonl): real video through this exact path at
# 4320x2160@90 is clean, and the playlist chains unattended with wraparound. (Historical
# context: until that test, the only clean-90Hz verdicts were via hmd-vk with solid test
# colors, and the one prior real-video run, T021, still flickered - that caveat is closed.)
#
# Teardown always applies here: jack-in-wayland.sh itself unconditionally kills any prior
# monado-service before starting (no reuse of an existing session), so this script owns
# shutdown the same way. Sends a real SIGTERM (not -9) so the panel gets a proper HID
# screen-off, same distinction jack-in.sh's wake_panel() makes in reverse for its throwaway
# startup run.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TIME_LIMIT=0
MODE=1
while getopts "t:M:h" opt; do
	case "$opt" in
		t) TIME_LIMIT="$OPTARG" ;;
		M) MODE="$OPTARG" ;;
		h) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) exit 1 ;;
	esac
done
shift $((OPTIND - 1))

if [ $# -lt 1 ]; then
	echo "usage: $0 [-t SECONDS] [-M 0|1|2] <directory>" >&2
	exit 1
fi
PLAYLIST_DIR=$(readlink -f "$1")
[ -d "$PLAYLIST_DIR" ] || { echo "not a directory: $PLAYLIST_DIR" >&2; exit 1; }

SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/monado_comp_ipc"

service_pids() { pgrep -f "targets/service/monado-service"; }

teardown() {
	echo
	echo "Shutting the session down..."

	# hello_xr: give it its own quit path a moment, then make sure.
	for pid in $(pgrep -f "hello[_]xr"); do kill "$pid" 2>/dev/null; done
	sleep 1
	for pid in $(pgrep -f "hello[_]xr"); do kill -9 "$pid" 2>/dev/null; done

	pids="$(service_pids)"
	if [ -n "$pids" ]; then
		echo "Stopping monado-service (SIGTERM - clean shutdown, panel screen-off)..."
		for pid in $pids; do kill "$pid" 2>/dev/null; done
		for _i in $(seq 1 10); do
			[ -z "$(service_pids)" ] && break
			sleep 1
		done
		pids="$(service_pids)"
		if [ -n "$pids" ]; then
			echo "monado-service didn't exit cleanly, forcing it." >&2
			for pid in $pids; do kill -9 "$pid" 2>/dev/null; done
			sleep 1
		fi
	fi
	rm -f "$SOCKET"
	echo "Panel off, socket cleared."
}
trap teardown EXIT

echo "Bringing the stack up over DRM lease (mode $MODE)..."
"$HERE/jack-in-wayland.sh" "$MODE" || { echo "jack-in-wayland failed." >&2; exit 1; }

PLAY_ARGS=()
[ "$TIME_LIMIT" -gt 0 ] && PLAY_ARGS+=(-t "$TIME_LIMIT")
PLAY_ARGS+=("$PLAYLIST_DIR")

echo "Playing playlist: $PLAYLIST_DIR"
"$HERE/play360.sh" "${PLAY_ARGS[@]}"
