#!/usr/bin/env python3
"""replay-basalt-variants.py -- replay ONE recorded EuRoC dataset through basalt_vio with N
Basalt configs and rank them: drift + landmark survival vs. yaw rate, without the headset.

Why (2026-08-27 night, docs/80): Aircar 6dof drifts metres on fast yaw, and the cause is in
Basalt's backend -- the landmark count collapses under yaw (p10 = 0 above 90 deg/s) while the
frontend keeps ~2600 keypoints. Testing backend configs live costs a wearer session each.
With one EUROC_RECORD session + the VIT_DUMP_CALIB calibration (patches/basalt/0013) every
config replays offline against the IDENTICAL input, repeatably, in minutes.

Pieces it relies on:
  * ~/vr/basalt/build-tools/basalt_vio  (src/vio.cpp, built with Pangolin; --show-gui 0 is
    truly headless: pangolin::CreateWindowAndBind only runs if show_gui)
  * a dataset dir containing mav0/{cam0..N,imu0}/data.csv (Monado's EUROC_RECORD=1 output,
    t_euroc_recorder.cpp -- writes exactly what dataset_io_euroc.h reads)
  * the calibration JSON written by VIT_DUMP_CALIB=<path> on a live launch
  * VIT_COLLAPSE_LOG=1 -> basalt_vio prints the same vit_of/vit_vio lines as the live tracker
    (they live in frame_to_frame_optical_flow.h / sqrt_keypoint_vio.cpp, not the VIT glue)

Yaw rate is taken from the dataset's own IMU gyro (input, identical for every config), NOT
from each run's trajectory -- so the per-yaw-band landmark table compares like with like.

Usage:
  replay-basalt-variants.py --dataset DIR --calib calib.json \
      --config base=/home/iam/vr/basalt-g2-config.json --config G=/home/iam/vr/basalt-variants/G.json ...
      [--out ~/vr/logs/replay] [--threads 6] [--vio ~/vr/basalt/build-tools/basalt_vio]
"""
import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
DEFAULT_VIO = HOME / "vr" / "basalt" / "build-tools" / "basalt_vio"
YAW_BANDS = [(0, 30), (30, 90), (90, 180), (180, 360), (360, 1e9)]


def pct(values, p):
    if not values:
        return float("nan")
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * p))]


def load_imu_yaw_rate(dataset):
    """Per-IMU-sample (t_ns, |yaw rate| deg/s, |pitch+roll rate| deg/s) from mav0/imu0/data.csv.
    'Up' in the body frame comes from a slow low-pass of the accelerometer (gravity); yaw rate is
    the gyro component along it. Good enough to band frames by rotation regime."""
    rows = []
    with open(dataset / "mav0" / "imu0" / "data.csv") as f:
        for r in csv.reader(f):
            if not r or r[0].startswith("#"):
                continue
            try:
                rows.append([int(r[0])] + [float(x) for x in r[1:7]])
            except ValueError:
                continue
    out = []
    g = None
    alpha = 0.02  # ~1 s time constant at 250 Hz
    for t, wx, wy, wz, ax, ay, az in rows:
        a = (ax, ay, az)
        g = a if g is None else tuple(alpha * a[i] + (1 - alpha) * g[i] for i in range(3))
        n = math.sqrt(sum(c * c for c in g)) or 1.0
        up = tuple(c / n for c in g)
        yaw = abs(wx * up[0] + wy * up[1] + wz * up[2])
        total2 = wx * wx + wy * wy + wz * wz
        pr = math.sqrt(max(0.0, total2 - yaw * yaw))
        out.append((t, math.degrees(yaw), math.degrees(pr)))
    return out


def yaw_at(imu, t_ns, _cache={}):
    """Peak |yaw rate| in the 33 ms window ending at t_ns (one camera frame)."""
    import bisect
    if "ts" not in _cache or _cache.get("id") != id(imu):
        _cache["ts"] = [r[0] for r in imu]
        _cache["id"] = id(imu)
    ts = _cache["ts"]
    hi = bisect.bisect_right(ts, t_ns)
    lo = bisect.bisect_left(ts, t_ns - 33_000_000)
    seg = imu[lo:hi]
    return max((r[1] for r in seg), default=0.0)


def parse_vit_log(path):
    """Pair each frame's t_ns (vit_collapse IN) with its keypoints/recall_ms (vit_of) and
    landmarks/opt/marg (vit_vio). Tolerates interleaved/mangled lines."""
    frames = {}
    cur = None
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("vit_collapse IN"):
                m = re.search(r"t_ns=(\d+)", line)
                cur = int(m.group(1)) if m else None
                if cur:
                    frames[cur] = {}
            elif cur and line.startswith("vit_of"):
                for key, pat in (("kp", r"keypoints=(\d+)"), ("recall_ms", r"recall_ms=([0-9.eE+-]+)"),
                                 ("total_ms", r"total_ms=([0-9.eE+-]+)"), ("patches", r"patches=(\d+)")):
                    m = re.search(pat, line)
                    if m:
                        frames[cur][key] = float(m.group(1))
            elif cur and line.startswith("vit_vio"):
                for key, pat in (("lm", r"landmarks=(\d+)"), ("opt_ms", r"opt_ms=([0-9.eE+-]+)"),
                                 ("marg_ms", r"marg_ms=([0-9.eE+-]+)")):
                    m = re.search(pat, line)
                    if m:
                        frames[cur][key] = float(m.group(1))
    return frames


def load_trajectory(path):
    rows = []
    with open(path) as f:
        for r in csv.reader(f):
            if len(r) < 4 or r[0].startswith("#"):
                continue
            try:
                rows.append((int(r[0]), float(r[1]), float(r[2]), float(r[3])))
            except ValueError:
                continue
    return rows


def drift_metrics(traj, skip_s=5.0):
    """1-second-window displacement stats on the trajectory (after an initial settle)."""
    if len(traj) < 60:
        return {"windows": 0}
    t0 = traj[0][0]
    start = next((i for i, r in enumerate(traj) if (r[0] - t0) / 1e9 > skip_s), 0)
    wins = []
    i = start
    while i + 30 < len(traj):
        a, b = traj[i], traj[i + 30]
        wins.append(math.dist(a[1:4], b[1:4]))
        i += 15
    xs, ys, zs = zip(*[r[1:4] for r in traj[start:]])
    return {
        "windows": len(wins),
        "max_1s_disp_m": max(wins) if wins else 0.0,
        "win_over_0p5m": sum(w > 0.5 for w in wins),
        "win_over_1m": sum(w > 1.0 for w in wins),
        "span_m": max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)),
        "duration_s": (traj[-1][0] - t0) / 1e9,
    }


def run_variant(tag, config, args, imu):
    out = args.out / tag
    out.mkdir(parents=True, exist_ok=True)
    log = out / "vit.log"
    traj_fn = f"{tag}.csv"
    cmd = [str(args.vio), "--dataset-type", "euroc", "--dataset-path", str(args.dataset),
           "--cam-calib", str(args.calib), "--config-path", str(config),
           "--save-trajectory", "euroc", "--save-trajectory-fn", traj_fn,
           "--result-path", str(out / "result.json"), "--show-gui", "0",
           "--num-threads", str(args.threads)]
    env = {**os.environ, "VIT_COLLAPSE_LOG": "1"}
    t_start = time.monotonic()
    with open(log, "w") as lf:
        proc = subprocess.run(cmd, cwd=out, env=env, stdout=lf, stderr=subprocess.STDOUT)
    wall = time.monotonic() - t_start
    rec = {"tag": tag, "config": str(config), "rc": proc.returncode, "wall_s": round(wall, 1)}
    if proc.returncode != 0:
        rec["error"] = "basalt_vio failed -- see " + str(log)
        return rec
    # trajectory: basalt saves it in cwd under the given name
    traj_path = out / traj_fn
    if traj_path.exists():
        rec["drift"] = drift_metrics(load_trajectory(traj_path))
    res = out / "result.json"
    if res.exists():
        try:
            rec["result"] = json.load(open(res))
        except Exception:
            rec["result"] = "unparsed"
    frames = parse_vit_log(log)
    rec["frames"] = len(frames)
    bands = {}
    for lo, hi in YAW_BANDS:
        sel = [f for t, f in frames.items() if lo <= yaw_at(imu, t) < hi and "lm" in f]
        if sel:
            bands[f"{lo}-{int(hi) if hi < 1e8 else 'inf'}"] = {
                "n": len(sel),
                "lm_p50": pct([f["lm"] for f in sel], .5), "lm_p10": pct([f["lm"] for f in sel], .1),
                "kp_p50": pct([f.get("kp", 0) for f in sel], .5),
            }
    rec["landmarks_by_yaw_band"] = bands
    allf = [f for f in frames.values() if f]
    rec["recall_ms_p50"] = pct([f.get("recall_ms", 0) for f in allf], .5)
    rec["recall_ms_p99"] = pct([f.get("recall_ms", 0) for f in allf], .99)
    rec["frontend_total_ms_p99"] = pct([f.get("total_ms", 0) for f in allf], .99)
    rec["opt_ms_p99"] = pct([f.get("opt_ms", 0) for f in allf], .99)
    rec["patches_last"] = max((f.get("patches", 0) for f in allf), default=0)
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dataset", type=Path, required=True, help="dir containing mav0/")
    ap.add_argument("--calib", type=Path, required=True, help="JSON from VIT_DUMP_CALIB")
    ap.add_argument("--config", action="append", required=True, help="tag=path/to/config.json (repeatable)")
    ap.add_argument("--out", type=Path, default=HOME / "vr" / "logs" / "replay")
    ap.add_argument("--vio", type=Path, default=DEFAULT_VIO)
    ap.add_argument("--threads", type=int, default=6)
    args = ap.parse_args()
    for p in (args.vio, args.dataset / "mav0" / "imu0" / "data.csv", args.calib):
        if not p.exists():
            sys.exit(f"missing: {p}")
    imu = load_imu_yaw_rate(args.dataset)
    print(f"dataset: {args.dataset}  imu samples: {len(imu)}  "
          f"yaw>90deg/s: {sum(1 for r in imu if r[1] > 90) / 250:.1f}s (at ~250 Hz)")
    results = []
    for spec in args.config:
        tag, _, cfg = spec.partition("=")
        if not cfg:
            sys.exit(f"--config wants tag=path, got {spec}")
        print(f"--- {tag}: {cfg}", flush=True)
        rec = run_variant(tag, Path(cfg), args, imu)
        results.append(rec)
        print(json.dumps({k: v for k, v in rec.items() if k != "result"}, indent=None, default=str), flush=True)
    # ranked table: fewer >1m windows, then smaller max displacement, then more landmarks at >90 deg/s
    def key(r):
        d = r.get("drift", {})
        lm = r.get("landmarks_by_yaw_band", {}).get("90-180", {}).get("lm_p10", 0)
        return (r["rc"] != 0, d.get("win_over_1m", 1e9), d.get("max_1s_disp_m", 1e9), -lm)
    print("\nRANKED (best first):")
    print(f"{'tag':<8}{'rc':>3}{'>1m wins':>10}{'max 1s m':>10}{'span m':>8}{'lm p10 @90-180':>16}{'lm p10 @180-360':>17}{'recall p99 ms':>14}{'wall s':>8}")
    for r in sorted(results, key=key):
        d = r.get("drift", {}); b = r.get("landmarks_by_yaw_band", {})
        print(f"{r['tag']:<8}{r['rc']:>3}{d.get('win_over_1m', '-'):>10}{d.get('max_1s_disp_m', float('nan')):>10.2f}"
              f"{d.get('span_m', float('nan')):>8.2f}{b.get('90-180', {}).get('lm_p10', float('nan')):>16.0f}"
              f"{b.get('180-360', {}).get('lm_p10', float('nan')):>17.0f}{r.get('recall_ms_p99', float('nan')):>14.2f}{r['wall_s']:>8}")
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "replay-report.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "dataset": str(args.dataset),
                            "results": results}, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
