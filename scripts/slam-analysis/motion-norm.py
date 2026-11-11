#!/usr/bin/env python3
"""Resets normalised by how much the wearer actually moved.

Sessions of different length and different routines cannot be compared on resets-per-minute:
the reset fires on fast motion, so a livelier session earns more resets honestly. Path length
and time spent above a speed threshold are the fair denominators.

Jumps themselves are excluded from the path sum -- a 3 m teleport is not distance travelled.
"""
import sys, math

path = sys.argv[1]
thr = 0.5

prev = None; prevt = None
t0 = t1 = None
dist = 0.0
jumps = 0
fast_s = 0.0          # seconds spent above 1.0 m/s
speeds = []
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
    if t0 is None:
        t0 = t
    t1 = t
    if prev is not None:
        d = math.dist(p, prev)
        dt = (t - prevt) / 1e9
        if d > thr:
            jumps += 1
        elif dt > 0:
            dist += d
            v = d / dt
            speeds.append(v)
            if v > 1.0:
                fast_s += dt
    prev = p; prevt = t

mins = (t1 - t0) / 1e9 / 60
speeds.sort()
p95 = speeds[int(len(speeds) * 0.95)] if speeds else 0
print(f"  span {mins:5.1f} min | path {dist:6.1f} m | fast(>1 m/s) {fast_s:5.1f} s | v_p95 {p95:.2f} m/s")
print(f"  resets {jumps:3d}  ->  {jumps/mins:5.2f}/min   {jumps/dist*100 if dist else 0:5.2f}/100 m   "
      f"{jumps/fast_s*60 if fast_s else 0:5.2f}/fast-min")
