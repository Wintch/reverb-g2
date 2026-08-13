#!/bin/bash
# controller-watch.sh - live, flat-monitor readout of where the controllers are and which way
# they point. Run it in a terminal next to you; no headset needed to read it.
#
#   ./controller-watch.sh              follow the running player's output
#   ./controller-watch.sh <logfile>    follow a specific log
#
# Written 2026-08-12 (T163). "The left controller points at me" is a claim about a direction,
# and judging directions by eye through a headset -- taking it off to talk, putting it back on
# to check the next build -- is slow and hard to compare between runs. This turns it into two
# numbers per hand that can be read, quoted and diffed.
#
# WHAT THE NUMBERS MEAN. fwd is the controller's forward axis (-Z in OpenXR) expressed in the
# reference space, so:
#
#   fz around -1   pointing away from you        <- what a hand held out normally should read
#   fz around +1   pointing back at you
#   fx around +-1  pointing sideways
#   fy around +-1  pointing up or down
#
# Both hands held parallel and pointing forward should read nearly the SAME vector. They are
# what tells a real orientation bug from a comfortable-looking coincidence: a mirrored error
# puts one hand at -Z and the other at +Z while both feel natural to hold.

set -u

LOG="${1:-}"
if [ -z "$LOG" ]; then
	# The player writes wherever it was launched from; find the newest log that actually has
	# POSE lines in it rather than guessing at a path.
	LOG="$(grep -l "POSE head" /tmp/claude-*/*/*/scratchpad/*.log ~/vr/*.log 2>/dev/null |
	       xargs -r ls -t 2>/dev/null | head -1)"
fi

if [ -z "$LOG" ] || [ ! -f "$LOG" ]; then
	echo "no player log with POSE lines found -- is the player running?" >&2
	echo "usage: $0 [logfile]" >&2
	exit 1
fi

echo "watching: $LOG"
echo
printf '%-10s | %-34s | %-34s\n' "" "LEFT" "RIGHT"
printf '%-10s-+-%-34s-+-%-34s\n' "----------" "----------------------------------" "----------------------------------"

stdbuf -oL tail -n0 -F "$LOG" 2>/dev/null | while IFS= read -r line; do
	case "$line" in
		*"POSE head"*) ;;
		*) continue ;;
	esac
	# Pull the two fwd(...)=LABEL groups and the two trk: flags, in order.
	dirs="$(printf '%s\n' "$line" | grep -o 'fwd([^)]*)=[A-Z-]*')"
	trks="$(printf '%s\n' "$line" | grep -o 'trk:[A-Z-]*')"
	l_dir="$(printf '%s\n' "$dirs" | sed -n 1p)"
	r_dir="$(printf '%s\n' "$dirs" | sed -n 2p)"
	l_trk="$(printf '%s\n' "$trks" | sed -n 1p)"
	r_trk="$(printf '%s\n' "$trks" | sed -n 2p)"
	[ -z "$l_dir" ] && continue
	printf '%-10s | %-24s %-9s | %-24s %-9s\n' \
	       "$(date '+%H:%M:%S')" "${l_dir#fwd}" "$l_trk" "${r_dir#fwd}" "$r_trk"
done
