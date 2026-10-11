#!/bin/bash
# ab-run.sh -- one unattended, wearer-less leg of the hare_ware constellation clock A/B.
#
#   setsid nohup ~/vr/ab-run.sh <variant-label> <monado-service path> <duration_s> \
#       > ~/vr/logs/ab-launch-<label>.out 2>&1 < /dev/null &
#
# RUN IT ON iashur, DETACHED (feedback_detached_hardware_runs). Poll for the end marker:
#   ~/vr/logs/ab-<label>-<stamp>.done      (first line: "status=ok|void|failed|refused|aborted ...")
#
# What one leg does (docs/135 runs 1-4, made repeatable):
#   1. Preflight, refusing (exit 2, nothing touched) on: another monado-service running, an active
#      monado.socket systemd unit, no Wayland/GNOME session, headset not 5/5 on USB, low disk,
#      another ab-run holding the lock.
#   2. rm -f the stale $XDG_RUNTIME_DIR/monado_comp_ipc socket.
#   3. Copies ~/vr/jack-in-wayland.sh to a temporary launcher beside it (it must live in ~/vr: it
#      resolves panel.py / gui_env.py / drmprops.c relative to itself) changing ONLY the SERVICE=
#      and LOG= lines (asserted), exactly like the hand-made jack-in-wayland-hw.sh of docs/135.
#   4. Runs it as `up 1 ctrl` (mode 1 = 4320x2160@90, head 3dof, cameras on, controller
#      constellation tracking) with the docs/135 run-3/4 environment: WMR_SLAM=0
#      WMR_HANDTRACKING=0 VR_VERBOSE=1 (-> XRT_LOG/WMR_LOG/SLAM_LOG=debug) and
#      CONSTELLATION_TRACKER_LOG=debug T_LED_SYNC_REFINEMENT_LOG=debug, tracker data recorder on.
#   5. Lets it run <duration_s> from the moment the launcher reports a usable compositor, with no
#      client and no wearer (headset on the desk, controllers lying in camera view, SAME lighting
#      and placement for every variant -- see the dark-room rule in
#      project_aircar_yaw_drift_investigation).
#   6. SIGTERM by PID, wait, verify gone (SIGKILL only if still alive after 20 s, flagged in .done),
#      rm the socket, 4 s USB settle, launcher `down` (only to restore the GNOME idle-blank the
#      launcher suppressed), collects the kernel USB log.
#
# Outputs, all in ~/vr/logs/ with base ab-<label>-<YYYYmmdd-HHMMSS>:
#   .log           service stdout/stderr, every line prefixed '@<epoch.mmm> ' (ab-ts.py; Monado's
#                  own lines carry no timestamp) -- THIS is what ab-analyze.py reads
#   .launcher.log  the launcher's own output       .meta  provenance (binary sha, git rev, diffs)
#   .env           the service's real environment  .usb.log  USB/hidraw changes seen while running
#   .kernel.log    kernel USB/HID messages (best effort, journalctl -k)   .done  end marker
#
# Knobs (environment, all optional): AB_VR_DIR (~/vr)  AB_LAUNCHER (~/vr/jack-in-wayland.sh)
#   AB_RECORD=1 (tracker data recorder .bin in ~/vr/datasets/constellation)  AB_KEEP_RAW=0
#   AB_FORCE=1 (pass --force to the launcher: clears ~/vr/.jack-in-failed)  AB_GZIP=0
#   AB_NUDGE_AT=60 (seconds after ready: speak the Spanish "shake the joys" cue through espeak-ng and
#     record nudge_epoch in .meta; 0 = no nudge; ignored if it would fall in the last 20 s)
#   AB_SETTLE=20 (minimum seconds since the previous leg's .done before a new launch)
#   AB_ALLOW_BT_HIDRAW=1 (do not refuse when a host-Bluetooth G2 controller hidraw exists)
#   VR_BT_CTRL_CHECK is forced to 0 for the leg unless you export it (the launcher's host-BT
#     wait/exit-2 guard is for the UB500 setup; this A/B uses headset-tunnelled controllers)
#   AB_SOCKET  AB_SKIP_DESKTOP_CHECK=1  AB_SKIP_USB_CHECK=1  AB_SKIP_SYSTEMD_CHECK=1  AB_DRY=1
#   (preflight + launcher copy only; the last four exist so the script can be tested on a machine without the rig)
#
# Never pushes, posts or sudoes. Never uses pkill -f / pgrep -f (feedback_pkill_f_self_kill_ssh):
# processes are found by exact comm in /proc and killed by PID.
#
# No `set -e` ON PURPOSE: a hardware leg must always reach cleanup() (stop the service, rm the socket,
# write .done), and many probes here (grep/lsusb/journalctl/kill -0) are expected to "fail". Every
# step that matters is checked explicitly (refuse / REASON + exit 1) and the EXIT trap owns teardown.
# SIGKILL of this script cannot be trapped: if that ever happens, run `~/vr/jack-in-wayland.sh down`
# (pgrep -x + SIGTERM) before the next leg.
set -u

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
usage() { sed -n '2,8p' "${BASH_SOURCE[0]}" >&2; exit 2; }
[ $# -eq 3 ] || usage
LABEL=$1
SVC_ARG=$2
DURATION=$3

case "$LABEL" in ''|*[!A-Za-z0-9._-]*) echo "label must match [A-Za-z0-9._-]+ (got '$LABEL')" >&2; exit 2;; esac
case "$DURATION" in ''|*[!0-9]*) echo "duration_s must be a positive integer (got '$DURATION')" >&2; exit 2;; esac
[ "$DURATION" -ge 10 ] && [ "$DURATION" -le 3600 ] || { echo "duration_s must be 10..3600" >&2; exit 2; }
case "$SVC_ARG" in *[\"\$\`\\]*) echo "service path must not contain quotes, \$, backticks or backslashes" >&2; exit 2;; esac
SVC=$(readlink -f -- "$SVC_ARG" 2>/dev/null || echo "$SVC_ARG")

VRDIR=${AB_VR_DIR:-$HOME/vr}
LAUNCHER_SRC=${AB_LAUNCHER:-$VRDIR/jack-in-wayland.sh}
LOGDIR=$VRDIR/logs
STAMP=$(date +%Y%m%d-%H%M%S)
BASE=$LOGDIR/ab-$LABEL-$STAMP
OUT=$BASE.log                 # timestamped service log
RAW=$BASE.raw.log             # what the launcher's service writes (LOG= in the copy)
LAUNCHLOG=$BASE.launcher.log
META=$BASE.meta
USBLOG=$BASE.usb.log
KLOG=$BASE.kernel.log
ENVF=$BASE.env
DONE=$BASE.done
TS_STOP=$BASE.ts.stop
USB_STOP=$BASE.usb.stop
ABORT_FILE=$LOGDIR/ab-STOP    # touch it to end the running leg early (graceful)
RT=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export XDG_RUNTIME_DIR="$RT"   # systemctl --user / dconf need it in a detached shell
SOCKET=${AB_SOCKET:-$RT/monado_comp_ipc}
LCOPY=$(dirname "$LAUNCHER_SRC")/.ab-launcher-$LABEL-$STAMP.sh
USB_RE="03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"

mkdir -p "$LOGDIR" || { echo "cannot create $LOGDIR" >&2; exit 2; }

now() { date +%s.%N; }
log() { echo "$(date '+%F %T') $*" | tee -a "$META"; }
meta() { echo "$*" >> "$META"; }

STATUS=failed
REASON="never started"
SVC_PID=""
KILL9=0
LPID=""
TS_PID=""
USB_PID=""
START_EPOCH=""
READY_EPOCH=""
RAN_S=0
VOID=""         # non-empty = the leg ran but is not a valid measurement (status=void)
STARTED_ANY=0   # set once we may have started a service/launcher: cleanup then owns teardown

svc_pids() {
    local p c
    for p in /proc/[0-9]*; do
        c=$(cat "$p/comm" 2>/dev/null) || continue
        [ "$c" = monado-service ] && echo "${p#/proc/}"
    done
}
alive() { # alive <pid>: exists AND is still monado-service (guards PID reuse)
    [ -n "${1:-}" ] && [ "$(cat "/proc/$1/comm" 2>/dev/null)" = monado-service ]
}
usb_count() { lsusb 2>/dev/null | grep -cE "$USB_RE"; }

usb_snapshot() {
    local n h hid=""
    n=$(usb_count)
    for h in /sys/class/hidraw/hidraw*; do
        [ -e "$h/device/uevent" ] || continue
        if grep -qiE 'HID_ID=0003:000003F0:' "$h/device/uevent" 2>/dev/null; then hid="$hid ${h##*/}"; fi
    done
    echo "usb=$n/5 hid_hp:${hid:- none}"
}

usb_watch() {
    local last="" cur parent=$$
    # $$ is the main script even inside this subshell; exit if it dies so a SIGKILLed run leaves no orphan.
    while [ ! -e "$USB_STOP" ] && kill -0 "$parent" 2>/dev/null; do
        cur=$(usb_snapshot)
        if [ "$cur" != "$last" ]; then
            printf '@%s %s\n' "$(date +%s.%3N)" "$cur" >> "$USBLOG"
            last=$cur
        fi
        sleep 2
    done
}

stop_service() { # stop_service <pid>: TERM, wait, verify, escalate only if confirmed alive
    local pid=$1 i
    alive "$pid" || return 0
    log "stopping monado-service pid $pid (SIGTERM)"
    kill -TERM "$pid" 2>/dev/null
    for i in $(seq 1 20); do alive "$pid" || break; sleep 1; done
    if alive "$pid"; then
        log "!! still alive 20 s after SIGTERM -- escalating to SIGKILL (will leave the DRM lease dangling)"
        KILL9=1
        kill -9 "$pid" 2>/dev/null
        for i in 1 2 3 4 5; do alive "$pid" || break; sleep 1; done
    fi
    if alive "$pid"; then log "!! pid $pid STILL alive after SIGKILL"; return 1; fi
    log "monado-service pid $pid gone"
    return 0
}

finish_collect() { # best-effort evidence that does not depend on the service
    if [ -n "$START_EPOCH" ]; then
        if journalctl -k --since "@${START_EPOCH%.*}" --no-pager -o short-iso 2>/dev/null \
            | grep -iE 'usb|hid|xhci|hub|disconnect' > "$KLOG" 2>/dev/null && [ -s "$KLOG" ]; then
            :
        elif dmesg --time-format iso 2>/dev/null | grep -iE 'usb|hid|xhci|hub|disconnect' | tail -n 300 > "$KLOG" 2>/dev/null \
            && [ -s "$KLOG" ]; then
            echo "# (dmesg tail, not time-filtered)" >> "$KLOG"
        else
            echo "# no kernel log readable without privileges (journalctl -k and dmesg both empty)" > "$KLOG"
        fi
        if command -v coredumpctl >/dev/null 2>&1; then
            meta "coredumps_since_start: $(coredumpctl list --no-pager --no-legend --since "@${START_EPOCH%.*}" 2>/dev/null | grep -c monado-service)"
        fi
    fi
}

CLEANED=0
cleanup() {
    local rc=$?
    [ "$CLEANED" = 1 ] && return
    CLEANED=1
    trap '' INT TERM HUP
    # Whatever happens, no stray service may outlive this script (feedback_detached_hardware_runs).
    if [ -n "$LPID" ] && kill -0 "$LPID" 2>/dev/null; then
        log "launcher still running at cleanup -- terminating pid $LPID"
        kill -TERM "$LPID" 2>/dev/null; sleep 1
    fi
    if [ "$STARTED_ANY" = 1 ]; then
        # The preflight proved there was no monado-service before us, so any present now is ours.
        local p
        for p in $(svc_pids); do stop_service "$p"; done
        rm -f "$SOCKET"
        if [ -z "$(svc_pids)" ]; then
            sleep 4   # USB re-enumeration settle (feedback_monado_process_hygiene)
            meta "usb_after_stop: $(usb_snapshot)"
            command -v nvidia-smi >/dev/null 2>&1 && \
                meta "nvidia_compute_apps_after_stop: $(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader 2>/dev/null | cut -c1-60 | tr '\n' ';')"
        else
            log "!! monado-service still present after cleanup: $(svc_pids | tr '\n' ' ')"
            STATUS=failed; REASON="monado-service survived cleanup"
        fi
        # `down` only to restore the GNOME idle-blank that the launcher's `up` suppressed; no service
        # is running now so its kill loop is a no-op. Its MONADO_MARKER lands in $RAW (still followed).
        if [ -x "$LCOPY" ]; then
            timeout 30 "$LCOPY" down >> "$LAUNCHLOG" 2>&1 9>&- < /dev/null || true
        fi
    fi
    # Stop the helpers (by PID, verified).
    touch "$USB_STOP" "$TS_STOP" 2>/dev/null
    if [ -n "$TS_PID" ]; then
        for _i in $(seq 1 30); do kill -0 "$TS_PID" 2>/dev/null || break; sleep 0.5; done
        kill -0 "$TS_PID" 2>/dev/null && { log "!! ab-ts.py did not exit, killing pid $TS_PID"; kill "$TS_PID" 2>/dev/null; }
    fi
    if [ -n "$USB_PID" ]; then
        for _i in $(seq 1 10); do kill -0 "$USB_PID" 2>/dev/null || break; sleep 0.5; done
        kill -0 "$USB_PID" 2>/dev/null && kill "$USB_PID" 2>/dev/null
    fi
    # Raw log: drop it once the stamped copy provably holds every line (disk headroom rule).
    if [ -f "$RAW" ] && [ -f "$OUT" ]; then
        local nraw nout
        nraw=$(wc -l < "$RAW"); nout=$(grep -c . "$OUT")
        nout=$((nout - 1))   # minus the AB_TS_END trailer
        meta "lines_raw=$nraw lines_stamped=$(wc -l < "$OUT")"
        if [ "${AB_KEEP_RAW:-0}" != 1 ] && [ "$nraw" -le "$((nout + 0))" ] && tail -n1 "$OUT" | grep -q AB_TS_END; then
            rm -f "$RAW"
        else
            meta "raw_log_kept: $RAW (line count mismatch or AB_KEEP_RAW=1)"
        fi
    fi
    finish_collect
    rm -f "$LCOPY" "$TS_STOP" "$USB_STOP"
    [ -s "${RAW%.log}.prev.log" ] || rm -f "${RAW%.log}.prev.log"
    if [ "${AB_GZIP:-0}" = 1 ] && [ -f "$OUT" ]; then gzip -f "$OUT" && OUT=$OUT.gz; fi
    {
        echo "status=$STATUS reason=$REASON"
        echo "label=$LABEL service=$SVC duration_requested_s=$DURATION ran_s=$RAN_S sigkill_needed=$KILL9"
        echo "start_epoch=$START_EPOCH ready_epoch=$READY_EPOCH end=$(date -Is)"
        echo "log=$OUT"
        echo "meta=$META usb=$USBLOG kernel=$KLOG env=$ENVF launcher_log=$LAUNCHLOG"
    } > "$DONE"
    echo "ab-run: $(head -n1 "$DONE")"
    case "$STATUS" in ok) exit 0;; refused) exit 2;; *) exit 1;; esac
}
trap cleanup EXIT
trap 'REASON="${REASON}; signalled"; [ "$STATUS" = ok ] || STATUS=aborted; exit 1' INT TERM HUP

refuse() { STATUS=refused; REASON="$1"; log "REFUSED: $1"; exit 2; }

: > "$META"
log "ab-run label=$LABEL service=$SVC duration=${DURATION}s stamp=$STAMP host=$(hostname)"
log "reminder: G2 controllers must already be ON and paired to the headset (no hotplug into a running Monado), controllers in camera view, headset on the desk, same lighting for every variant"

# --- single instance ------------------------------------------------------------------------
exec 9> "$LOGDIR/.ab-run.lock"
flock -n 9 || refuse "another ab-run.sh holds $LOGDIR/.ab-run.lock"

# --- argument checks ------------------------------------------------------------------------
[ -f "$SVC" ] && [ -x "$SVC" ] || refuse "monado-service not found/executable: $SVC"
case "$SVC" in
    "$(readlink -f "$VRDIR/monado" 2>/dev/null)"/*|"$VRDIR"/monado/*)
        refuse "$SVC is inside the production tree $VRDIR/monado -- this kit only runs the monado-hw / monado-hw-nofix builds";;
esac
[ -f "$LAUNCHER_SRC" ] || refuse "launcher template not found: $LAUNCHER_SRC"
[ -f "$HERE/ab-ts.py" ] || refuse "ab-ts.py must sit next to ab-run.sh ($HERE)"
command -v python3 >/dev/null || refuse "python3 missing"

# --- process hygiene preflight --------------------------------------------------------------
EXISTING=$(svc_pids | tr '\n' ' ')
[ -z "$EXISTING" ] || refuse "monado-service already running (pid ${EXISTING}) -- not touching it"
if [ "${AB_SKIP_SYSTEMD_CHECK:-0}" != 1 ] && command -v systemctl >/dev/null 2>&1; then
    for u in monado.socket monado.service; do
        systemctl --user is-active --quiet "$u" 2>/dev/null && \
            refuse "systemd --user $u is active and would own the IPC socket (systemctl --user stop $u)"
    done
fi
# Competing OpenVR/XR stacks would fight for the headset USB and the DRM lease.
for p in /proc/[0-9]*; do
    c=$(cat "$p/comm" 2>/dev/null) || continue
    case "$c" in
        vrserver|vrcompositor|vrmonitor|hello_xr|monado-gui|monado-cli)
            refuse "$c is running (pid ${p#/proc/}) -- stop it first; this leg needs the headset to itself";;
    esac
done
# A host-Bluetooth G2 controller (hidraw bus 0005, 045e:066a) would make the WMR builder create a
# BT controller for any hand without a tunnelled one, and a BT creation failure drops the whole
# builder to the Simulated HMD (target_builder_wmr.c). This A/B is about the tunnelled path.
AB_TRANSPORT="${AB_TRANSPORT:-tunnel}"   # tunnel | bt (bt = controllers on the host UB500, docs/136)
case "$AB_TRANSPORT" in tunnel|bt) ;; *) refuse "AB_TRANSPORT must be tunnel or bt";; esac
[ "$AB_TRANSPORT" = bt ] && AB_ALLOW_BT_HIDRAW=1
if [ "${AB_ALLOW_BT_HIDRAW:-0}" != 1 ]; then
    for h in /sys/class/hidraw/hidraw*; do
        grep -q 'HID_ID=0005:0000045E:0000066A' "$h/device/uevent" 2>/dev/null && \
            refuse "host-Bluetooth G2 controller node ${h##*/} present -- unplug the UB500 / power the joys off (AB_ALLOW_BT_HIDRAW=1 overrides)"
    done
fi
# Do not relaunch a headset that just dropped its USB links (relaunching a sick headset makes it worse).
PREV=$(ls -t "$LOGDIR"/ab-*.done 2>/dev/null | head -n1)
if [ -n "$PREV" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$PREV") ))
    WANT=${AB_SETTLE:-20}
    if [ "$AGE" -lt "$WANT" ]; then log "previous leg ended ${AGE}s ago -- waiting $((WANT - AGE))s (AB_SETTLE=$WANT)"; sleep $((WANT - AGE)); fi
fi
if [ -e "$SOCKET" ]; then log "removing stale socket $SOCKET (no monado-service running)"; fi
rm -f "$SOCKET"
[ ! -e "$SOCKET" ] || refuse "cannot remove $SOCKET"

# --- GUI env for a detached shell (feedback_detached_hardware_runs) --------------------------
if [ "${XDG_SESSION_TYPE:-}" != wayland ] && [ -S "$RT/wayland-0" ]; then
    GUI_DIR=$(dirname "$LAUNCHER_SRC")
    if [ -f "$GUI_DIR/gui_env.py" ]; then
        ENVLINES=$(python3 -I - "$GUI_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import gui_env
e = gui_env.get()
for k in ("XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"):
    if k in e:
        print(f"{k}={e[k]}")
PY
)
        while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$ENVLINES"
    else
        export XDG_RUNTIME_DIR="$RT" XDG_SESSION_TYPE=wayland WAYLAND_DISPLAY=wayland-0
    fi
fi
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR:-$RT}/bus}"
meta "gui_env: XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset} DISPLAY=${DISPLAY:-unset}"
if [ "${AB_SKIP_DESKTOP_CHECK:-0}" != 1 ]; then
    [ "${XDG_SESSION_TYPE:-}" = wayland ] || \
        refuse "no Wayland session (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset}, no $RT/wayland-0) -- after the Windows pairing boot into GNOME on Wayland, not KDE X11"
    gs=0
    for p in /proc/[0-9]*; do [ "$(cat "$p/comm" 2>/dev/null)" = gnome-shell ] && { gs=1; break; }; done
    [ "$gs" = 1 ] || refuse "no gnome-shell process: DRM lease needs GNOME Wayland (KWin does not offer the connector)"
fi

# --- headset on the bus, stable -------------------------------------------------------------
if [ "${AB_SKIP_USB_CHECK:-0}" != 1 ]; then
    STABLE=0
    for _s in $(seq 1 30); do
        if [ "$(usb_count)" -ge 5 ]; then STABLE=$((STABLE + 1)); [ "$STABLE" -ge 3 ] && break; else STABLE=0; fi
        sleep 1
    done
    [ "$STABLE" -ge 3 ] || refuse "headset not 5/5 on USB and stable after 30 s ($(usb_count)/5): reseat the PC-end cable (reference_g2_usb_port_fault)"
fi
meta "usb_before: $(usb_snapshot)"
meta "bluetooth_adapters: $(ls /sys/class/bluetooth 2>/dev/null | tr '\n' ' ')"
meta "other_procs: $(for p in /proc/[0-9]*; do c=$(cat "$p/comm" 2>/dev/null); case "$c" in steam|steamwebhelper|Xorg|Xwayland|gnome-shell|obs|chrome|firefox) echo "$c";; esac; done | sort | uniq -c | tr '\n' ' ')"
command -v nvidia-smi >/dev/null 2>&1 && \
    meta "nvidia_compute_apps_before: $(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader 2>/dev/null | cut -c1-60 | tr '\n' ';')"

# --- disk ------------------------------------------------------------------------------------
AVAIL_KB=$(df -Pk "$LOGDIR" | awk 'NR==2{print $4}')
[ "${AVAIL_KB:-0}" -ge 2097152 ] || refuse "less than 2 GB free on $LOGDIR (${AVAIL_KB} KB)"

# --- provenance of the variant ---------------------------------------------------------------
meta "service_sha256: $(sha256sum "$SVC" | cut -d' ' -f1)"
meta "service_mtime: $(stat -c %y "$SVC")"
d=$(dirname "$SVC"); GITROOT=""
while [ "$d" != / ]; do [ -e "$d/.git" ] && { GITROOT=$d; break; }; d=$(dirname "$d"); done
if [ -n "$GITROOT" ] && command -v git >/dev/null; then
    meta "service_git_root: $GITROOT"
    meta "service_git_head: $(git -C "$GITROOT" log -1 --format='%h %s' 2>/dev/null)"
    meta "service_git_branch: $(git -C "$GITROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    meta "service_git_dirty_files: $(git -C "$GITROOT" status --porcelain 2>/dev/null | grep -c .)"
fi

# --- launcher copy: ONLY SERVICE= and LOG= differ ---------------------------------------------
NS=$(grep -c '^SERVICE=' "$LAUNCHER_SRC"); NL=$(grep -c '^LOG=' "$LAUNCHER_SRC")
[ "$NS" = 1 ] && [ "$NL" = 1 ] || refuse "launcher template must have exactly one ^SERVICE= and one ^LOG= line (found $NS/$NL): $LAUNCHER_SRC"
awk -v svc="$SVC" -v lg="$RAW" '
    /^SERVICE=/ { print "SERVICE=\"" svc "\""; next }
    /^LOG=/     { print "LOG=\"" lg "\""; next }
    { print }' "$LAUNCHER_SRC" > "$LCOPY" || refuse "cannot write launcher copy $LCOPY"
chmod +x "$LCOPY"
NDIFF=$(diff "$LAUNCHER_SRC" "$LCOPY" | grep -c '^>')
[ "$NDIFF" = 2 ] || refuse "launcher copy differs in $NDIFF lines, expected exactly 2"
meta "launcher_template: $LAUNCHER_SRC sha256=$(sha256sum "$LAUNCHER_SRC" | cut -d' ' -f1)"
meta "launcher_diff:"; diff "$LAUNCHER_SRC" "$LCOPY" | sed 's/^/    /' >> "$META"
if [ -f "$(dirname "$LAUNCHER_SRC")/jack-in-wayland-hw.sh" ]; then
    meta "docs135_hw_launcher_vs_template_diff_lines: $(diff "$LAUNCHER_SRC" "$(dirname "$LAUNCHER_SRC")/jack-in-wayland-hw.sh" | grep -c '^[<>]')"
fi

# --- environment of the leg (docs/135 run 3/4) ------------------------------------------------
export WMR_SLAM=0 WMR_HANDTRACKING=0
export VR_VERBOSE=1 VR_PACING=0 VR_POSE_CSVS=0
# bt transport: keep the launcher's host-BT guard on, it waits for the awake BT nodes
if [ "$AB_TRANSPORT" = bt ]; then export VR_BT_CTRL_CHECK="${VR_BT_CTRL_CHECK:-1}"; else export VR_BT_CTRL_CHECK="${VR_BT_CTRL_CHECK:-0}"; fi
export CONSTELLATION_TRACKER_LOG="${CONSTELLATION_TRACKER_LOG:-debug}"
export T_LED_SYNC_REFINEMENT_LOG="${T_LED_SYNC_REFINEMENT_LOG:-debug}"
if [ "${AB_RECORD:-1}" = 1 ]; then
    mkdir -p "$VRDIR/datasets/constellation"
    export CONSTELLATION_TRACKER_DATA_RECORDER_OUTPUT="$VRDIR/datasets/constellation/ab-$LABEL-$STAMP.bin"
fi
meta "ambient_env: $(env | grep -E '^(WMR_|XRT_|SLAM_|CONSTELLATION|T_LED|VR_|VIT_|U_)' | sort | tr '\n' ' ')"

meta "plan: $LCOPY ${AB_FORCE:+--force }up 1 ctrl  (launcher output -> $LAUNCHLOG)"
if [ "${AB_DRY:-0}" = 1 ]; then
    STATUS=ok; REASON="dry run: preflight and launcher copy only, nothing started"
    log "$REASON"; exit 0
fi

# --- go ---------------------------------------------------------------------------------------
STARTED_ANY=1; REASON="launch in progress"
START_EPOCH=$(now)
meta "start_epoch: $START_EPOCH"
# RAW is NOT pre-created: the launcher copies an existing $LOG to *.prev.log before starting.
python3 -I "$HERE/ab-ts.py" "$RAW" "$OUT" "$TS_STOP" 9>&- &
TS_PID=$!
usb_watch 9>&- &
USB_PID=$!
log "timestamper pid $TS_PID, usb watcher pid $USB_PID; launching (up 1 ctrl) ..."

FORCE_ARG=(); [ "${AB_FORCE:-0}" = 1 ] && FORCE_ARG=(--force)
timeout 300 "$LCOPY" "${FORCE_ARG[@]}" up 1 ctrl > "$LAUNCHLOG" 2>&1 9>&- < /dev/null &
LPID=$!
wait "$LPID"; LRC=$?
LPID=""
meta "launcher_rc: $LRC"
LATT=$(sed -n 's/.*Socket ready (attempt \([0-9]*\)\/.*/\1/p' "$LAUNCHLOG" | tail -n1)
meta "launcher_attempt: ${LATT:-unknown}"
[ "${LATT:-1}" = 1 ] || log "!! launcher needed attempt $LATT -- the raw log restarted; treat this leg as suspect (see AB_TS_RESTART in the log)"
if [ "$LRC" != 0 ]; then
    REASON="launcher exited $LRC ($(tail -n 3 "$LAUNCHLOG" | tr '\n' '|' | cut -c1-300))"
    log "launcher failed: $REASON"
    exit 1
fi

PIDS=$(svc_pids); NP=$(echo "$PIDS" | grep -c .)
[ "$NP" = 1 ] || { REASON="expected exactly 1 monado-service after launch, found $NP ($PIDS)"; log "$REASON"; exit 1; }
SVC_PID=$PIDS
EXE=$(readlink -f "/proc/$SVC_PID/exe" 2>/dev/null)
# (a real monado-service is an ELF, so exe == path; the check is skipped for a script stand-in used in tests)
if [ "$(head -c4 "$SVC" | tail -c3)" = ELF ] && [ "$EXE" != "$SVC" ]; then
    REASON="running service exe '$EXE' is not the requested '$SVC'"; log "$REASON"; exit 1
fi
grep -q "Using builder wmr" "$RAW" || { REASON="log lacks 'Using builder wmr' (Simulated HMD fallback?)"; log "$REASON"; exit 1; }
tr '\0' '\n' < "/proc/$SVC_PID/environ" 2>/dev/null | grep -E '^(WMR_|XRT_|SLAM_|CONSTELLATION|T_LED|VR_|VIT_|U_)' | sort > "$ENVF"
READY_EPOCH=$(now)
meta "ready_epoch: $READY_EPOCH"
# host CLOCK_MONOTONIC ~ /proc/uptime (no suspend): lets ab-analyze.py turn the no-fix arm's
# "device - host" timesync value back into the headset clock it implies (PROTOCOL C1)
meta "host_uptime_at_ready_s: $(cut -d' ' -f1 /proc/uptime)"
meta "service_pid: $SVC_PID  time_to_ready_s: $(awk -v a="$START_EPOCH" -v b="$READY_EPOCH" 'BEGIN{printf "%.1f", b-a}')"
log "service up (pid $SVC_PID, exe verified). Running ${DURATION}s. No client, no wearer: do not touch the desk."

REASON="running"
T0=$(date +%s); LAST_HB=0
NUDGE_AT=${AB_NUDGE_AT:-60}
case "$NUDGE_AT" in ''|*[!0-9]*) NUDGE_AT=0;; esac
[ "$NUDGE_AT" -gt 0 ] && [ "$NUDGE_AT" -le $((DURATION - 20)) ] || NUDGE_AT=0
NUDGED=0
while :; do
    RAN_S=$(( $(date +%s) - T0 ))
    [ "$RAN_S" -ge "$DURATION" ] && break
    if ! alive "$SVC_PID"; then
        REASON="monado-service died on its own after ${RAN_S}s"; log "$REASON"; STATUS=failed; exit 1
    fi
    if [ "$NUDGE_AT" -gt 0 ] && [ "$NUDGED" = 0 ] && [ "$RAN_S" -ge "$NUDGE_AT" ]; then
        NUDGED=1
        meta "nudge_epoch: $(now)"
        log "NUDGE at t=${RAN_S}s: asking the user to pick both controllers up for ~3 s and put them back on their marks"
        if command -v espeak-ng >/dev/null 2>&1; then
            espeak-ng -v es "Agita los joys, tres segundos" >/dev/null 2>&1 9>&- < /dev/null &
        fi
    fi
    if [ -e "$ABORT_FILE" ]; then
        REASON="aborted by $ABORT_FILE after ${RAN_S}s"; log "$REASON"; rm -f "$ABORT_FILE"; STATUS=aborted; exit 1
    fi
    if [ $((RAN_S - LAST_HB)) -ge 30 ]; then
        LAST_HB=$RAN_S
        echo "$(date '+%F %T') t=${RAN_S}s/${DURATION}s raw_bytes=$(stat -c %s "$RAW" 2>/dev/null)" > "$BASE.progress"
    fi
    sleep 1
done
RAN_S=$(( $(date +%s) - T0 ))
# Only controllers added BEFORE the compositor logged its display mode existed when the builder
# returned (wmr_create_headset waits for the controller status first); a late-waking controller is
# logged too but is neither exposed nor attached to the constellation tracker (target_builder_wmr.c).
CTRLS=$(awk '/found display mode/ {exit} {print}' "$RAW" 2>/dev/null | grep -o 'Adding controller device [0-9]*' | sed 's/.*device //' | sort -u | tr '\n' ',')
LATE=$(awk 'f {print} /found display mode/ {f=1}' "$RAW" 2>/dev/null | grep -o 'Adding controller device [0-9]*' | sed 's/.*device //' | sort -u | tr '\n' ',')
[ -z "$LATE" ] || meta "controllers_added_late_not_tracked: $LATE"
meta "controllers_created: ${CTRLS:-none}"
# Transport-neutral count: wmr_controller_base logs this INFO line for tunnelled and BT controllers.
NCFG=$(awk '/found display mode/ {exit} {print}' "$RAW" 2>/dev/null | grep -c 'Reading configuration for controller serial')
meta "transport: $AB_TRANSPORT controller_configs_before_display: $NCFG"
if grep -q 'Failed to add device to constellation tracker\|did not have config when adding\|did not get assigned a constellation tracker' "$RAW" 2>/dev/null; then
    VOID="constellation_attach_failed"
fi
[ "$AB_TRANSPORT" = bt ] && [ "${NCFG:-0}" -ge 2 ] && CTRLS="0,1,"
case "$CTRLS" in
    0,1,) ;;
    *) log "!! VOID LEG: not both controllers were created (${CTRLS:-none}) -- they must be ONLINE before the launch"; VOID="controllers_created=${CTRLS:-none}";;
esac
log "duration reached (${RAN_S}s) -- stopping"
if [ -n "$VOID" ]; then STATUS=void; REASON="ran to the end but the leg is void: $VOID"; else STATUS=ok; REASON="completed"; fi
exit 0
