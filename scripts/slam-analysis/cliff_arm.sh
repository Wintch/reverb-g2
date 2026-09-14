#!/bin/bash
# Bring Monado up for one arm of the visibility-cliff amplitude sweep.
#
#   $1 = WMR_CONTROLLER_CAM_GAIN        (driver default 100, max 255)
#   $2 = WMR_CONTROLLER_CAM_EXPOSURE_US (driver default 6000) -- optional
#
# ctrl mode, headset stationary: tracking origin is the head, so a sample's distance from origin
# is its hand-to-camera range. Blob telemetry on, so a zero window can be told apart from a
# window with blobs that failed to solve -- the whole point of the sweep.
set -u
GAIN="${1:-100}"
EXPO="${2:-6000}"
L="$HOME/vr/jack-in-wayland.log"

GUI_PID=$(pgrep -u "$(id -un)" -f gnome-session-binary | head -1)
[ -n "$GUI_PID" ] || { echo "!! no GUI session" >&2; exit 1; }
while IFS= read -r -d '' kv; do
    case "$kv" in
        DISPLAY=*|WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_SESSION_TYPE=*)
            export "${kv?}" ;;
    esac
done < "/proc/$GUI_PID/environ"

export WMR_CONTROLLER_CAM_GAIN="$GAIN"
export WMR_CONTROLLER_CAM_EXPOSURE_US="$EXPO"
export WMR_CONSTELLATION_RAW_SAMPLES_LOG=1
export WMR_CONSTELLATION_BLOB_TELEMETRY=1
export CONSTELLATION_TRACKER_LOG=info          # the telemetry lines are CT_INFO
export WMR_CONTROLLER_LED_INTENSITY=0          # 0108 stays OFF -- it breaks tracking, docs/126

echo "arm: gain=$GAIN exposure=${EXPO}us (driver defaults are 100 / 6000)"
setsid nohup "$HOME/vr/jack-in-wayland.sh" 1 ctrl </dev/null >"/tmp/cliff-arm-g$GAIN-e$EXPO.log" 2>&1 &

for _i in $(seq 1 60); do [ -S /run/user/1000/monado_comp_ipc ] && break; sleep 1; done
[ -S /run/user/1000/monado_comp_ipc ] || { echo "!! Monado never came up" >&2; exit 1; }

# WAIT for the role line; it is logged after the socket appears (this raced once already).
for _i in $(seq 1 30); do
    grep -q "right: HP Reverb G2 Right Controller" "$L" && break
    sleep 1
done
if grep -q "right: HP Reverb G2 Right Controller" "$L"; then
    echo "right controller registered"
else
    echo "!! right controller MISSING -- stop here, do not spend the operator's time" >&2
    exit 1
fi

P=$(pgrep -x monado-service | head -1)
echo "live service env:"
tr '\0' '\n' < "/proc/$P/environ" | grep -E "CAM_GAIN|CAM_EXPOSURE|BLOB_TELEMETRY|LED_INTENSITY" | sed 's/^/  /'
grep -i "battery raw" "$L" | grep Right | tail -1 | sed 's/^/  /'
