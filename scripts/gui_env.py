"""Shared desktop-session env vars for launching GUI processes (Steam,
jack-in-wayland.sh) from a non-interactive context (systemd service, SSH
shell) that doesn't inherit them.

XAUTHORITY's suffix is a fresh random cookie every Xwayland (re)start --
always discovered live via glob, never hardcoded (confirmed to change
across a reboot, 2026-08-22: .50FFU3 -> .TS4KU3).
"""
import glob
import os


def get():
    matches = glob.glob("/run/user/1000/.mutter-Xwaylandauth.*")
    xauth = matches[0] if matches else "/run/user/1000/.mutter-Xwaylandauth"
    return {
        **os.environ,
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": ":0",
        "XAUTHORITY": xauth,
    }
