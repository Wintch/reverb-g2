#!/bin/bash
# triage-sweep.sh - launch a list of Steam titles one by one and record how far each gets.
#
#   ./triage-sweep.sh 701100 722590 ...     sweep the given AppIDs
#
# THIS IS TRIAGE, NOT VERIFICATION, and the distinction is a project rule (CLAUDE.md):
# a title is not "working" until a human has seen it inside the headset. What this gives
# you is which titles are worth putting the headset on for, and which fail on their own
# before anyone needs to look. An automated sweep that closes each title on a timer was
# explicitly called out as useless for verification (docs/pruebas.jsonl T073) -- so every
# row it writes says TRIAGE.
#
# For each title it records the furthest stage reached:
#   no-process     the executable never started (install/Proton problem)
#   died           started and exited on its own within the window
#   no-runtime     ran, but never opened an xrizer log -> never reached OpenVR
#   connected      xrizer initialised and Monado saw a new client
#   session        an XR session actually reached FOCUSED
#
# Requires the stack already up (./jack-in-wayland.sh) -- it checks.

set -u

[ $# -ge 1 ] || { echo "usage: $0 <appid> [appid...]" >&2; exit 1; }

VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$HOME/vr" ] && VR="$HOME/vr"
LOG="$VR/jack-in-wayland.log"
XRIZER_LOG="$HOME/.local/state/xrizer/xrizer.txt"
STEAM="$HOME/.steam/debian-installation"
OUT="$VR/logs/triage-$(date +%Y%m%d-%H%M%S).tsv"
mkdir -p "$(dirname "$OUT")"

pgrep -f "targets/service/monado-service" >/dev/null || {
    echo "monado-service is not running -- start the stack first." >&2; exit 1; }

WAIT_START="${TRIAGE_WAIT_START:-75}"   # seconds to wait for the executable to appear
WATCH="${TRIAGE_WATCH:-25}"             # seconds to observe it once running

name_of() {
    local m="$STEAM/steamapps/appmanifest_$1.acf"
    [ -r "$m" ] && sed -n 's/.*"name"[[:space:]]*"\(.*\)"/\1/p' "$m" | head -1 || echo "?"
}

# Kill anything that looks like a running Proton/native game, but never Steam itself.
kill_game() {
    local pids
    pids="$(ps -eo pid,args --no-headers \
            | grep -iE "\.exe|steamapps/common" \
            | grep -viE "grep|steamwebhelper|steam\.exe|reaper|entry-point|pressure-vessel|iscriptevaluator|/proton |xalia" \
            | awk '{print $1}')"
    [ -n "$pids" ] && kill $pids 2>/dev/null
    sleep 4
}

printf "appid\tname\tstage\tdetail\n" > "$OUT"
echo "Triage sweep -> $OUT"
echo

for APPID in "$@"; do
    NAME="$(name_of "$APPID")"
    printf "%-9s %s\n" "$APPID" "$NAME"

    kill_game
    rm -f "$XRIZER_LOG"
    CONN_BEFORE="$(grep -c client_connected "$LOG" 2>/dev/null || echo 0)"

    steam -applaunch "$APPID" >/dev/null 2>&1 &

    # Wait for any game-looking process to appear.
    RUNNING=0
    for _ in $(seq 1 $((WAIT_START / 3))); do
        if ps -eo args --no-headers | grep -iE "steamapps/common" \
           | grep -qviE "grep|steamwebhelper|reaper|entry-point|pressure-vessel|iscriptevaluator|/proton |xalia"; then
            RUNNING=1; break
        fi
        sleep 3
    done

    if [ "$RUNNING" = 0 ]; then
        printf "%s\t%s\t%s\t%s\n" "$APPID" "$NAME" "no-process" "never started within ${WAIT_START}s" >> "$OUT"
        echo "   -> no-process"
        continue
    fi

    sleep "$WATCH"

    ALIVE=0
    ps -eo args --no-headers | grep -iE "steamapps/common" \
      | grep -qviE "grep|steamwebhelper|reaper|entry-point|pressure-vessel|iscriptevaluator|/proton |xalia" && ALIVE=1

    CONN_AFTER="$(grep -c client_connected "$LOG" 2>/dev/null || echo 0)"
    NEWCONN=$((CONN_AFTER - CONN_BEFORE))
    XR=0; [ -s "$XRIZER_LOG" ] && XR=1
    FOCUSED=0
    [ "$XR" = 1 ] && grep -q "FOCUSED" "$XRIZER_LOG" 2>/dev/null && FOCUSED=1

    if [ "$FOCUSED" = 1 ]; then
        STAGE="session";  DETAIL="reached FOCUSED -- worth putting the headset on"
    elif [ "$NEWCONN" -gt 0 ] || [ "$XR" = 1 ]; then
        STAGE="connected"; DETAIL="xrizer log=$XR, new monado clients=$NEWCONN"
    elif [ "$ALIVE" = 1 ]; then
        STAGE="no-runtime"; DETAIL="process alive but never opened an xrizer log"
    else
        STAGE="died"; DETAIL="exited on its own within ${WATCH}s"
    fi

    # Capture the last interesting line from whichever log the title writes.
    ERR="$(grep -hiE "exception|error|unable|not found" "$XRIZER_LOG" 2>/dev/null | tail -1)"
    [ -n "$ERR" ] || ERR="$(find "$HOME/.config/unity3d" -name Player.log -newermt "-2 minutes" 2>/dev/null \
                            | head -1 | xargs -r grep -hiE "exception|unable to" 2>/dev/null | tail -1)"
    [ -n "$ERR" ] && DETAIL="$DETAIL | $ERR"

    printf "%s\t%s\t%s\t%s\n" "$APPID" "$NAME" "$STAGE" "$DETAIL" >> "$OUT"
    echo "   -> $STAGE"
done

kill_game
echo
echo "Done. Results (TRIAGE ONLY -- nothing here is verified until a human looks):"
column -t -s$'\t' "$OUT" 2>/dev/null || cat "$OUT"
