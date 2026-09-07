#!/usr/bin/env python3
"""End-to-end pose latency per arm -- the metric the wearer's "redraw" actually is.

  pose-latency.py <timing.csv> <summon_monotonic_ns> [worn_seconds] [label]

Position drift and pose staleness are different failures and today they moved in opposite
directions, so the arm that FELT better has to be judged on latency, not on drift. timing.csv
carries absolute stamps for every stage, so latency is the span from the camera frame's own
timestamp to the moment Monado received the pose built from it -- the same quantity
VIT_COLLAPSE_LOG reports as age_out_ms, but recorded per session instead of scraped from a log
that each run truncates.

Restricted to the worn window: before the summon and after the doff the headset is sitting
somewhere, and those samples are not what the wearer judged.
"""
import statistics
import sys

path = sys.argv[1]
mark = int(sys.argv[2])
worn = float(sys.argv[3]) if len(sys.argv) > 3 else 240.0
label = sys.argv[4] if len(sys.argv) > 4 else path
end = mark + int(worn * 1e9)

hdr = open(path).readline().lstrip('#').strip().split(',')
idx = {n: i for i, n in enumerate(hdr)}
need = ('frames_original_timestamp', 'received_by_monado',
        'frontend_pyramid_created', 'frontend_detection_cami_ended')
for n in need:
    if n not in idx:
        print(f"  missing column {n}"); sys.exit(1)

lat, front = [], []
for line in open(path):
    if line.startswith('#'):
        continue
    f = line.rstrip('\n').split(',')
    if len(f) < len(hdr):
        continue
    try:
        t0 = int(f[idx['frames_original_timestamp']])
        rx = int(f[idx['received_by_monado']])
        fa = int(f[idx['frontend_pyramid_created']])
        fz = int(f[idx['frontend_detection_cami_ended']])
    except ValueError:
        continue
    if not (mark <= t0 <= end):
        continue
    d = (rx - t0) / 1e6
    if 0 < d < 1000:
        lat.append(d)
    d2 = (fz - fa) / 1e6
    if 0 <= d2 < 500:
        front.append(d2)


def show(name, v, unit=" ms"):
    if not v:
        print(f"  {name:22s} no samples"); return
    s = sorted(v)
    print(f"  {name:22s} n={len(v):5d}  med={statistics.median(v):6.1f}{unit}"
          f"  p90={s[int(len(s)*.9)]:6.1f}{unit}  p99={s[int(len(s)*.99)]:6.1f}{unit}")


print(f"  [{label}]")
show("pose latency", lat)
show("frontend cost", front)
if front:
    over = sum(1 for x in front if x > 33.0)
    print(f"  frontend over the 33 ms camera interval: {over}/{len(front)} "
          f"({100*over/len(front):.0f}%)")
