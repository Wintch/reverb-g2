#!/bin/bash
# apply-bpc-patch.sh - RETIRED 2026-10-12 (code review, docs/147 §4 #8).
#
# It edited patch 0004 straight into NVIDIA's DKMS source tree and rebuilt the module.
# `bootstrap-lab.sh patch-nv` already lists 0004 in dkms.conf's PATCH[] together with
# 0001-0003, so on a box set up that way the direct edit applied 0004 twice and broke the
# DKMS build. One path is enough:
#
#   ./scripts/bootstrap-lab.sh patch-nv     apply 0001-0004 through PATCH[] and rebuild
#
# To undo 0004 only: delete its PATCH[] line from /usr/src/nvidia-<ver>/dkms.conf, then
# `dkms build nvidia/<ver> --force && dkms install nvidia/<ver> --force` and reboot.
# The last working version of this script is in git history (`git log -- scripts/apply-bpc-patch.sh`).
#
# The file stays (and exits non-zero) because the lab sudoers allowlist and older notes
# name this path; remove it from linuxlab-kit/sudoers/reverb-g2-agent.sudoers.

echo "apply-bpc-patch.sh is retired: use ./scripts/bootstrap-lab.sh patch-nv (see the header of $0)." >&2
exit 1
