"""Shared desktop-session env vars for launching GUI processes (Steam,
jack-in-wayland.sh) from a non-interactive context (systemd service, SSH
shell) that doesn't inherit them.

XAUTHORITY's suffix is a fresh random cookie every Xwayland (re)start --
always discovered live via glob, never hardcoded (confirmed to change
across a reboot, 2026-08-22: .50FFU3 -> .TS4KU3).

DISPLAY was hardcoded to ":0" until 2026-08-26, when that turned out to be
wrong: Xwayland is launched on-demand with `-displayfd` and self-selects
its real number over that fd rather than trusting its own argv, so the
live session can end up on ":1", ":2", etc. while ":0" belongs to an
unrelated root-owned server (GDM's own). Presenting the correct XAUTHORITY
cookie to the wrong DISPLAY number is exactly what produced "Invalid
MIT-MAGIC-COOKIE-1 key" for monado-gui/xdotool. Fixed the same way as
XAUTHORITY: read it live off a real X11 client already in this session
(mutter-x11-frames, GNOME's own window-decoration helper) instead of
guessing a number.
"""
import glob
import os
import subprocess


def _live_display():
    pids = subprocess.run(["pgrep", "-f", "mutter-x11-frames"], capture_output=True, text=True).stdout.split()
    for pid in pids:
        try:
            environ = open(f"/proc/{pid}/environ", "rb").read()
        except OSError:
            continue
        for entry in environ.split(b"\0"):
            if entry.startswith(b"DISPLAY="):
                return entry.split(b"=", 1)[1].decode()
    return ":0"


def get():
    matches = glob.glob("/run/user/1000/.mutter-Xwaylandauth.*")
    xauth = matches[0] if matches else "/run/user/1000/.mutter-Xwaylandauth"
    return {
        **os.environ,
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": _live_display(),
        "XAUTHORITY": xauth,
    }
