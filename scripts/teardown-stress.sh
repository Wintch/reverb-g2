#!/bin/bash
# teardown-stress.sh -- bring the compositor up and down N times, headset on the desk, and count
# monado-service cores. Exercises the SLAM-tracker teardown race (patch 0104: pop_pose SIGSEGV
# when the camera USB thread pushes into a stopped tracker). Half the cycles run a light client
# (play360.sh -t) so the pose-query path is exercised too. Detached: run with setsid nohup, poll
# the .done marker. Never run while someone wears the headset.
#
#   scripts/teardown-stress.sh [cycles=8] [up_seconds=20]      (needs gui_env.py next to it)
set -u
N="${1:-8}"; UP_S="${2:-20}"
VR="$HOME/vr"; OUT="$HOME/vr/logs/teardown-stress"; mkdir -p "$OUT"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Live-discover the Wayland env (gui_env.py, shared with the dashboard): a detached
# setsid/nohup shell has XDG_SESSION_TYPE=tty and jack-in-wayland.sh refuses to launch in it
# AND writes its fail marker, which then blocks every dashboard launch until --force up.
# The first run of this script (2026-08-29 16:16) did exactly that: 18 "cycles" that never
# brought Monado up, and a blocked booth. Hence this block and the per-cycle up check below.
ENVLINES=$(python3 - "$HERE" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import gui_env
e = gui_env.get()
for k in ("XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"):
    if k in e: print(f"{k}={e[k]}")
PY
)
[ -z "$ENVLINES" ] && { echo "could not read gui_env, aborting" >&2; exit 1; }
while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$ENVLINES"
[ -e "$VR/.jack-in-failed" ] && { echo "jack-in fail marker present ($VR/.jack-in-failed) -- fix the cause first, not looping on it" >&2; exit 1; }
STAMP="$(date +%Y%m%d-%H%M%S)"; LOG="$OUT/stress-$STAMP.log"; DONE="$OUT/stress-$STAMP.done"
exec > "$LOG" 2>&1
START_TS="$(date '+%Y-%m-%d %H:%M:%S')"
echo "$START_TS teardown stress: $N cycles, $UP_S s up, binary $(stat -c %y "$VR/monado/build/src/xrt/targets/service/monado-service" | cut -d. -f1)"
for i in $(seq 1 "$N"); do
    if pgrep -x monado-service >/dev/null; then echo "cycle $i: monado already up -- forcing down"; "$VR/jack-in-wayland.sh" down >/dev/null 2>&1; sleep 3; fi
    rm -f /run/user/1000/monado_comp_ipc
    echo "$(date +%T) cycle $i: up"
    "$VR/jack-in-wayland.sh" up 1 6dof > "$OUT/stress-$STAMP-cycle$i-up.out" 2>&1
    sleep 5
    if ! pgrep -x monado-service >/dev/null || [ ! -S /run/user/1000/monado_comp_ipc ]; then
        echo "$(date +%T) cycle $i: UP FAILED (monado $(pgrep -x monado-service || echo none), socket $([ -S /run/user/1000/monado_comp_ipc ] && echo yes || echo none)) -- stopping, see $OUT/stress-$STAMP-cycle$i-up.out"
        tail -5 "$OUT/stress-$STAMP-cycle$i-up.out"
        echo "aborted at cycle $i" > "$DONE"; exit 1
    fi
    echo "$(date +%T) cycle $i: up ok (monado $(pgrep -x monado-service | head -1), $(grep -o "Headset USB devices: [0-9]/[0-9]" "$OUT/stress-$STAMP-cycle$i-up.out" | head -1))"
    CLIENT=""
    if [ $((i % 2)) -eq 0 ] && [ -x "$VR/play360.sh" ]; then
        "$VR/play360.sh" -t > /dev/null 2>&1 &
        CLIENT=$!
        echo "$(date +%T) cycle $i: client play360 -t pid $CLIENT"
    fi
    sleep "$UP_S"
    if [ -n "$CLIENT" ]; then kill "$CLIENT" 2>/dev/null; sleep 2; fi
    echo "$(date +%T) cycle $i: down"
    "$VR/jack-in-wayland.sh" down > "$OUT/stress-$STAMP-cycle$i-down.out" 2>&1
    sleep 3
    for p in $(pgrep -x monado-service); do kill "$p"; done; sleep 2
    for p in $(pgrep -x monado-service); do kill -9 "$p"; done
    rm -f /run/user/1000/monado_comp_ipc
    D=$(grep -c "0104:" "$VR/jack-in-wayland.log" 2>/dev/null); D=${D:-0}
    W=$(grep -o "0104: [0-9]* sample" "$VR/jack-in-wayland.log" 2>/dev/null | head -1)
    cp "$VR/jack-in-wayland.log" "$OUT/stress-$STAMP-cycle$i-jack-in.log"
    echo "$(date +%T) cycle $i: down done, monado $(pgrep -x monado-service || echo none); 0104 warn lines=$D ${W:+($W)}"
    sleep 5
done
echo "=== cores since start:"
coredumpctl list --since "$START_TS" --no-pager 2>/dev/null | grep -c monado-service | sed 's/^/monado-service cores: /'
coredumpctl list --since "$START_TS" --no-pager 2>/dev/null | tail -5
echo "$(date +%T) done"
echo ok > "$DONE"
