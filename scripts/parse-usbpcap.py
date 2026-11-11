#!/usr/bin/env python3
"""Parses USBPcap (Windows) pcapng captures and extracts the headset channels. No dependencies.

The lab system doesn't have tshark, and downloading it just to read a .pcapng is unnecessary:
the format is simple and streamable, which is also needed since the captures are hundreds of MB.

Extracts the two channels we decoded on Linux (ch. 12):

  0x05  DEVICE_STATUS  from the companion, 33 bytes
        byte 5      refresh in decimal
        bytes 19-20 htotal little-endian
        bytes 21-22 vtotal little-endian
        byte 1      1 = the backlight turned on (unreliable, see ch. 12)
  0x03  FIRMWARE LOG, 509 bytes ASCII
        magic "Dlo+" | 4B ts | 2B seq | 1B level | text

  ./parse-usbpcap.py capture.pcapng [another.pcapng ...]

pcapng format: blocks of {type u32, length u32, body, length u32}. We care about the
Enhanced Packet Block (type 6). USBPcap format: 27-byte header with headerLen at the
start and dataLength at the end; the data starts at headerLen.
"""
import re
import struct
import sys
import collections

EPB = 0x00000006
SHB = 0x0A0D0D0A
IDB = 0x00000001


def usb_packets(path):
    """Yields (device, endpoint, transfer, data) for each USB packet in the capture."""
    with open(path, "rb") as f:
        # The SHB tells us the endianness via its byte-order magic.
        head = f.read(12)
        if len(head) < 12:
            return
        btype = struct.unpack("<I", head[0:4])[0]
        if btype != SHB:
            print(f"  !! {path}: does not start with a Section Header Block", file=sys.stderr)
            return
        bom = struct.unpack("<I", head[8:12])[0]
        endi = "<" if bom == 0x1A2B3C4D else ">"
        blen = struct.unpack(endi + "I", head[4:8])[0]
        f.seek(blen)

        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                return
            btype, blen = struct.unpack(endi + "II", hdr)
            if blen < 12:
                return
            body = f.read(blen - 12)
            f.read(4)  # length repeated at the end
            if btype != EPB or len(body) < 20:
                continue
            caplen = struct.unpack(endi + "I", body[12:16])[0]
            pkt = body[20:20 + caplen]
            if len(pkt) < 27:
                continue
            header_len = struct.unpack(endi + "H", pkt[0:2])[0]
            device = struct.unpack(endi + "H", pkt[19:21])[0]
            endpoint = pkt[21]
            transfer = pkt[22]
            data_len = struct.unpack(endi + "I", pkt[23:27])[0]
            if data_len == 0 or header_len > len(pkt):
                continue
            yield device, endpoint, transfer, pkt[header_len:header_len + data_len]


def fw_entries(buf):
    out = []
    for m in re.finditer(re.escape(b"Dlo+"), buf):
        p = m.end()
        if p + 7 > len(buf):
            continue
        seq = int.from_bytes(buf[p + 4:p + 6], "little")
        body = buf[p + 7:]
        end = body.find(b"\x00")
        txt = (body[:end] if end >= 0 else body).decode("ascii", "replace").strip()
        if txt:
            out.append((seq, txt))
    return out


def show_status(b):
    ht = b[19] | (b[20] << 8)
    vt = b[21] | (b[22] << 8)
    return (f"refresh={b[5]:<4} htotal={ht:<6} vtotal={vt:<6} b1={b[1]} "
            f"b9={b[9]:02x} b10={b[10]:02x} b12={b[12]:02x} b14={b[14]:02x} b15={b[15]:02x}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for path in sys.argv[1:]:
        print(f"\n{'='*78}\n  {path}\n{'='*78}")
        n = 0
        devs = collections.Counter()
        status, seen_status = [], set()
        fw, seen_fw = [], set()
        for device, endpoint, transfer, data in usb_packets(path):
            n += 1
            devs[device] += 1
            if not data:
                continue
            if data[0] == 0x05 and len(data) == 33:
                h = data.hex(" ")
                if h not in seen_status:
                    seen_status.add(h)
                    status.append((device, data))
            elif data[0] == 0x03 and len(data) > 64:
                for seq, txt in fw_entries(data):
                    if (seq, txt) not in seen_fw:
                        seen_fw.add((seq, txt))
                        fw.append((seq, txt))
        print(f"  USB packets: {n}")
        print(f"  devices seen (addr:packets): "
              f"{', '.join(f'{d}:{c}' for d, c in devs.most_common(8))}")

        print(f"\n  --- DEVICE_STATUS (0x05): {len(status)} distinct ---")
        for device, b in status:
            print(f"    [dev {device}] {show_status(b)}")
            print(f"       {b.hex(' ')}")

        print(f"\n  --- FIRMWARE LOG (0x03): {len(fw)} entries ---")
        for seq, txt in fw:
            mark = "!!" if re.search(r"error|fail|err", txt, re.I) else "  "
            print(f"    {mark} seq={seq:<7} {txt}")


main()
