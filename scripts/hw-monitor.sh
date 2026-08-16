#!/bin/bash
# hw-monitor.sh - transition-only background monitor for the headset's USB/DP health.
#
# Written 2026-08-15 (T183) during a live investigation of the USB2 branch's marginal
# contact (companion 03f0:0580 + audio 0bda:4c15, behind hub 04b4:6506): raw log tailing
# does not scale (jack-in-wayland.log hit 53 MB in ~19 minutes of active storm) and a plain
# polling loop that logs every sample is just as bad. This logs ONLY on state change, plus
# a coarse companion-error/imu_age_ms snapshot every ~30s, so the file stays tiny (a few KB)
# even over hours. It answered "how long do the USB2 blips last / how far apart are they"
# with real timestamps for the first time this project had that data: consistently ~3s
# drops, 25-90s apart, while the USB3 branch (cameras/controller tunnel, docs/03) never
# moved once in the same window -- see docs/pruebas.jsonl T183 for the full timeline.
#
# Usage:
#   ./hw-monitor.sh &            start monitoring loop in the background
#   ./hw-monitor.sh --mark TEXT  append a manual timestamped action marker, so state
#                                 transitions can be correlated with what was actually
#                                 done at that moment (relaunch, game start, cable reseat...)

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VR="$(cd "$HERE/.." && pwd)"
[ -d "$HOME/vr" ] && VR="$HOME/vr"
LOG="$VR/jack-in-wayland.log"
MONLOG="$VR/logs/hw-monitor.log"
mkdir -p "$(dirname "$MONLOG")"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ "${1:-}" = "--mark" ]; then
    shift
    echo "$(ts)  ACTION: $*" >> "$MONLOG"
    exit 0
fi

usb_state() {
    local found bus4
    found=$(lsusb | grep -cE "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15")
    bus4=$(lsusb | grep -c "Bus 004 Device [0-9]*.*04b4:6504\|Bus 004 Device [0-9]*.*045e:0659")
    echo "usb=${found}/5 usb3_branch=${bus4}/2"
}

dp_state() {
    cat /sys/class/drm/card0-DP-*/status 2>/dev/null | grep -c connected
}

echo "$(ts)  MONITOR START  $(usb_state) dp_connected=$(dp_state)" >> "$MONLOG"

prev_usb=""
prev_dp=""
prev_ms_up=""
last_snapshot=0

while true; do
    cur_usb="$(usb_state)"
    cur_dp="$(dp_state)"
    ms_pid="$(pgrep -f "monado[-]service" 2>/dev/null | head -1)"
    cur_ms_up="down"; [ -n "$ms_pid" ] && cur_ms_up="up"

    if [ "$cur_usb" != "$prev_usb" ]; then
        echo "$(ts)  USB CHANGE   $cur_usb  (was: ${prev_usb:-none})" >> "$MONLOG"
        prev_usb="$cur_usb"
    fi
    if [ "$cur_dp" != "$prev_dp" ]; then
        echo "$(ts)  DP CHANGE    connected_ports=$cur_dp  (was: ${prev_dp:-none})" >> "$MONLOG"
        prev_dp="$cur_dp"
    fi
    if [ "$cur_ms_up" != "$prev_ms_up" ]; then
        echo "$(ts)  MONADO       $cur_ms_up  (pid ${ms_pid:-none})" >> "$MONLOG"
        prev_ms_up="$cur_ms_up"
    fi

    # Coarse companion-error snapshot every ~30s, only while monado-service is up.
    # Reads the live log's current line count, never copies it -- no disk growth of its own.
    now_epoch=$(date +%s)
    if [ "$cur_ms_up" = "up" ] && [ $((now_epoch - last_snapshot)) -ge 30 ] && [ -f "$LOG" ]; then
        errs=$(grep -c "control_read_packets.*os_hid_read returned -1" "$LOG" 2>/dev/null)
        calib_left_age=$(grep "CALIB hand=left" "$LOG" 2>/dev/null | tail -1 | grep -oE "imu_age_ms=[0-9]+")
        calib_right_age=$(grep "CALIB hand=right" "$LOG" 2>/dev/null | tail -1 | grep -oE "imu_age_ms=[0-9]+")
        echo "$(ts)  SNAPSHOT     companion_errors=${errs:-0} left.${calib_left_age:-imu_age_ms=NA} right.${calib_right_age:-imu_age_ms=NA}" >> "$MONLOG"
        last_snapshot=$now_epoch
    fi

    sleep 3
done
