#!/usr/bin/env python3
"""Hunts the headset's HID 0x03 DEBUG channel during a mode attempt.

Reason: in Monado issue #332, another user (Kukeltje) reported seeing a
`DMA CMT ERR` error on the 0x03 DEBUG channel right during a 90Hz attempt. We looked at
that channel AT REST and it emitted nothing — but it may only emit when something fails.

Listens on BOTH devices and shows everything that is NOT the sensor stream (0x01), in
hex and ASCII, because firmware debug messages are usually text.

  ./hunt-debug.py [seconds]

Run in parallel with hmd-vk requesting the mode that fails.

Types (wmr_protocol.h): 0x01 SENSORS, 0x02 CONTROL, 0x03 DEBUG, 0x05 BT_IFACE,
0x06/0x0E controllers, 0x16 BT_CONTROL, 0x17 CONTROLLER_STATUS.
The BT interface also has a sub-message 0x19 = WMR_BT_IFACE_MSG_DEBUG.
"""
import collections, glob, os, select, sys, time

NAMES = {0x01: "SENSORS", 0x02: "CONTROL", 0x03: "DEBUG", 0x05: "BT_IFACE",
         0x06: "LEFT_CTRL", 0x0E: "RIGHT_CTRL", 0x16: "BT_CONTROL", 0x17: "CTRL_STATUS"}
DEVS = (("sensors", (0x045E, 0x0659)), ("companion", (0x03F0, 0x0580)))


def find(vp):
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if line.startswith("HID_ID="):
                _, v, p = line.split(":")
                if (int(v, 16), int(p, 16)) == vp:
                    return "/dev/" + os.path.basename(d)
    return None


def ascii_of(b):
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40
    fds = {}
    for label, vp in DEVS:
        p = find(vp)
        if not p:
            print(f"  !! can't find {label}")
            continue
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = label
            print(f"  {label}: {p}")
        except OSError as e:
            print(f"  !! {label}: {e}")
    if not fds:
        sys.exit("no devices")

    counts = collections.Counter()
    interesting = 0
    t0 = time.time()
    while time.time() - t0 < secs:
        r, _, _ = select.select(list(fds), [], [], 0.4)
        for fd in r:
            try:
                b = os.read(fd, 2048)
            except OSError:
                continue
            if not b:
                continue
            label = fds[fd]
            rid = b[0]
            counts[(label, rid)] += 1
            if rid == 0x01 and label == "sensors":
                continue                      # the IMU stream, noise for this purpose
            interesting += 1
            t = time.time() - t0
            print(f"  [{t:6.2f}s] {label:<9} 0x{rid:02x} {NAMES.get(rid,'?'):<12} len={len(b)}")
            print(f"            hex   {b[:48].hex(' ')}")
            txt = ascii_of(b)
            if sum(1 for c in txt if c != ".") > 4:      # only if there's real text
                print(f"            ascii {txt}")

    print("\n  count by type:")
    for (label, rid), n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {label:<10} 0x{rid:02x} {NAMES.get(rid,'?'):<13} {n}")
    print(f"\n  non-SENSORS messages: {interesting}")
    if not counts.get(("sensors", 0x03)) and not counts.get(("companion", 0x03)):
        print("  (no 0x03 DEBUG -- the channel is still silent)")


main()
