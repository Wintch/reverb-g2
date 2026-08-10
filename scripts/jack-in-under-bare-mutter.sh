#!/bin/bash
# jack-in-under-bare-mutter.sh -- launches jack-in-wayland.sh against the
# "Mutter (bare, no shell)" SDDM session instead of "GNOME on Wayland", to
# verify Monado can actually get the DRM lease and light the panel there,
# not just that mutter announces wp_drm_lease_device_v1 (already confirmed
# via check-lease.sh, 2026-08-10 -- see mutter-bare-session.sh).
#
# REAL BUG FOUND LIVE 2026-08-10, TWO LAYERS:
#
# 1. `systemd-run --scope --uid=iam` does NOT resolve iam's real
#    supplementary groups -- confirmed: `systemd-run --scope --uid=iam -- id`
#    returns `iam,root` only, missing `plugdev`. Compare with
#    `runuser -u iam -- id`, which correctly resolves the full list
#    (adm, cdrom, floppy, audio, dip, video, plugdev, users, netdev,
#    systemd-journal). This explains an EACCES(-13) opening
#    /dev/hidraw2 (HoloLens Sensors) that first looked hardware-related.
#
# 2. The working production pipeline (vr-launcher-console.sh) never
#    actually depended on that group resolution being correct -- it was
#    silently riding on logind's per-session "uaccess" ACL grant to
#    whichever session is ACTIVE on seat0, independent of groups. That ACL
#    is revoked the instant the active session's VT loses focus (e.g.
#    switching to a rescue console to talk to the operating agent) --
#    which is exactly what broke the first two attempts at this test, even
#    after chvt'ing back (the window closed again the moment the human
#    switched away to report the result).
#
# FIX: use `runuser` ONLY to drop privilege correctly (real group
# resolution via PAM+NSS), then hand off to `systemd-run --user --scope`
# (the user's OWN systemd instance, not a system scope) to decouple the
# process tree from runuser's login-session cgroup -- so monado-service
# survives runuser's PAM session teardown the same way it already survived
# systemd-run --scope's teardown in the original design. This no longer
# depends on which VT is active, so it's safe to run from any TTY.
#
# Needs root (crossing to another user's session needs polkit auth
# interactively otherwise) -- run with sudo, from a TTY.
set -u
rm -f /run/user/1000/monado_comp_ipc

runuser -u iam -- bash -c '
    export HOME=/home/iam USER=iam LOGNAME=iam
    export XDG_RUNTIME_DIR=/run/user/1000
    export WAYLAND_DISPLAY=wayland-0
    export XDG_SESSION_TYPE=wayland
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
    exec systemd-run --user --quiet --scope -- /home/iam/vr/jack-in-wayland.sh "$1" "$2"
' _ "${1:-1}" "${2:-3dof}" 2>&1 | tee /tmp/jack-in-under-bare-mutter-toplevel.log
