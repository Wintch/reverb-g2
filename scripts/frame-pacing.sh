#!/bin/bash
# frame-pacing.sh - measure dropped/late frames over a window, while a title is running.
#
#   ./frame-pacing.sh            measure for 30 s
#   ./frame-pacing.sh 60         measure for 60 s
#
# WHY THIS EXISTS (2026-08-12, T161). A frame that misses its slot makes the compositor
# re-show the previous one, so the view snaps back to the old pose for a beat. In VR that
# is felt long before it is seen: the user reported it as a "microajuste" when turning the
# head, and as mildly nauseating, while the on-screen counter still read 89-90 fps. The
# framerate number does not capture it -- this does. Per the user's instruction, every
# title gets measured, not just the ones that already feel wrong.
#
# WHAT THE NUMBERS MEAN. The interesting figure is the MEDIAN lateness. If it lands on one
# full frame period (11.11 ms at 90 Hz) the frames are not "a bit late", they are missing
# their slot entirely and being shown one refresh later -- that is the artefact above. A
# median well below one period is jitter, which is a different (and milder) problem.
#
# WARM-UP TRAP, learned the hard way on Aircar the same day: the first minute of a Proton
# title measures DXVK shader compilation and asset streaming, not steady state. The same
# session read 3.44% late frames early and 0.13% once warm, with nothing changed in
# between. Let the title settle before believing a number, and say so when reporting one.
#
# Requires the pacing instrumentation, which jack-in-wayland.sh turns on by default
# (VR_PACING=1). This script checks for it rather than silently reporting zero.

set -u

WINDOW="${1:-30}"
case "$WINDOW" in
    ''|*[!0-9]*) echo "usage: $0 [seconds]" >&2; exit 1 ;;
esac

VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -d "$HOME/vr" ] && VR="$HOME/vr"
LOG="$VR/jack-in-wayland.log"

[ -r "$LOG" ] || { echo "No log at $LOG -- has the stack ever been started?" >&2; exit 1; }

MPID="$(pgrep -f "targets/service/monado-service" | head -1)"
if [ -z "$MPID" ]; then
    echo "monado-service is not running. Start the stack first (./jack-in-wayland.sh)." >&2
    exit 1
fi

# Verify the instrumentation is actually in the running process, not merely intended.
# Without it the counters below are all zero and would read as a perfect result.
if ! tr '\0' '\n' < "/proc/$MPID/environ" 2>/dev/null | grep -q "^XRT_APP_FRAME_LAG_LOG_AS_LEVEL="; then
    echo "WARNING: frame-lag logging is NOT enabled in the running monado-service." >&2
    echo "         A zero result here would be meaningless. Restart the stack with" >&2
    echo "         VR_PACING=1 (the default) and measure again." >&2
    exit 2
fi

# Refresh rate from the log rather than assumed -- this rig runs 90 Hz but jack-in-wayland.sh
# takes a mode argument, and mode 2 is 60 Hz.
HZ="$(grep -oE "found display mode [0-9]+x[0-9]+@[0-9.]+" "$LOG" | tail -1 | sed -E 's/.*@//')"
[ -n "$HZ" ] || HZ=90
PERIOD_MS="$(awk -v hz="$HZ" 'BEGIN{printf "%.2f", 1000/hz}')"

echo "Measuring for ${WINDOW}s at ${HZ} Hz (one frame = ${PERIOD_MS} ms)..."
echo "Play normally, and include the movement that provokes it -- head turns show it best."

BEFORE="$(grep -c "Frame late by" "$LOG" 2>/dev/null || echo 0)"
START="$(date +%s)"
sleep "$WINDOW"
AFTER="$(grep -c "Frame late by" "$LOG" 2>/dev/null || echo 0)"
ELAPSED="$(( $(date +%s) - START ))"
[ "$ELAPSED" -gt 0 ] || ELAPSED=1

LATE="$(( AFTER - BEFORE ))"

# Distribution over the frames observed in THIS window only: take the last $LATE entries.
DIST="$(grep -oE "late by [0-9.]+ms" "$LOG" | tail -n "$((LATE > 0 ? LATE : 1))" \
        | awk '{gsub(/ms/,"",$3); print $3}' | sort -n)"

echo
awk -v late="$LATE" -v el="$ELAPSED" -v hz="$HZ" -v per="$PERIOD_MS" '
BEGIN { split("", v) }
{ v[++n] = $1 }
END {
    expected = el * hz
    printf "  window          %d s\n", el
    printf "  late frames     %d\n", late
    printf "  rate            %.2f /s\n", late / el
    printf "  share           %.2f %% of %d expected frames\n", (late / expected) * 100, expected
    if (n > 0) {
        med = v[int(n/2) + 1]
        printf "  lateness        min %.2f  median %.2f  max %.2f ms\n", v[1], med, v[n]
        if (med >= per * 0.9)
            printf "  -> median is ~one full frame: frames are MISSING their slot, not merely jittering.\n"
        else
            printf "  -> median is well under one frame (%.2f ms): jitter rather than dropped slots.\n", per
    }
    print ""
    if (late / expected > 0.01)
        print "  VERDICT: above 1% -- expect it to be felt. Check whether the title is still warming up."
    else if (late > 0)
        print "  VERDICT: under 1% -- normally imperceptible."
    else
        print "  VERDICT: no late frames in this window."
}' <<< "$DIST"
