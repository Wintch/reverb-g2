#!/usr/bin/env python3
"""Controls the G2 panel via HID, without Monado.

  ./panel.py activate    full power-on sequence (the one that's actually needed)
  ./panel.py on          just the screen-enable {0x04,0x01}
  ./panel.py off         screen-disable {0x04,0x00}
  ./panel.py cycle       off -> wait for re-enumeration -> on

Replicates `wmr_hmd_activate_reverb()` from Monado (wmr_hmd.c:767) against the companion
`03f0:0580`. Useful for driving the panel without bringing up the whole runtime, e.g. to
test modesets with `hmd-modeset`.

MEASURED (2026-08-04):
  - `on` ALONE is not enough: without the activation sequence the panel stays completely
    off, not even the HP logo shows up. Use `activate`.
  - `off` can make the companion RE-ENUMERATE and change its hidraw node (we've seen
    hidraw8 -> hidraw7). That's why it always rescans and never caches the path.
"""
import fcntl, glob, os, sys, time

# _IOC(READ|WRITE, 'H', nr, len)
HIDIOCSFEATURE = lambda n: 0xC0004806 | (n << 16)
HIDIOCGFEATURE = lambda n: 0xC0004807 | (n << 16)

COMPANION = (0x03F0, 0x0580)


def find_companion():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split(":")
                if (int(vid, 16), int(pid, 16)) == COMPANION:
                    return "/dev/" + os.path.basename(d)
    return None


def wait_for_companion(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        dev = find_companion()
        if dev:
            try:                       # appears in sysfs before it's openable
                open(dev, "wb+", buffering=0).close()
                return dev
            except OSError:
                pass
        time.sleep(0.5)
    return None


def open_companion():
    dev = wait_for_companion()
    if not dev:
        sys.exit("companion 03f0:0580 not found -- check the USB port (ch. 00)")
    return dev


def set_screen(state):
    dev = open_companion()
    buf = bytearray([0x04, 0x01 if state else 0x00])
    with open(dev, "wb+", buffering=0) as f:
        fcntl.ioctl(f, HIDIOCSFEATURE(len(buf)), buf)
    print(f"  {dev}: screen {'on' if state else 'off'}")
    return dev


def activate():
    dev = open_companion()
    with open(dev, "wb+", buffering=0) as f:
        time.sleep(0.3)                        # Monado: "300ms is what Windows does"
        for _ in range(4):                     # the G1 hack inherited from OpenHMD
            buf = bytearray(64)
            buf[0], buf[1] = 0x50, 0x01
            fcntl.ioctl(f, HIDIOCSFEATURE(64), buf)
            g = bytearray(64)
            g[0] = 0x50
            try:
                fcntl.ioctl(f, HIDIOCGFEATURE(64), g)
            except OSError as e:
                print(f"  get 0x50: {e}")
            time.sleep(0.01)
        for rid in (0x09, 0x08, 0x06):         # identification reads
            g = bytearray(64)
            g[0] = rid
            try:
                fcntl.ioctl(f, HIDIOCGFEATURE(64), g)
                print(f"  get 0x{rid:02x}: {g[:16].hex(' ')}")
            except OSError as e:
                print(f"  get 0x{rid:02x}: {e}")
        fcntl.ioctl(f, HIDIOCSFEATURE(2), bytearray([0x04, 0x01]))
    print(f"  {dev}: full activation + screen on")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("activate", "on", "off", "cycle"):
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "activate":
        activate()
    elif cmd == "cycle":
        before = set_screen(False)
        print("  waiting for re-enumeration...")
        time.sleep(2)
        after = wait_for_companion()
        if after and after != before:
            print(f"  re-enumerated: {before} -> {after}")
        set_screen(True)
    else:
        set_screen(cmd == "on")


main()
