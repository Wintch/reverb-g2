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
#   - "casco en la mesa": the debounced NOT-WORN commit itself (WMR_USER_PRESENCE_DOFF_MS,
#     ~1s after a real doff) -- long before the SCREENOFF_MS grace period (120000ms in
#     production) actually blanks the panel. Added 2026-09-06 for continuous state
#     awareness ("bien detallado con audio"), not just the two endpoint events.
#     Deliberately NOT mirrored on the WORN commit: that log line also fires on every
#     ordinary don while the panel was never blanked (ANY doff-then-redon inside the
#     SCREENOFF_MS window), which would double up with "casco encendido" in the one case
#     that matters (redonning after a real blank) while adding noise to the far more
#     common case (a quick doff/redon that never blanked at all).
#     This step's OWN timing is configurable, separate from SCREENOFF_MS -- first instance
#     of the "each step gets its own delay" staged-sequence design the user asked for
#     2026-09-06, building it one step at a time rather than all at once. The delay is
#     PER-USER (status-dashboard.py's user-center "resting_alert_delay_ms" field, same
#     preset pattern as brightness/lang/height): the dashboard writes it to
#     RESTING_ALERT_DELAY_FILE on every user save/select, and this script re-reads that
#     file FRESH on every single doff -- not once at startup -- so switching the active
#     user applies to the very next doff with no restart needed (unlike PRESENCE_ENABLE/
#     SCREENOFF_MS in presence.conf, which need a jack-in down/up). The ambient
#     PRESENCE_RESTING_ALERT_DELAY_MS env var, if set, overrides the file -- kept for quick
#     ad-hoc testing the way it was used before the dashboard preset existed. A nonzero
#     delay speaks in a background subshell so it never blocks the tail loop from seeing
#     later lines, and is CANCELLED if a WORN commit (redonning) arrives before it fires --
#     announcing "en la mesa" after you've already put it back on would be wrong.
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
RESTING_ALERT_DELAY_FILE="$VR/logs/presence-resting-alert-delay-ms"

say() {
	XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" espeak-ng -v "$VOICE" "$1" >/dev/null 2>&1
}

# Ambient env var wins (ad-hoc testing override); else the per-user dashboard preset file,
# read fresh so it's never stale; else 0 (instant, the original behavior). Sanitized to
# digits-only so a missing/corrupt file can't break the "-gt 0" test below under set -u.
resting_alert_delay_ms() {
	if [ -n "${PRESENCE_RESTING_ALERT_DELAY_MS:-}" ]; then
		printf '%s' "$PRESENCE_RESTING_ALERT_DELAY_MS"
		return
	fi
	local v
	v="$(cat "$RESTING_ALERT_DELAY_FILE" 2>/dev/null | tr -d '[:space:]')"
	case "$v" in
	'' | *[!0-9]*) printf '0' ;;
	*) printf '%s' "$v" ;;
	esac
}

resting_alert_pid=""

echo "presence-sound-alert: watching $LOG"
tail -n0 -F "$LOG" 2>/dev/null | while IFS= read -r line; do
	case "$line" in
	*"panel blanked by auto-standby"*)
		say "casco apagado"
		;;
	*"panel restored from auto-standby"*)
		say "casco encendido"
		;;
	*"User presence: NOT WORN"*)
		delay_ms="$(resting_alert_delay_ms)"
		if [ "$delay_ms" -gt 0 ]; then
			(
				sleep "$(awk "BEGIN{printf \"%.3f\", $delay_ms/1000}")"
				say "casco en la mesa"
			) &
			resting_alert_pid=$!
		else
			say "casco en la mesa"
		fi
		;;
	*"User presence: WORN"*)
		if [ -n "$resting_alert_pid" ]; then
			kill "$resting_alert_pid" 2>/dev/null
			resting_alert_pid=""
		fi
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
