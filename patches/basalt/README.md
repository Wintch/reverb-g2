# Basalt patches

Basalt is the VIT/SLAM implementation loaded for 6DoF head tracking
(`VIT_SYSTEM_LIBRARY_PATH=~/vr/basalt/build/libbasalt.so`, set by
`scripts/jack-in-wayland.sh <mode> 6dof`).

Base: `df6e970c8da7636eb401a09e3317fbeaaf829b9a`. `bootstrap-lab.sh sources` applies the 21
files listed in `applies-on-base.txt` (22 patches, since `0020-0021` is one file). The build is
`cmake --preset library`, which produces `libbasalt.so` without the Pangolin UI, so `SLAM_UI=1`
does nothing. After a build, check that `libbasalt.so` exists: a failed configure can leave a
directory that looks built.

0022 is Mateo de Mayo's upstream fix from `mateosss/efix`, author preserved.

| # | What |
|---|---|
| 0001 | `--cam-calib` optional, so a config file can carry pipeline settings only (pairs with Monado 0020 `SLAM_CONFIG_PIPELINE_ONLY`). The state-output queue capacity is now set on every path |
| 0002 | Input image queue capped at 2 and drops the oldest frame instead of blocking. Frame-to-pose age p50 819 ms to 109 ms; delivered position residual at rest 9.8 mm to 0.57 mm |
| 0003-0006 | `VIT_COLLAPSE_LOG=1` instrumentation (input/output rate, queue depth, VIO and frontend timings, loop waits), off by default. Used to localise the SLAM pose-rate collapse |
| 0007 | `BASALT_IMU_NONBLOCK_CATCHUP`: IMU catch-up uses `try_pop` instead of blocking. The fix for the collapse (`docs/39`) |
| 0008 | Makes 0007 the default. Validated over a 919 s soak with no collapse. `=0` restores the old behaviour |
| 0009 | Caps the optical-flow to VIO queue at 2 with drop-oldest. **Measured negative result**: every surviving frame became a keyframe and output fell to 2.5 Hz |
| 0010 | Corrects 0009: the capped queue blocks by default, drop-oldest is opt-in (`BASALT_VISION_DROP_OLDEST=1`) |
| 0011 | Caps `ExecutionStats` per-key vectors (they grew about 72 MB/h on the live path) |
| 0012 | Names the worker threads (`bslt-optflow`, `bslt-vio`, `bslt-vo`) for `top -H`, `perf sched` and pinning |
| 0013 | `VIT_DUMP_CALIB=<path>` dumps the live calibration as Basalt JSON, so a recorded EuRoC session can be replayed offline (`scripts/replay-basalt-variants.py`) |
| 0014 | `prunePatches()` bounds the landmark-recall patch map, which leaked about 18 GB in three minutes. `BASALT_RECALL_PATCH_GRACE_FRAMES` (default 90, 0 = unbounded) |
| 0015 | Recall patches are built in parallel (`tbb::parallel_for`) |
| 0016 | The `prunePatches()` sweep is amortised over a second instead of one 88 ms frame |
| 0017 | `VIT_CAM_TIME_OFFSET_NS` shifts camera stamps against the IMU (default 0). Replayed yaw drift was strongly sensitive to it; the driver-side form is Monado 0101 |
| 0018 | `prunePatches()` no longer scans all of `patch_last_seen` |
| 0019 | Per-stage timing on the `vit_of` log line (with `VIT_COLLAPSE_LOG=1`) |
| 0020-0021 | `age_in_ms` / `age_out_ms` on the collapse-log lines; `VIT_QUEUE_DEPTH` sets both live queues (default 2). Known caveat: the ages are biased by `VIT_CAM_TIME_OFFSET_NS` when it is non-zero |
| 0022 | Fixes the multi-camera essential-constraint index (cameras 2 and 3 were checked against camera 1's extrinsic). The G2 has four cameras. Not on upstream `main` at 2026-10-18 |

## Why the detection settings matter

Basalt's default pipeline settings equal its EuRoC settings. On the G2's four 640x480 fisheye
cameras they detect far too few points: a mean of 0.0 to 0.9 landmarks per camera, and the pose
was pure IMU dead reckoning. `grid_size 30`, `num_points_cell 3`, `min_threshold 3` took static
drift to 0.72 m at 60 s. No single parameter was enough on its own. Use
`SLAM_CONFIG=<file.toml> SLAM_CONFIG_PIPELINE_ONLY=1` to try variants.

## Upstream

The recall patch leak (0014, 0016, 0018) is upstream's own ("Patches are never getting
deleted"). Upstream's fix, `mateosss/basalt` !39, has sat un-rebased since 2024-03. Our
variant was offered on it (see `docs/149-basalt-upstream-sync-2026-10-18.md`).
