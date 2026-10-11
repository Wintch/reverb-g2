#!/usr/bin/env python3
"""worn-tally.py <hello.log> -- per-hand summary of the hello_xr 1 Hz POSE lines (worn-leg.sh).

tracked_s  seconds with trk:OK
frozen_s   seconds that repeat the previous line's position AND orientation exactly while trk:OK
           (the "frozen but still TRACKED" pose of docs/135)
outliers   tracked samples farther than 2 m from the origin on any axis
"""
import re
import sys

PAT = re.compile(r"\| (left|right) \(([-+ .0-9]+) ([-+ .0-9]+) ([-+ .0-9]+)\) pos:\S+ trk:(\S+) (fwd\([^)]*\))")
hands = {"left": [], "right": []}
with open(sys.argv[1], errors="replace") as f:
    for line in f:
        if "POSE head" not in line:
            continue
        for h, x, y, z, trk, fwd in PAT.findall(line):
            hands[h].append(((x.strip(), y.strip(), z.strip(), fwd), trk == "OK"))
out = []
for h, s in hands.items():
    tracked = sum(1 for _, ok in s if ok)
    frozen = sum(1 for a, b in zip(s, s[1:]) if a[1] and b[1] and a[0] == b[0])
    outliers = sum(1 for p, ok in s if ok and max(abs(float(v)) for v in p[:3]) > 2.0)
    out.append("%s_n=%d %s_tracked_s=%d %s_frozen_s=%d %s_outliers=%d" % (h, len(s), h, tracked, h, frozen, h, outliers))
print(" ".join(out))
