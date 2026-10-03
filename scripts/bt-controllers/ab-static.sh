#!/bin/bash
# Static LED-intensity protocol over system BT. usage: ab-static.sh LABEL LEFT RIGHT [AMBIENT-label]
# Headset fixed (on a desk, NOT worn); the joys are held still (rings toward the cameras) at 50, 75, 100 cm
# from the front of the headset. LEFT/RIGHT = per-hand LED intensity (0 = no command, the historical arm).
# Per distance: 12 s to place, 25 s measured (+ per-controller report rate to detect sleeping joys); tracked ratio from get_tracked_pose lines in that log window.
LABEL="${1:?label}"; L="${2:-0}"; R="${3:-0}"; AMB="${4:-lit-room}"
OUT=~/ab-static.log; LOG=~/vr/jack-in-wayland.log
export XDG_RUNTIME_DIR=/run/user/$(id -u)
say() { espeak-ng -v es "$1" >/dev/null 2>&1; }
log() { echo "$(date +%T) $*" >> "$OUT"; }
cd ~/vr || exit 1
log "=== $LABEL left=$L right=$R ambient=$AMB"
./jack-in-wayland.sh down >/dev/null 2>&1; rm -f /run/user/1000/monado_comp_ipc
say "Brazo $LABEL. Agita los dos joys ahora"
WMR_CONSTELLATION_CONTROLLERS=1 WMR_CONTROLLER_LED_INTENSITY_LEFT=$L WMR_CONTROLLER_LED_INTENSITY_RIGHT=$R \
  ./jack-in-wayland.sh dev ctrl > ~/vr/ab-static-launch.out 2>&1
if ! pgrep -x monado-service >/dev/null; then log "LAUNCH FAILED"; say "Falló el lanzamiento"; exit 1; fi
setsid nohup ./play360.sh -s -t 400 ~/vr/openjk_screenshot.png > ~/vr/ab-static-player.out 2>&1 < /dev/null &
for _ in $(seq 1 60); do grep -q "Started native session, 1 active" "$LOG" && break; sleep 2; done
log "led first-send lines: $(grep -c 'first LED pulse-train' "$LOG") ($(grep -o 'first LED pulse-train.*' "$LOG" | tr '\n' ';' | cut -c1-200))"
sleep 8
for d in 50 75 100; do
  say "A $d centímetros del visor. Joys en la mano, aros hacia el visor. Muévelos apenas para que no se duerman"
  sleep 12
  say "Mido"; s=$(wc -l < "$LOG"); RATE=$(python3 ~/vr/rate-window.py 25); e=$(wc -l < "$LOG")
  sed -n "${s},${e}p" "$LOG" > /tmp/abs-win.log
  r=""; for h in Left Right; do y=$(grep "get_tracked_pose \[HP Reverb G2 $h" /tmp/abs-win.log | grep -c "position_tracked=yes"); n=$(grep "get_tracked_pose \[HP Reverb G2 $h" /tmp/abs-win.log | grep -c "position_tracked=no"); r="$r $h=$y/$((y+n))"; done
  log "$LABEL d=${d}cm tracked:$r rejected=$(grep -c REJECTED /tmp/abs-win.log) reports/s: $RATE"
done
for p in $(ps -eo pid,args | awk '/play360|hello_xr/ && !/awk/ {print $1}'); do kill $p 2>/dev/null; done
sleep 3; ./jack-in-wayland.sh down >/dev/null 2>&1; rm -f /run/user/1000/monado_comp_ipc /tmp/abs-win.log
log "done"; say "Brazo terminado"
