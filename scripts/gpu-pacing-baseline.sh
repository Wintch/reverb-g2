#!/bin/bash
# gpu-pacing-baseline.sh -- detached, no-wearer GPU baseline for THIS rig: VR frame pacing vs
# synthetic GPU load (scripts/gpu-load-sweep.sh) at one or more GPU power caps, headset resting
# on the desk, 3dof (no SLAM, no controllers), so the only variable is the GPU. Meant to be run
# once per GPU/driver change and kept: the CSVs are what lets two cards, or two rigs, be
# compared honestly instead of by feel.
#
# Structural mirror of light-preflight.sh / soak-sequence.sh: rig_clean/force_down helpers, an
# unconditional EXIT trap (the rig never stays up, the power watchdog always comes back), and the
# setsid-nohup-only contract -- a foreground ssh session dying mid-run must not orphan monado.
#
# Usage (always detached, never foreground):
#   cd ~/Documents/reverb-g2 && setsid nohup scripts/gpu-pacing-baseline.sh [-w WINDOWS] [-d SECONDS] \
#       [-l "LEVELS"] [CAP_PCT...] > ~/vr/logs/pacing-baseline/launch.out 2>&1 < /dev/null &
#
#   -w WINDOWS   windows per load level (default 3 -- the project's discipline; 1 = smoke run)
#   -d SECONDS   seconds per window (default 120)
#   -l "LEVELS"  HELLO_XR_GPU_LOAD levels, quoted (default "0 25 50 75 100")
#   CAP_PCT...   GPU power caps as % of the card's max limit, one sweep each (default: 100 70).
#                Needs the sudoers grants from docs/68 (vr-power-setup.sh, watchdog stop/start);
#                with no grant the caps are skipped and one sweep runs at whatever cap is live.
#
# Output: ~/vr/logs/pacing-baseline/<stamp>/ with meta.txt (GPU, driver, limits, kernel),
#   sweep-cap<PCT>.csv (copied from gpu-load-sweep.sh's own output), power-cap<PCT>.txt
#   (nvidia-smi -q -d POWER as applied), run.log, and <stamp>.done ("ok"/"failed").
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/.." && pwd)
WINDOWS=3; DURATION=120; LEVELS="0 25 50 75 100"
while getopts "w:d:l:h" opt; do
    case "$opt" in
        w) WINDOWS="$OPTARG" ;;
        d) DURATION="$OPTARG" ;;
        l) LEVELS="$OPTARG" ;;
        h) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) exit 2 ;;
    esac
done
shift $((OPTIND - 1))
CAPS=("$@"); [ ${#CAPS[@]} -gt 0 ] || CAPS=(100 70)

VR=$HOME/vr
BASE=$VR/logs/pacing-baseline
STAMP=$(date +%Y%m%d-%H%M%S)
RUN=$BASE/$STAMP
mkdir -p "$RUN"
LOG=$RUN/run.log
DONE=$BASE/$STAMP.done
RUNTIME=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
SOCKET=$RUNTIME/monado_comp_ipc
DASH=http://127.0.0.1:8765
JACKIN=$VR/jack-in-wayland.sh
[ -x "$JACKIN" ] || JACKIN=$HERE/jack-in-wayland.sh
SWEEP=$HERE/gpu-load-sweep.sh
POWER=$HERE/vr-power-setup.sh

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
attention() { curl -s -m 5 -X POST "$DASH/api/attention" -H 'Content-Type: application/json' -d "$1" >/dev/null 2>&1 || true; }
rig_clean() { ! pgrep -x monado-service >/dev/null && [ ! -e "$SOCKET" ]; }
force_down() {
    log "forcing the rig down (jack-in down, then kill by pid)"
    "$JACKIN" down >/dev/null 2>&1 || true
    sleep 5
    for p in $(pgrep -x monado-service); do kill "$p" 2>/dev/null; done
    sleep 5
    for p in $(pgrep -x monado-service); do kill -9 "$p" 2>/dev/null; done
    rm -f "$SOCKET"
}
have_sudo() { sudo -n true 2>/dev/null && sudo -n -l "$POWER" >/dev/null 2>&1; }

STATUS=failed
WATCHDOG_STOPPED=0
cleanup() {
    pkill -x hello_xr 2>/dev/null
    rig_clean || force_down
    if [ "$WATCHDOG_STOPPED" = 1 ]; then
        sudo -n systemctl start vr-power-watchdog.service 2>/dev/null && log "power watchdog restarted" || log "WARNING: could not restart vr-power-watchdog.service"
    fi
    attention '{"active": false}'
    log "pacing baseline end: status=$STATUS  results: $RUN"
    echo "$STATUS $(date '+%F %T')" > "$DONE"
}
trap cleanup EXIT

ST=$(python3 "$HERE/game-stop.py" status 2>/dev/null)
if [ -n "$ST" ] && [ "$ST" != "no Proton game trees running" ]; then
    log "refusing: a game is running -- $ST"; exit 1
fi
[ -x "$SWEEP" ] || { log "missing $SWEEP"; exit 1; }
rig_clean || { log "rig not clean at start"; force_down; sleep 5; }

{
    echo "date: $(date -Is)"; echo "host: $(hostname)"; echo "kernel: $(uname -r)"
    echo "cpu: $(lscpu | awk -F: '/Model name/ {gsub(/^ +/, "", $2); print $2; exit}') x$(nproc)"
    echo "gpu: $(nvidia-smi --query-gpu=name,pci.device_id,driver_version,memory.total --format=csv,noheader)"
    echo "power limits (W, default/min/max): $(nvidia-smi --query-gpu=power.default_limit,power.min_limit,power.max_limit --format=csv,noheader,nounits)"
    echo "windows: $WINDOWS  duration: ${DURATION}s  levels: $LEVELS  caps: ${CAPS[*]}"
    echo "monado: $(git -C "$VR/monado" log -1 --format=%h 2>/dev/null)  repo: $(git -C "$REPO" log -1 --format=%h 2>/dev/null)"
} > "$RUN/meta.txt"
log "pacing baseline start: $(sed -n 's/^gpu: //p' "$RUN/meta.txt")"
attention "{\"active\": true, \"message\": \"GPU pacing baseline running (~$(( ${#CAPS[@]} * $(echo $LEVELS | wc -w) * WINDOWS * (DURATION + 15) / 60 )) min, headset on the desk, nobody wearing it) -- do not touch the headset. Log: $LOG\"}"

# Live-discover the Wayland/X env (per-session, never hardcoded -- see gui_env.py).
ENVLINES=$(python3 - "$HERE" <<'PY'
import sys, importlib.util
spec = importlib.util.spec_from_file_location("gui_env", sys.argv[1] + "/gui_env.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
e = m.get()
for k in ("XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"):
    print(f"{k}={e[k]}")
PY
)
[ -z "$ENVLINES" ] && { log "could not read the GUI env (gui_env.py), aborting"; exit 1; }
while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$ENVLINES"
export VR_PACING=1 VR_VERBOSE=0 XRT_COMPOSITOR_LOG=warn

SUDO_OK=0
if have_sudo; then
    SUDO_OK=1
    sudo -n systemctl stop vr-power-watchdog.service 2>/dev/null && WATCHDOG_STOPPED=1 && log "power watchdog stopped for the run"
else
    log "no sudo grant for $POWER -- caps will not be changed, one sweep at the live cap"
    CAPS=(live)
fi

log "jack-in-wayland.sh up 1 3dof (VR_PACING=1)"
"$JACKIN" up 1 3dof >>"$LOG" 2>&1
if [ $? -ne 0 ] || [ ! -e "$SOCKET" ]; then
    log "jack-in-wayland.sh did not leave the socket ready"; exit 1
fi
log "monado-service pid $(pgrep -x monado-service | head -1)"
sleep 10

ALL_OK=1
for cap in "${CAPS[@]}"; do
    if [ "$cap" != live ]; then
        if sudo -n "$POWER" --gpu-limit "$cap" >>"$LOG" 2>&1; then
            log "gpu cap -> ${cap}% : $(nvidia-smi --query-gpu=power.limit --format=csv,noheader)"
        else
            log "could not set cap ${cap}% -- skipping this leg"; ALL_OK=0; continue
        fi
        sleep 3
    fi
    nvidia-smi -q -d POWER > "$RUN/power-cap$cap.txt" 2>&1
    MARK=$RUN/.mark-$cap; touch "$MARK"; sleep 1
    log "sweep cap=$cap: levels [$LEVELS], $WINDOWS x ${DURATION}s"
    # shellcheck disable=SC2086
    "$SWEEP" -w "$WINDOWS" -d "$DURATION" $LEVELS >>"$LOG" 2>&1 || { log "sweep at cap $cap exited non-zero"; ALL_OK=0; }
    CSV=$(find "$VR/logs" -maxdepth 1 -name 'gpu-load-sweep-*.csv' -newer "$MARK" | sort | tail -1)
    if [ -n "$CSV" ]; then
        cp -f "$CSV" "$RUN/sweep-cap$cap.csv"; log "sweep cap=$cap -> $RUN/sweep-cap$cap.csv"
        sed 's/^/    /' "$RUN/sweep-cap$cap.csv" | tee -a "$LOG"
    else
        log "sweep cap=$cap produced no CSV"; ALL_OK=0
    fi
done

"$JACKIN" down >>"$LOG" 2>&1
[ "$ALL_OK" = 1 ] && STATUS=ok
exit 0
