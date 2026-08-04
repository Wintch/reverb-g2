#!/bin/bash
# jack-in.sh - bring up the Reverb G2 VR pipeline in one shot.
#
# Requires an X11 session (not Wayland) - the NVIDIA direct-mode compositor
# path needs it. Log into "Plasma (X11)" from the SDDM session picker first.

set -u

MONADO_BUILD="$HOME/Documents/linux_vr_base/monado/build"
BASALT_LIB="$HOME/Documents/linux_vr_base/basalt/build/libbasalt.so"
SERVICE="$MONADO_BUILD/src/xrt/targets/service/monado-service"
LOG="$HOME/Documents/linux_vr_base/jack-in.log"
SOCKET="/run/user/$(id -u)/monado_comp_ipc"

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
COMMON_ENV=(
	VIT_SYSTEM_LIBRARY_PATH="$BASALT_LIB"
	XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="HP Inc."
	XRT_COMPOSITOR_DESIRED_MODE=2
	XRT_NO_STDIN=1
	WMR_DISPLAY_INIT_SLEEP_SECONDS=2
)

dp0_status() { xrandr --query 2>/dev/null | awk '/^DP-0/{print $2}'; }
service_pids() { pgrep -f "targets/service/monado-service"; }

# Turning DP-0 off forces a CRTC reconfiguration, and the NVIDIA driver silently drops DP-3's
# rotation transform when that happens (xrandr still REPORTS "right", but the panel shows
# landscape). Re-assert the full desktop layout so the portrait monitor stays portrait.
# Toggling rotation off first is what actually forces the driver to reprogram the CRTC.
# This is also needed after Monado acquires the display, not just after `--off`.
reassert_monitors() {
	xrandr --output DP-3 --rotate normal 2>/dev/null
	sleep 1
	xrandr --output HDMI-1 --mode 1920x1080 --pos 0x0 --rotate normal \
	       --output DP-3   --mode 1920x1080 --pos 1920x0 --rotate right --primary \
	       --output HDMI-0 --mode 1920x1080 --pos 3000x0 --rotate normal 2>/dev/null
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
	env "${COMMON_ENV[@]}" "$@" \
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
	start_service WMR_SLAM=0 WMR_CAMERAS=0 || return 1

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
if [ "${1:-}" = "3dof" ]; then
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

echo "Freeing the headset's display from the desktop (DP-0)..."
xrandr --output DP-0 --off
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

echo "Starting Monado (log: $LOG)..."
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
