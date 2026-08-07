#!/usr/bin/env python3
"""Reads the headset's FIRMWARE LOG in plain text, over HID.

The G2 emits 509-byte `0x03 DEBUG` messages over the HoloLens Sensors interface, with the
internal log of its firmware in ASCII. Captured examples:

    RequestImuDisable forSpi=0
    ImuDisable Req=0 Spi=0
    RequestImuEnable forSpi=0
    ICMStart
    ERROR: CommandSet st 0, cmd 0, reqCmd 23
    ICM start status=0

Format of each entry within the packet:
    magic "Dlo+" | 4 bytes (timestamp) | 2 bytes (sequence) | 1 byte (level?) | ASCII text
A packet can carry SEVERAL entries concatenated, padded with zeros.

IMPORTANT: the channel is SILENT until someone performs the headset's configuration
sequence. Our `hmd-vk` doesn't do it; `monado-service` does. So to capture anything you
need to bring Monado up (or replicate its 0x0b -> 0x06 -> 0x04 -> 0x08 sequence).

  ./fwlog.py [seconds]
"""
import glob, os, re, select, sys, time

SENSORS = (0x045E, 0x0659)
MAGIC = b"Dlo+"


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


def entries(buf):
    """Returns (seq, text) for each entry within the packet."""
    out = []
    for m in re.finditer(re.escape(MAGIC), buf):
        p = m.end()
        if p + 7 > len(buf):
            continue
        ts = int.from_bytes(buf[p:p + 4], "little")
        seq = int.from_bytes(buf[p + 4:p + 6], "little")
        body = buf[p + 7:]
        end = body.find(b"\x00")
        txt = (body[:end] if end >= 0 else body).decode("ascii", "replace").strip()
        if txt:
            out.append((ts, seq, txt))
    return out


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    p = find(SENSORS)
    if not p:
        sys.exit("can't find the HoloLens Sensors 045e:0659")
    fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
    print(f"  listening on {p} for {secs:.0f}s (needs Monado running for it to talk)")

    t0 = time.time()
    seen = set()
    n = 0
    while time.time() - t0 < secs:
        r, _, _ = select.select([fd], [], [], 0.3)
        for f in r:
            try:
                b = os.read(f, 2048)
            except OSError:
                continue
            if not b or b[0] != 0x03:
                continue
            for ts, seq, txt in entries(b):
                key = (seq, txt)
                if key in seen:
                    continue
                seen.add(key)
                n += 1
                mark = "  !!" if ("ERROR" in txt or "err" in txt.lower() or
                                  "fail" in txt.lower()) else "    "
                print(f"{mark}[{time.time()-t0:6.2f}s] seq={seq:<6} {txt}")
    print(f"\n  {n} firmware log entries")


main()
