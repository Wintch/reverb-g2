#!/bin/bash
# jack-in.sh - bring up the Reverb G2 VR pipeline in one shot.
#
#   ./jack-in.sh [action] [tracking]
#
# Requires an X11 session (not Wayland) - the NVIDIA direct-mode compositor
# path needs it. Log into "Plasma (X11)" from the SDDM session picker first.
#
# Two orthogonal, order-independent tokens (docs/43's up/dev/quiet/down mode contract --
# run with -h/--help for the full usage):
#   action     up (default) = quiet launch, ambient-overridable log levels
#              dev = verbose launch (WMR/XRT/SLAM/compositor logs at debug)
#              quiet = non-inheriting unattended station (hard-pinned warn, firehoses scrubbed)
#              down = teardown, ignores the tracking token below
#   tracking   6dof (default) = SLAM/Basalt, real 6DoF, currently jittery on this rig
#              3dof = IMU-only, rotation only, tracking cameras off entirely -- rock steady

set -u

usage() {
	cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [action] [tracking]

Two orthogonal tokens, any order (docs/43's up/dev/quiet/down mode contract):

  action      lifecycle -- what to do. Default: up.
      up, start              Quiet launch: WMR_LOG/XRT_LOG/SLAM_LOG/XRT_COMPOSITOR_LOG
                              default to warn. Ambient exports of those still win. This is
                              a deterministic restatement of the script's old, only,
                              behavior (Monado's own compiled default was already WARN).
      dev, --verbose, -v     Verbose launch: the same four log levels default to debug.
                              Ambient still wins.
      quiet, unattended      Non-inheriting station mode: same levels as 'up' but HARD-
                              pinned (ambient does not win), pacing logs pinned too, and the
                              opt-in firehose/debug-GUI vars scrubbed via 'env -u'. Suppresses
                              the dev usage banner at the end.
      down, stop             Teardown: SIGTERM monado-service (escalate to -9 after 10s),
                              remove the IPC socket, reassert the desktop monitor layout.
                              Ignores the tracking token below.

  tracking    Default: 6dof.
      6dof   SLAM/Basalt, real 6DoF, currently jittery on this rig.
      3dof   IMU-only, rotation only, tracking cameras off entirely -- rock steady.

  -h, --help  Show this help and exit.

Examples:
  $(basename "${BASH_SOURCE[0]}")              # up, 6dof (unchanged from before this contract)
  $(basename "${BASH_SOURCE[0]}") dev 3dof
  $(basename "${BASH_SOURCE[0]}") quiet
  $(basename "${BASH_SOURCE[0]}") down
EOF
}

# One order-independent pass (docs/43), mirroring jack-in-wayland.sh's argument model:
# every argument is classified by which of two disjoint token sets it belongs to, so
# 'action' and 'tracking' may appear in either order, and the old single positional
# invocation (./jack-in.sh 3dof, ./jack-in.sh with no args) keeps working unchanged. An
# argument matching neither set is a hard error (exit 2 + usage), not a silent fall-through
# -- previously an unrecognized $1 silently fell through to the 6dof branch.
ACTION=up
TRACK=""
for arg in "$@"; do
	case "$arg" in
		-h|--help) usage; exit 0 ;;
		up|start) ACTION=up ;;
		dev|--verbose|-v) ACTION=dev ;;
		quiet|unattended) ACTION=quiet ;;
		down|stop) ACTION=down ;;
		3dof|6dof)
			[ -n "$TRACK" ] && { echo "duplicate tracking argument: '$arg'" >&2; usage >&2; exit 2; }
			TRACK="$arg"
			;;
		*)
			echo "unknown argument: '$arg'" >&2
			usage >&2
			exit 2
			;;
	esac
done
TRACK="${TRACK:-6dof}"

# Where the source trees live. bootstrap-lab.sh puts them in ~/vr; the older hand-built setup
# on the development machine used ~/Documents/linux_vr_base. Autodetected, VR_BASE=... overrides.
if [ -n "${VR_BASE:-}" ]; then
	:
elif [ -d "$HOME/Documents/linux_vr_base/monado/build" ]; then
	VR_BASE="$HOME/Documents/linux_vr_base"
else
	VR_BASE="$HOME/vr"
fi

MONADO_BUILD="$VR_BASE/monado/build"
BASALT_LIB="$VR_BASE/basalt/build/libbasalt.so"
SERVICE="$MONADO_BUILD/src/xrt/targets/service/monado-service"
LOG="$VR_BASE/jack-in.log"
SOCKET="/run/user/$(id -u)/monado_comp_ipc"

# The video output the headset hangs off. DP-0 on both of our machines so far, but nothing
# guarantees that: HMD_OUTPUT=DP-1 ./jack-in.sh if xrandr says otherwise.
HMD_OUTPUT="${HMD_OUTPUT:-DP-0}"

# 2026-08-07 status note: the paragraph below is HISTORICAL. The 90Hz failure it describes
# was resolved by the bpc patch (repo docs/13 + docs/19); the verified 90Hz path is
# jack-in-wayland.sh (DRM lease, GNOME). This X11 script has NOT been retested at 90Hz
# since the fix, so its 60Hz default stays as a conservative choice, not as a law of nature.
#
# Mode 2 = 4320x2160@60 (supersampled render target for the 2880x1440 panel). 60Hz is forced
# because of NVIDIA driver bug 5923212 (driver 550.163.01): at 90Hz the DP link never trains and
# the panel shows only its boot logo. Tested 2026-08-04 -- BOTH 90Hz modes fail (idx 0 =
# 2880x1440@90 native, 428MHz pclk; idx 1 = 4320x2160@90, 905MHz), while idx 2 = 4320x2160@60 at
# 709MHz works. Since the working 60Hz mode has a HIGHER pixel clock than the native 90Hz mode
# that fails, this is NOT a bandwidth limit - it is tied to the 90Hz refresh rate itself. The same
# headset does 90Hz fine under Windows, so the hardware/cable are capable. The API reports success
# and a happy 90.0 fps even when the panel is black - the failure is invisible above the driver,
# only observable physically in the headset. Cost of the workaround: visible 60Hz backlight-strobe
# flicker. Retry 90Hz after any NVIDIA driver upgrade.
#
# WMR_DISPLAY_INIT_SLEEP_SECONDS=2 (default 4) is load-bearing, see wake_panel() below.
#
# The mode can be overridden from outside - which is exactly what the 90Hz test in ch. 04 asks
# for (`XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof`). This list used to pin it to 2
# regardless of the environment, so the 90Hz test was silently running at 60Hz.
DESIRED_MODE="${XRT_COMPOSITOR_DESIRED_MODE:-2}"
COMMON_ENV=(
	VIT_SYSTEM_LIBRARY_PATH="$BASALT_LIB"
	XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="${XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY:-HP Inc.}"
	XRT_COMPOSITOR_DESIRED_MODE="$DESIRED_MODE"
	XRT_NO_STDIN=1
	WMR_DISPLAY_INIT_SLEEP_SECONDS="${WMR_DISPLAY_INIT_SLEEP_SECONDS:-2}"
)

# --- Lifecycle action -> logging policy (docs/43 mode contract) ---------------------
# This script never set WMR_LOG/XRT_LOG/SLAM_LOG/XRT_COMPOSITOR_LOG explicitly before --
# Monado's own compiled default is WARN, so plain 'up' below is a deterministic restatement
# of the old effective noise, not a behavior change.
#
#   up     (default)  ${VAR:-warn} on all four -- ambient exports still win.
#   dev                ${VAR:-debug} on all four -- ambient still wins.
#   quiet              HARD-pinned warn (no ${VAR:-...} -- ambient does NOT win), the pacing
#                      logs pinned too (U_PACING_APP_LOG/U_PACING_COMPOSITOR_LOG=warn,
#                      U_PACING_LIVE_STATS=false), and the opt-in firehoses + XRT_DEBUG_GUI
#                      scrubbed via 'env -u'. The one deliberately non-inheriting mode -- the
#                      station you can walk away from.
#
# Layering: SCRUB_ENV (-u, quiet only) must come first in the `env` invocation inside
# start_service() so it strips before anything re-adds a var; COMMON_ENV (which now carries
# LOG_ENV) comes next; explicit args passed to start_service() (WMR_SLAM=.../WMR_CAMERAS=...,
# or wake_panel()'s own pinned-low overrides) come last and win, matching GNU env's
# later-NAME=VALUE-wins semantics.
case "$ACTION" in
	dev)   LOG_LEVEL_DEFAULT=debug ;;
	*)     LOG_LEVEL_DEFAULT=warn ;;   # up, quiet
esac

SCRUB_ENV=()
if [ "$ACTION" = quiet ]; then
	LOG_ENV=(
		WMR_LOG=warn XRT_LOG=warn SLAM_LOG=warn XRT_COMPOSITOR_LOG=warn
		U_PACING_APP_LOG=warn U_PACING_COMPOSITOR_LOG=warn U_PACING_LIVE_STATS=false
	)
	SCRUB_ENV=(-u VIT_COLLAPSE_LOG -u CONSTELLATION_TRACKER_LOG -u HELLO_XR_POSE_STATS
	           -u SLAM_UI -u XRT_TRACING -u XRT_DEBUG_GUI)
	echo "Quiet/unattended launch: levels hard-pinned, firehoses scrubbed."
else
	LOG_ENV=(
		WMR_LOG="${WMR_LOG:-$LOG_LEVEL_DEFAULT}"
		XRT_LOG="${XRT_LOG:-$LOG_LEVEL_DEFAULT}"
		SLAM_LOG="${SLAM_LOG:-$LOG_LEVEL_DEFAULT}"
		XRT_COMPOSITOR_LOG="${XRT_COMPOSITOR_LOG:-$LOG_LEVEL_DEFAULT}"
	)
	[ "$ACTION" = dev ] && echo "Verbose launch: WMR/XRT/SLAM/compositor logs at debug."
fi
COMMON_ENV+=("${LOG_ENV[@]}")

dp0_status() { xrandr --query 2>/dev/null | awk -v o="$HMD_OUTPUT" '$1==o{print $2}'; }
# pgrep -x (exact comm match), NOT -f: a -f pattern scans every process's full cmdline, so
# any bystander that merely *mentions* the binary -- a shell running a compound command, a
# tail on a path containing "monado-service" -- gets matched too. Live-fired 2026-08-17
# (T196) on jack-in-wayland.sh's first 'down' invocation, which SIGTERM'd the invoking
# agent's own shell this exact way; every pgrep site in this project now uses -x.
service_pids() { pgrep -x monado-service; }

# Switching the headset's display off forces a CRTC reconfiguration, and there the NVIDIA
# driver silently loses the rotation of a portrait monitor (xrandr keeps REPORTING "right"
# while the panel shows landscape). The whole layout has to be re-asserted, and not only after
# the `--off`: also after Monado takes the display.
#
# This used to be hardcoded with the outputs of one particular machine, which on anybody
# else's rig would rearrange or switch off monitors that have nothing to do with VR. Now we
# snapshot the REAL layout before touching anything and restore that snapshot.
MONITOR_LAYOUT=()

snapshot_monitors() {
	local line
	MONITOR_LAYOUT=()
	while IFS= read -r line; do
		[ -n "$line" ] && MONITOR_LAYOUT+=("$line")
	done < <(xrandr --query | awk -v hmd="$HMD_OUTPUT" '
		function flush(  ) {
			if (cur != "" && mode != "") print cur "|" mode "|" pos "|" rot "|" prim
			cur = ""; mode = ""; pos = ""; rot = "normal"; prim = ""
		}
		/^[^ \t]/ {
			flush()
			if ($2 != "connected" || $1 == hmd) next
			cur = $1
			for (i = 3; i <= NF; i++) {
				if ($i == "primary") { prim = "primary"; continue }
				if ($i ~ /^[0-9]+x[0-9]+\+[-0-9]+\+[-0-9]+$/) {
					split($i, g, "+"); pos = g[2] "x" g[3]
					n = $(i + 1)
					if (n == "left" || n == "right" || n == "inverted") rot = n
					break
				}
			}
			if (pos == "") cur = ""   # connected but no CRTC: leave it alone
			next
		}
		# The active mode is the line carrying "*". The geometry on the header line is
		# already rotated (1080x1920), so the mode has to come from here or --mode fails.
		/\*/ { if (cur != "" && mode == "") mode = $1 }
		END { flush() }
	')
}

reassert_monitors() {
	local entry name mode pos rot prim args=() rotated=()

	[ ${#MONITOR_LAYOUT[@]} -gt 0 ] || return 0

	for entry in "${MONITOR_LAYOUT[@]}"; do
		IFS='|' read -r name mode pos rot prim <<<"$entry"
		args+=(--output "$name" --mode "$mode" --pos "${pos/x/+}" --rotate "$rot")
		[ "$prim" = "primary" ] && args+=(--primary)
		[ "$rot" != "normal" ] && rotated+=("$name:$rot")
	done

	# Cycling the rotation back through normal is what actually forces the driver to
	# reprogram the CRTC: re-requesting the rotation xrandr already thinks it has is a no-op.
	for entry in "${rotated[@]}"; do
		xrandr --output "${entry%%:*}" --rotate normal 2>/dev/null
	done
	[ ${#rotated[@]} -gt 0 ] && sleep 1

	xrandr "${args[@]}" 2>/dev/null

	# On KDE, Plasma has its own idea of the layout and can overwrite what xrandr just did;
	# kscreen-doctor talks to the same daemon, so the rotation sticks.
	if [ ${#rotated[@]} -gt 0 ] && command -v kscreen-doctor >/dev/null 2>&1; then
		for entry in "${rotated[@]}"; do
			kscreen-doctor "output.${entry%%:*}.rotation.${entry##*:}" >/dev/null 2>&1
		done
	fi
}

wait_for_companion() {
	# The headset's companion board (03f0:0580, "QHMD A85V") carries the HID control interface
	# and the audio function. If it is absent when the service starts, Monado silently falls
	# back to the "legacy" builder and you get a Simulated HMD instead of the real headset.
	#
	# It also drops off the bus while the panel is lit: the whole internal USB 2.0 hub
	# (04b4:6506) resets and re-enumerates, taking the companion and the headset's audio
	# device with it. Scales with panel load (measured 2026-08-04) and looks like a brownout,
	# BUT it is not the DC supply: the same headset runs 90Hz under Windows 11 for hours
	# without a single drop, and killing Monado brings the companion back within ~5s.
	# Current suspect: Monado's WMR HID keepalive handling vs. Windows' (see repo
	# docs/06-known-issues.md). Nothing here can fix it, so just wait for a good moment.
	for _i in $(seq 1 30); do
		lsusb | grep -q "03f0:0580" && return 0
		sleep 2
	done
	echo "Companion device (03f0:0580) still missing after 60s." >&2
	echo "Unplug and replug the headset USB, then retry. Verify with: lsusb | grep 03f0:0580" >&2
	return 1
}

start_service() {
	# Run WITHOUT `script`. It used to be needed to hand Monado a pty, but XRT_NO_STDIN=1
	# already covers that, and `script` buffers the log so aggressively that it sits frozen
	# mid-line for minutes - which makes every failure impossible to diagnose. stdbuf keeps
	# the log live.
	cd "$MONADO_BUILD" || return 1
	env "${SCRUB_ENV[@]}" "${COMMON_ENV[@]}" "$@" \
		setsid stdbuf -oL -eL "$SERVICE" < /dev/null >> "$LOG" 2>&1 &
	disown
}

# The panel is off until Monado sends the WMR activation report over HID. But Monado can only
# take the display in direct mode if X is not driving it, and X cannot release a connector that
# never linked in the first place. So: run the service once purely to wake the panel, then kill
# it with -9 (SIGTERM would run the clean shutdown path, which sends screen-off and puts us back
# where we started), leaving the panel lit for the real run.
#
# Timing matters. The panel powers up, waits for a valid video signal, and powers itself back
# down after ~3 seconds if none arrives. With the upstream default of 4s Monado wakes up one
# second after the panel died, finds no display to enumerate, and sleeps forever in
# hrtimer_nanosleep. Hence WMR_DISPLAY_INIT_SLEEP_SECONDS=2.
wake_panel() {
	echo "Panel is dark - running Monado once to send the WMR activation report..."
	rm -f "$SOCKET"
	# Pinned low regardless of ACTION (docs/43): this run is kill -9'd within seconds and
	# its log is about to be truncated before the real run, so it never needs 'dev's
	# verbosity. These explicit values win over COMMON_ENV's mode-based LOG_ENV because
	# start_service()'s `env` invocation lists "$@" (this call's own args) after COMMON_ENV,
	# and env's later NAME=VALUE wins. Export the level yourself if you need to debug the
	# probe itself.
	start_service WMR_SLAM=0 WMR_CAMERAS=0 WMR_LOG=warn XRT_LOG=warn XRT_COMPOSITOR_LOG=warn XRT_DEBUG_GUI=0 || return 1

	for _i in $(seq 1 25); do
		if [ "$(dp0_status)" = "connected" ]; then
			echo "Panel is up."
			break
		fi
		sleep 1
	done

	for pid in $(service_pids); do kill -9 "$pid" 2>/dev/null; done
	sleep 2
	rm -f "$SOCKET"

	[ "$(dp0_status)" = "connected" ]
}

# 'down' teardown (docs/43), dispatched here -- before the X11-session guard and the
# already-running guard below, both of which a plain stop doesn't need and the latter of
# which would actively defeat it (it would print "Already running" and exit without
# stopping anything, since it only checks for the service already being up). TRACK is
# parsed above but deliberately unused past this point: down is not a launch.
if [ "$ACTION" = down ]; then
	echo "Stopping monado-service..."
	RUNNING=0
	for p in $(service_pids); do
		RUNNING=1
		# SIGTERM first, deliberately -- the opposite of wake_panel's kill -9 above (that
		# one is pre-launch hygiene against a stale process holding the socket, not a
		# shutdown). SIGTERM runs Monado's clean-path handler (screen-off, display
		# released); do not "fix" this teardown to match the launch path's kill -9.
		kill -TERM "$p" 2>/dev/null
	done
	if [ "$RUNNING" = 1 ]; then
		for _i in $(seq 1 10); do
			[ -z "$(service_pids)" ] && break
			sleep 1
		done
		if [ -n "$(service_pids)" ]; then
			echo "  Still running after 10s, escalating to SIGKILL."
			for p in $(service_pids); do kill -9 "$p" 2>/dev/null; done
		fi
	else
		echo "  Not running."
	fi
	rm -f "$SOCKET"
	# Restore the desktop monitor layout -- but only under X11, so 'down' can also clean up
	# from a non-X11 session without touching xrandr at all. Unlike the launch path's two
	# reasserts (one after freeing DP-0, one after Monado starts), this is a single
	# snapshot+reassert of whatever the desktop looks like right now: Monado taking/
	# releasing the direct-mode display can leave a portrait monitor's CRTC rotation
	# desynced from what xrandr reports (see reassert_monitors' comment on why re-cycling
	# the rotation is what actually forces a reprogram), and this is the same fix applied
	# once at teardown instead of twice around a launch.
	if [ "${XDG_SESSION_TYPE:-}" = "x11" ]; then
		snapshot_monitors
		reassert_monitors
		echo "Desktop monitor layout reasserted."
	fi
	# Writes nothing else to disk: $LOG is left untouched on purpose -- a session that just
	# failed is exactly the one you don't want a teardown silently erasing.
	echo "Socket removed ($SOCKET). $LOG left untouched."
	exit 0
fi

if [ "${XDG_SESSION_TYPE:-}" != "x11" ]; then
	echo "Not in an X11 session (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset})." >&2
	echo "Log out and pick 'Plasma (X11)' at the SDDM login screen, then re-run this." >&2
	exit 1
fi

if [ -n "$(service_pids)" ]; then
	echo "Already running."
	exit 0
fi

# Tracking mode. SLAM (Basalt) gives 6DoF but on this rig it DIVERGES badly - measured ~3 deg mean
# and 20-30 deg max inter-frame rotation with the headset sitting motionless on a desk. IMU-only
# 3DoF measures ~0.0013 deg mean / 0.056 deg max, i.e. ~2000x more stable, at the cost of
# positional tracking. For orientation-only apps (360 photos/video, skyboxes) 3DoF is strictly
# better; real 6DoF apps still need SLAM despite the jitter.
#   ./jack-in.sh 3dof   -> IMU-only, rock steady, no position, tracking cameras off entirely
#   ./jack-in.sh        -> SLAM/Basalt, 6DoF, currently jittery
# Orthogonal to the lifecycle action (docs/43): ./jack-in.sh dev 3dof, ./jack-in.sh quiet, etc.
if [ "$TRACK" = "3dof" ]; then
	echo "Tracking: IMU-only 3DoF (WMR_SLAM=0, WMR_CAMERAS=0) - rotation only, very stable."
	MODE_ENV=(WMR_SLAM=0 WMR_CAMERAS=0)
else
	echo "Tracking: SLAM/Basalt 6DoF (pass '3dof' for the rock-steady orientation-only mode)."
	MODE_ENV=(WMR_SLAM=1)
fi

wait_for_companion || exit 1

if [ "$(dp0_status)" != "connected" ]; then
	wake_panel || {
		echo "Panel never came up. Check the headset's DC supply and the DisplayPort cable." >&2
		exit 1
	}
fi

# The snapshot is taken HERE: the layout is still intact, and the headset (already awake) is
# kept out of it by the HMD_OUTPUT filter.
snapshot_monitors
echo "Desktop layout: ${MONITOR_LAYOUT[*]:-<none detected>}"

echo "Freeing the headset's display from the desktop ($HMD_OUTPUT)..."
xrandr --output "$HMD_OUTPUT" --off
sleep 8   # let X/NVIDIA fully release the CRTC before Vulkan tries to lease it - without this,
          # vkAcquireXlibDisplayEXT races and fails with VK_ERROR_UNKNOWN. 3s was not always enough.

echo "Re-asserting desktop monitor layout..."
reassert_monitors

# The companion often drops during that several-second window - wait for it again rather than
# starting into a Simulated HMD.
wait_for_companion || exit 1

# Turn the controllers on BEFORE this point if you want them: they are already paired to the
# headset over Bluetooth, but Monado only probes for them at startup, so ones powered on later
# show up as 'left/right: <none>' until the service is restarted.

echo "Starting Monado (action $ACTION, tracking $TRACK, log: $LOG)..."
rm -f "$SOCKET"
: > "$LOG"
start_service "${MODE_ENV[@]}" || exit 1

for _i in $(seq 1 20); do
	grep -q "Started vblank event thread" "$LOG" 2>/dev/null && break
	sleep 1
done

# Monado acquiring the display reprograms the CRTCs a second time, which drops the portrait
# monitor's rotation again. Put it back.
reassert_monitors

if grep -q "Started vblank event thread" "$LOG" 2>/dev/null; then
	echo "Jacked in - compositor is presenting."
else
	echo "Compositor did not reach the vblank thread. Check $LOG." >&2
fi

# 'quiet' suppresses this banner (docs/43) -- no human is reading it on an unattended station.
if [ "$ACTION" != quiet ]; then
	cat <<EOF

Launch any OpenXR app with:
  XR_RUNTIME_JSON=$MONADO_BUILD/openxr_monado-dev.json IPC_IGNORE_VERSION=1 <app> --graphics Vulkan2

IPC_IGNORE_VERSION=1 is needed because hello_xr was built against an older Monado than the one
running here (client v25.1.0-706 vs service v25.1.0-708); without it xrCreateInstance fails with
XR_ERROR_RUNTIME_UNAVAILABLE. Rebuilding hello_xr is the clean fix.

hello_xr quits the instant stdin hits EOF, so keep stdin open, e.g.:
  sleep 120 | XR_RUNTIME_JSON=... IPC_IGNORE_VERSION=1 hello_xr --graphics Vulkan2

For the 360 photo viewer, set HELLO_XR_PHOTO360=/path/to/equirect.jpg
EOF
fi
