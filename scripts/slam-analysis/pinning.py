#!/usr/bin/env python3
"""Does the output position stay pinned at the guard radius after the first trip?

The guard's own doc comment warns that with RESET_OFFSET_CARRY on, a reset restarts the VIO but
leaves the OUTPUT position wherever the drift carried it -- i.e. at the radius. If that is what
happens here, distance-from-anchor should step up to the radius at the first trip and stay
there, and the "storm" is not new drift but the session being pinned against the boundary.
"""
import sys, math

path = sys.argv[1]
radius = float(sys.argv[2])
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
buckets = {}
for t, p in rows:
    buckets.setdefault(int((t - t0) / 1e9 / 30), []).append(math.dist(p, anchor))

print(f"  radius {radius:.2f} m -- distance from session anchor, per 30 s")
print("   t(s)   p50    p90    max   | bar = p50 as fraction of radius")
for b in sorted(buckets):
    v = sorted(buckets[b])
    p50 = v[len(v)//2]; p90 = v[int(len(v)*.9)]; mx = v[-1]
    bar = "#" * int(round(p50 / radius * 40))
    print(f"  {b*30:5d}  {p50:5.2f}  {p90:5.2f}  {mx:5.2f}  | {bar}")
