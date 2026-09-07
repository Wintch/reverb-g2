#!/usr/bin/env python3
"""Measure only the WORN segment of an A/B arm.

  worn-window.py <tracking.csv> <summon_monotonic_ns> [worn_seconds]

Both ends of a session are contaminated: before the summon the headset sits wherever the arm
puts it, and after the wearer takes it off it goes back on the table -- which is the degenerate
scene that invents tens of metres. Measuring the whole file mixes all three.

Prints the same measures as motion-norm.py, restricted to [summon, summon+worn], plus a sanity
line confirming the CSV clock and the marker are the same clock (they must overlap; if the window
catches no samples that assumption is wrong and the number would be silently meaningless).
"""
import math
import sys

path = sys.argv[1]
mark = int(sys.argv[2])
worn = float(sys.argv[3]) if len(sys.argv) > 3 else 240.0
end = mark + int(worn * 1e9)

rows = []
allts = []
for line in open(path):
    if line.startswith('#'):
        continue
    f = line.split(',')
    if len(f) < 4:
        continue
    try:
        t = int(f[0]); p = (float(f[1]), float(f[2]), float(f[3]))
    except ValueError:
        continue
    allts.append(t)
    if mark <= t <= end:
        rows.append((t, p))

if not allts:
    print("  no samples at all")
    sys.exit(1)
print(f"  csv clock spans {allts[0]/1e9:.0f}..{allts[-1]/1e9:.0f} s; marker at {mark/1e9:.0f} s")
if not rows:
    print("  !! the worn window caught NO samples -- marker and CSV are not the same clock")
    sys.exit(1)

prev = None
dist = 0.0
jumps = []
fast_s = 0.0
speeds = []
xs, ys, zs = [], [], []
for t, p in rows:
    xs.append(p[0]); ys.append(p[1]); zs.append(p[2])
    if prev is not None:
        d = math.dist(p, prev[1])
        dt = (t - prev[0]) / 1e9
        if d > 0.5:
            jumps.append(d)
        elif dt > 0:
            dist += d
            v = d / dt
            speeds.append(v)
            if v > 1.0:
                fast_s += dt
    prev = (t, p)

mins = (rows[-1][0] - rows[0][0]) / 1e9 / 60
speeds.sort()
p95 = speeds[int(len(speeds) * 0.95)] if speeds else 0
print(f"  worn {mins:4.1f} min | path {dist:6.1f} m | fast(>1 m/s) {fast_s:5.1f} s | v_p95 {p95:.2f} m/s")
print(f"  ranges  x {max(xs)-min(xs):.2f}  y {max(ys)-min(ys):.2f}  z {max(zs)-min(zs):.2f} m")
print(f"  resets {len(jumps):3d}  ->  {len(jumps)/mins if mins else 0:5.2f}/min   "
      f"{len(jumps)/dist*100 if dist else 0:5.2f}/100 m")
