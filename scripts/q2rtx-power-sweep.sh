#!/bin/bash
# q2rtx-power-sweep.sh -- GPU power-limit vs fps sweep using Quake II RTX's own timedemo,
# for a genuinely GPU-bound counter-example to docs/48's "power capping is free" VR result.
#
#   ./q2rtx-power-sweep.sh                  default sweep: 100 150 175 200 W, 2 reps each
#   ./q2rtx-power-sweep.sh -r 3 100 175 250  custom reps/levels
#   ./q2rtx-power-sweep.sh -h                full usage
#
# WHY THIS EXISTS (docs/48, 2026-08-23/T246 follow-up): T209 measured VR frame pacing
# UNCHANGED across GPU power caps down to 105W (Aircar is CPU/pacing-bound, so the GPU
# boosting to its limit for zero extra delivered frames is pure waste -- capping it costs
# nothing). Quake II RTX's path tracer is the opposite case: genuinely GPU-bound (95%
# utilization at any cap tried), so a single 175W-vs-100W datapoint already showed a real
# -24.2% fps hit. This script gets the actual curve instead of one point, the same
# discipline scripts/gpu-load-sweep.sh already applies to the VR/pacing side.
#
# vr-power-watchdog.py is stopped for the duration (would otherwise flip the cap back to
# power.conf's GPU_LIMIT_PCT the moment it notices the game running) and always restarted
# on exit, including Ctrl-C or a crash -- see the trap below. Needs root for `nvidia-smi
# -pl` and `systemctl stop/start` -- run as your normal user, not via sudo directly: each
# of those calls does its own `sudo`, so you get exactly one password prompt (sudo's
# credential cache covers the rest of the sweep) and Steam/the game still launch with your
# normal desktop session env, not root's.
#
# Requires: Quake II RTX installed (Steam appid 1089130), Steam already running (a cold
# Steam boot adds ~30-60s to the first rep only), game-stop.py next to this script.

set -u

APPID=1089130
CONSOLE_LOG="$HOME/.local/share/quake2rtx/baseq2/logs/console.log"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME_STOP="$HERE/game-stop.py"
VR="$HOME/vr"
[ -d "$VR" ] || VR="$HOME/Documents/reverb-g2"
OUT_CSV="$VR/logs/q2rtx-power-sweep-$(date +%Y%m%d-%H%M%S).csv"
LAUNCH_TIMEOUT_S=60

REPS=2
LEVELS=(100 150 175 200)

usage() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [-r REPS] [levels...]

  -r REPS   repetitions per power level. Default: 2.
  -h        this help.
  levels    GPU power limits in watts to sweep. Default: 100 150 175 200
            (card's floor/max here are 100W/250W -- nvidia-smi refuses anything
            outside that range with a clear error, this script doesn't re-check it).

Output: $VR/logs/q2rtx-power-sweep-<timestamp>.csv, columns:
        watts,rep,frames,seconds,fps
EOF
}

while getopts "r:h" opt; do
    case "$opt" in
        r) REPS="$OPTARG" ;;
        h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
[ "$#" -gt 0 ] && LEVELS=("$@")

# Caught live 2026-08-23: run as root (a `su`/`sudo -i` shell, not plain `sudo` per call),
# `steam -applaunch` has no desktop session to launch into (no DISPLAY/WAYLAND_DISPLAY for
# root, and $HOME becomes /root -- CONSOLE_LOG and OUT_CSV silently resolve to root's home
# instead of the real user's) -- every rep times out waiting for a result that can never
# arrive, no error, just 60s of silence per rep. Refuse early instead of burning minutes.
if [ "$(id -u)" = 0 ]; then
    echo "Don't run this as root (or under sudo -i/su) -- Steam needs YOUR desktop session," >&2
    echo "not root's. Run it as your normal user; it calls sudo itself for the nvidia-smi/" >&2
    echo "systemctl calls that actually need root." >&2
    exit 1
fi

WATCHDOG_WAS_ACTIVE=0
systemctl is-active --quiet vr-power-watchdog.service && WATCHDOG_WAS_ACTIVE=1

restore() {
    echo
    echo "Restoring: stopping any leftover Quake II RTX, restarting the watchdog..."
    python3 "$GAME_STOP" stop "$APPID" >/dev/null 2>&1
    if [ "$WATCHDOG_WAS_ACTIVE" = 1 ]; then
        sudo systemctl start vr-power-watchdog.service
    fi
}
trap restore EXIT

if [ "$WATCHDOG_WAS_ACTIVE" = 1 ]; then
    echo "Stopping vr-power-watchdog.service for the duration (would fight the sweep otherwise)."
    sudo systemctl stop vr-power-watchdog.service
fi

mkdir -p "$(dirname "$OUT_CSV")"
echo "watts,rep,frames,seconds,fps" > "$OUT_CSV"

run_one() {
    local watts="$1" rep="$2"
    local before_lines after_lines line frames seconds fps waited

    sudo nvidia-smi -pl "$watts" >/dev/null || { echo "  nvidia-smi -pl $watts failed -- skipping"; return 1; }

    before_lines=0
    [ -f "$CONSOLE_LOG" ] && before_lines="$(wc -l < "$CONSOLE_LOG")"

    steam -applaunch "$APPID" +set logfile 2 +timedemo 1 +demo q2demo1 >/dev/null 2>&1 &

    waited=0
    line=""
    while [ "$waited" -lt "$LAUNCH_TIMEOUT_S" ]; do
        sleep 2; waited=$((waited + 2))
        [ -f "$CONSOLE_LOG" ] || continue
        after_lines="$(wc -l < "$CONSOLE_LOG")"
        [ "$after_lines" -gt "$before_lines" ] || continue
        line="$(tail -n "+$((before_lines + 1))" "$CONSOLE_LOG" | grep -E 'frames,.*seconds:.*fps' | tail -1)"
        [ -n "$line" ] && break
    done

    python3 "$GAME_STOP" stop "$APPID" >/dev/null 2>&1

    if [ -z "$line" ]; then
        echo "  ${watts}W rep ${rep}: TIMED OUT waiting for the timedemo result (${LAUNCH_TIMEOUT_S}s) -- skipped"
        return 1
    fi
    # e.g. "[2026-08-23 16:46] 631 frames, 11.94 seconds: 52.838718 fps"
    frames="$(echo "$line" | grep -oE '[0-9]+ frames' | grep -oE '[0-9]+')"
    seconds="$(echo "$line" | grep -oE '[0-9.]+ seconds' | grep -oE '[0-9.]+')"
    fps="$(echo "$line" | grep -oE '[0-9.]+ fps' | grep -oE '[0-9.]+')"
    echo "  ${watts}W rep ${rep}: ${frames} frames, ${seconds}s, ${fps} fps"
    echo "${watts},${rep},${frames},${seconds},${fps}" >> "$OUT_CSV"
}

echo "=== q2rtx power sweep: ${LEVELS[*]} W, ${REPS} rep(s) each ==="
for watts in "${LEVELS[@]}"; do
    for rep in $(seq 1 "$REPS"); do
        run_one "$watts" "$rep"
        sleep 2  # settle between runs -- avoid one run's teardown racing the next launch
    done
done

echo
echo "=== summary (mean fps per level) ==="
awk -F, 'NR>1 {sum[$1]+=$5; n[$1]++} END {for (w in sum) printf "  %sW: %.2f fps (n=%d)\n", w, sum[w]/n[w], n[w]}' "$OUT_CSV" | sort -t: -k1 -n

echo
echo "Raw data: $OUT_CSV"
