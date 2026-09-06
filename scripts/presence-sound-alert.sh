#!/bin/bash
# presence-sound-alert.sh -- speaks short Spanish phrases for operator-relevant state
# transitions, so a booth operator gets audible feedback without watching a screen.
# Read-only: tails the log, never launches or kills anything, and never blocks
# jack-in-wayland.sh's own startup.
#
# States covered (2026-09-06, docs/103):
#   - "casco apagado" / "casco encendido": auto-standby blanks/restores the panel
#     (presence.conf PRESENCE_ENABLE). Needs an active OpenXR client to ever fire --
#     see wmr_hmd_update_inputs()'s doc comment; monado-service alone, with no app,
#     never evaluates presence at all.
#   - "monado arriba" / "monado abajo": the MONADO_MARKER lines jack-in-wayland.sh
#     appends to $LOG on a successful 'up' and on 'down'. Added after a live incident
#     the same day where a test round produced zero alerts simply because the service
#     was up with no app running -- this distinguishes "nothing happened" from
#     "nothing is listening".
#   - controller-missing nudge: WMR only checks for the motion controllers once at
#     HMD creation (the "G2 controller hotplug gap", unscoped/unfixed) -- if they were
#     off at launch, the fix is a down+up after turning them on, not a live reconnect.
#   - game name on connect: Monado logs every OpenXR client's own applicationInfo as
#     `application_name: '...'` (ipc_handle_instance_describe_client). Several of these
#     fire per real launch before the actual app -- 'libmonado' (jack-in-wayland.sh's own
#     post-launch validation probe), 'steam' and 'wineopenxr test instance' (wrapper
#     handshaking) -- GAME_NAME_MAP below stays silent on those by omission, so only the
#     last, real one gets spoken. Raw names are inconsistent (an Unreal build gives its
#     full binary path, e.g. 'AirCar/Binaries/Win64/AirCar-Win64-Shipping') so known names
#     are normalized to a short spoken word; anything unrecognized falls back to "testing"
#     rather than reading a raw path aloud -- add a case here once a new title's real
#     application_name is confirmed live, don't guess ahead of that.
#
#   ./presence-sound-alert.sh &     run in the background alongside a jack-in session
#
# Survives a monado-service restart (tail -F re-opens the log by name, including through the
# truncation jack-in-wayland.sh's own '>' redirect does on each launch).
set -u

VR="$HOME/vr"
LOG="$VR/jack-in-wayland.log"
VOICE="es-419"

say() {
	XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" espeak-ng -v "$VOICE" "$1" >/dev/null 2>&1
}

echo "presence-sound-alert: watching $LOG"
tail -n0 -F "$LOG" 2>/dev/null | while IFS= read -r line; do
	case "$line" in
	*"panel blanked by auto-standby"*)
		say "casco apagado"
		;;
	*"panel restored from auto-standby"*)
		say "casco encendido"
		;;
	*"MONADO_MARKER: up"*)
		say "monado arriba"
		;;
	*"MONADO_MARKER: down"*)
		say "monado abajo"
		;;
	*"Failed to request controller status from HMD"*)
		say "encendé los joysticks y reiniciá monado"
		;;
	*"application_name:"*)
		name="${line#*\'}"
		name="${name%\'*}"
		case "$name" in
		HelloXR)
			say "player"
			;;
		SUPERHOTVR)
			say "superhot"
			;;
		AirCar*)
			say "aircar"
			;;
		OpenVRBenchmark)
			say "benchmark"
			;;
		libmonado | steam | "wineopenxr test instance" | "")
			;; # wrapper/probe noise, not a real session -- stay silent
		*)
			say "testing"
			;;
		esac
		;;
	esac
done
