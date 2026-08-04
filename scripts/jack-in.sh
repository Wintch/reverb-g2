#!/bin/bash
# jack-in.sh - bring up the Reverb G2 VR pipeline in one shot.
#
# Requires an X11 session (not Wayland) - the NVIDIA direct-mode compositor
# path needs it. Log into "Plasma (X11)" from the SDDM session picker first.

set -u

MONADO_BUILD="$HOME/Documents/linux_vr_base/monado/build"
BASALT_LIB="$HOME/Documents/linux_vr_base/basalt/build/libbasalt.so"
LOG="$HOME/Documents/linux_vr_base/jack-in.log"

if [ "${XDG_SESSION_TYPE:-}" != "x11" ]; then
	echo "Not in an X11 session (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset})." >&2
	echo "Log out and pick 'Plasma (X11)' at the SDDM login screen, then re-run this." >&2
	exit 1
fi

if pgrep -f "monado/build/src/xrt/targets/service/monado-service" > /dev/null; then
	echo "Already running."
	exit 0
fi

echo "Freeing the headset's display from the desktop (DP-0)..."
xrandr --output DP-0 --off
sleep 8   # let X/NVIDIA fully release the CRTC before Vulkan tries to lease it - without this,
          # vkAcquireXlibDisplayEXT races and fails with VK_ERROR_UNKNOWN. 3s was not always enough.

# Turning DP-0 off forces a CRTC reconfiguration, and the NVIDIA driver silently drops DP-3's
# rotation transform when that happens (xrandr still REPORTS "right", but the panel shows
# landscape). Re-assert the full desktop layout so the portrait monitor stays portrait.
# Toggling rotation off first is what actually forces the driver to reprogram the CRTC.
echo "Re-asserting desktop monitor layout (DP-0 off drops DP-3's rotation)..."
xrandr --output DP-3 --rotate normal 2>/dev/null
sleep 1
xrandr --output HDMI-1 --mode 1920x1080 --pos 0x0 --rotate normal \
       --output DP-3   --mode 1920x1080 --pos 1920x0 --rotate right --primary \
       --output HDMI-0 --mode 1920x1080 --pos 3000x0 --rotate normal 2>/dev/null

rm -f "/run/user/$(id -u)/monado_comp_ipc"

# Tracking mode. SLAM (Basalt) gives 6DoF but on this rig it DIVERGES badly - measured ~3 deg mean
# and 20-30 deg max inter-frame rotation with the headset sitting motionless on a desk. IMU-only
# 3DoF measures ~0.0013 deg mean / 0.056 deg max, i.e. ~2000x more stable, at the cost of
# positional tracking. For orientation-only apps (360 photos/video, skyboxes) 3DoF is strictly
# better; real 6DoF apps still need SLAM despite the jitter.
#   ./jack-in.sh 3dof   -> IMU-only, rock steady, no position
#   ./jack-in.sh        -> SLAM/Basalt, 6DoF, currently jittery
if [ "${1:-}" = "3dof" ]; then
	echo "Tracking: IMU-only 3DoF (WMR_SLAM=0) - rotation only, very stable."
	SLAM_ENV="WMR_SLAM=0"
else
	echo "Tracking: SLAM/Basalt 6DoF (pass '3dof' for the rock-steady orientation-only mode)."
	SLAM_ENV="WMR_SLAM=1"
fi

# The headset's companion board (03f0:0580, "QHMD A85V") drops off the USB bus constantly - it
# carries the HID control interface and the audio function, and it is physically flaky (the same
# fault makes audio appear/disappear under Windows). If it is absent when the service starts,
# Monado silently falls back to the "legacy" builder and you get a Simulated HMD instead of the
# real headset. So poll for it here - AFTER the xrandr work above, not before, because it often
# drops during that several-second window - and start the service the moment it shows up.
echo "Waiting for the headset companion device (03f0:0580)..."
for _i in $(seq 1 30); do
	lsusb | grep -q "03f0:0580" && break
	sleep 2
done
if ! lsusb | grep -q "03f0:0580"; then
	echo "Companion device still missing after 60s - unplug and replug the headset USB, then retry." >&2
	echo "(Verify with: lsusb | grep 03f0:0580)" >&2
	exit 1
fi

# Turn the controllers on BEFORE this point if you want them: they are already paired to the
# headset over Bluetooth, but Monado only probes for them at startup, so ones powered on later
# show up as 'left/right: <none>' until the service is restarted.

echo "Starting Monado (log: $LOG)..."
cd "$MONADO_BUILD" || exit 1
# Mode 2 = 4320x2160@60. 60Hz is forced because of NVIDIA driver bug 5923212 (driver 550.163.01):
# at 90Hz the DP link never trains and the panel shows only its boot logo. Tested 2026-08-04 --
# BOTH 90Hz modes fail (idx 0 = 2880x1440@90 native, 428MHz pclk; idx 1 = 4320x2160@90, 905MHz),
# while idx 2 = 4320x2160@60 at 709MHz works. Since the 60Hz mode has a HIGHER pixel clock than
# the native 90Hz mode that fails, this is NOT a bandwidth limit - it is tied to the 90Hz refresh
# rate itself. The same headset does 90Hz fine under Windows, so the hardware/cable are capable.
# The API reports success and a happy 90.0 fps even when the panel is black - the failure is
# invisible above the driver, only observable physically in the headset.
# Cost of the workaround: visible 60Hz backlight-strobe flicker. Retry 90Hz after any NVIDIA
# driver upgrade (trixie ships only 550.163.01; needs backports or the official installer).
env VIT_SYSTEM_LIBRARY_PATH="$BASALT_LIB" \
XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="HP Inc." \
XRT_COMPOSITOR_DESIRED_MODE=2 \
XRT_NO_STDIN=1 \
$SLAM_ENV \
setsid script -qec "./src/xrt/targets/service/monado-service" "$LOG" < /dev/null > /dev/null 2>&1 &
disown

echo "Jacked in. Give it ~10s, then launch any OpenXR app with:"
echo "  XR_RUNTIME_JSON=$MONADO_BUILD/openxr_monado-dev.json <app> --graphics Vulkan2"
echo
echo "Note: hello_xr quits the instant stdin hits EOF, so keep stdin open, e.g.:"
echo "  sleep 120 | XR_RUNTIME_JSON=... hello_xr --graphics Vulkan2"
echo "For the 360 photo viewer, set HELLO_XR_PHOTO360=/path/to/equirect.jpg"
