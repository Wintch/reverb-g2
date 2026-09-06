#!/bin/bash
# presence-sound-alert.sh -- speaks "casco apagado" / "casco encendido" when auto-standby
# blanks or restores the panel (presence.conf PRESENCE_ENABLE), so a booth operator gets
# audible feedback without watching a screen. Read-only: tails the log, never launches or
# kills anything, and never blocks jack-in-wayland.sh's own startup.
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
	esac
done
