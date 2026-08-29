#!/bin/bash
# soak-sequence.sh -- run several soak-variant.py legs back to back, detached from the caller.
#
# Why (2026-08-28 night): an agent drove a 15-minute soak leg from a foreground ssh session; the
# session died mid-leg (a 600 s harness cap), SIGHUP killed soak-variant.py before its teardown,
# and monado-service sat orphaned for 17 minutes holding the DRM lease until someone killed it by
# hand -- which then tripped the known teardown SIGSEGV. Legs must outlive whoever starts them.
#
# Usage (always detached):
#   cd ~/Documents/reverb-g2 && setsid nohup scripts/soak-sequence.sh MINUTES TAG[=SLAM_CONFIG.toml] ... \
#       > ~/vr/logs/soak/sequence-launch.out 2>&1 < /dev/null &
#   e.g. scripts/soak-sequence.sh 15 base-i2 P2-i2=$HOME/vr/basalt-variants/P2.toml base-i3 P2-i3=$HOME/vr/basalt-variants/P2.toml
#
# A tag without "=config" is a base leg (the global basalt-g2-config.json); a tag with one is a
# variant leg and is graded against the most recent base leg's JSON (soak-variant.py --baseline).
# Between legs: rig must be clean (no monado-service, no IPC socket) or it is forced down, then
# 60 s of USB settle. Stops on the first leg that fails or leaves no JSON. The dashboard attention
# flag is set for the whole run and cleared on any exit. Progress: ~/vr/logs/soak/sequence-<stamp>.log;
# end marker: sequence-<stamp>.done ("ok" / "failed" / "stopped" / "aborted"). To abort between
# legs: touch ~/vr/logs/soak/STOP; to abort the running leg: ~/vr/jack-in-wayland.sh down.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SOAK=$HOME/vr/logs/soak
mkdir -p "$SOAK"
RUNTIME=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
SOCKET=$RUNTIME/monado_comp_ipc
STAMP=$(date +%Y%m%d-%H%M%S)
LOG=$SOAK/sequence-$STAMP.log
DONE=$SOAK/sequence-$STAMP.done
STOP=$SOAK/STOP
DASH=http://127.0.0.1:8765

if [ $# -lt 2 ]; then
    echo "usage: $0 MINUTES TAG[=SLAM_CONFIG.toml] [TAG[=SLAM_CONFIG.toml] ...]" >&2
    exit 2
fi
MIN=$1; shift
LEGS=("$@")

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
attention() { curl -s -m 5 -X POST "$DASH/api/attention" -H 'Content-Type: application/json' -d "$1" >/dev/null 2>&1 || true; }
rig_clean() { ! pgrep -x monado-service >/dev/null && [ ! -e "$SOCKET" ]; }
force_down() {
    log "forcing the rig down (jack-in down, then kill by pid)"
    "$HOME/vr/jack-in-wayland.sh" down >/dev/null 2>&1 || true
    sleep 5
    for p in $(pgrep -x monado-service); do kill "$p" 2>/dev/null; done
    sleep 5
    for p in $(pgrep -x monado-service); do kill -9 "$p" 2>/dev/null; done
    rm -f "$SOCKET"
}

STATUS=aborted
cleanup() {
    rig_clean || force_down
    attention '{"active": false}'
    log "sequence end: $STATUS"
    echo "$STATUS $(date '+%F %T')" > "$DONE"
}
trap cleanup EXIT

TOTAL=$(( ${#LEGS[@]} * (MIN + 2) ))
UNTIL=$(date -d "+${TOTAL} min" '+%H:%M')
rm -f "$STOP"
attention "{\"active\": true, \"message\": \"Unattended at-rest soak sequence (${LEGS[*]}; ${MIN} min each, ~${TOTAL} min, until ~${UNTIL} -03) -- do not touch the headset. Abort between legs: touch $STOP; abort the running leg: ~/vr/jack-in-wayland.sh down. Log: $LOG\"}"
log "sequence start: ${#LEGS[@]} legs x ${MIN} min (${LEGS[*]}), until ~${UNTIL}"

BASELINE=""
for LEG in "${LEGS[@]}"; do
    TAG=${LEG%%=*}
    CFG=""
    [ "$LEG" != "$TAG" ] && CFG=${LEG#*=}
    if [ -e "$STOP" ]; then
        log "STOP file present, not starting $TAG"
        STATUS=stopped
        exit 0
    fi
    if ! rig_clean; then
        log "rig not clean before $TAG"
        force_down
        sleep 30
    fi
    ARGS=(--tag "$TAG" --minutes "$MIN")
    [ -n "$CFG" ] && ARGS+=(--slam-config "$CFG")
    [ -n "$CFG" ] && [ -n "$BASELINE" ] && ARGS+=(--baseline "$BASELINE")
    log "leg $TAG start: soak-variant.py ${ARGS[*]}"
    ( cd "$HERE/.." && timeout $(( (MIN + 6) * 60 )) python3 "$HERE/soak-variant.py" "${ARGS[@]}" ) > "$SOAK/$TAG-run.out" 2>&1
    RC=$?
    HAS_JSON=no
    [ -f "$SOAK/$TAG.json" ] && HAS_JSON=yes
    log "leg $TAG end: rc=$RC json=$HAS_JSON cores_today=$(coredumpctl list --since today 2>/dev/null | grep -c monado-service)"
    [ -z "$CFG" ] && [ "$HAS_JSON" = yes ] && BASELINE=$SOAK/$TAG.json
    rig_clean || { log "leg $TAG left the rig dirty"; force_down; }
    if [ "$RC" -ne 0 ] || [ "$HAS_JSON" = no ]; then
        log "leg $TAG failed, stopping the sequence"
        STATUS=failed
        exit 1
    fi
    sleep 60
done
STATUS=ok
exit 0
