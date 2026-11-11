#!/bin/bash
# Waits for the local status-dashboard server to respond, then opens it in a
# normal (non-kiosk) Chrome window. Run by hand first; see
# dashboard-kiosk.service's own header for the deliberate, not-auto-applied
# install step.
#
# Deliberately NOT --kiosk (2026-08-21): the user found Moonlight couldn't
# inject mouse/keyboard input at all while Chrome was in kiosk mode --
# unconfirmed root cause, but kiosk mode is suspected of grabbing input in a
# way that interferes with Moonlight's synthetic events. A normal maximized
# window avoids that without giving up "shows the dashboard full-screen at
# a glance" -- and leaves the desktop reachable if input needs recovering.
set -u

URL="http://127.0.0.1:8765/"
TRIES=30

for i in $(seq 1 "$TRIES"); do
    if curl -sf -o /dev/null "$URL"; then
        break
    fi
    sleep 1
done

exec /usr/bin/google-chrome \
    --new-window \
    --no-first-run \
    --start-maximized \
    "$URL"
