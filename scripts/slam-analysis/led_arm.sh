#!/bin/bash
set -u
INTENSITY="$1"
GUI_PID=$(pgrep -u "$(id -un)" -f gnome-session-binary | head -1)
[ -n "$GUI_PID" ] || { echo "!! no GUI session" >&2; exit 1; }
while IFS= read -r -d "" kv; do
    case "$kv" in
        DISPLAY=*|WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_SESSION_TYPE=*) export "${kv?}" ;;
    esac
done < "/proc/$GUI_PID/environ"
export WMR_CONTROLLER_LED_INTENSITY="$INTENSITY"
export WMR_CONSTELLATION_RAW_SAMPLES_LOG=1
setsid nohup "$HOME/vr/jack-in-wayland.sh" 1 ctrl </dev/null >/tmp/arm-$INTENSITY.log 2>&1 &
for _i in $(seq 1 60); do [ -S /run/user/1000/monado_comp_ipc ] && break; sleep 1; done
for _i in $(seq 1 30); do grep -q "right: HP Reverb G2 Right Controller" "$HOME/vr/jack-in-wayland.log" && break; sleep 1; done
grep -E "stable for|LED pulse train" /tmp/arm-$INTENSITY.log
grep -q "right: HP Reverb G2 Right Controller" "$HOME/vr/jack-in-wayland.log" && echo "right controller registered" || echo "!! right controller MISSING"
grep -i "battery raw" "$HOME/vr/jack-in-wayland.log" | tail -2
