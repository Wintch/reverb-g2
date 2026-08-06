#!/usr/bin/env python3
"""Coarse brightness/color analysis of a panel-cam-capture.sh frame sequence.

The webcam has no focus at the distance it is mounted at - do not expect legible images.
This only extracts a per-frame mean brightness and per-channel means, and flags frames that
jump above a baseline (a candidate "backlight turned on" event) or shift color notably
between frames (a candidate mode-change/pattern event, e.g. the CTRL4K blue/white/green test
pattern from docs/16-lab-vblank.md). Cross-check against panel-status.py's HID DEVICE_STATUS
timeline before trusting any single frame - this is a second, much noisier channel, not a
replacement for it. Physical confirmation by a human still wins over both, per project
convention.

  ./scripts/panel-cam-analyze.py <capture-dir> [--csv out.csv] [--threshold N]
"""
import argparse
import csv
import glob
import json
import os
import sys

from PIL import Image, ImageStat


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("capture_dir")
	ap.add_argument("--csv", default=None)
	ap.add_argument("--threshold", type=float, default=15.0,
	                 help="min jump in mean luma between consecutive frames to flag (default 15/255)")
	a = ap.parse_args()

	meta_path = os.path.join(a.capture_dir, "meta.json")
	meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
	fps = meta.get("fps", 10)
	start_epoch = meta.get("start_epoch")

	frames = sorted(glob.glob(os.path.join(a.capture_dir, "frame_*.jpg")))
	if not frames:
		sys.exit(f"no frames found in {a.capture_dir}")

	rows = []
	prev_luma = None
	for i, path in enumerate(frames):
		img = Image.open(path).convert("RGB")
		r, g, b = ImageStat.Stat(img).mean
		luma = 0.299 * r + 0.587 * g + 0.114 * b
		delta = None if prev_luma is None else luma - prev_luma
		rows.append({
			"frame": i,
			"file": os.path.basename(path),
			"t_offset_s": round(i / fps, 2),
			"mean_r": round(r, 1),
			"mean_g": round(g, 1),
			"mean_b": round(b, 1),
			"mean_luma": round(luma, 1),
			"delta_luma": None if delta is None else round(delta, 1),
			"flag": bool(delta is not None and abs(delta) >= a.threshold),
		})
		prev_luma = luma

	print(f"{len(rows)} frames, fps={fps}, start_epoch={start_epoch}")
	flags = [r for r in rows if r["flag"]]
	print(f"{len(flags)} frame(s) flagged (|delta luma| >= {a.threshold})\n")
	for r in flags:
		print(f"  frame {r['frame']:>5}  t={r['t_offset_s']:>6.2f}s  luma {r['mean_luma']:>6.1f}  "
		      f"delta {r['delta_luma']:>+6.1f}  rgb=({r['mean_r']:.0f},{r['mean_g']:.0f},{r['mean_b']:.0f})")

	if not flags:
		print("  (none - either the panel never changed state, or the threshold is too high)")

	if a.csv:
		with open(a.csv, "w", newline="") as f:
			w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
			w.writeheader()
			w.writerows(rows)
		print(f"\nwrote {a.csv}")


if __name__ == "__main__":
	main()
