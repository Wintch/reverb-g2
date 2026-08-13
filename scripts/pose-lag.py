#!/usr/bin/env python3
"""How stale is the pose we render against? Measured, per stage, from the CSVs.

Born 2026-08-13 (T175/T176). Pipelined pacing fixed the missed slots, and the
wearer immediately saw what the pacing meter cannot: a ghost whose separation
from the real image GROWS WITH HEAD ROTATION SPEED. That is the signature of a
fixed time lag -- angular separation = angular velocity x lag -- so the useful
question stopped being "how many frames are late" and became "how many
milliseconds old is the pose in the frame".

This answers it without touching the session, the cable or the headset: Monado
already writes the three stages of the output pipeline as separate CSVs
(SLAM_WRITE_CSVS=1), each with its own timestamps:

    tracking.csv    raw SLAM output, at camera rate (~30 Hz here)
    filtering.csv   after the output filter (SLAM_FILTER=one_euro), at IMU rate
    prediction.csv  after forward prediction -- this is what rendering uses

METHOD. A pure time delay between two versions of the same motion shows up as
the shift that best aligns them, so: pick the quaternion component with the most
variance (best signal-to-noise for whatever axis was actually moved), resample
both streams onto a uniform grid, and scan shifts, keeping the one with the
lowest sum of squared differences. Reported in milliseconds, positive meaning
the second stream LAGS the first.

WHAT THE NUMBERS MEAN, and the honest limit of this tool: it measures the lag
BETWEEN STAGES, not the absolute photon-to-pose latency. It cannot see the
camera exposure -> SLAM result delay (tracking.csv is stamped with the frame's
own timestamp, not with when the result appeared), nor the scanout. So a clean
result here does not prove the total is small -- it localises which stage of the
part we control is spending the milliseconds.

MOTION IS REQUIRED. With the headset sitting still every shift fits equally well
and the answer is meaningless; the script refuses to report in that case rather
than printing a confident zero.

    ./scripts/pose-lag.py [session_dir]      # default: newest ~/vr/logs/slam-*
"""

import sys
from pathlib import Path

MAX_SHIFT_MS = 80.0
STEP_MS = 0.5
GRID_HZ = 400.0


def load(path):
    """-> (times_s, [q_w, q_x, q_y, q_z] columns). Timestamps are ns."""
    ts, cols = [], [[], [], [], []]
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split(",")
            if len(p) < 8:
                continue
            try:
                ts.append(int(p[0]) / 1e9)
                for i in range(4):
                    cols[i].append(float(p[4 + i]))
            except ValueError:
                continue
    return ts, cols


def pick_channel(cols):
    """The axis that actually moved carries the signal; the others carry noise."""
    best, best_var = 0, -1.0
    for i, c in enumerate(cols):
        if len(c) < 2:
            continue
        m = sum(c) / len(c)
        var = sum((x - m) ** 2 for x in c) / len(c)
        if var > best_var:
            best, best_var = i, var
    return best, best_var


def resample(ts, vals, t0, t1, hz):
    """Linear interpolation onto a uniform grid. The streams run at different
    rates (30 Hz vs IMU rate), so they cannot be compared sample to sample."""
    out, n = [], int((t1 - t0) * hz)
    j = 0
    for k in range(n):
        t = t0 + k / hz
        while j + 1 < len(ts) and ts[j + 1] < t:
            j += 1
        if j + 1 >= len(ts):
            out.append(vals[-1])
            continue
        span = ts[j + 1] - ts[j]
        f = 0.0 if span <= 0 else (t - ts[j]) / span
        out.append(vals[j] + f * (vals[j + 1] - vals[j]))
    return out


def best_shift(ref, test, hz):
    """Shift `test` against `ref`; return (lag_ms, normalised residual)."""
    max_k = int(MAX_SHIFT_MS / 1000.0 * hz)
    step_k = max(1, int(STEP_MS / 1000.0 * hz))
    n = min(len(ref), len(test))
    best_k, best_sse = 0, None
    for k in range(-max_k, max_k + 1, step_k):
        lo, hi = max(0, k), min(n, n + k)
        if hi - lo < hz:  # need at least a second of overlap
            continue
        sse = 0.0
        for i in range(lo, hi):
            d = test[i] - ref[i - k]
            sse += d * d
        sse /= (hi - lo)
        if best_sse is None or sse < best_sse:
            best_k, best_sse = k, sse
    return best_k / hz * 1000.0, best_sse


def compare(name, a_path, b_path):
    ta, ca = load(a_path)
    tb, cb = load(b_path)
    if len(ta) < 10 or len(tb) < 10:
        print(f"  {name}: sin datos suficientes")
        return
    ch, var = pick_channel(ca)
    t0, t1 = max(ta[0], tb[0]), min(ta[-1], tb[-1])
    if t1 - t0 < 5:
        print(f"  {name}: menos de 5 s en comun, no alcanza")
        return
    ra = resample(ta, ca[ch], t0, t1, GRID_HZ)
    rb = resample(tb, cb[ch], t0, t1, GRID_HZ)
    m = sum(ra) / len(ra)
    sig = sum((x - m) ** 2 for x in ra) / len(ra)
    if sig < 1e-8:
        print(f"  {name}: el casco no se movió lo suficiente (varianza {sig:.2e}) -- "
              f"sin movimiento la medición no significa nada")
        return
    lag, sse = best_shift(ra, rb, GRID_HZ)
    frac = (sse / sig) if sig else float("nan")
    print(f"  {name}: {lag:+.1f} ms   (canal q[{ch}], residuo {frac*100:.2f}% de la señal, "
          f"{t1-t0:.0f} s)")


def main():
    if len(sys.argv) > 1:
        d = Path(sys.argv[1])
    else:
        dirs = sorted(Path.home().glob("vr/logs/slam-*"), key=lambda p: p.stat().st_mtime)
        if not dirs:
            print("No hay directorios de sesión en ~/vr/logs/")
            return 1
        d = dirs[-1]
    print(f"Sesión: {d}")
    print("Positivo = la segunda etapa ATRASA respecto de la primera.\n")
    compare("tracking -> filtering ", d / "tracking.csv", d / "filtering.csv")
    compare("filtering -> prediction", d / "filtering.csv", d / "prediction.csv")
    compare("tracking -> prediction ", d / "tracking.csv", d / "prediction.csv")
    print("\nA 200 grados/s de giro de cabeza, 10 ms de atraso = 2 grados de separación.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
