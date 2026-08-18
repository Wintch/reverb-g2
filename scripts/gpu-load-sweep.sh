#!/bin/bash
# gpu-load-sweep.sh - sweep synthetic GPU load against real VR frame pacing, no game needed.
#
#   ./gpu-load-sweep.sh                        smoke: levels 0 25 50 75 100, 1 window, 120s each
#   ./gpu-load-sweep.sh -w 3                    real run: 3 windows per level (project discipline)
#   ./gpu-load-sweep.sh -d 60 -w 3 0 50 100     custom duration/windows/levels
#   ./gpu-load-sweep.sh -h                      full usage
#
# WHY THIS EXISTS (NEXT-STEP.md's tooling queue, item (a), 2026-08-18): pacing has been
# measured CPU-bound at every GPU power cap tried so far (T204/T209: 147W==210W==105W for
# Aircar's late-frame rate) -- but that was always confounded by a real title's own CPU cost
# riding along with the GPU load. This sweeps GPU load ALONE, driven by hello_xr's
# HELLO_XR_GPU_LOAD=<0-100> fragment-shader busy-loop (src/tests/hello_xr/vulkan_shaders/
# frag.glsl's GpuLoadPerturb, ~/vr/OpenXR-SDK-Source), with no SLAM, no constellation, no
# Proton/DXVK -- so a pacing change across levels can only be the GPU, answering "how low can
# the power cap go" without a title's CPU cost muddying the answer.
#
# ASSUMES A MONADO SESSION IS ALREADY UP (this script never calls jack-in-wayland.sh -- the
# headset session belongs to whoever started it). It only launches/kills hello_xr, once per
# (level, window) pair.
#
# GPU watts+clocks: nvidia-smi power.draw + clocks.sm, sampled on an interval while hello_xr
# runs -- same instrument as scripts/power-log.sh (T209), just inlined here so sampling starts
# and stops exactly bracketing each window instead of running for an unrelated span.
#
# Pacing: reuses scripts/frame-pacing.sh's own instrument and log format (T161/T175, hardened
# through T178) rather than reinventing it -- monado-service logs "Frame late by N.NNms" lines
# to $VR_BASE/jack-in-wayland.log whenever XRT_APP_FRAME_LAG_LOG_AS_LEVEL is set in its
# environment (jack-in-wayland.sh's VR_PACING=1, the 'dev'/'quiet' launch actions). This script
# diffs that log's line count before/after each window -- it does NOT start hello_xr with any
# special pacing flag; the instrumentation lives in the already-running monado-service, so it
# has to already be on when the session was launched, or every row here reads a false 0%.
#
# STDIN TRAP (CLAUDE.md "Concrete traps"): hello_xr reads transport keys from stdin and treats
# EOF as "end of timed run" -- launched with stdin closed it exits in under a second, exit 0,
# no error, and monado's log looks like a normal client_connected/client_disconnected cycle
# with no BEGIN_SESSION, easily mistaken for a compositor failure. The historically-documented
# fix was a literal `sleep N | hello_xr` pipe -- play360.sh (2026-08-09) found that version has
# its OWN bug: a real pipe makes the shell wait for BOTH sides, so the caller blocks for the
# full N seconds even after hello_xr has already exited on its own (a quit gesture, a crash).
# This script uses play360.sh's fixed idiom instead: `timeout` bounds hello_xr directly, and
# stdin is fed from a `sleep infinity` via PROCESS SUBSTITUTION (not a pipe), so this script's
# own wait is only ever on hello_xr's actual process.
#
# DEFAULT CONTENT TRAP (CLAUDE.md again): hello_xr's default HELLO_XR_PHOTO360 points at a
# path that only exists on the main system; missing it THROWS inside LoadPhotoTexture and the
# session shows BEGIN_SESSION with no error but a black panel forever after. This script always
# passes an explicit HELLO_XR_PHOTO360 (default: $VR_BASE/media/test-equirect.jpg, confirmed
# present in the lab tree) so every window has real, guaranteed-loadable content for
# GpuLoadPerturb to add its busy-work on top of -- the sweep is measuring the SHADER load knob,
# not testing content loading.

set -u

usage() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [-d SECONDS] [-w WINDOWS] [-i SECONDS] [levels...]

  -d SECONDS   duration of hello_xr per window. Default: 120.
  -w WINDOWS   windows measured per level, averaged into that level's CSV row. Default: 1
               (smoke sweep). Use 3 for a real run -- the project's benchmark discipline
               (T204/T209/etc: three windows per condition, not one).
  -i SECONDS   nvidia-smi sampling interval during each window. Default: 2.
  -h           this help.

  levels       HELLO_XR_GPU_LOAD values to sweep, 0-100 each. Default: 0 25 50 75 100.

Output: one CSV row per level at \$VR_BASE/logs/gpu-load-sweep-<timestamp>.csv, columns
        load_pct,gpu_watts_avg,gpu_clock_avg,pacing_late_pct,frames

Requires: a Monado session already up (this script never starts one -- see jack-in-wayland.sh),
          launched with pacing logging on (VR_PACING=1 / action 'dev' or 'quiet'), and
          ~/vr/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr built with HELLO_XR_GPU_LOAD
          support (2026-08-18 patch to frag.glsl / graphicsplugin_vulkan.cpp).
EOF
}

DURATION=120
WINDOWS=1
GPU_INTERVAL=2
LEVELS=()

while getopts "d:w:i:h" opt; do
    case "$opt" in
        d) DURATION="$OPTARG" ;;
        w) WINDOWS="$OPTARG" ;;
        i) GPU_INTERVAL="$OPTARG" ;;
        h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
for arg in "$@"; do LEVELS+=("$arg"); done
[ "${#LEVELS[@]}" -gt 0 ] || LEVELS=(0 25 50 75 100)

for n in "$DURATION" "$WINDOWS" "$GPU_INTERVAL"; do
    case "$n" in
        ''|*[!0-9]*) echo "duration/windows/interval must be positive integers, got '$n'" >&2; exit 2 ;;
    esac
done
for lvl in "${LEVELS[@]}"; do
    case "$lvl" in
        ''|*[!0-9]*) echo "level '$lvl' is not an integer 0-100" >&2; exit 2 ;;
    esac
    [ "$lvl" -ge 0 ] && [ "$lvl" -le 100 ] || { echo "level '$lvl' out of range 0-100" >&2; exit 2; }
done

# Same VR_BASE auto-detection as play360.sh/jack-in.sh: ~/Documents/linux_vr_base on the main
# system, ~/vr in the lab. VR_BASE= in the environment overrides both.
if [ -n "${VR_BASE:-}" ]; then
    :
elif [ -d "$HOME/Documents/linux_vr_base/monado/build" ]; then
    VR_BASE="$HOME/Documents/linux_vr_base"
else
    VR_BASE="$HOME/vr"
fi
MONADO_BUILD="$VR_BASE/monado/build"
HELLO_XR="$VR_BASE/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr"
LOG="$VR_BASE/jack-in-wayland.log"
PHOTO="${HELLO_XR_PHOTO360:-$VR_BASE/media/test-equirect.jpg}"

[ -x "$HELLO_XR" ] || { echo "hello_xr needs to be built ($HELLO_XR)" >&2; exit 1; }
[ -r "$PHOTO" ] || { echo "no content at HELLO_XR_PHOTO360 candidate: $PHOTO" >&2; exit 1; }

# pgrep -x (exact comm match), not -f: docs/43's lesson, -f matches any bystander whose
# cmdline merely mentions the binary path (a shell, a tail, this very script's own args if it
# ever echoed the path). See jack-in-wayland.sh's 'down' action for the precedent.
MPID="$(pgrep -x monado-service | head -1)"
if [ -z "$MPID" ]; then
    echo "monado-service is not running. This script does not start a session -- bring the" >&2
    echo "stack up first (./jack-in-wayland.sh dev 1 3dof, or whatever mode you need)." >&2
    exit 1
fi
[ -r "$LOG" ] || { echo "No log at $LOG -- has the stack ever been started via jack-in-wayland.sh?" >&2; exit 1; }

# Verify the pacing instrumentation is actually on in the RUNNING process, exactly like
# frame-pacing.sh does -- a session launched with the default 'up' action runs VR_PACING=0,
# and a silently-zero "0.00% late" row for every level would be worse than no row at all.
if ! tr '\0' '\n' < "/proc/$MPID/environ" 2>/dev/null | grep -q "^XRT_APP_FRAME_LAG_LOG_AS_LEVEL="; then
    echo "WARNING: frame-lag logging is NOT enabled in the running monado-service." >&2
    echo "         Restart the stack with action 'dev' or 'quiet' (VR_PACING=1) and re-run." >&2
    exit 2
fi

HZ="$(grep -oE "found display mode [0-9]+x[0-9]+@[0-9.]+" "$LOG" | tail -1 | sed -E 's/.*@//')"
[ -n "$HZ" ] || HZ=90

TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$VR_BASE/logs"
OUT="$VR_BASE/logs/gpu-load-sweep-$TS.csv"
HELLOLOGDIR="$VR_BASE/logs/gpu-load-sweep-$TS-hello_xr"
mkdir -p "$HELLOLOGDIR"
echo "load_pct,gpu_watts_avg,gpu_clock_avg,pacing_late_pct,frames" > "$OUT"

echo "VR_BASE=$VR_BASE  HZ=$HZ  duration=${DURATION}s  windows=$WINDOWS  gpu-interval=${GPU_INTERVAL}s"
echo "levels: ${LEVELS[*]}"
echo "-> $OUT"
echo

count_late() {
    # Same fragile-history lesson as frame-pacing.sh (T178): grep -c prints "0" AND exits
    # non-zero on no match, so a bare `|| echo 0` doubles up into "0\n0" and breaks the
    # arithmetic below. Guard the same way.
    local n
    n="$(grep -c "Frame late by" "$LOG" 2>/dev/null || true)"
    n="${n%%$'\n'*}"
    echo "${n:-0}"
}

RUNTIME_ENV=(
    XR_RUNTIME_JSON="$MONADO_BUILD/openxr_monado-dev.json"
    IPC_IGNORE_VERSION=1
    HELLO_XR_PHOTO360="$PHOTO"
)

SAMPLE_PID=""
STDIN_KEEPALIVE_PID=""
cleanup() {
    [ -n "$SAMPLE_PID" ] && kill "$SAMPLE_PID" 2>/dev/null
    [ -n "$STDIN_KEEPALIVE_PID" ] && kill "$STDIN_KEEPALIVE_PID" 2>/dev/null
}
trap cleanup INT TERM EXIT

# Samples "watts, clock_mhz" once per $GPU_INTERVAL into $1 until sample_gpu_stop kills it --
# same nvidia-smi query as power-log.sh (power.draw), plus clocks.sm alongside it in one call
# so both columns come from the same sample instant.
sample_gpu_start() {
    local out="$1"
    : > "$out"
    ( while :; do
        nvidia-smi --query-gpu=power.draw,clocks.sm --format=csv,noheader,nounits 2>/dev/null >> "$out"
        sleep "$GPU_INTERVAL"
      done ) &
    SAMPLE_PID=$!
}
sample_gpu_stop() {
    [ -n "$SAMPLE_PID" ] && kill "$SAMPLE_PID" 2>/dev/null
    wait "$SAMPLE_PID" 2>/dev/null
    SAMPLE_PID=""
}

# One hello_xr run, bounded to $DURATION seconds, at the given HELLO_XR_GPU_LOAD level. See
# the STDIN TRAP note at the top of this file for why this is process substitution + timeout,
# not a literal `sleep N | hello_xr` pipe.
run_hello_xr() {
    local level="$1" logfile="$2"
    exec 3< <(exec sleep infinity)
    STDIN_KEEPALIVE_PID=$!
    timeout "$DURATION" env "${RUNTIME_ENV[@]}" HELLO_XR_GPU_LOAD="$level" \
        stdbuf -oL -eL "$HELLO_XR" --graphics Vulkan2 0<&3 >"$logfile" 2>&1
    local rc=$?
    exec 3<&-
    [ -n "$STDIN_KEEPALIVE_PID" ] && kill "$STDIN_KEEPALIVE_PID" 2>/dev/null
    STDIN_KEEPALIVE_PID=""
    return "$rc"
}

for level in "${LEVELS[@]}"; do
    win_watts=() win_clock=() win_pct=()
    for w in $(seq 1 "$WINDOWS"); do
        echo "== load=${level}%  window ${w}/${WINDOWS} (${DURATION}s) =="
        BEFORE="$(count_late)"

        SAMPLES="$(mktemp)"
        sample_gpu_start "$SAMPLES"

        HELLOLOG="$HELLOLOGDIR/load${level}-w${w}.log"
        run_hello_xr "$level" "$HELLOLOG"
        RC=$?

        sample_gpu_stop
        AFTER="$(count_late)"

        # timeout's own exit code for "ran the full duration and was killed on schedule" is
        # 124 -- the expected, successful case here (rc 0 would mean hello_xr quit on its own
        # early, e.g. a crash or the stdin-EOF trap misfiring).
        if [ "$RC" -ne 124 ] && [ "$RC" -ne 0 ]; then
            echo "  WARNING: hello_xr exited rc=$RC (expected 124/timeout) -- see $HELLOLOG" >&2
        elif [ "$RC" -eq 0 ]; then
            echo "  WARNING: hello_xr exited on its own before ${DURATION}s -- see $HELLOLOG" >&2
        fi

        LATE=$((AFTER - BEFORE))
        EXPECTED_WIN="$(awk -v d="$DURATION" -v hz="$HZ" 'BEGIN{printf "%d", d*hz}')"
        PCT="$(awk -v l="$LATE" -v e="$EXPECTED_WIN" 'BEGIN{printf "%.3f", (e>0)?(l/e*100):0}')"

        read -r WATTS CLOCK < <(awk -F, '{s1+=$1; s2+=$2; n++} END{if(n>0) printf "%.2f %.2f", s1/n, s2/n; else printf "0 0"}' "$SAMPLES")
        SAMPLE_COUNT="$(wc -l < "$SAMPLES" | tr -d ' ')"
        rm -f "$SAMPLES"
        [ "$SAMPLE_COUNT" -gt 0 ] || echo "  WARNING: zero GPU samples this window (duration < interval?)" >&2

        echo "  late=${LATE}/${EXPECTED_WIN} (${PCT}%)  gpu=${WATTS}W  clk=${CLOCK}MHz  (${SAMPLE_COUNT} samples)"
        win_watts+=("$WATTS")
        win_clock+=("$CLOCK")
        win_pct+=("$PCT")
    done

    # One CSV row per level: mean of each window's mean (exact vs. the grand mean only when
    # every window collected the same sample count, which they do here -- fixed duration and
    # interval per run -- close enough otherwise, this is a rough sweep tool, not a stats lab).
    AVG_WATTS="$(printf '%s\n' "${win_watts[@]}" | awk '{s+=$1; n++} END{printf "%.2f", (n>0)?s/n:0}')"
    AVG_CLOCK="$(printf '%s\n' "${win_clock[@]}" | awk '{s+=$1; n++} END{printf "%.2f", (n>0)?s/n:0}')"
    AVG_PCT="$(printf '%s\n' "${win_pct[@]}" | awk '{s+=$1; n++} END{printf "%.3f", (n>0)?s/n:0}')"
    TOTAL_FRAMES="$(awk -v d="$DURATION" -v w="$WINDOWS" -v hz="$HZ" 'BEGIN{printf "%d", d*w*hz}')"

    echo "${level},${AVG_WATTS},${AVG_CLOCK},${AVG_PCT},${TOTAL_FRAMES}" >> "$OUT"
    echo "  -> level ${level}% done: avg ${AVG_WATTS}W / ${AVG_CLOCK}MHz / ${AVG_PCT}% late over ${WINDOWS} window(s)"
    echo
done

echo "Sweep complete -> $OUT"
cat "$OUT"
