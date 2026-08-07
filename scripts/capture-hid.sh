#!/bin/bash
# Captures the companion's (03f0:0580) HID traffic during Monado startup,
# once per video mode, in order to diff the activation sequence.
#
# The companion is 'hid_control_dev' in Monado's WMR driver (wmr_hmd.c:771): that's where
# the activation sequence (0x50 x4, 0x09, 0x08, 0x06) and the screen_enable go through. The
# 'Hololens Sensors' (045e:0659) is deliberately NOT captured: it spews IMU data at high
# frequency and would flood the file.
#
# RUN AS ROOT:  sudo ./scripts/capture-hid.sh
# Output: ~/vr/hid-mode{2,0,1}.txt  (usbmon text format, readable and diffable)

set -u

REAL_USER=${SUDO_USER:-iam}
VR=/home/$REAL_USER/vr
OUT=$VR

if [ "$(id -u)" -ne 0 ]; then
    echo "This script needs root: sudo $0" >&2
    exit 1
fi

# --- graphical environment ------------------------------------------------------------
# 'su - user' resets the environment and strips DISPLAY/XDG_SESSION_TYPE: jack-in.sh aborts
# with "Not in an X11 session" and Monado never starts (there would be nothing to capture).
# We pull it from the user's actual session process.
SESSION_PID=""
for proc in plasmashell kwin_x11 xfce4-session gnome-shell; do
    SESSION_PID=$(pgrep -u "$REAL_USER" -x "$proc" 2>/dev/null | head -1)
    [ -n "$SESSION_PID" ] && break
done
if [ -z "$SESSION_PID" ]; then
    echo "Could not find a graphical session process for $REAL_USER. Log in on X11 first." >&2
    exit 1
fi

mapfile -t USERENV < <(tr '\0' '\n' < "/proc/$SESSION_PID/environ" | grep -E \
    '^(DISPLAY|XAUTHORITY|XDG_SESSION_TYPE|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS|HOME|USER|PATH)=')

if ! printf '%s\n' "${USERENV[@]}" | grep -q '^XDG_SESSION_TYPE=x11'; then
    echo "$REAL_USER's session is not X11. jack-in.sh needs X11." >&2
    printf '%s\n' "${USERENV[@]}" >&2
    exit 1
fi
echo "environment taken from PID $SESSION_PID ($(printf '%s\n' "${USERENV[@]}" | grep ^DISPLAY=))"

# --- usbmon ---------------------------------------------------------------------------
modprobe usbmon || { echo "could not load usbmon" >&2; exit 1; }

BUS=$(lsusb | grep "03f0:0580" | sed -E 's/^Bus 0*([0-9]+).*/\1/' | head -1)
if [ -z "$BUS" ]; then
    echo "Companion 03f0:0580 is not present. Check the USB port (chapter 00)." >&2
    exit 1
fi
MON=/sys/kernel/debug/usb/usbmon/${BUS}u
[ -r "$MON" ] || { echo "cannot read $MON" >&2; exit 1; }
echo "companion on bus $BUS -> $MON"

kill_monado() {
    for p in $(pgrep -f "hello[_]xr"); do kill "$p" 2>/dev/null; done
    sleep 1
    for p in $(pgrep -f "monado[-]service"); do kill -9 "$p" 2>/dev/null; done
    sleep 3
    rm -f /run/user/1000/monado_comp_ipc
}

# mode 2 = 4320x2160@60 (the one that TURNS ON the panel) — this is the diff reference.
# mode 0 = 2880x1440@90 native (fails).  mode 1 = 4320x2160@90 (fails).
FAILED=0
for MODE in 2 0 1; do
    echo
    echo "=== capturing mode $MODE ==="
    kill_monado

    DEV=$(lsusb | grep "03f0:0580" | sed -E 's/^Bus [0-9]+ Device 0*([0-9]+).*/\1/' | head -1)
    echo "companion device address at startup: $DEV"

    # jack-in.log is overwritten on each startup; we delete it so we don't read the mode
    # from the previous run if jack-in were to fail.
    rm -f "$VR/jack-in.log"

    # stdbuf -o0: without this 'cat' block-buffers when writing to a file, and a small
    # capture gets lost entirely when we kill it.
    stdbuf -o0 cat "$MON" > "$OUT/hid-mode${MODE}.txt" &
    CATPID=$!
    sleep 1

    runuser -u "$REAL_USER" -- env "${USERENV[@]}" \
        XRT_COMPOSITOR_LOG=debug XRT_COMPOSITOR_DESIRED_MODE="$MODE" \
        bash -c "cd '$VR' && ./jack-in.sh 3dof" > "$OUT/jack-mode${MODE}.log" 2>&1

    # Let it run a bit: the second screen_enable from wmr_hmd.c:818 arrives late.
    sleep 8
    kill $CATPID 2>/dev/null
    wait $CATPID 2>/dev/null

    MODE_TAKEN=$(grep -E "found display mode" "$VR/jack-in.log" 2>/dev/null | tail -1)
    LINES=$(wc -l < "$OUT/hid-mode${MODE}.txt")

    if [ -z "$MODE_TAKEN" ]; then
        echo "  !! jack-in did NOT start Monado. Last lines:" >&2
        tail -4 "$OUT/jack-mode${MODE}.log" >&2
        FAILED=1
    else
        echo "  mode taken: $MODE_TAKEN"
    fi
    echo "  lines captured: $LINES"
    [ "$LINES" -eq 0 ] && { echo "  !! empty capture" >&2; FAILED=1; }

    { echo "$MODE_TAKEN"; echo "companion_device=$DEV"; echo "lines=$LINES"; } \
        > "$OUT/hid-mode${MODE}.meta"
done

kill_monado
chown "$REAL_USER":"$REAL_USER" "$OUT"/hid-mode*.txt "$OUT"/hid-mode*.meta "$OUT"/jack-mode*.log 2>/dev/null

echo
if [ "$FAILED" -eq 1 ]; then
    echo "=== FINISHED WITH PROBLEMS: check the messages above ==="
else
    echo "=== done ==="
fi
ls -l "$OUT"/hid-mode*.txt
