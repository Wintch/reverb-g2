#!/usr/bin/env python3
"""Force a USB device to re-enumerate, by VID:PID, without root.

WHY IT IS WORTH HAVING. The G2's USB2 branch re-enumerates by itself several times a minute
(docs/60: measured at the same rate on Windows, so it is the link and not this stack). Every
one of those invalidates the hidraw fd Monado holds. Waiting for a natural event to test the
driver's recovery is slow and unrepeatable; issuing USBDEVFS_RESET reproduces exactly that
condition on demand, which is what turns "the reconnect works" into a regression test.

No root needed as long as the user is in `plugdev` (Debian's default for /dev/bus/usb), which
also means the lab agent can run it unattended -- the sysfs `authorized` route in
usb-companion-reset.sh needs sudo and a human.

  ./scripts/usb-reset-device.py                 # the G2 companion, one reset
  ./scripts/usb-reset-device.py -n 5 -i 20      # a synthetic storm
  ./scripts/usb-reset-device.py --vid 045e --pid 0659   # anything else on the bus
"""

import argparse
import fcntl
import glob
import os
import sys
import time

# USBDEVFS_RESET is _IO('U', 20). Resetting re-runs enumeration on the port: the device gets a
# new devnum and its character devices (hidraw, ALSA) are torn down and recreated -- the same
# thing the storm does to us, on demand.
USBDEVFS_RESET = ord("U") << 8 | 20


def find_usb(vid, pid):
    for d in sorted(glob.glob("/sys/bus/usb/devices/*")):
        try:
            with open(os.path.join(d, "idVendor")) as f:
                v = f.read().strip()
            with open(os.path.join(d, "idProduct")) as f:
                p = f.read().strip()
        except OSError:
            continue
        if v.lower() == vid.lower() and p.lower() == pid.lower():
            with open(os.path.join(d, "busnum")) as f:
                bus = int(f.read())
            with open(os.path.join(d, "devnum")) as f:
                dev = int(f.read())
            return d, bus, dev
    return None, None, None


def hidraw_node(vid, pid):
    """The node a driver would find right now. Printing it before and after is the point: an
    unchanged node means the device did not really re-enumerate and the test proved nothing."""
    want = "HID_ID=0003:%08X:%08X" % (int(vid, 16), int(pid, 16))
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(h, "device", "uevent")) as f:
                if want in f.read():
                    return os.path.basename(h)
        except OSError:
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vid", default="03f0", help="vendor id, hex (default: HP)")
    ap.add_argument("--pid", default="0580", help="product id, hex (default: Reverb G2 companion)")
    ap.add_argument("-n", "--count", type=int, default=1, help="how many resets")
    ap.add_argument("-i", "--interval", type=float, default=15.0, help="seconds between resets")
    ap.add_argument("-s", "--settle", type=float, default=6.0,
                    help="seconds to wait for re-enumeration before judging the result")
    args = ap.parse_args()
    settle = args.settle

    for i in range(args.count):
        syspath, bus, dev = find_usb(args.vid, args.pid)
        if syspath is None:
            print("no USB device %s:%s -- is the headset connected?" % (args.vid, args.pid), file=sys.stderr)
            return 1

        before = hidraw_node(args.vid, args.pid)
        node = "/dev/bus/usb/%03d/%03d" % (bus, dev)
        print("[%d/%d] %s resetting %s (%s, hidraw=%s)"
              % (i + 1, args.count, time.strftime("%H:%M:%S"), node, syspath, before))

        try:
            fd = os.open(node, os.O_WRONLY)
        except PermissionError:
            print("cannot open %s -- need group plugdev (or run with sudo)" % node, file=sys.stderr)
            return 1
        try:
            fcntl.ioctl(fd, USBDEVFS_RESET, 0)
        finally:
            os.close(fd)

        # HOW TO READ THE RESULT, and this cost two wrong instruments to learn.
        #
        # USBDEVFS_RESET does not always tear the device down the same way. Sometimes the
        # kernel restores the old USB address (devnum unchanged) and merely re-probes the HID
        # interface, which still hands out a NEW hidraw minor and still kills any open fd;
        # sometimes the node name is even reused. So neither devnum nor the node name is a
        # reliable tell on its own, and polling sysfs for the transition races the teardown --
        # both the old and the new entry can be listed at once, which produced two confident
        # measurements the driver's log flatly contradicted.
        #
        # The authoritative instrument is the driver itself: it prints the node it opened and
        # how long the channel was dead, and only after a successful open. What this script
        # prints below is context for that line, not a verdict.
        time.sleep(settle)
        _, _, new_dev = find_usb(args.vid, args.pid)
        after = hidraw_node(args.vid, args.pid)
        print("[%d/%d] %s after settle: devnum %s -> %s, node %s -> %s   (verdict lives in the "
              "service log: 'Companion device RECONNECTED')"
              % (i + 1, args.count, time.strftime("%H:%M:%S"), dev, new_dev, before, after))

        if i + 1 < args.count:
            time.sleep(args.interval)

    print("done. Look for 'Companion device RECONNECTED' in the service log.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
