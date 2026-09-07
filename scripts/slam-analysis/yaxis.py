#!/usr/bin/env python3
"""Trace the vertical axis for a sustained drop.

A correction tug is a transient: one sample out, then back. The wearer reported the viewpoint
falling ~1 m to the floor and STAYING there, which is a different failure -- so what matters is
not the jump but whether the level shifted and held. Prints a per-2s summary of height plus any
sustained level change.
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
        rows.append((int(f[0]), float(f[1]), float(f[2]), float(f[3])))
    except ValueError:
        pass

t0 = rows[0][0]
# Which axis is up? The one with the smallest spread is usually not; pick by convention check.
for i, name in ((1, 'x'), (2, 'y'), (3, 'z')):
    v = [r[i] for r in rows]
    print(f"  {name}: min={min(v):7.2f} max={max(v):7.2f} range={max(v)-min(v):6.2f}")

# 2-second buckets of each axis mean, so a sustained level shift is visible as a step.
print("\n  t(s)   x_mean   y_mean   z_mean")
bucket = {}
for t, x, y, z in rows:
    b = int((t - t0) / 1e9 / 2)
    bucket.setdefault(b, []).append((x, y, z))
prev = None
for b in sorted(bucket):
    vs = bucket[b]
    mx = sum(v[0] for v in vs) / len(vs)
    my = sum(v[1] for v in vs) / len(vs)
    mz = sum(v[2] for v in vs) / len(vs)
    flag = ""
    if prev:
        d = max(abs(mx - prev[0]), abs(my - prev[1]), abs(mz - prev[2]))
        if d > 0.4:
            flag = f"   <== step {d:.2f} m"
    print(f"  {b*2:4d}  {mx:7.2f}  {my:7.2f}  {mz:7.2f}{flag}")
    prev = (mx, my, mz)
