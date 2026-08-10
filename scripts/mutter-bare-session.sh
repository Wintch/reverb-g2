#!/bin/bash
# mutter-bare-session.sh -- the whole graphical session, no gnome-shell UI at
# all: just `mutter --wayland --no-x11 --display-server`. Tests the parked
# idea (docs, 2026-08-10) that mutter itself implements the DRM-lease
# protocol and gnome-shell is a UI layer on top, not a separate backend --
# so a bare mutter session might keep offering the G2's connector for lease
# while shedding gnome-shell's own weight.
#
# Installed as an ADDITIONAL SDDM session entry, alongside "GNOME on
# Wayland" -- never replaces it. If this doesn't work, just pick "GNOME on
# Wayland" again at the next login; nothing here touches that path.
#
# Launched only through SDDM (a real login, real logind session --
# confirmed live 2026-08-10 that mutter's native/KMS backend refuses to run
# at all otherwise: "Failed to setup: Native backend mode needs to be
# session controller" when tried via a bare systemd-run --scope). Don't try
# to invoke this script directly from a non-login shell; it will fail the
# same way.
set -u
LOG="/tmp/mutter-bare-session-$$.log"
: > "$LOG"
echo "mutter-bare-session: starting, log at $LOG" >> "$LOG"

mutter --wayland --no-x11 --display-server >>"$LOG" 2>&1 &
MUTTER_PID=$!

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
for _i in $(seq 1 20); do
    [ -S "$RUNTIME_DIR/wayland-0" ] && break
    sleep 0.5
done

{
    echo
    echo "=== check-lease.sh, run from inside the bare mutter session ==="
    if [ -x /home/iam/vr/check-lease.sh ]; then
        /home/iam/vr/check-lease.sh
    else
        /home/iam/Documents/reverb-g2/scripts/check-lease.sh
    fi
} >>"$LOG" 2>&1

# Keep the session alive as long as mutter itself is alive -- SDDM/logind
# end the whole session the moment this script's process tree exits.
wait "$MUTTER_PID"
echo "mutter-bare-session: mutter exited, session ending" >> "$LOG"
