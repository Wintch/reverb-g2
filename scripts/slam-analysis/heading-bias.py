#!/usr/bin/env python3
"""heading-bias.py -- is the controller's heading error a stale gyro bias, or is it noise?

Reads what monado lab patch 0107 (WMR_CONTROLLER_HEADING_CSV) writes: one row per constellation
solve reaching apply_solve_yaw_correction, accepted or distrusted.

The question (docs/125 step 3): the blob-to-LED correspondence needs a trusted heading, and the
heading's noise under worn motion (10-30 deg) is wider than the LED spacing it must resolve
(~11 deg). m_imu_3dof's gyro-bias estimator fires ONLY while the controller is still, and
gravity never observes yaw -- so under motion yaw integrates freely against a bias last measured
who knows when. If |yaw_err| grows with how stale that estimate is, a better estimator is a real
fix. If it does not, that branch is dead.

THE CONFOUND, and why this script does not just print a correlation: bias_age_ms and motion are
not independent. The estimator only fires while still, so a large age means "has been moving for
a while" -- and motion has its own reasons to produce heading error (higher gyro noise, worse
blob detection, faster real rotation between frame and solve). A raw yaw_err-vs-age correlation
would therefore be positive even if staleness had no causal role at all. The 2D table below is
the control: read DOWN a motion column. If age still matters at fixed motion, the effect is real.

  heading-bias.py <csv> [<csv> ...]
"""
import sys

import numpy as np

AGE_BINS = [0, 250, 1000, 4000, 15000, np.inf]      # ms since the bias estimator last ran
MOTION_BINS = [0, 0.1, 0.5, 1.5, np.inf]            # |gyro| rad/s, after bias removal


def pct(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")


def bin_label(edges, i, unit):
    lo, hi = edges[i], edges[i + 1]
    return f"{lo:g}-{hi:g}{unit}" if np.isfinite(hi) else f">{lo:g}{unit}"


def load(path):
    rows = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8",
                         invalid_raise=False)
    if rows.shape == ():
        rows = rows.reshape(1)
    return rows


def report(path, r):
    err = np.abs(r["yaw_err_deg"])
    age = r["bias_age_ms"]
    gyro = r["gyro_len"]
    acc = r["accepted"].astype(bool)

    print(f"\n=== {path} ===")
    print(f"  {len(r)} solves: {acc.sum()} accepted, {(~acc).sum()} distrusted as ghosts "
          f"({100.0 * (~acc).sum() / max(len(r), 1):.1f}%)")
    print(f"  |yaw err|: p50 {pct(err, 50):.1f}deg  p90 {pct(err, 90):.1f}deg  "
          f"p99 {pct(err, 99):.1f}deg  max {err.max() if len(err) else float('nan'):.1f}deg")
    print(f"  bias estimator fired {int(r['bias_fires'].max()) if len(r) else 0} times; "
          f"{(age < 0).sum()} solves had NO bias estimate yet")
    bmag = np.sqrt(r["bias_x"] ** 2 + r["bias_y"] ** 2 + r["bias_z"] ** 2)
    print(f"  |bias| p50 {pct(bmag, 50) * 180 / np.pi * 60:.1f} deg/min "
          f"(y-axis alone {pct(np.abs(r['bias_y']), 50) * 180 / np.pi * 60:.1f} deg/min)")

    # Rows with no estimate yet are a different state, not a very stale one -- see patch 0107.
    ok = age >= 0
    if ok.sum() < 20:
        print("\n  !! too few rows with a bias estimate to say anything -- not concluding")
        return
    err, age, gyro, acc = err[ok], age[ok], gyro[ok], acc[ok]

    print("\n  |yaw err| by staleness of the bias estimate   <- the hypothesis")
    print(f"    {'bias age':>14} {'n':>7} {'p50':>9} {'p90':>9} {'ghost %':>9}")
    for i in range(len(AGE_BINS) - 1):
        m = (age >= AGE_BINS[i]) & (age < AGE_BINS[i + 1])
        if m.sum() == 0:
            continue
        print(f"    {bin_label(AGE_BINS, i, 'ms'):>14} {m.sum():>7} {pct(err[m], 50):>8.1f}d "
              f"{pct(err[m], 90):>8.1f}d {100.0 * (~acc[m]).sum() / m.sum():>8.1f}%")

    print("\n  |yaw err| by how fast the controller is moving   <- the confound")
    print(f"    {'|gyro|':>14} {'n':>7} {'p50':>9} {'p90':>9} {'ghost %':>9}")
    for j in range(len(MOTION_BINS) - 1):
        m = (gyro >= MOTION_BINS[j]) & (gyro < MOTION_BINS[j + 1])
        if m.sum() == 0:
            continue
        print(f"    {bin_label(MOTION_BINS, j, ' rad/s'):>14} {m.sum():>7} {pct(err[m], 50):>8.1f}d "
              f"{pct(err[m], 90):>8.1f}d {100.0 * (~acc[m]).sum() / m.sum():>8.1f}%")

    print("\n  |yaw err| p50, age DOWN vs motion ACROSS   <- read a column: does age still matter?")
    head = "".join(f"{bin_label(MOTION_BINS, j, ''):>12}" for j in range(len(MOTION_BINS) - 1))
    print(f"    {'':>14}{head}     (rad/s)")
    for i in range(len(AGE_BINS) - 1):
        cells = ""
        for j in range(len(MOTION_BINS) - 1):
            m = ((age >= AGE_BINS[i]) & (age < AGE_BINS[i + 1]) &
                 (gyro >= MOTION_BINS[j]) & (gyro < MOTION_BINS[j + 1]))
            cells += f"{pct(err[m], 50):>10.1f}d" if m.sum() >= 15 else f"{'-':>11}"
        print(f"    {bin_label(AGE_BINS, i, 'ms'):>14}{cells}")
    print("    (cells with fewer than 15 samples are left blank rather than shown as noise)")

    # A residual bias would make the error grow linearly with age at a fixed rate. Fit that slope
    # inside the quietest motion bin, where the confound is weakest -- NOT over everything.
    quiet = gyro < MOTION_BINS[1]
    if quiet.sum() >= 30 and np.ptp(age[quiet]) > 500:
        slope, _ = np.polyfit(age[quiet], err[quiet], 1)
        print(f"\n  Within the quietest motion bin ({quiet.sum()} samples), |yaw err| grows "
              f"{slope * 1000:.2f} deg per second of staleness,")
        print(f"    i.e. an implied unestimated residual bias of {slope * 1000 * 60:.1f} deg/min. "
              f"Compare against the 20-72 deg/min")
        print("    measured at rest on this hardware (m_imu_3dof.h). A slope near zero kills the "
              "bias hypothesis.")
    else:
        print("\n  Not enough quiet-bin spread to fit a slope -- capture a session with real "
              "still stretches in it.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for path in sys.argv[1:]:
        try:
            r = load(path)
        except OSError as e:
            print(f"!! {path}: {e}")
            continue
        if len(r) == 0:
            print(f"\n=== {path} ===\n  empty -- the controller never produced a solve. A window "
                  "with sleeping controllers is not a control; re-run it.")
            continue
        report(path, r)


if __name__ == "__main__":
    main()
