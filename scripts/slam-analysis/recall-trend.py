#!/usr/bin/env python3
"""Does any frontend stage grow over the session?

The reset storm starts ~11 min into a session that was clean before it, which is the signature
of something accumulating rather than of the room or the wearer. Basalt's recall cache is the
known suspect (patch 0014 bounds it). Timing CSV columns are absolute ns stamps, so each stage's
cost is a difference; bucket them by minute and look for monotonic growth.
"""
import sys, statistics

path = sys.argv[1]
hdr = open(path).readline().lstrip('#').strip().split(',')
idx = {n: i for i, n in enumerate(hdr)}

STAGES = [
    ("tracking",   "frontend_pyramid_created",        "frontend_tracking_ended"),
    ("recall",     "frontend_tracking_ended",         "frontend_recall_ended"),
    ("detect0",    "frontend_recall_ended",           "frontend_detection_cam0_ended"),
    ("matching",   "frontend_detection_cam0_ended",   "frontend_matching_ended"),
    ("detecti",    "frontend_matching_ended",         "frontend_detection_cami_ended"),
    ("backend_opt","backend_observations_processed",  "backend_optimization_ended"),
    ("marginal",   "backend_optimization_ended",      "backend_marginalization_ended"),
]

buckets = {}
t0 = None
for line in open(path):
    if line.startswith('#'):
        continue
    f = line.rstrip('\n').split(',')
    if len(f) < len(hdr):
        continue
    try:
        ts = int(f[idx['frames_original_timestamp']])
    except (ValueError, KeyError):
        continue
    if t0 is None:
        t0 = ts
    m = int((ts - t0) / 1e9 / 60)
    b = buckets.setdefault(m, {n: [] for n, _, _ in STAGES})
    for name, a, z in STAGES:
        try:
            d = (int(f[idx[z]]) - int(f[idx[a]])) / 1e6
        except (ValueError, KeyError):
            continue
        if 0 <= d < 500:
            b[name].append(d)

print("  min  " + "".join(f"{n:>12s}" for n, _, _ in STAGES))
for m in sorted(buckets):
    row = f"  {m:3d}  "
    for name, _, _ in STAGES:
        v = buckets[m][name]
        row += f"{statistics.median(v):11.2f} " if v else f"{'-':>11s} "
    print(row)
