#!/usr/bin/env python3
"""Blanks the password of the GNOME 'Login' keyring, headlessly, so it auto-unlocks
with no prompt (standard fix for SDDM autologin boxes). Asks for the CURRENT password
interactively (hidden input via getpass -- never an argv/env value, never logged,
never leaves this terminal). Run this yourself, in your own terminal, as the user
whose keyring this is (iam) -- do not paste output or the password anywhere.

Requires a live gnome-keyring-daemon on the session bus (it already is, if you're
logged into the desktop normally).
"""
import dbus
import getpass
import os
import pwd
import sys

TARGET_USER = "iam"

def ensure_session_env():
    """Auto-discover and export the real session bus address/runtime dir from the
    already-running gnome-shell process, so this works from any shell (root or not)
    without needing manual exports first -- but still refuses to proceed as the
    wrong Unix user, since the session bus socket belongs to TARGET_USER specifically."""
    me = pwd.getpwuid(os.getuid()).pw_name
    if me != TARGET_USER:
        print(f"ERROR: running as '{me}', but the Login keyring belongs to '{TARGET_USER}'.\n"
              f"Switch user first, e.g.: su - {TARGET_USER}   (then re-run this script)",
              file=sys.stderr)
        sys.exit(1)

    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return  # already set, trust it

    try:
        target_uid = pwd.getpwnam(TARGET_USER).pw_uid
        gs_pid = None
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/comm") as f:
                    if f.read().strip() != "gnome-shell":
                        continue
                if os.stat(f"/proc/{entry}").st_uid != target_uid:
                    continue
                gs_pid = entry
                break
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        if gs_pid is None:
            raise RuntimeError("no running gnome-shell process found for this user")
        with open(f"/proc/{gs_pid}/environ", "rb") as f:
            env_data = f.read()
        for item in env_data.split(b"\0"):
            if item.startswith(b"DBUS_SESSION_BUS_ADDRESS=") or item.startswith(b"XDG_RUNTIME_DIR="):
                k, _, v = item.decode().partition("=")
                os.environ[k] = v
    except Exception as e:
        print(f"Could not auto-discover the session bus ({e}); falling back to the default path.",
              file=sys.stderr)
        os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS",
                               f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus")

def main():
    ensure_session_env()
    current = getpass.getpass("Current Login keyring password: ")
    confirm_blank = input("Type YES to confirm setting it to BLANK (unencrypted on disk): ")
    if confirm_blank.strip() != "YES":
        print("Aborted, nothing changed.")
        sys.exit(1)

    bus = dbus.SessionBus()
    service = dbus.Interface(
        bus.get_object("org.freedesktop.secrets", "/org/freedesktop/secrets"),
        "org.freedesktop.Secret.Service",
    )
    _, session_path = service.OpenSession("plain", dbus.String("", variant_level=1))

    collection_path = service.ReadAlias("default")
    if str(collection_path) == "/":
        print("ERROR: no default keyring/alias found -- is gnome-keyring-daemon running "
              "on this session bus?", file=sys.stderr)
        sys.exit(1)

    def secret_struct(password_str):
        return dbus.Struct(
            (session_path, dbus.ByteArray(b""), dbus.ByteArray(password_str.encode()),
             dbus.String("text/plain")),
            signature="oayays",
        )

    internal = dbus.Interface(
        bus.get_object("org.freedesktop.secrets", "/org/freedesktop/secrets"),
        "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface",
    )

    try:
        internal.ChangeWithMasterPassword(
            collection_path,
            secret_struct(current),
            secret_struct(""),
        )
    except dbus.exceptions.DBusException as e:
        print(f"FAILED -- likely wrong current password: {e}", file=sys.stderr)
        sys.exit(1)

    print("Done. Login keyring password is now blank -- it auto-unlocks with no prompt, "
          "and its contents are stored unencrypted on disk from now on.")

if __name__ == "__main__":
    main()
