#!/bin/bash
# heaven-power-sweep.sh -- GPU power-limit vs fps sweep using Unigine Heaven 4.0's own
# built-in benchmark, following the exact pattern scripts/q2rtx-power-sweep.sh already
# established (docs/48) -- just for a second, independent GPU-bound flat benchmark, and
# one that has NO Steam Cloud dependency at all (standalone Proton prefix, docs/69), so
# it can't be blocked by a stuck/pending cloud-sync entry the way Quake II RTX can.
#
#   ./heaven-power-sweep.sh                  default sweep: 100 130 160 210 W, 2 reps each
#   ./heaven-power-sweep.sh -r 3 100 210      custom reps/levels
#   ./heaven-power-sweep.sh -h                full usage
#
# Default levels match this project's 4-mode framework (full-eco/smart-eco/max-reasonable/
# turbo, see project_gpu_fps_per_watt_modes) rather than the older ad-hoc numbers, so this
# title's data lines up with Superposition's and Aircar/Dali's for a direct comparison.
#
# Resolution: -video_mode 5 (1600x900) -- the ONLY index confirmed against the real
# in-game settings UI (docs/69). Index 6 is *believed* to be 1920x1080 by list-order alone,
# never independently confirmed -- deliberately NOT used here, to avoid silently sweeping
# at the wrong resolution the way the very first Heaven run did picking coordinates off a
# dropdown that re-anchors around the current selection.
#
# vr-power-watchdog.service is stopped for the duration (would otherwise flip the cap back
# to power.conf's GPU_LIMIT_PCT the moment it next runs) and restarted on exit, including
# Ctrl-C or a crash. Needs root for vr-power-setup.sh --gpu-limit and the watchdog
# start/stop -- run as your normal user, not via sudo directly: each call does its own
# `sudo`, and both are covered by the existing reverb-g2-power NOPASSWD sudoers grant.
#
# Requires: the standalone Proton prefix at ~/vr/proton-prefixes/unigine with Heaven 4.0
# already installed there (docs/69) -- this script does not install anything.
#
# UNLIKE q2rtx-power-sweep.sh: Heaven is launched directly via `proton run`, not through
# Steam, so game-stop.py / vr-power-watchdog.py's own process scan can't see it (it only
# matches processes Steam itself launched -- docs/69's documented gap). This script kills
# it directly by matching Heaven.exe's own commandline instead.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VR="$HOME/vr"
[ -d "$VR" ] || VR="$HOME/Documents/reverb-g2"
PREFIX="$HOME/vr/proton-prefixes/unigine"
BINDIR="$PREFIX/pfx/drive_c/Program Files (x86)/Unigine/Heaven Benchmark 4.0/bin"
RESULTS_DIR="$PREFIX/pfx/drive_c/users/steamuser"
PROTON="$HOME/.steam/steam/steamapps/common/Proton - Experimental/proton"
OUT_CSV="$VR/logs/heaven-power-sweep-$(date +%Y%m%d-%H%M%S).csv"
# Real full-flythrough duration observed live 2026-09-04: several minutes (26 scenes,
# camera-path-timed, independent of the fps it renders at) -- this must comfortably
# outlast that, not just a launch grace period like q2rtx-power-sweep.sh's 60s.
LAUNCH_TIMEOUT_S=480
VIDEO_MODE=5   # confirmed 1600x900 (docs/69) -- do not change without re-confirming the index

REPS=2
LEVELS=(100 130 160 210)

usage() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [-r REPS] [levels...]

  -r REPS   repetitions per power level. Default: 2.
  -h        this help.
  levels    GPU power limits in watts to sweep. Default: 100 130 160 210
            (the 4-mode framework's full-eco/smart-eco/max-reasonable/turbo points --
            nvidia-smi refuses anything outside the card's real floor/max, this script
            doesn't re-check it).

Output: $VR/logs/heaven-power-sweep-<timestamp>.csv, columns:
        watts,rep,fps,score,min_fps,max_fps
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

if [ "$(id -u)" = 0 ]; then
    echo "Don't run this as root (or under sudo -i/su) -- Heaven needs YOUR desktop session," >&2
    echo "not root's. Run it as your normal user; it calls sudo itself for the nvidia-smi/" >&2
    echo "systemctl calls that actually need root." >&2
    exit 1
fi

if [ ! -f "$BINDIR/Heaven.exe" ]; then
    echo "Heaven.exe not found under: $BINDIR" >&2
    echo "(expected the standalone Proton prefix from docs/69 -- not installing it here)" >&2
    exit 1
fi

WATCHDOG_WAS_ACTIVE=0
systemctl is-active --quiet vr-power-watchdog.service && WATCHDOG_WAS_ACTIVE=1

kill_heaven() {
    pkill -f 'Heaven\.exe' >/dev/null 2>&1
    sleep 1
    pkill -9 -f 'Heaven\.exe' >/dev/null 2>&1
}

restore() {
    echo
    echo "Restoring: stopping any leftover Heaven.exe, restarting the watchdog..."
    kill_heaven
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
echo "watts,rep,fps,score,min_fps,max_fps" > "$OUT_CSV"

GPU_MAX_W="$(nvidia-smi --query-gpu=power.max_limit --format=csv,noheader,nounits | cut -d. -f1)"

run_one() {
    local watts="$1" rep="$2"
    local pct target result_file line fps score min_fps max_fps waited

    # Ceiling, not floor -- q2rtx-power-sweep.sh's own floor rounding (double-truncated
    # against vr-power-setup.sh's own floor) could land a couple watts UNDER the requested
    # value, undershooting the card's min-limit floor at the boundary (2026-09-04 fix).
    pct=$(( (watts * 100 + GPU_MAX_W - 1) / GPU_MAX_W ))
    sudo "$HERE/vr-power-setup.sh" --gpu-limit "$pct" >/dev/null \
        || { echo "  --gpu-limit $pct (${watts}W) failed -- skipping"; return 1; }

    local before_files
    before_files="$(find "$RESULTS_DIR" -maxdepth 1 -iname 'Unigine_Heaven_Benchmark_*.html' 2>/dev/null)"

    (
        cd "$BINDIR" || exit 1
        STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.steam/steam" \
        STEAM_COMPAT_DATA_PATH="$PREFIX" \
        "$PROTON" run Heaven.exe \
            -project_name Heaven -data_path ../ -engine_config ../data/heaven_4.0.cfg \
            -system_script heaven/unigine.cpp -sound_app openal \
            -video_app direct3d11 -video_multisample 0 -video_fullscreen 1 \
            -video_mode "$VIDEO_MODE" \
            -extern_define ,RELEASE,LANGUAGE_EN,QUALITY_HIGH,TESSELLATION_DISABLED \
            -extern_plugin ,GPUMonitor \
            >/dev/null 2>&1 &
    )

    # Heaven's CLI launch opens the interactive free-cam viewer, NOT the timed benchmark
    # directly (found live 2026-09-04 -- docs/69 only documents the CLI args, not this) --
    # a real click on the top-left "Benchmark" button is what actually starts the timed
    # 26-scene flythrough. When it finishes, a results overlay (FPS/Score/Min/Max + a
    # Save/Close pair) appears on its own; clicking "Save" opens a native Save-As dialog
    # pre-filled with a timestamped filename that a click on its own "Ok" confirms -- THAT
    # write is what produces the html this script parses. All three click points were
    # found by screenshotting a live run (`import -window`), not guessed from the UI:
    #   (60, 17)     "Benchmark" button, top-left menu bar (1920x1080 window)
    #   (1103, 800)  "Save" on the results overlay
    #   (1097, 764)  "Ok" on the Save-As file dialog
    # Re-confirm these three if Heaven's UI ever changes -- they are pixel coordinates,
    # not resolved by name.
    local win="" w_waited=0
    while [ "$w_waited" -lt 30 ]; do
        win="$(xdotool search --name 'Heaven Benchmark' 2>/dev/null | head -1)"
        [ -n "$win" ] && break
        sleep 2; w_waited=$((w_waited + 2))
    done
    if [ -z "$win" ]; then
        echo "  ${watts}W rep ${rep}: Heaven window never appeared (30s) -- skipped"
        kill_heaven
        return 1
    fi
    sleep 6  # let the renderer/shaders settle before the first click
    xdotool windowactivate "$win" 2>/dev/null
    xdotool mousemove --window "$win" 60 17
    xdotool click --window "$win" 1

    waited=0
    result_file=""
    while [ "$waited" -lt "$LAUNCH_TIMEOUT_S" ]; do
        sleep 15; waited=$((waited + 15))
        # Harmless if the results overlay isn't up yet -- these coordinates are empty
        # flythrough-camera space during the timed run, no UI element lives there.
        # Re-activate every time (not just once before the Benchmark click): caught live
        # 2026-09-04 -- `xdotool click --window` delivers via XTest against whatever
        # window actually holds input focus, not necessarily the target window, so if
        # focus drifts away over a multi-minute wait the click silently lands nowhere and
        # the whole rep times out with zero visible error.
        xdotool windowactivate "$win" 2>/dev/null
        xdotool mousemove --window "$win" 1103 800
        xdotool click --window "$win" 1
        sleep 1
        xdotool windowactivate "$win" 2>/dev/null
        xdotool mousemove --window "$win" 1097 764
        xdotool click --window "$win" 1
        sleep 1
        local now_files new_file
        now_files="$(find "$RESULTS_DIR" -maxdepth 1 -iname 'Unigine_Heaven_Benchmark_*.html' 2>/dev/null)"
        new_file="$(comm -13 <(echo "$before_files" | sort) <(echo "$now_files" | sort) | head -1)"
        if [ -n "$new_file" ]; then
            result_file="$new_file"
            break
        fi
    done

    kill_heaven

    if [ -z "$result_file" ]; then
        echo "  ${watts}W rep ${rep}: TIMED OUT waiting for a new result file (${LAUNCH_TIMEOUT_S}s) -- skipped"
        return 1
    fi

    fps="$(grep -A0 'FPS:</td>' "$result_file" | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)"
    score="$(grep -A0 'Score:</td>' "$result_file" | grep -v 'Min\|Max' | head -1 | grep -oE '[0-9]+' | head -1)"
    min_fps="$(grep -A0 'Min FPS:</td>' "$result_file" | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)"
    max_fps="$(grep -A0 'Max FPS:</td>' "$result_file" | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)"

    if [ -z "$fps" ]; then
        echo "  ${watts}W rep ${rep}: result file found but couldn't parse FPS -- skipped ($result_file)"
        return 1
    fi
    echo "  ${watts}W rep ${rep}: fps=${fps} score=${score} min=${min_fps} max=${max_fps}"
    echo "${watts},${rep},${fps},${score},${min_fps},${max_fps}" >> "$OUT_CSV"
}

echo "=== heaven power sweep: ${LEVELS[*]} W, ${REPS} rep(s) each ==="
for watts in "${LEVELS[@]}"; do
    for rep in $(seq 1 "$REPS"); do
        run_one "$watts" "$rep"
        sleep 2
    done
done

echo
echo "=== summary (mean fps per level) ==="
awk -F, 'NR>1 && $3!="" {sum[$1]+=$3; n[$1]++} END {for (w in sum) printf "  %sW: %.2f fps (n=%d)\n", w, sum[w]/n[w], n[w]}' "$OUT_CSV" | sort -t: -k1 -n

echo
echo "Raw data: $OUT_CSV"
