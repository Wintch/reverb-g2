#!/usr/bin/env python3
"""Turn a constellation session's logs into the numbers this project actually argues about.

Every measurement in T223/T224 was computed ad hoc, one grep at a time, while a wearer stood
waiting. This is those greps, named and in one place, so a measurement window costs a command
instead of a conversation.

  ./constellation-session-report.py [service.log] [player.log] [--since HH:MM:SS] [--until HH:MM:SS]

Defaults to ~/vr/jack-in-wayland.log and the newest ~/vr/logs/play360-*.log.

WHAT IT WILL NOT DO: interpret zeros. A window whose controllers were asleep, or whose headset
sat on a desk, produces the same zeros as a window that measured something -- see docs/59's
invalidation rules. The report says "no data" where it cannot tell, and it is on the reader to
know which windows were real.
"""
import argparse, math, os, re, statistics, sys, glob

LC, RC = "HP Reverb G2 Left Controller", "HP Reverb G2 Right Controller"


def newest(pattern):
    files = glob.glob(os.path.expanduser(pattern))
    return max(files, key=os.path.getmtime) if files else None


def pct(n, d):
    return f"{100.0 * n / d:5.1f}%" if d else "  n/a"


def read(path):
    with open(path, errors="ignore") as f:
        return f.read().splitlines()


def section(title):
    print(f"\n== {title} " + "=" * max(0, 58 - len(title)))


def report_service(lines):
    joined = "\n".join(lines)

    section("session validity")
    builder = "wmr" if "Using builder wmr" in joined else "NOT wmr -- SESSION INVALID"
    reg = joined.count("Registered with constellation tracker")
    print(f"  builder                 {builder}")
    print(f"  constellation devices   {reg}/2" + ("" if reg == 2 else "   <-- a device missing means no hot-add; relaunch"))
    for hand, name in ((LC, "left"), (RC, "right")):
        vals = re.findall(rf"battery raw byte \[{re.escape(hand)}\]: \d+ -> (\d+)", joined)
        if vals:
            first, last = int(vals[0]), int(vals[-1])
            warn = "  <-- BELOW THE 85 ALARM" if last < 85 else ""
            print(f"  battery {name:<15} {first} -> {last}{warn}")

    section("positional presence (the headline metric)")
    print("  sampled at the driver's own output, once per 90 get_tracked_pose calls")
    for hand, name in ((LC, "left"), (RC, "right")):
        rows = [l for l in lines if f"get_tracked_pose [{hand}]" in l]
        yes = sum(1 for l in rows if "position_tracked=yes" in l)
        print(f"  {name:<6} {pct(yes, len(rows))}  ({yes}/{len(rows)})")
    if not any(f"get_tracked_pose [{LC}]" in l for l in lines):
        print("  no get_tracked_pose lines at all -- the driver logs these only once a sample")
        print("  has ever arrived, so this means ZERO samples were delivered, not zero presence.")

    section("where candidate poses die")
    counts = {
        "tracker gravity gate (0084, pre-delivery)": joined.count("tracker gravity gate:"),
        "camera-range gate (0085, implausible vs camera)": joined.count("camera-range gate:"),
        "world-range absurdity guard (0085)": joined.count("absurdity guard"),
        "no world pose for the frame (0086)": joined.count("has no world pose"),
        "driver gravity gate (0074)": sum(1 for l in lines if "gravity gate [" in l),
        "yaw prior (0074)": sum(1 for l in lines if "yaw prior [" in l),
        "POSE_MATCH_GOOD lost after refinement": joined.count("not publishing it"),
    }
    for k, v in counts.items():
        print(f"  {v:6d}  {k}")
    print("  NOTE: these are LOG LINES, and most are throttled (every 50/100). Compare them to")
    print("  each other and across arms, never read one as an absolute count of events.")

    section("recovery ladder")
    print(f"  {joined.count('succeeded with blob recovery'):6d}  blob recovery succeeded")
    print(f"  {joined.count('succeeded with seeded recovery'):6d}  seeded recovery succeeded (0077/0082)")
    for dev, name in ((0, "left"), (1, "right")):
        att = re.findall(rf"seeded recovery for device {dev} .*?(\d+) attempts", joined)
        if att:
            print(f"          seeded attempts {name}: >= {att[-1]} (throttled counter, floor not total)")

    section("yaw layer (0086's instrument)")
    locks = [l for l in lines if "yaw lock ACQUIRED" in l]
    status = [l for l in lines if "yaw lock status" in l]
    if not locks and not status:
        print("  no yaw-lock lines -- either patch 0086 is not in this binary, or no gated")
        print("  sample was ever checked (the gravity gate must be ON for the lock to form).")
    for l in locks:
        i = l.find("yaw lock")
        print("  " + l[i:i + 110])
    for hand, name in ((LC, "left"), (RC, "right")):
        last = [l for l in status if hand in l]
        if last:
            state = "LOCKED" if "LOCKED" in last[-1] else "not locked"
            print(f"  {name:<6} {state}   (last heartbeat of {len(last)})")
    errs = [float(m) for m in re.findall(r"solve-yaw correct \[[^\]]+\]: error=([-0-9.]+)", joined)]
    if errs:
        a = sorted(abs(e) for e in errs)
        bands = [(0, 10), (10, 20), (20, 30), (30, 60), (60, 181)]
        print(f"  solve-yaw error distribution, n={len(a)}:")
        for lo, hi in bands:
            n = sum(1 for v in a if lo <= v < hi)
            if n:
                print(f"    {lo:3d}-{hi:3d} deg  {pct(n, len(a))}  ({n})")
        print("  T224: the ghost's own yaw error sits INSIDE the legitimate band, so a global")
        print("  threshold cannot separate them. Read this distribution before tuning anything.")

    section("channel health")
    # READ THIS COUNT CORRECTLY, because it used to be read wrong for months. A companion read
    # failure does NOT measure the storm: before patch 0090 a single re-enumeration killed the
    # hidraw fd permanently, so every later read failed forever and the counter measured our own
    # polling of a corpse (docs/61, T227 -- and it is why T183 saw 400-600 failures/s during
    # stretches where lsusb already read 5/5). With 0090 the driver reopens the device, so the
    # honest storm proxy is the RECONNECT count -- one per survived re-enumeration -- and the
    # failure count is just how noisy each detection was.
    comp = joined.count("Error reading from companion")
    recon = re.findall(r"Companion device RECONNECTED on (\S+) after (\d+) ms dead", joined)
    print(f"  {comp:6d}  companion HID read failures")
    if recon:
        dead = sorted(int(d) for _, d in recon)
        mid = dead[len(dead) // 2]
        print(f"  {len(recon):6d}  companion RECONNECTS (survived re-enumerations; p50 {mid} ms dead,")
        print(f"          worst {dead[-1]} ms) -- this is the storm rate, not the failure count above")
    elif comp > 100:
        print("          <-- many failures and NO reconnect line: either this is a pre-0090 build,")
        print("          in which case the channel died once and everything on it (panel control,")
        print("          IPD, XR_EXT_user_presence) has been dead since, or the reopen is failing.")
    if joined.count("could NOT be re-synced"):
        print(f"  {joined.count('could NOT be re-synced'):6d}  reconnects left presence on its pre-outage value (expected on this")
        print("          unit: the device answers -1 to a feature read of the proximity report)")
    prox = re.findall(r"Proximity sensor (\d+) IPD: (\d+)", joined)
    if prox:
        print(f"  {len(prox):6d}  proximity messages (change-driven: few is normal, zero after a")
        print(f"          transition means the channel died, not that nothing moved)")
        print(f"          raw values seen: {sorted({p[0] for p in prox})}")
    for l in lines:
        if "User presence:" in l:
            print("  " + l[l.find("User presence:"):][:110])


def report_player(lines):
    rx = re.compile(
        r"\[(\d\d):(\d\d):(\d\d)\.\d+\].*POSE head \(([-+0-9.]+) ([-+0-9.]+) ([-+0-9.]+)\)"
        r".*left \(([-+0-9.]+) ([-+0-9.]+) ([-+0-9.]+)\) pos:\S+ trk:(\S+)"
        r".*right \(([-+0-9.]+) ([-+0-9.]+) ([-+0-9.]+)\) pos:\S+ trk:(\S+)")
    rows = []
    for l in lines:
        m = rx.search(l)
        if m:
            g = m.groups()
            t = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2])
            rows.append((t, tuple(map(float, g[3:6])), tuple(map(float, g[6:9])), g[9],
                         tuple(map(float, g[10:13])), g[13]))
    if not rows:
        print("  no POSE lines -- was the player running with stats on?")
        return

    section("head pose vs the tracking origin")
    d = [math.dist((0, 0, 0), r[1]) for r in rows]
    print(f"  distance from origin: p50 {sorted(d)[len(d)//2]:.2f} m   max {max(d):.2f} m")
    if max(d) > 5.0:
        print("  >5 m: before patch 0085 this ALONE silently killed all controller position.")
        print("  With 0085 it is survivable, but it still means the SLAM origin has walked off.")

    section("delivered controller position, tracked samples only")
    print("  CAUTION: these lines are ~1 s apart, so a 'jump' here includes whatever the hand")
    print("  genuinely moved in that second. T223 published a p50 that was inflated for exactly")
    print("  this reason; the wearer's own estimate was less than half of it. Treat as an upper bound.")
    for idx, flag, name in ((2, 3, "left"), (4, 5, "right")):
        pts = [r[idx] for r in rows if r[flag] == "OK"]
        print(f"  {name:<6} tracked samples {len(pts):4d}/{len(rows)}  ({pct(len(pts), len(rows))} of frames)")
        jumps = [(math.dist(a, b), (b[0]-a[0], b[1]-a[1], b[2]-a[2])) for a, b in zip(pts, pts[1:])]
        big = [j for j in jumps if j[0] > 0.05]
        if big:
            mags = sorted(j[0] for j in big)
            horiz = statistics.mean(math.hypot(j[1][0], j[1][2]) / j[0] for j in big)
            print(f"         steps >5cm: {len(big)}  p50 {mags[len(mags)//2]:.3f} m  max {mags[-1]:.3f} m"
                  f"  horizontal {100*horiz:.0f}%")
            print("         (a high horizontal fraction is the yaw-ghost signature: a rotation about")
            print("          the vertical axis moves a hand sideways and leaves its height alone)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("service", nargs="?", default=os.path.expanduser("~/vr/jack-in-wayland.log"))
    ap.add_argument("player", nargs="?", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.service):
        sys.exit(f"no service log at {args.service}")
    print(f"service log: {args.service}")
    report_service(read(args.service))

    player = args.player or newest("~/vr/logs/play360-*.log")
    if player and os.path.exists(player):
        print(f"\nplayer log: {player}")
        report_player(read(player))
    else:
        print("\n(no player log found -- skipping the delivered-pose section)")


if __name__ == "__main__":
    main()
