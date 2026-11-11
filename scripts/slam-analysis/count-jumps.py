#!/usr/bin/env python3
"""Count pose discontinuities in a Basalt/Monado SLAM CSV.

A session-anchor reset is a single-sample teleport of metres; ordinary head motion between
consecutive samples is centimetres. So a frame-to-frame delta above the threshold is a reset,
not movement. Reported per worn minute so sessions of different length compare.

  count-jumps.py <csv> [threshold_m]
"""
import sys, math

path = sys.argv[1]
thr = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5

prev = None
t0 = t1 = None
n = 0
jumps = []
for line in open(path):
    if line.startswith('#'):
        continue
    f = line.split(',')
    if len(f) < 4:
        continue
    try:
        t = int(f[0]); x, y, z = float(f[1]), float(f[2]), float(f[3])
    except ValueError:
        continue
    n += 1
    if t0 is None:
        t0 = t
    t1 = t
    if prev is not None:
        d = math.dist((x, y, z), prev)
        if d > thr:
            jumps.append((t, d))
    prev = (x, y, z)

mins = (t1 - t0) / 1e9 / 60 if t0 and t1 and t1 > t0 else 0
print(f"  samples={n}  span={mins:.1f} min  rate={n/(mins*60):.0f} Hz" if mins else f"  samples={n}")
print(f"  jumps>{thr} m: {len(jumps)}   per minute: {len(jumps)/mins:.2f}" if mins else "")
if jumps:
    ds = sorted(d for _, d in jumps)
    print(f"  jump size: min={ds[0]:.2f} med={ds[len(ds)//2]:.2f} max={ds[-1]:.2f} m")
