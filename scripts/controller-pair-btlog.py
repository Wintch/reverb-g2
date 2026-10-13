#!/usr/bin/env python3
"""Send the headset's PAIR command and print its Bluetooth debug log for 25 s.

    scripts/controller-pair-btlog.py

Sends PAIR (feature report 16 05 01) to the headset's sensor interface (045e:0659), then
decodes report 0x05 (the firmware's BT state-machine log, ASCII) and report 0x17 (controller
status) as they arrive. See docs/03-controllers.md, the pairing reverse-engineering sections.

This puts the headset's own radio into pairing: a controller in pairing mode may bond to the
headset instead of the host Bluetooth adapter it is paired with now.
"""
import fcntl
import glob
import os
import select
import sys
import time


def dev():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(d + "/device/uevent").read()
        except OSError:
            continue
        if "045E:00000659" in ue.upper():
            return "/dev/" + os.path.basename(d)
    return None


def HIDIOCSFEATURE(length):
    return (3 << 30) | (ord('H') << 8) | 0x06 | (length << 16)


def feat(fd, payload):
    b = bytes(payload) + bytes(64 - len(payload))
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE(len(b)), b, True)
        return True
    except OSError:
        return False


def main():
    path = dev()
    if path is None:
        sys.exit("no 045e:0659 hidraw node: is the headset connected?")
    fd = os.open(path, os.O_RDWR)
    # fire PAIR (16 05 01) via control SET_REPORT
    print("fire PAIR 16 05 01 via HIDIOCSFEATURE:", feat(fd, [0x16, 0x05, 0x01]))
    # now READ everything for 25s, decode report 0x05 ASCII (the BT state machine)
    print("listening 25s for the BT debug log (report 0x05) and status (0x17)...")
    t0 = time.time()
    while time.time() - t0 < 25:
        r, _, _ = select.select([fd], [], [], 0.5)
        if not r:
            continue
        try:
            b = os.read(fd, 64)
        except OSError:
            print("  [fd died -- reopening]")
            try:
                os.close(fd)
            except OSError:
                pass
            time.sleep(0.5)
            nd = dev()
            if nd is None:
                sys.exit("  the headset's hidraw node did not come back")
            fd = os.open(nd, os.O_RDWR)
            continue
        if not b:
            continue
        if b[0] == 0x05 and len(b) > 6:
            txt = bytes(x for x in b[6:] if 32 <= x < 127).decode('ascii', 'replace')
            if txt.strip():
                print(f"  t+{time.time() - t0:4.1f}s  BT-LOG: {txt}")
        elif b[0] == 0x17 and len(b) >= 3:
            st = {0: 'UNPAIRED', 1: 'offline', 2: 'ONLINE'}.get(b[2], b[2])
            if b[1] == 1:
                print(f"  t+{time.time() - t0:4.1f}s  STATUS right={st}")
    os.close(fd)


if __name__ == "__main__":
    main()
