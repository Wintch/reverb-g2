#!/usr/bin/env python3
"""Pair a G2 motion controller to the headset FROM LINUX. First attempt in the world (T236).

Nobody has ever done this. The wire format is reverse-engineered and sitting UNUSED in Monado's
own header (wmr_protocol.h): WMR_BT_CONTROL_MSG_PAIR = 0x05 on report 0x16. The only code path
that ever sends 0x16 is the status query (0x17). This sends the pair command instead. If it
works, the battery-compartment button stops being one-way on Linux and the last Windows
dependency in this project dies.

WHAT THIS DOES, and the safety model is the whole design, not a footnote:
  * Sends ONLY the PAIR command (0x05). It never sends UNPAIR (0x06): the semantics of a
    host-side unpair are unknown (does it drop one bond or both? which slot?), and the physical
    button already erases a bond deterministically, aimed at ONE controller you chose. There is
    no reason to hand an unknown destructive command a chance to fire. UNPAIR stays out.
  * Reads state before and after with the SAME decoder controller-pair-check.py uses, so
    "did it work" is answered by the headset, not by whether the write returned success.
  * Is idempotent-safe: pairing an already-paired controller is, at worst, a no-op. The
    dangerous direction (erase) is not on the table here.

THE PROCEDURE (a bond needs a controller in discovery to bond WITH):
  1. Put the target controller in discovery yourself: hold the small button inside its battery
     compartment until the LEDs pulse slowly. THAT is what makes it bondable; the host command
     arms the headset's radio to look for it. Both halves are required.
  2. Run this. It arms the radio, then polls status for up to --wait seconds looking for the
     UNPAIRED/absent -> paired transition.

RECOVERY, stated up front because we are first: if this leaves a controller unpaired and it
will not re-pair here, a Windows machine with Oasis restores it (docs/03). Do this with that
escape hatch available. Test ONE controller at a time; leave the other paired and untouched as
a live control.

  ./controller-pair.py [left|right] [--wait SECONDS] [--arm-only]

--arm-only sends the command and reports, without waiting for the transition (for capturing the
headset's immediate response). Default target: whichever controller currently reads UNPAIRED or
absent; if both are paired it refuses (nothing to do -- do not poke a working pair).
"""
import argparse, glob, os, select, sys, time

HOLOLENS_SENSORS = (0x045E, 0x0659)
MSG_BT_CONTROL = 0x16
SUB_CONTROLLER_STATUS = 0x17
BT_PAIR = 0x05
PKT = {0x0: "UNPAIRED", 0x1: "paired/offline", 0x2: "paired/online"}
NAME = {0: "left", 1: "right"}
ID = {"left": 0, "right": 1}


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


def read_status(fd, secs=2.0):
    """Send the status query, collect one packet per controller id. Returns {id: pkt_type}."""
    os.write(fd, bytes([MSG_BT_CONTROL, SUB_CONTROLLER_STATUS]) + bytes(62))
    seen = {}
    t0 = time.time()
    while time.time() - t0 < secs and len(seen) < 2:
        r, _, _ = select.select([fd], [], [], 0.3)
        if not r:
            continue
        b = os.read(fd, 64)
        if b and len(b) >= 3 and b[0] == SUB_CONTROLLER_STATUS:
            seen[b[1]] = b[2]
    return seen


def fmt(seen):
    return ", ".join(f"{NAME[i]}={PKT.get(seen[i], hex(seen[i]))}" if i in seen else f"{NAME[i]}=absent"
                     for i in (0, 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", choices=["left", "right"], help="which hand (default: the unpaired one)")
    ap.add_argument("--wait", type=float, default=30.0, help="seconds to watch for the pairing to take (default 30)")
    ap.add_argument("--arm-only", action="store_true", help="send the command and report immediately, do not wait")
    args = ap.parse_args()

    dev = find_dev()
    if not dev:
        sys.exit("cannot find Hololens Sensors (045e:0659) -- headset powered and connected?")
    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except PermissionError:
        sys.exit(f"no permission for {dev} -- need group plugdev (see scripts/70-wmr-reverb.rules)")

    before = read_status(fd)
    print(f"before: {fmt(before)}")

    # Choose the target. Refuse to poke a fully-paired pair unless told exactly which hand.
    if args.target:
        cid = ID[args.target]
    else:
        unpaired = [i for i in (0, 1) if before.get(i, 0x0) == 0x0 or i not in before]
        if not unpaired:
            os.close(fd)
            sys.exit("both controllers already paired -- nothing to do. Name a hand explicitly to force.")
        cid = unpaired[0]
    print(f"target: {NAME[cid]} controller (id {cid})")
    print(f"  reminder: that controller must be IN DISCOVERY -- hold its battery-compartment")
    print(f"  button until the LEDs pulse slowly, THEN this arms the headset's radio for it.")

    # Arm the radio: {0x16, 0x05, controller_id}. The id byte is the same position the status
    # query leaves zero; this is the documented-but-never-sent PAIR message.
    cmd = bytes([MSG_BT_CONTROL, BT_PAIR, cid]) + bytes(61)
    try:
        os.write(fd, cmd)
    except OSError as e:
        os.close(fd)
        sys.exit(f"could not send PAIR: {e}")
    print(f"  SENT: report 0x16 subtype 0x05 (PAIR) for id {cid} -- first time from Linux, ever.")

    if args.arm_only:
        time.sleep(1.0)
        print(f"after (immediate): {fmt(read_status(fd))}")
        os.close(fd)
        return

    print(f"  watching for {NAME[cid]} to become paired, up to {args.wait:.0f}s...")
    t0 = time.time()
    took = False
    while time.time() - t0 < args.wait:
        st = read_status(fd, 1.0)
        if st.get(cid) in (0x1, 0x2):
            print(f"\n  *** {NAME[cid]} is now {PKT[st[cid]]} at t+{time.time()-t0:.1f}s -- PAIRED FROM LINUX ***")
            took = True
            break
        print(f"    t+{time.time()-t0:4.0f}s  {fmt(st)}")
    os.close(fd)

    if not took:
        print(f"\n  no transition in {args.wait:.0f}s. Not proven. Things to vary before concluding:")
        print("    - controller actually in discovery (slow pulse) when the command was sent?")
        print("    - id byte position: this assumes byte2; if it does nothing, the arg may live elsewhere")
        print("    - some stacks arm the radio with ONLINE_STATUS (0x04) first -- worth a try")
        print("  Recovery if it is now stuck unpaired: pair it once on Windows/Oasis (docs/03).")


main()
