#!/usr/bin/env python3
"""euroc-phases.py -- write phases.json for a Monado EUROC_RECORD dataset from yaw-protocol-voice.py's log.

yaw-protocol-voice.py logs each phase boundary in wall-clock time (`unix`); the dataset's frames
are stamped on Monado's CLOCK_MONOTONIC (`t_ns`, the PNG file name). Two ways to map one onto the
other:
  --method clock (default): t_ns = unix*1e9 + (CLOCK_MONOTONIC - CLOCK_REALTIME), the offset read
      live on this machine -- exact to the NTP slew, but only valid on the SAME BOOT as the
      recording (refused if the voice log predates the boot; the boot id is written out).
      Validated 2026-08-29 against the 27th's hand-made phases.json: every phase within -0.72 s.
  --method mtime: the 2026-08-27 hand method (docs/80, "matching the phase log's wall clock to
      PNG mtimes") -- median of (t_ns - mtime) over a sample of cam0 frames. Only valid on the
      ORIGINAL files (a plain cp rewrites mtimes) and biased by the PNG writer's lag; for datasets
      recorded under another boot.
Output is the exact layout replay-phase-slice.py reads (`protocol_start_t_ns` + `phases[].t_ns`),
plus `in_dataset` per phase so a phase outside the recording is visible at a glance.

Usage: euroc-phases.py --dataset DIR --voice ~/vr/logs/yaw-protocol-<stamp>.json [--out DIR/phases.json]
       euroc-phases.py --dataset DIR --voice ... --check DIR/phases.json   (compare, do not write)
"""
import argparse, json, os, statistics, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--dataset", type=Path, required=True, help="dir containing mav0/")
ap.add_argument("--voice", type=Path, required=True, help="yaw-protocol-voice.py's JSON log")
ap.add_argument("--out", type=Path, help="default: <dataset>/phases.json")
ap.add_argument("--check", type=Path, help="existing phases.json to compare against (no write)")
ap.add_argument("--cam", default="cam0")
ap.add_argument("--method", choices=["clock", "mtime"], default="clock")
a = ap.parse_args()

frames = sorted(p for p in (a.dataset / "mav0" / a.cam / "data").iterdir() if p.suffix == ".png")
if not frames:
    sys.exit(f"no PNG frames under {a.dataset}/mav0/{a.cam}/data")
first, last = int(frames[0].stem), int(frames[-1].stem)
import time
boot_id = open("/proc/sys/kernel/random/boot_id").read().strip()
if a.method == "clock":
    # offset = t_ns - unix_ns; both clocks read back-to-back, a few us apart
    samples = []
    for _ in range(5):
        r, m = time.time_ns(), time.monotonic_ns()
        samples.append(m - r)
    off = int(statistics.median(samples)); spread = (max(samples) - min(samples)) / 1e9
    boot_unix = time.time() - time.monotonic()
    print(f"frames {len(frames)}  method clock: t_ns - unix_ns = {off}  (boot {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(boot_unix))}, boot_id {boot_id[:8]})")
else:
    step = max(1, len(frames) // 400)
    offs = [int(p.stem) - int(p.stat().st_mtime * 1e9) for p in frames[::step]]
    off = int(statistics.median(offs)); spread = (max(offs) - min(offs)) / 1e9
    boot_unix = None
    print(f"frames {len(frames)}  method mtime: t_ns - unix_ns = {off} (spread {spread:.2f} s over {len(offs)} samples)")

v = json.load(open(a.voice))
phases = v["phases"] if isinstance(v, dict) else v
start_unix = phases[0]["unix"]
if boot_unix is not None and start_unix < boot_unix:
    sys.exit(f"the voice log starts before this boot ({time.ctime(start_unix)} < boot {time.ctime(boot_unix)}): the monotonic offset does not apply -- use --method mtime on the original files")
out = {"protocol_start_t_ns": None, "phases": [], "method": a.method, "clock_offset_ns": off, "clock_offset_spread_s": round(spread, 6),
       "boot_id": boot_id, "dataset_first_t_ns": first, "dataset_last_t_ns": last, "voice_log": str(a.voice.name)}
for ph in phases:
    t = int(ph["unix"] * 1e9) + off
    inside = first <= t <= last
    out["phases"].append({**ph, "t_ns": t, "in_dataset": inside})
    print(f"  {ph['phase']:<9} t_mono {ph.get('t_mono_s', 0):7.1f}s  t_ns {t}  {'' if inside else '<-- OUTSIDE the recording'}")
out["protocol_start_t_ns"] = out["phases"][0]["t_ns"]

if a.check:
    ref = json.load(open(a.check))
    refmap = {p["phase"]: p["t_ns"] for p in ref["phases"]}
    worst = 0.0
    for p in out["phases"]:
        if p["phase"] in refmap:
            d = (p["t_ns"] - refmap[p["phase"]]) / 1e9
            worst = max(worst, abs(d))
            print(f"  check {p['phase']:<9} computed - reference = {d:+.3f} s")
    print(f"check: worst |diff| {worst:.3f} s ({'OK' if worst < 1.0 else 'MISMATCH'})")
    sys.exit(0 if worst < 1.0 else 1)

dst = a.out or (a.dataset / "phases.json")
json.dump(out, open(dst, "w"), indent=2)
print(f"wrote {dst}")
