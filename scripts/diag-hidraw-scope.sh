#!/bin/bash
# diag-hidraw-scope.sh -- ad-hoc diagnostic, 2026-08-10: jack-in-under-bare-mutter.sh
# failed with EACCES (-13) opening /dev/hidraw2 (HoloLens Sensors, confirmed via
# udevadm) even though `id iam` shows plugdev membership and the device is
# crw-rw-r-- root:plugdev with no ACL entries (getfacl showed none). Checking
# whether systemd-run --scope --uid=iam actually resolves that group membership
# right now, live, instead of guessing.
set -u
LOG=/tmp/diag-hidraw-scope.log
exec > >(tee "$LOG") 2>&1

echo "=== who is this shell, really? (root's own groups right now) ==="
id

echo
echo "=== groups via --scope --uid=iam (the broken one: got just 'root' before) ==="
systemd-run --quiet --scope --uid=iam -- id

echo
echo "=== groups via --scope --uid=iam --gid=iam (explicit primary gid) ==="
systemd-run --quiet --scope --uid=iam --gid=iam -- id

echo
echo "=== groups via a plain transient SERVICE, not --scope (goes through PID1's normal exec-context/initgroups) ==="
systemd-run --quiet --uid=iam -- id

echo
echo "=== groups via runuser (PAM-based, different codepath entirely) ==="
runuser -u iam -- id

echo
echo "=== can --scope read hidraw2 with explicit gid? ==="
systemd-run --quiet --scope --uid=iam --gid=iam -- timeout 2 head -c1 /dev/hidraw2 > /dev/null
echo "exit code: $?"

echo
echo "=== can a plain service read/write-probe hidraw2? ==="
systemd-run --quiet --uid=iam -- timeout 2 head -c1 /dev/hidraw2 > /dev/null
echo "exit code: $?"

echo
echo "log saved at $LOG"
