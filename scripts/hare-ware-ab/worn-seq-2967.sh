#!/bin/bash
# worn-seq-2967.sh -- blind worn A/B of the !2967 follow-ups: leg 1 and leg 2 are monado-hw-nofix (A) and
# monado-2967-hw (B) in a random order that is written to ~/vr/logs/worn-order-2967.txt and NOT announced.
#   setsid nohup bash worn-seq-2967.sh [client_s] > ~/vr/logs/worn-seq-2967.out 2>&1 < /dev/null &
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); LOGS=$HOME/vr/logs; CLIENT_S=${1:-120}
say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
if [ -n "${WORN_ORDER:-}" ]; then ORDER="$WORN_ORDER"; elif [ $((RANDOM % 2)) -eq 0 ]; then ORDER="monado-hw-nofix monado-2967-hw"; else ORDER="monado-2967-hw monado-hw-nofix"; fi
echo "$ORDER" > "$LOGS/worn-order-2967.txt"
i=0
for wt in $ORDER; do
	i=$((i + 1)); label="blind$i"
	bash "$HERE/worn-leg-2967.sh" "$label" "$wt" "$i" "$CLIENT_S" > "$LOGS/worn-launch-$label.out" 2>&1 < /dev/null
	echo "leg $i ($label) -> $(head -1 "$LOGS/worn-$label.done" 2>/dev/null)"
	[ "$i" -lt 2 ] && { say "Descanso de treinta segundos. Seguí con el visor puesto"; sleep 40; }
done
say "Terminó la prueba. Podés sacarte el visor."
echo "done $(date +%T)" > "$LOGS/worn-seq-2967.done"
