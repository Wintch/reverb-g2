#!/bin/bash
# Starts Monado in a WAYLAND session using DRM lease, instead of NVIDIA Direct-Mode
# from X11. This is the path by which Project-VR reports the G2 running at 4320x2160@90.
#
#   ./jack-in-wayland.sh [mode]     mode: 0 = 2880x1440@90
#                                         1 = 4320x2160@90  (the one Project-VR uses)
#                                         2 = 4320x2160@60  (the only one that works today in X11)
#
# Why this is MUCH simpler than jack-in.sh: in X11 you have to fight X for the display
# (free DP-0, cycle the CRTC, restore the portrait rotation). With DRM lease the
# Wayland compositor never takes the HMD -- it sees it marked as non-desktop and leaves it
# leasable. No desktop monitor is touched.

set -u

MODE="${1:-1}"
# "3dof" is jack-in.sh's syntax, not this script's — and atoi("3dof")=3 silently requested a
# nonexistent mode (happened on 2026-08-06). Here the argument is ONLY the mode index.
case "$MODE" in
    0|1|2) ;;
    *) echo "invalid mode: '$MODE' (0 = 2880x1440@90, 1 = 4320x2160@90, 2 = 4320x2160@60)" >&2; exit 1 ;;
esac
VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$HOME/vr/monado" ] && VR="$HOME/vr"
SERVICE="$VR/monado/build/src/xrt/targets/service/monado-service"
LOG="$VR/jack-in-wayland.log"
SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/monado_comp_ipc"

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

echo "Starting Monado (mode $MODE) via DRM lease... log: $LOG"

# Keep the previous run's log. Truncating on every start destroyed the one log that could
# have proven why tracking froze mid-session on 2026-08-07 (T045): a later service start
# wiped the evidence. One generation back is enough for the "what did the LAST session say"
# question, without unbounded growth.
[ -f "$LOG" ] && cp -f "$LOG" "${LOG%.log}.prev.log"

# WMR_DISPLAY_INIT_SLEEP_SECONDS=2 is load-bearing just like in X11: the panel turns off
# on its own after ~3s if it doesn't receive a video signal, and with the default 4s Monado wakes up
# when it has already turned off.
#
# XRT_NO_STDIN=1 is also mandatory: without it Monado registers stdin in epoll and, launched
# in the background, dies with 'epoll_ctl(stdin) failed' -> IPC_MAINLOOP_FAILED_TO_INIT before
# even reaching the compositor. setsid + stdbuf -oL keep the log alive (using
# `script` to give it a pty buffers so much that failures become unreadable).
env XRT_COMPOSITOR_FORCE_WAYLAND_DIRECT=1 \
    XRT_COMPOSITOR_DESIRED_MODE="$MODE" \
    XRT_COMPOSITOR_LOG=debug \
    XRT_NO_STDIN=1 \
    WMR_SLAM=0 WMR_CAMERAS=0 \
    WMR_DISPLAY_INIT_SLEEP_SECONDS=2 \
    setsid stdbuf -oL -eL "$SERVICE" < /dev/null > "$LOG" 2>&1 &

SVC=$!
for _i in $(seq 1 30); do
    [ -S "$SOCKET" ] && break
    kill -0 "$SVC" 2>/dev/null || break
    sleep 1
done

# The socket appears BEFORE the compositor finishes logging the backend and the mode,
# so grepping as soon as we see it comes back empty and looks like a failure. We wait for the marker.
for _i in $(seq 1 20); do
    grep -q "found display mode" "$LOG" && break
    sleep 1
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
MODE_OK=0
if [ -n "$OUT" ]; then
    echo "$OUT"
    MODE_OK=1
else
    echo "  (no mode found -- the HMD may not be leasable)"
fi

echo
# A socket existing is NOT enough: the IPC server binds it before it tries to init the
# compositor, so a failed lease (no connector, no mode) still leaves a live process with a
# live socket -- any OpenXR app launched against it fails later with XRT_ERROR_RUNTIME_FAILURE
# on xrGetSystem, and the broken service just sits there until something kills it (found the
# hard way on 2026-08-07: had to manually pkill a service that had been "Socket ready" for
# several failed launches in a row). Require BOTH the socket and a real mode; otherwise kill
# the broken instance ourselves instead of reporting a false success.
if [ "$MODE_OK" = 1 ] && [ -S "$SOCKET" ]; then
    echo "Socket ready. Launch an OpenXR app with:"
    echo "  XR_RUNTIME_JSON=$VR/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 <app> --graphics Vulkan2"
else
    echo "!! No usable compositor (no leasable connector / no mode found) -- not leaving a broken service running." >&2
    echo "!! Last lines of the log:" >&2
    tail -15 "$LOG" >&2
    for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
    rm -f "$SOCKET"
    exit 1
fi
