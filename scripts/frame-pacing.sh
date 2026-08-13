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
# CONTROL THE WINDOW FOCUS, and say which state you measured in (user's catch, 2026-08-13).
# The title's desktop window being unfocused is not a neutral condition: Unreal throttles
# when it is not the foreground app, and the whole Proton/DXVK stack can follow. Two
# measurements taken minutes apart are not comparable unless both were taken in the same
# focus state, and nothing in this script detects it. Standard from here on: measure with
# the game window FOCUSED, and note it next to the number.
#
# WHAT THIS TOOL CANNOT SEE, and it bit on 2026-08-13 (T175): it counts frames that MISS
# THEIR SLOT. It is blind to LATENCY. Turning on pipelined app pacing took Aircar from
# 12.37% to 0.69-0.94% here -- a clean 13x by this measure -- while the wearer immediately
# saw a NEW artefact: a ghost/trail whose separation from the real image grows with how
# fast he turns his head, i.e. the frame was rendered against a pose predicted for a moment
# that had already passed. Both readings were correct; neither was sufficient. If a change
# improves this number, ask what it traded away and put the headset on somebody.
#
# WHAT THE NUMBERS MEAN. The interesting figure is the MEDIAN lateness. If it lands on one
# full frame period (11.11 ms at 90 Hz) the frames are not "a bit late", they are missing
# their slot entirely and being shown one refresh later -- that is the artefact above. A
# median well below one period is jitter, which is a different (and milder) problem.
#
# WARM-UP TRAP, and it is not a one-off -- confirmed on three independent titles the same
# day: Aircar 3.44% -> 0.13%, Emergence 2.56% -> 0.41%, VersaillesVR from a user-reported
# 2 fps to perfect. In every case the render scale and everything else were unchanged; it
# was DXVK finishing its shader compilation. The first minute of a Proton title measures
# warm-up, not steady state. Let the title settle before believing a number, and say so
# when reporting one.
#
# WHAT THE PERCENTAGES FEEL LIKE. The 1% threshold below is not an industry rule -- it is
# calibrated against this user's own reports on this hardware, which lined up with the
# measurements three times:
#
#   0.13 %   imperceptible          -- "casi perfecto"
#   2.56 %   noticeable, playable   -- "se nota que un poquito apenas se pierde, pero bien igual"
#   3.44 %   noticeable, unpleasant -- felt as a micro-snap on head turns, mildly nauseating
#
# Treat those as this rig's scale, not as universal numbers, and re-calibrate if the
# hardware or the user changes.
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
# With LATE=0 there is nothing from this window, and asking for `tail -1` would report a
# stale entry from an earlier run as if it belonged here -- a false reading in a tool whose
# whole job is to be trusted. Emit nothing instead.
if [ "$LATE" -gt 0 ]; then
    DIST="$(grep -oE "late by [0-9.]+ms" "$LOG" | tail -n "$LATE" \
            | awk '{gsub(/ms/,"",$3); print $3}' | sort -n)"
else
    DIST=""
fi

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

# --- record the measurement with the environment it was taken against ----------------
# A dropped-frame figure means nothing alone: it becomes evidence only when it can be
# compared against another measurement on a known-different driver, Monado build or render
# resolution. Appending here makes "did this change with the driver?" a query instead of an
# argument -- the 2026-08-09 kernel/DKMS boundary cost a whole session precisely because no
# such record existed and it had to be reconstructed from file timestamps.
RECORD="$VR/logs/frame-pacing.jsonl"
mkdir -p "$(dirname "$RECORD")"
TITLE="$(ps -eo args --no-headers 2>/dev/null | grep -oE "[^/\\]+\.exe" \
         | grep -viE "^(steam|services|explorer|winedevice|plugplay|svchost|rpcss|conhost|tabtip|iscriptevaluator|xalia)\.exe$" \
         | head -1)"
[ -n "$TITLE" ] || { pgrep -f "hello_xr" >/dev/null 2>&1 && TITLE="hello_xr"; }
[ -n "$TITLE" ] || TITLE="unknown"
RES="$(grep -oE "CREATE [^ ]+ [0-9]+x[0-9]+" "$LOG" | tail -1 | grep -oE "[0-9]+x[0-9]+")"

python3 - "$RECORD" "$TITLE" "$ELAPSED" "$LATE" "$HZ" "${RES:-unknown}" "$VR" <<'PY'
import json, sys, os, subprocess, datetime
rec, title, elapsed, late, hz, res, vr = sys.argv[1:8]
elapsed, late, hz = int(elapsed), int(late), float(hz)

def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:
        return None

expected = elapsed * hz
entry = {
    "when": datetime.datetime.now().isoformat(timespec="seconds"),
    "title": title,
    "window_s": elapsed,
    "late_frames": late,
    "rate_per_s": round(late / elapsed, 3),
    "share_pct": round(late / expected * 100, 3) if expected else None,
    "refresh_hz": hz,
    "render_per_eye": res,
    "kernel": os.uname().release,
    "nvidia": sh("sed -n '1p' /proc/driver/nvidia/version"),
    "monado_head": sh(f"git -C '{vr}/monado' log --oneline -1"),
    "monado_built": sh(f"stat -c %y '{vr}/monado/build/src/xrt/targets/service/monado-service' | cut -d. -f1"),
    "xrizer_built": sh(f"stat -c %y '{vr}/xrizer/target/release/libxrizer.so' | cut -d. -f1"),
    "proton": sh("cat '/home/iam/.steam/debian-installation/steamapps/common/Proton - Experimental/version'"),
}
with open(rec, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
print(f"\n  recorded -> {rec}   (title: {title})")
PY
