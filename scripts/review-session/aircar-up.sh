#!/bin/bash
# Review wearer session, part 2: Aircar 6dof through the launcher with only the neck arm changed.
#   aircar-up.sh <label> <neck_mm>
set -u
L="$1"; MM="$2"; R=~/vr/review-session; cd "$R"
ENVLINES=$(python3 - ~/Documents/reverb-g2/scripts <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import gui_env; e = gui_env.get()
for k in ("XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"):
    if k in e: print(f"{k}={e[k]}")
PY
)
while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$ENVLINES"
bluetoothctl power off >/dev/null
echo "$(date +%T) $L start" >> runs.txt
cd ~/vr && VR_BT_CTRL_CHECK=0 VR_LAUNCH_APPID=1073390 SLAM_PRED_NECK_ARM_MM="$MM" SLAM_POSE_AGE_LOG=512 \
    U_PACING_APP_LOG=debug setsid nohup python3 ~/vr/vr-launcher.py 1 6dof > "$R/aircar-$L.out" 2>&1 < /dev/null &
