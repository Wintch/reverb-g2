#!/bin/bash
# One-shot fix for docs/73-nvidia-symlink-drift.md: reinstalls the NVIDIA-owned packages
# found missing symlinks on disk (dpkg still lists them, but the files are gone), then
# re-runs the same dpkg -V check pre-update-check.sh now uses to confirm it's clean.
#
#   sudo ./scripts/fix-nvidia-symlink-drift.sh

set -u

if [ "$(id -u)" != "0" ]; then
    echo "Run this with sudo: sudo $0" >&2
    exit 1
fi

echo "=== reinstalling xserver-xorg-video-nvidia (Xorg GLX symlink) ==="
apt-get install --reinstall -y xserver-xorg-video-nvidia

echo
echo "=== reinstalling libnvcuvid1, libcuda1, nvidia-vdpau-driver (NVDEC/VDPAU/CUDA symlinks) ==="
apt-get install --reinstall -y libnvcuvid1 libcuda1 nvidia-vdpau-driver

echo
echo "=== verifying: dpkg -V, non-conffile drift only ==="
DRIFT=$(dpkg -V 2>&1 | grep -v '^..5?????? c ' | grep -v '^????????? c ')
if [ -z "$DRIFT" ]; then
    echo "OK: no drift left. All four symlinks restored."
else
    echo "$DRIFT"
    echo
    echo "!! Still drift left after reinstalling the known packages -- find the owner with"
    echo "   'dpkg -S <path>' and reinstall that one too. See docs/73-nvidia-symlink-drift.md."
    exit 1
fi

echo
echo "=== confirming the GLX symlink specifically ==="
ls -la /usr/lib/xorg/modules/extensions/libglxserver_nvidia.so 2>&1

echo
echo "Done. If a Plasma X11 session is still up from before this fix, it won't pick up the"
echo "restored GLX module until Xorg itself restarts (not just the session) -- see"
echo "docs/73-nvidia-symlink-drift.md, 'Fix', for why. Restart sddm to be sure:"
echo "  sudo systemctl restart sddm"
echo "(this kills every session sddm manages on every VT/seat, not just X11 -- confirm first"
echo "if anything else is running on another tty)."
