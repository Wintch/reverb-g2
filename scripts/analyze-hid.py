#!/usr/bin/env python3
"""
Analyzes and diffs HID captures from the Reverb G2 companion device (03f0:0580).

Goal: find which command Windows sends to put the panel into 90Hz that Monado does not.
Measured on Linux on 2026-08-04: Monado sends EXACTLY the same thing at 60Hz (the panel
turns on) and at 90Hz (it does not turn on) — see ch. 04. The Windows side is still missing.

Reads two formats, so the Linux <-> Windows diff is homogeneous:

  usbmon (Linux)    scripts/capture-hid.sh produces this directly.
  tsv    (Windows)  exported with tshark from USBPcap's .pcapng; the exact command
                    (with ALL the required fields) is in docs/07.

What actually matters are the HID class control transfers:

  SET_REPORT  bmRequestType=0x21 bRequest=0x09   host -> headset  (the commands)
  GET_REPORT  bmRequestType=0xa1 bRequest=0x01   headset -> host

and in both, wValue = (type << 8) | report_id, with type 1=Input 2=Output 3=Feature.

The rest of the bus traffic (enumeration, string descriptors, hubs, audio) is
discarded: the companion is detected automatically, via its device descriptor.

Usage:
  ./analyze-hid.py resumen  ~/vr/hid-mode2.txt
  ./analyze-hid.py diff     ~/vr/hid-mode2.txt ~/vr/hid-mode1.txt
  ./analyze-hid.py diff     ~/vr/hid-mode1.txt windows-90hz.tsv
"""

import argparse
import re
import sys
from collections import Counter

VID, PID = 0x03F0, 0x0580

# Reports Monado currently sends (wmr_hmd.c). Anything NOT here is a candidate to be
# the command we're missing.
KNOWN = {
    0x50: "loop (activation)",
    0x09: "data_1 (activation)",
    0x08: "data_2 (activation)",
    0x06: "data_3 (activation)",
    0x04: "screen on/off",
    0x02: "proximity/IPD (telemetry)",
}
RTYPE = {1: "Input", 2: "Output", 3: "Feature"}

# ffff8c00587106c0 2027666441 S Co:3:079:0 s 21 09 0350 0000 0040 64 = 50010000 ...
USBMON_RE = re.compile(
    r"^\S+\s+(\d+)\s+([SCE])\s+([CZIB])([io]):(\d+):(\d+):(\d+)\s+(.*)$"
)
SETUP_RE = re.compile(
    r"^s\s+([0-9a-f]{2})\s+([0-9a-f]{2})\s+([0-9a-f]{4})\s+([0-9a-f]{4})\s+([0-9a-f]{4})"
)


class Xfer:
    """A normalized HID class control transfer."""

    def __init__(self, t, req_type, request, wvalue, data):
        self.t = t
        self.req_type = req_type
        self.request = request
        self.report_type = (wvalue >> 8) & 0xFF
        self.report_id = wvalue & 0xFF
        self.data = data

    @property
    def kind(self):
        if self.req_type == 0x21 and self.request == 0x09:
            return "SET_REPORT"
        if self.req_type == 0xA1 and self.request == 0x01:
            return "GET_REPORT"
        return f"other(bmRequestType=0x{self.req_type:02x},bRequest=0x{self.request:02x})"

    def signature(self):
        # Timestamps and zero padding are ignored: what matters is WHAT was sent.
        return (self.kind, self.report_type, self.report_id, self.data[:16].rstrip("0"))


def find_companion(path):
    """Finds the companion's device address via its device descriptor.

    The descriptor carries idVendor/idProduct in little endian in bytes 8..11, which in
    usbmon's hex dump show up as 'f0038005'. The device address changes on every
    re-enumeration (and the G2 re-enumerates all the time, ch. 06), so hardcoding it
    does not work.
    """
    want = f"{VID & 0xFF:02x}{VID >> 8:02x}{PID & 0xFF:02x}{PID >> 8:02x}"
    found = set()
    with open(path, errors="replace") as fh:
        for line in fh:
            if want not in line.replace(" ", "").lower():
                continue
            m = USBMON_RE.match(line.strip())
            if m and m.group(6) != "000":
                found.add(int(m.group(6)))
    return found


def parse_usbmon(path, device=None):
    if device is None:
        cands = find_companion(path)
        if len(cands) == 1:
            device = cands.pop()
        elif len(cands) > 1:
            # Re-enumerated during the capture: keep the one that actually
            # received commands, not just the first one that shows up.
            device = pick_active(path, cands)
        # If no descriptor shows up, fall back to "any device with HID class traffic".

    out = []
    with open(path, errors="replace") as fh:
        for line in fh:
            m = USBMON_RE.match(line.strip())
            if not m:
                continue
            ts, event, ttype, direction, bus, dev, ep, rest = m.groups()
            if ttype != "C":  # only control transfers
                continue
            if device is not None and int(dev) != device:
                continue
            sm = SETUP_RE.match(rest)
            if not sm:
                continue  # this is the callback; the setup travels in the submit
            req_type, request, wvalue, _widx, _wlen = sm.groups()
            data = ""
            if "=" in rest:
                data = "".join(rest.split("=", 1)[1].split()).lower()
            x = Xfer(int(ts), int(req_type, 16), int(request, 16), int(wvalue, 16), data)
            if x.kind.startswith("other"):
                continue  # descriptors, SET_ADDRESS, etc.
            out.append(x)
    return out, device


def pick_active(path, cands):
    counts = Counter()
    with open(path, errors="replace") as fh:
        for line in fh:
            m = USBMON_RE.match(line.strip())
            if m and int(m.group(6)) in cands and SETUP_RE.match(m.group(8)):
                counts[int(m.group(6))] += 1
    return counts.most_common(1)[0][0] if counts else sorted(cands)[0]


def parse_tsv(path, device=None):
    """tshark TSV. Columns, in this order (see docs/07):
    time_relative, device_address, bmRequestType, bRequest, wValue, capdata
    """
    out = []
    with open(path, errors="replace") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 5:
                continue
            try:
                t = int(float(p[0]) * 1_000_000)
                dev = int(p[1]) if p[1].strip() else None
                req_type = int(p[2], 0) if p[2].strip() else 0
                request = int(p[3], 0) if p[3].strip() else 0
                wvalue = int(p[4], 0) if p[4].strip() else 0
            except ValueError:
                continue  # header row or empty field
            if device is not None and dev != device:
                continue
            data = p[5].replace(":", "").replace(" ", "").lower() if len(p) > 5 else ""
            x = Xfer(t, req_type, request, wvalue, data)
            if x.kind.startswith("other"):
                continue
            out.append(x)
    return out, device


def load(path, fmt, device=None):
    if fmt == "auto":
        fmt = "tsv" if path.endswith((".tsv", ".csv")) else "usbmon"
    dev = int(device) if device else None
    return (parse_usbmon if fmt == "usbmon" else parse_tsv)(path, dev)


def fmt_sig(sig, count=None):
    kind, rtype, rid, data = sig
    arrow = "->" if kind == "SET_REPORT" else "<-"
    note = KNOWN.get(rid, "")
    note = f"  [{note}]" if note else "  [UNKNOWN]"
    c = f"  x{count}" if count and count > 1 else ""
    t = RTYPE.get(rtype, f"type{rtype}")
    return f"  {kind:10s} {arrow} {t:7s} report 0x{rid:02x}  data={data or '(empty)'}{c}{note}"


def cmd_resumen(args):
    recs, dev = load(args.file, args.format, args.device)
    print(f"{args.file}")
    print(f"companion detected: device {dev if dev is not None else '(unfiltered)'}")
    if not recs:
        print("\nNo HID class transfers found. If the companion re-enumerated during\n"
              "startup, the capture may be unusable: check that there is a SET_REPORT 0x50.",
              file=sys.stderr)
        return 1
    print(f"{len(recs)} HID class transfers\n")
    counts = Counter(r.signature() for r in recs)
    seen = []
    for r in recs:
        if r.signature() not in seen:
            seen.append(r.signature())
    for s in seen:
        print(fmt_sig(s, counts[s]))
    sets = sum(1 for r in recs if r.kind == "SET_REPORT")
    print(f"\nSET_REPORT (host->headset): {sets}   GET_REPORT: {len(recs) - sets}")
    return 0


def cmd_diff(args):
    a, da = load(args.file_a, args.format_a, args.device_a)
    b, db = load(args.file_b, args.format_b, args.device_b)
    print(f"A = {args.file_a}  (device {da}, {len(a)} HID transfers)")
    print(f"B = {args.file_b}  (device {db}, {len(b)} HID transfers)\n")
    if not a or not b:
        print("One of the two captures has no usable HID traffic.", file=sys.stderr)
        return 1

    sa, sb = Counter(x.signature() for x in a), Counter(x.signature() for x in b)

    print("=" * 72)
    print("IN B BUT NOT IN A  <-- if B is 90Hz and A is 60Hz, THIS is the answer")
    print("=" * 72)
    only_b = [s for s in sb if s not in sa]
    print("\n".join(fmt_sig(s, sb[s]) for s in only_b) if only_b
          else "  (nothing: B does not send any command that A does not send)")

    print("\n" + "=" * 72)
    print("IN A BUT NOT IN B")
    print("=" * 72)
    only_a = [s for s in sa if s not in sb]
    print("\n".join(fmt_sig(s, sa[s]) for s in only_a) if only_a else "  (nothing)")

    print("\n" + "=" * 72)
    print("SAME COMMAND, DIFFERENT COUNT")
    print("=" * 72)
    diffs = [s for s in sa if s in sb and sa[s] != sb[s]]
    print("\n".join(f"{fmt_sig(s)}   A x{sa[s]}  B x{sb[s]}" for s in diffs)
          if diffs else "  (nothing)")

    ia = {x.report_id for x in a if x.kind == "SET_REPORT"}
    ib = {x.report_id for x in b if x.kind == "SET_REPORT"}
    print("\nReport IDs sent to the headset (SET_REPORT):")
    print(f"  A: {sorted('0x%02x' % i for i in ia)}")
    print(f"  B: {sorted('0x%02x' % i for i in ib)}")
    if ib - ia:
        print(f"  >>> ONLY IN B: {sorted('0x%02x' % i for i in ib - ia)}")
    elif not only_b:
        print("  >>> Both captures send the same thing.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resumen", help="lists the HID commands in a capture")
    r.add_argument("file")
    r.add_argument("--format", choices=["auto", "usbmon", "tsv"], default="auto")
    r.add_argument("--device", help="force the device address (normally auto-detected)")
    r.set_defaults(func=cmd_resumen)

    d = sub.add_parser("diff", help="compares two captures")
    d.add_argument("file_a")
    d.add_argument("file_b")
    d.add_argument("--format-a", choices=["auto", "usbmon", "tsv"], default="auto")
    d.add_argument("--format-b", choices=["auto", "usbmon", "tsv"], default="auto")
    d.add_argument("--device-a")
    d.add_argument("--device-b")
    d.set_defaults(func=cmd_diff)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
