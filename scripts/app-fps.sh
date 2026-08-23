#!/bin/bash
# app-fps.sh -- the APP's real frame rate, counted from Monado's own pacer log.
#
#   ./app-fps.sh [window_s=20] [repeats=3] [log=~/vr/jack-in-wayland.log]
#
# Why (2026-08-21, T244): frame-pacing.sh counts compositor-missed slots and Steam's overlay
# counts whatever the app believes -- both were structurally blind to the 45/30 fps ceiling
# (0.00% late + "45 fps" while the app delivered 29). The only honest number is how many
# frames the app actually DELIVERED per second, and the app pacer prints one line per
# delivered frame at debug level:  "Delivered frame 2.34ms late." (u_pacing_app.c).
# Needs U_PACING_APP_LOG=debug on the SERVICE (export it before jack-in-wayland.sh; ambient
# wins over the script's VR_PACING=1 default of info). Two clients = double the rate
# (151/s = two titles alive, the T244 trap) -- run `game-stop.py status` first.
set -u
WINDOW="${1:-20}"
REPEATS="${2:-3}"
LOG="${3:-$HOME/vr/jack-in-wayland.log}"
[ -r "$LOG" ] || { echo "no log at $LOG" >&2; exit 1; }
if ! grep -q "Delivered frame" "$LOG"; then
    echo "!! no 'Delivered frame' lines in $LOG at all -- is U_PACING_APP_LOG=debug set on the service," >&2
    echo "   and is a client actually rendering? (an idle compositor delivers nothing)" >&2
fi
for ((i = 1; i <= REPEATS; i++)); do
    before=$(grep -c "Delivered frame" "$LOG")
    sleep "$WINDOW"
    after=$(grep -c "Delivered frame" "$LOG")
    n=$((after - before))
    # integer fps*100 so the result is exact to 0.01 without bc
    fps100=$(( n * 100 / WINDOW ))
    printf 'window %d/%d: %d delivered frames in %ds = %d.%02d fps\n' "$i" "$REPEATS" "$n" "$WINDOW" $((fps100 / 100)) $((fps100 % 100))
done
