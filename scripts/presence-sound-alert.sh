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
#   - "casco en la mesa" / "casco puesto": the debounced NOT-WORN / WORN commits
#     (WMR_USER_PRESENCE_DOFF_MS / _DON_MS, ~1s / ~250ms after a real doff/don) -- fire on
#     EVERY commit, unconditionally, long before (or entirely independent of) the
#     SCREENOFF_MS grace period (120000ms in production) that actually blanks/restores the
#     panel. Added 2026-09-06 for continuous state awareness ("bien detallado con audio",
#     "reaccionamos inmediatamente"), not just the two auto-standby endpoint events below.
#     "casco puesto" was added AFTER "casco en la mesa" the same day, once the user pointed
#     out the asymmetry live: they heard "en la mesa" on every doff but nothing at all on a
#     plain don unless it happened to follow a genuine blank (which speaks "casco
#     encendido" instead, see below). The two WORN-side alerts answer different questions
#     and both stay: "casco puesto" is "did I just put it on, period" (every single WORN
#     commit); "casco encendido" is "did that just wake the panel from a real standby"
#     (only the genuine restore case, gated on screen_off_by_presence in the driver).
#     "casco en la mesa"'s OWN timing is configurable, separate from SCREENOFF_MS -- first instance
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
#   PARTIAL-DIM BRIGHTNESS MITIGATION (2026-09-06, docs/103 addendum): the same two
#   commit lines that drive "casco en la mesa"/"casco puesto" above ALSO now drop/restore
#   a purely-cosmetic, rendering-side brightness gain -- dim_panel() on every debounced
#   NOT WORN commit, undim_panel() on every debounced WORN commit. This is orthogonal to
#   (and much cheaper/faster than) the real HID panel blank/restore covered by "casco
#   apagado"/"casco encendido" above, which only fires after the much longer SCREENOFF_MS
#   wait (up to 30 min) -- the dim reacts within the ~1s/~250ms DOFF_MS/DON_MS debounce
#   itself, the user's own framing being "raise it back on presence and lower it a bit as
#   soon as it's taken off... if it's not worn, nobody's there." Reuses the EXACT live-file
#   mechanism status-dashboard.py's own brightness slider already writes
#   ($VR/logs/xrizer-brightness, BRIGHTNESS_FILE below, polled ~every 30 frames by
#   xrizer's patched compositor.rs) -- no new IPC, no driver change needed. Deliberately
#   NOT wired into the C driver: this script already has jq access to the ACTIVE
#   operator's own saved brightness baseline (USER_PROFILES_FILE's "brightness" field,
#   the same value status-dashboard.py's slider writes there), so it can restore to
#   exactly what the operator asked for instead of a driver-hardcoded number that would
#   silently clobber a custom setting on every doff/don cycle. Also rides the SAME
#   packet-confirm-count hardening as the audible "casco puesto" alert (WMR_USER_PRESENCE_
#   DON_CONFIRM_PACKETS, wmr_hmd.c) -- both react to the driver's already-debounced
#   `committed` transitions, not the raw candidate, so neither is exposed to the single-
#   stray-packet noise bug that motivated that fix. Known gap: if the operator adjusts the
#   dashboard slider WHILE the panel is already dimmed (headset genuinely resting), that
#   write lands at full requested brightness, not the dimmed fraction, until the next real
#   doff -- rare (nobody is watching the panel to judge brightness while it's resting) and
#   self-corrects on the next NOT WORN commit, so left as a known limitation rather than
#   fixed here.
#
#   LANGUAGE (2026-09-06): every phrase above is spoken in the ACTIVE operator's language
#   (status-dashboard.py's per-user "lang" field, en/es/ru), read fresh from
#   USER_PROFILES_FILE on every single alert via jq -- same "never cached, no restart
#   needed to pick up a profile switch" philosophy as the resting-alert delay above.
#   Falls back to "es" (this project's long-standing default) if the file is missing,
#   corrupt, or the jq lookup otherwise fails -- unit-tested against all three. See
#   phrase_for() for the EN/ES/RU text.
#
#   VOICE, TTS ENGINE, AND THE audio_guide_enabled GATE (2026-09-06) all live in
#   speak.sh, sourced below -- NOT duplicated here. That file is also directly callable
#   on its own (`~/vr/speak.sh "some phrase"`) for ad-hoc narration outside this script
#   (e.g. the live coordinating session summoning the operator), so both paths share one
#   source of truth for which voice speaks and whether anything should speak at all. Read
#   speak.sh's own header for the full story (Piper-vs-espeak-ng fallback, per-language-
#   and-gender voice models, the audio_guide_enabled no-op gate).
#
#   ./presence-sound-alert.sh &     run in the background alongside a jack-in session
#
# Survives a monado-service restart (tail -F re-opens the log by name, including through the
# truncation jack-in-wayland.sh's own '>' redirect does on each launch).
set -u

VR="$HOME/vr"
LOG="$VR/jack-in-wayland.log"
RESTING_ALERT_DELAY_FILE="$VR/logs/presence-resting-alert-delay-ms"
# Same path status-dashboard.py's BRIGHTNESS_FILE writes -- see this script's own header,
# "PARTIAL-DIM BRIGHTNESS MITIGATION", for why the write happens here instead of in the
# C driver.
BRIGHTNESS_FILE="$VR/logs/xrizer-brightness"
# Fraction of the operator's own saved brightness baseline applied while genuinely NOT
# WORN. Chosen as a visible-but-not-jarring partial dim (not full black, which would look
# indistinguishable from a real crash/blank to anyone glancing at a spectator feed) --
# untuned against a live wearer, revisit if 0.35 reads as too subtle or too dark.
RESTING_DIM_FACTOR="0.35"

# shellcheck source=speak.sh
source "$VR/speak.sh"

# Active operator's saved brightness baseline (status-dashboard.py user-center's
# "brightness" field, the same value its slider writes to BRIGHTNESS_FILE), read fresh via
# jq every call -- same fresh-per-call contract as speak.sh's active_lang()/
# active_voice_gender(). Falls back to 1.0 (passthrough gain) on a missing/corrupt file or
# a non-numeric field, matching every other per-profile fail-open default in this script.
active_brightness() {
	local v
	v="$(jq -r '.users[.active].brightness // 1.0' "$USER_PROFILES_FILE" 2>/dev/null)"
	case "$v" in
	'' | *[!0-9.]*) printf '1.0' ;;
	*) printf '%s' "$v" ;;
	esac
}

# Writes RESTING_DIM_FACTOR of the operator's own baseline -- called on every debounced
# NOT WORN commit (see the case arm below), independent of and much sooner than the
# SCREENOFF_MS-gated HID blank.
dim_panel() {
	awk "BEGIN{printf \"%.3f\\n\", $(active_brightness) * $RESTING_DIM_FACTOR}" >"$BRIGHTNESS_FILE" 2>/dev/null
}

# Restores the operator's own undimmed baseline -- called on every debounced WORN commit.
# Reads the baseline fresh rather than remembering the pre-dim value, so a brightness
# change made by the operator while away (rare, see this script's header) is honored on
# the very next don rather than reverting to whatever was in effect before the dim.
undim_panel() {
	awk "BEGIN{printf \"%.3f\\n\", $(active_brightness)}" >"$BRIGHTNESS_FILE" 2>/dev/null
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
	worn:en) echo "headset on head" ;;
	worn:ru) echo "шлем надет" ;;
	worn:*) echo "casco puesto" ;;
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

# Resolves phrase_for(state, active_lang()) and hands it to speak.sh's shared speak()
# (voice selection, Piper/espeak-ng fallback, and the audio_guide_enabled gate all live
# there now -- see the sourced speak.sh for the full story).
say_state() {
	local state="$1" lang phrase
	lang="$(active_lang)"
	phrase="$(phrase_for "$state" "$lang")"
	speak "$phrase"
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
		dim_panel
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
		undim_panel
		if [ -n "$resting_alert_pid" ]; then
			kill "$resting_alert_pid" 2>/dev/null
			resting_alert_pid=""
		fi
		say_state worn
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
