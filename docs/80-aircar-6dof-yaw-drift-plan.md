# 80 — Aircar 6dof: fast-yaw position drift, an experiment plan

Tonight's (2026-08-26) live finding: Aircar 6dof (seated, Xbox pad, constellation OFF), well-lit
room, is "gold, not platinum" — no VIO runaways in the wearer's own 6-minute window (max
frame-to-frame jump 0.17 m, confirmed below), clean 90 fps, but a **fast yaw turn drifts the
wearer out of his seated position roughly 20x more than the same speed of pitch or roll** (his
own estimate), fixed instantly by the pad's recentre button. He also feels a subtle periodic
"redraw" that 3dof does not have. This document is the experiment plan to close both, grounded in
this session's own CSVs and the actual Monado/Basalt code, not generic VIO advice.

**Headline conclusion, stated up front because it cuts against the intuitive reading**: the raw
numbers in tonight's own log do **not** show a clean, continuous "position error scales with yaw
rate" law — if anything pitch/roll shows slightly *more* apparent position velocity per degree/s
than yaw at matched rates. What the data does show is (a) yaw bursts are ~4x more frequent and
much larger in a seated cockpit than pitch/roll bursts, so yaw supplies nearly all of the
few-big-jump events a wearer would ever notice or remember, and (b) two structural facts in the
code — position is double-integrated from raw accelerometer between SLAM updates, and yaw has no
gravity-anchored self-correction the way roll/pitch do — mean that whatever triggers a hiccup
lands worse and stays longer specifically on yaw. Section 2 has the numbers, section 3 the code.

## 1. What prior docs already establish (don't re-litigate)

- **docs/34** §3B: gravity correction (`m_imu_3dof.c`) removes *tilt* drift (roll/pitch) by
  aligning measured gravity to world-up. It says nothing about yaw — yaw has no equivalent
  absolute reference in a monocular/stereo VIO system. This is the standard 4-DoF-unobservable
  property of VIO (3 position + yaw), not a bug in this codebase.
- **docs/39 / docs/44**: the SLAM pose-rate collapse and the camera/IMU clock-domain skew are
  both closed (Basalt `BASALT_IMU_NONBLOCK_CATCHUP` default-on; Monado `0055`'s companion-backoff
  fix). Anchor age today reads a genuine content age, not a lie — confirmed again below.
- **T211/T212** (`docs/pruebas.jsonl`): a real-looking 9%-of-yaw roll/pitch leak from a gyro
  mounting misalignment was fitted (`WMR_HMD_HMD_GYRO_MOUNT_FIX`, `wmr_hmd.c:2068-2143`,
  default off) and then **refuted by held-out data** (T212: leak slope +0.003/+0.001 at R²
  0.01/0.00 on a clean re-run, vs. the original 0.60/0.44). **Do not re-enable this fix or
  re-open this specific mechanism** — it is a documented, resolved negative result for HMD roll
  drift. It is unrelated to tonight's finding anyway: tonight is about *position* drift keyed to
  *rotation rate*, not a fixed-axis rotation leak.
- **docs/67 §3 A-head-3**: with constellation OFF (Aircar's profile), diversion should be ~0%
  and SLAM should get the full ~30 Hz camera stream. **Confirmed below.** Also established there:
  Basalt's frontend is already over-budget at 30 Hz (p50 46 ms against a 33 ms budget) and
  detection/matching is single-threaded — relevant context for why a fast yaw (which stresses
  the frontend's optical-flow search hardest) has less headroom than it looks like it should.
- **docs/67 §7 (T245)**: the *previous* Aircar dim-room run parked the raw pose at 41 m during
  a runaway, and a **separate "resting produces a reset storm"** pattern was documented when the
  wearer set the headset down. Tonight's file has an identical-looking event (below) — it is the
  same known, already-understood phenomenon, not a new yaw-drift data point.
- **docs/59**: side cameras "aim outward/up" (docs/56 §1); SLAM uses cameras that are not purely
  forward-facing. `WMR_MAX_SLAM_CAMS`/`WMR_MAX_CAMERAS=4` (`wmr_config.h:21`,
  `wmr_config.c:461`) means Basalt gets all 4 tracking cameras by default, not just the forward
  stereo pair — the near-parallax-free-motion problem during pure rotation applies to all of them
  equally, since it is about translation, not facing direction.

## 2. What tonight's CSVs actually show

Source: `/mnt/vrtmp/slam-20260826-042947/{tracking,filtering,prediction,timing}.csv`.
`tracking.csv` is Basalt's raw ~30 Hz VIO output; `prediction.csv`/`filtering.csv` are Monado's
delivered stream, queried once per eye per compositor frame (~180 rows/s, ~90 Hz per eye after
de-interleaving) — this second pair is what the wearer actually sees, and is the one that matters
for a "does the position channel jump during fast yaw" question.

**Pose rate / diversion (item 1 in the brief):** `tracking.csv` runs 55366 valid rows over
2294.7 s at a **median 33.16 ms interval = 30.15 Hz** — the full camera rate, confirming ~0%
controller-frame diversion with constellation OFF, exactly as docs/67 A-head-3 predicts.

**Anchor age / latency:** `timing.csv`'s own `received_by_monado - #sampled` end-to-end latency
is **median 106.2 ms (p10 90.7, p90 123.9, max 173.5 ms)** — squarely inside the wearer-observed
119-189 ms anchor-age range from docs/44's instrumentation. Stage breakdown (medians relative to
capture): `frames_read` 6.6 ms, `frontend_frames_received` 55.2 ms, `frontend_keypoints_pushed`
97.1 ms, `backend_state_pushed` 105.1 ms, `received_by_monado` 106.2 ms. Nearly all the latency
(97.1 of 106.2 ms) is frontend detection+matching, matching A-head-3's single-threaded-frontend
finding.

**The wearer's "6-minute, 0.17 m" window is real and locatable**: the maximum frame-to-frame
jump in `[0, 360] s` of this file is **0.1729 m at t+104.5 s**, and it stays the session max
through t+450 s — i.e. this IS the clean window he described.

**A separate, known, unrelated runaway exists later in the same file**: at t+1830-1832 s, jump
hits 14.70 m (443 m/s — a reset/teleport artifact, not physical motion), inside a stretch
(t≈1795-2100 s) of erratic values that looks exactly like docs/67 §7's "resting produces a reset
storm" pattern (the file spans 38 min total; the wearer was not continuously doing the yaw test
the whole time). **Excluded from all analysis below.**

**Per-sample rate-vs-position correlation (does NOT show the 20x claim):** binning both the raw
30 Hz stream and the 90 Hz delivered stream by `|yaw rate|` and by `|pitch/roll rate|`
(`sqrt(pitch²+roll²)`, body-frame, from consecutive-quaternion angle-axis / dt) and comparing
median `position_velocity / rate` in matched bands:

| band (deg/s) | yaw median(vel/rate) | pitch+roll median(vel/rate) | ratio yaw/pr |
|---|---|---|---|
| 5-10 | 0.0211 | 0.0179 | 1.18 |
| 10-20 | 0.0087 | 0.0123 | 0.71 |
| 20-40 | 0.0057 | 0.0077 | 0.74 |
| 40-80 | 0.0042 | 0.0057 | 0.75 |
| 80-160 | 0.0036 | 0.0059 | 0.64 |

(90 Hz delivered stream, `prediction.csv`, single-eye de-interleaved, dt-filtered ≥3 ms, runaway
window excluded.) At matched instantaneous angular rate, pitch/roll shows *equal or slightly
more* position velocity than yaw, not 20x less. The 30 Hz raw-SLAM stream shows the same pattern.
**This rules out a smooth, continuous "translation ∝ yaw rate" law at this session's motion
amplitudes** — whatever is happening is not a constant per-degree scale factor that is bigger for
yaw.

**Event-based net displacement (closer to what "drifted out of my seat" means):** isolating
sustained (≥33 ms) fast (smoothed rate >60°/s, dominant axis ≥3x the other) single-axis bursts
and comparing position 300 ms before the burst to position 500-900 ms after it ends:

| | n events | median displacement | median angle traveled | median disp/degree |
|---|---|---|---|---|
| yaw-dominant | 58 | 0.171 m | 19.4° | 0.0056 m/deg |
| pitch/roll-dominant | 14 | 0.166 m | 8.2° | 0.0225 m/deg |

Median-for-median, pitch/roll again looks *worse* per degree traveled, not better — but this
comparison is weak evidence either way: the pitch/roll sample is small (14 events in 38 minutes
of seated cockpit play — people barely nod or tilt fast when seated) and at least one of those
14 (t+105.12 s: 2.1° in 22 ms, 0.43 m) looks like a glitch, not a real head movement, which
inflates that group's ratio. **The real asymmetry in this data is exposure, not per-degree
severity**: 58 qualifying fast-yaw bursts vs. 14 fast-pitch/roll bursts in the same session, and
the largest individual yaw bursts (0.25-0.40 m over 8-70°, several under 200-600 ms — e.g.
t+160.91 s: 0.40 m/51.4°, t+267.57 s: 0.34 m in just 89 ms) are exactly the kind of single
noticeable snap a wearer would remember and attribute to "yaw is worse," even though the
per-degree statistics don't clearly support a 20x multiplier. **A wearer who yaws constantly and
nods/tilts rarely will accumulate essentially all of his bad-jump memories on the yaw axis even
if the underlying mechanism is axis-agnostic.**

**Periodic re-anchor:** an FFT of position magnitude in a still 300-second window (300-600 s,
head essentially motionless) found no discrete spectral peak — only broad low-frequency (0.02-
0.05 Hz, i.e. 20-45 s) content typical of ordinary random-walk drift, not a resonant "redraw"
period. **Could not find a periodic discontinuity in the position channel itself** — see §5.

## 3. Code-level mechanism candidates, ranked by how directly they explain the asymmetry

### H1 — IMU-camera time offset: structurally uncorrectable, both layers, confirmed by reading the code

Monado's calibration struct handed to Basalt, `struct t_slam_camera_calibration`
(`monado/src/xrt/auxiliary/tracking/t_tracking.h:625-630`), carries only `T_imu_cam` (extrinsic
transform) and `frequency` — **no time-offset field exists at all.**
`wmr_hmd_fill_slam_cams_calibration()` (`wmr_hmd.c:1832-1874`) never estimates or applies one.

Basalt's own calibration format *does* have `cam_time_offset_ns`, and it is even referenced in
the live VIO backend's frame-ingestion loop — but that line is **dead code**:
```cpp
// sqrt_keypoint_vio.cpp:260-261, right after backend_keypoints_received
// Correct camera time offset
// curr_frame->t_ns += calib.cam_time_offset_ns;
```
So even if Monado *did* populate this field (it doesn't), the live estimator would not apply it.
**A residual camera-IMU time offset on this hardware is, right now, completely uncorrected by
either layer.** This is the textbook VIO time-sync error signature: a fixed timestamp
misalignment produces an apparent translation proportional to angular *velocity* (rotate the
wrong accel sample into the wrong orientation at the wrong instant, worst when the orientation is
changing fastest) — i.e. it would show up worst on whichever axis moves fastest and most often,
which in seated Aircar play is yaw. This is consistent with the exposure asymmetry in §2 even
though it wouldn't necessarily produce a clean continuous per-degree law (a fixed offset applied
during a fast, brief, high-angular-acceleration sweep can look "discrete" rather than smooth).

### H2 — Position prediction is a live double integration of raw accelerometer, confirmed by reading the code

Answering the brief's own question directly: **Monado does NOT hold position at the last SLAM
pose.** With the default `SLAM_PREDICTION_TYPE=SLAM_PRED_DEAD_RECKONING`
(`t_tracker_slam.cpp:89`), every pose query re-integrates fresh IMU samples on top of the last
SLAM pose (`t_apply_dead_reckoning()`, `t_dead_reckoning.c:26-142`):

```c
// t_dead_reckoning.c:115-126
struct xrt_vec3 world_accel = ...;
world_accel = m_vec3_add(world_accel, *gravity_correction);
*lin_vel = m_vec3_add(*lin_vel, m_vec3_mul_scalar(world_accel, dt));
const struct xrt_vec3 accumulated_position_change = m_vec3_add(
    m_vec3_mul_scalar(*lin_vel, dt),
    m_vec3_mul_scalar(world_accel, dt * dt * 0.5f));
math_vec3_accum(&accumulated_position_change, pos);
```
Orientation is gyro-integrated (line 108-113, `math_quat_exp`) — smooth and, per H4 below,
self-correcting on roll/pitch via `gravity_correction`. Position is a **double integration of
raw accelerometer** over the anchor-age window (measured at 90-190 ms tonight, §2). Any
transient accelerometer error during that window — bias, a small extrinsic rotation error
misprojecting gravity/centripetal force, or genuine centripetal/tangential acceleration from the
real lever-arm between the neck pivot and the visor's IMU — gets integrated **twice**, so its
contribution to the predicted position grows with the *square* of how long dead reckoning has
to carry it before the next SLAM correction arrives. This is squarely in scope for "orientation
feels fine, position wobbles."

### H3 — Optical-flow feature loss under fast yaw (candidate, not yet measured tonight)

`basalt-g2-config.json` vs. Basalt's own `data/default_config.json` differs in exactly 3 keys
(denser/lower-threshold feature detection: `optical_flow_detection_grid_size` 50→30,
`optical_flow_detection_min_threshold` 5→3, `optical_flow_detection_num_points_cell` 1→3) — a
tuning for this camera's harder scene, not itself yaw-specific. What's unchanged from default and
directly relevant: `optical_flow_levels: 3` and `optical_flow_max_recovered_dist2: 0.04` bound
how far a feature can move between frames and still be tracked by the pyramidal LK tracker; a
fast yaw sweeps every feature across the image fastest of all three axes, and if displacement
exceeds what 3 pyramid levels can recover, tracks are lost and `vio_new_kf_keypoints_thresh: 0.7`
(basalt-g2-config.json) can trip a forced keyframe re-insertion — a discrete event, which would
explain the *skewed, occasional-not-continuous* jump distribution in §2 (a few big yaw jumps,
most yaw motion fine) far better than a smooth per-degree law would. **Not measured tonight** —
this session's own log (`jack-in-wayland.log`) has already been overwritten by later sessions, so
this needs a fresh capture with keypoint-count logging (Experiment 3).

### H4 — Yaw has no gravity anchor; roll/pitch do (structural, not a bug, ties H1-H3 together)

`gravity_correction` (`t_dead_reckoning.c:29`, populated from the tilt-alignment fusion in
`m_imu_3dof.c`, docs/34 §3B) continuously pulls roll/pitch orientation error back toward true
vertical using the accelerometer's gravity reading — a free, constant, absolute reference. Yaw
has no equivalent: nothing in this pipeline (no magnetometer, no loop closure) tells the
integrator "this heading is wrong" except the vision-based bundle adjustment itself, which is
exactly the sensor whose constraint on translation *and* heading weakens under near-pure rotation
(a seated fast yaw is much closer to pure rotation than a nod or tilt, since a yaw's real
lever-arm translation is smaller relative to its arc than pitch/roll's). So whatever triggers a
hiccup (H1's timing error, H2's double-integrated accel noise, or H3's feature-track loss) gets
silently corrected on roll/pitch every fusion cycle, but rides uncorrected on yaw until the next
successful bundle adjustment — explaining why the same-size trigger would look and feel much
worse specifically on yaw, independent of whether §2's per-degree numbers show a clean scaling.

## 4. Experiment plan, ranked by (expected impact × cheapness)

| # | Experiment | Knob / file | Measure with | Pass criterion |
|---|---|---|---|---|
| 1 | **Controlled per-axis capture.** Wearer does ~15 deliberate fast (~80-150°/s) isolated bursts each of pure yaw, pure pitch, pure roll, seated, same room/light as tonight, `SLAM_WRITE_CSVS=1` (already on). Fixes §2's uneven exposure (58 vs 14 events) that makes today's comparison weak. | No code change — a wear protocol only | Re-run this doc's own event-detection method (§2) on the new CSVs — worth turning into a small script modeled on `scripts/head-jitter.py`'s structure (reads `tracking.csv`+`filtering.csv` from a `SLAM_WRITE_CSVS` dir already) | With matched N (≥20/axis): if yaw's median disp/degree is ≥3x pitch/roll's, the per-degree asymmetry is confirmed and H1-H3 below are worth the code investment; if it stays ≤1.5x (tonight's pattern), treat the wearer's "20x" as exposure + perceptual (Experiment 5), not a translation-per-degree law |
| 2 | **Prediction A/B — directly answers "accel-integrated vs. held."** `SLAM_PREDICTION_TYPE=2` (`SLAM_PRED_GYRO`: orientation from gyro, position NOT accel-integrated) vs. default `4` (`SLAM_PRED_DEAD_RECKONING`) during Experiment 1's protocol. | Env var, `t_tracker_slam.cpp:89` — zero code change | Wearer verdict (does a fast yaw still throw him out of his seat with `=2`?) + same event-detection script (does yaw disp/degree drop with `=2`?) | GYRO reduces yaw-triggered displacement without the wearer reporting new floatiness/lag during ordinary motion → H2 confirmed as a real contributor, worth designing a smarter (bounded/capped) dead-reckoning instead of reverting outright |
| 3 | **Optical-flow feature-loss check (H3).** Re-run Experiment 1's protocol with `SLAM_LOG=debug` (or add a one-line log of tracked-keypoint count at `frontend_keypoints_pushed`) and correlate keypoint-count dips against this doc's own yaw-event timestamps. | `SLAM_LOG` env var; optionally a 1-line instrumentation patch in `frame_to_frame_optical_flow.h` if the existing log level doesn't already expose a per-frame count | grep the new log at the exact t+ timestamps Experiment 1's event list gives | Keypoint count visibly craters (e.g. drops below the `vio_new_kf_keypoints_thresh: 0.7` line) at the fastest yaw bursts and not at pitch/roll bursts of the same peak rate → H3 confirmed; keypoints stay flat → H3 refuted, focus stays on H1/H2/H4 |
| 4 | **IMU-camera timing residual probe (H1), the explicitly-requested one.** Extend docs/44's own `0052`/`0053`-style diagnostic (raw `cam_hw2mono` skew at ingestion, already proven-out instrumentation) to log during Experiment 1's fast-yaw bursts specifically, and check whether the residual (post-0055) skew shows any few-ms shift correlated with rising angular rate. | Small additive logging patch in `wmr_source.c` (no live-path behavior change) | New `SLAM_LOG=info` capture, grep `pred: anchor age` / a new skew line, timestamp-matched to yaw bursts | A skew that grows with |yaw rate| (even a few ms) is a real, fixable residual — the fix is then a genuine patch (wire a `cam_time_offset_ns`-equivalent into `t_slam_camera_calibration` and *uncomment* the correction in `sqrt_keypoint_vio.cpp:261`, which as of tonight does not exist as a live path at all). A flat skew regardless of rate closes H1 as the CSVs already suggest it might be secondary. Ranked below 1-3 because even a positive result requires writing that patch before it helps the wearer, not just measuring |
| 5 | **Perceptual/vection decoupling — wearer-only, cheapest, zero code.** In the same session, ask the wearer to do a fast yaw with the render intentionally letting the view catch up slower (or, simplest, just ask him directly: "does a same-size position wobble feel worse when your view is sweeping fast, independent of whether the tracker actually erred more?"). | None | Wearer's own comparative report | If he says a same-magnitude jump feels much worse mid-yaw-sweep than at rest/slow motion, that is direct evidence the "20x" is partly (or mostly) perceptual amplification from rotational vection, not a 20x bigger tracker error — reframes the fix from "chase the tracker" to "the tracker just needs to not have ANY visible hiccup during fast yaw," which experiments 2-4 already target |
| 6 | **(Conditional mitigation, only if #3 confirms H3).** Loosen the optical-flow search headroom: `optical_flow_levels` 3→4 or `optical_flow_max_recovered_dist2` 0.04→0.08 in `basalt-g2-config.json`, trading some CPU (already tight per docs/67 A-head-3) for more recoverable per-frame displacement. | `basalt-g2-config.json` | Same protocol + `scripts/app-fps.sh`/`frame-pacing.sh` to confirm no pacing regression from the extra pyramid level | Yaw-event disp/degree drops toward the pitch/roll baseline from Experiment 1, with no new late-frame cost |

## 5. What this analysis could not determine — needs a wearer or a new capture

- **Whether the per-degree asymmetry is real at all.** Tonight's naturalistic data (§2) does not
  confirm it; it also does not have enough matched, clean pitch/roll events to refute it with
  confidence. Experiment 1 is the actual answer, not more analysis of tonight's file.
- **The "periodic redraw" mechanism.** No periodicity found in the position channel at rest
  (§2). Could be the continuous ~30 Hz SLAM-correction-over-dead-reckoning cycle (not literally
  periodic-feeling, but a real per-update snap), the `p10→p90` 90→124 ms latency spread (roughly
  one full SLAM cycle, meaning ~1-in-10 frames eats an extra 33 ms), or Basalt's own
  keyframe/marginalization cadence (`vio_max_kfs: 7`, `vio_min_frames_after_kf: 5`) — none of
  these are visible in `tracking.csv`/`prediction.csv` alone. Needs a wearer marking (verbally,
  live) the exact moments a "redraw" is felt, cross-referenced against a `SLAM_LOG=debug`
  capture from the same session.
- **Whether the wearer's felt severity tracks the objective displacement numbers at all**, or
  whether (per H4/Experiment 5) the same 0.15-0.20 m excursion feels dramatically different
  depending on whether it happens during a visual sweep or at rest. Only a wearer can answer
  this — it is exactly the kind of claim CLAUDE.md's verification rule exists for.

## 2026-08-26 (late) — Localized: orientation/position TIMESTAMP MISMATCH, not a hidden accumulator

Three traces (SLAM_PREDICTION_TYPE=0/2/2+FREEZE A/B, CSVs in
`/home/iam/vr/logs/yaw-drift-study/`) were adversarially refuted for overreach. Facts, from the
live source + this session's own logs: tracking.csv (t_tracker_slam.cpp:1330, `raw_pose` from
local `nrot/npos`) is untouched by the one-euro filter mutating `rel.pose` just above
(:1252-1256) — same meaning under every pred_type. That filter (`Output filter: one_euro`,
`SLAM_FILTER_BEFORE_PREDICT=1`, pos cutoff 3.14 Hz/rot 20 Hz, confirmed ACTIVE tonight in both
`jack-in-wayland.log:60-64` and `.prev.log:60-64`) runs on the anchor BEFORE `predict_pose()`,
identically for NONE/GYRO/FREEZE. `do_position()` (m_predict.c:73-103) under FREEZE:
`accum={0,0,0}`, so `out_rel->pose.position = rel->pose.position` exactly — no rotation, no
lever arm — the SAME filtered-anchor value NONE also returns verbatim (predict_pose:1369-1371).
What DOES differ: `do_orientation()` (m_predict.c:16-71) runs for GYRO(+FREEZE) but never NONE,
forward-integrating orientation to the query's real `when_ns` from live gyro data
(t_tracker_slam.cpp:1416-1420); NONE leaves the anchor's ~90-190 ms-stale orientation untouched.

**Mechanism**: pred_type ≥ GYRO pairs a REAL-TIME orientation with a STALE (anchor-age)
position in one relation. NONE never splits the two — both stale equally, scene lag is uniform
("orientation delay") and never detaches from where you're looking, which is why NONE feels
rock-solid despite its own raw SLAM noise being the SAME order as GYRO/FREEZE's (median
per-burst residual 8.8/9.0/15.2 cm — nearly identical, off the CSVs). FREEZE removes only the
`linear_velocity*dt` overshoot (axis = raw SLAM velocity, "right"), never `do_orientation`'s
forward prediction — the timestamp split survives, and the SAME order-of-magnitude raw jitter
surfaces on whatever axis the filtered anchor is moving on: axis changes, magnitude doesn't.

**Next experiment (wearer A/B, not more logging)**: real kinematic compensation, not a static
freeze. After `m_predict_relation()` returns (t_tracker_slam.cpp:1455-1457), when
`t.pred_freeze_position`, rotate a candidate lever-arm vector by `rel.pose.orientation` and by
`predicted_relation.pose.orientation`, add the difference to `predicted_relation.pose.position`
(a neck-model delta reusing `do_orientation`'s own orientation change, not the discarded
velocity). Gate via `SLAM_PRED_NECK_ARM_MM` (0 = tonight's freeze). Build (cmake regen broken,
same path as FREEZE_POSITION): `ninja -C /home/iam/vr/monado/build aux_tracking monado-service`
(incrementally recompiles+relinks); re-run Aircar's fast-yaw protocol.

**Pass criterion (wearer, both)**: turns as responsive as GYRO/FREEZE (no return of NONE's lag)
AND no seat displacement accumulates over repeated fast yaws — sweep 2-3 arm lengths live
(0/80/150 mm), not derivable from tonight's data alone. If none collapses the drift toward
NONE's stability, this is refuted and the mechanism is outside Monado (Aircar/xrizer's camera
rig, or a real SLAM/IMU-to-eye extrinsics recalibration) — bigger work, not a tonight fix.

## 2026-08-26 (late) — RESOLVED to "super similar a windows": the seated-6dof recipe

Live wearer A/B sweep on Aircar (seated, gamepad, constellation off), all env-only after the
one code change (patch 0097). Result, wearer's own words across the sweep: 2-4m accumulating
yaw drift -> "bastante solido" -> "como 3dof pero con los 6dof" -> "muy solido... super similar
a windows", "esta suave, sin redraws malos". **This meets the project's stated cutoff (`docs/04`:
"headset on par with Windows or better").**

**Winning config** (now auto-applied to Aircar 1073390 by `vr-launcher.py`'s TITLE_PROFILES;
inert in 3dof since SLAM isn't running):
```
SLAM_PREDICTION_TYPE=2  SLAM_PRED_FREEZE_POSITION=1  SLAM_PRED_NECK_ARM_MM=150  SLAM_CORRECTION_SPREAD_MS=50
```

**What each knob does** (mechanism confirmed by the prior trace above + the per-axis wearer
response):
- `SLAM_PREDICTION_TYPE=2` (GYRO): predicts orientation from the gyro -> head turns are
  responsive (no NONE-style lag). Patch 0097.
- `SLAM_PRED_FREEZE_POSITION=1`: holds position at the last SLAM anchor instead of extrapolating
  linear_velocity across the ~150ms latency -> kills the original ~50cm/turn overshoot that
  accumulated to metres. Patch 0097.
- `SLAM_PRED_NECK_ARM_MM=150`: swings the frozen eye along the neck-pivot arc as orientation
  predicts forward (position = anchor + (R_pred - R_anchor)*arm) -> fixes the orientation/
  position timestamp split. Swept live 80/150/200mm: 80 helped (yaw ~1m, pitch minor, roll
  none), 150 best (rarely >50cm total), 200 no better and felt over-corrected. Patch 0097.
- `SLAM_CORRECTION_SPREAD_MS=50`: existing Monado option (not new code), was off (0). Spreads
  each per-anchor position correction over 50ms so the periodic re-anchor stops snapping -- the
  wearer named that snap ("se reacomoda seguido, eso marea") as the remaining nausea source;
  100ms smoothed it but added convergence lag, 50ms was the balance ("suave, sin redraws malos").

**Remaining residual (documented, not a demo blocker)**: on FAST motion, ~1m bounded drift +
a visible delay before position starts updating. This is the fundamental SLAM anchor age
(~120-190ms) -- genuine head TRANSLATION (not rotation) can only be predicted with the
accelerometer, which is exactly what reintroduces the drift, so this is the practical floor of
this approach. For a seated cockpit demo (rotation-dominant) it is minor. A possible future
refinement (untested): give translation a SHORT clamped-horizon position prediction (e.g. cap
do_position's dt to ~40-50ms) to trade a little drift for less translation latency.

**Still to do before flipping the demo default from 3dof to 6dof**: a 30-minute worn soak to
confirm it holds and does not fatigue over time (per `docs/75`'s own acceptance bar). Data for
every config in `/home/iam/vr/logs/yaw-drift-study/` (WINNER-FINAL-* is this recipe).

## 2026-08-27 — last night's residual reconfirmed live; 0098 ruled out; a 4-way research pass for what's next

A real wearer session (docs/85's closing section) reconfirmed the "FAST motion" residual named
above is still exactly what it was: "seguia desviando bastante al girar rapido, pero se acomodaba"
— matches this doc's own prior description almost word for word. Patch 0098
(`WMR_FORWARD_ANGULAR_VELOCITY`) was on for that session and made no perceptible difference — a
real negative, not surprising in hindsight: 0098 only feeds SteamVR's own late-stage
extrapolation, a stage downstream of where this residual actually lives (the ~120-190ms SLAM
anchor age itself). **Removed from Aircar's profile** to cut a variable.

Ran a 4-candidate research pass (`wf_c99cb54e-e54`, each agent grounded in this doc + the live
source tree, not re-deriving from scratch) on what could still move the needle. Full results in
the workflow journal; summary and what got applied:

- **SLAM_THREADS, re-isolated for Aircar's own constellation-off condition — genuinely new,
  applied.** Every past SLAM_THREADS rejection (docs/67 A-head-3, NEXT-STEP's 2026-08-25 sanity
  check) had WMR constellation controller-tracking competing for the same camera/CPU budget.
  Aircar's own profile runs with constellation OFF, and last night's own `timing.csv`
  (`/mnt/vrtmp/slam-20260826-042947`, recomputed fresh by the research agent, not assumed) shows
  the TRACKING sub-stage — confirmed `tbb::parallel_for`'d in `frame_to_frame_optical_flow.h`,
  unlike detection which is a confirmed plain sequential loop in `keypoints.cpp` — costing 23.2ms
  of the 41.9ms frontend total, more than DOUBLE detection's 12.2ms. That's the opposite weighting
  from "detection is the bottleneck, threads can't help," which is what killed every prior
  attempt. Extrapolating from the one closest real measurement (T235: tracking 24.6→13.4ms at
  4→8 threads) suggests ~10ms off the anchor age. **Set `SLAM_THREADS=6` on Aircar's profile only**
  (not the global default) in `vr-launcher.py`. Real risk, not yet measured: CPU contention with
  Aircar's own render/game threads on this 6C/12T box — must be checked against fps/pacing on the
  next session, not assumed safe just because Aircar is currently GPU-bound.
- **`optical_flow_max_recovered_dist2` 0.04→0.08 — zero CPU cost, applied.** A pure
  forward-backward-consistency acceptance threshold on an already-computed result, not more
  compute. Loosens how much per-frame feature displacement (i.e. fast rotation sweeping features
  across the image) is still accepted as a valid track instead of being dropped. Set directly in
  `~/vr/basalt-g2-config.json` (also **not per-title** — this is Basalt's one shared config file,
  so the change applies to every title's SLAM, not just Aircar; flagged since no other title was
  checked against it). **Second habit-check caught here too**: this file is ALSO not a symlink
  into the repo (`scripts/basalt-g2-config.json`) — synced both copies, same drift class as
  `vr-launcher.py` found earlier tonight (docs/NEXT-STEP.md's 2026-08-27 entry).
- **`optical_flow_levels` 3→4 — held back, conditional.** The other half of H3's mitigation
  (docs/80's own original Experiment 6) genuinely costs CPU on an already-tight frontend budget
  (~42ms against a 33ms nominal per-frame budget on Aircar's own profile). The research agent's
  recommendation: measure first, don't spend the margin blind. **Free, zero-code probe for the
  next session**: launch with `VIT_COLLAPSE_LOG=1` and grep `~/vr/jack-in-wayland.log` for
  `vit_of ... keypoints=` dips timestamp-matched to the wearer's own fast-turn moments (the log
  descriptor is in `docs/41-diagnostic-toolkit.md`). If keypoints visibly crater at the fast
  bursts and not elsewhere, H3 is real and `optical_flow_levels=4` is the next thing to try; if
  they don't, this specific lever is refuted and not worth the CPU.
- **`SLAM_CORRECTION_SPREAD_MS` (currently 50ms) — held back, real risk in BOTH directions.**
  The decay is a pure exponential (`decay_correction_locked()`), so a bigger fast-motion jump
  only adds `ln(size ratio)` to settle time, not a proportional amount — meaning a fixed 50ms
  window plausibly feels proportionally slower to "forget" a big jump than a small one, which
  fits "se acomodaba." But this project's own prior A/B history already tested the OTHER
  direction: 100-120ms was rejected for adding a distinct, perceived "re-adjustment/fill-in
  layer" (`docs/45`, T206) — the *same failure signature* as last night's complaint, produced by
  a longer spread. Shortening to ~25ms is the historically-consistent direction to try, but risks
  turning the biggest jumps into a percussive snap instead of a glide (reintroducing T202's
  original "jittering de casco" complaint this feature exists to prevent). **Not applied** —
  needs a live wearer A/B specifically comparing 25ms against 50ms on BOTH fast motion (does it
  help) and quiet/slow play (does the already-gold feel survive), not a default change on paper
  reasoning alone.
- **IMU-camera timing residual (H1) — not actionable this round.** No code path exists to even
  apply a nonzero camera-IMU time offset today: `cam_time_offset_ns` has no slot anywhere in the
  structs that actually cross the Monado/Basalt process boundary (`vit_camera_calibration_t`),
  so the "commented-out correction" docs/80 originally flagged (`sqrt_keypoint_vio.cpp:260-261`)
  would do nothing even uncommented. The existing 0053 clockskew diagnostic
  (`log_cam_clockskew`) measures a different, coarser quantity (host-arrival jitter between two
  independent streams, 1 sample per ~10s, no rotation-rate field) and cannot answer whether a
  real hardware sync residual grows with rotation rate. Would need a small new instrumentation
  patch before this is even measurable, let alone fixable — parked, not chased further today.

**For the next combined wearer test** (what "probamos todo junto" means concretely): Aircar 6dof
now carries 0097 (unchanged) + 0099 (guards, confirmed clean) + `SLAM_THREADS=6` (new) +
Basalt's looser `optical_flow_max_recovered_dist2` (new, global). Launch with `VIT_COLLAPSE_LOG=1`
set for that one session as a free diagnostic. Watch/report: (1) does fast-turn drift feel any
different, (2) does fps/pacing hold (SLAM_THREADS=6's real risk), (3) any `Tracker diverged` log
spam (0099's radius), (4) keypoint dips at fast-turn timestamps in the log (answers whether
`optical_flow_levels=4` and/or a `SLAM_CORRECTION_SPREAD_MS` A/B are worth a follow-up round).

## 2026-08-27 (night) — combined test ran; a new lever (0100) built, regressed, root-caused, fixed; a 5-variant A/B plan

**The combined test (SLAM_THREADS=6 + looser optical-flow, 0098 removed) — positive, wearer's
words: "viene muy bien, por ahí responde un poco más ágil."** Then a precise description of what
remains, better than any prior session had: *"cuando giro hacia un costado, me desplazo unos cm
hacia el lado opuesto. Miro arriba y baja la cámara un poco suavemente, luego se acomoda de nuevo.
Lo mismo yaw y pitch, roll bien. No es entrecortado, es un poco de delay + un movimiento que ni
está ahí."* Smooth, not jerky; yaw+pitch, roll clean; opposite-direction displacement that settles.

**Hypothesis 1, investigated and RULED OUT: a coordinate-frame bug in 0097's neck-arm vector.**
The arm `{0, 0.6, -0.8}` (authored in OpenXR convention) is rotated by Basalt-native-frame
quaternions, and the Basalt→WMR axis correction (`wmr_hmd_correct_pose_from_basalt`, a +90°
X-rotation then y/z negation) only runs afterwards, once, on the summed position. Looked exactly
like a frame mismatch. Two independent derivations (`wf_4356c640-f2b`) **disagreed** — one said
bug (fix: `{0, 0.8, 0.6}`), one said correct. Tie-break by direct numeric verification: because
the correction is a *linear* map applied to the whole sum, `M(R_pred·arm − R_anchor·arm) =
(M·R_pred)·arm − (M·R_anchor)·arm` — i.e. the raw-frame arithmetic is exactly equivalent to doing
it in the corrected frame with the literal OpenXR-convention arm. Verified on two different test
rotations to full precision; the "fixed" vector would have *introduced* a bug. **Existing code is
correct; not touched.** The symptom is instead the documented residual: FREEZE zeroes real head
translation over the whole anchor-age gap, and the neck-arm model (fixed pivot, fixed direction)
only approximates it — whatever real translation the wearer's actual neck produces during the
gap goes uncompensated until the next SLAM sample, then "se acomoda."

**Lever 2, built: patch 0100 `SLAM_PRED_POSITION_HORIZON_MS`** — the "possible future refinement
(untested)" this doc named on 2026-08-26. Extrapolates the SLAM tracker's real linear velocity
for up to N ms (instead of 0 under full freeze, or the full 90-190 ms gap without freeze), then
holds flat. Position only; orientation still integrates gyro over the full gap. Independently
verified (capture point, dt cap, no double-count with the neck-arm block, default-off no-op,
units) and built clean. Wired at 50 ms.

**Its first wearer test REGRESSED hard**: *"apenas unos pocos movimientos rápidos y me voy 1-2-3
metros fuera de la cabina. Creo que está peor en este sentido, pero a lo mejor sí responde un poco
más rápido. Menos delay, más desfasaje."* The "less delay" is the lever working as designed; the
"more displacement" was the data, not the logic — that session's own `tracking.csv`
(`/mnt/vrtmp/slam-20260827-102554`, 28,011 anchors at 30.0 Hz over 935 s):

| raw SLAM anchor-to-anchor speed | value |
|---|---|
| p50 | 0.042 m/s |
| p90 | 0.535 m/s |
| p99 | 1.656 m/s |
| **p99.9** | **81.0 m/s** |
| **max** | **127.3 m/s** |
| anchors > 1.5 m/s | 353 / 28,010 (1.26 %) |
| anchors > 3.0 m/s | 61 (0.22 %) |

~0.2 % of anchors are re-localization jumps, physically impossible for a seated head; 127 m/s ×
50 ms = **6.4 m in a single frame**. Full FREEZE had been immune by accident — zeroing the
velocity discarded the spikes along with the signal. **Fix, same patch: `SLAM_PRED_POSITION_MAX_
SPEED_CM_S`** (default 150 = 1.5 m/s, 0 = off), a magnitude clamp on the extrapolated velocity,
direction preserved, NaN-safe. Passes essentially all real motion (p99 sits at the boundary),
kills the tails. **Not yet worn.**

**Side find, root-caused**: this doc's own "cmake regen broken" note. A `git commit` in
`~/vr/monado` changes `.git/refs`, which CMake tracks for `u_git_tag.c`, forcing a reconfigure —
which fails on this box because `PYTHONPATH=:/opt/resolve/...` (DaVinci Resolve, leading colon =
empty element) is rejected by a `$<SHELL_PATH:>` generator expression in
`steamvr_bindings/CMakeLists.txt`. `env PYTHONPATH=/opt/resolve/Developer/Scripting/Modules/
ninja -C ~/vr/monado/build aux_tracking monado-service` builds clean. Detail in
`patches/monado/README.md` (0100).

### The plan: 5 variants as dashboard buttons, wearer A/Bs them back to back

Every variant sets only the env vars that differ; `vr-launcher.py` lets ambient env override the
profile by design, so the rest is exactly the gold Aircar 6dof profile (0097 + 0099 +
SLAM_THREADS=6 + the looser optical-flow threshold). All auto-record with the variant name in the
comment — the recordings are the A/B log. `VIT_COLLAPSE_LOG=1` on all (free keypoint diagnostic).

| variant | horizon | clamp | other | what it answers |
|---|---|---|---|---|
| **A** | 50 ms | 1.5 m/s | — | **the main candidate** — does the clamp keep A's "less delay" and remove the "more displacement"? |
| B | 25 ms | 1.5 m/s | — | if A still overshoots on the fastest turns |
| **C** | 0 | — | — | **CONTROL** — the earlier-tonight config the wearer approved; compare against THIS, not memory |
| D | 50 ms | 1.0 m/s | — | if A is right in general but still "jumps" on the fastest turns |
| E | 0 | — | `SLAM_CORRECTION_SPREAD_MS=25` | the other held-back lever, isolated; risk: T202's hard-snap returns |

**Decision rule**: whichever of A/B/D beats C on the fast-turn displacement *without* new
jitter, stays and becomes the profile default (promote to `TITLE_PROFILES`, keep the clamp). If
none beats C, the horizon lever is refuted as shipped and C stays — the residual then genuinely
needs real per-wearer neck extrinsics or a shorter anchor age (SLAM_THREADS was the last cheap
lever for that), not more prediction tuning. E is judged on its own: keep only if it helps the
"se acomoda" tail with no snap.

**Still parked from the research pass**: `optical_flow_levels=4` (read the `VIT_COLLAPSE_LOG`
keypoint counts from tonight's variant runs first — if they don't crater at fast turns, it's
refuted for free) and the IMU-camera timing residual (no code path to even apply one).

## 2026-08-27 (late night) — the A–E verdicts, and the real mechanism: Basalt's landmarks collapse under yaw

### Wearer verdicts, C → A → D → B → E, same fast-turn protocol each time

| variant | wearer's words | read |
|---|---|---|
| **C** control (no horizon) | "no se acomoda, tengo el panorama" | the known residual, reference |
| **A** 50 ms + clamp 1.5 | "mejor la demora, se actualiza más seguido; la posición aún se va al girar rápido pero no tanto; en resumen está mejor" | **beats C** on latency; drift still there |
| **D** 50 ms + clamp 1.0 | "parecido; aún se va bastante al mover la cabeza; igual de poco delay" | ≈ A — the clamp level is not what sets the residual drift |
| **B** 25 ms + clamp 1.5 | "más o menos lo mismo; moviendo rápido me voy unos metros, especialmente yaw" | ≈ A — the horizon length is not what sets it either |
| **E** no horizon + spread 25 | "más demora para actualizar mi posición (no los giros), pero es más suave" | E's smoothness is the spread; its delay is the missing horizon |

**A is promoted to `TITLE_PROFILES["1073390"]`** (`SLAM_PRED_POSITION_HORIZON_MS=50` +
`SLAM_PRED_POSITION_MAX_SPEED_CM_S=150`). The wearer's synthesis — "estaría bueno esa suavidad
pero sin demora" — is variant **F = A + `SLAM_CORRECTION_SPREAD_MS=25`**, untested, queued.

### Why no prediction knob moved the metres: the drift is in the raw VIO

Offline pass over every variant's raw tracker output (`/mnt/vrtmp/slam-20260827-*/tracking.csv`
= Basalt's pose stream *before* any Monado prediction, so horizon/clamp/spread cannot touch it):

| variant | dur s | yaw>90 s | max \|v\| m/s | 1 s windows >1 m | max 1 s disp | span m |
|---|---|---|---|---|---|---|
| C | 268 | 10.5 | 92.7 | 11 | 3.07 | 4.81 |
| A | 231 | 20.6 | 94.5 | 12 | 3.01 | 5.56 |
| D | 311 | 19.1 | 125.4 | 31 | 3.41 | 5.44 |
| B | 585 | 29.6 | 151.9 | 8 | 3.10 | 6.33 |
| E | 414 | 14.0 | 91.5 | 2 | 2.83 | 3.07 |
| unclamped 50 ms | 1148 | 18.2 | 127.3 | 101 | 3.75 | 5.83 |

Every run, control included, has 3 m raw excursions and 90–150 m/s velocity spikes. (Exposure
differs — B had 3× C's fast-yaw seconds — so the counts aren't comparable across rows; the
point is the *presence* in all of them.) Also visible in B's log: the 0099 session-anchor guard
fired **6 times** (3 resets, each at exactly 3.0 m) — the first time it has ever tripped, and
precisely on the wearer's "me voy unos metros"; it measures the runaway correctly and, as its
own disclosed limitation says, does not undo it.

### The mechanism, per frame: keypoints hold, landmarks vanish — and yaw is special

Variant B's `VIT_COLLAPSE_LOG=1` stream (17,372 frames) paired to `tracking.csv` by the exact
`vit_collapse IN … t_ns` frame timestamp (16,616 matched), binned by the instantaneous yaw rate
derived from consecutive quaternions (Basalt world +Z up):

| yaw rate °/s | n | frontend keypoints p50 / p10 | **backend landmarks p50 / p10** |
|---|---|---|---|
| 0–30 | 14,387 | 2944 / 2735 | 52 / 23 |
| 30–90 | 1,376 | 2817 / 2686 | 42 / 10 |
| 90–180 | 372 | 2713 / 2586 | **15 / 1** |
| 180–360 | 410 | 2652 / 2566 | **6 / 0** |
| >360 | 71 | 2614 / 2521 | **5 / 0** |

Control axis — pitch/roll rate with yaw < 30 °/s: 90–180 °/s keeps landmarks **37 / 9**,
180–360 keeps **27 / 10**. So: the frontend never loses features (H3 refuted — `optical_flow_
levels=4` is off the table, free), the backend's landmark set (`lmdb.numLandmarks()`,
`sqrt_keypoint_vio.cpp:1676`) collapses to zero specifically under yaw, and with zero landmarks
the VIO has no visual constraint on translation — position becomes pure IMU double-integration,
which is the metres. Source-verified causes (Basalt tree, read this session):

1. `vio_marg_lost_landmarks: true` (ours) marks every landmark not observed *this frame* as lost
   (`sqrt_keypoint_vio.cpp:563-572`) and deletes it at the next marginalization
   (`:1122-1123`), which in steady state fires nearly every frame. A landmark swept out of view
   is gone before the head comes back. Basalt's **landmark recall** (`optical_flow_recall_enable`,
   off in ours; `frame_to_frame_optical_flow.h:560-655`) can only re-find landmarks still in
   `lmdb` — so it is useless for sweep-and-return unless marg-lost is off. Basalt's own TODO at
   `sqrt_keypoint_vio.cpp:776-783` names exactly this tension.
2. `vio_min_triangulation_dist: 0.05` is a metric baseline gate (`:532-536`). A seated yaw has
   ~0 baseline, so the many keyframes taken during a sweep (`vio_new_kf_keypoints_thresh`
   trips as connected-ratio drops) add **no** new landmarks; keyframe marginalization then
   deletes their hosted landmarks unconditionally (`landmark_database.cpp:66-87`).
3. Yaw vs pitch/roll: a level yaw sweeps the whole scene out horizontally; pitch keeps floor/
   ceiling structure partially in view. Plus H4 (no gravity anchor for yaw): whatever error
   accrues rides uncorrected.

Also low even at rest: p50 = 52 landmarks for 2900 tracked keypoints — a 7-keyframe window
with a 5 cm triangulation gate is starving the backend. Backend cost is nowhere near the limit:
`opt_ms` p99 6.9 ms, `marg_ms` p99 1.5 ms per 33 ms frame.

### Two instruments that were silently broken (fixed)

- **`demo-recorder.py` never ran.** Every launch since 2026-08-26 died on import
  (`ModuleNotFoundError: rig_telemetry`): `rig_telemetry.py`, `gui_env.py`, `wmr_usb_ids.py`
  (and `reseat_audio.py`) lived only in repo `scripts/`, never in `~/vr/`. None of tonight's
  "auto-recorded" variant sessions exist; the per-variant SLAM CSVs above come from the tracker's
  own `SLAM_WRITE_CSVS`, which is why the offline pass was possible at all. Third instance in one
  night of `~/vr` ↔ repo drift (after `vr-launcher.py` and `basalt-g2-config.json`); **11 of 55
  shared scripts** had drifted too (repo newer in all — 18.5 V corrections, English strings,
  the `hmd_usb_no_autosuspend()` refactor). All deployed; new **`scripts/deploy-check.py`** lists
  drift + missing modules and exits non-zero — run it before trusting any launch.
- The "static" EuRoC recording from 2026-08-12 is empty (0 frames): there was no dataset.

### The next lever is the backend — and it can be A/B'd offline

Plan of record (`~/.claude/plans/reflective-herding-codd.md`, approved): patch
`patches/basalt/0013` (`VIT_DUMP_CALIB`) exports the live calibration; `basalt_vio` (built in
`~/vr/basalt/build-tools`) replays an `EUROC_RECORD=1` session; `scripts/replay-basalt-variants.py`
runs N Basalt configs against the same recording and ranks them by drift + landmarks-per-yaw-band;
`scripts/soak-variant.py` runs unattended headset-on stationary soaks for safety (crash,
divergence, CPU, the documented unbounded recall `patches` map). Variant matrix in
`scripts/basalt-variants/` and as dashboard buttons **G** (recall + marg-lost off), **H**
(triangulation 2 cm + 12 keyframes), **I** (G+H), **J** (I + Basalt's looser C++ recall norms —
our JSON's norms are 4× stricter, a discrepancy inside Basalt itself). F–J all ride on A's
Monado-side config with spread 25. Results of the soaks and the replay go below as they land.

### Pipeline validated end to end on a stationary recording (unattended, headset on, nobody wearing it)

`soak-variant.py --tag record --minutes 2 --dump-calib … --euroc-record …` — the first
unattended headset-on run: PASS (0 coredumps, 0 divergence trips, clean teardown). Three things
learned, all now in the tools:

- **`EUROC_RECORD_PATH` is a prefix.** `euroc_recorder_start()` (`t_euroc_recorder.cpp:408-414`)
  always appends `_YYYYMMDDHHmmss` — which is also why the 2026-08-12 "static" dataset looked
  empty: the real one was next to it. Recording works: 5,378 frames × 4 cams, 44.5 k IMU rows,
  1.7 GB as JPG for ~3 min.
- **Patch 0013 works live**: `~/vr/logs/calib-g2.json` (6 KB, 4 × `pinhole-radtan8` 640×480,
  IMU at 250 Hz, `T_imu_cam`, `cam_time_offset_ns=0`) — `basalt_vio --cam-calib` loads it.
- **`vit_collapse IN … t_ns` does not exist offline** (it is VIT-glue instrumentation); the
  harness keys frames by sequence index into `mav0/cam0/data.csv` instead, exact because the
  offline loader feeds every frame and drops none.

Live vs offline on the *same* stationary recording (182 s):

| | max 1 s disp | span | end − start | landmarks p50 |
|---|---|---|---|---|
| live raw SLAM (`tracking.csv`) | 0.087 m | 0.39 m | 0.48 m | 15 |
| offline `basalt_vio` replay, base config | 0.19 m | 0.86 m | 0.42 m | ~20 |

Same regime, not a bit-exact twin: the live tracker itself wanders ~0.4 m at rest on this
view (15 landmarks — the cameras were pointing at whatever the headset lay on), and the
offline run differs by ~2× in span. Known differences: offline runs 1.35× faster than real time
with 6 worker threads (non-deterministic scheduling), the frames were JPG-compressed, and the
Monado-side VIT-glue patches (0007-0010, queue behavior) don't apply offline. **Two rules for
the yaw dataset**: record it as PNG (drop `EUROC_RECORDER_USE_JPG`, ~3 GB in tmpfs for 3 min,
fine), and replay `base` twice to measure run-to-run variance before ranking anything — a
variant has to beat the base by more than the base beats itself. Wall time: 135 s per replay
of a 3-min recording, so a 6-config matrix is ~15 min, no headset.

### Unattended soaks: the base starves at rest too; recall is the lever — and it leaked 18 GB

**base (20 min, headset lying still)**: landmarks p50 16 / p10 7, **min 0 in every 5-minute
bucket** for 2,700 tracked keypoints; the raw position random-walked to **1.97 m from the start
at minute 10, span 4.75 m**, and the 0099 session-anchor guard tripped **7 times at rest** (first
at 256 s, then a cluster at 631–879 s). So the soak's "0 trips at rest" pass rule was wrong on
arrival: the same landmark starvation yaw accelerates is already there when nothing moves, just
slower — which also makes the stationary 20-minute soak a real A/B instrument for the backend
(same view for every variant): span at 20 min, % of frames with < 5 landmarks, trips. All
grading is now relative to base (`scripts/soak-grade.py`).

**G (recall on + `vio_marg_lost_landmarks: false`) — the lever works, then eats the machine.**
Over the same first 3,868 frames the base had landmarks p50 12 / p10 5; G had **p50 70 / p10
55** — ~6× more, with recall costing 0.07 ms p50 / 0.20 ms p99. But `monado-service` RSS hit
**19 GB at 2 minutes** (`patches=7,556,239`, +1,953/frame): `addPointsForCamera()` saves a
pyramid patch for *every* newly detected keypoint when recall is on, and nothing ever erases
them (Basalt's own "TODO: Patches are never getting deleted", `frame_to_frame_optical_flow.h:675`).
Killed at 3 min before it took the 32 GB box down (the tmpfs alone holds 20 GB); the sequence
loop was stopped before I and J (same recall) could start; H (no recall) ran on.

**Patch 0014 (`prunePatches()`)**: a patch is only ever read by `recallPointsForCamera()` for
ids in `latest_lm_bundle`, so keep patches whose id is tracked in any camera or present in the
latest bundle, erase the rest after a grace of 90 frames (the bundle arrives asynchronously a
few frames behind), sweep once a second; `patches.at()` → `find()` so a pruned id means "can't
recall this one", not `std::out_of_range` on the frontend thread. `BASALT_RECALL_PATCH_GRACE_
FRAMES=0` restores the old behaviour for an A/B. Re-run G/I/J on it below.

**H (`vio_min_triangulation_dist` 0.05 → 0.02 + `vio_max_kfs` 7 → 12, no recall) — refuted at
rest.** Full 20 min: landmarks p50 24 / p10 6 (barely above base's 16 / 7), but **46 divergence
trips** (base 7), span **7.5 m** (base 4.75), max 4.9 m from the start, 5.1 % of frames under 5
landmarks (base 4.4 %). Backend cost of the wider window: `opt_ms` p99 7.0 ms vs 2.7 — still far
from the 33 ms frame, so the *keyframe* half of H is affordable; it is the 2 cm baseline gate
that hurts: near-zero-baseline pairs triangulate to badly conditioned depths, and those garbage
landmarks are what jump the position. The two H knobs are therefore split: the triangulation
gate stays at 5 cm; the 12-keyframe window moves into a new variant **K = G + `vio_max_kfs` 12**
(recall + no marg-lost + wider window, triangulation untouched). I and J as originally defined
inherit H's 2 cm gate and are deprioritised; I still runs once for the record.

| variant (20 min, headset still) | lm p50 / p10 | % frames lm < 5 | trips | span | max from start | opt p99 | RSS MB/h (steady, min 10→20) | grade |
|---|---|---|---|---|---|---|---|---|
| base | 16 / 7 | 4.4 | 7 | 4.75 m | 3.00 m | 2.7 ms | +11 | reference |
| H | 24 / 6 | 5.1 | 46 | 7.50 m | 4.90 m | 7.0 ms | +3 | UNSAFE |
| G′ (G + 0014) | 64 / 37 | 1.3 | 30 | 5.73 m | 3.00 m | 5.6 ms | +602 | UNSAFE |
| K (G′ + 12 kfs; rerun on 0015) | 108 / 66 | 0.00 | 1 | 3.01 m | 2.94 m | 10.0 ms | flat (−200) | better than base (trips 7→1), not the fix (span 3 m); frontend p50 36.5 / p99 97 |
| **I (G′ + H: recall + marg-lost off + 2 cm + 12 kfs)** | **145 / 81** | **0.02** | **0** | **0.41 m** | **0.32 m** | 13.6 ms | +232 | **one exceptional run — see I2** |
| I2 (same config as I, on 0015) | 97 / 53 | 0.13 | 4 | 4.52 m | 3.00 m | 10.1 ms | flat (−43) | ≈ base drift with more landmarks; frontend p50 34.8 / p99 93 |

**I did not replicate.** I2 is byte-for-byte I's Basalt config (the only difference is the
`libbasalt.so` underneath: 0015's parallel patch build, which computes the same patches), and it
drifted like the base: span 4.52 m, trips at 413 / 749 / 1004 / 1028 s. Either I's 20 minutes
were a lucky draw of a high-variance process, or the faster frontend (p50 49 → 35 ms) changed
which frames get through and that changed the outcome — with n = 1 per arm the two can't be
told apart. **So "I fixes rest" is withdrawn to "one run of I was exceptional."** I3 and I4 are
I's config again (different prune grace / sweep — no effect on the tracking math), so by their
end there are four runs of the I family to estimate run-to-run variance from; nothing about
rest is decided before that. The landmark-count gains (G3, K, I, I2 all 5–9× base) are
consistent across runs; the drift outcome is not.

**I is the first config that fixes rest** — an order of magnitude on every drift metric (span
0.41 m vs 4.75, max 1-s step 0.20 m vs 3.29, zero trips vs 7) with 145 / 81 landmarks and only
0.02 % of frames under 5. Neither half did it alone: G′ (recall + marg-lost off) had 4× the
landmarks and *still* tripped 30 times; H (2 cm + 12 kfs) was the worst run of the night. The
combination works because each half supplies what the other lacks — recall/marg-lost-off keep
landmarks alive, the 2 cm gate lets a static (zero-baseline) view keep *creating* them, and the
12-keyframe window holds them long enough — and K (I minus the 2 cm gate; result partly lost to a
driver bug, drift metrics recovered from its tmpfs CSV: span 3.0 m, 1 trip) confirms the 2 cm
gate is the ingredient that separates I from "somewhat better". **Costs**: frontend `total_ms`
p50 **49 ms** (base 28; budget 33) and p99 117, `opt_ms` p99 13.6 (base 2.7), RSS +145 MB/h.
The frontend cost is the blocker for a real session and it is known: building 4 pyramid
patches for each of ~2,000 detections per frame, sequentially. **Patch 0015** parallelizes that
loop (`tbb::parallel_for` over the detections; ids, `addKeypoint`, map insertion stay sequential
and cheap; same patches, same ids, same order) — compile-checked in `build-tools`, production
rebuild + an **I2 = I on 0015** soak queued after L. Driver bug that ate K's log (a thread-
interleaved value like `0.93003432.9358`) fixed: the raw log is now copied *before* parsing and
the parser skips unparsable values; K reruns after L.
| G2 (recall only, marg-lost stays on) | 15 / 8 | 0.8 | 5 | 4.85 m | 2.99 m | 3.2 ms | −9 (flat) | = base on every drift metric, plus recall's CPU cost (frontend p99 108) — exactly as the source read predicted |

RSS column note: the driver's first-to-last slope is dominated by the start-up ramp (recall
fills its patch map in the first 2–3 minutes), so `soak-grade.py` now reports the slope over
minutes 10→20 only. Read that way, **G2 is flat** — patch 0014's bound on the patch map holds —
and the residual growth in G′/I (+600 / +232 MB/h) comes from `vio_marg_lost_landmarks: false`
on the backend side (landmarks live longer and keep accumulating observations), not from
recall. +232 MB/h is fine for a demo session (30 min ≈ +115 MB), not for an all-day booth
without a restart between sessions.
| G3 (marg-lost off only, no recall) | 89 / 49 | 0.09 | 7 | 5.46 m | 3.00 m | 6.6 ms | +9 (flat) | SAFE — 5× the landmarks for +3 ms; drift = base |
| L (keyframe threshold 0.9) | 17 / 4 | — | **96** | — | — | — | +34 | **worst of the night — refuted** |
| M (I without recall: marg-lost off + 2 cm + 12 kfs) | 109 / 67 | 0.38 | **21** | 5.95 m | 3.00 m | 10.7 ms | +16 | unstable without recall; frontend p50 28.6 (= base) |
| I3 (I config, recall grace 30 frames, on 0015) | 94 / 40 | 1.9 | **50** (2–5 every minute) | 5.93 m | 3.02 m | 10.4 ms | +360 | CPU fixed (p50 30.6 / p99 58, patches 190k) — tracking much worse, steadily |
| I4 (I config, grace 90, on 0016) | 161 / 93 | 0.12 | 2 | 3.39 m | 2.94 m | 18.0 ms | +125 (1.54 → 1.69 GB) | frontend p50 39 / **p99 65** (was 117 on 0014, 93 on 0015): the amortized sweep works; patches p50 249k / p99.9 385k, bounded |
| base2 (base config, headset moved to a new resting spot at 16:30, controller on) | 64 / 7 | — | **36** | — | — | — | — | **the control that settles it**: same config as base (7 trips), 5× the trips from a different view — placement/texture dominates at-rest stability; interleave or don't compare |

The interleaved pair (base3 → K3) was cut so the wearer session could start; it is the right
next unattended experiment (any night, `soak-variant.py`, back to back at one placement).

### 2026-08-27 17:00 — the wearer's return: F approved, the yaw recording made

**F (A + `SLAM_CORRECTION_SPREAD_MS=25`), worn, same fast-turn protocol**: *"bastante sólido.
Al acercarme al panel volvió un leve jitter, pero hay poca latencia para movimientos, aunque no
ideal aún. Movimientos rápidos siguen con delay, pero no me voy tanto del asiento — uno o dos
metros si lo hago seguido y rápido. Tira hacia atrás generalmente. Antes tiraba a un costado
derecho, antes de eso al izquierdo."* → F ≥ A: **spread 25 is now Aircar's profile default**
(`TITLE_PROFILES["1073390"]`, both copies; Cyberpilot keeps 50, not re-tested). Two observations
worth keeping: the jitter near the panel is the close-range/few-landmarks regime (expected); and
the drift *direction* changes between sessions (left → right → back), which rules out a fixed
extrinsic/lever-arm error (that would push the same way every time) and points at the
optimizer's per-session state — consistent with the landmark story, not with calibration.

**The recording (button R)**: Aircar on F's config + `EUROC_RECORD=1` (PNG) + `VIT_DUMP_CALIB`.
`yaw-protocol-voice.py` spoke the script into the headset at 17:10:39; the wearer followed it
(30 s still → 10 fast yaw → 10 pitch → 10 roll → 60 s free). The recorder wrote from launch to
teardown — 14 GB in 10 min at ~31 fps × 4 cams, with 2.4 GB of tmpfs left when it was stopped
(**lesson: the recorder does not stop with the protocol; stop the session right after, or the
20 GB tmpfs fills in ~4 more minutes**). Trimmed to the protocol window ± 20 s by matching the
phase log's wall clock to PNG mtimes (±1 s): `/mnt/vrtmp/euroc-yaw_20260827170436`, 6,852
frames/cam, 56,709 IMU rows, 4.9 GB, with `phases.json` carrying each phase's `t_ns` boundary;
archived with its calibration and phase log under `~/vr/logs/euroc/`. The dataset's own gyro
holds **18.7 s above 90 °/s of yaw** — enough to band by rotation regime. Replay matrix
launched: base ×2 (noise floor), G3, K, I, J, M, H.

**I3: the grace is not a memory knob.** A 30-frame grace brought the frontend under budget
(p50 30.6 ms, p99 58, patch map 190k) — and produced 50 trips. A patch is the recall's memory
of a landmark that left view; one second is too short for it to come back, so the landmark is
re-detected as a *new* one instead — the churn again. Grace stays at 90 (or longer). Note also
what this does to the I family's at-rest record: **0 / 4 / 50 trips for the same tracking
config.** That is no longer "variance" — the runs were made at different hours (base 11:46,
I 13:19, I2 15:05, I3 15:49) and the room's light changed across the afternoon; every soak sees
whatever the resting headset sees. `base2` (a base replicate at ~16:40) is the control for that
confound, and no at-rest ranking is trusted until it lands.

**The confound is visible in the data.** Frontend keypoints per frame (p50 over each 20-min
run) is a proxy for how much texture the resting cameras had to work with; beside the trips:

| run (start) | base 11:46 | H 12:11 | G′ 12:34 | I 13:17 | G2 13:39 | G3 14:00 | L 14:22 | K 14:44 | I2 15:05 | M 15:26 | I3 15:48 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| keypoints p50 | 2641 | **2397** | 2628 | **3248** | 3017 | 3032 | 2746 | 2983 | 2864 | 2744 | **2398** |
| trips | 7 | **46** | 30 | **0** | 5 | 7 | 96 | 1 | 4 | 21 | **50** |

The two worst runs (H, I3) are the two with the fewest keypoints; the best (I) had the most.
It is not simply "light fades in the afternoon" (G3 at 14:00 had 3032) — it is whatever the
headset happened to be looking at plus the ambient light at that moment, and it moves between
runs by ±15 %. Config still matters inside that (M vs base at similar keypoints: 21 vs 7 trips;
K at 2983: 1), but **no single-run at-rest comparison across different hours is clean**, and
I's 0-trip run coincided with the best-textured 20 minutes of the day. The honest protocol for
the next round is interleaving: base → candidate → base → candidate, back to back.

**M answers the recall question at rest: recall is load-bearing, not decorative.** Same
config as I minus recall → 21 trips (base 7). Lining up every run by whether it has recall +
marg-lost-off: *with* — K 1, I 0, I2 4 trips (all under the base's 7, three runs); *without* —
base 7, G3 7, M 21, H 46, L 96. The 2 cm gate makes the no-recall configs *worse* (H, M) and
the recall configs better (I/I2 vs K) — plausibly because zero-baseline landmarks are only
sound when the frame-to-frame tracker's dropouts get re-attached to the same landmark instead
of re-triangulated as new ones. Span is where the run-to-run variance lives (K 3.0, I 0.41,
I2 4.5 m); trips are the more consistent signal so far.

**L refuted, precisely.** The 0.9 threshold never engaged at rest — keyframe-set changes per
minute `[7, 0, 0, 0, 0, 0, 0, 8, 24, 16, 0, 0, 18, 0, 8, 8, 24, 18, 162, 237, 236]`: nothing
in minutes 1–6 (a static view keeps the connected ratio above 0.9 too), the mid-run changes are
the resets re-initialising, and minutes 18–20 are a reset storm (96 trips total, span 6.4 m).
So "no keyframes at rest" is not fixable from this knob, and together with H it makes a
pattern: adding keyframes/landmarks at zero baseline while `vio_marg_lost_landmarks: true`
keeps churning the set is destabilising; I works because marg-lost-off keeps a consistent set
*and* the gate/window let it grow. The IMU-bias reading of the base's at-rest walk stays a
hypothesis, not a result.

**Where the recall-on frontend cost actually is (K rerun on 0015, live).** Parallel patch
building (0015) bought ~4 ms at the median (p50 42 → 38), not the ~14 hoped. The p99 (~99 ms)
is something else, and it is exact: **63 of 63 frames over 80 ms sit on `frame_counter % 30 ==
0`** — 0014's prune sweep, which erased the whole 200–400k-entry map in one frame: p50 88 ms on
those frames vs 37.7 ms on every other. **Patch 0016** amortizes it: snapshot the key set once a
second (a flat copy, ~1 ms) and check-and-erase 1/29th per frame. The remaining +10 ms at the
median (37.7 vs base 28) is the per-frame recall bookkeeping on a large map — I3 (`BASALT_
RECALL_PATCH_GRACE_FRAMES=30`, env only, queued after M) tests whether a 3× smaller map
recovers most of it. Note the hot spot is confined to recall; M (no recall) pays none of it.

**G3 says most of the landmark gain is just not deleting them.** `vio_marg_lost_landmarks:
false` alone: landmarks 89 / 49 (base 16 / 7; more than G′'s 64 / 37 *with* recall), 0.09 % of
frames under 5, frontend p50 31 ms (base 28), RSS flat — and drift unchanged (7 trips, span
5.5 m). So at rest recall adds nothing that marg-lost-off doesn't already give, and neither
fixes the walk; I's fix needs the 2 cm gate + 12 keyframes on top. That makes **M = I minus
recall** the cheap candidate to test: if M matches I at rest, recall's whole CPU cost (patch
building, 0015 or not) is only justified by what it does under *yaw* — sweep-and-return —
which the offline replay of the wearer's recording will measure, not a stationary soak.

**G′ (recall + marg-lost off, with 0014), full 20 min — three separate verdicts:**

- *Memory*: 0014 cut the leak by >95 % (18 GB in 3 min → RSS 1.13 → 1.73 GB over 20 min).
  `patches` oscillated 228k–388k — bounded with a slow creep, not linear; the RSS slope after
  minute 3 is ~500 MB/h. Liveable for a demo session, not for a day; the 90-frame grace can drop
  to 30 (~60k patches) once the direction is settled.
- *CPU*: recall itself is cheap (1.0 ms p99) — the cost is **building 4 pyramid patches for
  each of the ~2,000 keypoints detected per frame** in `addPointsForCamera()`, a sequential
  loop: frontend `total_ms` p50 **28 → 42 ms** (p99 40 → 101). That is over the 33 ms frame
  budget at the median. The loop is embarrassingly parallel (`tbb::parallel_for`, patch 0015 if
  recall wins); a lazier alternative — only build patches for keypoints that become landmarks —
  needs the detection frame's pyramid later, which the frontend no longer holds.
- *Drift at rest*: **not better** — 30 trips (base 7), span 5.73 m (base 4.75), max 3.0 m from
  the start, despite **4× the landmarks** (p10 37 vs 7, and only 1.3 % of frames under 5). A
  static camera with 37 good landmarks does not walk 3 m; so the extra landmarks are bad ones —
  either recalls re-attached at the wrong image position (`recall_max_patch_dist` allows 3 % of
  the width ≈ 19 px; the JSON's strict `max_patch_norms` were supposed to gate this) or the
  stale observations `vio_marg_lost_landmarks: false` keeps in the optimizer. G2 and G3 split
  exactly those two halves; K adds the wider keyframe window on top of G′.

### Two checks on the interpretation (base soak + variant B, offline)

**The yaw collapse is real, not a reset artifact.** Every divergence reset zeroes `lmdb`, so a
"0 landmarks" frame could just be a post-reset transient. Recomputing B's table excluding the
3 s after each of its 6 resets (497 frames dropped) changes nothing: 90–180 °/s stays 15 / 1,
180–360 stays 6 / 0, >360 stays 4 / 0 (p50 / p10). The collapse under yaw stands as measured.

**At rest the metre jumps are NOT starvation — they are churn on a frozen keyframe set.** In
the base soak, aligning each 1-second raw displacement with the landmark count in that second:
seconds with ≥ 5 landmarks throughout have p90 4 cm; the 3 m jumps all sit in seconds whose
minimum is 0 — but the 0 is the *reset's* doing, not the cause. Frame by frame around the
t = 255 s jump (1.2 m at 255.0 s, 2.8 m at 256.4 s, reset at 256.5 s): landmarks are 39 → 174
→ 70 → 53 → 82 → 64 → 120 → 78 → 176 → 76 … — **flapping by ~100 every frame** for the ~2 s
before the jump, with the camera static. That flapping is an *onset signature*, not the steady
state: over the whole 20 min the frame-to-frame landmark change is p50 0 / p90 5. Meanwhile
`frame_poses` = 7 and `marg_H` = 57 never move outside the resets: **after the first minute at
rest no keyframe is ever taken again** for the entire run (a static view never drops the
connected ratio below `vio_new_kf_keypoints_thresh` 0.7; the only keyframe changes in the
per-minute count sit exactly at the reset minutes). So the backend spends 20 minutes on a
keyframe set frozen from minute 1 — the textbook stationary-VIO failure: with no fresh keyframes
the IMU bias estimate drifts until preintegration and vision disagree, the optimizer starts
rejecting landmarks (`vio_outlier_threshold` 3.0 — the churn), and a bad step walks the position
metres. `vio_marg_lost_landmarks: true` makes the churn worse (G3 tests turning it off alone), but
the cheaper, more direct remedy for *rest* is to keep taking keyframes when the view is static:
**variant L = `vio_new_kf_keypoints_thresh` 0.7 → 0.9** (new detections each frame keep the
connected ratio a little under 1.0, so 0.9 should trigger keyframes periodically; `vio_min_frames_
after_kf` 5 still floors the rate). Queued after G3. It also says the at-rest and the under-yaw
failures are different: yaw genuinely runs out of landmarks; rest has plenty and lets the IMU
side drift.
