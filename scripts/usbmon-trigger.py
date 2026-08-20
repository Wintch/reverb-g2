#!/usr/bin/env python3
"""One-shot, SAFE trigger for a usbmon byte-diff against pairing_joys.pcapng (T240).

Sends exactly two routine, non-destructive reports to the HoloLens Sensors device --
the same shapes controller-pair-check.py and the --handshake poll already send in normal
operation, nothing new and nothing that touches PAIR/UNPAIR:
  1. {0x16, 0x09} (CMD_STATUS) via HIDIOCSFEATURE  -- Feature, same path PAIR itself uses
  2. {0x02, 0x08} (PAIRING_STATUS poll) via write() -- Output, same path the sustained poll uses

Meant to run WHILE a usbmon capture is active on the same bus, so the two writes land in
the capture and can be byte-diffed against the equivalent Windows frames in
/mnt/win3/debug_vr/pairing_joys.pcapng (frame 7766 for the Output shape, any of the eight
`16 xx` Feature frames in docs/03's T240 table for the Feature shape).
"""
import fcntl, glob, os, time

HOLOLENS_SENSORS = (0x045E, 0x0659)


def find_dev():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split(":")
                if (int(vid, 16), int(pid, 16)) == HOLOLENS_SENSORS:
                    return "/dev/" + os.path.basename(d)
    return None


def _HIDIOCSFEATURE(length):
    return (3 << 30) | (ord("H") << 8) | 0x06 | (length << 16)


dev = find_dev()
if not dev:
    raise SystemExit("cannot find Hololens Sensors (045e:0659)")
fd = os.open(dev, os.O_RDWR)

buf = bytes([0x16, 0x09]) + bytes(62)
fcntl.ioctl(fd, _HIDIOCSFEATURE(len(buf)), buf, True)
print("sent 16 09 (CMD_STATUS) via HIDIOCSFEATURE")
time.sleep(0.3)

buf = bytes([0x02, 0x08]) + bytes(62)
os.write(fd, buf)
print("sent 02 08 (PAIRING_STATUS poll) via write()")

os.close(fd)
