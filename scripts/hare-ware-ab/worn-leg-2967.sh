#!/bin/bash
# worn-leg-2967.sh -- worn-leg.sh with monado-2967-v2 allowed (pre-push session test of !2967); original: one WORN leg of the hare_ware clock A/B: ab-run.sh (service, debug env, teardown)
# plus a hello_xr client with its 1 Hz pose log, so the wearer sees the controller gizmos (drawn only
# while POSITION_TRACKED) and the run leaves app-side tracked/untracked counts next to the service log.
#
#   setsid nohup bash worn-leg.sh <label> <worktree> <leg-number> [client_s] \
#       > ~/vr/logs/worn-launch-<label>.out 2>&1 < /dev/null &
#
#   <worktree>    monado-hw (clock fix) or monado-hw-nofix, under ~/vr
#   <leg-number>  what the speaker announces ("tramo 2"), so the wearer does not learn the arm
#   client_s      hello_xr run time, default 120; ab-run.sh gets client_s + 25
#
# End marker: ~/vr/logs/worn-<label>.done (first line status=...). Controllers on the host UB500
# (AB_TRANSPORT=bt) -- the setup of docs/136/143. Never sudoes, never pkill -f; ab-run.sh owns the
# service teardown. See docs/143 and docs/135 for why this leg exists.
set -u

LABEL=${1:?label}; WT=${2:?worktree}; LEGNO=${3:?leg number}; CLIENT_S=${4:-120}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VR=$HOME/vr; LOGS=$VR/logs
SVC=$VR/$WT/build/src/xrt/targets/service/monado-service
JSON=$VR/$WT/build/openxr_monado-dev.json
HELLO=$VR/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr
DONE=$LOGS/worn-$LABEL.done
# hello_xr throws at startup without a readable 360 image; a grid also gives the wearer a fixed reference.
PHOTO=${WORN_PHOTO360:-$HOME/Documents/linux_vr_base/photo360/testgrid.png}

say() { XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "$1" >/dev/null 2>&1 || true; }
finish() { echo "$1" > "$DONE.tmp"; shift; for l in "$@"; do echo "$l" >> "$DONE.tmp"; done; mv "$DONE.tmp" "$DONE"; }

rm -f "$DONE" "$DONE.tmp"
case "$WT" in monado-hw|monado-hw-nofix|monado-2967-v2) ;; *) finish "status=refused reason=worktree must be monado-hw, monado-hw-nofix or monado-2967-v2"; exit 2;; esac
for f in "$SVC" "$HELLO"; do [ -x "$f" ] || { finish "status=refused reason=missing $f"; exit 2; }; done
[ -r "$PHOTO" ] || { finish "status=refused reason=missing $PHOTO"; exit 2; }
[ -f "$JSON" ] || { finish "status=refused reason=missing $JSON"; exit 2; }

AB_TRANSPORT=bt VR_BT_CTRL_CHECK=1 AB_NUDGE_AT=0 AB_RECORD=1 AB_SETTLE=0 AB_FORCE=1 \
    bash "$HERE/ab-run.sh" "$LABEL" "$SVC" $((CLIENT_S + 25)) > "$LOGS/worn-ab-$LABEL.out" 2>&1 < /dev/null &
ABPID=$!

# Wait for this leg's launcher to report the socket (or for ab-run.sh to give up).
LL=""
for _ in $(seq 1 360); do
    LL=$(ls -t "$LOGS"/ab-"$LABEL"-*.launcher.log 2>/dev/null | head -1)
    [ -n "$LL" ] && grep -q "Socket ready" "$LL" && break
    kill -0 "$ABPID" 2>/dev/null || break
    sleep 0.5
done
if [ -z "$LL" ] || ! grep -q "Socket ready" "$LL"; then
    wait "$ABPID"
    AB=$(head -1 "$(ls -t "$LOGS"/ab-"$LABEL"-*.done 2>/dev/null | head -1)" 2>/dev/null)
    say "El tramo $LEGNO no arrancó. Esperá, por favor."
    finish "status=failed reason=service never became ready" "ab: $AB"
    exit 1
fi
BASE=${LL%.launcher.log}

sleep 2
say "${WORN_CUE_START:-Jack in. Tramo $LEGNO.}"
# hello_xr quits on stdin EOF: give it a stdin that never ends (same trick as gpu-load-sweep.sh).
exec 3< <(exec sleep infinity)
XR_RUNTIME_JSON="$JSON" IPC_IGNORE_VERSION=1 HELLO_XR_POSE_LOG=1 HELLO_XR_PHOTO360="$PHOTO" HELLO_XR_DURATION_S="$CLIENT_S" \
    stdbuf -oL -eL "$HELLO" --graphics Vulkan2 0<&3 > "$BASE.hello.log" 2>&1
HRC=$?
exec 3<&-
say "${WORN_CUE_END:-Fin del tramo $LEGNO. Dejá los joysticks quietos.}"

wait "$ABPID"
AB=$(head -1 "$BASE.done" 2>/dev/null)

# App-side tally from the 1 Hz POSE lines (worn-tally.py): tracked / frozen-while-tracked / outlier seconds.
TALLY=$(python3 -I "$HERE/worn-tally.py" "$BASE.hello.log" 2>&1)
FP=$(grep -c "Found pose" "$BASE.log" 2>/dev/null)
finish "status=done hello_rc=$HRC $TALLY service_found_pose=$FP" \
    "label=$LABEL worktree=$WT git=$(git -C "$VR/$WT" log -1 --format=%h) leg=$LEGNO client_s=$CLIENT_S" \
    "ab: $AB" "base=$BASE"
