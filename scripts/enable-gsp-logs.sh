#!/bin/bash
# Enables GSP firmware logs in dmesg. This GPU (GA104) runs most of the resource manager
# logic in that firmware, not in the open module -- that's why the nvidia_modeset.debug
# parameter (used before) is capped at 7 lines: the interesting logic happens in a
# microcontroller inside the GPU, not in the Linux kernel.
#
# NVreg_EnableGpuFirmwareLogs makes THAT firmware send its logs to the host. By default,
# in a release build, it is disabled (nv-reg.h: it only activates if the driver is a
# DEBUG/DEVELOP build). It has to be forced with value 1.
#
#   sudo ./scripts/enable-gsp-logs.sh
#   sudo ./scripts/enable-gsp-logs.sh --revert
#
# REQUIRES A REBOOT. The parameter belongs to the "nvidia" (core) module, which loads
# before nvidia-modeset and nvidia-drm -- it cannot be enabled live like the modeset debug.

set -eu
[ "$(id -u)" -eq 0 ] || { echo "needs root: sudo $0" >&2; exit 1; }

CONF=/etc/modprobe.d/99-nvidia-gsp-logs.conf

if [ "${1:-}" = "--revert" ]; then
    rm -f "$CONF"
    echo "reverted: $CONF removed. REBOOT for it to take effect."
    exit 0
fi

cat > "$CONF" <<'EOF'
# GSP firmware logs to dmesg -- see scripts/enable-gsp-logs.sh and docs/13-bug-6bpc.md
options nvidia NVreg_EnableGpuFirmwareLogs=1
EOF

echo "written: $CONF"
cat "$CONF"
echo
update-initramfs -u -k "$(uname -r)" 2>&1 | tail -5 || true
echo
echo "DONE. YOU MUST REBOOT (the parameter belongs to the 'nvidia' core module, read at load time)."
echo "After the reboot: sudo /home/iam/Documents/reverb-g2/scripts/collect-nv.sh"
echo "and look in dmesg-*.txt for anything new (RPC, GSP, DPU, link training, etc)."
