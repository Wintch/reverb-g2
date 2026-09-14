#!/bin/bash
# Live "can the cameras see the controller at all" hunter. Speaks the moment a new raw
# constellation sample lands, so the operator can sweep the controller around and find the
# camera cone by ear instead of guessing. Reports a per-interval count at the end.
#
# $1 = seconds to run (default 90)
set -u
SECS="${1:-90}"
L="$HOME/vr/jack-in-wayland.log"
PAT="raw constellation sample \[HP Reverb G2 Right"

say() { espeak-ng -v es -s 150 "$1" >/dev/null 2>&1; }

GUI_PID=$(pgrep -u "$(id -un)" -f gnome-session-binary | head -1)
[ -n "$GUI_PID" ] || { echo "!! no GUI session" >&2; exit 1; }
while IFS= read -r -d '' kv; do
    case "$kv" in
        XDG_RUNTIME_DIR=*|DBUS_SESSION_BUS_ADDRESS=*|WAYLAND_DISPLAY=*|DISPLAY=*) export "${kv?}" ;;
    esac
done < "/proc/$GUI_PID/environ"

PREV=$(grep -c "$PAT" "$L" 2>/dev/null || echo 0)
START=$PREV
say "Buscando. Movelo despacio delante del casco."
echo "start count: $PREV"

END=$((SECONDS + SECS))
LAST_SPOKE=0
while [ "$SECONDS" -lt "$END" ]; do
    sleep 2
    NOW=$(grep -c "$PAT" "$L" 2>/dev/null || echo 0)
    D=$((NOW - PREV))
    if [ "$D" -gt 0 ]; then
        echo "  +$D  (total $NOW)"
        # Don't stutter: at most one announcement every 4 s.
        if [ $((SECONDS - LAST_SPOKE)) -ge 4 ]; then
            say "Te veo"
            LAST_SPOKE=$SECONDS
        fi
    fi
    PREV=$NOW
done

say "Fin de la búsqueda."
echo "total new samples: $((PREV - START)) in ${SECS}s"
