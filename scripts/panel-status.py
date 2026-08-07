#!/usr/bin/env python3
"""Listens to what the HEADSET says about its own panel, over HID.

The companion (03f0:0580) sends a DEVICE_STATUS (0x05) message when the screen
state changes. From the Monado comment in wmr_hmd.c (control_read_packets):

    On Reverb G1 this message is received twice after having sent an 'enable screen' command.
    The first one is received promptly. The second one is received a few seconds later once
    the HMD screen backlight VISIBLY POWERS ON.
      1st message: 05 00 01 01 00 00 00 00 00 00 00
      2nd message: 05 01 01 01 01 00 00 00 00 00 00

In other words, the hardware tells us when the panel actually turned on. It's the only
SINK-side instrumentation we have: everything else (Vulkan, the NVIDIA log) reports
success with a dead panel.

Experiment idea: capture this while requesting 60Hz (locks) and while requesting 90Hz
(does not lock), and diff them. If the bytes differ, the headset is telling us where it breaks.

  ./panel-status.py [seconds]

Known messages (wmr_protocol.h):
  0x01 IPD_VALUE     byte1 = proximity sensor, bytes2-3 = IPD
  0x02 UNKNOWN_02    seen alongside proximity events on the G1
  0x05 DEVICE_STATUS device/screen status   <-- the one that matters
"""
import glob, os, select, sys, time

COMPANION = (0x03F0, 0x0580)
NAMES = {0x01: "IPD_VALUE", 0x02: "UNKNOWN_02", 0x05: "DEVICE_STATUS"}


def find_companion():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split(":")
                if (int(vid, 16), int(pid, 16)) == COMPANION:
                    return "/dev/" + os.path.basename(d)
    return None


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    dev = find_companion()
    if not dev:
        sys.exit("can't find companion 03f0:0580")
    print(f"  listening on {dev} for {secs:.0f}s")
    print(f"  (the companion may RE-ENUMERATE on screen-off; if it disappears, it's reopened)")

    t0 = time.time()
    fd = None
    n = 0
    while time.time() - t0 < secs:
        if fd is None:
            p = find_companion()
            if not p:
                time.sleep(0.3)
                continue
            try:
                fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                time.sleep(0.3)
                continue
        r, _, _ = select.select([fd], [], [], 0.3)
        for f in r:
            try:
                b = os.read(f, 512)
            except OSError:
                os.close(fd)
                fd = None
                print(f"  [{time.time()-t0:6.2f}s] -- companion went away, reopening --")
                break
            if not b:
                continue
            n += 1
            rid = b[0]
            # The message is 33 bytes. Print it in FULL: the second-half bytes
            # also change between modes and truncating to 16 dropped half the data.
            print(f"  [{time.time()-t0:6.2f}s] 0x{rid:02x} {NAMES.get(rid,'?'):<14} "
                  f"len={len(b):<3} {b.hex(' ')}")
    print(f"\n  total: {n} messages from the companion")
    if n == 0:
        print("  (none -- the companion only speaks when something changes: you need to "
              "turn the panel on/off while this is listening)")


main()
