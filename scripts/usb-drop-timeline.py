#!/usr/bin/env python3
"""usb-drop-timeline.py - correlate headset USB hub drops with SteamVR / Steam / Oasis events.

Read-only. Sources (all optional, missing ones are skipped):
  kernel journal   usb <hub>: USB disconnect / new high-speed, error -71/-110, NVRM Xid,
                   Bluetooth G2 controller HID attach (hid-generic 0005:045E:066A)
  Steam            logs/content_log.txt (+ .previous): app start / exit
  SteamVR          logs/vrstartup.txt (SteamVR launch, VR_Init errors),
                   logs/vrcompositor(.previous).txt (Startup Complete / direct display),
                   logs/vrserver*.txt + vrstartup-linux*.txt (Oasis "Failed to get HID report" burst window)
  session tool     ~/vr/oasis-x11.log (up / down / result lines)

A "bounce" is a hub disconnect followed by the hub enumerating again within --bounce-secs
(the headset dropped and came back). A disconnect with no re-enumeration is an UNPLUG. Use
--manual to mark disconnects you caused by hand (they are excluded from the storm counts).

Usage:
  usb-drop-timeline.py [--boot 0] [--since 'YYYY-MM-DD HH:MM'] [--until '...'] [--hub 3-1]
                       [--manual 'YYYY-MM-DD HH:MM:SS' ...] [--window 10] [--no-events]
Exit status is always 0 (it is a report, not a check).
"""
import argparse
import bisect
import collections
import datetime as dt
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
LOGS = os.path.join(HOME, ".steam/debian-installation/logs")
OASIS_LOG = os.path.join(HOME, "vr/oasis-x11.log")
APP_NAMES = {
    "250820": "SteamVR", "1363430": "Propagation VR", "650000": "DOOM VFR",
    "502820": "Batman Arkham VR", "546560": "Half-Life Alyx", "617830": "Superhot VR",
    "450390": "The Lab", "3824490": "Oasis driver",
}


def parse_ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def parse_steamvr_ts(s):  # "Sat Oct 03 2026 22:13:51.452412"
    return dt.datetime.strptime(s[:24], "%a %b %d %Y %H:%M:%S")


def read_lines(path):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def kernel_events(boot, hub, ev):
    try:
        out = subprocess.run(
            ["journalctl", "-k", "-b", str(boot), "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception as e:  # noqa
        print("# journalctl failed: %s" % e, file=sys.stderr)
        return
    pre = re.escape("usb %s" % hub)
    last_ctl = None
    for line in out.splitlines():
        m = re.match(r"(\S+) \S+ kernel: (.*)", line)
        if not m:
            continue
        try:
            t = dt.datetime.fromisoformat(m.group(1)).astimezone().replace(tzinfo=None)
        except ValueError:
            continue
        msg = m.group(2)
        if re.match(pre + r": USB disconnect", msg):
            ev.append((t, "DROP", "hub %s USB disconnect" % hub))
        elif re.match(pre + r": new high-speed USB device", msg):
            ev.append((t, "REENUM", "hub %s enumerated again" % hub))
        elif re.match(pre + r"\.\d: (device not accepting address|device descriptor read).*error -(71|110)", msg) \
                or re.match(r"usb usb\d+-port\d+: (Cannot enable|unable to enumerate)", msg):
            ev.append((t, "USBERR", msg[:100]))
        elif re.match(r"usb 4-1: USB disconnect", msg):
            ev.append((t, "SS-DROP", "SuperSpeed hub 4-1 disconnect"))
        elif "NVRM: Xid" in msg:
            ev.append((t, "XID", msg[msg.index("Xid"):][:110]))
        elif re.search(r"hid-generic 0005:045E:066A\.\w+: hidraw\d+: BLUETOOTH", msg):
            if last_ctl is None or (t - last_ctl).total_seconds() > 5:
                ev.append((t, "CTRL", "G2 controller HID attached over host Bluetooth"))
            last_ctl = t


def steam_events(ev):
    running = {}
    for name in ("content_log.previous.txt", "content_log.txt"):
        for line in read_lines(os.path.join(LOGS, name)):
            m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] AppID (\d+) state changed : (.*)", line)
            if not m:
                continue
            t, app, flags = parse_ts(m.group(1)), m.group(2), m.group(3)
            run = "App Running" in flags
            if run and not running.get(app):
                ev.append((t, "APP-START", "%s (%s) started" % (APP_NAMES.get(app, "app"), app)))
            elif not run and running.get(app):
                ev.append((t, "APP-EXIT", "%s (%s) exited" % (APP_NAMES.get(app, "app"), app)))
            running[app] = run


def steamvr_events(ev):
    for name in ("vrstartup.txt",):
        for line in read_lines(os.path.join(LOGS, name)):
            if "vrstartup 2." in line and "startup with PID" in line:
                ev.append((parse_steamvr_ts(line), "VR-LAUNCH", "SteamVR (vrstartup) launched"))
            elif "VR_Init error, exiting" in line:
                ev.append((parse_steamvr_ts(line), "VR-INITERR", line.split("exiting:")[1].strip()[:80]))
    for name in ("vrcompositor.previous.txt", "vrcompositor.txt"):
        for line in read_lines(os.path.join(LOGS, name)):
            if "Startup Complete" in line:
                ev.append((parse_steamvr_ts(line), "VR-COMP-OK", "compositor Startup Complete"))
            elif "CannotDRMLeaseDisplay" in line or "Failed to acquire xlib display" in line:
                ev.append((parse_steamvr_ts(line), "VR-COMP-FAIL", line.split("]")[-1].strip()[:80]))


def oasis_log_events(ev):
    for line in read_lines(OASIS_LOG):
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)", line)
        if not m:
            continue
        t, msg = parse_ts(m.group(1)), m.group(2)
        if msg.startswith("=== up"):
            ev.append((t, "TOOL-UP", "jack-in-oasis-x11 up"))
        elif msg.startswith("=== down"):
            ev.append((t, "TOOL-DOWN", "jack-in-oasis-x11 down"))
        elif msg.startswith("--- result:"):
            ev.append((t, "TOOL-RESULT", msg[4:60]))


def hid_spam_window():
    """First/last retained 'Failed to get HID report' time. The spam rotates the Steam logs
    within minutes, so this is only the retained window, not the real onset."""
    first = last = None
    n = 0
    for name in ("vrserver.previous.txt", "vrserver.txt"):
        for line in read_lines(os.path.join(LOGS, name)):
            if "Failed to get HID report" in line:
                try:
                    t = parse_steamvr_ts(line)
                except ValueError:
                    continue
                n += 1
                first = t if first is None else min(first, t)
                last = t if last is None else max(last, t)
    return first, last, n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--boot", default="0")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--hub", default="3-1")
    ap.add_argument("--manual", action="append", default=[], help="timestamp of a disconnect caused by hand")
    ap.add_argument("--window", type=int, default=10, help="seconds for drop/event association")
    ap.add_argument("--bounce-secs", type=int, default=5)
    ap.add_argument("--no-events", action="store_true", help="summary only, no merged listing")
    a = ap.parse_args()

    ev = []
    kernel_events(a.boot, a.hub, ev)
    steam_events(ev)
    steamvr_events(ev)
    oasis_log_events(ev)
    ev.sort(key=lambda e: e[0])
    since = dt.datetime.strptime(a.since, "%Y-%m-%d %H:%M") if a.since else None
    until = dt.datetime.strptime(a.until, "%Y-%m-%d %H:%M") if a.until else None
    k_times = [e[0] for e in ev if e[1] == "REENUM"]
    manual = [parse_ts(m) for m in a.manual]

    # Classify drops.
    drops = []
    for t, kind, _ in ev:
        if kind != "DROP":
            continue
        if (since and t < since) or (until and t > until):
            continue
        i = bisect.bisect_left(k_times, t)
        bounced = i < len(k_times) and (k_times[i] - t).total_seconds() <= a.bounce_secs
        is_manual = any(abs((t - m).total_seconds()) <= 3 for m in manual)
        cls = "MANUAL" if is_manual else ("BOUNCE" if bounced else "UNPLUG?")
        drops.append((t, cls))

    others = [e for e in ev if e[1] in ("APP-START", "APP-EXIT", "VR-LAUNCH", "VR-INITERR", "VR-COMP-OK",
                                         "VR-COMP-FAIL", "TOOL-UP", "TOOL-DOWN", "XID")]
    o_times = [e[0] for e in others]

    def near(t):
        res = []
        i = bisect.bisect_left(o_times, t - dt.timedelta(seconds=a.window))
        while i < len(others) and others[i][0] <= t + dt.timedelta(seconds=a.window):
            res.append(others[i])
            i += 1
        return res

    if not a.no_events:
        print("== merged timeline (DROP lines carry their classification) ==")
        dset = {t: c for t, c in drops}
        for t, kind, msg in ev:
            if (since and t < since) or (until and t > until):
                continue
            if kind == "REENUM":
                continue  # implied by the BOUNCE class
            if kind == "DROP":
                if t not in dset:
                    continue
                print("%s  >> DROP[%s] %s" % (t.strftime("%m-%d %H:%M:%S"), dset[t], msg))
            else:
                print("%s     %-12s %s" % (t.strftime("%m-%d %H:%M:%S"), kind, msg))
        print()

    bounces = [t for t, c in drops if c == "BOUNCE"]
    print("== summary (boot %s, hub %s) ==" % (a.boot, a.hub))
    print("disconnects: %d  | bounces (storm events): %d  | manual: %d  | unplug-without-reenum: %d" % (
        len(drops), len(bounces), sum(1 for _, c in drops if c == "MANUAL"),
        sum(1 for _, c in drops if c == "UNPLUG?")))
    if bounces:
        span_h = max((bounces[-1] - bounces[0]).total_seconds() / 3600, 1 / 60)
        print("first/last bounce: %s / %s (%.2f h span, %.1f per hour inside the span)" % (
            bounces[0].strftime("%m-%d %H:%M:%S"), bounces[-1].strftime("%m-%d %H:%M:%S"), span_h, len(bounces) / span_h))
        per_h = collections.Counter(t.strftime("%m-%d %Hh") for t in bounces)
        print("per hour: " + "  ".join("%s=%d" % kv for kv in sorted(per_h.items())))
        # bursts: gap > 120 s starts a new burst
        bursts, cur = [], [bounces[0]]
        for t in bounces[1:]:
            if (t - cur[-1]).total_seconds() > 120:
                bursts.append(cur)
                cur = [t]
            else:
                cur.append(t)
        bursts.append(cur)
        big = [b for b in bursts if len(b) >= 5]
        print("bursts (gap<=120 s): %d, of which >=5 drops: %s" % (
            len(bursts), "; ".join("%s-%s x%d" % (b[0].strftime("%H:%M"), b[-1].strftime("%H:%M"), len(b)) for b in big) or "none"))
        gaps = [(b - a_).total_seconds() for a_, b in zip(bounces, bounces[1:])]
        if gaps:
            gs = sorted(gaps)
            print("gap between consecutive bounces: min %ds, median %ds, max %ds" % (gs[0], gs[len(gs) // 2], gs[-1]))
        # association with software events
        hit = [(t, near(t)) for t in bounces]
        nhit = sum(1 for _, n in hit if n)
        total = (bounces[-1] - bounces[0]).total_seconds() or 1
        w = dt.timedelta(seconds=a.window)
        covered, cur_end = 0.0, None
        for t in o_times:
            lo, hi = max(t - w, bounces[0]), min(t + w, bounces[-1])
            if hi <= lo:
                continue
            if cur_end is None or lo > cur_end:
                covered += (hi - lo).total_seconds()
                cur_end = hi
            elif hi > cur_end:
                covered += (hi - cur_end).total_seconds()
                cur_end = hi
        exp = min(1.0, covered / total)
        print("bounces within +-%ds of a Steam/SteamVR/tool event: %d of %d (%.0f%%); naive chance level for events spread uniformly "
              "over the same span would be about %.0f%%" % (a.window, nhit, len(bounces), 100.0 * nhit / len(bounces), 100 * exp))
        kinds = collections.Counter(e[1] for _, n in hit for e in n)
        print("   which events: " + ", ".join("%s=%d" % kv for kv in kinds.most_common()))
        print("   (association is not causation: see docs/139 for how this was read)")
    ctl = [e for e in ev if e[1] == "CTRL" and (not since or e[0] >= since) and (not until or e[0] <= until)]
    if ctl and bounces:
        cn = sum(1 for e in ctl if any(abs((e[0] - b).total_seconds()) <= a.window for b in bounces))
        print("G2 controller BT attach events: %d, within +-%ds of a bounce: %d (controllers are on the host BT adapter, "
              "they should NOT follow hub bounces)" % (len(ctl), a.window, cn))
    xid = [e for e in ev if e[1] == "XID"]
    if xid:
        print("NVIDIA Xid events: " + "; ".join("%s %s" % (e[0].strftime("%H:%M:%S"), e[2][:60]) for e in xid))
    err = [e for e in ev if e[1] == "USBERR"]
    if err:
        print("USB enumeration errors on the hub children (-71/-110): " + "; ".join(
            "%s" % e[0].strftime("%H:%M:%S") for e in err))
    f, l, n = hid_spam_window()
    if n:
        print("Oasis 'Failed to get HID report' lines still in retained Steam logs: %d, window %s -> %s "
              "(the spam rotates the logs, so the real onset is earlier than the first retained line)" % (
                  n, f.strftime("%H:%M:%S"), l.strftime("%H:%M:%S")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
