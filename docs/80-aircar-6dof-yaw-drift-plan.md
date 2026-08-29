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

### The wearer's recording, replayed: K kills the landmark collapse and halves the yaw drift — but 1.6 m remain with vision alive

Dataset `euroc-yaw_20260827170436` (trimmed to the protocol ± 20 s: 6,852 frames per camera,
56,709 IMU rows, 4.9 GB; `phases.json` carries the `t_ns` of every phase boundary from
`yaw-protocol-voice.py`; archived under `~/vr/logs/euroc/` with `calib-g2-yaw.json`). The IMU
confirms the wearer followed the script — and it calibrates what "fast" means on this head:

| phase | gyro p50 / p90 / max (°/s) | \|acc\|−g p90 / max (m/s²) |
|---|---|---|
| intro (30 s still) | 1.5 / 14.9 / 160.6 | 0.32 / 8.27 — one adjustment event |
| yaw ×10 | 5.1 / **377.5 / 600.2** | 3.84 / 10.93 |
| settle-1 | 1.1 / 1.8 / 3.0 | 0.08 / 0.14 |
| pitch ×10 | 2.0 / 288.9 / 476.2 | 6.46 / 14.04 |
| settle-2 | 1.2 / 2.0 / 3.2 | 0.09 / 0.19 |
| roll ×10 | 7.2 / 274.4 / 412.3 | 1.83 / 4.68 |
| settle-3 | 1.2 / 1.8 / 2.6 | 0.08 / 0.16 |
| free play | 22.4 / 131.8 / 369.5 | 1.78 / 7.02 |

The settle phases are genuinely still (≤ 3 °/s, ≤ 0.2 m/s²), so whatever the trajectory does
there is the tracker. `scripts/replay-phase-slice.py` cuts each replayed trajectory by these
boundaries; per phase: max 1 s displacement / net (start → end) / max distance from the
phase start, all in metres. Base config vs K (`G` + `vio_max_kfs` 12), same dataset, same calib:

| config | intro | **yaw** | settle-1 | pitch | settle-2 | roll | settle-3 | free | rot maxfar Σ |
|---|---|---|---|---|---|---|---|---|---|
| base | 0.69/0.83/0.85 | 0.61/2.55/**2.62** | 0.00/0.01/0.01 | 0.25/0.30/0.36 | 0.01/0.01/0.01 | 0.14/0.54/0.61 | 0.00/0.01/0.01 | 0.65/0.27/0.88 | **3.59** |
| K | 0.70/0.87/0.89 | 0.53/1.27/**1.65** | 0.00/0.01/0.01 | 0.28/0.03/0.23 | 0.00/0.01/0.01 | 0.14/0.13/0.25 | 0.00/0.01/0.01 | 0.65/0.27/0.82 | **2.12** |

Whole-recording: base span 3.62 m, landmarks p50 / p10 at > 360 °/s = **5 / 0** (the live
collapse, reproduced offline); K span 2.14 m, **671 / 565** at > 360 °/s — the collapse is gone.
Three readings:

1. **The settles are 1 cm in both.** Still head + rich view = no drift; the at-rest walk of the
   20-minute soaks needs minutes to start, not seconds, and does not confound a 3-minute test.
2. **K halves the rotation drift everywhere** (yaw 2.62 → 1.65 m, pitch 0.36 → 0.23, roll 0.61 →
   0.25) and the intro / free-play phases are identical between configs (0.85–0.89 / 0.82–0.88 m,
   with the IMU showing real motion in both) — so those are the wearer, not the tracker.
3. **But yaw still runs 1.3 m net with ~600 landmarks alive.** Landmark starvation was the
   dominant term and is fixed; what remains is a rate-dependent error *with vision present*.
   That is the signature of **H1 (§3): an IMU–camera time offset** — a few ms of misalignment is
   invisible at rest and turns into translation exactly in proportion to angular rate
   (`cam_time_offset_ns` is 0 in the dumped calibration, never calibrated, and Basalt's own
   correction for it is commented out at `src/vi_estimator/sqrt_keypoint_vio.cpp:261` —
   `// curr_frame->t_ns += calib.cam_time_offset_ns;` — so setting the field would do nothing;
   the dataset shift below is exactly what that line would do, same sign). The recording makes H1 testable **offline without code**: four copies of
   the dataset with `camN/data.csv` timestamps shifted by −10 / −5 / +5 / +10 ms (PNGs symlinked,
   IMU untouched — `/mnt/vrtmp/euroc-yaw-shift_*`), replayed with K. If one direction cuts the
   yaw-phase drift monotonically, the offset is real and its sign is known; the live fix is then
   a stamp shift in `vit_tracker.cpp` (a patch, env-gated like the rest). If all four are worse
   than K, H1 is closed for good and the residual is elsewhere (rolling shutter, blur-corrupted
   tracks at 400–600 °/s). Queued behind the matrix; results below when in.

### The full matrix on the recording: J takes the yaw drift from 2.6 m to 0.28 m (net 5 cm)

All eight configs, same dataset, same calibration, per phase (max 1 s / net / max-far, m):

| config | what it is | **yaw** | pitch | roll | Σ rot maxfar | worst settle | span (whole) |
|---|---|---|---|---|---|---|---|
| base | `basalt-g2-config.json` | 0.61/2.55/**2.62** | 0.25/0.30/0.36 | 0.14/0.54/0.61 | **3.59** | 0.014 | 3.62 |
| base2 | same again (noise floor) | 0.61/2.70/2.76 | 0.25/0.30/0.36 | 0.13/0.51/0.56 | 3.68 | 0.019 | 3.71 |
| G3 | marg-lost off only | 0.68/1.63/1.63 | 0.28/0.40/0.49 | 0.10/0.17/0.31 | 2.43 | **0.223** | 2.62 |
| H | gate 2 cm + 12 kfs (no recall, marg-lost on) | 0.49/1.72/1.75 | 0.24/0.22/0.28 | 0.11/0.40/0.42 | 2.45 | 0.008 | 2.65 |
| K | recall + marg-lost off + 12 kfs | 0.53/1.27/1.65 | 0.28/0.03/0.23 | 0.14/0.13/0.25 | 2.12 | 0.012 | 2.14 |
| M | I without recall | 0.34/1.21/1.21 | 0.34/0.28/0.47 | 0.10/0.20/0.30 | 1.99 | 0.037 | 1.93 |
| I | recall + marg-lost off + gate 2 cm + 12 kfs | 0.39/0.69/0.96 | 0.27/0.10/0.20 | 0.09/0.12/0.19 | 1.34 | 0.008 | 1.58 |
| **J** | **I + Basalt's default recall norms** | **0.28/0.05/0.28** | 0.27/0.03/0.22 | 0.09/0.08/0.12 | **0.63** | 0.010 | **0.96** |

Intro and free-play columns are the same for every config (0.85–0.89 / 0.80–0.88 m max-far,
with the IMU showing real motion) and are omitted. Readings:

- **Noise floor**: base vs base2 differ by 0.1 m on the Σ; every step below is well outside it.
- **J after ten 400–600 °/s yaws ends 5 cm from where it started** (base: 2.55 m), max
  excursion 0.28 m — which is the order of the neck-arm translation of a real seated head turn.
  Pitch 0.22 and roll 0.12 max-far are in the same regime. The whole-recording span, 0.96 m, is
  now mostly the wearer's own motion (intro adjustment + free play).
- **Each lever's contribution is separable**: marg-lost off alone (G3) helps yaw but *leaks*
  22 cm of drift into the still phase right after it — stale observations kept in the
  optimizer; the 2 cm gate + 12 kfs (H) helps a similar amount without the leak; their union K
  is better than either; adding the gate to K (I) is the biggest single step for yaw (1.65 →
  0.96); removing recall from I (M) costs 0.65 m on the Σ *even though M keeps 661 landmarks p10
  through > 360 °/s* — so recall's value is not landmark *count* (the gate and marg-lost-off do
  that) but re-attaching the **same** landmark IDs after a sweep; and the last step, J, is only
  the recall acceptance norms: the JSON's 4× stricter `optical_flow_recall_max_patch_norms` were
  rejecting most valid recalls (I: recall on, but half-working).
- Costs offline (two 4-thread streams sharing 12 cores, so absolute ms are pessimistic): J's
  recall p99 2.8 ms, patches 325 k at the end (0014's bound), wall 360 s vs base 328 (+10 %);
  I 407 s. Live, patch 0015's parallel patch building applies; the earlier soak measured I at 0
  trips with acceptable frontend timing.

### H1 CONFIRMED offline: the camera stamps are late vs the IMU by ≥ 5–10 ms, and it is the biggest lever of all

The ±5 / ±10 ms sweep (config I, camera stamps shifted, IMU untouched), per phase:

| I with cam stamps shifted | **yaw** max1s/net/maxfar | pitch | roll | Σ rot | worst settle | span |
|---|---|---|---|---|---|---|
| **−10 ms** | 0.29/0.10/**0.24** | 0.27/0.04/0.21 | 0.09/0.04/0.10 | **0.55** | 0.009 | 0.93 |
| −5 ms | 0.29/0.10/0.30 | 0.27/0.04/0.21 | 0.08/0.10/0.15 | 0.66 | 0.010 | 0.94 |
| 0 (I) | 0.39/0.69/0.96 | 0.27/0.10/0.20 | 0.09/0.12/0.19 | 1.34 | 0.008 | 1.58 |
| +5 ms | 0.73/1.63/1.72 | 0.30/0.27/0.27 | 0.14/0.32/0.52 | 2.50 | 0.051 | 2.15 |
| +10 ms | 2.64/4.08/**4.21** | 0.34/0.55/0.55 | 0.25/1.09/1.26 | 6.01 | 0.085 | 5.40 |

Monotonic in both directions and enormous: a 20 ms difference in one number moves the yaw
drift from 0.24 m to 4.2 m, with pitch and roll far less sensitive — exactly the H4 asymmetry
(§3: yaw has no gravity anchor, so a timing error goes straight into translation). The
direction says the **frame timestamps Monado hands to Basalt are later than the exposure by
at least 5–10 ms** (moving the camera stamps *earlier* fixes it), which is what a
transfer-latency stamp would look like. −10 ms alone beats J's config gains (Σ 0.55 vs 0.63)
and the two are independent, so the sweep continues on J at −5/−10/−15/−20/−30 ms to find
the minimum; the settle phases stay at 1 cm throughout, so the shift costs nothing at rest.

**The value, pinned on J** (same sweep, Σ rot max-far / yaw max-far, m): J 0.63 / 0.28; **−5 ms
0.53 / 0.21; −10 ms 0.53 / 0.22**; −15 ms 0.70 / 0.39; −20 ms 1.86 / 1.53; −30 ms 5.09 / 4.54.
A flat plateau from −5 to −10 and a cliff on both sides; settles ≤ 1.1 cm throughout. The
midpoint, **−7 ms**, is what the JT button carries (`VIT_CAM_TIME_OFFSET_NS=-7000000`). The
plateau's width is the auto-exposure's doing: the true stamp error is 5.55 ms − exposure / 2
(next paragraph), i.e. 1–5.5 ms as the exposure ranges 9 → 0.06 ms, plus whatever `start_ts`
itself lags; a fixed offset can only sit in the middle of that, which is one more reason the
driver-side `start + exposure / 2` fix is the right permanent one.

The live lever is patch **0017** (`VIT_CAM_TIME_OFFSET_NS`, applied at `vit_tracker.cpp`'s
`partial_frame->t_ns = s->timestamp` — the one place the frame stamp enters Basalt; the IMU
path is untouched, `frames_original_timestamp` keeps the original). Negative values move the
frames earlier; the offline dataset shift and the env var have the same sign. The permanent
fix belongs upstream of that — in how Monado's WMR camera driver stamps frames — once the
value is pinned. **Where at least half of it comes from, read in `wmr_camera.c:396-434`**: the
frame footer carries `start_ts` and `end_ts` (100 ns ticks, same clock as the IMU), and
`end_ts − start_ts` is "always about 111000 × 100 ns" = **11.1 ms, the 90 Hz slot period**,
not the exposure. The driver stamps the frame at `frame_start_ts + delta / 2` = start +
**5.55 ms**. The actual exposure is in the pixel header (`exposure`, µs — 6000 ≈ 6 ms per the
T221 note; SLAM frames auto-expose between 60 and 9000), so mid-exposure is start +
exposure / 2 = start + 0.03–4.5 ms: the stamp is late by 1–5.5 ms from that alone, more if
`start_ts` marks something later than the exposure start. That explains the sign and the
first ~5 ms; the −5…−30 ms J sweep says how much is left over. The driver-side fix is
`xf->timestamp = frame_start_ts + exposure_ns / 2` (a Monado patch, env-gated for A/B), which
also tracks the auto-exposure frame by frame instead of a fixed offset.

**Round N — J is the config plateau.** Five refinements on top of J, same dataset (Σ rot
max-far, m; noise floor 0.1): N1 gate 1 cm **0.67**, N2 16 keyframes **0.63**, N3 kf-threshold
0.9 **0.73**, N4 kf every 2 frames **0.65**, N5 recall on all four cameras **0.66** — none
beats J's 0.63, all settles ≤ 1.2 cm, and the costs go the wrong way (N5 recall p99 7.9 ms vs
2.8; N1/N2 wall +33 %). Nothing left to win in the backend config; the residual 0.28 m of yaw
max-far is timing (next section).

**Decision**: J is the offline winner by every column and the wearer tests it next (dashboard
button J).

### 2026-08-27 ~20:30 — worn: J and JT, 5 min each

- **J**: *"muy similar. Al moverme rápido, siento misma demora, pero se vuelve a acomodar más o
  menos bien, por más que primero se vaya varios cm para un costado. Movimientos lentos aún veo
  cabina con un poco de jitter y latencia."* — The metres are gone (F, two hours earlier: *"uno
  o dos metros si lo hago seguido y rápido"*; now *"varios cm"*), which is what the offline
  ranking predicted. What is left is a different layer: the same **delay** on fast motion and
  **jitter + latency on slow motion**. 0 divergence trips in the session (B's protocol run
  had 6); live CSV `~/vr/logs/live-J-tracking-20260827.csv`.
- **JT** (J + −7 ms): *"muy similar, un poco más de jitter al mirar lento parece. Pero se
  reacomoda igual al girar rápido."* — no wearer-visible gain over J; the offline gain at J's
  level was small (Σ 0.63 → 0.53) and the wearer can't tell it apart. The −7 ms is NOT
  promoted; 0017 stays as the A/B instrument for the driver-side fix.
- **The number behind the delay**, from JT's live log (3,935 frames): frontend `total_ms`
  **p50 45.8 / p90 57.9 / p99 76.8 ms** against the 33 ms camera period — the base config runs
  p50 28. Landmarks p50 498 / p10 194 (base at rest: 52 / 7). So J's backend fix costs ~18 ms
  per frame in the frontend, the SLAM pose arrives that much later, and at p90 the frontend is
  1.75 frames behind — irregular pose spacing is a plausible source of the slow-motion jitter
  and the position lag is fed straight into the 50 ms horizon clamp of 0100. Next lever is
  **frontend cost**, not accuracy: round P (J with lighter detection: `num_points_cell` 2,
  `grid_size` 40, both, `max_threshold` 60) runs single-stream offline to measure ms and drift
  together; plus three code reads (frontend hot spots under recall, the pose-age/prediction
  path in `t_tracker_slam.cpp`, the camera stamp semantics for the driver fix).

### The three code reads (unattended, ~21:00) — three levers, four small patches, three buttons

**Frontend (Basalt, `frame_to_frame_optical_flow.h`)**: (a) `recall_ms` in the `vit_of` line
times only `recallPoints()` (`:333-335`); the recall-gated patch build in `addPointsForCamera`
(`:746-762`) and `prunePatches()` (`:339`) land in the undifferentiated rest of `total_ms` — so
"recall p99 2.8 ms" understates recall's cost by an order of magnitude; the existing
`addTime()` stage stamps (`vit_tracker.cpp:65-92`) are the right attribution and should go
into the log line next. (b) A straight bug of ours: 0016 amortized the sweep of `patches` but
left `prunePatches`' *other* map, `patch_last_seen`, on a full walk every 30 frames (`:721-725`,
~300 k entries in one frame) — the same spike shape 0016 fixed one map over. **Patch 0018**
stamps only ids that own a patch, which makes `patch_last_seen ⊆ patches` and lets the
amortized sweep erase both; the full scan is gone. (c) Recall *reduces* new detections (a
successful recall fills its cell before `detectKeypointsWithCells` runs), so `num_points_cell`
and `grid_size` are trade-off knobs, not free ones — but **`optical_flow_levels` 3 → 2** cuts
both per-point costs (patch build and `trackPointFromPyrPatch`) by 25 % without touching the
same-id logic: variants P5 (levels 2) and P7 (levels 2 + 2 pts/cell) queued after round P.
(d) Two serial loops remain: `recallPointsForCamera`'s per-landmark loop (Basalt's own `TODO:
Parallelize recall`, `:611`) and `detectKeypointsWithCells`' per-cell FAST sweep — candidates
once the attribution says they matter.

**Pose path (Monado, `t_tracker_slam.cpp`)**: (a) Under the deployed `SLAM_PREDICTION_TYPE=2`
the only anchor-age log sits in the dead-reckoning branch and never runs; **nobody has ever
measured the pose age**. **Patch 0102** (`SLAM_POSE_AGE_LOG=N`) samples `when_ns − rel_ts` at
every `t_slam_get_tracked_pose` and logs p50 / p90 / max every N predictions — on for every
dashboard variant from now (`512`). (b) 0100's horizon is a **freeze, not a delay**: orientation
integrates over the full age, position over `min(age, 50 ms)` and then stops (`:1672-1691`);
with J's 46 ms frontend + 33 ms period the age exceeds 50 ms on essentially every anchor, so the
position lags by `v × (age − 50 ms)` — the wearer's "misma demora" has a mechanism. Button
**JH** = J + horizon 100 ms (env only; the 1.5 m/s clamp still guards the spikes). (c) Slow-
motion jitter: with the head nearly still each anchor's correction delta is raw mm-level VIO
noise, and a 25 ms decay against a 33 ms anchor period never settles before the next
uncorrelated delta lands — the spread replays the noise at camera rate. **Patch 0103**
(`SLAM_CORRECTION_AVG_N`) feeds the accumulator the mean of the last N deltas (ring, reset on
the reset-anchor path); ~1 anchor of lag on the correction only. Button **JA** = J + N=3.
`filter_pose` is inert in every deployed profile (`SLAM_FILTER` unset) — not a suspect.

**Camera stamps (Monado, `wmr_camera.c`, `wmr_source.c`)**: the hardware→monotonic offset is
learned from IMU arrivals only (`wmr_source.c:204-278`, `hw2mono`) and applied identically to
SLAM and controller frames — so no *relative* offset comes from there; the lateness is the
`start + slot/2` stamp. Exposure is confirmed microseconds (`"[%d] Exposure (usec)"`,
`wmr_camera.c:632`). **Patch 0101** (`WMR_CAM_TS_MID_EXPOSURE=1`) stamps SLAM frames at
`start + exposure/2`, following the auto-exposure frame by frame; controller frames untouched
(the constellation tracker uses the stamp the same way but has no measurement to calibrate
against and its own exposure experiments in flight). Button **JM** = J + that, no fixed offset.
What it cannot explain: the offline optimum (−5…−10 ms) exceeds the 1–5.5 ms this arithmetic
predicts, so `start_ts` itself likely lags the exposure start — the shortfall is measurable
by recording once more with JM and replaying at offset 0 vs −5.

All four patches default off; `monado-service` and `libbasalt.so` rebuilt with them at ~20:40
(nothing running). An adversarial review of the four diffs ran before any wearer use — and
earned its keep: 0102's first draft wrote its ring with no lock on the claim "compositor
thread only", while the file's own `correction.mutex` comment says the constellation tracker's
thread calls the same function (data race, now under the mutex); 0101's trace printed an
`int64_t` with `PRIu64`; 0103's "~1 anchor of lag" is really (N − 1) / 2 periods. Plus **0019**:
the `vit_of` line now carries `pyr_ms track_ms detect_ms filter_ms prune_ms`, because
`recall_ms` was measuring almost none of recall's cost.

### Round P — the frontend cost has a config answer: `grid_size` 40 (J's drift at the base's cost)

Single stream, 6 threads, idle box, same recording — and the offline numbers reproduce the
live ones (base 28.2 ms p50 offline vs 28 worn; J 44.9 vs 45.8 worn), so they are real ms:

| config | frontend p50 / p90 / p99 (ms) | keypoints p50 | patches p50 | Σ rot max-far (yaw) |
|---|---|---|---|---|
| base | 28.2 / 30.6 / 37.3 | 3239 | 0 | 3.54 (2.61) |
| J | 44.9 / 55.5 / 68.8 | 3173 | 217 k | 0.70 (0.33) |
| P1 = J + `num_points_cell` 2 | 34.0 / 45.2 / 57.6 | 2044 | 141 k | 0.74 (0.43) |
| **P2 = J + `grid_size` 40** | **26.6 / 33.3 / 42.7** | 1922 | 120 k | **0.78 (0.43)** |
| P3 = J + both | 20.1 / 25.0 / 31.7 | 1228 | 76 k | 1.07 (0.68) |
| P4 = J + `max_threshold` 60 | 50.8 / 64.5 / 78.5 | 3286 | 228 k | 0.58 (0.27) |

Fewer, larger detection cells (640 × 480 / 40² ≈ 190 per camera instead of 340) cut the
keypoint count 40 % and with it every per-point stage — patch build, tracking, recall — and
the drift does not move (0.78 vs 0.70, noise floor 0.1, settles 7 mm). P3 goes further on
cost but starts paying in yaw (0.68); P4 buys a little drift for a lot of ms. **P2 is J
without the 18 ms** and under the 33 ms camera period at p90 — buttons **JP** (P2 alone) and
**JX** (P2 + horizon 100 + correction averaged over 3 + mid-exposure stamp, the whole night's
stack, for after the single-lever tests). [As run on the 28th JX kept horizon 50 — JH's 100 ms had been refuted worn by then; see the JX verdict below.] Queued offline: P5/P7 (`levels` 2 on J, J + 2 pts),
P6/P8 (`levels` 2 and `max_threshold` 60 on P2) for the margins.

**`optical_flow_levels` 3 → 2 is refuted, hard**: P5 (J + levels 2) saves 1 ms (43.7 vs 44.9
p50) and **diverges to kilometres** — yaw 3.5 m, then pitch 1,346 m, roll 10 km, the still
phases 6 km; P7 (levels 2 + 2 pts/cell) 35.5 ms and Σ 6.07 m (yaw 4.5). The coarsest pyramid
level is what lets the tracker follow 400–600 °/s between two frames 33 ms apart; without it
the frontend loses the frame-to-frame match and the VIO free-runs on the IMU. The per-point
cost that `levels` was supposed to cut was never the dominant term (1 ms of 45); the cell
count is. Do not retry. P6 (P2 + levels 2) did fail the same way (Σ 4.37 m, yaw 3.2), and P8
(P2 + `max_threshold` 60) buys nothing (31.5 ms p50, Σ 0.81). **P2 stands.**

**P2 on the 0018 + 0019 build, with the stage attribution the frontend read asked for**
(`basalt_vio` rebuilt, same recording): total **25.9 / 31.6 / 41.3 ms** (p50 / p90 / p99; pre-
0018 26.6 / 33.3 / 42.7 — 0018 is worth ~1 ms), drift unchanged (Σ 0.82 vs 0.78). Per stage,
p50 / p99: pyramid 0.8 / 4.0, **tracking 10.4 / 18.5**, **detection + matching + patch build
12.7 / 20.6**, filter 0.1 / 0.2, **prune 0.4 / 11.4**. So with recall on the frontend is two
halves — frame-to-frame tracking and detection — and the one remaining spike is the sweep
frame of `prunePatches` (1 in 30: the snapshot of ~120 k patch keys), which is the whole p99
tail above p90. Next micro-lever if the tail ever matters: spread the snapshot too, or drop
the grace from 90 to 60 frames to halve the map. Not needed for the wearer test.

### 2026-08-28 ~18:13 — worn: JP; and the pose age, measured for the first time, is 115 ms under load

[Times in this and the next section corrected 2026-08-28 19:40 from the sessions' own artifacts
(/mnt/vrtmp/slam-20260828-181330 … -184706, demo-recorder finalisation 18:59); the headers
originally said ~00:30 / ~01:45.]

**JP** (P2 config): *"Si me muevo lento, parece que apenas mejoró el jittering mirando la
cabina. Si me muevo rápido, circular — me voy unos cuantos cm y tengo que reiniciar. Dentro de
todo yaw no me saca tanto como en otras pruebas. Pero no es la solución aún."* Live frontend
with the game running: **29.9 / 37.7 / 47.7 ms** (p50/p90/p99; J was 45.8 / 57.9 / 76.8 —
tracking 13.7 + detection 12.6, prune p99 12.7 = the snapshot frame), 1 divergence trip,
landmarks p50 657 / p10 128, CPU load 6 of 12 cores.

**0102's first numbers.** Before the game loaded: pose age p50 68–71 ms, p90 88–96, max
111–204. **With Aircar running: p50 115 ms (per-window 64–246), p90 151, max 359** — over
155 windows of 1024 predictions. Under load the whole chain stretches: backend `opt_ms` p50
17 / p90 32 / p99 45, output interval p50 34 / p90 46 / p99 58 ms (the camera delivers every
33; 293 input frames dropped over the session, input queue up to 2). Against 0100's **50 ms
horizon that is a position freeze of 65 ms at the median and 100 ms at p90** — the wearer's
"demora" and, since the freeze ends with a jump when the next anchor lands, part of the
"circular → unos cm → reiniciar" too. JH (horizon 100) covers the median, not p90; a 150–200
ms rung is prepared as JH2 (the 1.5 m/s clamp is what makes a long horizon safe).

**JH refuted worn** (J config + horizon 100): *"hay más jitter. Si me muevo rápido, se va,
incluso un poco más. Pero en uno o dos segundos se acomoda nuevamente. Si me esfuerzo, aún
puedo hacer que se vaya girando rápido en círculo. Con yaw solo difícil que pase."* Its age
log: p50 153 / p90 181 / max 500 ms (J's heavier frontend + the game). Extrapolating a noisy
anchor velocity twice as far doubles every velocity error — the same "menos delay, más
desfasaje" the first 0100 test found, now with the clamp. **The horizon is not the lever; the
age is.** JH2 not tried. JA/JM/JX moved onto P2 with horizon 50.

**JA kept** (P2 + `SLAM_CORRECTION_AVG_N=3`): *"el jitter diría que es manejable, no perfecto
pero mejoró. Hay bastante latencia para desplazarme hacia los costados, igual que siempre,
capaz a medida que baja jitter suma un poco más todavía de esta demora. Muy molesto aún el
tema de movimiento yaw y pitch que provocan primero un desplazamiento, también como
veníamos."* Age p50 74 / p90 94 / max 388 (0 trips, frontend 26.6 / 38.4 / 51.7) — JP's 115
was not the config, it was that session's CPU load; the age varies run to run. Two problems
left, both named precisely: (1) lateral-motion latency (the age itself, now measured; 0020
adds `age_in_ms` / `age_out_ms` on the collapse lines to split it into transport / Basalt /
Monado — first idle numbers: exposure → tracker input **12 ms**, exposure → pose out 29 ms);
(2) the rotation-onset displacement (yaw/pitch → the head "moves" first, then settles) —
which is exactly what the offline timing sweep was about, so JM (mid-exposure stamp) is the
test of it.

**JM kept** (P2 + `WMR_CAM_TS_MID_EXPOSURE=1`): *"lo bueno — complicado hacer que me vaya de
la nave, un reset cada tanto y va. Lo malo es que aún girando me mueve de silla bastante,
luego se acomoda. Jittering poco, pero notable aún."* The excursions are the part the
timing fixes, as offline predicted; the rotation-onset displacement is still there (2 trips).

**And the age, decomposed (JM's log, 9,100 frames, game running)**: `age_in` (exposure →
tracker input) **p50 11.4 / p90 11.9 / p99 13.3 ms** — transport is small and constant;
`age_out` (exposure → pose out of Basalt) **p50 59 / p90 170 / p99 265 ms** with the frontend
at 29.5 / 38.9 / 52.9 and the backend `opt` p90 ~32. Neither stage explains a 170 ms p90 —
the **queues** do: `image_data_queue` capacity 2 and `vision_data_queue` capacity 2 (`vit_
tracker.cpp:449,469`, both drop-oldest since 0001/0002) let the pipeline run up to 4 frames
deep after one slow backend frame, and 4 × 33 + processing ≈ 170. Monado's display-side age
that session: p50 105 / p90 138 / max 402. **The lever for the lateral latency is queue
depth 1 on both** (a dropped frame costs nothing at 30 Hz with the IMU in between; the pose
age is bounded to ~2 frames + processing) — patch 0021 next.

**JX** (P2 + AVG_N 3 + mid-exposure): *"muy similar, bien, no perfecto. No le noté mucho
cambio ahora."* — JA + JM compose without surprises. Its age: p50 155 / p90 186 / max 1159
ms, Basalt in→out p50 102 / p90 188 / p99 257, 1 trip — worse numbers than JM's session with
the same config, i.e. the age is dominated by the moment's CPU load, not the config; Monado
adds ~50 ms on top of `age_out` (out-queue wait until the next `flush_poses` + the display
time being ~2 frames ahead). **JQ** = JX + `VIT_QUEUE_DEPTH=1` (Basalt 0021) is the test of
the queue hypothesis, with 0020's numbers as the instrument.

### 2026-08-28 ~18:47 — JQ: "sólido, pero no resuelto aún" — the afternoon's stack becomes Aircar's profile

**JQ** (P2 + AVG_N 3 + mid-exposure + queue depth 1): *"se va pero se acomoda bastante bien.
Sólido, pero no resuelto aún."* — the best of the seven verdicts. The instrument agrees:
Basalt in→out **p50 43 / p90 103 / p99 153 ms** over the full session (first minute 42 / 50 /
73; JM 59 / 170 / 265, JX 102 / 188 / 257), display-side age **p50 75 / p90 93 / max 281**
(JX 155 / 186 / 1159), frontend 24 / 36 / 46, **383 of 18,280 frames dropped (2.1 %)** at the
depth-1 queues, 0 divergence trips. The queue hypothesis held: the tail above p90 was
queueing, and depth 1 halves it without a felt cost.

**Seven worn A/Bs (J/JT 2026-08-27 ~20:12–20:22, JP→JQ 2026-08-28 18:13–18:57 -03), one line
each**: J (metres → cm) · JT (−7 ms: no felt change) ·
JP (P2: cost fix, same feel) · JH (horizon 100: **worse**, more jitter) · JA (AVG_N 3: jitter
manageable, kept) · JM (mid-exposure: hard to leave the ship, kept) · JX (JA+JM: same) · JQ
(+ queues 1: solid). **Profile** (`vr-launcher.py` Aircar): `SLAM_CONFIG=P2.toml`,
`SLAM_CORRECTION_AVG_N=3`, `WMR_CAM_TS_MID_EXPOSURE=1`, `VIT_QUEUE_DEPTH=1`, horizon 50,
clamp 150, spread 25.

**What is left, named**: the rotation-onset displacement — yaw/pitch first "moves you off the
seat", then it settles. Offline, the raw VIO under J-class configs does NOT do this (yaw net
5 cm on the recording), so the live displacement is either (a) the prediction layer — the
position freeze + `SLAM_PRED_NECK_ARM_MM` 150 model during the ~75 ms the anchor is stale (a
wrong arm length or centre shows up exactly as "moves then settles"), or (b) the timing
shortfall the sweep left (optimum −5…−10 ms vs the ~2.5 ms mid-exposure recovers → `start_ts`
lags exposure start). Both are cheap to separate next session: one recording under JQ
(button R's env + JQ's), replayed at 0 / −5 / −10 ms → if the raw trajectory is clean while the
wearer felt the displacement, it is (a) and the A/B is `NECK_ARM_MM` 100 / 200 / 0 (env only);
if −5 ms still wins offline, add `VIT_CAM_TIME_OFFSET_NS=-5000000` on top of the mid-exposure
stamp and test worn. If it holds worn, `optical_flow_recall_enable: true`, `vio_marg_lost_landmarks:
false`, `vio_min_triangulation_dist: 0.02`, `vio_max_kfs: 12` and the default recall norms go
into `basalt-g2-config.json` (global — one Dalí 6dof check afterwards). Round N (J + one
refinement each: gate 1 cm, 16 kfs, kf-threshold 0.9, kf every 2 frames, recall on all 4 cams)
and the ±5/10 ms time-offset sweep are queued offline for the margins.

### Teardown SIGSEGVs during the round (JA, JM)

Two of the six sessions did not tear down clean. `coredumpctl info 636130` / `651124` (`Timestamp:`,
matching the kernel `segfault at a8 ... libbasalt.so` journal lines; `coredumpctl list` shows the
dump-completion times 18:34:35 / 18:40:43; re-checked 19:40, read-only): monado-service SIGSEGV at
**18:34:12 -03, pid 636130, core 555 M** — the end
of JA (its CSVs and jack-in log stop at 18:34:12) — and at **18:40:17 -03, pid 651124, 615 M** —
the end of JM (last write 18:40:17). Both cores are present under `/var/lib/systemd/coredump/`.
Same shape in both (`coredumpctl info <pid>`):

- Crashing thread: `wmr_cam_usb_thread` → `libusb_handle_events_completed` →
  `xrt_sink_push_frame` → `t_slam_receive_cam3` → `receive_frame` → `flush_poses` →
  `basalt::vit_implementation::Tracker::pop_pose` (frame #0, in `libbasalt.so`).
- Main thread at that moment: `ipc_server_main_common` → `xrt_system_devices_destroy` →
  `xrt_device_destroy` → `xrt_frame_context_destroy_nodes` → `wmr_source_stream_stop` →
  `wmr_camera_stop` — JM inside `libusb_cancel_transfer`, JA one step later inside
  `os_thread_helper_stop_and_wait`.

That is the known teardown race family — patches 0095/0096 make `wmr_camera_stop` join the USB
thread — with the USB thread still delivering a frame into `flush_poses` evidently after the
tracker is already gone, so it now surfaces in `pop_pose`. JP, JH, JX and JQ tore down clean.
Both crashed sessions were P2.toml without `VIT_QUEUE_DEPTH` (JA = P2 + AVG_N 3, JM = P2 +
mid-exposure; `VIT_QUEUE_DEPTH` appears only in JQ's jack-in log), but JP and JX were P2
without it too and did not crash — a race, not a config. The sessions' data survived: the CSVs
were written up to the crash instant, and their partial last line is not crash damage — 22 of
the 24 CSVs end mid-record (JX's `filtering` / `prediction` happen to stop on a row boundary);
the writer never flushes its final buffer, so drop the last line of all of them regardless.
Low priority unless it starts appearing mid-session; the next step when it does is
`coredumpctl gdb 636130` (or `651124`) + `thread apply all bt`, to see what `pop_pose`
dereferences.

All six sessions' CSVs (`filtering` / `prediction` / `timing` / `tracking.csv`, 127 MB) were
copied 2026-08-28 19:37 from tmpfs to `~/vr/logs/slam-csv/slam-20260828-<HHMMSS>-<file>.csv`
(session → button in that directory's `README.md`; the tmpfs originals were left in place).

### 2026-08-28 late — the interleaved at-rest pair base→P2: first attempt lost to orchestration, rerun detached

The pending "interleaved at-rest pair base→P2" (above: placement and lighting dominate at-rest
stability, so base → candidate → base → candidate back to back is the only fair comparison) was
attempted unattended from the everyday box at 23:12 -03, driving `scripts/soak-variant.py` from a
foreground ssh session inside an agent turn. Leg 1 ran: `base-i1`, `monado-service` pid 685622, the
360 player for its full 900 s (23:12:20 → 23:27:20), RSS 316 → 328 MB, **`Tracker diverged` 104 by
t = 841 s** (vs 7 in the daytime `base` and 36 in `base2` on the 27th — the at-rest trip rate is a
property of the scene and the hour, which is exactly why the pair must interleave). Then the
orchestrating session died (a 600 s harness cap moved the ssh to the background and the agent's turn
ended); SIGHUP reached `soak-variant.py` before its metrics/teardown step, so no `base-i1.json` was
written and `monado-service` sat orphaned for 17 minutes holding the DRM lease, until a later agent
killed it by pid at 23:44 — a kill that tripped the known teardown race (SIGSEGV, core 685622, 32 MB,
the third of the day; "Teardown SIGSEGVs" above). Preserved by hand: `~/vr/logs/soak/base-i1-{run.out,
player.log,jack-in-stdout.log,jack-in.log}` (the jack-in log includes the orphaned minutes: 546
`Tracker diverged` lines over 32 min) and the leg's CSVs as `~/vr/logs/slam-csv/slam-20260828-231216-*`
(4 files). P2 never ran in that attempt.

**Fix, not a retry: `scripts/soak-sequence.sh` (new).** Runs N legs back to back detached from the
caller (`setsid nohup`), one `soak-variant.py` per leg under a per-leg `timeout`, forces the rig down
if a leg leaves `monado-service` or the IPC socket behind, waits 60 s between legs (USB settle),
stops at the first leg without a JSON, sets the dashboard attention flag with abort instructions
(`touch ~/vr/logs/soak/STOP` between legs; `~/vr/jack-in-wayland.sh down` for the running leg),
clears it on any exit, and writes `sequence-<stamp>.done` (`ok` / `failed` / `stopped` / `aborted`).
Relaunched 2026-08-29 00:01:36 -03: `base-i2 → P2-i2 → base-i3 → P2-i3`, 15 min each, variant legs
graded against the preceding base leg (`--baseline`), expected end ~01:09; log
`~/vr/logs/soak/sequence-20260829-000136.log`. The results and the promotion call go below when it
finishes.

**Results (2026-08-29 00:01 → 01:11 -03, `sequence-20260829-000136` + `-001957`).** The first
driver stopped after `base-i2` because it treated `soak-variant.py`'s absolute "0 trips at rest"
rule as fatal (fixed in `1ef9c8b`: only no-JSON / service death / new core / dirty teardown are);
the remaining three legs ran under the second driver with `SOAK_BASELINE=base-i2.json`. Headset
untouched on the desk throughout; 84.2 delivered fps, 0 coredumps, `monado-service` alive at the
end and a clean teardown in every leg. Per leg (15 min; `<tag>.json` + `soak-grade.py`):

| leg | trips | span m | max from start m | lm p50 / p10 | % frames lm<5 | keypoints p50 | frontend p50 / p99 ms | opt p99 ms | patches max | RSS start→end MB/h | RSS steady slope MB/h |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base-i2 | 142 | 13.4 | 7.3 | 0 / 0 | 88.5 | 1866 | 21.9 / 25.6 | 1.6 | 0 | 31 | 77 |
| **P2-i2** | **35** | **7.8** | 5.2 | **22 / 10** | **3.7** | 1503 | 19.4 / 32.0 | 3.4 | 223 k | 421 | 49 |
| base-i3 | 107 | 18.4 | 14.2 | 1 / 0 | 79.5 | 2080 | 23.4 / 27.2 | 1.8 | 0 | 26 | −65 |
| **P2-i3** | **19** | **5.8** | 3.1 | **24 / 13** | **1.8** | 1540 | 19.8 / 32.8 | 3.7 | 208 k | 259 | −229 |

Both interleaved pairs say the same thing. At rest the shipped base config has essentially no
landmarks (p50 0–1; 80–89 % of frames under 5) and trips the session anchor 107–142 times in 15
minutes; P2 keeps 22–24 (2–4 % of frames under 5), trips 4–5.6× less (35 and 19) and halves the raw
span or better (7.8 and 5.8 m vs 13.4 and 18.4). The at-rest trip rate itself drifted between legs
of the same config (142 → 107, 35 → 19) — the hour/scene drift that made interleaving necessary —
but the ordering never flipped. Costs are the known ones: frontend p99 +21–25 % (32.0 / 32.8 ms,
still under the 33 ms camera period; p50 lower than base), backend `opt` p99 1.6 → 3.5 ms, and the
recall patch cache — 208–223 k patches and a start→end RSS growth of 259–421 MB/h over 15 minutes,
while `soak-grade.py`'s steady-state slope is 49 and −229 MB/h: the growth is the cache filling in
the first minutes, 0014/0016/0018's bound holds. `soak-grade.py` labels both P2 legs "UNSAFE" on its
frontend-p99 rule alone (base + 20 %) and lists every other column as "better". (`soak-families.py`
did not recognise the `-iN` tags — its recipe lookup stripped digits, `P2-i2` → `P-i`; fixed the same
night to drop a trailing `-i<n>` and try the exact tag first.)

**Verdict**: P2 is at least as safe at rest as base on every failure criterion (no crash, no core,
clean teardown, same delivered fps) and far more stable in tracking; nothing here argues against
promoting its backend settings into the global `basalt-g2-config.json`. The remaining gate is the one
NEXT-STEP already named — one Dalí 6dof worn run under P2 (the other approved 6dof title) — plus,
for a booth day, a glance at RSS after the first hour. Aircar already runs P2 per-title; Cyberpilot
would inherit it from the global file. Artifacts: `~/vr/logs/soak/{base-i2,P2-i2,base-i3,P2-i3}.*`,
CSVs `~/vr/logs/slam-csv/slam-20260829-00{0144,2005,3730,5454}-*`.
**Added 2026-08-29 05:24**: this pair was run in the dark (before dawn, room unlit) — see the
next section; its trip ratio is a dark-room number, not a promotion argument.

### 2026-08-29 05:24 — Dalí 6dof worn under P2 — the gate run was invalid: the room was dark

The gate named above ran as soon as the wearer was back, then a control — and the pair says nothing
about P2, because both ran in an unlit room before dawn. This section replaces a first draft (never
committed) that read the P2 run's 161 m as P2's landmarks running away; the control run and six
adversarial re-reads of the sources on iashur (`t_tracker_slam.cpp`, the profiles, the archived
CSVs) corrected the mechanism. Numbers are `scripts/worn-grade.py` (new) on the archived
`~/vr/logs/soak/dali-{P2,base}-worn-1-*` unless said otherwise.

**The P2 run (05:24–05:38, `dali-P2-worn-1`).** Dreams of Dalí (591360), 6dof, its own title
profile — constellation off and nothing else: Dalí is the only approved title whose profile carries
no head-prediction knob and no anchor guard, so the application receives Basalt's position
unclamped (one-euro-filtered and gyro-predicted, but `filtering.csv` peaks at 161.2 m exactly where
`tracking.csv` does) — with `SLAM_CONFIG=~/vr/basalt-variants/P2.toml` from the environment
(ambient env wins over the profile by design), launched detached. Room dark. 13.8 min worn.
Wearer, verbatim: *"aparecí muy lejos de todo, aun anda bien. 60fps"*.

- Raw position: within 0.09 m for the first 3 min (headset still on the desk), then 1.6 m
  (180–210 s), **52.9 m** (210–240 s), **151.8 / 161.2 / 72.7 m** (330–420 s), 105–150 m from
  540 s to the end; final row 2.96 m. 5 speed-guard trips.
- Monado log 609 MB / 6.66 M lines: **5 132 012** `d_res_d_p / d_res_d_xi is not valid` and
  **497 513** `det(Q1Jl) == 0, skipping backsubstitution`.
- Frontend p50 24.2 / p99 47.9 ms; backend `opt` p50 12.3 / p99 106.7 ms; camera 18.6–24 Hz in
  minutes 7–9 (frames dropped; 30 Hz otherwise).
- Rendered at **3024×3024**/eye (`comp_swapchain_create_init`, log line 585): Monado's 140 %
  default — Dalí's profile did not carry Aircar's `XRT_COMPOSITOR_SCALE_PERCENTAGE=100`. GPU,
  one `nvidia-smi` grab: 94 % / 245 W of the 250 W limit.

**The control (05:44–05:57, `dali-base-worn-1`).** Same title, same wearer, the global
`basalt-g2-config.json` (base), `XRT_COMPOSITOR_SCALE_PERCENTAGE=100` from the env (rendered
2160×2160, log line 584), the headset worn from the start. Same dark room, and base ran away
*harder*: raw position **37.2 / 27.0 / 43.7 / 65.2 m** in the first four 30-s buckets, 80.6 m
max at t = 373 s, **17 trips** (all before t = 477 s), `d_res` 14 701, `det` 5 240. Wearer: *"veo
una raya de luz nada mas"*. Base ran at `SLAM_THREADS=4` (jack-in's default; nobody sets an
override for Dalí, while `P2.toml` hardcodes `num-threads=6`) — frontend p50 40.9 / p99 47.4 ms
all run long, camera 23–26 Hz all run long; the thread finding below.

**05:52:35 — lights on** (*"hay luz"*) = `tracking.csv` row 11914 (t = 491.2 s from the first
pose, ~505 s from launch). From that row: **0 trips and 0 new `d_res` warnings** for the rest of
the run (`det` continues at a reduced rate and produces no trip). Per-minute peak |p|:
37.2 / 65.2 / 7.8 / 59.2 / 42.9 / 40.3 / 80.6 / 50.6 m (minutes 0–7, dark) → 5.1 / 5.4 / 5.6 /
5.0 / 5.0 / 0.0 m (minutes 8–13, lit). Window 1 (05:52:35–05:54:05): drift 0.97 → 4.01 m over
90 s, recovering while the wearer looked around, 22 Hz. Window 2 (05:54:58–05:56:28): **within
0.19 m for 75 s**, then 1.95 m in the last 15 s = the wearer taking the headset off to type.
Wearer: *"solido, bien. Algun jitter un poco al girar."* GPU, one grab: 73 % / 235 W. No fps
reading from the wearer for this run.

**The at-rest record says the same thing, by hour.** Every at-rest soak on file
(`~/vr/logs/soak/*.json`, all produced by `soak-variant.py` under the same env):

| start (local) | tag | config | lm p50 / p10 | % frames lm<5 | trips |
|---|---|---|---|---|---|
| 08-27 11:40 | record | base | 15 / 6 | 4.9 | 0 |
| 08-27 11:46 | base | base | 16 / 7 | 4.4 | 7 |
| 08-27 12:11 → 16:10 | H G I G2 G3 L K I2 M I3 I4 | daytime variants | 15–161 / 4–93 | 0.0–12.3 | 0–96 |
| 08-27 16:32 | base2 | base | 64 / 7 | 9.2 | 36 |
| 08-29 00:01 | base-i2 | base | **0 / 0** | **88.4** | 142 |
| 08-29 00:19 | P2-i2 | P2 | 22 / 10 | 3.7 | 35 |
| 08-29 00:37 | base-i3 | base | **1 / 0** | **79.6** | 107 |
| 08-29 00:54 | P2-i3 | P2 | 24 / 13 | 1.8 | 19 |

14/14 daytime runs have lm p50 in [15, 161]; 0/4 night runs reach that range; no counter-example
either way. So **the previous section's "P2 trips 4–5× fewer at rest" was measured in the dark**
and is not a promotion argument — it is a dark-room number (P2 degrades less than base in the
dark; that is all it says). Nothing points at a build regression: the raw corner count already
collapses at night (`keypoints_p50` base daytime 2641 vs base-i2/i3 1866 / 2080 — upstream of
anything 0021's queue depth touches), the night legs' frontend is *faster* than daytime base (p50
21.9–23.4 vs 27.9 ms at the same 84–85 fps), `recall_ms` sits at the noise floor
(2e-05…1.2e-04 ms) for base/P2 in every soak, and `VIT_CAM_TIME_OFFSET_NS` is unset everywhere.
But note the gap: **no at-rest soak has ever run in daylight on the current build**
(`libbasalt.so` rebuilt 08-28 18:46 with 0021; the last daytime soak, base2, ended 08-27 16:53),
and the offline replay binary (`build-tools/basalt_vio`, statically linked, built 08-27 21:06)
predates 0021 by 22 h — no replay on disk has exercised it either. One daytime base→P2 at-rest
pair on the current build closes that. (Also: WMR auto-exposure/gain is on, but its live values
print only at `WMR_LOG=trace`, `wmr_camera.c:872` — 0 `exposure|gain` hits in either worn log; a
10–30 s trace capture at session start would show the trail.)

**The numeric warnings, kept as an instrument — with what they measure corrected.** The first
draft read the 5.1 M `d_res` lines as P2's landmarks pulling the state away. Re-counted across
every run that has them:

| run | worn? | room | `d_res … not valid` | `det(Q1Jl) == 0` | trips (guard) | raw \|p\| max |
|---|---|---|---|---|---|---|
| base-i2 / base-i3 | no | dark | 2 / 151 | 2 440 / 2 613 | 142 / 107 (anchor) | 7.3 / 14.2 m |
| P2-i2 / P2-i3 | no | dark | 29 203 / 96 120 | 52 222 / 107 493 | 35 / 19 (anchor) | 5.2 / 3.1 m |
| dali-base-worn-1 | yes | dark → lit | 14 701 | 5 240 | 17 (speed) | 80.6 m |
| **dali-P2-worn-1** | yes | dark | **5 132 012** | **497 513** | 5 (speed) | **161.2 m** |
| Aircar JQ, 08-28 18:47 | yes | lit | 0 | 3 626 | 0 | 1.03 m |
| Aircar JP, 08-28 18:13 | yes | lit | 6 741 | n/c | 1 (anchor) | 2.99 m |
| Aircar RQ / JN0 / JN100, 08-29 | yes | lit | 0 / 288 / 1 252 → 9 697 in 3 min of CPU contention | n/c | 0 / 0 / 0 | n/c |

The reading: base's 80 m dark runaway logged 14 701, Aircar JQ's clean 1.03 m session logged 0
(JP's 2.99 m: 6 741). The 5.1 M count scales with **darkness × P2's recall / 12-keyframe backend**
(same dark room at rest: P2 200–600× base) and — the JN100 incident — with **frontend starvation
from CPU contention** (three verifier agents' `awk` over this very 609 MB log at load 13 on 12
threads: `d_res` 1 252 → 9 697 in three minutes, lit room, wearer *"se siente que a veces tira 0
fps"*). Not with runaway magnitude. So it stays in `worn-grade.py`'s output as a real instrument
for "the frontend is starving (light or CPU)", not as a runaway detector — `worn-grade.py`'s
docstring corrected accordingly. And the trip counts across the two tables are not the same
guard: the soaks run Aircar's env (`soak-variant.py` PROFILE_ENV: anchor 300 cm + quat check), so
141 / 105 / 35 / 19 of those are 0099 session-anchor trips ("3.00–3.03 m from the session
anchor"), + 1 / 2 / 0 / 0 speed trips, + 1 quat-norm trip per leg (that guard is marked not
hardware-validated; the one trip per leg is unexplained — worth a glance), while Dalí's 5 / 17 are
all the 10 m/s speed guard.

**The mechanism, corrected** (sources: `t_tracker_slam.cpp`, `patches/monado/README.md`,
`vr-launcher.py` `TITLE_PROFILES`, the worn CSVs):

- *The position freeze hides nothing.* `SLAM_PRED_FREEZE_POSITION` (0097) only zeroes the
  predicted linear velocity before `m_predict_relation` (`t_tracker_slam.cpp:1687-1690`); the
  delivered position is the last SLAM pose — the runaway itself. The 50 ms horizon (0100) adds at
  most 1.5 m/s × 50 ms = 7.5 cm. Aircar's profile would have delivered the same 161 m.
- *The only clamp is 0099.* `SLAM_SESSION_ANCHOR_RADIUS_CM=300` restarts Basalt when the output
  is >3 m from the session start — it does not move the wearer back (its own comment,
  `:1393-1400`: the carried output "does not move back toward the session anchor by even one
  centimetre") and with the carry on it can re-fire every ~2 s quiet window (at rest: 141 trips at
  "3.00–3.03 m" in 15 min). It bounds by restarting; it is absent from Dalí's profile. Cyberpilot
  (1056970) is **not** a raw consumer: its profile carries the freeze, neck arm 150, spread 50,
  the quat-norm check and the 300 cm anchor — **only Dalí is raw**, and Cyberpilot would take a
  promoted P2 behind the same freeze + anchor Aircar uses.
- *JQ's "sólido" hid nothing.* The 08-28 18:47 JQ session's raw `tracking.csv`: max 1.03 m over
  10.4 min, final 0.09 m, 0 speed trips, 0 anchor trips, 0 `d_res`. All six P2-based Aircar
  sessions of the 28th: raw max-from-start 2.99 / 1.37 / 0.97 / 3.00 / 2.99 / 1.03 m, anchor
  trips 1 / 0 / 0 / 2 / 1 / 0. Basalt did not run away in the lit room under P2.
- *The speed guard.* `SLAM_AUTO_RESET_MAX_SPEED` default 10 m/s, parsed as an integer (`:108`; a
  fractional value silently becomes 0), a consecutive-pose speed test, blind for 2 s after each
  reset. It fired at **every** 10 m/s crossing — all 22 worn trips logged 10.00–10.10 m/s at the
  end of a smooth ramp (the four rows before each read 9.6–9.99 m/s) — just tens of metres late:
  first trip at |p| = **52.9 m** (P2, t = 219 s) / **37.2 m** (base, t = 22.9 s); single ramps
  walked 21.6–149.4 m over 3.9–32.3 s before it fired. The genuinely uncaught case is P2
  t = 480–700 s: max per-frame 5.69 m/s, 0 rows ≥ 6 m/s, |p| 1.7 → 120.4 m, **0 trips for
  220 s**. At its default 10 m/s the speed guard bounds nothing below it. Do not lower it: real
  heads peak 2–3 m/s and raw SLAM velocity has 0.2 % re-localization spikes to 127 m/s (0100's
  README), so the fix is a distance/anchor bound, not a lower speed.
- *What the wearer actually saw.* After every trip the reported position snapped back to
  0.67–4.44 m of the origin in the next accepted row (P2: 52.855 → 0.669 m, 156.236 → 1.221,
  72.665 → 1.717, 150.050 → 2.157, 83.759 → 2.638; base 37.198 → 0.672 … 37.520 → 4.443), while
  the `Reset #N: carrying offset` lines logged deltas of only 0.1–4.4 m — the carry solved its
  offset against a first post-reset pose still at the old raw position, and the fresh tracker's
  next pose teleported home. "Flown out 23–161 m, then snapped back" × 5 (P2) / × 17 (base), the
  post-snap offset growing 0.7 → 3.0 m (P2) / 0.7 → 4.4 m (base) across resets. That is *"aparecí
  muy lejos … aun anda bien"*. It contradicts the carry's "stays continuous" claim (suspect: a
  stale pose left in the VIT pose queue at `tracker_reset`; both queue depths show it) — its own
  open item, not tonight's.

**fps and GPU — what is measured and what is not.** No fps instrument ran in either Dalí run
(both launched in `up` mode, `U_PACING_APP_LOG` unset, 0 `Delivered frame` lines; docs/76: Dalí
had zero recorded fps metrics). "60 fps" is the wearer's reading and the first fps figure the
title has; the base run has none. The 94 % and 73 % are one unarchived `nvidia-smi` grab each
(docs/84 §2: a single grab is meaningless — 4+ samples over 15 s), and the wattage does not
discriminate (245 and 235 W are both within 6 % of the cap). What holds: the util drop is
quantitatively consistent with the 3024²/2160² = 1.96× pixel ratio *if* the app ran ~90 fps at
100 % (60 × 1.96 at 94 % predicts 72 % at 90 × 1.0), and Monado's own pacer held 90 Hz in both
runs (`Fake pacer fell behind` jumps 0–11/min at steady state for P2, 0–5/min for base, the bulk
in minute 0 = loading) — so the 60 fps was app-side; docs/23's desktop-vsync 60 Hz lock is not
excluded by tonight's data. Not a scale-only A/B either (P2 vs base, dark vs part-lit, a
6.66 M-line log vs a 44 KB one). **Power cap, corrected**: the 250 W is deliberate — the runtime
144 W of 08-22 was lost to one of the five 08-25 reboots (a reboot leaves the driver default
240 W) and at **2026-08-26 04:03:47 root ran `vr-power-setup.sh --gpu-limit 100`** (journal),
pinning the card's 250 W max, after stopping `vr-power-watchdog.service` at 04:02:33; already on
record in docs/84 §7 and docs/82 §9. `~/vr/power.conf` says `GPU_LIMIT_PCT=70` (~175 W) and the
watchdog is enabled-but-stopped — the next boot re-applies 175 W in sessions. Two competing
intended caps are on record (144 W in the 08-22 session note vs 70 % in `power.conf`);
reconciling them needs the user/root, not this session.

**The thread finding (per-stage split of the worn `timing.csv`).** Base's 40.9 ms worn frontend
(22–23 ms at rest) is the **tracking** stage — the one `tbb::parallel_for`'d stage, the one that
scales with `SLAM_THREADS` (T235: 24.6 → 13.4 ms at 4 → 8 threads) — and base ran at 4 threads
while P2 got 6 from `P2.toml`:

| p50 / p99 ms | base worn (4 threads, 18 905 rows) | P2 worn (6 threads, 23 176 rows) |
|---|---|---|
| pyramid | 0.74 / 1.47 | 1.10 / 2.81 |
| **tracking** | **20.42 / 28.53** | **12.36 / 30.16** |
| recall | 0.05 / 0.13 | 0.14 / 1.47 |
| detection cam0 | 2.35 / 3.33 | 1.29 / 3.05 |
| matching | 6.36 / 8.38 | 1.63 / 5.79 |
| detection cam_i | 10.78 / 12.35 | 7.04 / 12.24 |
| filter | 0.15 / 0.31 | 0.62 / 11.70 |
| frontend total | 40.90 / 47.45 | 24.24 / 47.87 |

Detection is sequential (`keypoints.cpp`) and cannot grow with a thread change; its difference
tracks grid 30 vs 40. `monado-service` CPU 537 % (P2) vs 367–373 % (base) = 1.44–1.46×, the 6:4
thread ratio (1.5×) — pool size, not per-frame work. Base's frontend was flat 38.0–43.5 ms p50
across all 13 minutes and unchanged by the lights (p50 41.13 before row 11914, 39.63 after), so
low-light image processing is not the cost driver either. Consequence: the worn base-vs-P2 pair
is not a config comparison at all (dark room + 4-vs-6 threads + 140-vs-100 % scale), and Dalí's
profile now carries `SLAM_THREADS=6` (below). For "what does grid 40 alone buy", the clean number
stays Round P's J → P2 (−18.3 / −22.2 / −26.1 ms p50/p90/p99, drift unchanged).

**Decision: P2 is NOT promoted into the global `basalt-g2-config.json` — the gate was not
passed, not failed.** Both configs ran away in the dark and base was clean once lit; no lit-room
Dalí minute under P2 exists, so the data do not discriminate. And the booth does not need the
promotion: Dalí on base + light reads *"solido"*; Aircar keeps P2 per-title (validated worn,
including today's lit-room RQ / JN0 / JN100 / JN200 — 0 trips); the promotion would only matter
for Cyberpilot, which is not in the lineup. A valid gate = one Dalí 6dof worn run under P2 in a
**lit** room, ~10 min, at scale 100 — optional, whenever a wearer slot is spare.

**Profile changes made (`vr-launcher.py` `TITLE_PROFILES["591360"]`)**:
`XRT_COMPOSITOR_SCALE_PERCENTAGE=100` (same rationale as Aircar's 2026-08-27 change; the render
targets are the hard evidence, the GPU figures one grab each; it needs a worn re-confirmation plus
a first Dalí fps number before it counts as validated — the 2026-08-26 approval ran at 140 %) and
`SLAM_THREADS=6` (the thread finding above; Aircar already carries it). **Not** P2. Considered,
not applied: `SLAM_SESSION_ANCHOR_RADIUS_CM` for Dalí — it would have bounded tonight's runaway to
3 m restarts, but the wearer would still not have seen the scene; the real fix is light.

**Lighting rule for 6dof titles: the room must be lit.** `scripts/light-preflight.sh` (new,
first run 2026-08-29 07:07, detached: verdict OK in a lit room -- landmarks p50 137 / p10 0, keypoints p50 3052, 15.2 % of frames under 5 landmarks, 5 session-anchor trips (the base config random-walks 3 m at rest even in light), 1800 frames in 60 s, clean teardown, 0 cores, attention flag cleared; the only rough edge is the player log filling with IPC errors because jack-in down kills Monado before hello_xr exits) brings Monado + the 360 player up with the headset on the desk for `SECONDS`
(default 60), parses Basalt's per-frame landmark counts with `soak-variant.py`'s own `parse_vit()`
under the same env as the soak baselines, and grades: **DARK** lm p50 < 5 (or no frames), **DIM**
5–15, **OK** ≥ 15 — calibrated strictly between the dark points (0 / 1) and the daytime base
points (16 / 64); DIM is an unmeasured buffer, not a data band. It reports
`pct_frames_lt5_landmarks` and the trip count alongside so a human can catch what the median
hides, and it grades the *base* config (the most starvation-sensitive one on file): OK/DIM
describes base, DARK is a hard stop for every profile. Output
`~/vr/logs/preflight/light-<stamp>.{log,json,done}`, last log line `light preflight end:
status=… verdict=…`; sets/clears the dashboard attention flag. Launch (the output directory must
exist before the redirect): `mkdir -p ~/vr/logs/preflight && cd ~/Documents/reverb-g2 && setsid
nohup scripts/light-preflight.sh 60 > ~/vr/logs/preflight/launch.out 2>&1 < /dev/null &`. Open:
the daytime base→P2 at-rest pair on the 0021 build (above).

**Side findings from the same hours.**

- The manual dashboard relaunch of 2026-08-28 23:05 (pid 683648/683653) had inherited an envfile
  without `DISPLAY`/`WAYLAND_DISPLAY` (only DBUS) — its demo buttons' `steam -applaunch` would not
  have reached the Steam client. Fixed 05:26: killed, `systemctl --user start
  status-dashboard.service` (the unit was already `enabled`; the user manager's environment
  carries `DISPLAY=:1 WAYLAND_DISPLAY=wayland-0 XAUTHORITY`); unit pid 716015 has them,
  `/api/status` ok, and the RQ/JN buttons then launched Aircar via
  `POST /api/action/variant-1073390-<TAG>`. `pmadminka` showed attached/active all session (the
  08-28 heartbeat failures did not recur; not investigated).
- 05:42, one more `pgrep -f` self-match: a cleanup line `for p in $(pgrep -f
  "DreamsOfDali|SteamLibrary/.*591360"); do kill $p; done` matched the ssh shell carrying that
  pattern and killed it (exit 255); nothing else harmed. Rule: bracket the pattern
  (`pgrep -f "Dreams[O]fDali"`), or `pgrep -x`, or Steam's reaper line
  `pgrep -f "AppId=107[3]390"` (stable while the game lives). Same class as the 22.5 h
  demo-recorder incident (docs/88). `CLAUDE.md` updated.
- **06:24–06:27, workflow contention while the wearer was in JN100**: three verifier agents ran
  `awk` over the 609 MB `dali-P2-worn-1` log (one awk at 40 % RAM ≈ 13 GB) plus `gzip -cd`; load
  13 on 12 threads; wearer: *"se siente que a veces tira 0 fps"*. Killed, workflow paused; `d_res`
  1 252 → 9 697 inside those minutes. **Rule: no heavy analysis on iashur while a wearer session
  is live; never scan the raw multi-hundred-MB Monado logs with `awk` associative arrays — use the
  `*-jack-in-filtered.log` or `zcat … | grep -c`.** In `CLAUDE.md`.
- One teardown SIGSEGV, 06:34:04, pid 731059 (the JN100 `monado-service`, on kill) — the
  `pop_pose` family above; `coredumpctl info 731059` when someone looks. Rig left down after
  every run; no other cores.

### 2026-08-29 06:08 — The 10-minute wearer slot: RQ recorded, neck arm 0 ≈ 100 < 150 < 200

Lit room throughout (the lights stayed on after 05:52), P2 backend + the JQ stack, all four runs
from the dashboard's round-7 buttons (`POST /api/action/variant-1073390-<TAG>`), rig down between
them. 0 speed/anchor trips in all four.

**RQ (06:08–06:13)** — JQ + `EUROC_RECORD` to `/mnt/vrtmp/euroc-yaw2_20260829060819`,
`VIT_DUMP_CALIB=~/vr/logs/calib-g2-yaw2.json`. `yaw-protocol-voice.py` started 06:09:06 on the
headset sink; phase boundaries (s from protocol start): intro 0, yaw 35.5, settle-1 69.0, pitch
79.2, settle-2 108.0, roll 118.2, settle-3 147.8, free 157.9, end 222.5. **0 trips, 0 `d_res`**
for the whole session. Recording 6.8 GB (1.5 GB/min — the recorder runs as long as Monado lives,
so `~/vr/logs/rq-finish.sh` auto-stopped the session 30 s after the voice ended), archived with
the calib dump, the voice log, the Monado log and the SLAM CSVs to
`/mnt/videos/euroc/euroc-yaw2_20260829060819` (root fs at 82 %, `/mnt/videos` 197 GB free; the
tmpfs copy is the one to drop before a reboot). The wearer did not report RQ's feel separately.

**`scripts/euroc-phases.py` (new)** writes the `phases.json` that `replay-phase-slice.py` reads
(`protocol_start_t_ns` + `phases[].t_ns`) from the voice log. Default `--method clock`:
`t_ns = unix × 1e9 − (CLOCK_REALTIME − CLOCK_MONOTONIC)` read live — same boot only (the boot_id
is recorded and it refuses a voice log that predates the boot). Validated against the 27th's
hand-made `phases.json`: every phase within −0.72 s, constant — the 27th's mtime method carried
the PNG writer's lag. `--method mtime` = the 27th's method, valid only on original (uncopied)
files. Usage: `euroc-phases.py --dataset DIR --voice ~/vr/logs/yaw-protocol-<stamp>.json
[--out DIR/phases.json] [--check DIR/phases.json]`.

**The neck-arm A/B (hypothesis a)**, the same fast yaw each time:

- **JN0** (06:14–06:18, `SLAM_PRED_NECK_ARM_MM=0`): *"bien! Diría que el tema de movimiento
  rápido me mueve de lugar mucho menos. hay un poco de jittering al mirar la cabina de cerca.
  Pero fuera de eso bien"*. 0 trips, `d_res` 288.
- **JN100** (06:19–06:31, 100 mm): *"igual parece a la vez anterior"* / *"muy similar, avanza"*
  — same as JN0. 0 trips. (The contention incident of the previous section fell inside this run.)
- **JN200** (06:32–06:37, 200 mm): *"la deriva es claramente mayor ahora"* — worse than 150.

**Order: 0 ≈ 100 < 150 (JQ) < 200.** Hypothesis (a) — the neck model over the ~75 ms stale anchor
— is confirmed in the direction "less arm, less displacement"; the 150 mm guess of 08-26 was
over. **Profile change: `SLAM_PRED_NECK_ARM_MM` 150 → 100** in Aircar's profile
(`vr-launcher.py` `TITLE_PROFILES["1073390"]`) and in the dashboard's `JQ_ENV` — the same feel as
0 without the near-field cockpit jitter the wearer noted at 0; a reversible one-liner; the wearer
had not chosen between 0 and 100 when this was written. Cyberpilot keeps 150 (not re-tested).

**RQ replay (P2, `~/vr/logs/rq-replay.sh` + two reruns; phase slices in
`~/vr/logs/replay-phase-yaw2.jsonl`, "rot-sum" = yaw + pitch + roll max-distance-from-phase-start):**

| shift | rot-sum | yaw / pitch / roll | settles | max 1-s disp | note |
|---|---|---|---|---|---|
| 0 ms, run 1 | **1.23 m** | 0.63 / 0.39 / 0.21 | 0.02–0.03 | 0.69 m (5/607 windows > 0.5) | clean |
| 0 ms, rerun | 1.72 m | 1.13 / 0.38 / 0.21 | 0.02–0.03 | 0.68 m (7/607) | run-to-run noise (`deterministic=0`, 6 threads) |
| −10 ms | 4.04 m | **3.30** / 0.51 / 0.23 | 0.02–0.03 | 0.95 m (11/607) | yaw 3–5× worse |
| −5 ms, run 1 | diverged | 4 383 / 6 517 / 10 059 | 1 680–4 165 | 1 707 m | |p| 157 m by t = 20 s, 116 km at the end |
| −5 ms, rerun | diverged | 2 072 / 11 665 / 27 834 | 1 744–12 399 | — | clean for 40 s (max 1.1 m), then 228 m at 40–60 s, 249 km at the end |

The −5 ms blow-up is **reproducible in outcome, not in onset** (t ≈ 6 s vs 40–60 s, both inside the
still intro phase), so it is not the untrimmed-dataset artefact first suspected (the rerun ran 40 s
clean on the same untrimmed copy) and not a timestamp coincidence (0 camera stamps equal an IMU
stamp in any shift; nearest gap 0.4–0.9 µs in all three). What it is exactly is open — a
first-frames/initialisation sensitivity of P2's recall backend to that particular offset is the
best guess — but the decision does not need it: this recording already carries the mid-exposure
camera stamp (0101 is part of JQ), so any further negative shift *overshoots*: −10 ms triples the
yaw error and −5 ms is unstable. On the 27th's recording (no 0101) −5/−10 ms had helped; 0101
banked that gain. **JQT (`VIT_CAM_TIME_OFFSET_NS=−5 ms` on top of 0101) is not justified — not
run, and JQ keeps 0101 without an extra offset.** Hypothesis (b) is closed for this stack; the
residual is hypothesis (a)'s (the neck arm, above).

Two tool notes from the sweep: `replay-basalt-variants.py` died in its log parser on a fused
`vit_` line (`'0.730290.059371'`, two threads' output interleaved) after a complete 4.5-min replay
— it now skips the field the way `soak-variant.py`'s `parse_vit()` does; and `build-tools/basalt_vio`
(statically linked, built 08-27 21:06) still predates Basalt 0021 — every replay above ran the
pre-0021 frontend queue; rebuild it alongside `libbasalt.so` before the next sweep so the two
cannot diverge silently.

### 2026-08-29 13:55 — the daytime at-rest pair base→P2 on the current build: A1's gap closed, and the warning counts re-read

`scripts/soak-sequence.sh 15 base-i4 P2-i4=~/vr/basalt-variants/P2.toml`, detached 13:55–14:29, lights on plus
daylight, headset on the desk, nobody in the room; both legs `ok`, 0 cores, clean teardowns, rig down at the
end. Same instrument as the night pair (`soak-variant.py` under Aircar's env: 0099 anchor 300 cm, so "trips"
are session-anchor restarts), graded with `soak-grade.py base-i4 P2-i4`:

| leg | lm p50 / p10 | % frames lm<5 | trips | span m | max 1 s m | keypoints p50 | frontend p50 / p99 ms | opt p99 ms | patches max | RSS start→end MB/h | RSS steady slope MB/h | `d_res … not valid` | `det(Q1Jl) == 0` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base-i4 | **143 / 35** | 7.0 | 44 | 5.54 | 3.52 | 3140 | 33.4 / 39.5 | 18.6 | 0 | −6 | −173 | 45 245 | 9 765 |
| **P2-i4** | **190 / 71** | **0.7** | **5** | 4.97 | 3.03 | 1851 | **22.8 / 33.2** | 24.1 | 198 k | +1129 | −30 | 57 008 | 162 737 |

- **A1's open item is closed.** The current build (`libbasalt.so` with 0021, 08-28 18:46) in a lit room gives
  the base config **143 landmarks p50 — the best at-rest base number on file** (08-27 daytime: 16 / 64; the
  night pair: 0 / 1). 0021 was not the night's problem; darkness was. Trips at rest are a scene/hour
  number for base (7 / 36 / 44 by day, 142 / 107 at night), so the ordering base→P2 is what carries
  information: **44 → 5 in light**, 142 → 35 and 107 → 19 in the dark.
- **P2 in light**: 9× fewer anchor trips than base, more landmarks (190 / 71), fewer frames under 5
  (0.7 %), and a *cheaper* frontend — p50 22.8 vs 33.4 ms — because grid 40 cuts detection where features
  are plentiful (keypoints 1851 vs 3140), the cost that Round P measured offline. Patches 198 k (within
  0014's bound, same as the night's 208–223 k); RSS start→end +1129 MB/h is the recall cache filling
  from a rich scene in the first minutes — the steady-state slope is −30 MB/h (base −173). `soak-grade.py`
  flags P2 "UNSAFE" on that raw RSS delta, as it did at night; the slope is the number to read, and a
  booth day still wants the glance at RSS after the first hour.
- **The numeric warnings, re-read once more — they do not measure darkness.** Base at rest in light
  logged **45 245** `d_res` lines against **2 / 151** in the dark: the count tracks how many landmarks
  the backend is optimising (143 vs 0), not how starved it is. What is P2-specific is `det(Q1Jl) == 0`
  (162 737 vs 9 765 = 17× in light; 20–40× in the dark) — the recall's re-observed landmarks reaching
  the solver with singular Hessian blocks. The 5.1 M of the dark Dalí run therefore reads as recall
  thrash + resets, and the JN100 contention bump (1 252 → 9 697 in 3 min) as extra solver churn under
  dropped frames. **Use both counts only as same-condition A/B columns** (same room, same light, same
  load); a raw count on its own says nothing. `worn-grade.py`'s docstring says so now.
- What this does *not* change: P2 is still not promoted to the global file. The at-rest instrument now
  argues for it in light as it did in the dark, but the gate is the lit-room Dalí worn run under P2
  (the only raw-position title), and the booth runs Dalí on base with light. Cyberpilot is the only
  title that would inherit a promoted P2, behind Aircar's freeze + anchor.

Artifacts: `~/vr/logs/soak/{base-i4,P2-i4}.*`, `sequence-20260829-135503.{log,done}`; CSV copies next to them.

### 2026-08-29 14:40 — the gate, this time in a lit room: P2 worn in Dalí still jumps metres — not promoted

Dashboard action `gate-591360-P2` (Dalí 6dof, own profile — scale 100, 6 threads, constellation off, no
head-prediction/anchor knobs — plus `SLAM_CONFIG=P2.toml` from the env), daylight + lights on, worn from the
first second, 9.5 min, `~/vr/logs/soak/dali-P2-lit-1-*`. Wearer: *"listo, jugué un poco. Parecido a como
venía"*, then: *"aparecí unos metros a la derecha, pero pude jugar igual. No sé si tiene reset de posición,
no uso controles, solo casco. Girando lento casi perfecto, rápido se siente un jitter como siempre"* — the
6.6 m step and the carried 8 m offset are the "unos metros a la derecha" (Dalí is gaze-only, no recentre;
its open scenes hide a few metres where this morning's *"aparecí muy lejos"* took 100+); the fast-turn
jitter is the known rotation-onset residual, the same one Aircar's neck-arm round is chasing.

| | `dali-P2-lit-1` (P2, lit) | `dali-base-worn-1`, lit part (base, this morning) |
|---|---|---|
| landmarks p10 / p50 / p90 | **73 / 887 / 1584** — no starvation | (no `vit_` lines) |
| raw position | 0.13 m (0–15 s) → **6.6 m at 30–45 s**, held ~45 s → **30 → 38.6 m at 90–120 s**, then ~8.7–8.9 m for 8 min | within 0.19 m for 75 s, 0.97 → 4.0 m while recovering (4 min sample) |
| guard | 1 speed trip at t = 107 s; reset carried **8.1 m and −13.3° of yaw** | 0 |
| frontend / backend p50 (p99) | 31.3 (45.6) / 24.9 (51.8) ms, camera 30 Hz throughout | 39.6 (48.2) / — ms, 23–26 Hz (4 threads) |
| `d_res` / `det(Q1Jl)` | 30 996 / 41 254 — all logged around the two jumps, flat afterwards | 2 249 after the lights came on |
| GPU (single grabs) | 98 / 93 / 73 % at 235–248 W, scale 100 | 73 % / 235 W |

So the dark room was the reason for *this morning's* 161 m, but it was not the only thing wrong with P2 on
a raw-position title: with 887 landmarks in view it still produced a 6.6 m step at 30 s and a 38.6 m
excursion at 107 s, both while the wearer was simply looking around, and the reset-offset carry then
parked the wearer 8–9 m from the origin with a 13° yaw error for the remaining 8 minutes. The daytime
at-rest pair (previous section) still favours P2 at rest — 5 trips vs 44 — and Aircar's wearer sessions
under P2 are clean because the 3 m session anchor and the seated cockpit bound it; Dalí has neither and
the booth runs it standing, looking around.

**Gate result: not passed. P2 stays Aircar-only; Dalí keeps the global base config.** The only fair
follow-up left is a 10-minute base control in the same lit room (this morning's lit base segment is
4 minutes of a recovering estimator) — optional; Dalí on base is what the 2026-08-26 approval and this
morning's lit segment already validated. Where the two jumps come from (recall re-observations at 12
keyframes on a standing wearer? the 2 cm triangulation gate?) is a P2-backend question for the Aircar
investigation, not a booth blocker. GPU at scale 100 still reads 73–98 % in Dalí — measure fps
(`app-fps.sh`/`frame-pacing.sh`) before treating scale 100 as the fix for the wearer's "60 fps".

### 2026-08-29 14:58 — the base control in the same light: base jumps too — the early excursion is Dalí-worn, not P2

Approved demo action `demo-591360-6dof` (global base config, scale 100, 6 threads), same lit room, worn from
the first second, 6.8 min, `~/vr/logs/soak/dali-base-lit-1-*`. Wearer: *"jugué, listo. Aparecí más centrado,
se siente muy parecido"*.

| | base, lit (`dali-base-lit-1`) | P2, lit (`dali-P2-lit-1`) |
|---|---|---|
| raw position, first 3 min per 15 s | 0.1 0.4 1.6 **24.5 38.8** 1.5 1.5 1.6 1.6 1.9 1.9 1.9 m | 0.1 2.0 6.6 6.4 6.4 6.4 **30.0 38.6** 8.7 8.9 8.8 8.7 m |
| max / final | 38.8 m at t = 68 s / 1.7 m | 38.6 m at t = 107 s / 8.7 m |
| speed trips → carried offsets | 3 → 0.4, 0.7, 1.4 m | 1 → **8.1 m + 13.3° yaw** |
| frontend / backend p50 (p99) ms | 34.9 (41.6) / 9.6 (28.1), 30 Hz | 31.3 (45.6) / 24.9 (51.8), 30 Hz |
| `d_res` / `det(Q1Jl)` | 242 / 702 | 30 996 / 41 254 |
| GPU (single grabs, scale 100) | 80–99 % / 232–246 W | 73–98 % / 235–248 W |

**Both configs run ~40 m away within the first two minutes of a worn Dalí session in a lit room, then
settle.** The at-rest instrument never saw it because the headset starts still on the desk; this
morning's lit base segment never saw it because it began in minute 8 of a session. The shape — a
rotation-only start (the wearer looks around), then a step of metres at the first real translation, then
stability — is textbook monocular-VIO scale unobservability under pure rotation: the scale snaps when
parallax finally arrives. (Aircar sits behind the 3 m session anchor and a seated cockpit; Cyberpilot the
same; Dalí runs raw and standing.) The wearer noticed neither run's 38 m ("Dalí's open scenes"), only
the residue: P2's reset happened to carry 8 m + 13° (*"unos metros a la derecha"*), base's three carried
0.4–1.4 m (*"más centrado"*). One sample each — the carry size is where the reset caught the ramp, not a
config property.

**What this changes.** The 14:40 section's "P2 still jumps metres" stands as a fact but not as a
P2-specific one; the gate is *undecided* rather than failed — and the decision does not move: P2 stays
Aircar-only (nothing to gain for the booth, Cyberpilot not in the lineup), Dalí keeps base. What the
booth needs is a bound on the start-of-session excursion, and there are two cheap levers, both
untested on Dalí as of writing:

1. **Procedure**: headset on the desk, still, until the title has loaded (Monado initialises Basalt at
   rest, as in every soak); only then the guest puts it on. The launcher already brings Monado up before
   `steam -applaunch`, so this is a queue rule for the operator, not code.
2. **`SLAM_SESSION_ANCHOR_RADIUS_CM=300` in Dalí's profile** (0099, the guard Aircar and Cyberpilot
   already run): bounds any excursion to a 3 m restart instead of 38 m. With the carry it still parks the
   wearer up to 3 m off — the yaw-carry error seen today (13°) is the thing to watch. Dashboard action
   `test-591360-anchor` (added now) runs Dalí on base with the anchor from the env for a worn check.

Also: Dalí at scale 100 still reads 80–99 % GPU on single grabs in both runs — the "60 fps" question is
not answered by the scale change; measure with `app-fps.sh`.

### 2026-08-29 15:02 — the anchor test: 3.45 m instead of 38, applied to Dalí's profile

Action `test-591360-anchor` (global base, scale 100, 6 threads, `SLAM_SESSION_ANCHOR_RADIUS_CM=300` +
`SLAM_QUAT_NORM_CHECK=1` from the env), lit room, **headset still on the desk for the first ~60 s** (the
title had loaded at 45 s), then worn, 4.8 min, `~/vr/logs/soak/dali-base-anchor-1-*`. Wearer: *"listo,
aparecí un metro o dos más cerca de lo que hacía falta, un poco más a la derecha de lo necesario también,
pero se puede iniciar igual. se juega muy similar"*.

| | base + anchor (`dali-base-anchor-1`) | base raw (`dali-base-lit-1`) | P2 raw (`dali-P2-lit-1`) |
|---|---|---|---|
| raw position, first 3 min per 15 s | 2.8 3.0 3.0 0.8 1.0 3.0 **3.4** 1.2 1.6 1.6 1.5 1.7 m | 0.1 0.4 1.6 24.5 **38.8** 1.5 … | 0.1 2.0 6.6 … 30.0 **38.6** 8.7 … |
| max / final | **3.45 m / 0.50 m** | 38.8 / 1.7 m | 38.6 / 8.7 m |
| guard trips → carried offsets | 6 anchor + 1 quat → 0.02–0.21 m, yaw ≤ 0.02° | 3 speed → 0.4–1.4 m | 1 speed → 8.1 m + 13.3° |
| frontend / backend p50 ms | 34.9 / 9.1 | 34.9 / 9.6 | 31.3 / 24.9 |

Two things worth noting. The base config random-walks to the 3 m radius **within the first 15 s even
on the desk** (2.8 / 3.0 / 3.0 m at rest — the daytime soak's "max 1 s displacement 3.5 m"), so "headset
still on the desk" does not by itself give a clean origin; what it gives is a Basalt initialised at rest.
And the anchor's resets are nearly free here — 0.02–0.21 m carried, no yaw — where the speed guard's
reset in the P2 run carried 8 m and 13°: catching the ramp at 3 m instead of at 10 m/s is the whole
difference. The wearer's "1–2 m off at the start" is the sum of the carried offsets plus the random
walk; a recentre at title start would remove it (Dalí has none; a Monado-side "re-anchor on first
xrBeginSession" is the natural follow-up, not tonight's).

**Applied**: `TITLE_PROFILES["591360"]` now carries `SLAM_SESSION_ANCHOR_RADIUS_CM=300` and
`SLAM_QUAT_NORM_CHECK=1` (reversible; deployed, `deploy-check.py` clean). Operator rule for the booth
queue: **the headset stays still on the desk until the title has loaded; only then the guest puts it on.**
`worn-grade.py` now labels its trip count as what it is (speed + anchor + quat, all logged as
`Tracker diverged`).
