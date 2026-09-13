#!/usr/bin/env python3
"""predict-error.py -- how far does the PREDICTED pose land from where the head really was?

The gap this fills (2026-09-13): every other tool in slam-analysis measures the raw tracker
(jumps, drift, latency). None of them measure the PREDICTION layer, which is where
SLAM_PRED_NECK_ARM_MM / FREEZE_POSITION / POSITION_HORIZON_MS actually act -- so the artifacts
those knobs introduce ("it carries me further than I turned", "pitching down drops me") had no
instrument at all and could only ever be judged by a wearer.

Method, and why it is valid:
  t_tracker_slam.cpp pushes prediction.csv as {when_ns, predicted_pose} -- i.e. each row is the
  runtime's claim about where the head IS at time `when_ns`. tracking.csv is pushed as
  {frame_ts, raw_pose} -- Basalt's own later, unextrapolated estimate for that same instant.
  So interpolating tracking.csv at a prediction row's timestamp gives the reference that the
  prediction was trying to anticipate, and the difference is prediction error.

  Reference caveat, stated plainly: tracking.csv is Basalt's estimate, not external ground truth.
  It drifts and it gets yanked by the anchor guard. That makes it useless as an absolute position
  reference -- but this tool only ever reads it over a ~150 ms prediction horizon, and it drops
  samples near guard resets outright, so what survives is a fair local reference.

Errors are reported in HEAD-LOCAL axes (right / up / back), because that is how they are felt:
horizontal error during a yaw is "it carried me sideways", vertical error during a pitch is
"I sank". Binned by the true angular rate, since both artifacts are rate-dependent by
construction (the neck-arm term is (R_pred - R_anchor) * arm -- zero at rest, growing with how
far orientation advanced during the gap).

Usage:  predict-error.py <session_dir> [--label NAME] [--json]
        session_dir holds tracking.csv + prediction.csv (e.g. /mnt/vrtmp/slam-<ts>/)
"""
import sys
import json
import numpy as np

RESET_JUMP_M = 0.5      # same threshold count-jumps.py uses for a guard reset
RESET_GUARD_S = 0.5     # drop prediction samples within this of a reset
MAX_GAP_S = 0.10        # never interpolate the reference across a longer dropout


def load_csv(path):
    # A run killed mid-flush leaves a half-written final row, so parse row by row rather than
    # letting np.loadtxt abort on it.
    rows = []
    with open(path) as fh:
        next(fh, None)
        for line in fh:
            f = line.rstrip("\n").split(",")
            if len(f) != 8:
                continue
            try:
                rows.append([float(v) for v in f])
            except ValueError:
                continue
    a = np.array(rows, dtype=np.float64)
    return a[:, 0].astype(np.int64), a[:, 1:4], a[:, 4:8]  # ts, pos, quat(w,x,y,z)


def quat_to_mat(q):
    """(N,4) w,x,y,z -> (N,3,3)"""
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
        np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
        np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1),
    ], -2)


def slerp(q0, q1, t):
    """Row-wise slerp. q0,q1 (N,4); t (N,)"""
    q1 = q1.copy()
    d = np.sum(q0 * q1, axis=1)
    flip = d < 0
    q1[flip] *= -1
    d = np.abs(d)
    d = np.clip(d, -1.0, 1.0)
    th = np.arccos(d)
    s = np.sin(th)
    near = s < 1e-6           # degenerate: fall back to lerp
    s_safe = np.where(near, 1.0, s)
    a = np.where(near, 1.0 - t, np.sin((1.0 - t) * th) / s_safe)
    b = np.where(near, t, np.sin(t * th) / s_safe)
    out = a[:, None] * q0 + b[:, None] * q1
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def quat_mul(a, b):
    aw, ax, ay, az = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    bw, bx, by, bz = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    return np.stack([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ], -1)


def body_rates(ts, q):
    """Body-frame angular velocity (rad/s) between consecutive samples, reported at the
    midpoint. Returns (ts_mid, w) with w[:,0]=pitch(X) w[:,1]=yaw(Y) w[:,2]=roll(Z)."""
    dt = np.diff(ts) / 1e9
    ok = dt > 1e-6
    q0, q1 = q[:-1], q[1:]
    inv = q0 * np.array([1.0, -1.0, -1.0, -1.0])
    rel = quat_mul(inv, q1)
    rel = np.where(rel[:, :1] < 0, -rel, rel)          # shortest arc
    vec = rel[:, 1:]
    n = np.linalg.norm(vec, axis=1)
    ang = 2.0 * np.arctan2(n, np.clip(rel[:, 0], -1.0, 1.0))
    axis = np.where(n[:, None] > 1e-9, vec / np.where(n[:, None] > 1e-9, n[:, None], 1.0), 0.0)
    w = axis * (ang / np.where(ok, dt, 1.0))[:, None]
    mid = ts[:-1] + np.diff(ts) // 2
    return mid[ok], w[ok]


def pct(x, p):
    return float(np.percentile(x, p)) if len(x) else float("nan")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    d = args[0].rstrip("/")
    label = next((f.split("=", 1)[1] for f in flags if f.startswith("--label=")), d.split("/")[-1])

    t_ts, t_pos, t_q = load_csv(f"{d}/tracking.csv")
    p_ts, p_pos, p_q = load_csv(f"{d}/prediction.csv")

    # --- reference resets: drop prediction samples near a tracker discontinuity -------------
    step = np.linalg.norm(np.diff(t_pos, axis=0), axis=1)
    reset_ts = t_ts[1:][step > RESET_JUMP_M]

    # --- interpolate the reference at each prediction timestamp -----------------------------
    lo, hi = t_ts[0], t_ts[-1]
    keep = (p_ts >= lo) & (p_ts <= hi)
    p_ts, p_pos, p_q = p_ts[keep], p_pos[keep], p_q[keep]

    idx = np.searchsorted(t_ts, p_ts, side="right") - 1
    idx = np.clip(idx, 0, len(t_ts) - 2)
    t0, t1 = t_ts[idx], t_ts[idx + 1]
    gap = (t1 - t0) / 1e9
    frac = np.where(gap > 0, (p_ts - t0) / 1e9 / np.where(gap > 0, gap, 1.0), 0.0)
    ref_pos = t_pos[idx] + (t_pos[idx + 1] - t_pos[idx]) * frac[:, None]
    ref_q = slerp(t_q[idx], t_q[idx + 1], frac)

    good = gap <= MAX_GAP_S
    if len(reset_ts):
        near = np.min(np.abs(p_ts[:, None] - reset_ts[None, :]), axis=1) / 1e9
        good &= near > RESET_GUARD_S

    p_ts, p_pos, ref_pos, ref_q = p_ts[good], p_pos[good], ref_pos[good], ref_q[good]

    # --- error, expressed in head-local axes (right / up / back) ----------------------------
    e_world = p_pos - ref_pos
    R = quat_to_mat(ref_q)                      # head->world
    e_head = np.einsum("nji,nj->ni", R, e_world)  # world->head via R^T
    right, up, back = e_head[:, 0], e_head[:, 1], e_head[:, 2]
    horiz = np.hypot(right, back)
    mag = np.linalg.norm(e_head, axis=1)

    # --- true angular rate at each surviving prediction sample ------------------------------
    w_ts, w = body_rates(t_ts, t_q)
    wi = np.clip(np.searchsorted(w_ts, p_ts, side="right") - 1, 0, len(w_ts) - 1)
    pitch_rate = np.degrees(w[wi, 0])
    yaw_rate = np.degrees(w[wi, 1])

    out = {"label": label, "dir": d, "samples": int(len(p_ts)),
           "resets_in_reference": int(len(reset_ts)),
           "err_mag_mm": {"p50": pct(mag, 50) * 1000, "p90": pct(mag, 90) * 1000,
                          "p99": pct(mag, 99) * 1000}}

    print(f"=== {label} ===")
    print(f"  {len(p_ts)} usable prediction samples "
          f"({int(keep.sum() - good.sum())} dropped near {len(reset_ts)} reference resets)")
    print(f"  prediction error magnitude: p50 {pct(mag,50)*1000:6.1f} mm   "
          f"p90 {pct(mag,90)*1000:6.1f} mm   p99 {pct(mag,99)*1000:6.1f} mm")

    # --- the two artifacts, binned by the rate that drives them ------------------------------
    print("\n  HORIZONTAL error vs |yaw rate|   <- 'it carries me further than I turned'")
    print("    |yaw| deg/s      n      horiz p50   horiz p90    signed right p50")
    bins = [(0, 10), (10, 30), (30, 60), (60, 120), (120, 1e9)]
    out["yaw_bins"] = []
    for a, b in bins:
        m = (np.abs(yaw_rate) >= a) & (np.abs(yaw_rate) < b)
        if m.sum() < 20:
            continue
        row = {"lo": a, "hi": None if b > 1e8 else b, "n": int(m.sum()),
               "horiz_p50_mm": pct(horiz[m], 50) * 1000, "horiz_p90_mm": pct(horiz[m], 90) * 1000,
               "right_p50_mm": pct(right[m], 50) * 1000}
        out["yaw_bins"].append(row)
        hi = "  inf" if b > 1e8 else f"{b:5.0f}"
        print(f"    {a:5.0f}-{hi}  {m.sum():7d}   {pct(horiz[m],50)*1000:8.1f}mm "
              f"{pct(horiz[m],90)*1000:9.1f}mm   {pct(right[m],50)*1000:+10.1f}mm")

    print("\n  VERTICAL error vs pitch rate     <- 'pitching down drops me'")
    print("    pitch deg/s      n       up p50      up p90")
    pbins = [(-1e9, -60), (-60, -20), (-20, 20), (20, 60), (60, 1e9)]
    out["pitch_bins"] = []
    for a, b in pbins:
        m = (pitch_rate >= a) & (pitch_rate < b)
        if m.sum() < 20:
            continue
        row = {"lo": None if a < -1e8 else a, "hi": None if b > 1e8 else b,
               "n": int(m.sum()), "up_p50_mm": pct(up[m], 50) * 1000,
               "up_p90_mm": pct(up[m], 90) * 1000}
        out["pitch_bins"].append(row)
        lo = " -inf" if a < -1e8 else f"{a:5.0f}"
        hi = "  inf" if b > 1e8 else f"{b:5.0f}"
        print(f"    {lo}-{hi}  {m.sum():7d}   {pct(up[m],50)*1000:+8.1f}mm {pct(up[m],90)*1000:+9.1f}mm")

    if "--json" in flags:
        print("\nJSON " + json.dumps(out))


if __name__ == "__main__":
    main()
