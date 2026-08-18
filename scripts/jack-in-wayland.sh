#!/bin/bash
# Starts Monado in a WAYLAND session using DRM lease, instead of NVIDIA Direct-Mode
# from X11. This is the path by which Project-VR reports the G2 running at 4320x2160@90.
#
#   ./jack-in-wayland.sh [action] [mode] [tracking]
#
# Three orthogonal, order-independent tokens (docs/43's up/dev/quiet/down mode contract,
# ported here from jack-in.sh -- run with -h/--help for the full usage):
#                                    action: up (default) = quiet launch, ambient-overridable
#                                            dev = verbose launch (this script's old no-args
#                                                  behavior)
#                                            quiet = non-inheriting unattended station
#                                            down = teardown, ignores mode/tracking below
#                                    mode: 0 = 2880x1440@90
#                                          1 = 4320x2160@90  (the one Project-VR uses, default)
#                                          2 = 4320x2160@60  (the only one that works today in X11)
#                                    tracking: 3dof = IMU only, rotation only (default)
#                                              6dof = real SLAM via Basalt (position + rotation)
#                                              ctrl = head 3dof, but cameras ON and constellation
#                                                     tracking of the CONTROLLERS enabled. Isolates
#                                                     controller position from Basalt's CPU load;
#                                                     see WMR_CONSTELLATION_CONTROLLERS below.
#
# Why this is MUCH simpler than jack-in.sh: in X11 you have to fight X for the display
# (free DP-0, cycle the CRTC, restore the portrait rotation). With DRM lease the
# Wayland compositor never takes the HMD -- it sees it marked as non-desktop and leaves it
# leasable. No desktop monitor is touched.

set -u

usage() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [action] [mode] [tracking]

Three orthogonal tokens, any order (docs/43's up/dev/quiet/down mode contract):

  action      lifecycle -- what to do. Default: up.
      up, start              Quiet launch: VR_VERBOSE=0 VR_PACING=0, XRT_COMPOSITOR_LOG
                              defaults to warn. Ambient exports of those still win.
      dev, --verbose, -v     Verbose launch: VR_VERBOSE=1 VR_PACING=1,
                              XRT_COMPOSITOR_LOG=debug -- this script's old, only, behavior.
      quiet, unattended      Non-inheriting station mode: same levels as 'up' but HARD-
                              pinned (ambient does not win), plus VR_POSE_CSVS=0 and the
                              opt-in firehose/debug-GUI vars scrubbed via 'env -u'.
      down, stop             Teardown: SIGTERM monado-service (escalate to -9 after 10s),
                              remove the IPC socket, touch nothing else on disk. Ignores
                              mode/tracking below.

  mode        display index. Default: 1.
      0   2880x1440@90
      1   4320x2160@90  (the one Project-VR uses)
      2   4320x2160@60  (the only one that works today in X11)

  tracking    Default: 3dof.
      3dof   IMU only, rotation only
      6dof   real SLAM via Basalt (position + rotation)
      ctrl   head 3dof, cameras ON, constellation tracking of the CONTROLLERS

  -h, --help  Show this help and exit.

Examples:
  $(basename "${BASH_SOURCE[0]}")              # up, mode 1, 3dof
  $(basename "${BASH_SOURCE[0]}") dev 6dof
  $(basename "${BASH_SOURCE[0]}") quiet 1 6dof
  $(basename "${BASH_SOURCE[0]}") down
EOF
}

# One order-independent pass, mirroring jack-in.sh's argument model (docs/43): every
# argument is classified by which of three disjoint token sets it belongs to, so 'mode'
# and 'tracking' can appear in either order and the new 'action' token can be inserted
# anywhere -- including the old two-positional invocation, ./jack-in-wayland.sh 1 6dof,
# which keeps working unchanged (this also retires the historical footgun where a lone
# '3dof', jack-in.sh's own single-arg syntax, once silently parsed as mode index
# atoi("3dof")=3 and failed as "invalid mode" -- 2026-08-06; classifying by content
# instead of position makes that class of bug structurally impossible now). An argument
# matching none of the three sets is a hard error (exit 2 + usage), not a silent
# fall-through.
ACTION=up
MODE=""
TRACKING=""
for arg in "$@"; do
    case "$arg" in
        -h|--help) usage; exit 0 ;;
        up|start) ACTION=up ;;
        dev|--verbose|-v) ACTION=dev ;;
        quiet|unattended) ACTION=quiet ;;
        down|stop) ACTION=down ;;
        0|1|2)
            [ -n "$MODE" ] && { echo "duplicate mode argument: '$arg'" >&2; usage >&2; exit 2; }
            MODE="$arg"
            ;;
        3dof|6dof|ctrl)
            [ -n "$TRACKING" ] && { echo "duplicate tracking argument: '$arg'" >&2; usage >&2; exit 2; }
            TRACKING="$arg"
            ;;
        *)
            echo "unknown argument: '$arg'" >&2
            usage >&2
            exit 2
            ;;
    esac
done
MODE="${MODE:-1}"
TRACKING="${TRACKING:-3dof}"
VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$HOME/vr/monado" ] && VR="$HOME/vr"
SERVICE="$VR/monado/build/src/xrt/targets/service/monado-service"
LOG="$VR/jack-in-wayland.log"
SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/monado_comp_ipc"

# 'down' teardown (docs/43), dispatched here -- before the Wayland-session guard, the
# basalt/6dof check and the USB census below, none of which a plain stop needs. MODE and
# TRACKING are parsed above but deliberately unused past this point: down is not a launch.
if [ "$ACTION" = down ]; then
    echo "Stopping monado-service..."
    # pgrep -x (exact comm match), NOT -f: -f scans every process's full cmdline, so any
    # bystander that merely *mentions* the binary -- a shell running a compound command, a
    # tail on a path containing "monado-service" -- gets killed too. First live use of
    # 'down' (2026-08-17) SIGTERM'd the invoking agent's own shell exactly this way.
    RUNNING=0
    for p in $(pgrep -x monado-service); do
        RUNNING=1
        # SIGTERM first, deliberately -- the opposite of the kill -9 used elsewhere in
        # this script (that one is pre-launch hygiene against a stale process holding the
        # socket, not a shutdown). SIGTERM runs Monado's clean-path handler (screen-off,
        # DRM lease released); do not "fix" this to match the launch path's kill -9.
        kill -TERM "$p" 2>/dev/null
    done
    if [ "$RUNNING" = 1 ]; then
        for _i in $(seq 1 10); do
            pgrep -x monado-service >/dev/null || break
            sleep 1
        done
        if pgrep -x monado-service >/dev/null; then
            echo "  Still running after 10s, escalating to SIGKILL."
            for p in $(pgrep -x monado-service); do kill -9 "$p" 2>/dev/null; done
        fi
    else
        echo "  Not running."
    fi
    rm -f "$SOCKET"
    # Ramdisk CSV lifecycle (user directive 2026-08-18): session CSVs live on the
    # 10G tmpfs; at close they either get compressed to the SSD (only when the
    # operator says this session's data matters: VR_ARCHIVE_CSV=1) or simply
    # evaporate at reboot/overwrite. Archiving is zstd (fast, ~5-10x on these
    # CSVs); nothing here ever touches dirs already on the SSD path.
    if [ "${VR_ARCHIVE_CSV:-0}" = 1 ] && mountpoint -q /mnt/vrtmp 2>/dev/null; then
        NEWEST="$(ls -dt /mnt/vrtmp/slam-* 2>/dev/null | head -1)"
        if [ -n "$NEWEST" ]; then
            ARCH="$VR/logs/$(basename "$NEWEST").tar.zst"
            tar -C /mnt/vrtmp -cf - "$(basename "$NEWEST")" | zstd -q -o "$ARCH" \
                && echo "CSVs archived: $ARCH" \
                || echo "WARNING: CSV archive failed for $NEWEST" >&2
        fi
    fi
    # Writes nothing else to disk: no DRM-lease/monitor state to restore (the compositor
    # owns the lease under Wayland, unlike jack-in.sh's X11 direct-mode path), and $LOG is
    # left untouched on purpose -- a session that just failed is exactly the one you don't
    # want a teardown silently erasing.
    echo "Socket removed ($SOCKET). $LOG left untouched."
    exit 0
fi

# T060: Basalt (~/vr/basalt/build/libbasalt.so) was never actually built here for a long
# time despite docs referencing SLAM measurements -- cmake --preset library was silently
# failing on undocumented deps and leaving a configured-but-not-built tree. Check for the
# real .so, not just the directory, before promising 6dof.
BASALT_LIB="$VR/basalt/build/libbasalt.so"
if [ "$TRACKING" = "6dof" ] && [ ! -e "$BASALT_LIB" ]; then
    echo "6dof requested but $BASALT_LIB doesn't exist -- build it first (docs/01, 'Basalt's own deps')." >&2
    exit 1
fi

if [ "${XDG_SESSION_TYPE:-}" != "wayland" ]; then
    echo "This needs a WAYLAND session (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset})." >&2
    echo "Log out and choose 'GNOME on Wayland' in SDDM." >&2
    echo "NOTE: there are TWO entries called just 'GNOME' -- one is Wayland and the other is X11." >&2
    echo "     KWin doesn't work for this: it doesn't offer the connector for lease (chap. 04)." >&2
    exit 1
fi

[ -x "$SERVICE" ] || { echo "Can't find monado-service at $SERVICE" >&2; exit 1; }

# The headset's five devices (chap. 00). If the companion is missing, it's the USB port, not Monado.
FOUND=$(lsusb | grep -cE "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15")
echo "Headset USB devices: $FOUND/5"
if [ "$FOUND" -lt 5 ]; then
    echo "  !! Devices missing. Check the USB port before continuing (chap. 00)." >&2
    lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15" >&2
fi

# SIGKILL doesn't clean up the socket, and a stale socket makes startup fail.
for p in $(pgrep -x monado-service); do kill -9 "$p" 2>/dev/null; done
sleep 2
rm -f "$SOCKET"

# Pre-flight the DP hotplug OURSELVES instead of letting Monado race it. Measured
# 2026-08-07 (T050): time from panel.py activate to the DP connector actually flipping
# to "connected" is NOT fixed -- 3 clean back-to-back runs measured ~0.5s, but right
# after an earlier failed attempt it measured ~6s twice, well past the
# WMR_DISPLAY_INIT_SLEEP_SECONDS=2 window Monado itself waits below -- this is why
# "Found no connectors available for direct mode" recurs intermittently even with USB
# fully healthy (04b4:6506, 03f0:0580, 0bda:4c15 all present). Activating and polling
# sysfs directly here, before Monado ever starts, means Monado only starts once the
# connector is provably already up -- its own internal activation is still harmless/
# idempotent on top of this.
PANEL_PY="$(dirname "${BASH_SOURCE[0]}")/panel.py"
echo "Activating panel and waiting for DP hotplug..."
# Don't swallow this: if panel.py can't even run (e.g. missing/moved -- this exact
# silent failure cost a whole night of "the cable must be dying again" 2026-08-08,
# every single automated activation was a no-op with the panel never told to turn on),
# a wrong DP-never-came-up diagnosis a screenful below is the wrong thing to chase.
if ! ACTIVATE_OUT="$(python3 "$PANEL_PY" activate 2>&1)"; then
    echo "  !! panel.py activate FAILED (not a hardware symptom -- fix this first):" >&2
    echo "$ACTIVATE_OUT" | sed 's/^/     /' >&2
fi
# 2026-08-09: checking ANY "card*-DP-*/status == connected" is a false-positive trap on any
# machine with a real desktop monitor on another DP port -- it satisfies this check forever,
# regardless of whether the HEADSET's own connector ever comes up. Found live: this exact
# false positive masked a real, total headset DP hotplug failure for 3+ attempts in a row
# (T096 already established the headset is specifically connector 137/non-desktop=1 on this
# machine -- it stayed disconnected/non-desktop=0 the whole time while a monitor on another
# DP port kept this loop happy). Use drmprops (already in this repo, ../scripts/drmprops.c)
# to check the one DRM property that's actually HMD-specific, instead of raw connector status.
DRMPROPS_C="$(dirname "${BASH_SOURCE[0]}")/drmprops.c"
DRMPROPS_BIN="${TMPDIR:-/tmp}/drmprops.$$"
DP_UP=0
if gcc -o "$DRMPROPS_BIN" "$DRMPROPS_C" -ldrm -I/usr/include/libdrm 2>/dev/null; then
    for _i in $(seq 1 20); do
        if "$DRMPROPS_BIN" 2>/dev/null | awk '
            /^connector/ { conn = $0 }
            /non-desktop  = 1/ { if (conn ~ /CONNECTED/) found = 1 }
            END { exit !found }
        '; then
            DP_UP=1
            break
        fi
        sleep 0.5
    done
    rm -f "$DRMPROPS_BIN"
else
    echo "  !! couldn't compile drmprops.c (missing libdrm-dev?) -- falling back to the old," >&2
    echo "     less precise check (any connected DP-*, can false-positive on other monitors)" >&2
    for _i in $(seq 1 20); do
        for s in /sys/class/drm/card*-DP-*/status; do
            [ "$(cat "$s" 2>/dev/null)" = "connected" ] && { DP_UP=1; break 2; }
        done
        sleep 0.5
    done
fi
if [ "$DP_UP" = 1 ]; then
    echo "  HMD connector (non-desktop=1) up."
    # SECOND gate, added 2026-08-11 (T145): the kernel seeing the connector is NOT the
    # same event as mutter offering it for lease, and Monado only ever asks the
    # compositor. comp_window_direct_wayland.c does one roundtrip, then accepts the
    # lease device's first "done" event as final -- if mutter hasn't finished
    # processing the hotplug at that instant it sends "done" with zero connectors and
    # Monado gives up immediately ("Found no connectors available for direct mode").
    # The old 3-attempt retry below was supposed to cover this, but the unattended
    # boot chain failed all 3 attempts in a row this night with the connector provably
    # up (drmprops green) -- so poll the compositor side directly instead of retrying
    # blind. Same query check-lease.sh already uses; counts the bare "connector:" line
    # (see the note there: grepping "connector: " with a trailing space always gives 0).
    if command -v wayland-info >/dev/null 2>&1 && [ -n "${WAYLAND_DISPLAY:-}" ]; then
        LEASE_OK=0
        for _i in $(seq 1 30); do
            if wayland-info 2>/dev/null \
                | awk '/wp_drm_lease_device_v1/{inblk=1} inblk && /^[[:space:]]*connector:[[:space:]]*$/{found=1} /^interface:/ && !/wp_drm_lease_device_v1/{inblk=0} END{exit !found}'; then
                LEASE_OK=1
                break
            fi
            sleep 0.5
        done
        if [ "$LEASE_OK" = 1 ]; then
            echo "  Compositor offers the connector for lease."
        else
            echo "  !! The connector is up in the kernel but the compositor offers ZERO of them" >&2
            echo "     after 15s -- Monado will fail with 'Found no connectors available'." >&2
            echo "     KWin does this permanently (never use it); on GNOME/mutter it means the" >&2
            echo "     hotplug wasn't picked up. Starting Monado anyway so the log records it." >&2
        fi
    else
        echo "  (wayland-info missing or no WAYLAND_DISPLAY -- skipping the compositor-side check)"
    fi
else
    echo "  !! The HMD's own connector never came up after activation (waited 10s) --" >&2
    echo "     starting Monado anyway, it will report 'Found no connectors available'" >&2
    echo "     if this doesn't clear. This is a real headset/cable symptom, not the old" >&2
    echo "     any-DP-connector false positive -- see docs/22 before assuming software." >&2
fi

if [ "$TRACKING" = "6dof" ]; then
    TRACKING_ENV=(WMR_SLAM=1 "VIT_SYSTEM_LIBRARY_PATH=$BASALT_LIB")

    # Basalt's default pipeline settings are also its EuRoC settings (data/default_config.json
    # and data/euroc/euroc_config.json are byte-for-byte identical), and they are far too
    # sparse for the G2's four 640x480 fisheye cameras. Measured 2026-08-12 (T162), motionless
    # headset, images visually perfect and calibration correct: Basalt held a mean of 0.0-0.9
    # landmarks per camera, so the visual term contributed nothing and the pose was pure IMU
    # dead reckoning -- thousands of metres of runaway. With basalt-g2-config.json's denser
    # detection the same measurement gives 0.72 m at 60 s, and worn+walking it reaches a mean
    # of ~20 landmarks per camera with the position bounded and returning (real tracking, not
    # drift). No single one of the three parameters is enough on its own; it is a threshold.
    #
    # Needs patches/monado/0020 (SLAM_CONFIG_PIPELINE_ONLY) + patches/basalt/0001, which let a
    # config file carry pipeline settings only and keep the driver's calibration. Without them
    # this would be ignored at best. Set SLAM_CONFIG yourself to override; set
    # SLAM_G2_CONFIG=0 to fall back to Basalt's defaults for an A/B.
    # The one euro filter on t_slam's output is off upstream and only reachable from the debug
    # GUI. Measured in-game 2026-08-12 (T162), rotation between consecutive poses: raw Basalt
    # p99 12.03 deg / max 32.3 deg, filtered p99 1.13 deg / max 5.54 deg. That is the jitter
    # the wearer actually feels, and it is rotational -- position filtering and prediction-type
    # changes moved nothing. SLAM_FILTER=none for an A/B.
    TRACKING_ENV+=("SLAM_FILTER=${SLAM_FILTER:-one_euro}")
    # The one euro filter's ORIENTATION cutoff, raised from Monado's compiled-in M_PI
    # (3.14 Hz) to 20 Hz, validated live by the wearer on 2026-08-13 (T177): "casi
    # perfecto", a few pixels of residual shimmer. It is only safe together with
    # SLAM_FILTER_BEFORE_PREDICT (the default in our build): with the filter at the output
    # stage, as upstream has it, the filter IS the continuous motion path and loosening it
    # like this puts Basalt's 12 deg p99 rotational jitter straight into the image. With
    # the reorder, dead reckoning carries the motion and the filter only softens SLAM
    # corrections, so 20 Hz -- ~8 ms of group delay, under one 90 Hz frame -- is enough.
    # Measured end to end: the pose handed to the app went from +42.5 ms BEHIND raw SLAM
    # to 5 ms ahead of it. Position is deliberately left at the original value: only the
    # orientation cutoff was swept and confirmed by a human.
    TRACKING_ENV+=("SLAM_FILTER_ROT_MIN_CUTOFF=${SLAM_FILTER_ROT_MIN_CUTOFF:-20}")

    # Basalt's worker threads. This was the literal 1 until 2026-08-12, and that literal was
    # expensive: measured with a game running, ONE monado thread sat at 99.4% CPU -- a whole
    # core of six on this box -- while the machine idled at 26% overall, and the user felt it
    # as 50-70 fps where 3dof gives 80-90. Aircar showed 7.2-7.7% late frames in 6dof against
    # 2.8% with SLAM off.
    #
    # 2, and it took measuring BOTH SIDES to get here -- the first pass measured only frame
    # pacing, concluded "more threads are worse", and was wrong. The user pushed back
    # ("venía andando bien... con multihilo"), and the pose CSVs settled it:
    #
    #   threads   pose rate   rotation p99   rotation max   late frames
    #   1          9.8 Hz      11.4-23.6 deg   159.8 deg      3.7 %
    #   2         13.8 Hz       7.52 deg        30.0 deg      8.2 %
    #   3         19.9 Hz       7.18 deg        25.1 deg     10.8-11.6 %
    #
    # More threads cost frame pacing and buy tracking. 2 gets essentially all of 3's tracking
    # quality for less of its cost, and the user's verdict wearing it was "mejoró MUCHO"
    # against 1 thread -- which is the criterion that decides it here, per CLAUDE.md. That
    # 159.8-degree step at 1 thread is not a head movement; it is the tracker losing it.
    #
    # NOTE, measured and surprising: this knob does NOT cap Basalt's total threads. At both 2
    # and 3 there are FOUR monado threads at 94-99% CPU; only at 1 is there a single saturated
    # one. Whatever it governs is an internal pool, so do not read it as a core budget.
    #
    # Still a variable, not a literal, for the original reason: tuned on a 6-core/12-thread
    # box, unexamined on an 8-thread one, and this rig runs unattended. Re-measure BOTH sides
    # when changing it -- scripts/frame-pacing.sh for pacing, the tracking.csv pose rate and
    # inter-pose rotation for tracking -- with three windows each; per-window pacing variance
    # here is wide (3.44% and 7.22% back to back in an identical configuration).
    # 2026-08-13 (T180), idle rig, constellation off: SLAM pose throughput 17.3 Hz at 2
    # threads, 25.9 Hz at 4 (the camera gives 30). The default stayed 2 until the in-game
    # side was re-measured; T197 (2026-08-17, pre power-pinning) then found 4 threads
    # indifferent under full load -- because constellation search and the schedutil
    # governor were eating the headroom. 2026-08-17 ~08:00 (T203), with the machine
    # pinned to performance and the clock-skew fix (0055) in: per-stage timing (finally
    # live, 0057) showed the optical-flow TRACKING stage as the #1 cost at 48.5 ms p50,
    # and 4 threads halved it to 28.4 ms with pose-interval p90 dropping 99.9 -> 66.8 ms
    # (the alternating 66/100 ms pattern gone). Wearer-confirmed same session: best
    # controller anchoring of the project, head "un poco mejor". Default is now 4;
    # SLAM_THREADS= still overrides either way.
    SLAM_THREADS="${SLAM_THREADS:-4}"

    G2_SLAM_JSON="$(dirname "${BASH_SOURCE[0]}")/basalt-g2-config.json"
    if [ "${SLAM_G2_CONFIG:-1}" = "1" ] && [ -z "${SLAM_CONFIG:-}" ] && [ -f "$G2_SLAM_JSON" ]; then
        G2_SLAM_TOML="${TMPDIR:-/tmp}/basalt-g2-$$.toml"
        cat > "$G2_SLAM_TOML" <<EOF
show-gui=0
config-path="$G2_SLAM_JSON"
marg-data=""
print-queue=0
use-double=0
deterministic=0
num-threads=$SLAM_THREADS
EOF
        echo "  SLAM worker threads: $SLAM_THREADS (of $(nproc) available; 4 is the measured default since T203, SLAM_THREADS= overrides)"
        TRACKING_ENV+=("SLAM_CONFIG=$G2_SLAM_TOML" SLAM_CONFIG_PIPELINE_ONLY=1)
        echo "  SLAM pipeline config: $G2_SLAM_JSON (denser detection; SLAM_G2_CONFIG=0 disables)"
    elif [ -n "${SLAM_CONFIG:-}" ]; then
        TRACKING_ENV+=("SLAM_CONFIG=$SLAM_CONFIG" "SLAM_CONFIG_PIPELINE_ONLY=${SLAM_CONFIG_PIPELINE_ONLY:-1}")
        echo "  SLAM pipeline config: $SLAM_CONFIG (from the environment)"
    fi
elif [ "$TRACKING" = "ctrl" ]; then
    # Cameras streaming, Basalt not loaded: the controllers' constellation solve gets the whole
    # camera and CPU budget, so "do the controllers report a real position" is answered without
    # Basalt's load in the way. T162 measured that CPU load perturbs IMU sample arrival, which
    # moves the clock fit -- the same clock the constellation samples are stamped against.
    TRACKING_ENV=(WMR_SLAM=0 WMR_CAMERAS=1)
else
    TRACKING_ENV=(WMR_SLAM=0 WMR_CAMERAS=0)
fi

# Constellation (LED) positional tracking of the CONTROLLERS -- patches/monado/0012-0017, the
# other thing this project calls "6DoF" and a different subsystem from head SLAM entirely.
# Default: on for "ctrl", off elsewhere, overridable from the environment for an A/B.
#
# ALWAYS pass it explicitly rather than relying on the default. The option is declared TWICE
# with DIFFERENT defaults -- wmr_hmd.c has `true`, wmr_camera.c has `false` -- so leaving it
# unset creates the tracker (hmd) while the camera path never assigns the controller exposure
# slots that feed it, i.e. a tracker that is silently starved rather than off.
if [ "$TRACKING" = "3dof" ]; then
    CONSTELLATION="${WMR_CONSTELLATION_CONTROLLERS:-0}"   # no cameras: it could only starve
else
    CONSTELLATION="${WMR_CONSTELLATION_CONTROLLERS:-$([ "$TRACKING" = ctrl ] && echo 1 || echo 0)}"
fi
TRACKING_ENV+=("WMR_CONSTELLATION_CONTROLLERS=$CONSTELLATION")

# WMR thumbstick center drift (2026-08-18, WS2 of the closing plan): the sticks ship with
# NO factory center calibration (docs/23's Aircar row documented it in 2026-08-12; patch
# 0008 added the knob) and the wearer feels it directly -- left stick self-presses up+left,
# right presses hard-left + slightly up. This default was never wired into this launcher
# until now. 0.15 masks it; the real fix (per-stick auto-centering, WMR_STICK_AUTOCENTER)
# will let this shrink to ~0.05.
TRACKING_ENV+=("WMR_STICK_DEADZONE=${WMR_STICK_DEADZONE:-0.15}")
if [ "$CONSTELLATION" = 1 ]; then
    echo "  Controller constellation tracking: ON (WMR_CONSTELLATION_CONTROLLERS=0 disables)"
    echo "    verify with: grep -E 'get_tracked_pose:|position_tracked' $LOG"
fi

# --- Lifecycle action -> logging policy (docs/43 mode contract) ---------------------
# Mirrors jack-in.sh's up/dev/quiet contract onto this script's EXISTING master switches
# instead of rebuilding a LOG_ENV from scratch: VR_VERBOSE/VR_PACING already gate the
# blocks below, and XRT_COMPOSITOR_LOG (further down, in the actual monado-service launch
# line) was "the one knob with no master switch" -- hardcoded to debug unconditionally.
# It now follows the same action.
#
#   up     (default)  VR_VERBOSE=0 VR_PACING=0, XRT_COMPOSITOR_LOG defaults to warn.
#                      Ambient exports of any of the three still win (same "ambient wins"
#                      rule as jack-in.sh's up/dev).
#   dev                VR_VERBOSE=1 VR_PACING=1, XRT_COMPOSITOR_LOG=debug -- this was this
#                      script's old, and only, no-args behavior. Still ambient-overridable.
#   quiet              Same effective levels as up, but HARD-PINNED -- ambient exports of
#                      VR_VERBOSE/VR_PACING/XRT_COMPOSITOR_LOG do NOT win here, mirroring
#                      jack-in.sh's "the one deliberately non-inheriting mode" -- plus
#                      VR_POSE_CSVS=0 (no per-run CSV directory) and an env -u scrub of the
#                      opt-in firehoses + debug GUI, the same six-variable list jack-in.sh
#                      scrubs.
#
# NOTE, worth being loud about: no-args now launches QUIETER than before this patch (this
# script's VR_VERBOSE/VR_PACING were unconditionally 1). That is the documented contract's
# own default action ('up'), not an oversight -- see docs/43's "Mirroring this on dev's
# jack-in-wayland.sh". The old verbose-by-default behavior is one token away: 'dev'.
case "$ACTION" in
    dev)  VERBOSE_DEFAULT=1; PACING_DEFAULT=1; COMPOSITOR_LOG_DEFAULT=debug ;;
    *)    VERBOSE_DEFAULT=0; PACING_DEFAULT=0; COMPOSITOR_LOG_DEFAULT=warn ;;  # up, quiet
esac

SCRUB_ENV=()
if [ "$ACTION" = quiet ]; then
    VERBOSE=0
    PACING=0
    XRT_COMPOSITOR_LOG_VALUE=warn
    POSE_CSVS=0
    SCRUB_ENV=(-u VIT_COLLAPSE_LOG -u CONSTELLATION_TRACKER_LOG -u HELLO_XR_POSE_STATS
               -u SLAM_UI -u XRT_TRACING -u XRT_DEBUG_GUI)
    echo "Quiet/unattended launch: levels hard-pinned, firehoses scrubbed, no pose CSVs."
else
    VERBOSE="${VR_VERBOSE:-$VERBOSE_DEFAULT}"
    PACING="${VR_PACING:-$PACING_DEFAULT}"
    XRT_COMPOSITOR_LOG_VALUE="${XRT_COMPOSITOR_LOG:-$COMPOSITOR_LOG_DEFAULT}"
    POSE_CSVS="${VR_POSE_CSVS:-1}"
fi

# --- Eye height / floor calibration (2026-08-12, T163) --------------------------------
# Monado does not measure where the floor is. b_space_overseer_legacy_setup() places STAGE a
# hardcoded 1.6 m below LOCAL (target_builder_helpers.c: T_stage_local.position.y = 1.6), so
# every session assumes the wearer's eyes are exactly 1.6 m up at the moment tracking starts.
# Seated, that is out by roughly half a metre, and the whole world sits at the wrong height.
#
# One number fixes it, and only one: the accelerometer already establishes which way is up, so
# the sole unknown is the distance to the floor. XRT_TRACKING_ORIGIN_OFFSET_Y shifts every
# tracking origin (u_builder_helpers.c applies it to all of them, whatever their type -- the
# 1.3/1.6 defaults just above it are only for XRT_TRACKING_TYPE_NONE), hence:
#
#     offset = (real eye height) - 1.6
#
# What is wanted is EYE height at the moment the origin is anchored, not stature -- eyes sit
# ~11 cm below the top of the head, and sitting down changes it far more than that. Two values
# are kept for that reason; VR_POSTURE picks one.
#
# Read from a profile file so the unattended boot path never has to ask a question. Values in
# metres. Env overrides win, for measuring.
VR_PROFILE="${VR_PROFILE:-$VR/vr-profile.conf}"
if [ -f "$VR_PROFILE" ]; then
    # shellcheck disable=SC1090
    . "$VR_PROFILE"
fi
VR_POSTURE="${VR_POSTURE:-standing}"
case "$VR_POSTURE" in
    standing) EYE_HEIGHT="${VR_EYE_HEIGHT_M:-${EYE_HEIGHT_STANDING_M:-1.6}}" ;;
    seated)   EYE_HEIGHT="${VR_EYE_HEIGHT_M:-${EYE_HEIGHT_SEATED_M:-1.6}}" ;;
    *) echo "invalid VR_POSTURE: '$VR_POSTURE' (standing or seated)" >&2; exit 1 ;;
esac
HEIGHT_ENV=()
ORIGIN_OFFSET_Y="$(awk -v h="$EYE_HEIGHT" 'BEGIN { printf "%.3f", h - 1.6 }')"
if [ "$ORIGIN_OFFSET_Y" != "0.000" ]; then
    HEIGHT_ENV=("XRT_TRACKING_ORIGIN_OFFSET_Y=$ORIGIN_OFFSET_Y")
    echo "  Eye height: ${EYE_HEIGHT} m ($VR_POSTURE) -> origin offset ${ORIGIN_OFFSET_Y} m"
else
    echo "  Eye height: 1.6 m assumed (no profile) -- set $VR_PROFILE to calibrate"
fi

# --- Verbose tracking logging (2026-08-11) ------------------------------------------
# Requested to confirm real movement/tracking rather than inferring it from a session
# that merely starts. Every name below was read out of this tree's own
# DEBUG_GET_ONCE_* declarations, not guessed:
#
#   XRT_LOG                 global default is WARN -- without this, most of the runtime
#                           is silent even when something interesting happens.
#   WMR_LOG                 the G2 driver itself (u_logging.c level names: trace/debug/
#                           info/warn/error).
#   SLAM_LOG                Basalt/VIT integration in t_tracker_slam.cpp.
#   SLAM_WRITE_CSVS +       the objective instrument: writes real pose/timing CSVs. A log
#   SLAM_CSV_PATH           line saying "tracking started" is not evidence of movement;
#                           a CSV of poses is. Per-run directory so runs never overwrite
#                           each other (upstream's default is a bare "evaluation/"
#                           RELATIVE to the CWD, which would scatter files wherever the
#                           launcher happened to be).
#   CONSTELLATION_TRACKER_LOG   no-op until patch 0014 wires a tracker up; set now so the
#                           first run that HAS one is already verbose.
#
# Deliberately NOT enabled here: SLAM_UI=1 (opens its own extra window, only useful with
# XRT_DEBUG_GUI and can steal focus), CONSTELLATION_TRACKER_RERUN_ENABLE (wants an
# external rerun.io viewer), and XRT_TRACING (perfetto). Set VR_VERBOSE=0 to turn the
# whole block off if log volume is ever suspected of perturbing the realtime USB
# callback -- that would be a real measurement, so keep the switch.
# VERBOSE is already resolved above by the lifecycle-action block (action-aware default,
# hard-pinned instead of ambient-overridable under 'quiet').
LOG_ENV=()
if [ "$VERBOSE" = 1 ]; then
    LOG_ENV=(
        XRT_LOG=debug
        WMR_LOG=debug
        SLAM_LOG=debug
        # Ambient wins (T206): a hardcoded debug here silently clobbered an ambient
        # CONSTELLATION_TRACKER_LOG=trace and cost a blob-calibration sample.
        CONSTELLATION_TRACKER_LOG="${CONSTELLATION_TRACKER_LOG:-debug}"
    )
    echo "Verbose tracking logs ON."
fi

# The pose CSVs are SEPARATE from the verbose logs above, and default ON (2026-08-13, T178).
# They used to live inside that block, so VR_VERBOSE=0 -- which is how you silence the
# driver's debug chatter -- silently also turned off the only offline instrument this
# project has. That cost real time the day it was found: a whole measurement session ran
# with no CSVs at all, and the stale file left over from an earlier run looked exactly like
# "the CSV writer died mid-session", which was investigated as a regression before the
# environment was checked. They do not share a cost either: the 31 KB/s and 268 lines/s
# that motivate VR_VERBOSE=0 are the driver's per-poll debug lines, while the CSVs are a
# few hundred KB over a long session. VR_POSE_CSVS=0 turns them off on their own.
CSV_ENV=()
if [ "$POSE_CSVS" = 1 ]; then
    # Big-temporary data goes to the 10G tmpfs when mounted (user directive
    # 2026-08-18: save SSD write cycles + speed; ~190 MB/h of CSVs per session,
    # 5.7 GB had silently accumulated in ~/vr/logs). RAM contents die on
    # reboot/umount BY DESIGN -- copy a session's dir to $VR/logs before reboot
    # if it matters (analysis scripts take the path as an argument either way).
    # Fallback to the SSD path when the ramdisk isn't mounted: never break.
    if mountpoint -q /mnt/vrtmp 2>/dev/null; then
        SLAM_CSV_DIR="/mnt/vrtmp/slam-$(date +%Y%m%d-%H%M%S)"
    else
        SLAM_CSV_DIR="$VR/logs/slam-$(date +%Y%m%d-%H%M%S)"
    fi
    mkdir -p "$SLAM_CSV_DIR"
    CSV_ENV=(
        SLAM_WRITE_CSVS=1
        "SLAM_CSV_PATH=$SLAM_CSV_DIR/"
    )
    echo "Pose CSVs: $SLAM_CSV_DIR"
fi

# --- Frame pacing instrumentation (2026-08-12, T161) --------------------------------
# ALWAYS ON, deliberately, and separate from the VR_VERBOSE block above.
#
# A dropped frame is felt in VR long before it is visible on a counter: a frame that
# misses its slot makes the compositor re-show the previous one, so the view snaps back
# to the old pose for a beat. The user reports this as a "microajuste" when turning the
# head, and reports it as nauseating even at low rates -- which is why this is measured
# on EVERY title from now on, not enabled on demand when something already feels wrong.
#
# What it costs: one log line per late frame. Measured on Aircar, that is ~3 lines/s at
# its worst (during DXVK shader warm-up) and 0.12 lines/s once warm -- against the
# ~49 KB/s the VR_VERBOSE block writes. It is not a meaningful load, and it was measured
# rather than assumed.
#
#   XRT_APP_FRAME_LAG_LOG_AS_LEVEL   the APP missing its deadline (default DEBUG, hidden)
#   XRT_COMP_FRAME_LAG_LOG_AS_LEVEL  the COMPOSITOR missing its deadline (default WARN)
#   U_PACING_APP_LOG / U_PACING_COMPOSITOR_LOG   the two pacers (both default WARN)
#   U_PACING_LIVE_STATS              per-frame pacing statistics (default false)
#
# Read it with ./scripts/frame-pacing.sh -- do not eyeball the log.
# Set VR_PACING=0 to turn it off; there is no known reason to.
# PACING is already resolved above by the lifecycle-action block, same as VERBOSE.
PACING_ENV=()
if [ "$PACING" = 1 ]; then
    PACING_ENV=(
        XRT_APP_FRAME_LAG_LOG_AS_LEVEL=info
        XRT_COMP_FRAME_LAG_LOG_AS_LEVEL=info
        # Externally-set values win. These used to be hardcoded, so exporting
        # U_PACING_APP_LOG=debug in front of this script silently did nothing --
        # `env VAR=x` after the array still loses to the array itself. That matters
        # because debug is the ONLY way to get one log line per DELIVERED app frame,
        # which is the app's real frame rate: frame-pacing.sh counts slots the
        # compositor missed and is blind to an app that delivers 30 fps punctually
        # (demonstrated live 2026-08-13 -- 0 late frames of 2700 while the wearer
        # was looking at 30 fps).
        U_PACING_APP_LOG="${U_PACING_APP_LOG:-info}"
        U_PACING_COMPOSITOR_LOG="${U_PACING_COMPOSITOR_LOG:-info}"
        U_PACING_LIVE_STATS="${U_PACING_LIVE_STATS:-true}"
    )
fi

# Pipelined app pacing is now the DEFAULT (2026-08-13, T175), not an opt-in you have to
# remember. Patch 0042 exists precisely because the serial pacer requires the app's whole
# cpu+draw+gpu sum to fit before its promised slot, so a title whose serial pipeline
# exceeds 11.1 ms gets every other slot forever no matter how idle the machine is. It had
# been measured in T169 and then left unwired, which is how this session ended up
# reproducing the same fault from scratch: measured on Aircar with the headset held still,
# serial 12.37% late frames with the median pinned at exactly one full period, against
# 0.94 / 0.77 / 0.69% over three consecutive windows with this on. Same title, same cable
# seat, nothing else changed. Same class of miss as Basalt's denser config: the fix
# existed, was proven, and simply wasn't the default.
#
# THE COST IS REAL AND THE USER SEES IT, so it is written here rather than buried: in
# pipelined mode he reports a ghost/trail whose separation grows with how fast he turns his
# head -- the signature of latency, not of dropped frames. We traded judder for a stale
# pose. His verdict was that the 6DoF nonetheless "se siente mucho mejor" and that this is
# the new starting point, so it ships on. The next target is the pose prediction, not the
# pacer. And note what this episode proves about the instrument: frame-pacing.sh counts
# missed slots and is BLIND to latency, so this change reads as a pure 13x win in the tool
# while the wearer watches a new artefact appear. Never accept that number alone.
# VR_PIPELINED=0 goes back to the serial pacer.
if [ "${VR_PIPELINED:-1}" = 1 ]; then
    PACING_ENV+=(U_PACING_APP_PIPELINED=true)
fi

echo "Starting Monado (action $ACTION, mode $MODE, tracking $TRACKING) via DRM lease... log: $LOG"

# Keep the previous run's log. Truncating on every start destroyed the one log that could
# have proven why tracking froze mid-session on 2026-08-07 (T045): a later service start
# wiped the evidence. One generation back is enough for the "what did the LAST session say"
# question, without unbounded growth.
[ -f "$LOG" ] && cp -f "$LOG" "${LOG%.log}.prev.log"

# 2026-08-09: "Found no connectors available for direct mode" is a SEPARATE race from the DP
# hotplug already polled above -- confirmed by reading comp_window_direct_wayland.c. It does
# one wl_display_roundtrip() (binds the wp_drm_lease_device_v1 object) then loops
# wl_display_dispatch() until the device sends its "done" event, and accepts THAT as final --
# if mutter's own internal recognition of the just-hotplugged connector as lease-eligible
# hasn't caught up yet and sends "done" with zero connectors, Monado gives up immediately
# instead of waiting/retrying. This is downstream of the sysfs "connected" state we already
# waited for above (that only proves the kernel/DRM side is up, not that mutter's own
# hotplug handling has processed it) -- reproduced 3/3 in a row on 2026-08-09. Cheapest fix
# without touching the live compositor (never do that live, see CLAUDE.md) or patching
# upstream C code: retry the whole launch a few times, same "let it settle, one clean retry"
# pattern already used elsewhere in this project for hardware timing races.
#
# WMR_DISPLAY_INIT_SLEEP_SECONDS=2 is load-bearing just like in X11: the panel turns off
# on its own after ~3s if it doesn't receive a video signal, and with the default 4s Monado wakes up
# when it has already turned off.
#
# XRT_NO_STDIN=1 is also mandatory: without it Monado registers stdin in epoll and, launched
# in the background, dies with 'epoll_ctl(stdin) failed' -> IPC_MAINLOOP_FAILED_TO_INIT before
# even reaching the compositor. setsid + stdbuf -oL keep the log alive (using
# `script` to give it a pty buffers so much that failures become unreadable).
MAX_ATTEMPTS=3
ATTEMPT=1
SUCCESS=0
while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
    if [ "$ATTEMPT" -gt 1 ]; then
        echo "Retry $ATTEMPT/$MAX_ATTEMPTS after a short settle..."
        sleep 3
    fi

    env "${SCRUB_ENV[@]}" \
        XRT_COMPOSITOR_FORCE_WAYLAND_DIRECT=1 \
        XRT_COMPOSITOR_DESIRED_MODE="$MODE" \
        XRT_COMPOSITOR_LOG="$XRT_COMPOSITOR_LOG_VALUE" \
        XRT_NO_STDIN=1 \
        "${TRACKING_ENV[@]}" \
        "${LOG_ENV[@]}" \
        "${CSV_ENV[@]}" \
        "${HEIGHT_ENV[@]}" \
        "${PACING_ENV[@]}" \
        WMR_DISPLAY_INIT_SLEEP_SECONDS=2 \
        setsid stdbuf -oL -eL "$SERVICE" < /dev/null > "$LOG" 2>&1 &

    SVC=$!
    for _i in $(seq 1 30); do
        [ -S "$SOCKET" ] && break
        kill -0 "$SVC" 2>/dev/null || break
        sleep 1
    done

    # The socket appears BEFORE the compositor finishes logging the backend and the mode,
    # so grepping as soon as we see it comes back empty and looks like a failure. We wait for
    # the marker.
    for _i in $(seq 1 20); do
        grep -q "found display mode" "$LOG" && break
        sleep 1
    done

    # A socket existing is NOT enough: the IPC server binds it before it tries to init the
    # compositor, so a failed lease (no connector, no mode) still leaves a live process with a
    # live socket -- any OpenXR app launched against it fails later with
    # XRT_ERROR_RUNTIME_FAILURE on xrGetSystem. Require BOTH the socket and a real mode.
    # And a real mode is STILL not enough (2026-08-17, caught live): if the wmr builder
    # fails to probe the headset -- e.g. the USB2 companion re-enumerating in exactly the
    # wrong window, as it did tonight at 04:38:54 -- Monado silently falls back to the
    # legacy builder's Simulated HMD, which still leases the connector and still logs
    # "found display mode". T050 documented this trap as a manual check; a launcher that
    # can retry should enforce it itself, so a legacy/Simulated session now counts as a
    # failed attempt and gets killed + retried like any other.
    if grep -q "found display mode" "$LOG" && [ -S "$SOCKET" ] && grep -q "Using builder wmr" "$LOG"; then
        SUCCESS=1
        break
    fi
    if grep -q "Using builder legacy" "$LOG"; then
        echo "  Attempt $ATTEMPT: wmr builder failed (companion missing?) -- Simulated HMD fallback detected, retrying." >&2
    fi

    # Failed attempt: don't leave a broken instance running into the next try (found the hard
    # way on 2026-08-07: had to manually pkill a service that had been "Socket ready" for
    # several failed launches in a row).
    for p in $(pgrep -x monado-service); do kill -9 "$p" 2>/dev/null; done
    rm -f "$SOCKET"
    ATTEMPT=$((ATTEMPT + 1))
done

echo
echo "=== chosen compositor backend ==="
# THIS is what you need to look at. The correct string is emitted by compositor_try_window:
#   "Target backend wayland-direct initialized!"   <- DRM lease was used, the test is valid
# In X11 it said "Selected NVIDIA Direct-Mode backend!". If that appears, the lease was NOT used.
# No `| head` here: head always exits 0 and swallows the `|| echo` of the empty branch.
OUT="$(grep -iE "Target backend|Selected .* backend|lease|Found no connectors" "$LOG")"
[ -n "$OUT" ] && echo "$OUT" || echo "  (nothing -- check the whole log)"

echo
echo "=== video mode taken ==="
OUT="$(grep -E "found display mode|frame interval" "$LOG" | tail -3)"
[ -n "$OUT" ] && echo "$OUT" || echo "  (no mode found -- the HMD may not be leasable)"

echo
if [ "$SUCCESS" = 1 ]; then
    if [ "$ACTION" = quiet ]; then
        # quiet suppresses the dev usage banner (docs/43) -- no human is reading it on an
        # unattended station.
        echo "Socket ready (attempt $ATTEMPT/$MAX_ATTEMPTS)."
    else
        echo "Socket ready (attempt $ATTEMPT/$MAX_ATTEMPTS). Launch an OpenXR app with:"
        echo "  XR_RUNTIME_JSON=$VR/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 <app> --graphics Vulkan2"
    fi
else
    echo "!! No usable compositor after $MAX_ATTEMPTS attempts (no leasable connector / no mode found / wmr builder fell back to Simulated)." >&2
    echo "!! Last lines of the log:" >&2
    tail -15 "$LOG" >&2
    for p in $(pgrep -x monado-service); do kill -9 "$p" 2>/dev/null; done
    rm -f "$SOCKET"
    exit 1
fi
