#!/bin/bash
# Starts Monado in a WAYLAND session using DRM lease, instead of NVIDIA Direct-Mode
# from X11. This is the path by which Project-VR reports the G2 running at 4320x2160@90.
#
#   ./jack-in-wayland.sh [mode] [tracking]
#                                    mode: 0 = 2880x1440@90
#                                          1 = 4320x2160@90  (the one Project-VR uses)
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

MODE="${1:-1}"
# "3dof" is jack-in.sh's syntax for its single positional arg, not this script's mode index —
# and atoi("3dof")=3 silently requested a nonexistent mode (happened on 2026-08-06). Here mode
# is ONLY the display-mode index; tracking is now a separate second argument (T060).
case "$MODE" in
    0|1|2) ;;
    *) echo "invalid mode: '$MODE' (0 = 2880x1440@90, 1 = 4320x2160@90, 2 = 4320x2160@60)" >&2; exit 1 ;;
esac
TRACKING="${2:-3dof}"
case "$TRACKING" in
    3dof|6dof|ctrl) ;;
    *) echo "invalid tracking: '$TRACKING' (3dof, 6dof or ctrl)" >&2; exit 1 ;;
esac
VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$HOME/vr/monado" ] && VR="$HOME/vr"
SERVICE="$VR/monado/build/src/xrt/targets/service/monado-service"
LOG="$VR/jack-in-wayland.log"
SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/monado_comp_ipc"

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
for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
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
    SLAM_THREADS="${SLAM_THREADS:-2}"

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
        echo "  SLAM worker threads: $SLAM_THREADS (of $(nproc) available; 2 is the measured default, SLAM_THREADS= overrides)"
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
if [ "$CONSTELLATION" = 1 ]; then
    echo "  Controller constellation tracking: ON (WMR_CONSTELLATION_CONTROLLERS=0 disables)"
    echo "    verify with: grep -E 'get_tracked_pose:|position_tracked' $LOG"
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
VERBOSE="${VR_VERBOSE:-1}"
LOG_ENV=()
if [ "$VERBOSE" = 1 ]; then
    SLAM_CSV_DIR="$VR/logs/slam-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$SLAM_CSV_DIR"
    LOG_ENV=(
        XRT_LOG=debug
        WMR_LOG=debug
        SLAM_LOG=debug
        CONSTELLATION_TRACKER_LOG=debug
        SLAM_WRITE_CSVS=1
        "SLAM_CSV_PATH=$SLAM_CSV_DIR/"
    )
    echo "Verbose tracking logs ON. Pose CSVs: $SLAM_CSV_DIR"
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
PACING="${VR_PACING:-1}"
PACING_ENV=()
if [ "$PACING" = 1 ]; then
    PACING_ENV=(
        XRT_APP_FRAME_LAG_LOG_AS_LEVEL=info
        XRT_COMP_FRAME_LAG_LOG_AS_LEVEL=info
        U_PACING_APP_LOG=info
        U_PACING_COMPOSITOR_LOG=info
        U_PACING_LIVE_STATS=true
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

echo "Starting Monado (mode $MODE, tracking $TRACKING) via DRM lease... log: $LOG"

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

    env XRT_COMPOSITOR_FORCE_WAYLAND_DIRECT=1 \
        XRT_COMPOSITOR_DESIRED_MODE="$MODE" \
        XRT_COMPOSITOR_LOG=debug \
        XRT_NO_STDIN=1 \
        "${TRACKING_ENV[@]}" \
        "${LOG_ENV[@]}" \
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
    if grep -q "found display mode" "$LOG" && [ -S "$SOCKET" ]; then
        SUCCESS=1
        break
    fi

    # Failed attempt: don't leave a broken instance running into the next try (found the hard
    # way on 2026-08-07: had to manually pkill a service that had been "Socket ready" for
    # several failed launches in a row).
    for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
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
    echo "Socket ready (attempt $ATTEMPT/$MAX_ATTEMPTS). Launch an OpenXR app with:"
    echo "  XR_RUNTIME_JSON=$VR/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 <app> --graphics Vulkan2"
else
    echo "!! No usable compositor after $MAX_ATTEMPTS attempts (no leasable connector / no mode found)." >&2
    echo "!! Last lines of the log:" >&2
    tail -15 "$LOG" >&2
    for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
    rm -f "$SOCKET"
    exit 1
fi
