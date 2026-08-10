#!/bin/bash
# vr-launcher-console.sh -- lighter alternative to the gnome-terminal/autostart
# approach: runs vr-launcher.py directly on tty4, plain text, no gnome-terminal,
# no GNOME autostart .desktop mechanism. GNOME/mutter itself still has to be
# running (jack-in-wayland.sh's DRM lease has no other validated path in this
# project) -- this only avoids the EXTRA weight of a terminal emulator + the
# autostart machinery just to show a text menu.
#
# Waits (bounded, polling) for two things before showing the picker:
#   1. ~/.vr-ready exists -- written by power-on.py --pre-login only on a real
#      LISTO, removed on every failure path.
#   2. A real Wayland session socket exists -- proxy for "GNOME actually
#      finished logging in", since a bare `graphical.target` reached doesn't
#      guarantee the human is done typing their password yet.
#
# If neither shows up within the wait window (manual mode chosen, auto
# failed, or login is just slow), falls through to a normal `agetty` on tty4
# -- this console never gets stuck showing nothing.
#
# WAS tty3 originally -- real bug, found live 2026-08-09: SDDM's own
# gnome-wayland.desktop session starts on VT 3 (confirmed via
# `journalctl -u sddm`: "...for VT 3", and `loginctl list-sessions` showing
# the real iam/seat0 session on tty3), not tty1 as assumed. The tty3 version
# of this service collided with the actual GNOME session for the console,
# kicking a fresh login back to a blank text console. tty4 is the confirmed
# genuinely-free VT (checked live: getty@tty4.service inactive, no session
# on it) -- don't move this again without re-checking with the same commands.

# set -u deliberately NOT used here: this runs as a root systemd service
# (needed for TTY control -- opening a VT for exclusive stdin/stdout isn't a
# plain-user operation), where $HOME can be entirely unset -- an unguarded
# reference to it would abort immediately with no visible error (StandardOutput=tty
# hides it from the journal too). Found live 2026-08-09 -- the service
# crash-looped 25+ times before this was traced. Use explicit paths, not $HOME.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
READY_FILE="/run/vr-ready"
WAIT_MAX=60
VR_USER="iam"

for _i in $(seq 1 "$WAIT_MAX"); do
    if [ -f "$READY_FILE" ] && [ -S "/run/user/1000/wayland-0" ]; then
        read -r MODE TRACKING CTRL_OK < "$READY_FILE"
        rm -f "$READY_FILE"  # one-shot
        if [ "${CTRL_OK:-1}" != "1" ]; then
            # Headset's fine, controllers aren't -- don't auto-launch a VR menu
            # that leads nowhere good. Behave like an ordinary Linux boot: leave
            # the human at a normal console/desktop to decide by hand.
            echo "vr-launcher-console: casco listo pero sin controles -- sin auto-launch, consola normal."
            exec /sbin/agetty tty4 linux
        fi
        # The console/TTY handling above needs root, but the actual app
        # launch must run as the real user -- Steam (and anything reading
        # the user's own config/session) must not run as root.
        #
        # systemd-run --scope, NOT runuser -- found live 2026-08-10 (T136):
        # runuser wraps the command in a PAM/logind LOGIN SESSION scope, and
        # systemd tears that whole scope down (killing every process still in
        # it) the instant its leader (vr-launcher.py) exits -- regardless of
        # whether children are still running. vr-launcher.py exits on purpose
        # right after handing off ("lanzado en background, no espera"), so
        # monado-service and Steam were being killed the moment it returned --
        # confirmed in jack-in-wayland.log: a real BEGIN_SESSION, then
        # "Server exiting: '0'" at the exact same second runuser's PAM session
        # closed in the journal. `setsid` inside jack-in-wayland.sh doesn't
        # escape this -- it changes the kernel process session (job control),
        # not the systemd cgroup the login-session teardown acts on.
        # `systemd-run --scope` instead creates its own transient scope that
        # is NOT tied to any login session -- systemd keeps it (and everything
        # in it) alive as long as the cgroup isn't empty, which is exactly
        # "as long as Monado/Steam are still running", regardless of whether
        # vr-launcher.py itself has already exited.
        #
        # Explicit env, same reasoning as before: systemd-run --uid= doesn't
        # build a login-like environment the way runuser does, so nothing
        # (not even HOME/USER) can be assumed present.
        #
        # NOT using --property=SupplementaryGroups= -- tried it (2026-08-10),
        # it's not a valid transient property for a --scope unit ("Unknown
        # assignment", confirmed via the debug log below -- scopes wrap an
        # already-forked process, they don't go through systemd's own
        # exec-context machinery the way service units do, so exec-context
        # properties like this one don't apply). Confirmed instead, by
        # testing `systemd-run --scope --uid=iam -- id` directly, that
        # --uid=<username> alone already resolves full supplementary groups
        # correctly (plugdev included) -- the EACCES seen on /dev/hidraw2
        # right before this had some other cause, not missing group
        # membership; don't reintroduce this property if that resurfaces,
        # look elsewhere.
        #
        # stderr also to a plain file, not just the tty -- StandardOutput=tty
        # in the .service hides everything from journalctl (same trap noted
        # elsewhere in this file), which made each of tonight's fixes above
        # slower to root-cause than it needed to be (had to wait for a human
        # to read tty4 directly). Debug aid, harmless to leave permanently.
        exec systemd-run --quiet --scope --uid="$VR_USER" \
            --setenv=HOME="/home/$VR_USER" --setenv=USER="$VR_USER" --setenv=LOGNAME="$VR_USER" \
            --setenv=XDG_RUNTIME_DIR="/run/user/1000" --setenv=WAYLAND_DISPLAY="wayland-0" \
            --setenv=XDG_SESSION_TYPE="wayland" --setenv=DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus" \
            -- python3 "$HERE/vr-launcher.py" "${MODE:-1}" "${TRACKING:-3dof}" \
            2>>/tmp/vr-launcher-console-debug.log
    fi
    sleep 1
done

# Nothing to show -- act like a normal console instead of leaving tty4 blank.
exec /sbin/agetty tty4 linux
