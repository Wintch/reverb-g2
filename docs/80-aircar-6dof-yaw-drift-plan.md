# 80 — Aircar 6dof: fast-yaw position drift, from experiment plan to resolved recipe

Aircar 6dof (seated, Xbox pad, constellation OFF, lit room) started at "gold, not platinum": no VIO
runaways in a 6-minute wearer window (max frame-to-frame jump 0.17 m), clean 90 fps, but a **fast yaw turn
drifted the wearer out of the seat far more than the same speed of pitch or roll** (wearer's estimate:
~20x), fixed by the pad's recentre button, plus a subtle periodic "redraw" that 3dof lacks. Sections 1-5 are
the original analysis; everything after is what the experiments showed.

**Where it ended**: the seated-6dof recipe (patch 0097 + `SLAM_CORRECTION_SPREAD_MS`) removed the metres of
drift; the remaining metre-scale yaw drift was **Basalt's landmark set collapsing under yaw** (fixed
offline by a backend config, `scripts/basalt-variants/P2.json`) plus a **camera-stamp lateness of 5-10 ms**
(H1 confirmed offline; patch 0101 banks most of it). What is left is a small rotation-onset displacement
that responds to the neck-arm length.

**Headline of the first analysis**: the raw numbers do **not** show a continuous "position error scales
with yaw rate" law; pitch/roll shows slightly *more* apparent position velocity per degree/s than yaw at
matched rates. What they show is (a) yaw bursts are ~4x more frequent and larger in a seated cockpit, and
(b) two structural facts: position is double-integrated from raw accelerometer between SLAM updates, and
yaw has no gravity-anchored self-correction the way roll/pitch do.

## 1. What prior docs already establish (don't re-litigate)

- **docs/34** §3B: gravity correction (`m_imu_3dof.c`) removes *tilt* drift by aligning measured gravity
  to world-up. Yaw has no absolute reference in a monocular/stereo VIO system (the standard
  4-DoF-unobservable property: 3 position + yaw).
- **docs/39 / docs/44**: the SLAM pose-rate collapse and the camera/IMU clock-domain skew are closed
  (Basalt `BASALT_IMU_NONBLOCK_CATCHUP` default-on; Monado `0055`).
- **T211/T212** (`docs/pruebas.jsonl`): a 9%-of-yaw roll/pitch leak from gyro mounting misalignment
  (`WMR_HMD_GYRO_MOUNT_FIX`, `wmr_hmd.c:2068-2143`, default off) was **refuted by held-out data**
  (slope +0.003/+0.001 at R² 0.01/0.00 vs 0.60/0.44). **Do not re-enable it.** It is also unrelated: this is
  *position* drift keyed to *rotation rate*, not a fixed-axis rotation leak.
- With constellation OFF (Aircar's profile) ~0% of camera frames are diverted to controller tracking
  and SLAM gets the full ~30 Hz stream. Basalt's frontend is over-budget at 30 Hz (p50 46 ms vs 33 ms in
  that session) and detection/matching is single-threaded, so fast yaw has little headroom.
- A "resting produces a reset storm" pattern (headset set down, raw pose parked at tens of metres) is
  known and unrelated to the yaw data. Basalt is fed 2 cameras by default
  (`WMR_MAX_SLAM_CAMS` compile default 2, `SLAM_CAM_COUNT` 2; the driver can expose up to 4,
  `WMR_MAX_CAMERAS=4`); pure-rotation parallax starvation applies to both.

## 2. What the 2026-08-26 CSVs show

Source: the session's `{tracking,filtering,prediction,timing}.csv`. `tracking.csv` is Basalt's raw
~30 Hz VIO output; `prediction.csv`/`filtering.csv` are Monado's delivered stream, queried once
per eye per compositor frame (~90 Hz per eye after de-interleaving) — the one that matters for
"does the position channel jump during fast yaw".

- **Pose rate / diversion:** 55,366 valid rows over 2294.7 s at a **median 33.16 ms interval =
  30.15 Hz** — the full camera rate, ~0% controller-frame diversion.
- **Anchor age / latency:** `received_by_monado - #sampled` is **median 106.2 ms (p10 90.7, p90
  123.9, max 173.5)**, inside the 119-189 ms anchor-age range of docs/44. Stage medians relative to
  capture: `frames_read` 6.6 ms, `frontend_frames_received` 55.2, `frontend_keypoints_pushed` 97.1,
  `backend_state_pushed` 105.1, `received_by_monado` 106.2. Nearly all the latency (97.1 of 106.2 ms)
  is frontend detection + matching.
- **The clean window is real:** max frame-to-frame jump in `[0, 360] s` is **0.1729 m at
  t+104.5 s**. A separate known runaway later in the file (t+1830 s, 14.7 m jump in a stretch of
  erratic values) is the reset-storm pattern and is excluded from everything below.

**Per-sample rate-vs-position correlation (does NOT show the 20x claim)** — median
`position_velocity / rate` in matched angular-rate bands (90 Hz delivered stream, single-eye
de-interleaved, runaway excluded; the 30 Hz raw stream shows the same):

| band (deg/s) | yaw median(vel/rate) | pitch+roll median(vel/rate) | ratio yaw/pr |
|---|---|---|---|
| 5-10 | 0.0211 | 0.0179 | 1.18 |
| 10-20 | 0.0087 | 0.0123 | 0.71 |
| 20-40 | 0.0057 | 0.0077 | 0.74 |
| 40-80 | 0.0042 | 0.0057 | 0.75 |
| 80-160 | 0.0036 | 0.0059 | 0.64 |

At matched instantaneous angular rate, pitch/roll shows equal or slightly more position velocity
than yaw. This rules out a smooth "translation proportional to yaw rate" law.

**Event-based net displacement** (sustained fast >60°/s single-axis bursts; position 300 ms before vs
500-900 ms after): yaw-dominant n = 58, median 0.171 m over 19.4° (0.0056 m/deg); pitch/roll-dominant n =
14, median 0.166 m over 8.2° (0.0225 m/deg; small sample, at least one glitch). **The real asymmetry is
exposure, not per-degree severity**: the largest yaw bursts (0.25-0.40 m over 8-70°, e.g. 0.34 m in 89 ms)
are the single snaps a wearer remembers.

**Periodic re-anchor:** an FFT of position magnitude in a still 300 s window found no discrete
peak, only broad 0.02-0.05 Hz random-walk content — no periodic discontinuity in the position
channel itself.

## 3. Code-level mechanism candidates, ranked by how directly they explain the asymmetry

### H1 — IMU-camera time offset: structurally uncorrectable, both layers, confirmed by reading the code

Monado's `struct t_slam_camera_calibration` (`monado/src/xrt/auxiliary/tracking/t_tracking.h:625-630`)
carries only `T_imu_cam` and `frequency` — **no time-offset field exists**.
`wmr_hmd_fill_slam_cams_calibration()` (`wmr_hmd.c:1832-1874`) never estimates or applies one.
Basalt's own calibration has `cam_time_offset_ns`, but its use in the live VIO backend is dead code:
```cpp
// sqrt_keypoint_vio.cpp:260-261, right after backend_keypoints_received
// Correct camera time offset
// curr_frame->t_ns += calib.cam_time_offset_ns;
```
(Also, `cam_time_offset_ns` has no slot in `vit_camera_calibration_t`, the struct that actually
crosses the Monado/Basalt boundary, so populating it would do nothing.) A fixed timestamp
misalignment produces an apparent translation proportional to angular *velocity* — worst on
whichever axis moves fastest and most often, which in seated Aircar play is yaw. **Confirmed
offline below** (§"H1 CONFIRMED offline").

### H2 — Position prediction is a live double integration of raw accelerometer, confirmed by reading the code

Monado does **not** hold position at the last SLAM pose. With the default `SLAM_PRED_DEAD_RECKONING`
(`t_tracker_slam.cpp:89`), every pose query re-integrates fresh IMU samples on top of the last SLAM pose
(`t_apply_dead_reckoning()`, `t_dead_reckoning.c:26-142`; the core step at `:115-126` is
`lin_vel += (world_accel + gravity_correction)*dt; pos += lin_vel*dt + world_accel*dt²/2`). Orientation is
gyro-integrated (smooth and, per H4, self-correcting on roll/pitch). Position is a **double integration of
raw accelerometer** over the anchor-age window (90-190 ms): any transient accelerometer error, extrinsic
rotation error misprojecting gravity, or real lever-arm acceleration is integrated twice, so its effect grows
with the square of how long dead reckoning carries it.

### H3 — Optical-flow feature loss under fast yaw (candidate; REFUTED later)

`basalt-g2-config.json` differs from Basalt's `default_config.json` in 3 keys (denser detection:
`optical_flow_detection_grid_size` 50→30, `min_threshold` 5→3, `num_points_cell` 1→3). A fast yaw
sweeps every feature across the image; if displacement exceeds what 3 pyramid levels recover, tracks
are lost. **Later measured: the frontend never loses features under yaw** (keypoints hold at 2600+);
it is the backend's *landmarks* that vanish (§"Landmark collapse"). `optical_flow_levels` 4 is off
the table, and so is levels 2 (it diverges, see the variant table).

### H4 — Yaw has no gravity anchor; roll/pitch do (structural, ties H1-H3 together)

`gravity_correction` (`t_dead_reckoning.c:29`, from the tilt-alignment fusion in `m_imu_3dof.c`)
continuously pulls roll/pitch error back toward vertical. Yaw has no equivalent (no magnetometer,
no loop closure): only the vision-based bundle adjustment constrains heading, and its constraint
on translation *and* heading weakens under near-pure rotation (a seated fast yaw is much closer to
pure rotation than a nod, whose lever arm is larger). Whatever triggers a hiccup (H1 timing, H2
double-integrated noise, H3 track loss) is silently corrected on roll/pitch but rides uncorrected on
yaw until the next successful bundle adjustment.

## 4. Experiment plan, ranked by (expected impact × cheapness), with what became of each

| # | Experiment | Knob / file | Outcome |
|---|---|---|---|
| 1 | **Controlled per-axis capture**: ~15 deliberate fast (80-150°/s) bursts each of pure yaw, pitch, roll, seated, `SLAM_WRITE_CSVS=1`. Pass: yaw disp/degree ≥3x pitch/roll confirms a per-degree asymmetry. | wear protocol only; analysis modelled on `scripts/head-jitter.py` | Done as `scripts/yaw-protocol-voice.py` (spoken script: 30 s still, 10 yaw, 10 pitch, 10 roll, 60 s free) + EuRoC recording + offline replay; yaw is the worst axis (below). |
| 2 | **Prediction A/B**: `SLAM_PREDICTION_TYPE=2` (GYRO, orientation from gyro, position not accel-integrated) vs default 4 (dead reckoning). | env var, `t_tracker_slam.cpp:89` | GYRO + frozen position removed the original ~50 cm/turn overshoot (patch 0097; §recipe). |
| 3 | **Feature-loss check (H3)** with `VIT_COLLAPSE_LOG=1` keypoint counts vs yaw bursts. | env var | Keypoints hold; landmarks collapse (§Landmark collapse). H3 refuted as stated. |
| 4 | **IMU-camera timing residual (H1)**. | `wmr_source.c` instrumentation | Done offline instead, by shifting camera stamps in the recording: monotonic, huge effect (§H1 CONFIRMED). |
| 5 | **Perceptual/vection decoupling** (is the "20x" partly perceptual amplification?). | wearer only | Not separated; the measured drift was real metres, so the question became moot. |
| 6 | Loosen optical-flow headroom (`levels` 3→4 or `max_recovered_dist2` 0.04→0.08). | `basalt-g2-config.json` | `max_recovered_dist2` 0.08 shipped (zero CPU cost, global); `levels` changes refuted. |

## 5. What the first analysis could not determine

- Whether a per-degree asymmetry exists: answered by the controlled recording (yaw is the one rotation
  with a metre-scale error offline: 2.6 m vs 0.36 pitch, 0.61 roll, base config).
- The "periodic redraw": candidates were the ~30 Hz correction-over-dead-reckoning snap, the 90→124 ms
  latency spread, or Basalt's keyframe cadence. `SLAM_CORRECTION_SPREAD_MS` addressed the visible snap.
- Whether felt severity tracks the numbers: only a wearer can say; every conclusion below was confirmed by
  a worn A/B before it became a profile default.

## 2026-08-26 — Localized: orientation/position TIMESTAMP MISMATCH, not a hidden accumulator

Three traces (`SLAM_PREDICTION_TYPE=0/2/2+FREEZE`): `tracking.csv` (`raw_pose`, `t_tracker_slam.cpp:1330`) is
untouched by the one-euro filter that runs on the anchor before `predict_pose()`. `do_position()`
(`m_predict.c:73-103`) under FREEZE returns the filtered anchor exactly, as NONE does. What differs:
`do_orientation()` (`m_predict.c:16-71`) runs for GYRO(+FREEZE) but never NONE, forward-integrating
orientation to the query's `when_ns`, while NONE leaves the 90-190 ms-stale anchor orientation untouched.

**Mechanism**: pred_type ≥ GYRO pairs a REAL-TIME orientation with a STALE (anchor-age) position. NONE never
splits the two (the scene lags uniformly and never detaches from where you look), which is why NONE feels
rock-solid although its raw SLAM noise is the same order (median per-burst residual 8.8/9.0/15.2 cm for
NONE/GYRO/FREEZE). FREEZE removes only the `linear_velocity*dt` overshoot; the split survives. The fix is
a kinematic compensation (the neck arm below), not a static freeze.

## 2026-08-26 — RESOLVED to "super similar to Windows": the seated-6dof recipe

A live wearer A/B sweep on Aircar (seated, gamepad, constellation off), env-only after one code change
(patch 0097), took the feel from "2-4 m accumulating yaw drift" to "solid... very similar to Windows,
smooth, no bad redraws". This meets the project's cutoff (`docs/04`: "headset on par with Windows or
better"). Profile (`scripts/vr-launcher.py`, `TITLE_PROFILES["1073390"]`; inert in 3dof since SLAM is
not running):
```
SLAM_PREDICTION_TYPE=2  SLAM_PRED_FREEZE_POSITION=1  SLAM_PRED_NECK_ARM_MM=150  SLAM_CORRECTION_SPREAD_MS=50
```
(later refined to neck arm 100 and spread 25, see below).

- `SLAM_PREDICTION_TYPE=2` (GYRO): predicts orientation from the gyro, so head turns are responsive
  (no NONE-style lag). Patch 0097.
- `SLAM_PRED_FREEZE_POSITION=1`: holds position at the last SLAM anchor instead of extrapolating
  `linear_velocity` across the ~150 ms latency; kills the ~50 cm/turn overshoot that accumulated to
  metres. Patch 0097.
- `SLAM_PRED_NECK_ARM_MM`: swings the frozen eye along the neck-pivot arc as orientation predicts
  forward (position = anchor + (R_pred - R_anchor)·arm), fixing the orientation/position timestamp
  split. Swept live at 80/150/200 mm: 80 helped, 150 best at the time, 200 over-corrected. **Later
  re-swept with the J-class backend: 0 ≈ 100 < 150 < 200 (less drift is better; 0 showed near-field
  cockpit jitter), so the profile moved to 100.** The vector convention was wrong until patch 0115
  (see the correction below): the A/B was run with an inverted sign, so it needs a re-run.
- `SLAM_CORRECTION_SPREAD_MS` (existing Monado option, was 0): spreads each per-anchor position
  correction over N ms so the periodic re-anchor stops snapping — the remaining nausea source. 100 ms
  smoothed it but added convergence lag and a perceived "fill-in layer"; 50 ms was the balance; **25 ms
  later won** (variant F: smooth without extra delay).

**Residual after the recipe**: on FAST motion, ~1 m bounded drift and a visible delay before
position starts updating. Genuine head *translation* can only be predicted with the accelerometer,
which is exactly what reintroduces the drift, so this is the floor of the prediction approach; the
next steps attacked the VIO itself.

### Further prediction levers (one-line verdicts)

- **Patch 0098** (`WMR_FORWARD_ANGULAR_VELOCITY`): no effect (it feeds only SteamVR's late extrapolation,
  downstream of this residual). Removed.
- **`SLAM_THREADS=6`** (Aircar profile): with constellation off the *tracking* sub-stage, which is
  `tbb::parallel_for`'d, costs 23.2 of 41.9 ms of frontend time (detection is sequential, 12.2 ms), so
  threads help here though they did not with constellation on. Worn: slightly more agile.
- **`optical_flow_max_recovered_dist2` 0.04→0.08**: acceptance threshold only, zero CPU; lives in the shared
  `scripts/basalt-g2-config.json`.
- **Patch 0100 `SLAM_PRED_POSITION_HORIZON_MS`** (extrapolate the SLAM velocity for N ms instead of 0
  under freeze): first test regressed hard (metres out of the cockpit) because ~0.2 % of raw anchors are
  re-localization jumps (anchor-to-anchor speed p99 1.66 m/s, p99.9 81 m/s, max 127 m/s: 6.4 m in one frame
  at 50 ms). Fixed with `SLAM_PRED_POSITION_MAX_SPEED_CM_S` (default 150, magnitude clamp). Full FREEZE had
  been immune by accident.
- Worn A/B of horizon/clamp/spread (C control 0 ms; A 50 ms + clamp 1.5 m/s; B 25 ms; D clamp 1.0; E spread
  25 without horizon): A beats C on latency (promoted), B and D ≈ A (neither clamp nor horizon length sets
  the drift), E smoother but slower; **F = A + spread 25 became the default**. Drift *direction* changes
  between sessions (left, right, back), ruling out a fixed lever-arm error. **Raw `tracking.csv` of every
  variant shows 3 m excursions and 90-150 m/s spikes**: no prediction knob could touch the metres; the drift
  is in the raw VIO.
- **Horizon 100 ms is worse** (extrapolating a noisy velocity twice as far doubles its error). **The horizon
  is not the lever; the pose age is.**

> **Correction 2026-10-12 (code review, docs/147, M14-1): an earlier ruling-out of a frame bug in
> 0097's neck-arm vector was wrong.** The Basalt→WMR axis correction negates y and z, which is a
> conjugation, so it changes the body frame too, not only the summed position. The OpenXR arm
> must be `(0, -0.6, 0.8)` in Basalt's raw frame. With the old vector the compensation came out
> exactly negated (ratio -1.000 on random rotation pairs). Fixed in patch 0115. The 0/100/150/200
> wearer A/B was run with the inverted sign; re-run it.

## Landmark collapse: Basalt's landmarks vanish under yaw (the real mechanism)

Variant B's `VIT_COLLAPSE_LOG=1` stream (17,372 frames) paired to `tracking.csv` by exact frame
timestamp (16,616 matched), binned by instantaneous yaw rate from consecutive quaternions:

| yaw rate °/s | n | frontend keypoints p50 / p10 | **backend landmarks p50 / p10** |
|---|---|---|---|
| 0–30 | 14,387 | 2944 / 2735 | 52 / 23 |
| 30–90 | 1,376 | 2817 / 2686 | 42 / 10 |
| 90–180 | 372 | 2713 / 2586 | **15 / 1** |
| 180–360 | 410 | 2652 / 2566 | **6 / 0** |
| >360 | 71 | 2614 / 2521 | **5 / 0** |

Control axis (pitch/roll rate, yaw < 30 °/s): 90–180 °/s keeps landmarks **37 / 9**, 180–360 keeps
**27 / 10**. Excluding the 3 s after each divergence reset changes nothing, so the collapse is real,
not a reset artifact. So the frontend never loses features (H3 refuted); the backend landmark set
(`lmdb.numLandmarks()`, `sqrt_keypoint_vio.cpp:1676`) collapses to zero specifically under yaw, and
with zero landmarks the VIO has no visual constraint on translation: position becomes pure IMU
double integration, which is the metres. Source-verified causes (Basalt tree):

1. `vio_marg_lost_landmarks: true` (our base config) marks every landmark not observed *this frame*
   as lost (`sqrt_keypoint_vio.cpp:563-572`) and deletes it at the next marginalization (`:1122-1123`,
   nearly every frame). A landmark swept out of view is gone before the head comes back. Basalt's
   **landmark recall** (`optical_flow_recall_enable`, off in base; `frame_to_frame_optical_flow.h:560-655`)
   can only re-find landmarks still in `lmdb`, so it is useless for sweep-and-return unless marg-lost is
   off (Basalt's own TODO at `sqrt_keypoint_vio.cpp:776-783` names this tension).
2. `vio_min_triangulation_dist: 0.05` is a metric baseline gate (`:532-536`). A seated yaw has ~0
   baseline, so the keyframes taken during a sweep add **no** new landmarks, and keyframe
   marginalization deletes their hosted landmarks unconditionally (`landmark_database.cpp:66-87`).
3. Yaw vs pitch/roll: a level yaw sweeps the whole scene out horizontally; pitch keeps floor/ceiling
   structure partially in view. Plus H4: whatever error accrues rides uncorrected.

Also low even at rest: p50 = 52 landmarks for ~2900 tracked keypoints. Backend cost is nowhere near
its limit (`opt_ms` p99 6.9 ms, `marg_ms` p99 1.5 ms per 33 ms frame).

**At rest, the metre jumps are a different failure.** In a 20-minute stationary soak of the base
config, the 3 m jumps are not starvation but *churn on a frozen keyframe set*: landmark counts
flap by ~100 per frame for ~2 s before a jump, and after the first minute no keyframe is ever taken
again (a static view never drops the connected ratio below `vio_new_kf_keypoints_thresh` 0.7), so the
IMU bias drifts until preintegration and vision disagree. Yaw genuinely runs out of landmarks; rest
has plenty and lets the IMU side drift (an IMU-bias reading of the at-rest walk stays a hypothesis).

## Offline A/B pipeline (no headset)

`patches/basalt/0013` (`VIT_DUMP_CALIB`) exports the live calibration (4 × `pinhole-radtan8` 640×480, IMU
250 Hz, `cam_time_offset_ns=0`); `basalt_vio` (`~/vr/basalt/build-tools`) replays an `EUROC_RECORD=1`
session; `scripts/replay-basalt-variants.py` runs N configs against one recording;
`scripts/replay-phase-slice.py` cuts trajectories by the protocol phases (`scripts/euroc-phases.py` makes
`phases.json` from the voice log; `scripts/euroc-shift.py` shifts camera stamps); `scripts/soak-variant.py`,
`soak-grade.py`, `soak-families.py`, `soak-sequence.sh` run and grade unattended stationary soaks.

- `EUROC_RECORD_PATH` is a prefix (a timestamp is appended). Record the yaw dataset as PNG (~14 GB per
  10 min of tmpfs; **stop the session right after the protocol, the recorder runs until Monado dies**).
- `vit_collapse IN … t_ns` does not exist offline; the harness keys frames by index.
- Replay is non-deterministic (6 threads): replay `base` twice and require a variant to beat the base by
  more than the base beats itself (noise floor ~0.1 m on Σ). Offline frontend ms match live (base 28.2 vs
  28 worn; J 44.9 vs 45.8). ~135 s per replay of a 3-minute recording.

## The Basalt variant sweep: config diffs that mattered

All variants are `scripts/basalt-variants/<X>.json` (+ `.toml` wrappers). **Only P2 remains in the
repo** (`scripts/basalt-variants/P2.json` and `P2.toml`; the others were removed after the sweep —
this table is the record). The shipped global config is `scripts/basalt-g2-config.json` ("base").
"Keys vs P2" is the literal JSON diff against P2.

**P2** = recall on (`optical_flow_recall_enable`, default norms `[1.74, 0.96, 0.99, 0.44]`),
`vio_marg_lost_landmarks: false`, `vio_min_triangulation_dist` 0.02, `vio_max_kfs` 12,
`optical_flow_detection_grid_size` 40; everything else as base (levels 3, `num_points_cell` 3,
`max_threshold` 40, `vio_new_kf_keypoints_thresh` 0.7, `vio_min_frames_after_kf` 5). So **base differs
from P2 in 6 keys**: grid 30, recall off, strict recall norms `[0.435, 0.24, 0.24, 0.11]`, marg-lost
on, kfs 7, triangulation 0.05.

Two measurement regimes: *offline yaw* = Σ of yaw+pitch+roll max-distance-from-phase-start on the
wearer's recording (m; base 3.59, noise floor 0.1); *at rest* = 20-min stationary soaks (anchor trips,
landmarks p50). At-rest numbers are confounded by placement and light (see below).

| Variant | Keys vs P2 | Outcome |
|---|---|---|
| base | grid 30, no recall, strict norms, marg-lost on, kfs 7, tri 0.05 | Reference. Yaw drift 2.62 m (Σ 3.59); landmarks 5/0 above 360 °/s; frontend p50 28 ms. |
| G | grid 30, strict norms, kfs 7, tri 0.05 (= recall + marg-lost off only) | 6× landmarks but leaked 18 GB at 2 min before patch 0014 (recall patch map never pruned). With 0014 (G′): 64/37 landmarks yet 30 trips at rest. UNSAFE. |
| G2 | grid 30, strict norms, marg-lost on, kfs 7, tri 0.05 (= recall only) | = base on every drift metric, plus recall CPU. Recall alone does nothing. |
| G3 | grid 30, no recall, strict norms, kfs 7, tri 0.05 (= marg-lost off only) | 89/49 landmarks (5× base) for +3 ms; at rest = base (7 trips); offline yaw 1.63 m but a 22 cm leak into the still phase after. Most of the landmark gain is just not deleting them. |
| H | grid 30, no recall, marg-lost on, strict norms (= tri 0.02 + 12 kfs only) | Refuted at rest: 46 trips (base 7), span 7.5 m. The 2 cm gate without recall triangulates garbage landmarks. Offline yaw 1.75 m. |
| K | grid 30, strict norms, tri 0.05 (= recall + marg-lost off + 12 kfs) | At rest 1 trip, span 3 m; offline yaw 1.65 m, Σ 2.12. Halves the yaw drift, landmark collapse gone (671/565 above 360 °/s). |
| M | grid 30, no recall, strict norms (= I without recall) | Unstable at rest (21 trips); offline Σ 1.99. Recall is load-bearing: it re-attaches the **same** landmark IDs after a sweep. |
| I | grid 30, strict norms | Offline yaw 0.96 m (Σ 1.34). At rest: one 20-min run with 0 trips and 0.41 m span did **not replicate** (I2 on a faster build: 4 trips, 4.5 m). |
| **J** | grid 30 | **Offline winner**: yaw drift 2.62→0.28 m, net 5 cm after ten 400-600 °/s yaws, Σ 0.63. Default recall norms matter: base's 4× stricter norms rejected most valid recalls. Cost: frontend p50 45 ms vs 28 (budget 33). |
| L | grid 30, no recall, strict norms, marg-lost on, kfs 7, tri 0.05, kf threshold 0.9 | Worst at rest (96 trips, reset storm); the 0.9 threshold never engaged at rest. Refuted. |
| N1 | grid 30, tri 0.01 | Σ 0.67, wall +33 %. No gain over J. |
| N2 | grid 30, kfs 16 | Σ 0.63, wall +33 %. No gain. |
| N3 | grid 30, kf threshold 0.9 | Σ 0.73. Worse. |
| N4 | grid 30, `vio_min_frames_after_kf` 2 | Σ 0.65. No gain. |
| N5 | grid 30, `optical_flow_recall_all_cams` true | Σ 0.66; recall p99 7.9 ms vs 2.8. No gain. J is the config plateau. |
| P1 | grid 30, `num_points_cell` 2 | Frontend 34.0 ms, Σ 0.74. |
| **P2** | (reference) | **Frontend 26.6 ms p50 (J's drift at base's cost)**, Σ 0.78 (yaw 0.43), 120 k patches. Cell count was the dominant cost term, not per-point work. Shipped per-title for Aircar. |
| P3 | `num_points_cell` 2 | Frontend 20.1 ms but Σ 1.07 (yaw 0.68): cheaper than needed, starts paying in drift. |
| P4 | grid 30, `max_threshold` 60 | Σ 0.58 for 50.8 ms. A little drift for a lot of ms. |
| P5 | grid 30, levels 2 | **Diverges to kilometres** (saves 1 ms). The coarsest pyramid level is what follows 400-600 °/s between frames 33 ms apart. Do not retry. |
| P6 | levels 2 | Same divergence (Σ 4.37 m). |
| P7 | grid 30, `num_points_cell` 2, levels 2 | Σ 6.07 m. |
| P8 | `max_threshold` 60 | 31.5 ms, Σ 0.81: buys nothing. |

Yaw-phase max-far (m, offline): base 2.62, G3 1.63, H 1.75, K 1.65, M 1.21, I 0.96, **J 0.28** (net
0.05); settle phases stay ≤ 4 cm (G3's 22 cm excepted). Each lever is separable: marg-lost off (G3) and
gate + 12 kfs (H) each help yaw; their union with recall (K, I) more; recall's value is landmark-ID
re-attachment, not count; the last step (J) is only the recall acceptance norms.

### Recall memory and CPU (patches 0014-0019)

- **Leak:** recall saves a pyramid patch per new keypoint and nothing erased them. **0014** `prunePatches()`
  keeps patches whose id is tracked or in the latest bundle and erases the rest after a 90-frame grace (leak
  cut >95 %, map bounded at ~200-400 k). A 30-frame grace is not a free knob (I3: 50 trips; a landmark that
  left view needs about a second to come back or it is re-detected as new).
- **CPU:** the cost is building 4 pyramid patches for each of ~2,000 detections per frame. **0015**
  parallelizes it (p50 42→38 ms); the p99 was a 1-in-30 spike from 0014's whole-map sweep, amortized by
  **0016** (1/29th per frame) and **0018** (second map); **0019** adds per-stage timing to the `vit_of` line.
  P2 stage split p50/p99 ms: pyramid 0.8/4.0, **tracking 10.4/18.5**, **detection + matching + patches
  12.7/20.6**, filter 0.1/0.2, prune 0.4/11.4.
- RSS: read the slope over minutes 10→20 (the recall cache fills in the first 2-3 min). Residual growth
  (+232 MB/h) is marg-lost off keeping landmarks alive: fine for a demo, not an all-day run.

### At-rest soaks: placement and light dominate; interleave or don't compare

Frontend keypoints per frame (a proxy for how much texture the resting cameras see) and trips move by
±15 % and 5× between runs of the *same config* at different hours (base 7 trips at 11:46, base2 36 at
16:40; the best I run coincided with the best-textured 20 minutes of the day). Any at-rest ranking
across hours is untrustworthy; the honest protocol is back-to-back interleaving (base → candidate →
base → candidate; `scripts/soak-sequence.sh`, detached with `setsid nohup`, one `soak-variant.py` per
leg, forced teardown between legs). Results of the interleaved pairs (15 min each, headset on the desk):

| Pair | condition | base: lm p50 / trips | P2: lm p50 / trips |
|---|---|---|---|
| i2 | dark room | 0 / 142 | 22 / 35 |
| i3 | dark room | 1 / 107 | 24 / 19 |
| i4 | lit, current build | 143 / 44 | 190 / 5 |

P2 trips 4-9× less than base in every pair, keeps landmarks (0.7-3.7 % of frames below 5 vs
7-89 %), and has a cheaper frontend in light (p50 22.8 vs 33.4 ms, because grid 40 cuts detection where
features are plentiful); P2's `det(Q1Jl) == 0` warnings are 17× base's in light. **Darkness is the
dominant factor**: every night run has lm p50 < 5 for base; every daytime run has it in [15, 161].
Rule for 6dof titles: **the room must be lit** (`scripts/light-preflight.sh` grades DARK lm p50 < 5,
DIM 5-15, OK ≥ 15 on the base config; DARK is a hard stop for every profile).

The `d_res_d_p is not valid` and `det(Q1Jl) == 0` solver warnings are same-condition A/B columns
only: they scale with the number of landmarks optimised, P2's recall thrash and frontend starvation
(CPU contention drove them 1,252→9,697 in 3 minutes while heavy analysis ran next to a wearer), not
with runaway magnitude. `scripts/worn-grade.py` reports them with that caveat.

## H1 CONFIRMED offline: the camera stamps are late vs the IMU by ≥ 5–10 ms, and it is the biggest lever of all

The wearer's yaw recording (6,852 frames per camera, 56,709 IMU rows; the IMU confirms the script was
followed: yaw ×10 gyro p90 377 °/s, max 600; settle phases ≤ 3 °/s, ≤ 0.2 m/s², so any drift there is
the tracker) was replayed with config I and the camera stamps shifted, IMU untouched (the shift is
exactly what the dead `sqrt_keypoint_vio.cpp:261` line would do, same sign). Per phase:

| I with cam stamps shifted | **yaw** max1s/net/maxfar | pitch | roll | Σ rot | worst settle | span |
|---|---|---|---|---|---|---|
| **−10 ms** | 0.29/0.10/**0.24** | 0.27/0.04/0.21 | 0.09/0.04/0.10 | **0.55** | 0.009 | 0.93 |
| −5 ms | 0.29/0.10/0.30 | 0.27/0.04/0.21 | 0.08/0.10/0.15 | 0.66 | 0.010 | 0.94 |
| 0 (I) | 0.39/0.69/0.96 | 0.27/0.10/0.20 | 0.09/0.12/0.19 | 1.34 | 0.008 | 1.58 |
| +5 ms | 0.73/1.63/1.72 | 0.30/0.27/0.27 | 0.14/0.32/0.52 | 2.50 | 0.051 | 2.15 |
| +10 ms | 2.64/4.08/**4.21** | 0.34/0.55/0.55 | 0.25/1.09/1.26 | 6.01 | 0.085 | 5.40 |

Monotonic in both directions: a 20 ms difference in one number moves the yaw drift from 0.24 m to
4.2 m, with pitch and roll far less sensitive — exactly the H4 asymmetry. The frame timestamps Monado
hands to Basalt are **later than the exposure by at least 5-10 ms**. Pinned on J (Σ rot max-far / yaw
max-far): J 0.63 / 0.28; −5 ms 0.53 / 0.21; −10 ms 0.53 / 0.22; −15 ms 0.70 / 0.39; −20 ms 1.86 / 1.53;
−30 ms 5.09 / 4.54 — a flat plateau at −5…−10 and a cliff either side; settles ≤ 1.1 cm.

**Where it comes from** (`wmr_camera.c:396-434`): the frame footer carries `start_ts`/`end_ts` (100 ns
ticks, IMU clock) and `end_ts − start_ts` is always ~11.1 ms, the 90 Hz slot period, not the exposure.
The driver stamped frames at `start + 5.55 ms`. The real exposure (pixel header, µs; auto-exposure 60 to
9000) puts mid-exposure at start + 0.03-4.5 ms, so the stamp is late by 1-5.5 ms from that alone; the
rest suggests `start_ts` itself lags the exposure start. The hardware→monotonic offset
(`wmr_source.c:204-278`, `hw2mono`) is learned from IMU arrivals and applied identically to every
frame, so it contributes no *relative* offset.

**Levers**: **patch 0017** `VIT_CAM_TIME_OFFSET_NS` (applied at `vit_tracker.cpp`'s
`partial_frame->t_ns = s->timestamp`, the one place a frame stamp enters Basalt; negative = earlier,
same sign as the offline shift) is the A/B instrument. **Patch 0101** `WMR_CAM_TS_MID_EXPOSURE=1`
stamps SLAM frames at `start + exposure/2`, following auto-exposure frame by frame; it is the
permanent fix and is in Aircar's profile. Worn, a fixed −7 ms on top of J (JT) was not distinguishable
from J, and **a further negative shift on top of 0101 overshoots**: replaying a second recording that
already carries 0101 gave −10 ms → yaw error 3× worse and −5 ms → unstable (divergence in one run,
reproducible in outcome though not in onset), so the J sweep's optimum has been banked by 0101 and no
extra offset is justified.

## Pose age, queues, and the worn A/B round that made Aircar's profile

**Pose age had never been measured.** Patch **0102** (`SLAM_POSE_AGE_LOG=N`) logs `when_ns − rel_ts` per
tracked-pose query. Idle: p50 68-71 ms, p90 88-96. **With Aircar running: p50 115 ms, p90 151, max 359**,
varying with CPU load. Patch 0020's `age_in_ms`/`age_out_ms`: exposure → tracker input **p50 11.4 / p90 11.9
ms** (transport is small and constant); exposure → pose out of Basalt p50 59 / p90 170 / p99 265 ms with a
~30 ms frontend. The extra is **queueing**: the image and vision queues (capacity 2, drop-oldest) let the
pipeline run up to 4 frames deep after one slow backend frame. **Basalt patch 0021 `VIT_QUEUE_DEPTH=1`**
halves the tail (Basalt in→out p90 103 vs 170-188 ms; display-side age p50 75 / p90 93 ms; 2.1 % frames
dropped, free at 30 Hz with the IMU between). **0103** `SLAM_CORRECTION_AVG_N` feeds the correction
accumulator the mean of the last N deltas (with a still head each delta is mm-level VIO noise that a 25 ms
decay never settles before the next one). `filter_pose` is inert in every deployed profile.

Worn A/B round on Aircar 6dof (same fast-turn protocol; the config stack built up cumulatively):

| Variant | Change | Worn outcome |
|---|---|---|
| J | backend J | Metres → "several cm" of drift; same delay on fast motion, jitter + latency on slow motion; 0 trips. Frontend p50 46 ms is the cost. |
| JT | J + −7 ms stamp | No felt change; not promoted. |
| JP | P2 | Same feel as J with a cheaper frontend (p50 ~30 ms live). |
| JH | P2/J + horizon 100 | **Worse** (more jitter, same escape). |
| JA | P2 + `SLAM_CORRECTION_AVG_N=3` | Jitter manageable. Kept. |
| JM | P2 + 0101 mid-exposure stamp | Hard to leave the ship; kept. |
| JX | P2 + AVG_N 3 + 0101 | Same, no surprises. |
| **JQ** | JX + `VIT_QUEUE_DEPTH=1` | Best of the round: "solid, but not resolved". Session raw max 1.03 m, 0 trips. |

**Aircar profile after the round** (`vr-launcher.py`): `SLAM_CONFIG=P2.toml`,
`SLAM_CORRECTION_AVG_N=3`, `WMR_CAM_TS_MID_EXPOSURE=1`, `VIT_QUEUE_DEPTH=1`, horizon 50 ms, clamp
150 cm/s, spread 25 ms, `SLAM_THREADS=6`, neck arm 100 mm (below). P2 is **not** in the global
`basalt-g2-config.json`; promoting it needs a valid lit-room Dalí 6dof check (below).

**What is left**: the rotation-onset displacement (yaw/pitch first "moves you off the seat", then
settles). Offline the raw VIO under J-class configs does *not* do this, so it is the prediction layer
(neck model over the ~75 ms stale anchor) rather than the timing, and indeed the **neck-arm A/B
(JN0/JN100/JN200 vs 150) gave 0 ≈ 100 < 150 < 200**: less arm, less displacement; 100 chosen over 0 for
near-field cockpit jitter. This was run with the pre-0115 inverted sign; re-run it with 0115.

## Dalí 6dof (raw-position title): what is different and what is not

Only Dalí is a *raw consumer* of Basalt's position (no head-prediction knob, no anchor guard); Aircar and
Cyberpilot sit behind freeze + anchor guard.

- **The first P2 gate was invalid: the room was dark.** Both P2 (161 m, 5 M `d_res` warnings) and base (80 m,
  17 trips) ran away in the dark; base was clean once lit. Lit-room runs then showed **both configs run ~40 m
  away within the first two minutes of a worn Dalí session** (base 38.8 m, P2 38.6 m), then settle: a
  rotation-only start, then a metres-sized step at the first real translation — monocular-VIO scale
  unobservability under pure rotation (the scale snaps when parallax arrives). The at-rest instrument never
  sees it because the headset starts still. **P2 is not promoted** (undecided, not failed); Dalí keeps base.
- **Guards**: `SLAM_SESSION_ANCHOR_RADIUS_CM=300` (patch 0099) restarts Basalt when the output is >3 m from
  the session start, bounding the excursion (3.45 m max instead of 38) with near-free resets (0.02-0.21 m
  carried), but does not move the wearer back and can re-fire every ~2 s while the VIO wanders. The speed
  guard (`SLAM_AUTO_RESET_MAX_SPEED`, default 10 m/s, integer-parsed) fires only after tens of metres of
  smooth ramp and misses slow ramps (P2 reached 120 m at max 5.7 m/s per frame, 0 trips for 220 s); its reset
  can carry 8 m + 13° of yaw. **Do not lower it**: real heads peak at 2-3 m/s and raw SLAM velocity has 0.2 %
  spikes to 127 m/s; the fix is a distance bound. After a trip the reported position snapped back to 0.7-4.4 m
  of the origin, contradicting the carry's "stays continuous" claim (open).
- **Procedure**: headset still on the desk until the title has loaded (Basalt initialises at rest), then
  worn. Base still random-walks to the 3 m radius within 15 s even on the desk.
- **Threads**: the worn base frontend's 40.9 ms vs P2's 24.2 ms was the *tracking* stage (20.4 vs 12.4 ms p50):
  base ran at `SLAM_THREADS=4`, P2's TOML hardcodes 6. Dalí's profile now carries `SLAM_THREADS=6`.
- **Render scale and fps**: Monado's 140 % default renders 3024×3024 per eye; `XRT_COMPOSITOR_SCALE_PERCENTAGE=100`
  renders 2160×2160 and Dalí delivers **~90 fps** (window means 79-90, GPU mean 83 % / ~237 W, dips only when
  the GPU touches its 250 W cap; 0.10 % of frames late, 0.02 % once worn). The cap is therefore needed at 90 fps.
- **Recentre**: xrizer **0008** adds an external recentre trigger file (polled in the compositor) and **0009** an
  opt-in recentre ~2 s after donning on the `XR_EXT_user_presence` PRESENT edge (`WMR_USER_PRESENCE=1` + flag
  file). Validated worn on Dalí and Aircar 6dof (flaps inside 15 s refused). In Aircar **3dof the cockpit does
  not follow**: the served pose resets correctly (head yaw 72-155° → ~0°) but the game re-bases its 3dof
  cockpit itself. One don in eleven was missed by the proximity sensor (change-driven
  `WMR_CONTROL_MSG_IPD_VALUE`); a polling feature read of id 0x01 **does not work** (the device does not answer
  and the read blocks 1.4-5.0 s inside the shared IMU/camera loop; this is why
  `WMR_COMPANION_RECONNECT_RESYNC` is off).
- **Teardown SIGSEGV** (`wmr_cam_usb_thread` → `flush_poses` → `Tracker::pop_pose` while the main thread
  destroys nodes newest-first, stopping the tracker while the camera thread can still push) was one bug, fixed
  by **monado 0104** (`patches/monado/README.md`, row 0104); `scripts/teardown-stress.sh` ran 8 up/down cycles + 3
  Dalí load→teardown cycles with 0 cores. A detached hardware script must export the GUI env (`gui_env.get()`):
  `jack-in-wayland.sh` refuses to launch in a tty session and writes `~/vr/.jack-in-failed`, which blocks later
  launches until cleared.

## Ruled out / do not retry

- `optical_flow_levels` 2 (diverges) and 4 (unneeded); horizon beyond 50 ms or without the speed clamp;
  recall grace 30; the 2 cm gate without recall; keyframe threshold 0.9 at rest; a fixed camera offset on
  top of mid-exposure stamping; lowering the speed guard below 10 m/s; the gyro-mount fix and 0098.

## Open items

- Re-run the neck-arm A/B after the 0115 sign fix (100 mm was tuned with the wrong sign).
- A lit-room ~10 min Dalí 6dof run under P2 at scale 100 (plus a base control) would settle the global
  promotion; the post-trip position snap-back contradicting the carry's continuity claim.
- Why the 3dof cockpit refuses a runtime recentre (the game's own base-orientation logic?).
- Rebuild `build-tools/basalt_vio` alongside `libbasalt.so` so offline replays match the live frontend queue.
