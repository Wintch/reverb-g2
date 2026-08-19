#!/usr/bin/env python3
"""controller-battery-check.py -- loud low-battery alert for the G2 controllers,
meant to run once Monado is up and BEFORE the actual game/player launches.

Why this can't live in power-on.py's step 5 (the pre-login hardware gate): that step
runs before Monado ever starts, and the raw battery byte is only reachable once a
controller's Monado device object exists and has parsed at least one 44-byte input
packet -- there is no lightweight standalone HID query for it like there is for
pairing status (controller-pair-check.py's 0x16/0x17 exchange). Getting it standalone
would mean re-running the controller's connection handshake (firmware config read,
"enable status reports"/"enable IMU" commands) over the SAME tunnel Monado itself
manages once it's running -- exactly the kind of thing that must NOT be done while
monado-service holds that tunnel. So this script queries Monado's OWN already-running
device instead, via libmonado, right after jack-in-wayland.sh/vr-launcher.py brings the
service up -- still comfortably "before a session starts" (the game/player hasn't
launched yet), just not before Monado itself has.

Real motivation (2026-08-13): the right controller had a low/dying battery and nobody
noticed until tracking quality degraded -- its optical constellation tracking starved
(dimmer LEDs -> fewer detected blobs) and the wearer saw that hand anchored meters off
mid-session. This is meant to catch that BEFORE it happens again.

Prerequisite: needs patches/monado/0040 built into the running monado-service (wires
the WMR HP controller driver's already-parsed battery byte into the generic
xrt_device::get_battery_status API libmonado already exposes). If the running build
predates that patch, every device reports "not present" -- this script says so plainly
instead of pretending it checked.

  ./controller-battery-check.py

Read-only: connects to the ALREADY-RUNNING monado-service over its normal libmonado/IPC
monitoring channel (the same mechanism monado-gui uses), same as any other client
querying telemetry -- does not touch hidraw, does not send any HID report, does not
change which client is active/focused. Safe to run next to a live game.
"""
import ctypes
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VR = HERE.parent
if (Path.home() / "vr" / "monado").is_dir():
    VR = Path.home() / "vr"

LIBMONADO = VR / "monado" / "build" / "src" / "xrt" / "targets" / "libmonado" / "libmonado.so"

# SCALE CONFIRMED (2026-08-18): raw/255 matches Windows' own HidP scaling exactly
# (percent = raw*100/255, the same ratio), see the driver's wmr_controller_hp_get_battery_status
# comment and docs/re-windows/03+06. Threshold updated the same day from the original
# deliberately-conservative 0.20 (byte ~51, picked before the scale was confirmed) to match
# docs/46's fitted voltage model (V ~= 0.00679*byte + 0.436) and its cliff prediction: byte ~83
# ~= 1.0V ("still usable" floor), byte ~68 ~= 0.9V (deep-discharge risk under load). The SAME DAY
# a real field failure (docs/46) showed a pair sag to byte 79 under load right before one cell
# caught a catastrophic internal-resistance spike -- i.e. the mid-70s is not a safe margin,
# it's where failures have actually happened. Trigger a bit above the cliff's own top (83) so
# the warning fires with lead time instead of exactly at the danger zone.
BATTERY_LOW_THRESHOLD = 85 / 255  # ~0.333 -- fires entering the cliff, not inside it

TTY = sys.stdout.isatty()
C_OK = "\033[1;92m" if TTY else ""
C_BAD = "\033[1;31m" if TTY else ""
C_WARN = "\033[1;33m" if TTY else ""
C_DIM = "\033[2m" if TTY else ""
C_RESET = "\033[0m" if TTY else ""

HANDS = ("left", "right")


def ok(msg):
    print(f"  {C_OK}✓{C_RESET} {msg}")


def bad(msg):
    print(f"  {C_BAD}✗{C_RESET} {msg}")


def warn(msg):
    print(f"  {C_WARN}!{C_RESET} {msg}")


def dim(msg):
    print(f"    {C_DIM}{msg}{C_RESET}")


class Libmonado:
    """Thin ctypes binding, just the four calls this script needs. See
    src/xrt/targets/libmonado/monado.h in the monado tree for the full API this is
    a slice of."""

    def __init__(self, path):
        self.lib = ctypes.CDLL(str(path))
        self.lib.mnd_root_create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.lib.mnd_root_create.restype = ctypes.c_int
        self.lib.mnd_root_destroy.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.lib.mnd_root_destroy.restype = None
        self.lib.mnd_root_get_device_from_role.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32),
        ]
        self.lib.mnd_root_get_device_from_role.restype = ctypes.c_int
        self.lib.mnd_root_get_device_battery_status.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_bool),
            ctypes.POINTER(ctypes.c_bool),
            ctypes.POINTER(ctypes.c_float),
        ]
        self.lib.mnd_root_get_device_battery_status.restype = ctypes.c_int
        self.root = ctypes.c_void_p()

    def connect(self):
        rc = self.lib.mnd_root_create(ctypes.byref(self.root))
        return rc == 0  # MND_SUCCESS

    def device_for_role(self, role):
        idx = ctypes.c_int32(-1)
        rc = self.lib.mnd_root_get_device_from_role(self.root, role.encode(), ctypes.byref(idx))
        if rc != 0 or idx.value < 0:
            return None
        return idx.value

    def battery_status(self, device_index):
        present = ctypes.c_bool(False)
        charging = ctypes.c_bool(False)
        charge = ctypes.c_float(0.0)
        rc = self.lib.mnd_root_get_device_battery_status(
            self.root, device_index, ctypes.byref(present), ctypes.byref(charging), ctypes.byref(charge)
        )
        if rc != 0:
            return None
        return present.value, charging.value, charge.value

    def close(self):
        if self.root:
            self.lib.mnd_root_destroy(ctypes.byref(self.root))


def main():
    print("=== Controller battery check ===")

    if not LIBMONADO.exists():
        warn(f"libmonado.so not found at {LIBMONADO} -- can't check, not blocking.")
        return 0

    try:
        mnd = Libmonado(LIBMONADO)
    except OSError as e:
        warn(f"couldn't load libmonado.so: {e} -- can't check, not blocking.")
        return 0

    if not mnd.connect():
        # Most likely monado-service isn't up yet (this should run right after it is) or
        # the IPC socket is otherwise unreachable. Either way this is a "can't tell you"
        # situation, not a "your battery is fine" one -- say so, don't go silent.
        warn("couldn't connect to monado-service over libmonado -- can't check battery, not blocking.")
        return 0

    any_present = False
    any_low = False
    try:
        for hand in HANDS:
            idx = mnd.device_for_role(hand)
            if idx is None:
                dim(f"{hand}: no device in that role right now (controller off, or not yet seen this session).")
                continue

            status = mnd.battery_status(idx)
            if status is None:
                warn(f"{hand}: battery query failed (device index {idx}).")
                continue

            present, _charging, charge = status
            if not present:
                # Either the controller hasn't sent an input packet yet, or the running
                # monado-service predates patches/monado/0040 -- both look identical from
                # here, and both are "no data", not "battery is fine". Say which is more
                # likely so this isn't mistaken for a clean bill of health.
                dim(f"{hand}: no battery data (needs a monado-service built with "
                    f"patches/monado/0040, and at least one packet from the controller).")
                continue

            any_present = True
            pct = round(charge * 100)
            if charge < BATTERY_LOW_THRESHOLD:
                any_low = True
                bad(f"{hand.upper()} CONTROLLER BATTERY LOW ({pct}%, cliff zone -- see docs/46).")
                dim(f"Consequence: optical constellation tracking will degrade as the LEDs dim --")
                dim(f"expect the {hand} hand to drift or 'anchor' meters off mid-session. Swap the")
                dim(f"battery before starting, or watch that hand for exactly this symptom.")
            else:
                ok(f"{hand}: {pct}%")
    finally:
        mnd.close()

    if not any_present:
        warn("No battery telemetry available for either controller this run -- see the notes")
        warn("above. Not blocking: this is a missing instrument, not a known-bad battery.")
    elif any_low:
        print()
        warn("Continuing anyway -- battery is informational, only the headset itself blocks.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
