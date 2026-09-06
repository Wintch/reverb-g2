#!/bin/bash
# presence-sound-alert.sh -- speaks short phrases for operator-relevant state
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
#     handshaking) -- the case arm below stays silent on those by omission, so only the
#     last, real one gets spoken. Raw names are inconsistent (an Unreal build gives its
#     full binary path, e.g. 'AirCar/Binaries/Win64/AirCar-Win64-Shipping') so known names
#     are normalized to a short spoken word; anything unrecognized falls back to "testing"
#     rather than reading a raw path aloud -- add a case here once a new title's real
#     application_name is confirmed live, don't guess ahead of that. Proper-noun game
#     names (superhot, aircar) are NOT translated per language -- only the generic
#     descriptive labels (player/testing/benchmark) are.
#
#   LANGUAGE (2026-09-06): every phrase above is spoken in the ACTIVE operator's language
#   (status-dashboard.py's per-user "lang" field, en/es/ru), read fresh from
#   USER_PROFILES_FILE on every single alert via jq -- same "never cached, no restart
#   needed to pick up a profile switch" philosophy as the resting-alert delay above.
#   Falls back to "es" (this project's long-standing default) if the file is missing,
#   corrupt, or the jq lookup otherwise fails -- unit-tested against all three. See
#   phrase_for() for the EN/ES/RU text and active_lang() for the lookup.
#
#   TTS ENGINE: tries Piper (neural TTS, ~/vr/tts-venv + ~/vr/tts-voices, one voice model
#   per language) first for a genuinely more natural voice than espeak-ng's formant
#   synthesis; falls back to espeak-ng if the venv/model for the needed language is
#   missing, or if piper's own synthesis fails for any reason -- espeak-ng ships with
#   Debian and needs no network/download, so it's the one engine that can never be
#   unavailable. Piper costs real latency (~0.9s per short phrase on this machine,
#   dominated by loading a ~60MB ONNX model fresh each call -- there is no persistent
#   piper daemon here, deliberately, to avoid a standing process on a shared lab machine)
#   versus espeak-ng's ~7ms -- judged an acceptable trade for an ambient status narration
#   that nothing else is waiting on. See say_state() for the fallback chain.
#
#   ./presence-sound-alert.sh &     run in the background alongside a jack-in session
#
# Survives a monado-service restart (tail -F re-opens the log by name, including through the
# truncation jack-in-wayland.sh's own '>' redirect does on each launch).
set -u

VR="$HOME/vr"
LOG="$VR/jack-in-wayland.log"
RESTING_ALERT_DELAY_FILE="$VR/logs/presence-resting-alert-delay-ms"
USER_PROFILES_FILE="$VR/logs/user-profiles.json"

TTS_VENV_PIPER="$VR/tts-venv/bin/piper"
TTS_VOICES="$VR/tts-voices"
ESPEAK_VOICE_ES="es-419"

# Active operator's language (en/es/ru), read fresh every call -- never cached, so a
# profile switch on the dashboard applies to the very next alert. jq's own stderr is
# discarded and a failed/empty lookup falls through to "es" below.
active_lang() {
	local l
	l="$(jq -r '.users[.active].lang // "es"' "$USER_PROFILES_FILE" 2>/dev/null)"
	case "$l" in
	en | es | ru) printf '%s' "$l" ;;
	*) printf 'es' ;;
	esac
}

# state:lang -> spoken text. Falls through to the Spanish phrase for any state/lang pair
# not explicitly listed (keeps this table short -- only add a language's line once its
# phrasing has actually been thought through, not as a placeholder).
phrase_for() {
	local state="$1" lang="$2"
	case "$state:$lang" in
	blanked:en) echo "headset off" ;;
	blanked:ru) echo "шлем выключен" ;;
	blanked:*) echo "casco apagado" ;;
	restored:en) echo "headset on" ;;
	restored:ru) echo "шлем включён" ;;
	restored:*) echo "casco encendido" ;;
	resting:en) echo "headset down" ;;
	resting:ru) echo "шлем на столе" ;;
	resting:*) echo "casco en la mesa" ;;
	monado_up:en) echo "monado up" ;;
	monado_up:ru) echo "монадо запущен" ;;
	monado_up:*) echo "monado arriba" ;;
	monado_down:en) echo "monado down" ;;
	monado_down:ru) echo "монадо остановлен" ;;
	monado_down:*) echo "monado abajo" ;;
	controller_missing:en) echo "turn on the controllers and restart monado" ;;
	controller_missing:ru) echo "включите контроллеры и перезапустите монадо" ;;
	controller_missing:*) echo "encendé los joysticks y reiniciá monado" ;;
	game_player:ru) echo "плеер" ;;
	game_player:*) echo "player" ;;
	game_benchmark:ru) echo "бенчмарк" ;;
	game_benchmark:*) echo "benchmark" ;;
	game_testing:en) echo "testing" ;;
	game_testing:ru) echo "тест" ;;
	game_testing:*) echo "testing" ;;
	game_superhot:*) echo "superhot" ;;
	game_aircar:*) echo "aircar" ;;
	esac
}

# Speaks phrase_for(state, active_lang()). Piper first (natural neural voice, one model
# per language); falls back to espeak-ng (instant, always installed) if the venv/model for
# this language is missing or piper's own synthesis fails.
say_state() {
	local state="$1" lang phrase voice_model
	lang="$(active_lang)"
	phrase="$(phrase_for "$state" "$lang")"
	[ -n "$phrase" ] || return
	export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

	case "$lang" in
	en) voice_model="$TTS_VOICES/en_US-lessac-medium.onnx" ;;
	ru) voice_model="$TTS_VOICES/ru_RU-irina-medium.onnx" ;;
	*) voice_model="$TTS_VOICES/es_ES-davefx-medium.onnx" ;;
	esac

	if [ -x "$TTS_VENV_PIPER" ] && [ -f "$voice_model" ]; then
		local wav
		wav="$(mktemp /tmp/presence-alert-XXXXXX.wav)"
		if printf '%s' "$phrase" | "$TTS_VENV_PIPER" -m "$voice_model" -f "$wav" >/dev/null 2>&1 \
			&& [ -s "$wav" ] && paplay "$wav" >/dev/null 2>&1; then
			rm -f "$wav"
			return
		fi
		rm -f "$wav"
	fi

	# Fallback: espeak-ng. Only "es"/"en" map cleanly to its own voice list on this
	# install; ru falls back to the es-419 voice rather than a wrong/missing espeak
	# voice -- acceptable since this path only runs if piper (which HAS a real ru
	# voice) is unavailable in the first place.
	local espeak_voice
	case "$lang" in
	en) espeak_voice="en-us" ;;
	*) espeak_voice="$ESPEAK_VOICE_ES" ;;
	esac
	espeak-ng -v "$espeak_voice" "$phrase" >/dev/null 2>&1
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
		say_state blanked
		;;
	*"panel restored from auto-standby"*)
		say_state restored
		;;
	*"User presence: NOT WORN"*)
		delay_ms="$(resting_alert_delay_ms)"
		if [ "$delay_ms" -gt 0 ]; then
			(
				sleep "$(awk "BEGIN{printf \"%.3f\", $delay_ms/1000}")"
				say_state resting
			) &
			resting_alert_pid=$!
		else
			say_state resting
		fi
		;;
	*"User presence: WORN"*)
		if [ -n "$resting_alert_pid" ]; then
			kill "$resting_alert_pid" 2>/dev/null
			resting_alert_pid=""
		fi
		;;
	*"MONADO_MARKER: up"*)
		say_state monado_up
		;;
	*"MONADO_MARKER: down"*)
		say_state monado_down
		;;
	*"Failed to request controller status from HMD"*)
		say_state controller_missing
		;;
	*"application_name:"*)
		name="${line#*\'}"
		name="${name%\'*}"
		case "$name" in
		HelloXR)
			say_state game_player
			;;
		SUPERHOTVR)
			say_state game_superhot
			;;
		AirCar*)
			say_state game_aircar
			;;
		OpenVRBenchmark)
			say_state game_benchmark
			;;
		libmonado | steam | "wineopenxr test instance" | "")
			;; # wrapper/probe noise, not a real session -- stay silent
		*)
			say_state game_testing
			;;
		esac
		;;
	esac
done
