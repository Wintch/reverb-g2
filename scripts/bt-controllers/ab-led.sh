#!/bin/bash
# LED-intensity A/B over system BT. usage: ab-led.sh INTENSITY "light dark"   (phase order; light|dark)
# One Monado (ctrl + constellation) per intensity; per phase: 20 s to set the room, 60 s measured.
# Tracked ratio = get_tracked_pose lines position_tracked=yes / all, per hand, within the phase's log window.
I="${1:-0}"; ORDER="${2:-light dark}"
OUT=~/ab-led.log; LOG=~/vr/jack-in-wayland.log
export XDG_RUNTIME_DIR=/run/user/$(id -u)
say() { espeak-ng -v es "$1" >/dev/null 2>&1; }
log() { echo "$(date +%T) $*" >> "$OUT"; }
cd ~/vr || exit 1
log "=== run intensity=$I order=$ORDER"
./jack-in-wayland.sh down >/dev/null 2>&1; rm -f /run/user/1000/monado_comp_ipc
say "Prueba con intensidad $I. Agita los dos joys ahora"
WMR_CONSTELLATION_CONTROLLERS=1 WMR_CONTROLLER_LED_INTENSITY=$I ./jack-in-wayland.sh dev ctrl > ~/vr/ab-led-launch.out 2>&1
if ! pgrep -x monado-service >/dev/null; then log "LAUNCH FAILED"; say "Falló el lanzamiento"; exit 1; fi
log "monado up: $(grep -c . ~/vr/ab-led-launch.out) launcher lines"
setsid nohup ./play360.sh -s -t 400 ~/vr/openjk_screenshot.png > ~/vr/ab-led-player.out 2>&1 < /dev/null &
for _ in $(seq 1 60); do grep -q "Started native session, 1 active" "$LOG" && break; sleep 2; done
say "Ponte el visor y agarra los joys"; sleep 25
for ph in $ORDER; do
  if [ "$ph" = dark ]; then say "Fase oscura. Apaga la luz de la sala. Quédate con el visor puesto"; else say "Fase con luz. Enciende la luz de la sala"; fi
  sleep 20
  say "Manos delante, aros hacia el visor, muévelas despacio. Mido ya"
  s=$(wc -l < "$LOG"); sleep 60; e=$(wc -l < "$LOG")
  sed -n "${s},${e}p" "$LOG" > /tmp/ab-win.log
  r=""; for h in Left Right; do y=$(grep "get_tracked_pose \[HP Reverb G2 $h" /tmp/ab-win.log | grep -c "position_tracked=yes"); n=$(grep "get_tracked_pose \[HP Reverb G2 $h" /tmp/ab-win.log | grep -c "position_tracked=no"); r="$r $h=$y/$((y+n))"; done
  log "intensity=$I phase=$ph tracked:$r rejected=$(grep -c REJECTED /tmp/ab-win.log) logwin=$((e-s))"
  say "Fin de fase"; sleep 3
done
for p in $(ps -eo pid,args | awk '/play360|hello_xr/ && !/awk/ {print $1}'); do kill $p 2>/dev/null; done
sleep 3; ./jack-in-wayland.sh down >/dev/null 2>&1; rm -f /run/user/1000/monado_comp_ipc /tmp/ab-win.log
log "done"; say "Brazo terminado. Quítate el visor"
