#!/usr/bin/env python3
"""Find the controller PAIRING command in a Windows USBPcap capture -- the wire format Linux needs.

This is the decoder for the ONE capture that lets this project abandon Windows completely. The
last Windows dependency is initial controller pairing; Linux could not do it because the real
{0x16, 0x05, ...} framing was unknown (the enum in wmr_protocol.h is an unvalidated guess, proven
inert in T236). Capture a real Oasis pairing with USBPcap (windows-kit/capture-bringup.ps1),
bring the trace to Linux, run this: it prints every host->headset control/output report that
carries a BT-control message (0x16), so the actual PAIR command and its payload jump out.

Controller pairing tunnels through the HoloLens Sensors device (045e:0659), NOT the companion.
So this targets 045e:0659 by default (analyze-hid.py handles the companion 03f0:0580 for the
panel question). Both read the same tshark TSV export.

INPUT: a .tsv exported from the .pcapng with (docs/07 has the canonical command):

  tshark -r bringup_USBPcapN.pcapng \\
     -Y "usb.device_address==<sensors_addr>" -T fields \\
     -e frame.time_relative -e usb.device_address \\
     -e usb.bmRequestType -e usb.setup.bRequest -e usb.setup.wValue \\
     -e usb.capdata > pairing.tsv

  (find <sensors_addr>: the device whose descriptor is 045e:0659; or just export all addresses
   and let this script filter by the 0x16 payload prefix.)

USAGE:
  ./analyze-pairing.py pairing.tsv            # show every 0x16 (BT-control) report, decoded
  ./analyze-pairing.py pairing.tsv --all      # show ALL output/feature reports, not just 0x16
"""
import argparse, sys, re

# The BT-control sub-commands, from wmr_protocol.h. We EXPECT to see 0x05 (PAIR) with a real
# payload the Linux attempt lacked. 0x17 (status) we already send and understand.
SUBCMD = {
    0x04: "ONLINE_STATUS", 0x05: "PAIR", 0x06: "UNPAIR",
    0x08: "PAIRING_STATUS", 0x09: "CMD_STATUS", 0x17: "CONTROLLER_STATUS(query)",
}


def parse_hex(s):
    s = (s or "").replace(":", "").strip()
    return bytes.fromhex(s) if re.fullmatch(r"[0-9a-fA-F]*", s) and len(s) % 2 == 0 else b""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tsv")
    ap.add_argument("--all", action="store_true", help="show every host->device report, not only 0x16")
    args = ap.parse_args()

    rows = []
    for line in open(args.tsv, encoding="utf-8", errors="replace"):
        f = line.rstrip("\n").split("\t")
        if len(f) < 6:
            continue
        t, addr, bmreq, breq, wval, capdata = f[:6]
        data = parse_hex(capdata)
        if not data:
            continue
        # host->device is bmRequestType with direction bit clear (0x21 SET_REPORT class, or
        # output on an interrupt OUT endpoint which USBPcap also carries as capdata).
        try:
            bm = int(bmreq, 16) if bmreq else 0
        except ValueError:
            bm = 0
        host_to_dev = (bm & 0x80) == 0
        rows.append((t, addr, bm, data, host_to_dev))

    print(f"parsed {len(rows)} data records from {args.tsv}\n")

    hits = 0
    for t, addr, bm, data, h2d in rows:
        is_bt = len(data) >= 1 and data[0] == 0x16
        if not (is_bt or (args.all and h2d)):
            continue
        hits += 1
        sub = data[1] if len(data) >= 2 else None
        subname = SUBCMD.get(sub, f"0x{sub:02x}" if sub is not None else "?")
        arrow = "H->D" if h2d else "D->H"
        head = data[:16].hex(" ")
        tag = ""
        if is_bt and sub == 0x05:
            tag = "   <=== PAIR  ***  THIS is the command Linux was missing"
        elif is_bt and sub == 0x06:
            tag = "   <=== UNPAIR"
        print(f"t={t:>10}  addr={addr:>3}  {arrow}  0x16/{subname:<22} len={len(data):3d}  {head}{tag}")
        # full payload for the interesting ones, so nothing is truncated
        if is_bt and sub in (0x05, 0x06):
            print(f"            FULL: {data.hex(' ')}")
            print(f"            bytes after subcmd (the payload to replicate): {data[2:].hex(' ')}")

    if not hits:
        print("No 0x16 BT-control reports found. Either the address filter dropped them, or the")
        print("pairing rode a different endpoint. Re-export WITHOUT the -Y address filter and")
        print("re-run with --all to see every host->device report, then look for the 0x16 prefix.")
    else:
        print(f"\n{hits} candidate report(s). The PAIR line's payload is what to send from")
        print("controller-pair.py: report 0x16, subcmd 0x05, then those payload bytes.")


if __name__ == "__main__":
    main()
