# 149 — Basalt upstream sync and review, 2026-10-18

Summary: upstream Basalt (`gitlab.freedesktop.org/mateosss/basalt`, `origin/main` still at our
pinned base `df6e970`) had nothing new on main. One upstream fix was adopted as patch 0022; an
offline A/B showed no measurable difference on the G2 rig (section 3). Upstream's branches
(`mateosss/efix`, `nikitakarpuks/controller-tracking`, `tsantucci/loop-closure`, `mateosss/lp`,
`mateosss/brush-wip`) and Faulto's fork (Basalt patches 0001-0012 identical to ours) were reviewed.
Controller 6DoF is not a Basalt problem (see the verdicts below).

## 1. What was added: patch 0022 (`mateosss/efix`)

One line in `include/basalt/optical_flow/optical_flow.h:222`: the essential matrix for
camera `i` was built from `T_i_c[1]` for every `i`; it is now `T_i_c[i]`. Cherry-picked
unchanged (author Mateo de Mayo kept) onto `lab`; patch file
`patches/basalt/0022-optical_flow-fix-multi-camera-essential-constraint-index.patch`.
`libbasalt.so` rebuilds cleanly.

Review result (one reviewer + three adversarial verifiers, none could refute):

- **Correct.** `E = hat(t.normalized()) * R` of `T_c0_ci`, consumed as `p3d0^T E[cam_id] p3d1`
  — the same convention `trackPoints` uses. The old code was right only for `i = 1`.
- **Active on the G2 live path.** `optical_flow_type = frame_to_frame`,
  `optical_flow_epipolar_error = 0.005` in both G2 configs; `filterPoints()` runs
  unconditionally after `addPoints()`; the jack-in scripts load
  `build/libbasalt.so`.
- **Narrow effect.** Only `E[2]` and `E[3]` change (`E[0]` is never read, `E[1]` is
  identical), and only for keypoint ids present in both cam 0 and cam 2/3. Points
  detected independently in cam 2/3 are not tested.
- **Nothing downstream relied on the old behaviour** (`E` is read only in the three
  `filterPointsForCam` implementations).
- **Expected direction, unmeasured:** more cam0↔cam2/3 tracks survive, fewer outlier
  cross-camera observations. Possible cost: more observations in the optimizer, and the
  0.005 threshold was tuned under the old behaviour and may need a retune.

## 2. Series audit (0001–0022 vs `lab`)

- Base + the 21 patch files = the `lab` tree exactly (empty `git diff`). 21 files because
  0020+0021 share one file; numbering skips nothing else. `applies-on-base.txt`: 21 clean.
- No semantic conflicts between queue patches (0002/0009/0010/0021) or between the
  `prunePatches` patches (0014/0016/0018).
- README fixes (documentation only, no code): 0012 row added (it was missing);
  `VIT_COLLAPSE_LOG` is on for any value of the variable; 0009 flag-name note; 0021
  wording about deterministic mode and `BASALT_VISION_NONBLOCK=0`; 0014/0016 superseded
  notes plus the `frame_to_frame`-only coverage caveat; 0020 offset caveat.
- Open code nits, not changed (they need a rebuild and a live check): `age_in_ms` /
  `age_out_ms` are biased by `VIT_CAM_TIME_OFFSET_NS` (subtract the unshifted
  `s->timestamp`); stale comments in `prunePatches()` and the `BASALT_VISION_NONBLOCK`
  block of `vit_tracker.cpp`.

## 3. Offline A/B of 0022 — result: no measurable difference

Setup: `euroc-yaw2_20260829060819` (4 cameras, 9273 frames, 308 s), config
`~/vr/basalt-g2-config.json`, 6 threads, 1x, serial and interleaved ctl/after/ctl/after.
`ctl` = `lab` minus 0022 (a separate worktree); `after` = `lab` with 0022; both
`basalt_vio` built 2026-10-17 (the 08-27 binary is kept as `basalt_vio.aug27`). Metrics come from `scripts/replay-basalt-variants.py`.

| metric | ctlA | ctlB | aftA | aftB |
|---|---|---|---|---|
| wall s | 332.5 | 329.8 | 330.9 | 330.3 |
| rms ATE m | 0.5292 | 0.5291 | 0.5280 | 0.5280 |
| position span m | 1.633 | 1.641 | 1.635 | 1.635 |
| max 1 s displacement m | 0.6858 | 0.6859 | 0.6859 | 0.6859 |
| windows > 0.5 m / > 1 m | 4 / 0 | 4 / 0 | 4 / 0 | 4 / 0 |
| frontend p99 ms | 41.43 | 41.03 | 41.31 | 40.95 |
| optimizer p99 ms | 18.60 | 18.89 | 18.24 | 18.54 |
| landmarks p50 / p10, 0-30 deg/s | 146 / 34 | 154 / 40 | 150 / 44 | 150 / 44 |
| landmarks p50 / p10, 30-90 | 207 / 35 | 207 / 35 | 207 / 34 | 207 / 34 |
| landmarks p50 / p10, 90-180 | 118 / 5 | 118 / 5 | 118 / 5 | 118 / 5 |
| landmarks p50 / p10, 180-360 | 24 / 0 | 24 / 0 | 24 / 0 | 24 / 0 |
| keypoints p50 (all bands) | identical to ±2 | | | |

Reading: every difference between ctl and after is inside the ctlA/ctlB spread (the noise
floor: the 0-30 deg/s landmark p10 moves 34→40 between two identical control runs). No
regression in drift, ATE, landmark survival or frame time; no gain either.

Why this is the expected outcome: with `optical_flow_detection_nonoverlap = true`, the epipolar
filter only judges ids shared by cam 0 and cam 2/3, and the optical axes of cam 2 and cam 3
are 76.6° and 95.9° from cam 0 (cam 1: 19.4°) in `calib-g2-yaw2.json`. Cross-camera
matches between cam 0 and the side cameras should be rare, so the line changes almost
nothing for this rig. This was inferred from the geometry; the number of surviving
cam0↔cam2/3 matches was **not** instrumented.

Decision: keep 0022 (it is a correctness fix, harmless here, and it matters for rigs whose
cameras overlap); **no headset session is justified for it** — the plan's gate was "live
only if the offline result is non-null". Caveats: one dataset (yaw protocol), one config,
replay feeds every frame (`outq_dropped=0`), and this proves nothing about `age_in/out` or
the queue patches, which only exist on the live path.

## 4. Upstream branches — verdicts

| Branch | Verdict |
|---|---|
| `nikitakarpuks/controller-tracking` | Name misleading: OptiTrack mocap ground-truth + calibration tooling for the **headset**; controllers explicitly out of scope. Do not merge. Keep `cam_calib.cpp:588-690` (`initCamExtrinsics` via Prim's algorithm; the old chain search left one camera at identity on a 4-camera rig) as a cherry-pick candidate for the next `basalt_calibrate` run. Merge is clean. |
| `tsantucci/loop-closure` | WATCH. Hash-BoW loop detection, PnP-RANSAC, pose graph, loop fusion; 106 commits from an older base (`72e01f7eb`), conflicts in `optical_flow.h`. Could cut long-term head drift; costs CPU; adopting means re-porting our series. Re-check after a rebase onto main. |
| `mateosss/lp` | Ignore. CI/dataset configs only (grid 40 / min_threshold 20 for EuRoC-type sets). Optional offline sweep arm. |
| `mateosss/brush-wip` | Ignore. Real-time Gaussian-splatting demo on top of loop-closure; CUDA/TensorRT; FoundationStereo (NVlabs) and Brush licences must be checked against the MIT policy before anything. |

Controller 6DoF is **not** a Basalt problem: docs/125 and docs/126 put it in Monado's
constellation blob-to-device correspondence (device owns 0 of 15 blobs, recovery needs 4).
No Basalt branch helps.
