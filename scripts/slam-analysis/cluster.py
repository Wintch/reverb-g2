#!/usr/bin/env python3
"""Group pose discontinuities into episodes.

The anchor guard's own doc comment warns that a slow-drift trip re-fires every ~2 s until head
motion brings the position back under the radius. So a raw reset COUNT can be one episode
stuttering, not N separate events. Anything within 5 s of the previous jump is the same episode.
"""
import sys, math

path = sys.argv[1]
prev = None
ts = []
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
    if prev is not None and math.dist(p, prev) > 0.5:
        ts.append(t)
    prev = p

eps = []
for t in ts:
    if eps and (t - eps[-1][-1]) / 1e9 < 5.0:
        eps[-1].append(t)
    else:
        eps.append([t])
print(f"  {len(ts)} jumps  ->  {len(eps)} episodes")
for e in eps:
    span = (e[-1] - e[0]) / 1e9
    print(f"    episode: {len(e):2d} jump(s) over {span:5.1f} s")
