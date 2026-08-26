#!/bin/bash
# Quick volume + output-routing control for the headset's USB Audio sink,
# without memorizing PipeWire IDs (they get renumbered on every USB2
# re-enumeration -- looked up by name every time, not cached).
#
#   ./hmd-audio.sh mute      silence the headset sink immediately
#   ./hmd-audio.sh unmute
#   ./hmd-audio.sh status    current volume/mute state + which output is the system DEFAULT
#   ./hmd-audio.sh set 20    set headset sink volume to 20%
#   ./hmd-audio.sh headset   route system default audio to the headset (also sets volume
#                            to HEADSET_VOLUME_PCT, 130 by default -- 100%/120% both read as quiet)
#   ./hmd-audio.sh external  route system default audio back to the onboard/external output
#
# Found live 2026-08-26: the headset's USB Audio sink is never the system default on its
# own (this rig's onboard analog output is), so a game launched normally plays out loud on
# the room speakers, not the headset -- surprising for a demo where the wearer expects
# sound in their ears. `headset`/`external` fix the DEFAULT (new streams) AND move any
# already-playing stream over (pactl move-sink-input) -- set-default alone does NOT
# retroactively move a stream that started before it ran.
set -u

EXTERNAL_SINK_NAME="${EXTERNAL_SINK_NAME:-Starship/Matisse HD Audio Controller Analog Stereo}"
# 100% read as quiet, then 120% still not enough (2026-08-26, live) -- wpctl allows going over
# 100% (software gain), so `headset` routing applies this level every time instead of
# relying on whatever the sink happened to be left at from a previous session.
HEADSET_VOLUME_PCT="${HEADSET_VOLUME_PCT:-130}"

sink_id() {  # sink_id "<exact wpctl label>"
    wpctl status 2>/dev/null | awk '/^ ├─ Sinks:/{f=1} /^ ├─ Sources:/{f=0} f' \
        | grep -oP "\d+(?=\.\s+${1//\//\\/})" | head -1
}

SINK_ID=$(sink_id "USB Audio Analog Stereo")

if [ -z "$SINK_ID" ]; then
    echo "USB Audio sink not found -- is the headset's companion enumerated? (lsusb | grep 0bda:4c15)" >&2
    exit 1
fi

route_to() {  # route_to <sink_id> <label, for the printed message>
    local target="$1" label="$2"
    wpctl set-default "$target"
    while read -r sid; do
        [ -n "$sid" ] && pactl move-sink-input "$sid" "$target" 2>/dev/null
    done < <(pactl list sink-inputs short 2>/dev/null | awk '{print $1}')
    echo "default audio -> $label (sink $target)"
}

case "${1:-status}" in
    mute)   wpctl set-mute "$SINK_ID" 1; echo "muted (sink $SINK_ID)" ;;
    unmute) wpctl set-mute "$SINK_ID" 0; echo "unmuted (sink $SINK_ID)" ;;
    set)    wpctl set-volume "$SINK_ID" "${2:?usage: set <0-100>}%"; wpctl get-volume "$SINK_ID" ;;
    headset)
        route_to "$SINK_ID" "headset"
        wpctl set-volume "$SINK_ID" "${HEADSET_VOLUME_PCT}%"
        wpctl get-volume "$SINK_ID"
        ;;
    external)
        EXT_ID=$(sink_id "$EXTERNAL_SINK_NAME")
        if [ -z "$EXT_ID" ]; then
            echo "external sink '$EXTERNAL_SINK_NAME' not found -- set EXTERNAL_SINK_NAME= to override" >&2
            exit 1
        fi
        route_to "$EXT_ID" "external"
        ;;
    status)
        DEFAULT_NAME=$(pactl get-default-sink 2>/dev/null)
        case "$DEFAULT_NAME" in
            *usb*) ROUTE="headset" ;;
            *)     ROUTE="external" ;;
        esac
        echo "route: $ROUTE ($DEFAULT_NAME)"
        wpctl get-volume "$SINK_ID"
        ;;
    *) echo "usage: $0 {mute|unmute|status|set <pct>|headset|external}" >&2; exit 1 ;;
esac
