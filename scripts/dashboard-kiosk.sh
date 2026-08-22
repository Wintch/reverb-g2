#!/bin/bash
# Waits for the local status-dashboard server to respond, then opens it in
# Chrome kiosk mode. Run by hand first; see dashboard-kiosk.service's own
# header for the deliberate, not-auto-applied install step.
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
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --start-maximized \
    "$URL"
