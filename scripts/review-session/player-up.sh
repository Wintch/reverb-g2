#!/bin/bash
# Review wearer session, part 1: Monado 3dof + the player on ~/vr/media/review, keys from a FIFO.
set -u
R=~/vr/review-session; mkdir -p "$R"; cd "$R"
ENVLINES=$(python3 - ~/Documents/reverb-g2/scripts <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import gui_env; e = gui_env.get()
for k in ("XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"):
    if k in e: print(f"{k}={e[k]}")
PY
)
while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$ENVLINES"
bluetoothctl power off >/dev/null
rm -f /run/user/1000/monado_comp_ipc
VR_BT_CTRL_CHECK=0 ~/vr/jack-in-wayland.sh up 1 3dof > up.out 2>&1
sleep 4
pgrep -x monado-service >/dev/null && [ -S /run/user/1000/monado_comp_ipc ] || { echo "UP FAILED"; tail -5 up.out; exit 1; }
rm -f keys; mkfifo keys
setsid sleep 3600 > keys & echo $! > holder.pid
setsid script -q -f -c "$HOME/vr/play360.sh -t 1500 $HOME/vr/media/review" player.out < keys > /dev/null 2>&1 & echo $! > player.pid
sleep 8
pgrep -x hello_xr >/dev/null && echo "PLAYER UP ($(pgrep -x hello_xr))" || { echo "PLAYER FAILED"; tail -8 player.out; }
