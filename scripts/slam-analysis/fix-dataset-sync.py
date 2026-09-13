#!/usr/bin/env python3
"""fix-dataset-sync.py -- make every camera in a recorded EuRoC dataset share one timestamp set.

Why (2026-09-13, first clean recording): Monado's euroc recorder indexes each camera into its own
data.csv, and a single missed row desynchronises everything after it. This dataset came out with
cam0/cam2/cam3 at 16105 rows and cam1 at 16104 -- from that point on, cam0[i] pairs with a cam1[i]
one frame (34 ms) later. `euroc_player_push_next_frame` detects it, logs ONE
"ERROR ... Unsynced frames", and stops pushing: tracking.csv simply ends mid-dataset while
prediction.csv keeps going against the last anchor, so the run looks complete and is silently
truncated. Here it cut a 9-minute dataset to 3m55s and took most of the routine's segments with it.

The images themselves are all on disk (16106 JPEGs per camera) -- only the index rows are missing,
so this is repairable without re-recording. Keeps the intersection of timestamps present in every
camera's index AND on disk, backs up each original once as data.csv.orig, and rewrites in place.

Usage:  fix-dataset-sync.py <dataset_dir> [--dry-run]
"""
import os
import sys


def read_index(path):
    rows = {}
    with open(path) as fh:
        header = fh.readline()
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "," not in line:
                continue
            ts, name = line.split(",", 1)
            rows[int(ts)] = name
    return header, rows


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    root = sys.argv[1].rstrip("/")
    dry = "--dry-run" in sys.argv
    mav = os.path.join(root, "mav0")
    cams = sorted(d for d in os.listdir(mav) if d.startswith("cam"))
    if not cams:
        print(f"!! no cam* directories under {mav}")
        sys.exit(2)

    indexes = {}
    for c in cams:
        p = os.path.join(mav, c, "data.csv")
        orig = p + ".orig"
        # Always re-read from the backup once one exists, so repeated runs stay idempotent rather
        # than intersecting an already-trimmed index with itself.
        header, rows = read_index(orig if os.path.exists(orig) else p)
        present = {ts: n for ts, n in rows.items()
                   if os.path.exists(os.path.join(mav, c, "data", n))}
        indexes[c] = (p, orig, header, rows, present)
        print(f"  {c}: {len(rows)} indexed, {len(present)} with an image on disk")

    common = set.intersection(*(set(v[4]) for v in indexes.values()))
    print(f"\n  common to all {len(cams)} cameras: {len(common)}")
    dropped = {c: len(v[4]) - len(common) for c, v in indexes.items()}
    print("  dropping per camera: " + ", ".join(f"{c} {n}" for c, n in dropped.items()))
    if not common:
        print("!! nothing in common -- refusing to write")
        sys.exit(1)
    if dry:
        print("\n  --dry-run, nothing written")
        return

    for c, (p, orig, header, rows, present) in indexes.items():
        if not os.path.exists(orig):
            os.rename(p, orig)
        with open(p, "w") as fh:
            fh.write(header if header.endswith("\n") else header + "\n")
            for ts in sorted(common):
                fh.write(f"{ts},{present[ts]}\n")
    print(f"\n  rewrote {len(cams)} indexes to {len(common)} rows each (originals kept as .orig)")


if __name__ == "__main__":
    main()
