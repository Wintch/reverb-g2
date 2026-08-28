#!/usr/bin/env python3
"""replay-phase-slice.py -- slice offline VIO trajectories by the yaw-protocol phases.

Why (2026-08-27): the whole-recording drift numbers from replay-basalt-variants.py mix the
wearer's real motion (the "free play" phase, the walk-in before the protocol) with the drift
we care about (position running away during pure head rotation). The yaw protocol
(yaw-protocol-voice.py) writes phases.json with the t_ns of every phase boundary, so each
trajectory can be cut into intro / yaw / settle / pitch / settle / roll / settle / free, and
the settle phases double as a sanity check: the head is still there, so any motion is drift.

Per config and phase: max 1 s displacement, net (phase start -> phase end) and "max far" (max
distance from the phase-start position). A seated head rotation has a few cm of real
translation (neck arm), so anything in metres is the tracker.

Usage:
  replay-phase-slice.py --phases /mnt/vrtmp/euroc-yaw_*/phases.json base=~/vr/logs/replay-yaw-A/base/base.csv K=...
"""
import argparse
import csv
import json
import math
import os
from pathlib import Path

ROT_PHASES = ("yaw", "pitch", "roll")


def load_traj(p):
    rows = []
    for r in csv.reader(open(os.path.expanduser(p))):
        if len(r) < 4 or r[0].startswith("#"):
            continue
        try:
            rows.append((int(r[0]), float(r[1]), float(r[2]), float(r[3])))
        except ValueError:
            pass
    return rows


def slice_phase(rows, t0, t1):
    seg = [r for r in rows if t0 <= r[0] < t1]
    if len(seg) < 5:
        return None
    p0 = seg[0][1:4]
    max1s, i = 0.0, 0
    for j in range(len(seg)):
        while seg[j][0] - seg[i][0] > 1_000_000_000:
            i += 1
        d = math.dist(seg[i][1:4], seg[j][1:4])
        if d > max1s:
            max1s = d
    return {"n": len(seg), "max1s": max1s, "net": math.dist(p0, seg[-1][1:4]),
            "maxfar": max(math.dist(p0, r[1:4]) for r in seg)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phases", required=True)
    ap.add_argument("--json", help="also append one line per config to this jsonl")
    ap.add_argument("traj", nargs="+", help="tag=trajectory.csv")
    a = ap.parse_args()
    ph = json.load(open(a.phases))["phases"]
    bounds = []
    for k, p in enumerate(ph):
        t0 = p["t_ns"]
        t1 = ph[k + 1]["t_ns"] if k + 1 < len(ph) else t0 + p["seconds"] * 1_000_000_000
        if p["phase"] != "end":
            bounds.append((p["phase"], t0, t1))
    results = {}
    for spec in a.traj:
        tag, path = spec.split("=", 1)
        rows = load_traj(path)
        results[tag] = {name: slice_phase(rows, t0, t1) for name, t0, t1 in bounds}
    names = [b[0] for b in bounds]
    print("| config | " + " | ".join(f"{n} max1s/net/maxfar" for n in names) + " | rot maxfar sum | settle maxfar max |")
    print("|---|" + "---|" * (len(names) + 2))
    for tag, res in results.items():
        cells, rot, settle = [], 0.0, 0.0
        for n in names:
            r = res[n]
            if r is None:
                cells.append("—")
                continue
            cells.append(f"{r['max1s']:.2f}/{r['net']:.2f}/{r['maxfar']:.2f}")
            if n in ROT_PHASES:
                rot += r["maxfar"]
            if n.startswith("settle"):
                settle = max(settle, r["maxfar"])
        print(f"| {tag} | " + " | ".join(cells) + f" | **{rot:.2f}** | {settle:.3f} |")
        if a.json:
            with open(os.path.expanduser(a.json), "a") as f:
                f.write(json.dumps({"tag": tag, "phases": res, "rot_maxfar_sum": rot, "settle_maxfar_max": settle}) + "\n")
    print("\nrot maxfar sum = yaw + pitch + roll 'max distance from phase start' (m): the number to minimise. "
          "settle phases are the still-head sanity check (should be ~0).")


if __name__ == "__main__":
    main()
