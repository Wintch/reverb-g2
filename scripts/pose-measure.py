#!/usr/bin/env python3
"""Report what the headset's tracked pose is actually doing, from the SLAM pose CSV.

Answers three questions the raw numbers do not answer on their own:

  1. Where is the headset right now, and in particular how high (the floor-calibration
     question -- see docs/03 and NEXT-STEP.md: Monado has no floor calibration, it assumes
     the floor sits 1.6 m below wherever the headset was when Basalt initialised).
  2. Is that number still trustworthy? Measured 2026-08-11: with the headset static, the
     pose can run away super-quadratically -- 10 cm at t+1.4 s, 475 m at t+73 s. A height
     read after that has started is worthless, and nothing about the number itself says so.
  3. If it is running away, how fast and in which direction. Measured runs on 2026-08-11
     went away along x in some and along y in others, so the dominant axis is a clue to
     collect, not a diagnosis: six runs that night had times-to-25-cm ranging from 2.2 s to
     50.8 s, and the spread within otherwise-identical configurations was larger than the
     difference between configurations. Do not conclude from one run.

Usage:
    ./pose-measure.py                 # newest ~/vr/logs/slam-*/ run
    ./pose-measure.py <dir-or-csv>    # a specific run
    ./pose-measure.py --window 5      # only consider the first N seconds (default: all)

The CSV is written by monado-service when SLAM_WRITE_CSVS=1, which jack-in-wayland.sh sets
by default. Column layout is upstream Basalt's: timestamp_ns, px, py, pz, qw, qx, qy, qz.
"""
import csv
import math
import sys
from pathlib import Path

VR = Path.home() / "vr"

# Monado's b_space_overseer_legacy_setup() places LOCAL 1.6 m above STAGE, and the WMR
# driver does not implement a driver-provided stage space, so STAGE == the tracking origin.
NOMINAL_EYE_HEIGHT_M = 1.6

# Past this, treat the run as diverged rather than drifting. Chosen from measurement, not
# taste: a healthy static run on this hardware stayed inside 2-4 cm over 132 s, so anything
# beyond a quarter of a metre with the headset still is a different phenomenon, not drift.
DIVERGED_M = 0.25


def newest_run():
    runs = sorted(VR.glob("logs/slam-*/tracking.csv"), key=lambda p: p.stat().st_mtime)
    if not runs:
        sys.exit(f"No SLAM run found under {VR}/logs/. Start a session with "
                 f"./jack-in-wayland.sh 1 6dof first (it enables SLAM_WRITE_CSVS).")
    return runs[-1]


def load(path, window_s=None):
    rows = list(csv.reader(open(path)))
    data = [r for r in rows[1:] if len(r) >= 8]
    if not data:
        sys.exit(f"{path} has no samples yet -- is the session actually up?")
    t0 = int(data[0][0])
    out = []
    for r in data:
        t = (int(r[0]) - t0) / 1e9
        if window_s is not None and t > window_s:
            break
        out.append((t, float(r[1]), float(r[2]), float(r[3])))
    return out


def main():
    args = [a for a in sys.argv[1:]]
    window = None
    if "--window" in args:
        i = args.index("--window")
        window = float(args[i + 1])
        del args[i:i + 2]

    path = Path(args[0]) if args else newest_run()
    if path.is_dir():
        path = path / "tracking.csv"

    s = load(path, window)
    dur = s[-1][0]
    print(f"run:      {path.parent.name}")
    print(f"samples:  {len(s)}  over {dur:.1f} s  ({len(s)/dur:.1f} Hz)" if dur > 0 else f"samples: {len(s)}")

    # Displacement from the origin, which IS the tracking origin: with the headset started
    # on the floor, y is height above the floor directly.
    def norm(p):
        return math.dist(p, (0.0, 0.0, 0.0))

    first, last = s[0], s[-1]
    print()
    print(f"first sample  t=+{first[0]:.2f}s   x={first[1]:+.3f}  y={first[2]:+.3f}  z={first[3]:+.3f}")
    print(f"last  sample  t=+{last[0]:.2f}s   x={last[1]:+.3f}  y={last[2]:+.3f}  z={last[3]:+.3f}")

    # When did it leave a plausible neighbourhood of where it started?
    crossed = None
    for t, x, y, z in s:
        if norm((x, y, z)) > DIVERGED_M:
            crossed = t
            break

    print()
    if crossed is None:
        span = max(norm((x, y, z)) for _, x, y, z in s)
        print(f"VERDICT: stable. Never left {DIVERGED_M*100:.0f} cm of the origin "
              f"(max {span*100:.1f} cm over {dur:.1f} s).")
        print()
        print("Height reading (valid, the pose is not running away):")
        print(f"  head is {last[2]:+.3f} m above the tracking origin.")
        print()
        print("  If the session was STARTED with the headset on the floor, that y is the")
        print("  headset's height above the floor, and the floor is already at y=0 -- no")
        print(f"  correction needed. Monado's own assumption is {NOMINAL_EYE_HEIGHT_M} m; if the")
        print("  headset was instead at head height at startup, the correction is:")
        print(f"    XRT_TRACKING_ORIGIN_OFFSET_Y = (real height at startup) - {NOMINAL_EYE_HEIGHT_M}")
    else:
        print(f"VERDICT: RUNAWAY. Left {DIVERGED_M*100:.0f} cm at t=+{crossed:.2f}s, "
              f"reached {norm(last[1:]):.1f} m by t=+{dur:.1f}s.")
        print()
        print("  Any height read after that point is meaningless. Re-run and take the")
        print("  reading inside the first second, or fix the runaway first.")
        # Which axis is running away, and is it the one that reads as 'drifting left'?
        axes = sorted(zip("xyz", last[1:]), key=lambda kv: -abs(kv[1]))
        dom, val = axes[0]
        print()
        print(f"  dominant axis: {dom} = {val:+.1f} m "
              f"({abs(val)/norm(last[1:])*100:.0f}% of the total)")
        if dom == "x":
            print("  An x-axis runaway of the world is perceived by the wearer as sliding")
            print("  sideways, which resembles the drift reported in Steam titles -- but")
            print("  measured runs have gone away in x AND in y, so do not treat a single")
            print("  dominant axis as identifying the cause. Collect several runs first.")
        # Growth law: p ~ t^n. n≈2 is a constant unmodelled acceleration (double integration
        # of a bias); n>2 means the attitude error is growing too, so gravity leaks in
        # progressively.
        mid = s[len(s) // 2]
        if mid[0] > 0 and norm(mid[1:]) > 0 and dur > mid[0]:
            n = math.log(norm(last[1:]) / norm(mid[1:])) / math.log(dur / mid[0])
            print(f"  growth exponent: p ~ t^{n:.1f}  "
                  f"({'≈2: constant unmodelled acceleration' if n < 2.4 else '>2: attitude error growing too'})")


if __name__ == "__main__":
    main()
