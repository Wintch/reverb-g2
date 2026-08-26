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
