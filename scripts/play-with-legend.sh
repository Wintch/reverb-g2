#!/bin/bash
# play-with-legend.sh - shows the current controls legend first, then plays the real
# content. Temporary measure (2026-08-09) while there's no in-headset text rendering (see
# docs/02-player-360.md) - the "legend" is just a static image with the control list baked
# in as pixels, shown via the player's existing photo mode.
#
#   ./play-with-legend.sh video.mp4
#   ./play-with-legend.sh folder/
#   ./play-with-legend.sh -t 60 video.mp4     any play360.sh flag works, passed straight through
#
# The legend has no time limit. Press any button except Menu (HELLO_XR_ANY_KEY_QUITS=1,
# only for this phase) to move on once you've read it, or hold Menu ~1.5s like always to
# quit instead of starting the content. Otherwise this is just play360.sh called twice.
#
# CONTROLS_IMG=/path/to/other.png overrides which image to show first.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAY360="$SCRIPT_DIR/play360.sh"
CONTROLS_IMG="${CONTROLS_IMG:-$HOME/vr/media/controles.png}"

if [ $# -lt 1 ]; then
	echo "usage: $0 [play360.sh flags] <file-or-folder>" >&2
	exit 1
fi

if [ ! -x "$PLAY360" ]; then
	echo "no encuentro play360.sh en $SCRIPT_DIR" >&2
	exit 1
fi

if [ ! -f "$CONTROLS_IMG" ]; then
	echo "no encuentro la imagen de controles: $CONTROLS_IMG (CONTROLS_IMG=... para otra)" >&2
	exit 1
fi

echo "Showing the controls legend - press any button (except Menu) to jump straight to the content, or hold Menu ~1.5s like always to quit instead."
# ANY_KEY_QUITS=1 only for this legend phase - unset (not just =0) for the real exec below so
# it never leaks into actual playback, where every button needs its normal job back.
HELLO_XR_ANY_KEY_QUITS=1 "$PLAY360" -s -p flat -w 55 "$CONTROLS_IMG"

echo "Starting..."
exec env -u HELLO_XR_ANY_KEY_QUITS "$PLAY360" "$@"
