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
        # XDG_RUNTIME_DIR/WAYLAND_DISPLAY explicit, not inherited -- a bare
        # `runuser -u X --` from a root service (no --login) doesn't reliably
        # get the PAM/logind-populated session environment a real interactive
        # login gets, even though the socket itself already exists on disk
        # (that's all the [-S ...] check above proves). Same bug class as the
        # $HOME-under-set-u crash found earlier tonight: something a real
        # login shell provides for free, silently missing one hop removed
        # from it. Without these, Monado's compositor can fail to reach
        # mutter's Wayland socket even though everything LOOKS ready.
        # XDG_SESSION_TYPE=wayland too -- jack-in-wayland.sh has its own real
        # sanity check on this exact variable (not cosmetic, see there), and
        # it's just as absent from a bare runuser as the other two. Found
        # live 2026-08-10 by reproducing the failure with a minimal env -i
        # instead of guessing -- the first fix (RUNTIME_DIR+DISPLAY alone)
        # LOOKED plausible but still failed identically until this was added.
        exec runuser -u "$VR_USER" -- env XDG_RUNTIME_DIR="/run/user/1000" WAYLAND_DISPLAY="wayland-0" \
            XDG_SESSION_TYPE="wayland" \
            python3 "$HERE/vr-launcher.py" "${MODE:-1}" "${TRACKING:-3dof}"
    fi
    sleep 1
done

# Nothing to show -- act like a normal console instead of leaving tty4 blank.
exec /sbin/agetty tty4 linux
