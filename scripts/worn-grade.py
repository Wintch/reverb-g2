#!/usr/bin/env python3
"""worn-grade.py -- grade a WORN (headset on, real title) 6dof run from its archived artifacts.

Companion to soak-grade.py (which grades at-rest player soaks). A worn run is archived by hand as
~/vr/logs/soak/<tag>-{tracking,timing}.csv plus <tag>-jack-in.log (or .log.gz). Per run this prints:
raw Basalt position excursion (max |p| from the first row, per 30 s bucket), camera rate per minute
(rows/60 s -- dips mean the frontend starved), frontend and backend latency percentiles per minute
from timing.csv, the speed-guard trip count ("Tracker diverged") and Basalt's two numeric warning
counts, `d_res_d_p/xi is not valid` and `det(Q1Jl) == 0, skipping backsubstitution`.

Read the two warning counts only as SAME-CONDITION A/B columns (same room, same light, same CPU
load). They are not a darkness or runaway detector: the base config at rest logged 45 245 `d_res`
lines in a lit room (143 landmarks p50) against 2 in the dark (0 landmarks) -- the count tracks how
many landmarks the backend is optimising. `det(Q1Jl)` is the P2/recall-specific one (17-40x base in
the same room). CPU contention also inflates both (2026-08-29 JN100: 1 252 -> 9 697 in 3 min).
docs/80, 2026-08-29 sections.

Usage: worn-grade.py TAG [TAG ...]      (looks in ~/vr/logs/soak by default; -d DIR to change)
"""
import argparse, csv, gzip, math, os, re, sys

def pct(v, p):
    if not v: return float("nan")
    v = sorted(v); return v[min(len(v) - 1, int(p / 100 * len(v)))]

def open_log(path):
    if os.path.exists(path): return open(path, "r", errors="replace")
    if os.path.exists(path + ".gz"): return gzip.open(path + ".gz", "rt", errors="replace")
    return None

def grade(d, tag):
    print(f"=== {tag}")
    tr = os.path.join(d, f"{tag}-tracking.csv")
    if os.path.exists(tr):
        rows = [r for r in csv.reader(open(tr)) if len(r) >= 4 and not r[0].startswith("#") and r[0].strip().isdigit()]
        t0 = int(rows[0][0]); x0, y0, z0 = map(float, rows[0][1:4])
        bucket, per_min, gmax, gt = {}, {}, 0.0, 0.0
        for r in rows[1:]:
            t = (int(r[0]) - t0) / 1e9
            dd = math.dist((float(r[1]), float(r[2]), float(r[3])), (x0, y0, z0))
            b = int(t // 30); bucket[b] = max(bucket.get(b, 0.0), dd)
            per_min[int(t // 60)] = per_min.get(int(t // 60), 0) + 1
            if dd > gmax: gmax, gt = dd, t
        dur = (int(rows[-1][0]) - t0) / 1e9
        print(f"  duration {dur/60:.1f} min, rows {len(rows)}, raw position max {gmax:.2f} m at t={gt:.0f}s, final {math.dist(tuple(map(float, rows[-1][1:4])), (x0,y0,z0)):.2f} m")
        worst = sorted(bucket.items(), key=lambda kv: -kv[1])[:4]
        print("  worst 30 s buckets: " + ", ".join(f"{k*30}-{k*30+30}s {v:.1f} m" for k, v in sorted(worst)))
        low = [f"min {m} {n/60:.1f} Hz" for m, n in sorted(per_min.items()) if n / 60 < 27 and m < max(per_min)]
        print("  camera rate: " + ("30 Hz throughout" if not low else "dips: " + ", ".join(low)))
    else:
        print("  (no tracking.csv)")
    tm = os.path.join(d, f"{tag}-timing.csv")
    if os.path.exists(tm):
        rows = list(csv.reader(open(tm))); h = [c.strip("#") for c in rows[0]]; ix = {n: i for i, n in enumerate(h)}
        fe = [n for n in h if n.startswith("frontend_")]; be = [n for n in h if n.startswith("backend_")]
        t0 = int(rows[1][ix["frames_original_timestamp"]]); per = {}
        for r in rows[1:]:
            try:
                t = (int(r[ix["frames_original_timestamp"]]) - t0) / 1e9
                f = (int(r[ix[fe[-1]]]) - int(r[ix[fe[0]]])) / 1e6
                oa, ob = int(r[ix[be[0]]]), int(r[ix[be[-1]]]); o = (ob - oa) / 1e6 if oa > 0 and ob > 0 else None
            except (ValueError, IndexError, KeyError): continue
            if not (0 <= f < 5000): continue
            m = int(t // 60); per.setdefault(m, ([], [])); per[m][0].append(f)
            if o is not None and 0 <= o < 20000: per[m][1].append(o)
        af = [x for m in per for x in per[m][0]]; ao = [x for m in per for x in per[m][1]]
        print(f"  frontend ms p50 {pct(af,50):.1f} p90 {pct(af,90):.1f} p99 {pct(af,99):.1f} | backend ms p50 {pct(ao,50):.1f} p99 {pct(ao,99):.1f}  (n={len(af)})")
        hot = [f"min {m} fe p50 {pct(v[0],50):.0f}/p99 {pct(v[0],99):.0f}, be p99 {pct(v[1],99):.0f}" for m, v in sorted(per.items()) if pct(v[0], 50) > 30 or pct(v[1], 99) > 60]
        if hot: print("  hot minutes: " + "; ".join(hot))
    lg = open_log(os.path.join(d, f"{tag}-jack-in.log"))
    if lg:
        dres = det = div = lines = 0
        for line in lg:
            lines += 1
            # counted independently: Basalt's threads interleave, one line can carry two warnings
            if "d_res_d_" in line and "is not valid" in line: dres += 1
            if "skipping backsubstitution" in line: det += 1   # "det(Q1Jl) == 0, skipping backsubstitution"
            if "Tracker diverged" in line: div += 1
        print(f"  monado log: {lines} lines, speed-guard trips {div}, Basalt d_res-invalid {dres}, det(Q1Jl)==0 {det}")
    else:
        print("  (no jack-in log)")

ap = argparse.ArgumentParser(); ap.add_argument("tags", nargs="+"); ap.add_argument("-d", default=os.path.expanduser("~/vr/logs/soak"))
a = ap.parse_args()
for t in a.tags: grade(a.d, t)
