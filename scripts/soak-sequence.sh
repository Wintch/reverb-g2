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
# variant leg and is graded against the most recent base leg's JSON (soak-variant.py --baseline);
# SOAK_BASELINE=<json> seeds that baseline for a run that starts with a variant leg.
# Between legs: rig must be clean (no monado-service, no IPC socket) or it is forced down, then
# 60 s of USB settle. Stops on the first leg that leaves no JSON, whose JSON says monado-service
# died / a coredump appeared / teardown was not clean. soak-variant.py's own exit code is NOT
# fatal: its absolute "0 divergence trips at rest" rule fails every base leg (soak-grade.py grades
# everything relative to base instead), which is exactly what stopped the 2026-08-29 00:01 run
# after its first leg. The dashboard attention
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

BASELINE=${SOAK_BASELINE:-}
[ -n "$BASELINE" ] && log "baseline seeded: $BASELINE"
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
    FATAL=""
    if [ "$HAS_JSON" = no ]; then
        FATAL="no JSON"
    else
        FATAL=$(python3 - "$SOAK/$TAG.json" <<'PY'
import json, sys
j = json.load(open(sys.argv[1]))
bad = []
if j.get("error"): bad.append("error: " + str(j["error"]))
if j.get("monado_alive_at_end") is False: bad.append("monado-service died")
if (j.get("coredumps_new") or 0) > 0: bad.append("%d new coredump(s)" % j["coredumps_new"])
if j.get("teardown_clean") is False: bad.append("teardown not clean")
print("; ".join(bad))
PY
)
    fi
    VERDICT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("verdict","?"))' "$SOAK/$TAG.json" 2>/dev/null || echo "?")
    log "leg $TAG end: rc=$RC json=$HAS_JSON verdict=\"$VERDICT\" fatal=\"${FATAL:-none}\""
    [ -z "$CFG" ] && [ "$HAS_JSON" = yes ] && BASELINE=$SOAK/$TAG.json
    rig_clean || { log "leg $TAG left the rig dirty"; force_down; }
    if [ -n "$FATAL" ]; then
        log "leg $TAG fatal ($FATAL), stopping the sequence"
        STATUS=failed
        exit 1
    fi
    sleep 60
done
STATUS=ok
exit 0
