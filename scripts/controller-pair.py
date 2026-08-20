#!/usr/bin/env python3
"""Attempt to pair a G2 motion controller FROM LINUX. Harness for a still-OPEN problem (T236).

STATUS 2026-08-20 (T238): the command bytes are CONFIRMED CORRECT. A USBPcap capture of a real
Oasis pairing (right controller) shows Windows pairs with exactly `16 05 01` -- byte for byte
what T236 already sent. So the format was never the problem; the T236 "inert guess" conclusion
was wrong. The difference is TIMING: Oasis sends PAIR ONCE, at the instant the controller is
actively pulsing in discovery. T236's tool read status first (a ~3 s delay) and the discovery
window had likely lapsed by the time PAIR landed. This version fires PAIR IMMEDIATELY on your
go, then watches. See docs/03-controllers.md "T238".

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
import argparse, fcntl, glob, os, select, sys, time

# The BREAKTHROUGH (T238): BT-control commands must be sent as a HID SET_REPORT over the CONTROL
# endpoint, exactly as Oasis does (capture: bmRequestType 0x21). os.write() to hidraw goes to the
# interrupt-OUT endpoint and NEVER reaches the command handler -- proven because the 0x17 status
# we thought our query fetched is actually STREAMED passively (16 packets arrive with zero writes).
# So every earlier "PAIR did nothing" was the command not landing, not a wrong command. Send via
# HIDIOCSFEATURE instead.
def _HIDIOCSFEATURE(length):
    return (3 << 30) | (ord('H') << 8) | 0x06 | (length << 16)


def send_feature(fd, payload):
    """Send a HID feature report (control SET_REPORT, wValue high byte 0x03), the channel Oasis
    uses for report 0x16 (BT_CONTROL: PAIR/UNPAIR/CMD_STATUS/...). payload[0] is the report id.
    Returns True if the device accepted it."""
    buf = bytes(payload) + bytes(64 - len(payload))
    try:
        fcntl.ioctl(fd, _HIDIOCSFEATURE(len(buf)), buf, True)
        return True
    except OSError:
        return False


def write_output(fd, payload):
    """Send a HID OUTPUT report (control SET_REPORT, wValue high byte 0x02). T240's capture shows
    Windows polls report 0x02 (PAIRING_STATUS) as Output, not Feature -- and interface 2 has no
    interrupt-OUT endpoint, so a plain write() to hidraw already routes as a control SET_REPORT
    with the Output wValue, no ioctl needed (unlike report 0x16, which IS sent as Feature).
    Sending 0x02 via HIDIOCSFEATURE (the earlier bug) put the wrong report type on the wire and
    made every send fail, forcing a re-enumeration loop that never let an inquiry survive."""
    buf = bytes(payload) + bytes(64 - len(payload))
    try:
        os.write(fd, buf)
        return True
    except OSError:
        return False

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


def reopen():
    """Re-find and open the sensors device by VID/PID. Sending PAIR resets the radio, which
    re-enumerates the device and invalidates the old fd (measured T238, same class as the
    companion re-enumeration patch 0090). Returns a fresh fd, or None if it is not back yet."""
    for _ in range(30):
        d = find_dev()
        if d:
            try:
                return os.open(d, os.O_RDWR | os.O_NONBLOCK)
            except OSError:
                pass
        time.sleep(0.3)
    return None


def read_status(fd, secs=2.0, log_debug=False):
    """Send the status query, collect one packet per controller id. Returns ({id: pkt_type}, fd).
    Survives the fd breaking under a re-enumeration by reopening and retrying.
    If log_debug: also decode and print any report 0x05 (WMR_BT_IFACE_MSG_DEBUG) packets seen
    while reading -- the radio's own BT state-machine log, decoded in T240 (COMMAND_INQUIRY,
    "inquiry started", "Found by address", etc). This is the ground truth for whether a PAIR
    command actually reached the BT command handler, independent of whether the USB write itself
    was accepted."""
    seen = {}
    # status is streamed passively, but send the query too (via the control channel) for parity
    if not send_feature(fd, [MSG_BT_CONTROL, SUB_CONTROLLER_STATUS]):
        nfd = reopen()
        if nfd is None:
            return seen, fd
        try:
            os.close(fd)
        except OSError:
            pass
        fd = nfd
        send_feature(fd, [MSG_BT_CONTROL, SUB_CONTROLLER_STATUS])
    t0 = time.time()
    while time.time() - t0 < secs and len(seen) < 2:
        try:
            r, _, _ = select.select([fd], [], [], 0.3)
        except OSError:
            break
        if not r:
            continue
        try:
            b = os.read(fd, 64)
        except OSError:
            break
        if b and len(b) >= 3 and b[0] == SUB_CONTROLLER_STATUS:
            seen[b[1]] = b[2]
        elif log_debug and b and len(b) > 6 and b[0] == 0x05:
            txt = bytes(x for x in b[6:] if 32 <= x < 127).decode("ascii", "replace").strip()
            if txt:
                print(f"      BT-LOG: {txt}")
    return seen, fd


def fmt(seen):
    return ", ".join(f"{NAME[i]}={PKT.get(seen[i], hex(seen[i]))}" if i in seen else f"{NAME[i]}=absent"
                     for i in (0, 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", choices=["left", "right"], help="which hand (default: the unpaired one)")
    ap.add_argument("--wait", type=float, default=30.0, help="seconds to watch for the pairing to take (default 30)")
    ap.add_argument("--arm-only", action="store_true", help="send the command and report immediately, do not wait")
    ap.add_argument("--now", action="store_true", help="fire instantly without waiting for you to confirm the pulse")
    ap.add_argument("--handshake", action="store_true", help="mirror the full Oasis sequence (CMD_STATUS + sustained PAIR/poll)")
    ap.add_argument("--probe", type=lambda s: int(s, 0), metavar="SUBTYPE",
                     help="SAFE, read-only: send {0x16, SUBTYPE} once and watch the report-0x05 "
                          "debug log for a reaction, without touching PAIR/UNPAIR or any target. "
                          "For the T240 unknown 0x07: --probe 0x07")
    args = ap.parse_args()

    dev = find_dev()
    if not dev:
        sys.exit("cannot find Hololens Sensors (045e:0659) -- headset powered and connected?")
    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except PermissionError:
        sys.exit(f"no permission for {dev} -- need group plugdev (see scripts/70-wmr-reverb.rules)")

    if args.probe is not None:
        # T236 already showed 0x08/0x04/0x05 alone (no controller id) just echo the passive 0x17
        # status stream with no visible reaction. This does the same non-destructive send but
        # ALSO watches report 0x05 (WMR_BT_IFACE_MSG_DEBUG, T240's decoded BT state-machine log)
        # for anything the radio says back -- T240's "16 07 00" had no attributable log line in
        # the reference capture either, so a silent result here is a real (if inconclusive) data
        # point, not a tooling failure.
        sub = args.probe
        ok = send_feature(fd, [MSG_BT_CONTROL, sub])
        print(f"probe: sent 16 {sub:02x} (no controller id) via control SET_REPORT (accepted={ok})")
        print("  listening 8s on report 0x05 (BT debug log) and 0x17 (status) for any reaction...")
        t0 = time.time()
        saw_anything = False
        while time.time() - t0 < 8.0:
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                continue
            try:
                b = os.read(fd, 64)
            except OSError:
                break
            if not b:
                continue
            if b[0] == 0x05 and len(b) > 6:
                txt = bytes(x for x in b[6:] if 32 <= x < 127).decode("ascii", "replace").strip()
                if txt:
                    saw_anything = True
                    print(f"    t+{time.time()-t0:4.1f}s  BT-LOG: {txt}")
            elif b[0] == SUB_CONTROLLER_STATUS and len(b) >= 3:
                pass  # the routine passive status stream, not a reaction -- don't clutter output
        if not saw_anything:
            print("  no report-0x05 activity attributable to the probe.")
        os.close(fd)
        return

    before, fd = read_status(fd)
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

    # TIMING IS THE WHOLE GAME (T238). The Oasis capture shows PAIR is sent ONCE, exactly while
    # the controller is pulsing in discovery, and succeeds ~7 s later. So: get the controller
    # pulsing FIRST, then fire with no delay. Unless --now, wait for you to confirm the pulse so
    # the command lands inside the discovery window (T236 failed by reading status first).
    if not args.now:
        print()
        print(f"  1. Power on the {NAME[cid]} controller.")
        print(f"  2. Open its battery compartment, hold the small button until the LEDs PULSE SLOWLY.")
        print(f"  3. WHILE it is pulsing, press Enter here -- PAIR fires instantly.")
        input("  ready (pulsing now)? Enter> ")

    # {0x16, 0x05, controller_id} via the CONTROL endpoint (HIDIOCSFEATURE), the channel Oasis
    # uses -- os.write() to the interrupt-OUT endpoint never reached the handler (T238).
    ok = send_feature(fd, [MSG_BT_CONTROL, BT_PAIR, cid])
    print(f"  SENT report 0x16/0x05 (PAIR) id {cid} via control SET_REPORT (accepted={ok}) -- the way Oasis does it.")

    if args.arm_only:
        time.sleep(1.0)
        st, fd = read_status(fd)
        print(f"after (immediate): {fmt(st)}")
        os.close(fd)
        return

    if args.handshake:
        # Mirror the captured Oasis sequence (T238): a CMD_STATUS precursor for this hand, then
        # PAIR, then SUSTAINED interaction -- Windows polled PAIRING_STATUS continuously and the
        # bond formed ~7 s after PAIR, so a single shot is not enough. Re-send PAIR periodically
        # and keep polling, surviving the radio re-enumeration throughout.
        MSG = MSG_BT_CONTROL
        def send(sub):
            nonlocal fd
            if not send_feature(fd, [MSG, sub, cid]):
                nf = reopen()
                if nf:
                    try: os.close(fd)
                    except OSError: pass
                    fd = nf
                    send_feature(fd, [MSG, sub, cid])
        print("  HANDSHAKE mode: CMD_STATUS precursor + sustained PAIR/poll, mirroring Oasis")
        def poll_02():
            # T240: report 0x02 (PAIRING_STATUS poll) is Output on the wire, not Feature -- Oasis
            # sent it 1263x over one session. write_output() (plain write(), no HIDIOCSFEATURE).
            nonlocal fd
            if not write_output(fd, [0x02, 0x08, cid]):
                nf = reopen()
                if nf:
                    try: os.close(fd)
                    except OSError: pass
                    fd = nf
                    print(f"    [radio re-enumerated -- the command landed on a discovering controller]")
        send(0x09)   # CMD_STATUS for this hand (Windows sent 16 09 01 before pairing)
        time.sleep(0.2)
        t0 = time.time()
        took = False
        last_pair = 0
        while time.time() - t0 < args.wait:
            now = time.time() - t0
            if now - last_pair >= 3.0:      # (re)send PAIR every 3 s across the discovery window
                # T240: the reference capture shows Windows sends a CMD_STATUS (0x09) for this
                # hand IMMEDIATELY before every PAIR, not just once at the start -- both the
                # first attempt and the retry got their own 0x09 precursor. Match that exactly.
                send(0x09)
                send(0x05)
                last_pair = now
            poll_02()                        # PAIRING_STATUS on report 0x02, as Output, as Oasis does
            st, fd = read_status(fd, 0.7, log_debug=True)    # CONTROLLER_STATUS read + BT debug log
            if st.get(cid) in (0x1, 0x2):
                print(f"\n  *** {NAME[cid]} is now {PKT[st[cid]]} at t+{now:.1f}s -- PAIRED FROM LINUX ***")
                took = True
                break
            print(f"    t+{now:4.0f}s  {fmt(st)}")
        try: os.close(fd)
        except OSError: pass
        if not took:
            print("\n  handshake did not complete. Next: the 0x02-report channel Windows also used")
            print("  (report id 0x02 vs our 0x16) may be a separate interface -- worth probing.")
        return

    # PASSIVE watch (T238, user insight): 0x17 status is STREAMED, so do NOT send status queries
    # while waiting -- each control SET_REPORT re-enumerates the radio and interrupts the pairing
    # in progress. Fire PAIR once, then just LISTEN, letting the headset find the controller
    # undisturbed. Reopen only if the fd genuinely dies.
    print(f"  fired once; now listening PASSIVELY for {NAME[cid]} to pair, up to {args.wait:.0f}s (radio left alone)...")
    t0 = time.time()
    took = False
    last_print = -1
    while time.time() - t0 < args.wait:
        now = time.time() - t0
        try:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                b = os.read(fd, 64)
                if b and len(b) >= 3 and b[0] == SUB_CONTROLLER_STATUS and b[1] == cid:
                    if b[2] in (0x1, 0x2):
                        print(f"\n  *** {NAME[cid]} is now {PKT[b[2]]} at t+{now:.1f}s -- PAIRED FROM LINUX ***")
                        took = True
                        break
        except OSError:
            nf = reopen()
            if nf:
                try: os.close(fd)
                except OSError: pass
                fd = nf
        if int(now) != last_print:
            last_print = int(now)
            if int(now) % 5 == 0:
                print(f"    t+{now:4.0f}s  listening...")
    try: os.close(fd)
    except OSError: pass
    if took:
        print("\n  *** THE LAST WINDOWS DEPENDENCY IS DEAD. G2 pairs from Linux. ***")
    else:
        print(f"\n  no pairing in {args.wait:.0f}s (passive). If the radio never re-enumerated on the")
        print("  PAIR itself, the controller was not in discovery when it fired; retry the pulse.")
    return

    # (old active-watch path kept below, unused)
    print(f"  watching for {NAME[cid]} to become paired, up to {args.wait:.0f}s...")
    t0 = time.time()
    took = False
    while time.time() - t0 < args.wait:
        st, fd = read_status(fd, 1.0)
        if st.get(cid) in (0x1, 0x2):
            print(f"\n  *** {NAME[cid]} is now {PKT[st[cid]]} at t+{time.time()-t0:.1f}s -- PAIRED FROM LINUX ***")
            took = True
            break
        print(f"    t+{time.time()-t0:4.0f}s  {fmt(st)}")
    try:
        os.close(fd)
    except OSError:
        pass

    if not took:
        print(f"\n  no transition in {args.wait:.0f}s. Not proven. Things to vary before concluding:")
        print("    - controller actually in discovery (slow pulse) when the command was sent?")
        print("    - id byte position: this assumes byte2; if it does nothing, the arg may live elsewhere")
        print("    - some stacks arm the radio with ONLINE_STATUS (0x04) first -- worth a try")
        print("  Recovery if it is now stuck unpaired: pair it once on Windows/Oasis (docs/03).")


main()
