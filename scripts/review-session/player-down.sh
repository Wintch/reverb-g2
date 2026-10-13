#!/bin/bash
set -u
R=~/vr/review-session; cd "$R"
[ -f player.pid ] && kill -TERM -- "-$(cat player.pid)" 2>/dev/null; sleep 2
[ -f holder.pid ] && kill "$(cat holder.pid)" 2>/dev/null
~/vr/jack-in-wayland.sh down > down.out 2>&1
bluetoothctl power on >/dev/null
sleep 2; echo "monado: $(pgrep -x monado-service || echo none), hello_xr: $(pgrep -x hello_xr || echo none)"
