#!/bin/bash
# Print the DRM connector the HP Reverb G2 panel is on (e.g. "card0-DP-3"), found by
# EDID fingerprint so nothing has to hardcode a port. The panel moved DP-1 -> DP-3
# after the 2026-09-03 GPU swap and could move again; jack-in-wayland.sh already
# autodetects the HMD, this gives the diagnostic scripts the same independence
# (verify-bpc, verify-override, collect-nv, status-dashboard).
#
# Fingerprint = EDID bytes 8..11 == "22 0e c1 36" (manufacturer HPN + product 0x36c1).
# That is the G2 DISPLAY MODEL's id, identical on every G2 unit -- NOT rig-specific,
# and it deliberately never reads the per-unit serial (bytes 12..15, see docs/91).
# /sys/class/drm/*/edid is world-readable, so no root/sudo is needed.
#
# Prints the connector and exits 0 on a match; prints nothing and exits 1 when the
# panel is asleep / the HMD is down (the caller decides its own fallback).
set -u

G2_FP="220ec136"

for e in /sys/class/drm/card*-*/edid; do
    [ -e "$e" ] || continue
    fp="$(od -An -tx1 -j8 -N4 "$e" 2>/dev/null | tr -d ' \n')"
    [ "$fp" = "$G2_FP" ] && { basename "$(dirname "$e")"; exit 0; }
done
exit 1
