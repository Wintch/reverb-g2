#!/bin/bash
# Quick volume control for the headset's USB Audio sink, without memorizing PipeWire IDs.
#
#   ./hmd-audio.sh mute      silence it immediately
#   ./hmd-audio.sh unmute
#   ./hmd-audio.sh status    current volume/mute state
#   ./hmd-audio.sh set 20    set volume to 20%
set -u

SINK_ID=$(wpctl status 2>/dev/null | awk '/^ ├─ Sinks:/{f=1} /^ ├─ Sources:/{f=0} f' | grep -oP '\d+(?=\.\s+USB Audio Analog Stereo)')

if [ -z "$SINK_ID" ]; then
    echo "USB Audio sink not found -- is the headset's companion enumerated? (lsusb | grep 0bda:4c15)" >&2
    exit 1
fi

case "${1:-status}" in
    mute)   wpctl set-mute "$SINK_ID" 1; echo "muted (sink $SINK_ID)" ;;
    unmute) wpctl set-mute "$SINK_ID" 0; echo "unmuted (sink $SINK_ID)" ;;
    set)    wpctl set-volume "$SINK_ID" "${2:?usage: set <0-100>}%"; wpctl get-volume "$SINK_ID" ;;
    status) wpctl get-volume "$SINK_ID" ;;
    *)      echo "usage: $0 {mute|unmute|status|set <pct>}" >&2; exit 1 ;;
esac
