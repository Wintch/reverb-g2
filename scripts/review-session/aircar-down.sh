#!/bin/bash
set -u
R=~/vr/review-session
python3 ~/Documents/reverb-g2/scripts/game-stop.py stop all > "$R/game-stop.out" 2>&1
sleep 3
~/vr/jack-in-wayland.sh down > "$R/down.out" 2>&1
sleep 2
echo "$(date +%T) down" >> "$R/runs.txt"
python3 ~/Documents/reverb-g2/scripts/game-stop.py status 2>&1 | tail -1
echo "monado: $(pgrep -x monado-service || echo none)"
