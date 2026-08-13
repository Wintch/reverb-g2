#!/bin/bash
# vr-state.sh - authoritative snapshot of what is actually running right now.
#
# Written 2026-08-12 (T163) after getting this wrong twice in one session: a game was
# declared closed while it was still running, and a launch that never started was reported
# as up. Both came from ad-hoc `pgrep -f <pattern>` calls, which in this environment match
# the agent's OWN shell because the pattern is sitting in its command line -- the trap
# CLAUDE.md already documents for pgrep and which cost a killed shell (exit 144) again today.
#
# Every process lookup below uses a bracketed pattern so it cannot match itself.
#
#   ./vr-state.sh          one snapshot
#   ./vr-state.sh -w       repeat every 3 s until interrupted
#
# The rule this exists to enforce: NEVER restart monado-service while a game is running
# (it kills the session -- Unreal titles die with "GameThread timed out waiting for
# RenderThread", xrizer panics in compositor.rs at "Failed to acquire swapchain image"),
# and NEVER launch a second VR title over a live one (docs/23 has a trap entry for that
# hanging the whole desktop).

set -u

VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$HOME/vr" ] && VR="$HOME/vr"
LOG="$VR/jack-in-wayland.log"
STEAMAPPS="$HOME/.steam/debian-installation/steamapps"

C_OK=$'\033[1;32m'; C_WARN=$'\033[1;33m'; C_ERR=$'\033[1;31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'

snapshot() {
	echo "=== VR state $(date '+%H:%M:%S') ==="

	# --- Monado ------------------------------------------------------------------
	local mpid
	mpid="$(pgrep -f "monado[-]service" | head -1)"
	if [ -n "$mpid" ]; then
		local since env_slam env_const env_filter
		since="$(ps -o etime= -p "$mpid" 2>/dev/null | tr -d ' ')"
		# Read the env it was actually started with, not what we think we passed.
		env_slam="$(tr '\0' '\n' < "/proc/$mpid/environ" 2>/dev/null | grep '^WMR_SLAM=' | cut -d= -f2)"
		env_const="$(tr '\0' '\n' < "/proc/$mpid/environ" 2>/dev/null | grep '^WMR_CONSTELLATION_CONTROLLERS=' | cut -d= -f2)"
		env_filter="$(tr '\0' '\n' < "/proc/$mpid/environ" 2>/dev/null | grep '^SLAM_FILTER=' | cut -d= -f2)"
		echo "  monado-service  ${C_OK}UP${C_OFF}  pid $mpid  up ${since:-?}"
		echo "                  head=$([ "${env_slam:-0}" = 1 ] && echo 6dof || echo 3dof)" \
		     " constellation=${env_const:-unset}  slam_filter=${env_filter:-default}"
	else
		echo "  monado-service  ${C_ERR}DOWN${C_OFF}"
	fi

	# --- OpenXR clients ----------------------------------------------------------
	# The log is the only place that says whether a session is actually open; a live
	# process proves nothing (a title can sit at a 2D window having abandoned its session).
	if [ -f "$LOG" ]; then
		local conn disc beg end state
		# No `|| echo 0` here: grep -c already prints 0 when it finds nothing, it just exits 1,
		# so the fallback appended a SECOND zero and the arithmetic below died on "0\n0".
		conn=$(grep -c "client_connected" "$LOG" 2>/dev/null); conn=${conn:-0}
		disc=$(grep -c "client_disconnected" "$LOG" 2>/dev/null); disc=${disc:-0}
		beg=$(grep -c "BEGIN_SESSION" "$LOG" 2>/dev/null); beg=${beg:-0}
		end=$(grep -c "END_SESSION" "$LOG" 2>/dev/null); end=${end:-0}
		if [ "$beg" -gt "$end" ]; then state="${C_OK}session OPEN${C_OFF}"; else state="${C_DIM}no session${C_OFF}"; fi
		echo "  openxr          $state   clients $((conn - disc)) connected  (begin $beg / end $end)"
	fi

	# --- Steam titles ------------------------------------------------------------
	# Match the reaper's own argv, which carries AppId=<n>, rather than guessing at
	# executable names (they are Windows .exe names inside pressure-vessel).
	local found=0
	while read -r appid; do
		[ -z "$appid" ] && continue
		local name
		name="$(grep -m1 '"name"' "$STEAMAPPS/appmanifest_$appid.acf" 2>/dev/null |
		        sed 's/.*"name"[^"]*"\([^"]*\)".*/\1/')"
		echo "  steam title     ${C_WARN}RUNNING${C_OFF}  ${name:-?} (appid $appid)"
		found=1
	done < <(ps -eo args= 2>/dev/null | grep -o "AppId=[0-9]\+" | cut -d= -f2 | sort -u)

	# The AppId only lives on Steam's `reaper` process. Kill that (or lose it any other way)
	# and the title keeps running perfectly well while every AppId-based check reports
	# "nothing running" -- which happened here on 2026-08-12 and produced two contradictory
	# readings in a row. The .exe path under steamapps/common survives it, so check that too.
	while read -r game; do
		[ -z "$game" ] && continue
		echo "  proton title    ${C_WARN}RUNNING${C_OFF}  $game  ${C_DIM}(no Steam reaper attached)${C_OFF}"
		found=1
	done < <(ps -eo args= 2>/dev/null | grep -o "steamapps/common/[^/]*/[^ ]*\.exe" |
	         cut -d/ -f3 | sort -u)

	[ "$found" = 0 ] && echo "  steam title     ${C_DIM}none${C_OFF}"

	# --- Our own player ----------------------------------------------------------
	local hpid
	hpid="$(pgrep -f "[h]ello_xr" | head -1)"
	if [ -n "$hpid" ]; then
		echo "  hello_xr        ${C_WARN}RUNNING${C_OFF}  pid $hpid"
	else
		echo "  hello_xr        ${C_DIM}none${C_OFF}"
	fi

	# --- Headset hardware --------------------------------------------------------
	local usb dp
	usb=$(lsusb | grep -cE "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15")
	dp="$(for c in /sys/class/drm/card*-DP-*; do
	        s=$(cat "$c/status" 2>/dev/null)
	        e=$(wc -c < "$c/edid" 2>/dev/null)
	        [ "${e:-0}" -gt 200 ] && echo "$(basename "$c")"
	      done | tr '\n' ' ')"
	if [ "$usb" = 5 ]; then
		echo "  headset usb     ${C_OK}5/5${C_OFF}   hmd connector: ${dp:-none}"
	else
		echo "  headset usb     ${C_ERR}$usb/5${C_OFF}  hmd connector: ${dp:-none}   (docs/00, check the port)"
	fi

	# --- The one rule ------------------------------------------------------------
	if [ "$found" = 1 ] || [ -n "$hpid" ]; then
		echo "  ${C_WARN}>> something is holding a session: do NOT restart monado-service and do NOT"
		echo "     launch another title until it is closed.${C_OFF}"
	fi
}

if [ "${1:-}" = "-w" ]; then
	while true; do clear; snapshot; sleep 3; done
else
	snapshot
fi
