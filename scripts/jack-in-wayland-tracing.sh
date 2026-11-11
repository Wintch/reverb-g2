#!/usr/bin/env bash
# jack-in-wayland-tracing.sh -- jack-in-wayland.sh, but launching the Tracy-instrumented
# monado-service-tracing build (docs/50). Same arguments as jack-in-wayland.sh.
# It differs from production in exactly three things, all set through the default-off hooks
# in jack-in-wayland.sh: the service binary, a separate log file, and the pgrep comm name
# (comm is truncated to 15 bytes, so monado-service-tracing reports "monado-service-").
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${VR_BASE:-}" ]; then VR="$VR_BASE"
else
    VR="$(cd "$HERE/../.." && pwd)"
    [ -x "$VR/monado-service-tracing" ] || VR="$HOME/vr"
fi
export JACK_IN_SERVICE="$VR/monado-service-tracing"
export JACK_IN_LOG="$VR/jack-in-wayland-tracing.log"
export JACK_IN_SERVICE_COMM="monado-service-"
exec "$HERE/jack-in-wayland.sh" "$@"
