#!/bin/bash
# Guided player check: voice prompts in the headset, keys sent to the paused player.
set -u
R=~/vr/review-session; K="$R/keys"; LOG="$R/protocol.log"
export XDG_RUNTIME_DIR=/run/user/1000
say() { echo "$(date +%T.%N | cut -c1-12) SAY $1" >> "$LOG"; espeak-ng -v es -s 150 "$1" >/dev/null 2>&1; }
key() { echo "$(date +%T.%N | cut -c1-12) KEY $(printf %q "$1")" >> "$LOG"; printf "%s" "$1" > "$K"; }
: > "$LOG"
say "Paso uno. El video está en pausa. Recordá la letra, el número de frame y el tiempo."; sleep 8
key h; sleep 1
say "Paso dos. Salté diez segundos para atrás, sin despausar. Recordá el número y el tiempo nuevos."; sleep 8
key ">"; sleep 1; key ">"; sleep 1; key ">"; sleep 1
say "Paso tres. Avancé tres frames. Recordá el número."; sleep 8
say "Paso cuatro. Ahora reproduce. Tiene que sonar un tono grave que se corta a los quince segundos, y el video tiene que seguir moviéndose después."; key " "; sleep 20
say "Paso cinco. Girá la cabeza noventa grados a la derecha y quedate así."; sleep 5
key $'\r'; sleep 1
say "Recentrado. El texto tiene que haber quedado justo enfrente tuyo."; sleep 7
say "Paso seis. Paso al video siguiente. Tiene que decir B y sonar un tono agudo."; key n; sleep 10
say "Listo. Podés sacarte el visor y contarme."
echo "$(date +%T) END" >> "$LOG"
