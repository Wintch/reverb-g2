#!/bin/bash
# speak.sh -- speaks $1 using the ACTIVE dashboard profile's configured voice
# (language accent + gender) via Piper (neural TTS) with an espeak-ng fallback.
# Standalone and callable from anywhere -- ad-hoc narration (e.g. a live operator
# summons: `~/vr/speak.sh "Atención, ponete el casco"`) goes through the exact
# same logic as presence-sound-alert.sh's own internal alert states, which
# source this file as a library instead of duplicating any of it. ONE source of
# truth for voice selection, the audio_guide_enabled gate, and the Piper/
# espeak-ng fallback chain (2026-09-06).
#
# Usage: speak.sh "<phrase text, already composed in whatever language you intend>"
#
# This script does NOT translate -- it only picks WHICH VOICE speaks. The active
# profile's "lang" field selects an accent/pronunciation model (English/Spanish/
# Russian) and "voice_gender" (male/female) selects which speaker within that
# language. Compose the phrase in a language that matches the active profile if
# you want it to come out right -- check ~/vr/logs/user-profiles.json's "active"
# entry first if unsure. Piper will pronounce whatever text you give it using
# that model's phonetic rules regardless of whether the words match the language.
#
# Honors "audio_guide_enabled" (default true) on the active profile: false means
# a clean, total no-op -- no synthesis call is even attempted, not a muted-but-
# still-running playback. This is the one switch meant to globally silence every
# alert without editing anything else.
set -u

VR="$HOME/vr"
USER_PROFILES_FILE="$VR/logs/user-profiles.json"
TTS_VENV_PIPER="$VR/tts-venv/bin/piper"
TTS_VOICES="$VR/tts-voices"
ESPEAK_VOICE_ES="es-419"

# Active operator's language (en/es/ru), read fresh every call -- never cached, so a
# profile switch on the dashboard applies to the very next alert.
active_lang() {
	local l
	l="$(jq -r '.users[.active].lang // "es"' "$USER_PROFILES_FILE" 2>/dev/null)"
	case "$l" in
	en | es | ru) printf '%s' "$l" ;;
	*) printf 'es' ;;
	esac
}

# Active operator's alert-voice gender (male/female), same fresh-per-call contract as
# active_lang(). Defaults to "male" -- matches what every profile's single voice-per-
# language actually was before this field existed for es (davefx) and en (lessac); only
# ru (irina) was female, and existing ru profiles get an explicit voice_gender set at
# migration time in status-dashboard.py precisely so they don't silently change voice.
active_voice_gender() {
	local g
	g="$(jq -r '.users[.active].voice_gender // "male"' "$USER_PROFILES_FILE" 2>/dev/null)"
	case "$g" in
	male | female) printf '%s' "$g" ;;
	*) printf 'male' ;;
	esac
}

# false only on an explicit "false" -- missing file, missing field, or any other value
# (including a genuinely malformed one) means enabled, matching every other per-profile
# field's fail-open default in this script and in status-dashboard.py.
audio_guide_enabled() {
	local v
	v="$(jq -r '.users[.active].audio_guide_enabled // true' "$USER_PROFILES_FILE" 2>/dev/null)"
	[ "$v" != "false" ]
}

# lang:gender -> "model.onnx" or "model.onnx:speaker_id" for a multi-speaker model.
# es_ES-sharvard is the one multi-speaker voice in use (M=0/F=1 in its own speaker_id_map,
# fetched 2026-09-06 from rhasspy/piper-voices) -- used here purely for its female speaker,
# since davefx already covers male Spanish as a dedicated single-speaker model.
voice_model_spec() {
	case "$1:$2" in
	es:male) echo "es_ES-davefx-medium.onnx" ;;
	es:female) echo "es_ES-sharvard-medium.onnx:1" ;;
	ru:male) echo "ru_RU-denis-medium.onnx" ;;
	ru:female) echo "ru_RU-irina-medium.onnx" ;;
	en:male) echo "en_US-lessac-medium.onnx" ;;
	en:female) echo "en_US-amy-medium.onnx" ;;
	esac
}

# Speaks $1 as the active profile. Piper first (natural neural voice, per-language-and-
# gender model); falls back to espeak-ng (instant, always installed) if the venv/model is
# missing or Piper's own synthesis fails for any reason.
speak() {
	local phrase="$1"
	[ -n "$phrase" ] || return 0
	audio_guide_enabled || return 0

	local lang gender spec model speaker
	lang="$(active_lang)"
	gender="$(active_voice_gender)"
	spec="$(voice_model_spec "$lang" "$gender")"
	model="${spec%%:*}"
	speaker=""
	case "$spec" in *:*) speaker="${spec#*:}" ;; esac

	export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

	if [ -x "$TTS_VENV_PIPER" ] && [ -f "$TTS_VOICES/$model" ]; then
		local wav piper_args
		wav="$(mktemp /tmp/speak-XXXXXX.wav)"
		piper_args=(-m "$TTS_VOICES/$model" -f "$wav")
		[ -n "$speaker" ] && piper_args+=(--speaker "$speaker")
		if printf '%s' "$phrase" | "$TTS_VENV_PIPER" "${piper_args[@]}" >/dev/null 2>&1 \
			&& [ -s "$wav" ] && paplay "$wav" >/dev/null 2>&1; then
			rm -f "$wav"
			return 0
		fi
		rm -f "$wav"
	fi

	# Fallback: espeak-ng. Only "es"/"en" map cleanly to its own voice list on this
	# install; ru falls back to the es-419 voice rather than a wrong/missing espeak
	# voice -- acceptable since this path only runs if Piper (which HAS a real ru
	# voice) is unavailable in the first place. Gender is not modeled in this
	# fallback at all (espeak-ng's default voices here are whatever they are) --
	# a known, accepted gap since this path is the rare-failure case, not the norm.
	local espeak_voice
	case "$lang" in
	en) espeak_voice="en-us" ;;
	*) espeak_voice="$ESPEAK_VOICE_ES" ;;
	esac
	espeak-ng -v "$espeak_voice" "$phrase" >/dev/null 2>&1
}

# Sourced (by presence-sound-alert.sh, to share this logic) vs executed directly (ad-hoc
# CLI use, e.g. `~/vr/speak.sh "..."`) -- only auto-run speak() in the latter case, so
# sourcing this file doesn't also immediately say whatever $1 happened to be unset to.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
	speak "${1:-}"
fi
