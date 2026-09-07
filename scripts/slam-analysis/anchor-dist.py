#!/usr/bin/env python3
"""How far from the session anchor does the wearer legitimately get?

The guard cannot tell "walked 2 m" from "drifted 2 m" -- it only measures distance from the
session's first accepted pose. So a radius set BELOW the play area's own envelope will fire on
honest movement. This prints the distance-from-anchor distribution, and where the resets sat in
it, to decide whether a given radius is even admissible for this room.
"""
import sys, math

path = sys.argv[1]
rows = []
for line in open(path):
    if line.startswith('#'):
        continue
    f = line.split(',')
    if len(f) < 4:
        continue
    try:
        rows.append((int(f[0]), (float(f[1]), float(f[2]), float(f[3]))))
    except ValueError:
        pass

anchor = rows[0][1]
t0 = rows[0][0]
d = [math.dist(p, anchor) for _, p in rows]
s = sorted(d)
def q(f): return s[int(len(s) * f)]
print(f"  distance from session anchor: p50={q(.5):.2f} p90={q(.9):.2f} p99={q(.99):.2f} max={max(s):.2f} m")

# Jump instants, with the distance the wearer had reached just before each.
prev = None
print("\n  reset  t(s)   dist_before   jump")
for i, (t, p) in enumerate(rows):
    if prev is not None:
        j = math.dist(p, prev)
        if j > 0.5:
            print(f"         {(t-t0)/1e9:5.0f}   {d[i-1]:8.2f} m   {j:.2f} m")
    prev = p
