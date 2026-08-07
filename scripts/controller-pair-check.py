#!/usr/bin/env python3
"""Asks the HEADSET whether it has the controllers paired, via direct HID (without Monado).

The G2 controllers do not speak Bluetooth to the PC (see docs/03-controllers.md): they are
paired at the factory with the headset's internal radio, and their pairing state is queried
by sending a command to the same Hololens Sensors device (045e:0659) that Monado already
uses - protocol read from wmr_hmd.c / wmr_protocol.h:

  Request (report 0x16, WMR_MS_HOLOLENS_MSG_BT_CONTROL):
      byte0=0x16  byte1=0x17 (subtype CONTROLLER_STATUS)  rest zeroed, 64 bytes

  Response (report 0x17, WMR_MS_HOLOLENS_MSG_CONTROLLER_STATUS), one per controller:
      byte0=0x17  byte1=controller_id (0=left, 1=right)  byte2=pkt_type
          pkt_type 0x0 UNPAIRED  -> never paired / became unpaired (hidden reset button)
          pkt_type 0x1 OFFLINE   -> paired, but currently off or out of range
          pkt_type 0x2 ONLINE    -> paired and currently responding
      if OFFLINE/ONLINE, bytes3-4=VID bytes5-6=PID (little-endian)

Investigated on 2026-08-06 by reading the Monado driver (authoritative source: the headset
itself). The "pair" command, on the other hand, does NOT exist in any Windows binary examined
(see docs/03-controllers.md, section "Pairing") - it is an internal radio handshake to the
headset, triggered by the controller's physical button, with no host command. This script
only QUERIES state; it does not attempt to pair anything.

  ./controller-pair-check.py [seconds_to_wait]

Works with or without monado-service running (hidraw allows being opened more than once).
"""
import glob, os, select, sys, time

HOLOLENS_SENSORS = (0x045E, 0x0659)
PKT_TYPE = {0x0: "UNPAIRED", 0x1: "paired, offline", 0x2: "paired, online"}
NAME = {0: "left", 1: "right"}


def find_hololens_sensors():
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


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    dev = find_hololens_sensors()
    if not dev:
        sys.exit("cannot find the Hololens Sensors (045e:0659) - is the headset powered on and connected?")

    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except PermissionError:
        sys.exit(f"no permission for {dev} - it should be rw for the plugdev group "
                  f"(see scripts/70-wmr-reverb.rules); are you in that group? (groups)")
    except OSError as e:
        sys.exit(f"could not open {dev}: {e}")

    cmd = bytes([0x16, 0x17]) + bytes(62)
    try:
        os.write(fd, cmd)
    except OSError as e:
        os.close(fd)
        sys.exit(f"could not write the status request to {dev}: {e}")

    print(f"  status request sent, listening on {dev} for {secs:.0f}s...")
    seen = {}
    t0 = time.time()
    while time.time() - t0 < secs and len(seen) < 2:
        r, _, _ = select.select([fd], [], [], 0.3)
        if not r:
            continue
        b = os.read(fd, 64)
        if not b or b[0] != 0x17 or len(b) < 3:
            continue
        cid, pkt_type = b[1], b[2]
        vidpid = None
        if pkt_type in (0x1, 0x2) and len(b) >= 7:
            vid = b[3] | (b[4] << 8)
            pid = b[5] | (b[6] << 8)
            vidpid = (vid, pid)
        seen[cid] = (pkt_type, vidpid)
    os.close(fd)

    print()
    for cid in (0, 1):
        label = f"  {NAME.get(cid, cid)} (id {cid}): "
        if cid not in seen:
            print(label + "no response (no 0x17 packet arrived for this id)")
            continue
        pkt_type, vidpid = seen[cid]
        desc = PKT_TYPE.get(pkt_type, f"unknown type 0x{pkt_type:02x}")
        if vidpid:
            desc += f"  (VID 0x{vidpid[0]:04x} PID 0x{vidpid[1]:04x})"
        print(label + desc)

    if len(seen) < 2:
        print("\n  (if one is missing: the headset only reports the ones it has news of - "
              "try with the controller on and nearby)")


main()
