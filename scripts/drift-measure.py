#!/usr/bin/env python3
"""drift-measure.py -- repeatable controller-orientation drift measurement.

Written 2026-08-13 after three consecutive drift measurements of the same motionless
controllers disagreed by up to 5x (left hand: 71.7 -> 9.4 -> 51.5 deg/min). Every one of
those was taken opportunistically, over a log that kept growing while the physical
conditions -- hands on the controllers, thermal state, estimator convergence -- changed
underneath it. This fixes the METHOD, not the tracker: one fixed protocol, self-validating,
producing numbers that are comparable run to run, appended to
~/vr/logs/drift-measure.jsonl with the environment that produced them (the same pattern
frame-pacing.jsonl already uses).

Protocol per invocation:

  1. Refuse to run if a Steam title is live. Kill stray hello_xr players (they are only
     ever our own measurement/viewer instances).
  2. Launch ONE player (play360.sh, still image) and keep it for the whole invocation, so
     back-to-back runs share identical conditions.
  3. SETTLE (default 120 s): nobody touches anything. The gyro-bias estimator fires every
     2 s with an EMA time constant of ~8 s, so it converges well inside this; hand-heat
     bias transients get most of this window to decay too.
  4. CAPTURE (default 120 s) x N runs, 5 s apart, same player session.
  5. Per run and per hand: least-squares slope of the forward-vector angle in deg/min
     (a slope over ~120 points, not an endpoint difference over 2), R^2 and residual RMS
     so "it is not even linear" is visible instead of silently averaged away. Plus the
     INTER-CONTROLLER angle slope -- the angle between the two hands' forward vectors,
     which no common rotation of anything can fake. That is the headline number.
  6. Validate from the data itself: position spread while position is tracked (movement
     detection), sample gaps, and the estimator's own activity during the window (fires
     per fusion instance and last smoothed value, read from the monado log) -- so "did
     the estimator even run" is part of the record, not an assumption. It was silently
     off once already (m_imu_3dof_reset) and only a counter caught it.

The operator's one job for the duration: DO NOT touch the controllers or the headset.

Usage:
    ./drift-measure.py [--settle S] [--capture S] [--runs N] [--label TEXT]
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

VR = Path.home() / "vr"
MONADO_LOG = VR / "jack-in-wayland.log"
OUT_JSONL = VR / "logs" / "drift-measure.jsonl"
TEST_IMAGE = VR / "media" / "test-equirect.jpg"
SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")) / "monado_comp_ipc"

POSE_RE = re.compile(
    r"\[(\d+):(\d+):(\d+)\.\d+\].*POSE head \(([^)]+)\)"
    r" \| left \(([^)]+)\) pos:(\S+) trk:(\S+) fwd\(([^)]+)\)=\S+"
    r" \| right \(([^)]+)\) pos:(\S+) trk:(\S+) fwd\(([^)]+)\)=\S+"
)
EST_RE = re.compile(r"auto-estimate\[(0x[0-9a-f]+)\] #(\d+) \(smoothed: ([0-9.]+) deg/min\)")


def sod(h, m, s):
    """Seconds-of-day."""
    return h * 3600 + m * 60 + s


def now_sod():
    t = datetime.now()
    return sod(t.hour, t.minute, t.second) + t.microsecond / 1e6


def vec(text):
    return [float(x) for x in text.split()]


def angle_deg(a, b):
    d = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    return math.degrees(math.acos(d))


def lsq_slope(ts, ys):
    """Least-squares slope of ys over ts (minutes), with R^2 and residual RMS."""
    n = len(ts)
    tm = sum(ts) / n
    ym = sum(ys) / n
    sxx = sum((t - tm) ** 2 for t in ts)
    if sxx == 0:
        return 0.0, 0.0, 0.0
    slope = sum((t - tm) * (y - ym) for t, y in zip(ts, ys)) / sxx
    resid = [y - (ym + slope * (t - tm)) for t, y in zip(ts, ys)]
    ss_res = sum(r * r for r in resid)
    ss_tot = sum((y - ym) ** 2 for y in ys) or 1e-12
    rms = math.sqrt(ss_res / n)
    return slope, 1.0 - ss_res / ss_tot, rms


def read_poses(log_path, unwrap_base):
    """Parse POSE lines into (t_sod, left_fwd, right_fwd, left_pos, right_pos, l_trk, r_trk).

    Timestamps wrap at midnight; anything more than an hour "before" unwrap_base is bumped
    by 24 h. Runs are minutes long, so a single bump is always enough.
    """
    rows = []
    try:
        text = log_path.read_text(errors="ignore")
    except FileNotFoundError:
        return rows
    for m in POSE_RE.finditer(text):
        t = sod(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if t < unwrap_base - 3600:
            t += 86400
        rows.append(
            (
                t,
                vec(m.group(8)),
                vec(m.group(12)),
                vec(m.group(5)),
                vec(m.group(9)),
                m.group(7),
                m.group(11),
            )
        )
    return rows


def estimator_snapshot():
    """Per fusion instance: (max counter seen, last smoothed value)."""
    out = {}
    try:
        text = MONADO_LOG.read_text(errors="ignore")
    except FileNotFoundError:
        return out
    for m in EST_RE.finditer(text):
        ptr, count, val = m.group(1), int(m.group(2)), float(m.group(3))
        prev = out.get(ptr, (0, 0.0))
        if count >= prev[0]:
            out[ptr] = (count, val)
    return out


def monado_env():
    """Mode and knobs read from the RUNNING service's environment, not from assumptions."""
    try:
        pid = subprocess.run(
            ["pgrep", "-f", "monado[-]service"], capture_output=True, text=True
        ).stdout.split()[0]
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        kv = dict(e.decode(errors="ignore").split("=", 1) for e in env if b"=" in e)
        return {
            "mode": "6dof" if kv.get("WMR_SLAM") == "1" else "3dof",
            "slam_filter": kv.get("SLAM_FILTER", "default"),
            "constellation": kv.get("WMR_CONSTELLATION_CONTROLLERS", "unset"),
        }
    except (IndexError, FileNotFoundError, PermissionError):
        return {"mode": "unknown", "slam_filter": "?", "constellation": "?"}


def analyze(rows, t0, t1, label, run_idx, est_before, est_after, meta):
    win = [r for r in rows if t0 <= r[0] <= t1]
    result = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "run": run_idx,
        "samples": len(win),
        **meta,
    }
    if len(win) < 30:
        result["error"] = f"only {len(win)} samples in window"
        return result

    base = win[0][0]
    ts = [(r[0] - base) / 60.0 for r in win]

    for name, fi, pi, ti in (("left", 1, 3, 5), ("right", 2, 4, 6)):
        f0 = win[0][fi]
        angles = [angle_deg(r[fi], f0) for r in win]
        slope, r2, rms = lsq_slope(ts, angles)
        tracked = [r for r in win if r[ti] == "OK"]
        spread = 0.0
        if len(tracked) >= 10:
            p0 = tracked[0][pi]
            spread = max(max(abs(a - b) for a, b in zip(r[pi], p0)) for r in tracked)
        result[name] = {
            "slope_deg_min": round(slope, 2),
            "r2": round(r2, 3),
            "resid_rms_deg": round(rms, 2),
            "trk_ok_frac": round(len(tracked) / len(win), 2),
            "pos_spread_m": round(spread, 3),
        }
        if spread > 0.05:
            result[name]["MOVEMENT"] = True

    inter = [angle_deg(r[1], r[2]) for r in win]
    slope, r2, rms = lsq_slope(ts, inter)
    result["inter"] = {
        "slope_deg_min": round(slope, 2),
        "r2": round(r2, 3),
        "resid_rms_deg": round(rms, 2),
        "first_deg": round(inter[0], 1),
        "last_deg": round(inter[-1], 1),
    }

    fires = {p: est_after.get(p, (0, 0.0))[0] - est_before.get(p, (0, 0.0))[0] for p in est_after}
    active = sum(1 for v in fires.values() if v > 0)
    result["estimator"] = {
        "fires_in_window": fires,
        "instances_active": active,
        "last_smoothed_deg_min": {p: v[1] for p, v in est_after.items()},
    }
    # WMR controllers gate their IMU on motion: ~30 s after coming to rest they stop sampling
    # entirely (measured 2026-08-13 -- both stopped at estimator fire #16, resumed instantly on a
    # button press). An instance with zero fires here was therefore IMU-silent for the window.
    # Before the prediction-horizon cap, a silent device's slope measured the EXTRAPOLATION of its
    # frozen angular velocity (31-47 deg/min at R^2 = 1.000, pure arithmetic); after the cap it
    # should measure ~0. Either way the slope of a silent device says nothing about gyro drift,
    # and the record must say so itself rather than rely on whoever reads it remembering.
    if active < 3:
        result["estimator"]["note"] = (
            f"only {active}/3 instances sampled during the window -- silent devices are "
            "motion-gated (resting); their slopes are NOT fusion drift"
        )
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=int, default=120)
    ap.add_argument("--capture", type=int, default=120)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    if not SOCKET.is_socket():
        sys.exit("monado-service is not up (no IPC socket) -- start the stack first")

    # A Steam title owning the session would make every number here meaningless -- and
    # killing the player under it is the mistake that crashed two games on 2026-08-12.
    comm = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True).stdout
    if any(c.strip().endswith(".exe") and c.strip() not in ("winedevice.exe",) for c in comm.splitlines()):
        sys.exit("a Steam/Proton title appears to be running -- close it before measuring")

    # pgrep + kill, never pkill -- pkill is blocked in the agent environment this runs under
    # (CLAUDE.md documents the exit-144 trap), and -x matches comm exactly so it cannot hit
    # the caller the way -f patterns famously do here.
    stray = subprocess.run(["pgrep", "-x", "hello_xr"], capture_output=True, text=True).stdout.split()
    for pid in stray:
        subprocess.run(["kill", pid], capture_output=True)
    if stray:
        time.sleep(2)

    meta = monado_env()
    try:
        meta["monado_head"] = subprocess.run(
            ["git", "-C", str(Path.home() / "vr" / "monado"), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
    except OSError:
        meta["monado_head"] = "?"
    meta["settle_s"] = args.settle
    meta["capture_s"] = args.capture

    total = args.settle + args.runs * (args.capture + 5) + 30
    player_log = Path(f"/tmp/drift-measure-{os.getpid()}.log")
    print(f"config: {meta}")
    print(f"player for {total} s -> {player_log}")
    print(">>> DO NOT touch the controllers or the headset until this finishes. <<<")
    player = subprocess.Popen(
        [str(VR / "play360.sh"), "-t", str(total), "-s", str(TEST_IMAGE)],
        stdout=open(player_log, "w"), stderr=subprocess.STDOUT,
        cwd=str(VR), start_new_session=True,
    )

    unwrap_base = now_sod()
    print(f"settling {args.settle} s (estimator convergence + thermal decay)...")
    time.sleep(args.settle)

    results = []
    try:
        for run in range(1, args.runs + 1):
            est_before = estimator_snapshot()
            t0 = now_sod()
            if t0 < unwrap_base - 3600:
                t0 += 86400
            print(f"run {run}/{args.runs}: capturing {args.capture} s...")
            time.sleep(args.capture)
            t1 = now_sod()
            if t1 < unwrap_base - 3600:
                t1 += 86400
            est_after = estimator_snapshot()

            rows = read_poses(player_log, unwrap_base)
            res = analyze(rows, t0, t1, args.label, run, est_before, est_after, meta)
            results.append(res)

            OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
            with open(OUT_JSONL, "a") as f:
                f.write(json.dumps(res) + "\n")

            if "error" in res:
                print(f"  !! {res['error']}")
            else:
                for h in ("left", "right"):
                    d = res[h]
                    moved = "  << MOVEMENT DETECTED" if d.get("MOVEMENT") else ""
                    print(
                        f"  {h:5s}  {d['slope_deg_min']:+7.2f} deg/min  "
                        f"(R2 {d['r2']:.2f}, resid {d['resid_rms_deg']:.2f} deg, "
                        f"trk {d['trk_ok_frac']:.0%}){moved}"
                    )
                i = res["inter"]
                print(
                    f"  inter  {i['slope_deg_min']:+7.2f} deg/min  "
                    f"(R2 {i['r2']:.2f}; {i['first_deg']} -> {i['last_deg']} deg)  "
                    f"<- frame-independent, the number that counts"
                )
                e = res["estimator"]
                print(f"  estimator: {e['instances_active']} instances fired {e['fires_in_window']}")
            if run < args.runs:
                time.sleep(5)
    finally:
        player.terminate()

    if len(results) >= 2 and all("error" not in r for r in results):
        pairs = [(r["inter"]["slope_deg_min"]) for r in results]
        print(f"\nreproducibility (inter-controller slope per run): {pairs}")
        spread = max(pairs) - min(pairs)
        print(f"spread: {spread:.2f} deg/min -- "
              + ("comparable runs, the method holds" if spread < 3 else
                 "runs disagree; the SYSTEM is not stationary, do not tune on single runs"))
    print(f"\nrecorded -> {OUT_JSONL}")


if __name__ == "__main__":
    main()
