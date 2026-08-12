# Basalt patches

Basalt is the VIT/SLAM implementation this project loads for 6DoF head tracking
(`VIT_SYSTEM_LIBRARY_PATH=~/vr/basalt/build/libbasalt.so`, wired in by
`scripts/jack-in-wayland.sh <mode> 6dof`).

Pinned base SHA: **`df6e970c8da7636eb401a09e3317fbeaaf829b9a`** ("Fix cmake configure on
fedora"). Apply with `git am` on top of it, then rebuild — the build here is
`cmake --preset library`, which produces `libbasalt.so` **without** the Pangolin UI, so
`SLAM_UI=1` is a silent no-op on it (checked 2026-08-12: `nm -D libbasalt.so | grep -c
pangolin` = 0, and no window ever appears).

| # | Status | What it does |
|---|--------|--------------|
| 0001 | unfiled, verified live 2026-08-12 | Makes `--cam-calib` optional so a unified config file can carry pipeline settings only, with the calibration still arriving from the caller (`add_camera_calibration`/`add_imu_calibration`). Needs Monado's `0020` (`SLAM_CONFIG_PIPELINE_ONLY=1`) on the other side. Also moves `monado_out_state_queue.set_capacity(32)` so it runs in every path: `pop_state()` does "push the newest, drop the oldest" via `while (!try_push(x)) pop(_)`, which is a no-op on an unbounded queue, so the caller-driven path — the one Monado uses by default — let that queue grow without bound instead of dropping stale states. |

## Why this exists

Basalt's default pipeline settings are also its EuRoC settings (`data/default_config.json`
and `data/euroc/euroc_config.json` are byte-for-byte identical). On the Reverb G2's four
640x480 fisheye cameras those defaults detect far too few points: measured 2026-08-12, with
perfect-looking images and correct calibration, Basalt held a mean of **0.0–0.9 landmarks
per camera** and the pose was pure IMU dead reckoning — thousands of metres of runaway from
a motionless headset.

Raising detection to `grid_size 30`, `num_points_cell 3`, `min_threshold 3` took static
drift to **0.72 m at 60 s**, reproduced twice. No single one of the three parameters was
enough on its own (measured at 60 s: only-`num_points_cell` 4613 m, only-`min_threshold`
1791 m, only-`grid_size` 865 m) — it is a threshold effect, not one wrong knob.

Config files used for the sweep live in `~/vr/slam-configs/` on the lab machine, driven by
`SLAM_CONFIG=<file.toml> SLAM_CONFIG_PIPELINE_ONLY=1`.

## Known open bug, not fixed here

Under load — disk I/O from the EuRoC recorder, or CPU from more aggressive detection —
camera timestamps coming out of Monado's clock-offset conversion (`m_clock_offset_a2b` →
`cam_hw2mono` in `wmr_source.c`) go **non-monotonic**, and Basalt responds by aborting the
whole process:

```
***** Assertion (prev_frame->t_ns < curr_frame->t_ns) failed in
      basalt::SqrtKeypointVioEstimator<float>::initialize(...)::<lambda()>:
      sqrt_keypoint_vio.cpp:311: frame timestamps not monotonically increasing?!
```

Seen twice on 2026-08-12 with two different triggers, killing `monado-service` both times
(SIGABRT, coredump). This is currently the ceiling on tuning detection any harder, and it
can also end a real game session. Two candidate fixes, neither attempted: drop the
offending frame instead of aborting (Basalt side), or stabilise `cam_hw2mono` under load
(Monado side). See `docs/pruebas.jsonl` T162.
