#!/usr/bin/env bash
set -u

# Retry a VR launch until the complete headset USB census and DP checks pass.
# Usage:
#   ./scripts/retry-vr-after-preflight.sh -- <command> [args...]
# Optional:
#   VR_PREFLIGHT_INTERVAL=10   seconds between checks (default: 10)

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INTERVAL=${VR_PREFLIGHT_INTERVAL:-10}

if [ "$#" -lt 2 ] || [ "$1" != "--" ]; then
    echo "usage: $0 -- <command> [args...]" >&2
    exit 2
fi
shift

attempt=0
while :; do
    attempt=$((attempt + 1))
    echo "[vr-retry] preflight attempt $attempt" >&2
    if "$HERE/preflight.sh"; then
        echo "[vr-retry] preflight passed; launching command" >&2
        exec "$@"
    fi
    echo "[vr-retry] headset is not ready; retrying in ${INTERVAL}s" >&2
    sleep "$INTERVAL"
done
