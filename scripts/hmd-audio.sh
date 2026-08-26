#!/bin/bash
# Per-device audio control for the demo command center. PipeWire-native (pactl/wpctl), no
# ALSA-legacy anything.
#
#   ./hmd-audio.sh status              route + volume of the headset sink
#   ./hmd-audio.sh list                machine-readable: name|description|active|volume% per sink
#   ./hmd-audio.sh set <pct>           volume of the headset (USB) sink
#   ./hmd-audio.sh setsink <name> <pct>  per-device volume (dashboard's per-row slider)
#   ./hmd-audio.sh mute | unmute       headset sink
#   ./hmd-audio.sh headset             route to the headset only
#   ./hmd-audio.sh external            route to the onboard/external output only
#   ./hmd-audio.sh both                play on headset AND external at once
#   ./hmd-audio.sh outputs <s> [s...]  route to an arbitrary SET of sinks (checkbox-per-device)
#   ./hmd-audio.sh mic {on|off|status} microphone (source); demo default OFF/muted
#
# DUPLICATE-OUTPUT DESIGN (rewritten 2026-08-26 after a feedback incident): "play on several
# outputs at once" is done with a **module-combine-sink** -- one virtual sink that FANS OUT to
# the chosen real sinks. Streams play to the combined sink and reach every output, with NO
# monitor capture anywhere. The earlier pw-loopback approach (capture sink A's monitor, play to
# sink B) howled: two mirrors in opposite directions (headset->external + external->headset,
# left over from stale/orphaned loopbacks and a USB re-enum) formed a loop that drove volume to
# 100%% with a very short round-trip echo. A combine-sink cannot feed back -- it's a fan-out,
# not a loop. See docs/02-player-360.md / the reverb-g2 session notes for the full incident.
set -u

EXTERNAL_SINK_NAME="${EXTERNAL_SINK_NAME:-Starship/Matisse HD Audio Controller Analog Stereo}"
COMBINE_SINK_NAME="hmd_combined"
COMBINE_STATE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hmd-audio-combine"   # "moduleid\nslaveNames"

sink_id() {  # wpctl id of a sink by its wpctl label (for volume/mute on the headset)
    wpctl status 2>/dev/null | awk '/^ ├─ Sinks:/{f=1} /^ ├─ Sources:/{f=0} f' \
        | grep -oP "\d+(?=\.\s+${1//\//\\/})" | head -1
}
sink_name() {  # pactl node name of the first sink matching a grep pattern
    pactl list sinks short 2>/dev/null | awk '{print $2}' | grep -iE "$1" | head -1
}

SINK_ID=$(sink_id "USB Audio Analog Stereo")   # the headset sink, for set/mute
if [ -z "$SINK_ID" ]; then
    echo "USB Audio sink not found -- is the headset's companion enumerated? (lsusb | grep 0bda:4c15)" >&2
    exit 1
fi

stop_combine() {  # tear down any duplicate-output fan-out (tracked + orphaned) and legacy loopbacks
    if [ -f "$COMBINE_STATE" ]; then
        local mod; read -r mod < "$COMBINE_STATE"
        [ -n "$mod" ] && pactl unload-module "$mod" 2>/dev/null
        rm -f "$COMBINE_STATE"
    fi
    # belt-and-braces: unload ANY combine-sink module and kill ANY stray pw-loopback (legacy),
    # so a duplicate mode can never coexist with another and re-create the feedback loop.
    local m pid
    for m in $(pactl list modules short 2>/dev/null | awk '/module-combine-sink/{print $1}'); do
        pactl unload-module "$m" 2>/dev/null
    done
    for pid in $(pgrep -x pw-loopback 2>/dev/null); do kill -9 "$pid" 2>/dev/null; done
}

combine_slaves() {  # if the fan-out is live, print its slave (real) sink names, one per line
    [ -f "$COMBINE_STATE" ] || return 0
    local mod slaves; { read -r mod; read -r slaves; } < "$COMBINE_STATE"
    pactl list modules short 2>/dev/null | awk '{print $1}' | grep -qxF "$mod" || { rm -f "$COMBINE_STATE"; return 0; }
    printf '%s\n' "${slaves//,/$'\n'}"
}

move_streams() {  # move every playing stream to a sink by name
    local target="$1" sid
    for sid in $(pactl list sink-inputs short 2>/dev/null | awk '{print $1}'); do
        pactl move-sink-input "$sid" "$target" 2>/dev/null
    done
}

route_single() {  # route default + streams to ONE sink by name
    stop_combine
    pactl set-default-sink "$1" 2>/dev/null
    move_streams "$1"
    echo "audio -> $1"
}

route_multi() {  # play on SEVERAL sinks at once via a combine-sink fan-out (no feedback possible)
    stop_combine
    local slaves; slaves=$(IFS=,; echo "$*")
    local mod; mod=$(pactl load-module module-combine-sink sink_name="$COMBINE_SINK_NAME" \
        slaves="$slaves" sink_properties="device.description='HMD combined (all outputs)'" 2>/dev/null)
    if ! [[ "$mod" =~ ^[0-9]+$ ]]; then
        echo "both/outputs: combine-sink failed to load (slaves: $slaves)" >&2; exit 1
    fi
    printf '%s\n%s\n' "$mod" "$slaves" > "$COMBINE_STATE"
    pactl set-default-sink "$COMBINE_SINK_NAME" 2>/dev/null
    move_streams "$COMBINE_SINK_NAME"
    echo "audio -> combined ($slaves)"
}

resolve_external() {
    local n; n=$(sink_name "pci-.*07_00\.4\.analog-stereo|Starship|Matisse")
    [ -z "$n" ] && n=$(pactl list sinks short 2>/dev/null | awk '{print $2}' | grep -iE "analog-stereo" | grep -viE "usb" | head -1)
    echo "$n"
}
HS_NAME=$(sink_name "usb.*analog-stereo")

case "${1:-status}" in
    mute)   stop_combine; wpctl set-mute "$SINK_ID" 1; echo "muted (sink $SINK_ID)" ;;
    unmute) wpctl set-mute "$SINK_ID" 0; echo "unmuted (sink $SINK_ID)" ;;
    set)    wpctl set-volume "$SINK_ID" "${2:?usage: set <0-150>}%"; wpctl get-volume "$SINK_ID" ;;
    setsink)
        pactl set-sink-volume "${2:?usage: setsink <name> <pct>}" "${3:?usage: setsink <name> <pct>}%" \
            && echo "set $2 -> $3%" ;;
    headset)  route_single "$HS_NAME" ;;
    external) EXT=$(resolve_external); [ -n "$EXT" ] || { echo "external sink not found" >&2; exit 1; }
              route_single "$EXT" ;;
    both)     EXT=$(resolve_external); [ -n "$HS_NAME" ] && [ -n "$EXT" ] || { echo "both: sink names unresolved" >&2; exit 1; }
              route_multi "$HS_NAME" "$EXT" ;;
    outputs)  shift; [ $# -ge 1 ] || { echo "usage: outputs <sink> [sink ...]" >&2; exit 1; }
              if [ $# -eq 1 ]; then route_single "$1"; else route_multi "$@"; fi ;;
    mic)
        MIC="${MIC_SOURCE:-@DEFAULT_SOURCE@}"
        case "${2:-status}" in
            on)     pactl set-source-mute "$MIC" 0 && echo "mic ON ($MIC)" ;;
            off)    pactl set-source-mute "$MIC" 1 && echo "mic OFF/muted ($MIC)" ;;
            status) case "$(pactl get-source-mute "$MIC" 2>/dev/null)" in *yes*) echo "muted" ;; *) echo "on" ;; esac ;;
            *) echo "usage: mic {on|off|status}" >&2; exit 1 ;;
        esac ;;
    list)
        # name|description|active|volume% per REAL sink. The virtual combine sink is hidden.
        # active = default sink OR a slave of the live fan-out.
        DEFAULT_NAME=$(pactl get-default-sink 2>/dev/null)
        SLAVES=$(combine_slaves)
        pactl list sinks 2>/dev/null | awk '
            /^\tName:/ { name=$2 }
            /^\tDescription:/ { $1=""; sub(/^ */,""); desc=$0; print name "|" desc }
        ' | while IFS='|' read -r name desc; do
            [ "$name" = "$COMBINE_SINK_NAME" ] && continue
            active=0
            [ "$name" = "$DEFAULT_NAME" ] && active=1
            printf '%s\n' "$SLAVES" | grep -qxF "$name" && active=1
            vol=$(pactl get-sink-volume "$name" 2>/dev/null | grep -oE '[0-9]+%' | head -1 | tr -d '%')
            echo "${name}|${desc}|${active}|${vol:-0}"
        done ;;
    status)
        if [ -n "$(combine_slaves)" ]; then
            ROUTE="both/combined ($(combine_slaves | paste -sd, -))"
        else
            DEFAULT_NAME=$(pactl get-default-sink 2>/dev/null)
            case "$DEFAULT_NAME" in *usb*) ROUTE="headset" ;; *) ROUTE="external" ;; esac
        fi
        echo "route: $ROUTE"
        wpctl get-volume "$SINK_ID" ;;
    *) echo "usage: $0 {status|list|set <pct>|setsink <name> <pct>|mute|unmute|headset|external|both|outputs <sink..>|mic {on|off|status}}" >&2; exit 1 ;;
esac
