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
        read -r MODE TRACKING CTRL_OK GAMEPAD_OK < "$READY_FILE"
        rm -f "$READY_FILE"  # one-shot
        if [ "${CTRL_OK:-1}" != "1" ] && [ "${GAMEPAD_OK:-0}" != "1" ]; then
            # Headset's fine, but no VR controllers AND no gamepad fallback --
            # don't auto-launch a VR menu that leads nowhere good. Behave like
            # an ordinary Linux boot: leave the human at a normal
            # console/desktop to decide by hand.
            echo "vr-launcher-console: casco listo pero sin controles ni gamepad -- sin auto-launch, consola normal."
            exec /sbin/agetty tty4 linux
        fi
        if [ "${CTRL_OK:-1}" != "1" ]; then
            # Gamepad-only fallback (2026-08-10): titles like Aircar already run
            # on gamepad input alone (docs/pruebas.jsonl T127) -- don't force a
            # manual desktop detour just because the VR controllers specifically
            # are off. The launcher menu itself still shows what's pickable.
            echo "vr-launcher-console: sin controles VR, pero hay gamepad -- lanzando el menu igual."
        fi
        # Switch the visible console to tty4 -- with autologin now landing
        # straight on the (empty) GNOME desktop on tty1, the picker below
        # would otherwise run invisibly until someone manually hits
        # Ctrl+Alt+F4. Requested live 2026-08-10: the menu should be what's
        # actually on screen in auto mode, not the idle desktop.
        chvt 4 2>/dev/null || true
        # The console/TTY handling above needs root, but the actual app
        # launch must run as the real user -- Steam (and anything reading
        # the user's own config/session) must not run as root.
        #
        # CORRECTION, 2026-08-10 (T143): the claim right below used to say
        # "systemd-run --scope --uid= alone resolves full supplementary
        # groups correctly, confirmed live" -- that was WRONG, caught the
        # hard way when this exact path broke a real gamepad-fallback launch
        # tonight with ERROR [p_open_hid_interface] Failed to open device
        # '/dev/hidraw2' got '-13' (EACCES), even with the GNOME session on
        # tty3 active/foreground the whole time (ruling out the VT-active-ACL
        # theory floated during the mutter-bare test earlier the same
        # night). Re-tested directly, live: `systemd-run --scope --uid=iam
        # -- id` returns `groups=1000(iam),0(root)` -- plugdev is simply
        # never resolved. `runuser -u iam -- id` DOES resolve the full,
        # correct list (adm,cdrom,floppy,audio,dip,video,plugdev,users,
        # netdev,systemd-journal) via PAM+NSS. This was silently masked
        # in every previous "verified working" session by logind's
        # per-session uaccess ACL grant happening to already cover
        # /dev/hidraw2 -- not by the group resolution actually being right.
        #
        # FIX: runuser ONLY to drop privilege with real group resolution,
        # then hand off to `systemd-run --user --scope` (the user's OWN
        # systemd instance, not a system scope) instead of a bare
        # `exec systemd-run --scope --uid=`. This keeps the original
        # protection this section was written for -- found live 2026-08-10
        # (T136): a plain `runuser -u iam -- vr-launcher.py` would let
        # systemd tear down the whole PAM/logind login-session scope
        # (killing Monado/Steam with it) the instant vr-launcher.py exits on
        # purpose right after handing off ("lanzado en background, no
        # espera") -- confirmed then via a real BEGIN_SESSION followed by
        # "Server exiting: '0'" at the exact second runuser's PAM session
        # closed in the journal; `setsid` inside jack-in-wayland.sh doesn't
        # escape this, it only changes the kernel process session (job
        # control), not the systemd cgroup the login-session teardown acts
        # on. A `--user --scope` registered under iam's own systemd instance
        # is NOT tied to runuser's login-session cgroup, so it survives that
        # teardown the same way the old system `--scope` did -- verified
        # live against the "Mutter (bare, no shell)" test session the same
        # night (scripts/jack-in-under-bare-mutter.sh) before porting here.
        #
        # NOT using --property=SupplementaryGroups= on the scope -- tried it
        # (2026-08-10), it's not a valid transient property for a --scope
        # unit ("Unknown assignment" -- scopes wrap an already-forked
        # process, they don't go through systemd's own exec-context
        # machinery the way service units do).
        #
        # stderr also to a plain file, not just the tty -- StandardOutput=tty
        # in the .service hides everything from journalctl (same trap noted
        # elsewhere in this file), which made each of tonight's fixes above
        # slower to root-cause than it needed to be (had to wait for a human
        # to read tty4 directly). Debug aid, harmless to leave permanently.
        exec runuser -u "$VR_USER" -- bash -c '
            export HOME="/home/'"$VR_USER"'" USER="'"$VR_USER"'" LOGNAME="'"$VR_USER"'"
            export XDG_RUNTIME_DIR="/run/user/1000"
            export WAYLAND_DISPLAY="wayland-0"
            export XDG_SESSION_TYPE="wayland"
            export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus"
            exec systemd-run --user --quiet --scope -- python3 "$1" "$2" "$3"
        ' _ "$HERE/vr-launcher.py" "${MODE:-1}" "${TRACKING:-3dof}" \
            2>>/tmp/vr-launcher-console-debug.log
    fi
    sleep 1
done

# Nothing to show -- act like a normal console instead of leaving tty4 blank.
exec /sbin/agetty tty4 linux
