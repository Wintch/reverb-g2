#!/bin/bash
# test-powermizer-90hz.sh - retest native 90Hz with the GPU forced out of adaptive clocking.
#
# Windows VR guidance always recommends forcing "Prefer Maximum Performance" in the NVIDIA
# control panel; Linux's 595-open also defaults to adaptive PowerMizer (dynamic clocks). If
# the closed GSP firmware's 90Hz handshake is clock-state-sensitive, an inopportune downclock
# mid-modeset could look identical to a hard link failure. Not yet tested before this script -
# see docs/16-lab-vblank.md for the vblank factorial this is a follow-up to.
#
# No reboot needed: this only flips a live GPU clock policy and re-requests one of the
# ALREADY-BUILT native modes via hmd-vk (see scripts/hmd-test.sh) - no EDID override involved,
# so there is no kernel module config to reload.
#
#   ./scripts/test-powermizer-90hz.sh [seconds-per-mode]
#
# Tests native mode 0 (2880x1440@90, the panel's actual advertised resolution - what Windows
# drives) first, then mode 1 (4320x2160@90, Monado's supersampled variant) for comparison.
# Restores the original PowerMizer mode on exit regardless of outcome.
#
# Verdict is automated (hmd-test.sh's HID backlight-byte detector), same caveat as always:
# it is solid but not infallible - if either mode reports ANDA, confirm physically before
# trusting it, since the API/driver can report success with a dark panel.

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
SECS="${1:-18}"

if [ "${XDG_SESSION_TYPE:-}" != "x11" ]; then
	echo "Not in an X11 session (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset})." >&2
	echo "Log out and pick 'Plasma (X11)' at the SDDM login screen first." >&2
	exit 1
fi

command -v nvidia-settings >/dev/null 2>&1 || { echo "nvidia-settings not found" >&2; exit 1; }

BIN="$(ls -t "$REPO"/nv-report-*/build/hmd-vk 2>/dev/null | head -1)"
[ -x "$BIN" ] || { echo "hmd-vk not built - see docs/16-lab-vblank.md" >&2; exit 1; }

ORIG_MODE="$(nvidia-settings -q '[gpu:0]/GPUPowerMizerMode' -t 2>/dev/null | tail -1)"
if [ -z "$ORIG_MODE" ]; then
	echo "Could not read the current GPUPowerMizerMode." >&2
	echo "If nvidia-settings can't touch it at all, this GPU/driver combo may not expose it" >&2
	echo "without Coolbits - not expected for PowerMizer mode specifically, but worth knowing." >&2
	exit 1
fi
echo "Current PowerMizer mode: $ORIG_MODE (0=Adaptive, 1=Prefer Max Performance, 2=Auto)"

restore_powermizer() {
	echo "Restoring PowerMizer mode to $ORIG_MODE..."
	nvidia-settings -a "[gpu:0]/GPUPowerMizerMode=$ORIG_MODE" >/dev/null 2>&1
}
trap restore_powermizer EXIT

echo "Forcing Prefer Maximum Performance (GPUPowerMizerMode=1)..."
nvidia-settings -a '[gpu:0]/GPUPowerMizerMode=1' >/dev/null || {
	echo "Failed to set PowerMizer mode." >&2
	exit 1
}
sleep 2   # let the clock state actually settle before the modeset attempt

declare -a RESULTS=()
for ENTRY in "0:2880x1440@90 (native panel res, what Windows drives)" \
             "1:4320x2160@90 (Monado supersampled)"; do
	IDX="${ENTRY%%:*}"
	DESC="${ENTRY#*:}"
	echo
	echo "=== testing mode $IDX - $DESC ==="
	TID="$(./scripts/testlog.py open "powermizer-max + native $IDX" "$DESC")"
	if ./scripts/hmd-test.sh "$IDX" "$SECS"; then
		VERDICT="ANDA (backlight on)"
	else
		VERDICT="FALLA (no backlight / no DEVICE_STATUS)"
	fi
	./scripts/testlog.py close "$TID" "$VERDICT - automated via hmd-test.sh under GPUPowerMizerMode=1"
	RESULTS+=("$TID  mode=$IDX  $VERDICT")
done

echo
echo "=== summary ==="
printf '%s\n' "${RESULTS[@]}"
echo
echo "If either mode shows ANDA: put the headset on and confirm physically before trusting it."
