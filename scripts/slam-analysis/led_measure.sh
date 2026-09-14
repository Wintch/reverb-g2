#!/bin/bash
# ONE measurement window. Nothing starts until the operator has already confirmed out of band.
#
#   $1 = label for this window (e.g. "arm0-d050")
#   $2 = seconds to measure (default 20)
#
# Counts the raw pre-gate constellation samples that land in the window and summarises the
# distance the solve reports, which is the hand-to-camera range while the headset is stationary
# in ctrl mode. Both numbers matter: the COUNT is docs/125's visibility cliff, the DISTANCE is
# the never-validated absolute scale (one hand once read 0.556 m against a 0.75 m tape).
set -u
LABEL="$1"
SECS="${2:-20}"
L="$HOME/vr/jack-in-wayland.log"
PAT="raw constellation sample \[HP Reverb G2 Right"
OUT="/mnt/vrtmp/ledmeasure"
mkdir -p "$OUT"

say() { espeak-ng -v es -s 150 "$1" >/dev/null 2>&1; }

GUI_PID=$(pgrep -u "$(id -un)" -f gnome-session-binary | head -1)
[ -n "$GUI_PID" ] || { echo "!! no GUI session" >&2; exit 1; }
while IFS= read -r -d '' kv; do
    case "$kv" in
        XDG_RUNTIME_DIR=*|DBUS_SESSION_BUS_ADDRESS=*|WAYLAND_DISPLAY=*|DISPLAY=*) export "${kv?}" ;;
    esac
done < "/proc/$GUI_PID/environ"

if ! pgrep -x monado-service >/dev/null; then
    echo "!! monado-service is not running" >&2
    exit 1
fi

say "Preparate."
sleep 5
BEFORE=$(grep -c "$PAT" "$L" 2>/dev/null); BEFORE=${BEFORE:-0}
say "Ya. Quieto."
sleep "$SECS"
AFTER=$(grep -c "$PAT" "$L" 2>/dev/null); AFTER=${AFTER:-0}
say "Listo. Bajá el brazo."

N=$((AFTER - BEFORE))
grep "$PAT" "$L" | tail -n "$N" > "$OUT/$LABEL.txt" 2>/dev/null

echo "label: $LABEL"
echo "window: ${SECS}s"
echo "raw samples: $N   ($(python3 -c "print(f'{$N/$SECS:.1f}')")/s)"

if [ "$N" -gt 0 ]; then
    grep -oE "dist=[0-9.]+" "$OUT/$LABEL.txt" | cut -d= -f2 | python3 -c "
import sys, statistics
v = [float(x) for x in sys.stdin if x.strip()]
if v:
    v.sort()
    print(f'dist_m: n={len(v)} min={v[0]:.3f} p50={statistics.median(v):.3f} p90={v[int(0.9*(len(v)-1))]:.3f} max={v[-1]:.3f}')
"
fi
