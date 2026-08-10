#!/bin/bash
# vr-launcher-console.sh -- lighter alternative to the gnome-terminal/autostart
# approach: runs vr-launcher.py directly on tty3, plain text, no gnome-terminal,
# no GNOME autostart .desktop mechanism. GNOME/mutter itself still has to be
# running (jack-in-wayland.sh's DRM lease has no other validated path in this
# project) -- this only avoids the EXTRA weight of a terminal emulator + the
# autostart machinery just to show a text menu.
#
# Waits (bounded, polling) for two things before showing the picker:
#   1. ~/.vr-ready exists -- written by power-on.py --pre-login only on a real
#      LISTO, removed on every failure path.
#   2. A real Wayland session socket exists -- proxy for "GNOME actually
#      finished logging in", since a bare `graphical.target` reached doesn't
#      guarantee the human is done typing their password yet.
#
# If neither shows up within the wait window (manual mode chosen, auto
# failed, or login is just slow), falls through to a normal `agetty` on tty3
# -- this console never gets stuck showing nothing.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
READY_FILE="$HOME/.vr-ready"
WAIT_MAX=60

for _i in $(seq 1 "$WAIT_MAX"); do
    if [ -f "$READY_FILE" ] && [ -S "/run/user/1000/wayland-0" ]; then
        read -r MODE TRACKING < "$READY_FILE"
        rm -f "$READY_FILE"  # one-shot
        exec python3 "$HERE/vr-launcher.py" "${MODE:-1}" "${TRACKING:-3dof}"
    fi
    sleep 1
done

# Nothing to show -- act like a normal console instead of leaving tty3 blank.
exec /sbin/agetty tty3 linux
