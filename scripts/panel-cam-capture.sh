#!/bin/bash
# panel-cam-capture.sh - grab a timestamped frame sequence from a webcam pointed at the
# headset panel, for offline pattern analysis (see panel-cam-analyze.py).
#
# The camera has no focus at the distance it's mounted at - frames will not be legible
# photos. That is fine: the goal is only coarse brightness/color pattern detection
# (backlight on/off, color shifts), meant to be cross-checked against panel-status.py's HID
# DEVICE_STATUS timeline - the same "two independent confirmation channels" approach already
# used for the vblank experiment, see docs/16-lab-vblank.md.
#
#   ./scripts/panel-cam-capture.sh [seconds] [device] [fps]
#
# Output: experiments/webcam/<timestamp>/frame_NNNNN.jpg + meta.json (start epoch, fps,
# device) so panel-cam-analyze.py can reconstruct each frame's wall-clock offset and line it
# up against panel-status.py's log from the same run.

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECS="${1:-30}"
DEVICE="${2:-/dev/video0}"
FPS="${3:-10}"

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg not found" >&2; exit 1; }
[ -c "$DEVICE" ] || { echo "no such device: $DEVICE" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$REPO/experiments/webcam/$STAMP"
mkdir -p "$OUT"

START_EPOCH="$(date +%s.%N)"
echo "Capturing ${SECS}s @ ${FPS}fps from $DEVICE -> $OUT"
ffmpeg -hide_banner -loglevel error \
	-f v4l2 -input_format mjpeg -video_size 640x480 -framerate "$FPS" -i "$DEVICE" \
	-t "$SECS" -q:v 3 "$OUT/frame_%05d.jpg"

N="$(ls "$OUT"/frame_*.jpg 2>/dev/null | wc -l)"
cat > "$OUT/meta.json" <<EOF
{"start_epoch": $START_EPOCH, "fps": $FPS, "device": "$DEVICE", "frames": $N, "seconds_requested": $SECS}
EOF

echo "Captured $N frames."
echo "Analyze with: ./scripts/panel-cam-analyze.py $OUT"
