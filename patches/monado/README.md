# Monado patches

Twenty-three patches on top of Monado `main` @ `735e29e4e` (the SHA `bootstrap-lab.sh sources`
pins) — **but two of them (0016, 0017) do not apply; read the box further down before
trusting this series.** The first ten are the linear form of four independent MR branches prepared for
upstreaming — see [`docs/18-monado-upstreaming.md`](../../docs/18-monado-upstreaming.md) for
the branches, the review that shaped them, and the submission runbook. 0011 came later
(2026-08-06) and isn't part of that grouping yet.

**Known sync gap (2026-08-11):** the lab machine's actual `g2-constellation-x11kde` branch
has real committed history well past what's exported here — at least a "fuse constellation
position into the controller's output pose" step and several freshness/clock-domain fixes
on top of it, referenced by their own commit messages as "0017" work. **That "0017" is a
different fix on a different checkout than this directory's `0017`** (the container_of bug
fix below, done on the everyday-system checkout) — the numbering collided by coincidence,
not by design. Don't assume this directory's numbering reflects the full state of the lab
branch; check `git log` there before assuming something past 0016 doesn't exist.

| patches | MR branch | what |
|---|---|---|
| 0001–0004 | `wmr-hid-resilience` | tolerate transient HID errors: companion read loop, fw-read retry with reply validation, bounded status wait, BT thread error cap |
| 0005–0008 | `wmr-controller-input-fixes` | G2 squeeze click, G2 haptic output name, input timestamps + misc, opt-in `WMR_STICK_DEADZONE` |
| 0009 | `wmr-camera-stream-toggle` | `WMR_CAMERAS=0`: orientation-only, cameras never start |
| 0010 | `steamvr-drv-origin-rpath` | `$ORIGIN` runtime path on `driver_monado.so` for pressure-vessel |
| 0011 | (unfiled) | G2 driver was missing the native `microsoft/motion_controller` binding remap — every binding under that profile silently failed to resolve, not just one input. See `docs/03-controllers.md` |
| 0012 | (unfiled, in progress) | First step of real 6DoF controller tracking: link `constellation` (the optical LED tracker rift/pssense already use) into `drv_wmr`. Build-only, no behavior change — nothing calls into it yet. See `docs/03-controllers.md` |
| 0013 | (unfiled, in progress, physically verified 2026-08-09) | Second step of 6DoF: split controller-tracking frames (frametype `0x2`) per camera in `wmr_camera.c` (previously dropped) and run LED blob detection on them via `t_rift_blobwatch`, visualized in a new "Controller Blob Cam N" debug GUI panel per camera. Still debug-only — no `t_constellation_tracker` wired up yet. Confirmed live with `XRT_DEBUG_GUI=1`: blob boxes track the LED ring in real time while moving a controller, and SLAM/controller rotation showed zero regression. See `docs/03-controllers.md` and the plan referenced from `NEXT-STEP.md`. |
| 0014 | (unfiled, in progress, verified live 2026-08-11) | Third step of 6DoF: `WMR_CONSTELLATION_CONTROLLERS` (default off) creates a `t_constellation_tracker` with one camera mosaic over the headset's tracking cameras and feeds 0013's blobs into it. The mosaic gets a *tracking source* reporting the headset's own pose rather than the fixed room pose a Rift sensor gets — the WMR cameras move with the head. No devices registered yet, so nothing solves and no pose changes — confirmed live: SLAM pose rate 30.1 Hz without it, 30.0 Hz with it. See `docs/pruebas.jsonl` T146. |
| 0015 | (unfiled, superseded by 0016) | Sets exposure/gain for the controller-tracking camera frames, which live in separate hardware slots from the SLAM ones, and gates the whole constellation path behind `WMR_CONSTELLATION_CONTROLLERS`. The controller frame stream is black on a G2 even with the LEDs plainly lit; this alone did not fix it (slot mapping and values were both wrong) — see 0016. |
| 0016 | (unfiled, verified live 2026-08-11, everyday system) | Corrects 0015's two wrong guesses (slot offset `+tcam_count` → flat `+2`; exposure/gain `400/1` → `6000/100`) and adds a clock-domain fix (`+cam_hw2mono`) for constellation frame timestamps. Confirmed live: `Controller Blob Cam N` panels went from solid black to real tracked LED blobs, and RANSAC-PnP started recovering real device poses (2000+ consecutive samples, reprojection error 0.04–0.10px). Left `get_tracked_pose` still reporting `position_tracked=false` due to what looked like a device-specific timestamp bug — see 0017, it wasn't device-specific. |
| 0017 | (unfiled, verified live 2026-08-11, everyday system) | Fixes a real bug in 0016's own `receive_ctrl_cam`: `container_of` was applied to an array element (`&ws->ctrl_ts_fix_sinks[i]`) instead of a whole-struct field, which only resolves correctly for `i==0` — for every other camera index it silently read garbage instead of the real `cam_hw2mono`/downstream sink. What looked like a "works for controller A, not B" bug was actually "works for physical camera 0, silently broken for 1–3," coincidentally correlated with which controller each camera happens to see most. Fixed with a small per-camera wrapper struct so `container_of` recovers the right instance regardless of array index. Confirmed live twice (incl. a full clean rebuild): `pushPose`'s sample timestamp now lands 5–40ms behind the host clock for every device/camera combination, and running `hello_xr` shows both controllers reporting `position_tracked=true` consistently. See `docs/pruebas.jsonl` T151. This closes out 6DoF constellation controller tracking end to end. **Does not apply to this series — see the box below.** |
| 0018 | (third-party: Project-VR) | Sets `screens[0].nominal_frame_interval_ns = 1e9/90` on WMR HMDs. `u_extents_2d_split_side_by_side()` leaves it at 0, so a downstream consumer computes refresh = 1/0 = infinite and falls back to 60 Hz, mis-pacing frames against the 90 Hz panel. **Scope caveat, from the commit message itself: the consumer it names is the SteamVR driver bridge**, not the native OpenXR path — whether its absence is visible through `jack-in-wayland.sh`/`hello_xr` or xrizer has **not** been measured, so don't claim it either way. Authored by Ashish Kumar Singh (`bf3a2e4b9`), lived only as a README footnote until T157. Applies clean on top of 0015. |
| 0019 | (unfiled, instrumentation) | Environment knobs for two pieces of SLAM instrumentation that were previously reachable only through the debug GUI: `EUROC_RECORD=1` / `EUROC_RECORD_PATH=<dir>` start the EuRoC dataset recorder from process start, and `SLAM_FEATURES_ENABLE=1` turns on the pose-features tracker extension so `t_slam` writes `features.csv` alongside the other CSVs. Defaults unchanged, so nothing runs that did not run before. This is the patch that made the 2026-08-12 6DoF investigation measurable — `features.csv` showed Basalt holding a mean of 0.0–0.9 landmarks per camera with visually perfect images, which located the failure in the visual front-end instead of leaving "the pose runs away" as a symptom. See `docs/pruebas.jsonl` T162. Applies on top of 0018. |
| 0020 | (unfiled, verified live 2026-08-12) | `SLAM_CONFIG_PIPELINE_ONLY=1` makes a `SLAM_CONFIG` file mean "pipeline settings only" and keeps sending the driver's calibration, instead of the current all-or-nothing behaviour where passing a file requires re-expressing the whole device calibration in the tracker's own format. Default off. Needs `patches/basalt/0001` on the other side (Basalt's `--cam-calib` stops being required). This is what made the G2 6DoF config sweep possible: one line per variant instead of a project, and it located the failure — Basalt's default detection settings are too sparse for the G2's fisheye cameras, `grid_size 30 / num_points_cell 3 / min_threshold 3` takes static drift from thousands of metres to 0.72 m at 60 s. See `docs/pruebas.jsonl` T162. Applies on top of 0019. |
| 0021 | (unfiled, verified live 2026-08-12) | Drops camera frame bundles whose timestamp is not greater than the last accepted one, instead of warning and pushing them to the tracker anyway (which is what the code did). Basalt aborts the whole process on those (`sqrt_keypoint_vio.cpp:311` → SIGABRT), and it killed `monado-service` three times in one session with three unrelated triggers: disk I/O from the EuRoC recorder, CPU load from denser detection, and a `CamerasDmaReset`/`DMA CMT ERR` burst from the headset itself. Dropped as a whole bundle because the tracker requires all cameras in a bundle to share a timestamp. **Measured after the fix: the guard fires ~195 times per session, 157 of them dropping a single bundle (max 5), with backwards jumps of 10–106 ms** — i.e. the G2's camera clock hiccups constantly and every one of those out-of-order frames used to reach the tracker. See `docs/pruebas.jsonl` T162. Applies on top of 0020. |

| 0022 | (unfiled, verified live 2026-08-12) | Stops `receive_imu_sample` throwing away IMU samples whose converted timestamp did not advance. The comment there says it happens for "one or two" samples after an unclean shutdown; on a Reverb G2 it was **5301 samples in 216 s, ~10% of the whole stream**, because `hw2mono` is re-fitted per sample from arrival time and USB jitter moves the fit (backwards steps: p50 3.3 ms, p99 14.7 ms, max 17.3 ms). Steps under 20 ms now floor the timestamp past the last accepted one and keep the sample; everything is counted (floored, dropped, burst lengths) with throttled logging and running totals, which doubles as a cheap link-health signal. The old log printed one line per dropped sample with an unsigned-underflow "diff". **Contains a documented negative result**: swapping in `m_clock_windowed_skew_tracker` (in-tree, used by the Rift driver) took dropped samples to zero and made drift *worse* — 0.7-1.0 m to 243 m and 1002 m on two runs. Don't re-apply it on the strength of the drop counters. See `docs/pruebas.jsonl` T162. Applies on top of 0021. |
| 0023 | (unfiled, verified live 2026-08-12) | Divergence auto-reset (`SLAM_AUTO_RESET`, on by default, `SLAM_AUTO_RESET_MAX_SPEED` in m/s, integer-only env var) — `flush_poses` calls `tracker_reset` when the implied speed between consecutive poses exceeds 10 m/s, after a session jumped 2459 m in one step and then froze on that value for 90 s. Needs a real `dt` floor (5 ms): two of the first three resets fired on `dt = 0.000 s` where 5 mm reads as 21 m/s. **Known cost, not fixed**: a reset re-anchors at the origin without telling the application, so the world anchor teleports. Also adds `SLAM_FILTER=one_euro|moving_average|exponential|none` — all three output filters are off upstream and GUI-only, so the pose the application gets is raw; measured in-game the one euro filter takes rotation between poses from p99 12.03°/max 32.35° to p99 1.13°/max 5.54°. **The jitter is rotational**: changing `SLAM_PREDICTION_TYPE` to gyro-only changed nothing. See `docs/pruebas.jsonl` T162. Applies on top of 0022. |

> ## 0024-0027 ARE ON A DIFFERENT BASE (2026-08-12, T163) — read this before trying to `git am` them
>
> `0024`-`0027` were developed and verified on the lab machine's `lab-full` branch, **not** on
> top of `0001`-`0023`. `lab-full` is `g2-constellation-x11kde` (`7cb73701b` — the branch with
> the full controller-tracking history, which is finer-grained than and diverged from this
> directory's `0012`-`0017`) with six head/SLAM commits cherry-picked on top: the 90 Hz patch
> plus `0019`-`0023`. All six applied clean. `lab-full` HEAD after these four is `2a6e64d6e`.
>
> They are numbered to continue this directory's sequence because they came next in time, not
> because they apply after `0023`. To reproduce the binary these were measured on, build
> `lab-full`, not this series. Untangling the two lineages is still open — same knot the box
> below describes.
>
> | patch | what |
> |---|---|
> | 0024 | `WMR_CONSTELLATION_CONTROLLERS` was declared twice with **different defaults** (`true` in `wmr_hmd.c`, `false` in `wmr_camera.c`). Unset, the HMD created a constellation tracker while the camera path never assigned the controller exposure slots feeding it — a starved tracker rather than a disabled one, which reads exactly like "constellation doesn't work". Both `false`; the launcher passes the value explicitly. |
> | 0025 | The camera mosaic had no `tracking_origin`, so `CameraMosaic::getTrackingOriginPose` returned `XRT_POSE_IDENTITY` and the tracker assumed the headset never moves or turns. Controller positions came out in a frame bolted to the IMU's initial orientation. **User-verified before and after**: tracked and displaced in all three axes but along visibly wrong axes → axes correct. |
> | 0026 | Upstream bug, not ours: both callers of `Camera::pushPose` gate on `POSE_MATCH_GOOD`, but that score predates the RANSAC-PnP refinement *inside* `pushPose`, whose recomputed score was only used for metrics. Poses the tracker's own criterion had rejected were still published — including `matched_blob_count == 0`. Max step for a motionless controller 1.607/0.937 m → 0.560/0.432 m. |
> | 0027 | Constellation samples now go through an `m_relation_history` (interpolated/predicted to the requested timestamp) instead of "last sample, else placeholder", and `t_constellation_tracker_device_params.tracking_source` — the tracker's own prior, previously `NULL` — reads it. Motionless-controller p99 step 0.435/0.413 m → **0.194/0.007 m**; poses rejected by the tracker 271 → 27. |
>
> | 0028 | Refuses non-finite poses at both constellation boundaries. The headset pose becomes the camera mosaic's origin, so one NaN there turns every controller position into NaN; and a non-finite sample must never enter the controller's relation history, because that history is also the tracker's prior, so the NaN feeds back into the solver and poisons everything after it. Both seen live in a real Aircar session. Note it does NOT use `math_pose_validate`: that one compares the quaternion norm against 1 to within `FLOAT_EPSILON`, and it rejected **5528 consecutive SLAM head poses in 40 s** — every one — leaving the tracker with no valid origin at all. `math_quat_validate_within_1_percent` is the in-tree validator meant for this. |
> | 0029 | **The bug 0025 exposed, and the most interesting one of the day.** The one euro filter divides by `dt = when_ns - its own last timestamp` (`m_filter_one_euro.c:243`) with no guard, and that timestamp is unsigned. Harmless while the compositor was the only caller (it always asks about a *predicted display time*, which advances); as soon as `0025` had the constellation tracker asking at **camera frame timestamps, which are in the past**, the two interleave, `dt` goes negative, and the resulting NaN is **stored in the filter permanently** — the headset's own pose came back `(-nan, nan, -nan)` with flags `0x33` and `XRT_SUCCESS`. A mutex does not fix it and was tried first: the problem is the ordering, not the race. Neither does a plain monotonic latch — one caller passed `when_ns = 5216735132270448003` (~165 years) *once*, and the latch then rejected every pose for the rest of the session, **11 filtered against 3489 skipped**, i.e. the filter silently switched itself off and the wearer felt the raw jitter. Plausibility is now checked against `os_monotonic_get_ns()`, near-simultaneous repeat queries (pairs 17–19 µs apart) are answered with the last *filtered* result rather than the raw pose so two views of one frame cannot disagree by the full jitter amplitude, and a standing applied/skipped/implausible count goes in the log because this failed silently once already. |
>
> `lab-full` HEAD after 0028–0029 is `cfebcd72b`.
>
> | 0030 | Four controller-path fixes from live sessions: hands at **floor level** (the controllers had adopted the constellation tracker's own origin, `initial_offset = IDENTITY`, where `u_builder_setup_tracking_origins` gives NONE-type origins y = 1.3 m — they now share the *head's* origin, which is correct once the mosaic has the head's pose; **user-verified**); hands **flying away** (a finite-but-absurd sample at −3.4M, −7.2M, −15.2M metres with 7 matched blobs, which the NaN guard could not catch); **position never reaching the application** (128 placeholder against 1 tracked while the tracker solved fine — the 200 ms freshness gate was shorter than the ~250 ms real sample interval, now `WMR_CONSTELLATION_MAX_AGE_MS`, default 500); and the **IMU-to-device rotation** `P_imu_me` finally applied to controllers as the HMD always did. |
> | 0031 | **`m_imu_3dof` has always had a gyro-bias estimator that nothing ever ran** — `gyro_biasing()` returns immediately unless `gyro_bias.manually_fire` is set, and the only thing that sets it is a debug-GUI checkbox. So the residual bias integrates forever. Measured, both controllers untouched on a desk, two independent windows within 1%: **left 72 °/min, right 20 °/min**, and **71.7 / 20.0 °/min in a completely different resting orientation** — orientation-independent, which rules out accelerometer misalignment and scale error and leaves plain gyro bias. Gravity correction pulls pitch and roll back but has **no reference for yaw**, which is exactly the axis the wearer kept reporting. `M_IMU_3DOF_USE_GYRO_BIAS_AUTO` fires the existing estimator after a continuous second of stillness. Result, measured frame-independently as the angle *between* the two controllers (immune to any rotation of the reference frame): **18.8 → 8.9 °/min**. |
>
> **Why 0031 is a 53% reduction and not a cure**, from the estimator's own log: successive
> estimates of the same motionless device read 34.5, 63.9 and 47.9 °/min. It averages 300 ms
> and then *replaces* the bias with that, adopting each noisy estimate wholesale. Smoothing
> rather than replacing is the next step and is deliberately not in this patch.
>
> **What 0031 also settles**: this drift is **not** a SLAM problem. It reproduces in 3dof,
> where Basalt is not running at all. `docs/23` and `docs/pruebas.jsonl` T162 both attributed
> the user's roll/yaw drift to long 6DoF sessions; that attribution was wrong.
>
> ## 0032-0035 — the resting-controller "drift" was three stacked mechanisms, closed end to end (2026-08-13, T165)
>
> The arc that ends with a resting controller measuring **+0.00 °/min, residual 0.00°** where
> it measured 31-72 °/min the night before. Base: `lab-full`, HEAD after these `2286029f8`.
>
> | patch | what |
> |---|---|
> | 0032 | Two same-day corrections: `m_imu_3dof_reset()` silently killed the auto bias estimator (it cached the enable flag in a second bool that `U_ZERO` wiped — deleted the duplicate state, the flag is read at the use site); and `WMR_CONTROLLER_IMU_TO_DEVICE` defaults **off** — it never fixed the symptom it was written for, the symptom later moved to the other hand (a fixed mirrored-calibration error cannot do that), and a frame review argues it double-applies. Kept as a knob because the unused transform is a real gap. |
> | 0033 | The estimator smooths (EMA α=0.25 over 1 s averages) instead of adopting each noisy estimate whole — raw estimates of the same motionless device scattered 34.5-63.9 °/min; smoothed they hold 65.5-65.9. Also per-instance log labels, after an unlabeled shared counter produced a wrong "only one device estimates" reading. |
> | 0034 | Prediction horizon capped at 100 ms; a device silent >1 s reports its last fused pose with **zero velocities**. Uncapped, a silent controller extrapolated its frozen angular velocity forever: 31-47 °/min at R²=1.000, pure arithmetic. |
> | 0035 | **The keystone.** ~30 s after a G2 controller stops moving, its firmware keeps the 44-byte packet stream alive but **zeroes the six IMU count fields**. The calibration pipeline then fabricates data: `0 × mix_matrix + bias_offsets` = each device's factory bias vector — measured as `|accel|` frozen at exactly 0.171 / 0.121 m/s² per device (impossible for a real resting sensor) and a fake constant gyro of 0.006-0.021 rad/s = **the whole night's 20-70 °/min "drift"**. Detection on the raw counts (six exact zeros can't come from a live sensor); fusion skipped, staleness then trips 0034's cap. `wmr_controller_og.c` almost certainly needs the same fix — untouched, no OG hardware to verify. |
>
> **Why it took three patches**: each earlier fix was necessary and provably insufficient — the
> estimator can't fire during idle (its stillness gate wants `|accel| ≈ g`, idle reads ~0.15),
> and the prediction cap never engaged (packets kept arriving, staleness never grew). Only the
> per-link instrumentation separated them: fires-per-instance counters, the stillness
> diagnostic with real values, and `scripts/drift-measure.py`'s fixed protocol — built after
> three ad-hoc measurements of the same resting controller disagreed by up to 5x, which
> itself turned out to be mechanism, not noise (each idle onset integrates `factory_offset −
> that_session's_estimate`).
>
> **What 0032-0035 do NOT close**: drift while the controller is actually IN HAND (micro-motion
> keeps real samples flowing; the estimator only converges during stillness windows), the
> head's own bias (measurably ~65 °/min, now auto-corrected while resting — matches the 3dof
> roll-drift reports), and everything already listed under 0027/0031.
>
> **Still open after 0027, measured and stated as measured**: one controller shows a bistable
> flip, two clusters **0.189 m** apart, both with ~8 matched blobs and a good fit. The prior
> cannot break that tie because the orientation it carries is the constellation solve's own —
> the ambiguous quantity itself. The IMU is the independent evidence, but the two are not in
> the same frame: **the gravity direction alone disagrees by 104-161°**, bimodally, matching
> the two clusters. An IMU-backed prior needs the fixed transform between the LED model frame
> and the IMU frame derived from the factory calibration first. It is not a drop-in.

> ## THE SERIES IS BROKEN — 0016 and 0017 DO NOT APPLY (measured 2026-08-12, T157)
>
> This section used to read *"All seventeen apply with plain `git am` onto the pinned SHA
> and build with zero warnings."* **That is false.** Measured on the lab machine by
> applying the series from scratch onto `735e29e4e`:
>
> - **0001–0015 apply clean.** 0016 fails on three files at once:
>   `wmr_camera.c:37`, `wmr_controller_base.c:576`, `wmr_source.c:74`.
> - **Two of 0016's own pre-image blobs do not exist in this repository at all**
>   (`0eaa8be3e` for `wmr_controller_base.c`, `a0f87946f` for `wmr_source.c`). They were
>   generated against commits that were never exported — the "known sync gap" warned about
>   above is not a footnote, it makes the series unbuildable.
> - **Decisive**: 0016 tries to *add* lines to `wmr_camera.c` that the exported 0015
>   **already contains** (`DEBUG_GET_ONCE_BOOL_OPTION(wmr_constellation_controllers, …)`).
>   So 0016 was generated against a **different 0015** than the one exported here. Two
>   divergent histories, not one series.
> - Consistent with all of the above, the exported 0015 still carries the values 0016 is
>   supposed to correct (`DEFAULT_CTRL_EXPOSURE 0x0190` = 400, `DEFAULT_CTRL_GAIN 0x0001`
>   = 1, slot offset `camera_id + cam->tcam_count`), and `ctrl_ts_fix_sinks` — the struct
>   0017 fixes — **does not exist** in this tree's `wmr_source.c`.
>
> **What this costs:** `patches/monado/` cannot currently reproduce the lab build, which is
> the only reason this directory exists. This is the same failure class as T068.
>
> **Do NOT hand-apply 0016/0017's intent onto this series.** Hand-editing the live tree is
> exactly what caused T068 and a week of tests against the wrong binary. The fix is to
> re-export a consistent series from the checkout where 0016/0017 were developed.
>
> **Current buildable state**: `0001–0015` + `0018` (the 90 Hz patch) + `0019–0023`
> (SLAM instrumentation, config sweeping, the frame-bundle drop guard, the IMU
> jitter floor and the divergence auto-reset, all added 2026-08-12) — 21 commits, builds
> with zero warnings, verified on the lab machine 2026-08-12. The constellation controller
> path stays at 0015's unvalidated state, but it is opt-in
> (`WMR_CONSTELLATION_CONTROLLERS`, default off), so nothing regresses.

Patches 0001–0015 and 0018 apply with plain `git am` onto the pinned SHA and build with
zero warnings. 0016 and 0017 do not — see the box above.

> ## UPDATE (2026-08-12): a second, unrelated cause of "6DoF isn't working on the lab" found — the handoff bundle itself was stale
>
> Separately from the loose-`.patch`-file divergence documented above, the **actual
> commits** for 0016/0017 live cleanly on the everyday system's own `monado` checkout,
> branch `g2-constellation-x11kde` — confirmed 28 commits ahead of that checkout's own
> `main` with **zero drift** between them (no rebase conflicts on that side at all). The
> durable handoff bundle
> (`~/Documents/linux_vr_base/g2-constellation-x11kde.bundle` on the everyday system) used
> to get this branch onto the lab machine was created 2026-08-11 and **never regenerated
> after the two commits that actually fix the bug landed later that same night** — so a
> lab build from that bundle would have had the exposure fix but not the `container_of`
> fix that makes `position_tracked=yes` report correctly. That reads exactly like "we saw
> it, it's not quite there" rather than "nothing happened", which is what was reported.
>
> The bundle has been regenerated and the stale copy overwritten in place, plus a fresh
> copy left on the lab disk directly. **Recommended recovery path — fetch the branch as
> real commit objects instead of hand-applying `.patch` files**, which sidesteps the
> divergent-history problem above entirely (a bundle carries the actual objects, not text
> hunks that need a matching parent to apply):
>
> ```bash
> git fetch /path/to/g2-constellation-x11kde.bundle g2-constellation-x11kde:g2-constellation-x11kde
> git checkout g2-constellation-x11kde
> git log -1 --oneline   # should show 7cb73701b "Fix container_of misuse in receive_ctrl_cam..."
> ```
>
> **Update, same day**: the branch is now already fetched into the lab machine's own
> `~/vr/monado` checkout (as local ref `g2-constellation-x11kde`, confirmed tip
> `7cb73701b`) — done via the mounted disk from the everyday system, without touching the
> lab checkout's then-current branch (`lab-90hz-0017`) or working tree. Whoever picks this
> up on the lab side just needs `git checkout g2-constellation-x11kde && ./build.sh` (or
> the project's usual build invocation) — **the build itself is still not verified**, that
> remains the concrete next step. See `docs/30-machine-handoff-protocol.md` for the
> general protocol this incident led to.

**A twelfth patch existed briefly (2026-08-07) and was retracted (2026-08-08).** It "fixed"
an AND/OR bug in 0003's bounded controller-status wait, reproduced 9/9 times in a real
session. Turned out the bug only existed in a hand-edited lab build that had drifted from
this tracked series — applying 0001–0011 fresh via `git am`, with zero manual edits, never
reproduces it (0003 already has the correct form). The apparent bug was an artifact of the
drifted live tree, not something wrong with the tracked patches. Full postmortem in
`docs/pruebas.jsonl` T068 and the (now-historical) correction in this repo's git log. Lesson
learned: the lab's built-and-tested binary must periodically be reconstructed from a clean
`git am` of this directory, not just accumulated live edits, or drift like this can hide for
a long time behind a plausible-looking "found a real bug" story.

~~Still needed on top for 90 Hz testing: the Project-VR nominal-frame-interval patch, see
`docs/04-lab-90hz.md` step 5.~~ **Closed 2026-08-12 (T157): that patch is now exported as
`0018` in this directory.** Leaving it as a prose footnote cost real time — the T068 clean
rebuild silently dropped it, and every lab binary built from `patches/` between 2026-08-08
and 2026-08-12 ran without it. A patch the build needs belongs *in the series*, not in a
sentence at the bottom of the README.

## 0036-0041 — one night of live-session fixes: the tracking freeze, the starved constellation, the 45 fps pacer, battery (2026-08-13, T166-T168)

All built and verified live the same night unless noted. Base: `lab-full`, HEAD after these `f24b56701`.

| patch | what |
|---|---|
| 0036 | A single `os_hid_read` -1 on the **Hololens Sensors** device returned false from `hololens_sensors_read_packets`, breaking `wmr_run_thread`'s loop and ending the shared read thread permanently — IMU, SLAM feed and controller tunnel all die while the service keeps compositing the last pose (seen live: one -1 early, tracking frozen the whole session, device healthy on the bus). Patch 0001's own commit message described this shared-thread risk but only fixed the companion direction. Now tolerates 10 consecutive failures with WARNs, same shape as `wmr_bt_controller.c`. |
| 0037 | Two constellation mechanisms behind "one hand anchored, then it jumps". **Deep-search backoff**: the depth-8 combinatorial search ran to completion every frame for any device without a strong match (cold start, occlusion, dim LEDs) — ~2 cores across the 4 slow threads while the solution rate collapsed to one fix per ~3-4 s (the searches saturating the threads WAS the low rate). Now per-camera-per-device exponential backoff 50→800 ms on the deep pass only. **Staleness-scaled recovery window**: `tryDeviceBlobRecovery` hard-rejected candidates outside `prior_pos_error/prior_rot_error` — ±10cm/30° literals never written anywhere, against a zero-velocity prior frozen at the last fix — so a hand that moved 10 cm could never reacquire cheaply. The window now grows with sample age (0.5 m/s, 60°/s, capped 0.75 m/150°). **Measured after: 0.2-0.3 → 1.7-2.9 optical solutions/s on the healthy hand, monado 4.2 → 2.2 cores under game load.** |
| 0038 | Instrumentation for the 45 fps mechanism: NVIDIA Linux has no `VK_GOOGLE_display_timing`, so the **fake pacer** free-runs a software clock; its catch-up shifts the cadence whole periods forward and (until 0041) nothing pulled it back. Logs each jump with step count + running total. First live data confirmed the ratchet: one-period jumps every few seconds during gameplay, frames late by exactly 11.1 ms, identical rates playing and motionless — structural, not load. |
| 0039 | The per-client wait thread ran `SCHED_OTHER` while sharing `slot_lock`/`list_and_timing_lock` with the `SCHED_FIFO(99)` main loop — priority inversion under tracking load, a stall trigger 0038's ratchet then made permanent. Raised like the main loop. **Corrects a stale CLAUDE.md note**: RT priority was never "still pending sudo" — the main threads have had SCHED_FIFO 99 all along; only this thread was missing it. |
| 0040 | Wires the G2 controller driver's already-parsed `last_inputs.battery` byte into `xrt_device::get_battery_status` (IPC carries it end to end; previously debug-GUI-only). Written after a live session went unnoticed with a dying right-controller battery until that hand's optical tracking starved. **Built and verified live same night**: `scripts/controller-battery-check.py` (libmonado) read left 40% / right 44% on the first try, and `vr-launcher.py` now warns loudly at startup naming the hand and the tracking consequence, never blocking. Scale still uncalibrated (`raw/255`, raw byte logged for a real discharge-cycle calibration) — and the user's mixed setup (NiMH right, alkaline left) shows the chemistry correction must be **per hand**, unlike the Oasis driver's single global `using_1v2_batteries` flag. `wmr_controller_og.c` needs the same fix (no OG hardware). |
| 0041 | The real pacer fix on top of 0038's evidence: `comp_target_swapchain_wait_for_present` now timestamps each successful `VK_KHR_present_wait` return — the moment the frame was actually presented — and feeds it through the previously-no-op `u_pc_info` into the fake pacer, which re-anchors on it (forward-only, so the vblank thread's true scanout times still win when fresh; a `using_fake_pacer` flag keeps synthesized info away from the real display-timing pacer). **Measured: pacer jumps 7-15 → 1-6 per 30 s window during gameplay; user verdict ~60 fps, "casi perfecto", head bounded within ~50 cm in-world with Basalt's own relocalization pulling drift back.** The remaining 4-5% late frames / 60-not-90 lock is the **client-side cadence** (the multi-compositor wrapper broadcasts timings the app inherits one-behind and never re-derives) — the named next target. |

## 0042 — the client-side cadence lock, closed in three measured iterations (2026-08-13, T169)

| patch | what |
|---|---|
| 0042 | `U_PACING_APP_PIPELINED=true`: the app pacer's serial model requires the full cpu+draw+gpu sum to fit before a promised slot, silently forbidding the CPU-vs-GPU overlap OpenXR frame pacing is designed around — an app whose serial pipeline exceeds one 11.1 ms period gets every other slot forever (the measured 45-60 fps) regardless of per-stage times. The pipelined gate reserves cpu+draw+margin only, and the promise shifts one period forward to the slot the GPU actually reaches (first deploy left the promise optimistic: 69-71% of frames "late" by exactly one period as pure bookkeeping, pose prediction aimed at the wrong time, compositor CPU climbing on queue churn — the amend fixed both). Wearer verdicts across the three iterations: free-run env knob "worse, 30 then 18 fps" (rejected with data — unpaced rendering burns the cores tracking needs), pipelined "bastante más fluido", honest promise "mucho mejor". Late frames 69-71% → 25-31%. **The remaining ceiling is raw tracking CPU, not pacing**: SLAM ~2 + live constellation ~2 + compositor ~1 cores against 6 physical leaves the game starved with the GPU at 43%. Next: the docs/30 Windows baseline, 2-vs-4-camera constellation, Basalt config middle ground. |

## 0043 — the 0021 guard was poisonable by one corrupted forward timestamp (2026-08-13, T171 soak)

| patch | what |
|---|---|
| 0043 | Found by the T171 post-repair soak session, ~7 min in: `0021`'s monotonic camera guard only rejects **backwards** jumps, so a single corrupted forward timestamp (a 3.6e18 ns value ≈ 114 years, origin unknown, possibly a glitched hw readout during a USB2-branch blip) was accepted as the new high-water mark — after which every sane frame reads as "older" and gets dropped **forever**: SLAM starved silently for 10+ minutes (11k+ bundles), session up, no crash, no recovery, tracking blind. Now cam0 jumps >10 s ahead are rejected *without* updating the mark; a genuine clock re-baseline (resume after a long stall) is still accepted when the next cam0 frame is consistent with the jumped clock (within 1 s), at the cost of one bundle — random garbage never repeats consistently, so it can no longer poison the guard. Verified live: rebuilt, relaunched (first try, same seat), `tracking.csv` flowing again. Base: `a382cc761` on `lab-full`. |

## 0044 — the ghost was the filter being the LAST stage (2026-08-13, T177)

| patch | what |
|---|---|
| 0044 | The wearer's "fantasma": a ghost image whose separation from the real one **grows with head rotation speed** — the signature of a fixed time lag, not of dropped frames. Bisected with his eyes, three arms, same photo and same compositor session: Aircar through xrizer (present), the native OpenXR viewer in 6dof (present → **xrizer ruled out**), the same viewer in 3dof (**absent** → compositor, scanout and display ruled out). That left the 6dof pose path, and `pose-lag.py` (written for this) measured it: the stream the app actually receives lagged raw SLAM by **+42.5 ms**. Root cause is ordering, not tuning — the path is `predict_pose() → filter_pose() → app`, so the low pass is the last stage and nothing downstream can pay back its group delay. It survived every parameter (beta 0.16→60 only shrank it; derivative cutoff 1→15 did nothing), while `SLAM_FILTER=none` removed it completely and brought back the 12° p99 jitter — the two were mutually exclusive **because the filter WAS the continuous motion path**. Filtering the SLAM poses on arrival breaks that: jitter is filtered where it is generated and dead reckoning then integrates the IMU from that pose's timestamp to the queried time, cancelling the delay. **Measured after: +42.5 ms behind → 5.0 ms ahead** (residual 0.01%), wearer: ghost gone, resting jitter still suppressed. Two naive-reorder bugs fixed in the same patch, one of them caught live as "tracking errors when moving fast": the previous pose is read back from the history, which now holds filtered poses, so the finite-difference angular velocity feeding prediction and the divergence guard's speed check were measuring raw-minus-filtered (i.e. the filter's own lag, inflating exactly during fast motion) — the last **raw** pose is kept separately; and `tracking.csv` / the EuRoC recorder would have silently started recording filtered poses, redefining the baseline every offline tool compares against. Parameters stop being compile-time constants, with **separate** position and orientation cutoffs: only orientation was swept and confirmed by a human, landing on **20 Hz** (~8 ms group delay, under one 90 Hz frame) where the correction step stops being visible — a value that is only safe *with* the reorder. `SLAM_FILTER_BEFORE_PREDICT=0` restores upstream order, and the flag is live-toggleable in the debug GUI. **Still open, stated as open**: a residual wobble when a SLAM correction lands, because the filtered pose is still pushed with the *new* sample's timestamp while its value is ~8 ms older. The fix is timestamp compensation by the filter's group delay (reconstructible as `fc_min + β·\|derivative\|`), deliberately not attempted here — pushing poses with backdated timestamps risks non-monotonic entries, which this project has already been burned by once (0021/0043). Base: `a382cc761` on `lab-full`. **Upstream candidate**: the ordering is Monado's, not ours. |

## 0045 — position deadband, and the rotation/position asymmetry it exposed (2026-08-13, T178)

| patch | what |
|---|---|
| 0045 | The wearer's idea, and his framing: a tool to USE and to rule things out with, not a fix — so it is **off by default** (every offline measurement here reads the delivered stream, and a deadband would flatten exactly the jitter being quantified; the tracker announces it at startup when on). Deadband **with tracking**, not a naive threshold: a naive one freezes the output while the error accumulates and releases it all at once on crossing, trading shimmer for a jump, which in VR is worse. The held point is dragged so it trails the input by exactly one threshold — bounded offset, never a discontinuity. **It must sit at the OUTPUT stage**, and that is the finding: tried first at the SLAM ingest by analogy with 0044's rotation fix, it did *nothing*, because with `SLAM_PRED_DEAD_RECKONING` the delivered position is the SLAM position PLUS accelerometer integration since that pose — freezing the input leaves prediction free to move the output. The wearer proved it in one try by setting 30 metres and seeing no change, a value absurd enough that the null result admitted no interpretation. **The asymmetry, now documented at both use sites**: rotation gains from being filtered *before* prediction (gyro integration faithfully restores what the filter delayed), position does not (accelerometer double integration re-injects noise instead of restoring signal). Verified live: 0.005 m calms the resting shimmer, 0.5 m pins position entirely — which also turns out to be a usable *seated mode*, orientation alive and position frozen, though 3dof buys the same thing and returns the SLAM cores. `SLAM_POS_DEADZONE_M`, also live-sweepable in the debug GUI. Base: `ae2543045` on `lab-full`. |

## 0046 — the IMU-to-LED-model transform was in the factory calibration all along (2026-08-13, T178)

| patch | what |
|---|---|
| 0046 | One log line, one blocker answered. Since 2026-08-12 `wmr_controller_base.c` has said an IMU-backed prior on the constellation solve is **"NOT a drop-in"** because the solve's orientation and the IMU fusion live in different frames, and that resolving the fixed transform *from the factory calibration* is the prerequisite. It is already parsed: the controller config reads both the LED model and the inertial sensors from the same `CalibrationInformation` block, so `sensors.accel.pose` **is** that bridge. Read off two real G2 controllers: **105.3° / 105.5° of rotation and 85 / 83 mm of offset**, mirror images of each other as left/right should be — not the identity the default initialiser would leave. And **105.3° is the low mode of the 104-161° constellation-vs-IMU disagreement measured earlier**, within a degree. That both answers the premise and explains the bimodality *with a discriminator attached*: apply the transform and the correct pose's gravity-axis disagreement should collapse toward zero while the wrong one keeps the remaining ~161°, which is precisely the outside information needed to break a tie that **no threshold on the tracker's own metrics can** — measured the same day, ~20 cm of scatter between solutions for a motionless controller with each reporting an excellent 0.17 px reprojection error. **This is the named starting point for the next session.** *Correction (T181, same night): the prediction did not survive measurement — applying `P_imu_me` does NOT collapse the disagreement in any composition tried; the real bridge is the WMR y/z axes flip (Rx180), identified by motion, see 0047. The 105°≈low-mode match was a coincidence.* Base: `b62a17de2` on `lab-full`. |

## 0047 — the gravity gate: the bridge was identified by motion, and it is NOT the factory transform (2026-08-13, T181)

| patch | what |
|---|---|
| 0047 | The discriminator 0046 asked for, built and validated — after its central hypothesis was **refuted by measurement**. Static captures with quaternion logging showed each bistability lobe is rigid to 1-3° (the solve-vs-fusion delta is constant per lobe), but no composition of `P_imu_me`, its conjugate, or any axis-fix conjugation collapsed both hands at once — two unknown fixed rotations plus a per-session yaw make static data underdetermined. The identification that worked bypasses world frames entirely: **wave the controllers and solve Wahba on paired relative rotations** (the same physical rotation seen by the solve stream and the fusion stream, each in its own body frame; `scripts/constellation-frame-fit.py`). Verdict: **178.9°/178.8° about X, left/right — the WMR y/z axes-swap convention** (`wmr_hmd.c`'s "Correct swapped axes"), identical on both hands as a convention must be, not the mirrored 105° factory `accel.pose`. Rotation-angle agreement p50 0.4-0.5° validates the rigid-body model; residuals p90 7-9°. The gate: world-down in the solve body frame vs world-down in the fusion body frame through Rx180, `WMR_CONSTELLATION_GRAVITY_GATE_DEG` (default 14°, 0 disables), gated only while IMU data flows so it cannot block the initial lock. Validated static: true lobes p90 4.3/6.5° vs orientation-flip ghosts p50 21/p90 89°; live, every sampled drop was a 105-128° flip. **What it cannot fix, by construction and measured the same night**: near-pure-yaw assignments keep gravity intact and still bounce position between stable clusters 20-30 cm apart (3 on the right controller, all at 0.07-0.08 px) — the open problem is feeding the prior into the solver's assignment search, or pattern-phase disambiguation (`scripts/constellation-gate-validate.py` is the instrument). Telemetry moved DEBUG→INFO with device name + both quats. In-game wearer verdict pending. Base: `a30028f3e` on `lab-full`. |

## 0049 — the companion device's read thread finally gets a backoff, closing T183/T188's most-urgent open item (2026-08-16, T188)

| patch | what |
|---|---|
| 0049 | `control_read_packets()` (the companion/HMD-control device) has swallowed every `os_hid_read` failure unconditionally since 0001, on the assumption that the shared thread loop stays paced by the hololens sensors device's blocking 100ms read — "a failing read is one cheap syscall". T188 (this same session's earlier entry) disproved that live: under real gameplay load (SLAM + constellation + Aircar) a sustained companion dropout produced **472175 consecutive failed reads and pinned `monado-service` at 400-432% CPU for a full ~17-minute session**, because the hololens read stops blocking for its usual 100ms once real IMU data is arriving fast enough — so the unbounded companion retry ran at whatever rate *that* read was returning, not the intended ~10Hz. Closing the game had zero effect; the spin lives entirely in this thread, independent of any client. Only `SIGTERM` recovered it. Same shape as 0036's fix for the hololens sensors read (consecutive-failure counter, reset on success), but **unlike 0036, never gives up** — past 50 consecutive failures it backs off with a 10ms sleep instead of retrying unbounded, since the companion device (IPD/proximity/screen-enable only) isn't load-bearing for tracking; killing the thread over it would be worse than the bug. Also escalates the log from silent `WMR_DEBUG` to a `WMR_WARN` on the 1st and every 1000th consecutive failure, so a sustained dropout is visible in a normal-verbosity log. **Written and compile-checked** (`-Wall -Wextra -pedantic`, matching the project's build flags) from the everyday system against the mounted lab disk, in both `monado` checkouts (lab disk and everyday system, same commit `657bcd8af`) — **not yet re-verified against real hardware** under T188's load pattern; that's the next concrete step, and it's what the `!2967` reply (this project's upstream MR for the same driver file, see `docs/18-monado-upstreaming.md`) is waiting on before citing this as resolved. Base: `e26ac16b3` on `lab-full`. |

## 0050 — testing (and disproving) the RT-priority preemption theory of the SLAM collapse (2026-08-16, T194/T195)

| patch | what |
|---|---|
| 0050 | Env-gated diagnostic, not a fix: `WMR_HMD_THREAD_NO_RT=1` skips `u_linux_try_to_set_realtime_priority_on_thread()` on the WMR read thread (`wmr_run_thread`), added to test T194's hypothesis that holding max `SCHED_FIFO` priority through 0049's 10ms backoff sleep was preempting Basalt's own threads ~100x/second and wrecking VIO timing. **T195 disproved it live**: disabling RT priority on this thread alone did not stop the SLAM pose-rate collapse, and a separate `perf sched` trace of a live collapse showed the thread's own scheduling delay maxed at 0.026ms while the rest of `monado-service`'s 29 threads got CPU promptly (60%+ utilization over the trace) — nothing scheduling-related explains the repeating ~632-666ms stall. Left in place, off by default, as a cheap diagnostic knob rather than reverted (cost nothing to keep, and the question may come up again). The real root cause — a blocking IMU catch-up in Basalt's own optical-flow frontend — was found afterward and lives entirely on the basalt side; see `docs/39-slam-collapse-root-cause.md` and `patches/basalt/0007`/`0008`. Base: `657bcd8af` on `lab-full`. |

## 0051 — constellation correspondence search: bounded with a per-model deadline, but the fix stays off by default (2026-08-17)

| patch | what |
|---|---|
| 0051 | `search_pose_for_model()` (`correspondence_search.c`) ran the full combinatorial LED↔blob expansion on every frame that produced no strong match — no wall-clock budget anywhere, only a `POSE_MATCH_STRONG` early-out — which pegged **3 CPU cores at 614% peak** on the everyday system's pathological case (controllers powered off, or spurious room-light blobs, so no real target ever prunes the search early). `WMR_CONSTELLATION_SEARCH_BUDGET_US` (default `0` = off, unbounded/original behaviour) caps each per-model search at N microseconds and keeps the best match found so far when the deadline fires. Validated at 3000 (3ms): 614%→261% CPU, all three pegged cores gone. **Deliberately not defaulted on**: a same-day controllers-on A/B on the everyday system's blob-swamped scene (mean 22-27 blobs/observation under room light — real LEDs plus spurious blobs, a pre-existing exposure/threshold issue) showed the 3ms budget cutting off real matches before they complete: **0 poses found (1603 failed) with the budget on, vs 19 poses found (1304 failed) with it off**, same lighting/position. "A real target matches well inside the budget" held only for a clean scene, not this swamped one. The same data also refutes the hypothesis that motivated this patch in the first place — that the constellation-search CPU runaway was starving Basalt's SLAM frontend of frames: with the budget on, CPU fell 614%→261% but the SLAM input-frame drop rate barely moved (~11→~10/s); that drop is Basalt's own optical-flow keypoint-detection cost (see `patches/basalt/0008`), unrelated to this search. **Refined fix direction, not yet implemented**: a blob-count/swamping guard (reject or subsample a frame once a camera reports far more blobs than a controller can actually show, which is exactly when the search explodes) or a controller-present gate (skip the exhaustive search only when the controller hasn't been seen recently, handling the controllers-off case at zero cost to real tracking) — either targets the pathological case specifically instead of time-cutting a legitimately hard match. See `docs/40-constellation-search-cpu-blowup.md`. Base: `aa68be117` on `lab-full`. |

## 0052 — the diagnostic that proved the camera clock runs +578 ms ahead of query-now (2026-08-17, T198)

| patch | what |
|---|---|
| 0052 | Rate-limited (~1 line/s at 250 Hz) `SLAM_INFO` in `predict_pose()` (`t_tracker_slam.cpp`), printing the anchor age dead reckoning actually sees at the call site: `when_ns` (the query/IMU-prediction clock) minus `rel_ts` (the filtered SLAM pose it integrates forward from). Written for the T197 constant ~1 s wearer lag, after reading the whole prediction path (`t_dead_reckoning.c`, `m_predict.c`, `m_filter_fifo.c`, `wmr_hmd.c`/`wmr_source.c`) found no horizon cap and a silent stale-anchor fallback whose own failure-path log came back with zero live hits — dead reckoning never fails, so the bug had to be in what it was fed, not in how it handled running dry. **This one diagnostic settled it**: anchors LOOK only 50-112 ms old to the predictor while their content is ~630-700 ms stale, and cross-referencing the same log's `when_ns` against Basalt's own `vit_collapse IN ... t_ns=` lines (`patches/basalt/0003`) for the newest camera-frame stamp proved the camera timestamps run **p50 +578 ms (max 610, n=121) in the FUTURE** of the query/IMU clock. This is the unifying root behind docs/39's "image ~600 ms ahead of arriving IMU" collapse mechanism, the suspiciously tight 632-666 ms period of T192/T194/T195, and the wearer's unbridgeable constant ~1 s latency (dead reckoning only ever integrates the ~90 ms the lying stamp admits to; Monado does not re-stamp — `flush_poses` uses `data.timestamp` verbatim, so the bias rides in from upstream untouched). Diagnostic-only, no behaviour change, always on at `SLAM_LOG=info`. See `docs/pruebas.jsonl` T198 and `docs/44-clock-domain-skew.md` for the full write-up, the honest scope caveats (measured at the tracker layer, not yet at the `cam_hw2mono` ingest site itself), and the surgical next step. Base: `560cc6e21` on `lab-full`, commit `9fe21a089`. |

## 0053 — the ingest-side diagnostic that overturned both the constant-bias and startup-burst hypotheses (2026-08-17, T199)

| patch | what |
|---|---|
| 0053 | The instrument that finally settled 0052/docs/44's open question. Logs, at cam0 cadence (unconditionally for the first 30 frames, then 1-in-300, ~1 line/10 s at 30 Hz), the RAW hardware-domain skew between a camera frame's stamp and the last IMU sample's stamp (`cam_minus_imu_hw_ms`) alongside where the CONVERTED stamp lands vs `os_monotonic_get_ns()` (`converted_minus_now_ms`) and the live `hw2mono` offset — logged directly at `receive_cam0` in `wmr_source.c`, the actual `cam_hw2mono` conversion site, not inferred two layers downstream at the tracker as 0052 was. **The first capture immediately killed the leading "startup-burst anchoring" hypothesis 0052/docs/44 had proposed** (the offset estimator fixing its fit on ~19 buffered frames at process start, 19 × 33 ms ≈ 630 ms): a FRESH idle session started **honest** — cam-vs-IMU hw skew −4..0 ms, converted camera stamps only −4.5 ms in the past — the opposite of a bias fixed at session start. Watched further, the SAME session then **ramped from −2.45 ms to +630 ms between frames ~300 and ~1200 (under 40 s, no app, no wearer)** and pinned there rock-stable — proving the bias is a load-onset **drift**, not a fixed constant, with `hw2mono` moving +630 ms in lockstep (i.e. the IMU stream itself falling ~630 ms behind at arrival, and the offset estimator dutifully absorbing that lag rather than producing it). This is what made `0055`'s fix possible: without raw skew measured at the real ingest site, the drift's shape and onset timing could never have been separated from a fixed bias. Frames 1-4 (before the first IMU sample initializes `hw2mono`) also exposed the raw device hardware clock in passing: +16.45 s vs host monotonic on that boot — noted, not investigated further. Diagnostic-only, `WMR_INFO`-level, no behaviour change. See `docs/44-clock-domain-skew.md`'s resolution section and `docs/pruebas.jsonl` T199. Base: `9fe21a089` on `lab-full`, commit `1c7bea7f2`. |

## 0054 — WMR_CONTROLLER_KEEPALIVE_S: an unvalidated keep-awake prototype (2026-08-17, T200)

| patch | what |
|---|---|
| 0054 | `WMR_CONTROLLER_KEEPALIVE_S` (default `0`/off) — a prototype, not a confirmed fix. Resends the G2 controller's two connect-time enable commands (status-report enable `{0x06,0x03,0x01,0x00,0x02}`, IMU-on `{0x06,0x03,0x02,0xe1,0x02}` — the exact bytes `wmr_controller_base_init` sends once at startup, same order, via the same `wmr_controller_send_bytes()`) at most once per N seconds, driven from `get_tracked_pose` so it runs for the life of the session. Motivated by docs/03's still-open "~15 min motionless controller power-off": a T200 research pass across the Windows RE (`docs/re-windows/03-05`) and this project's own `wmr` driver settled that **cold power-ON from software is settled-impossible** — no protocol write exists anywhere, controller pairing/wake is entirely radio+physical-button, and Windows' own `CrystalKeyKeepAlive` is a dead stub returning `ERROR_CALL_NOT_IMPLEMENTED` — so this patch's premise is narrower: whether unsolicited host traffic on the tunnel can *postpone* the sleep timer, the way real motion does, before it fires. Explicitly does **not** touch the two one-shot (re)init commands (zero, quiesce) sent earlier in `wmr_controller_base_init` — not known to be safe to repeat mid-session. Ranked against the other keep-awake candidates T200 surveyed: this (resend the connect-time enables) is **#1**; haptics is not currently implementable at all (`set_output` is a not-implemented stub, wire bytes unknown — docs/03 "double dead"); LED pulse-train needs more RE; an `0x17` status re-request is HMD-addressed and low-confidence. Best remaining RE lead for a real fix: the unexplored `IdledOut` string in `MotionControllerHid.dll`. **Deliberately left unvalidated**: the sleep timer may be purely motion/IMU-activity-gated on the controller's own side, in which case this traffic is inert. The deciding A/B — a powered, motionless controller for >15 min at `WMR_CONTROLLER_KEEPALIVE_S=600`, LED state + `imu_age_ms` as instruments, needs the user to press the buttons once first — is still pending and decides whether this graduates or reverts. See `docs/pruebas.jsonl` T200. Base: `1c7bea7f2` on `lab-full`, commit `93c11ee5a`. |

## 0055 — THE fix: companion backoff by deadline-skip, not by sleeping the shared read loop — closes the whole T192-T199 saga (2026-08-17, T199)

| patch | what |
|---|---|
| 0055 | **The real 0049 follow-up fix.** 0049's companion backoff, once past 50 consecutive `os_hid_read` failures, slept 10 ms via `os_nanosleep` **inside** `wmr_run_thread`'s single shared read loop (`control_read_packets` and `hololens_sensors_read_packets` run sequentially in one thread, sharing `wh->hid_lock` — T194). With the companion storm active (universal, T183/T188/T189/T190), that sleep capped the *whole loop* — hololens sensors/IMU reads included — at ~100 iterations/s against ~250 IMU packets/s actually produced by the device. The kernel-side ring buffer filled and pinned the IMU stream a fixed ~630 ms stale at arrival; `hw2mono` (fit from IMU arrival times) absorbed that lag rather than exposing it, which pushed the *converted* camera frame stamps ~630 ms into the **future** relative to query-now. That single number IS the 632-666 ms "magic number" chased across T192-T199: it produced docs/39's image-ahead-of-IMU stall (the SLAM pose-rate collapse `patches/basalt/0007`/`0008` had already fixed symptomatically, by not blocking indefinitely on IMU catch-up), and separately the wearer's constant ~1 s perceived head latency (T197) — prediction trusts the anchor's stamp, not its true content age, so dead reckoning only ever bridged the ~90 ms the lying stamp admitted to. It also resolves the standing "why WITH 0049 and never before it" question: T193's pre-0049 45-minute run never collapsed because the failing companion read back then spun **without any pacing sleep** in the loop at all — nothing throttled the hololens/IMU side, so the ring never filled. **The fix**: keep 0049's ≤100 Hz companion retry ceiling, but implement the backoff as a **skip** until `companion_backoff_until_ns` instead of a sleep — zero impact on the shared loop's pace (the hololens blocking read still paces the healthy loop; its own separate failure-path sleep is untouched). `WMR_COMPANION_BACKOFF_BLOCKING=1` restores the old in-loop sleep for a direct A/B. **Validated live** (idle SLAM session, storm ACTIVE the whole time — 39792 consecutive companion errors, the exact old trigger condition): cam-vs-IMU raw hardware-domain skew held flat at **−4..−0.7 ms over 8 minutes / 14400 frames** (old behavior: +630 ms by frame 1200), converted camera stamps steady at −4.5 ms (honest past), and the tracker's own prediction anchor age finally reads the TRUE content age (~144 ms idle) instead of a lying ~50-112 ms. **Cross-confirmed independently via Windows RE**: `MRUSBHost.dll` carries `IMUStaleDataDrop`/`CameraReaderLoopRestartingIMU` — Windows' own driver explicitly detects and restarts a stale IMU stream, i.e. defends against exactly this failure class, which this project only found by living through it. **Scope, stated plainly**: validated at mechanism level with the storm both active and idle; the wearer feel-test (head rotation should now be immediate, the constant ~1 s lag of T197 should be gone) is still pending. See `docs/44-clock-domain-skew.md`'s resolution section and `docs/pruebas.jsonl` T199. Base: `93c11ee5a` on `lab-full`, commit `6aa1fbd92`. |

## 0056 — constellation: blob-count swamping guard + lost-controller search decimation, both default off (2026-08-17, T197/T203)

| patch | what |
|---|---|
| 0056 | Implements docs/40's two "refined fix direction" candidates, one level above the search itself in `Camera::processSampleSlow`, additive to 0037's existing always-on deep-search backoff (lifecycle state for both is erased/reset together whenever a device matches). **`WMR_CONSTELLATION_MAX_BLOBS`** (default `0` = off): skips the whole combinatorial correspondence search outright for a frame whose blob count exceeds N — acquisition just retries next frame — instead of time-cutting it the way 0051's search budget does (0051 was found unsafe to default on because a tight deadline kills legitimately-hard-but-real matches, docs/40). **Deliberately ships with no built-in default N**: the lab rig measured `num_blobs=29` with **both controllers legitimately in view** (2×16 LEDs), which overlaps the everyday system's own *swamped, controllers-OFF* baseline of 22-27 blobs (room light alone) — there is no threshold that is universally safe, so this must be calibrated per box above its own highest legitimate blob count, not shipped as a shared constant. **`WMR_CONSTELLATION_LOST_SEARCH_DIV`** (default `0` = off): for a device not matched within the last 1 s (checked against `last_known_pose.timestamp_ns`, the same stamp `pushPose()` already maintains — no new per-model state needed), decimates *both* search passes (shallow and deep) to every Nth eligible frame instead of running the shallow pass on every single sample as the code otherwise does "so acquisition is attempted continuously" — e.g. N=10 against 30 Hz cameras still reacquires at ~3 Hz, a tenth of the cost. **Never decimates while recently matched**, so a controller that IS being tracked is never throttled, only one that's been lost for a while; computed once on the shallow (`i==0`) pass and re-read on the deep pass so both agree within a frame. Written after **T197's live `gdb` stack sampling during a sustained no-match session** caught the burn squarely in `pose_metrics`' own `project_led_points`/`find_best_matching_led` at `num_blobs=29` — i.e. the cost lives in the model search itself (both passes), not only in the deep-pass escalation 0037 already throttles, confirming docs/40's refined direction (blob-count guard / controller-present gate) is the real path rather than a wider search-budget deadline. See `docs/40-constellation-search-cpu-blowup.md` and `docs/pruebas.jsonl` T197/T203. Base: `6aa1fbd92` on `lab-full`, commit `965943d51`. |

## 0057 — headless per-stage pose timing (SLAM_TIMING_STAT finally consumed) + the divergence-reset teleport gets its real fix (2026-08-17, T202/T203)

| patch | what |
|---|---|
| 0057 | Two independent changes in `t_tracker_slam.cpp`. **(a) Headless per-stage pose timing**: `timing.csv` had shipped only its fixed 2 columns for the project's entire history because Basalt's 26-checkpoint breakdown was gated behind a debug-GUI toggle button, and `SLAM_TIMING_STAT` — parsed into `config->timing_stat` since day one — was never actually consumed anywhere, a dangling knob that looked like it should have enabled exactly this. It now does: `t_slam_create` calls the newly-extracted `timing_columns_setup()` (pulled out of `timing_ui_setup`, idempotent, callable from both the headless and GUI paths) and, if `config->timing_stat` is set and the tracker supports it, negotiates `VIT_TRACKER_EXTENSION_POSE_TIMING` at startup with no GUI attached. Fixes a second, silent bug in the same area: `timing_columns_setup()` must run **before** `TimingWriter` is constructed, because `CSVWriter`'s constructor copies its column-names vector **by value** — the old code populated `t.timing.columns` only inside `timing_ui_setup()`, which ran *after* `TimingWriter` already existed, so `timing.csv` shipped a permanently corrupted bare-`#` header (first data row glued onto it) unless the GUI's timing button had already been clicked that session. **First live headless use produced the project's first-ever 26-checkpoint breakdown** and immediately relocated the "backend saturated" story T197-T199 had been telling: the #1 cost is the **optical-flow TRACKING stage** (48.5 ms p50), not the VIO backend (~12 ms total) — the measurement that motivated the same night's `SLAM_THREADS` 2→4 graduation (48.5→28.4 ms, wearer-confirmed). See `docs/pruebas.jsonl` T203. **(b) `SLAM_RESET_OFFSET_CARRY`** (default **on**, `=0` restores the old behavior for an A/B): the real fix for T162/0023's divergence-reset teleport, which recurred live this same session (T202: a 1502 m spike then a hard snap to `[0,0,0]`, wearer luckily mid-motion). 0023's `tracker_reset()` makes the external tracker come back reporting poses in its own fresh coordinate frame near its own origin — every consumer previously read that as the position teleporting, with no way back short of a manual recenter. On reset, this solves the rigid transform mapping the tracker's first post-reset pose onto the last known-good **output** pose (captured as `lr.pose` — the previous accepted pose, not the diverged spike that triggered the reset) — but keeps only **position and gravity-twist yaw**, decomposing the full solved rotation about the up axis and discarding the swing (roll/pitch), because Basalt re-aligns to gravity on every reset and forcing the full relative rotation on top of that would tilt the world by whatever roll/pitch noise is in the difference; roll/pitch stay tracker-truth by design. Applied at **ingest** in `flush_poses`, before `npos`/`nrot`/`nvel` are used for anything, so the relation history, every output filter, prediction, and every CSV/EuRoC writer (including `tracking.csv` — a disclosed, deliberate exception to its usual "unfiltered raw output" contract: this is a coordinate **rebase**, not smoothing, and `SLAM_RESET_OFFSET_CARRY=0` restores byte-identical pre-fix output) all see one continuous frame and never have to know a reset happened. Because the offset is **re-solved, not composed**, against an anchor that is itself already in the corrected output frame, repeated resets in the same session accumulate correctly instead of multiplying stale transforms together. Strict no-op until a reset actually fires (identity offset all session otherwise). See `docs/pruebas.jsonl` T202 and T203. Base: `965943d51` on `lab-full`, commit `0a8fc0e81`. |

## 0058-0060 — round-2 (T204 program): CPU-affinity knobs, decaying correction spread, and the leak/blind-spot cleanup (2026-08-17, T204/T205)

Three deliverables from a four-workstream parallel investigation, landed together the same night. Base chain: `0a8fc0e81` on `lab-full` through `d32d03e43`.

| patch | what |
|---|---|
| 0058 | Two round-2 deliverables in one commit. **CPU-affinity knobs**: `XRT_COMPOSITOR_CPU_AFFINITY` / `WMR_CPU_AFFINITY`, env-gated CPU pinning for the compositor's three RT threads and the WMR read + constellation processing threads — strict no-op unset, touching 11 files across `u_linux`/`u_thread_priority`, the compositor's `main`+`multi` targets, `wmr_hmd.c`, `wmr_controller_base.c`, and `t_constellation_tracker.cpp`. Written after first confirming RT priority is already comprehensively applied everywhere it should be (no missing-RT hypothesis survives — the door 0039 opened is closed for good); the live suspects for the 4-7% one-slot-late frames measured under game load are the kernel's RT bandwidth throttle (`sched_rt_runtime_us=950000/1000000` reserves a 5% non-RT slice, numerically matching the 4-4.4% late-frame floor almost exactly — root A/B still pending, `sysctl -w kernel.sched_rt_runtime_us=-1`) and cache/SMT contention, which these knobs let the next session actually test (suggested first split on the x3600: compositor `0,6` / everything else `1-5,7-11`). **Controller keepalive v2**: moves 0054's periodic resend off a `get_tracked_pose`-driven call — self-invalidating, since it fires zero resends with zero OpenXR clients connected, T203/T204's own finding — onto a tick inside `wmr_run_thread` itself, once per loop, so it runs for the life of the process regardless of client state. The obvious alternative, resending from the tunnel's own receive-path callback, was rejected on inspection rather than by trial: that callback holds `conn->lock`, and `wmr_controller_send_bytes()` re-takes the same lock — a guaranteed self-deadlock, caught by reading both call chains before writing any code. Base: `0a8fc0e81` on `lab-full`, commit `133793149`. |
| 0059 | `SLAM_CORRECTION_SPREAD_MS` (default `0` = off, suggested live value `120`) — the round-2 answer to the wearer's ~200ms 'readjustment' snap on every SLAM anchor swap (T202: 4-4.6 Hz worn, corrections ≥0.5°/5mm, only weakly anchor-correlated at rest, 0.088 Hz). At each anchor arrival, computes the delta between what the old prediction history would still deliver at the new anchor's timestamp and the new anchor itself, then accumulates it — position and **yaw-only** twist; roll/pitch apply instantly, because gravity must never lag — into a correction that decays exponentially on the host monotonic clock and is added to every delivered pose between predict and filter. The `pred` CSV keeps meaning raw prediction throughout; only the delivered/filtered stream reflects the spread. Bypassed and zeroed whenever 0057's divergence auto-reset fires (`awaiting_anchor` checked first, so a reset's own coordinate rebase is never itself smoothed). **Wearer-validated same night (T206)**: "bastante bien che. Solido... el fondo esta clavado mas bien. Parece muy estable, casi por pixel" — the world anchor holding steadier than it has ever measured; head turn still carries some residual trail ("algo de rastro"). Joystick position breathe measured down from ~1cm to ~0.5cm at ~200ms. Base: `133793149` on `lab-full`, commit `3274494cf`. |
| 0060 | Two small, unrelated T204 follow-ups. **The leak**: `flush_poses`'s `pose_get_data`-failure exit returned without destroying `pose` — every *other* exit of that loop calls `vit.pose_destroy()`, this one alone leaked one `vit_pose_t` per occurrence; found during the same night's leak hunt that also produced `patches/basalt/0011`. **The blind spot**: nothing in this project had ever printed the factory IMU mix matrices actually driving fusion (Basalt's own `print_calibration()` is dead code, never called), even though a degenerate `mix_matrix` would manifest exactly as the measured motion-proportional roll drift and yaw→tilt coupling that night's own investigation was chasing — adds one `WMR_INFO` block per boot in `wmr_hmd_get_imu_calib`. **Not a red herring — a real answer**: the first-ever print showed the gyro mix matrix at diag `1.0033/1.0007/1.0024`, off-diagonal ≤0.0016, bias `0.018/-0.001/-0.011` — healthy, near-identity. This is a different finding from 0057's per-stage timing (which relocated the "#1 cost" from the VIO backend to the optical-flow frontend) — 0060's print instead kills a *calibration-quality* hypothesis outright: a degenerate factory matrix was never the source of the drift. One nuance stayed open in the same night's verdict: 0.16% cross-axis leak × the measured 319°/min gameplay yaw churn ≈ 0.5°/min into roll, the right order of magnitude for the observed +0.84–0.93°, so a below-tolerance residual or Basalt's own bias estimation under rotation are both still live — the named discriminating experiment is a turntable with the *headset* at constant rate. Base: `3274494cf` on `lab-full`, commit `d32d03e43`. |

## 0061 — WMR_CONTROLLER_ORIENT_FIX: a burned A/B candidate, kept as the record of why guessing failed (2026-08-17, T206)

| patch | what |
|---|---|
| 0061 | T206's sharp new spec — both controllers show **every** rotation axis inverted in-game (pitch forward renders backward, and so on) — first tried the cheapest hypothesis: since the delivered controller orientation is `fusion.rot` verbatim (structurally identical to the HMD's own proven 3DoF path) and every existing A/B knob only *composes* an additional proper rotation on top of it, none of which can produce or fix a systematic direction reversal, the candidate fix was a conjugate (`math_quat_invert`) applied to the delivered orientation, gated `WMR_CONTROLLER_ORIENT_FIX` (default off). **Burned live**: the conjugate alone changed the failure mode rather than fixing it — the wearer described rotation about "unseen intermediate axes" — and conjugate composed with the existing Rx180 knob just reverted to the original symptom. Kept in the tree, off by default, specifically as the documented record of why a blind sign-guess on the whole orientation couldn't work: a conjugate can only correct a *global* reflection, and the real defect (found next, 0062) was a reflection on exactly one axis of one hand — smaller and structurally different, and unreachable by any whole-orientation composition. Base: `d32d03e43` on `lab-full`, commit `a7a74b7b3`. |

## 0062 — WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT: the labeled-capture-derived reflection fix, proven by determinant (2026-08-17, T206/T207)

| patch | what |
|---|---|
| 0062 | The method that cracked the saga: a labeled motion capture per hand — still 10s → 5× pure pitch → still → 5× pure roll → still → 5× pure yaw → still, `WMR_CONTROLLER_CALIBRATION_LOG=1`, same wearer, same sequence, same session for both controllers — segmented by gyro magnitude into a per-phase dominant-axis table. **Right hand: pitch+X, roll−Z, yaw+Y — R = identity**, matching the OpenXR grip convention exactly and the wearer's own "derecho bien", validating both the method and the target. **Left hand: pitch+X, roll−Z (same as right), yaw−Y** — one axis sign-flipped, the other two untouched. Two axes correct and one flipped is a **reflection** (determinant −1): composing any fixed quaternion onto the delivered orientation — the entire prior A/B menu, including 0061's plain conjugate — can only ever produce another proper rotation (det +1 by construction, provably, not just empirically), so no such composition could ever have fixed this, explaining why every earlier knob failed or made it worse. It also explains why only yaw was ever affected: `m_imu_3dof`'s gravity correction continuously re-anchors pitch/roll every update, so a wrong-signed gyro axis feeding those two gets corrected out almost immediately; yaw has no such reference and integrates the sign error forever. **The fix**: negate the Y component of the LEFT controller's calibrated gyro sample — after `mix_matrix`/bias/`P_oxr_gyr`, before `m_imu_3dof_update` — so fusion integrates the correct sign going forward, verified numerically against the recorded capture (negating `gy` leaves pitch/roll RMS bit-for-bit unchanged and flips only the yaw peak's sign, landing it on +Y to match the right hand). Default off, left hand only, right hand's pipeline untouched, for a live wearer A/B. **Not yet hardware-root-caused**: whether the true defect lives in the factory `gyro.mix_matrix`, `bias_offsets`, or `P_oxr_gyr.orientation` for this specific unit is still open — none of those raw values were logged yet (see 0063). Base: `a7a74b7b3` on `lab-full`, commit `3b54250be`. |

## 0063 — controller factory calibration matrices + determinants at connect: the factory-reflection hypothesis dies (2026-08-17, T207)

| patch | what |
|---|---|
| 0063 | Logging built to pin 0062's still-open root cause. Investigation found the probable origin first: `pose_from_rt()` converts the factory `Rt.Rotation` through Eigen's polar decomposition, which silently forces `det=+1` — a genuine reflection in a physically-mirrored left/right mounting would get absorbed into a discarded scaling term, and a quaternion structurally cannot carry it back out. Adds a plain cofactor-expansion `mat3x3_det()` (transpose-invariant, so it doesn't matter that different call sites in this driver disagree on row-major vs column-major storage) and prints both sensors' `mix_matrix` **and** `Rt.Rotation`, with determinants, per hand, once per connect. **Result: all eight matrices proper** (left/right × mix/Rt × gyro/accel) — the factory-reflection hypothesis is dead; whatever `pose_from_rt`'s det-forcing might hide, it isn't hiding anything here, since nothing upstream of it is a reflection either. Eigen's silent det-forcing in `pose_from_rt` is documented in the comment as a real hazard for any *future* unit that does ship a genuine mirrored mounting — just not triggered on the two controllers measured tonight. Sets up 0064-0065's reconciliation-algebra attempt: with all matrices proper, the fix had to come from the two hands' frame *convention*, not their factory calibration. Base: `3b54250be` on `lab-full`, commit `21a8476b0`. |

## 0064-0065 — the accel extension and its same-night refutation by the wearer's figure-8 (2026-08-17, T207)

| patch | what |
|---|---|
| 0064 | T207's reconciliation analysis: the two hands' factory `Rt` mountings differ by ~178.6° about Y (all matrices proper per 0063 — no recoverable factory reflection), and the numerically-derived left-to-right correction algebra came out to exactly `diag(1,-1,1)` applied to **both** post-calibration sensor vectors, not just the gyro. 0062 had negated only the gyro, feeding `m_imu_3dof` two inconsistent conventions — the accel-driven gravity correction fighting the now-corrected gyro — which the reconciliation argued was behind the wearer's "still wrong" with the gyro-only fix live. Extends the same `WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT` gate to also negate `imu.acc.y` on the left controller, so both sensors share one coherent convention. |
| 0065 | **Same-night refutation, the decisive experiment.** With gyro **and** accel both negated, the wearer's 3D figure-8 test on the left controller wound up whole extra turns instead of closing ("sigue pegando vueltas completas"), while the right hand's closed exactly — the signature of **precession**: a flipped gravity reference fighting a correctly-signed gyro never settles. With only the gyro negated, all three axes rotated correctly per the wearer ("los ejes parecen estar bien"), leaving just a constant heading offset. Reverts 0064's accel negation; gyro-only stands as the empirical truth, and the reconciliation algebra's "coherent `diag(1,-1,1)` on both sensors" inference is retracted — refuted by hardware, not superseded by more analysis. The heading offset becomes the separately-scoped no-absolute-yaw-reference problem, closed next by 0066. Kept in the tree as a documented negative result, not deleted. |

Base: `21a8476b0` on `lab-full`; HEAD after these two `851692b11` (0064 commit `92eae558e`, 0065 commit `851692b11`).

## 0066 — WMR_CONTROLLER_SOLVE_YAW_CORRECT: anchoring fusion heading to gate-accepted constellation solves (2026-08-17, T206/T207)

| patch | what |
|---|---|
| 0066 | With dynamics correct on both hands (0062, and 0065's gyro-only conclusion), the residual left is a **constant heading offset** — there is no magnetometer, so nothing anchors yaw the way gravity anchors pitch/roll; boot attitude simply becomes the heading, exactly T207's "axes fine, pointing wrong". `WMR_CONTROLLER_SOLVE_YAW_CORRECT` (default `0.0` = off, suggested live `0.05`) fixes it by nudging fusion's heading toward the orientation implied by a **gate-accepted** constellation solve — hooked strictly inside 0047's gravity-gate acceptance path (gate off = structural no-op; this can never see an ungated sample, because an ungated sample could just as easily be a flip ghost). Reuses 0047's own identified Rx180 bridge to bring the solve into the fusion's body-frame convention, isolates yaw by swing-twist decomposition about world +Y with `atan2` extraction, and applies `gain * error` under `data_lock`, capped at 2°/step. At the suggested gain, a 90° boot offset converges in ~4-7s at the documented solve rates. Applies to both hands. Rate-limited convergence logging. Base: `851692b11` on `lab-full`, commit `b17ae1827`. |

## 0067 — wrap the solve-yaw error to ±180° and distrust ghost solves after heading lock (2026-08-17, T208)

| patch | what |
|---|---|
| 0067 | 0066's first hardware contact (T208) caught two live defects in one log. **(1) Unwrapped error**: `yaw_error_rad = 2*atan2(...)` spans `(-2π, 2π]`, so an error beyond ±180° (logged live: `-352.7°`, really `+7.3°`; `245.5°`, really `-114.5°`) stepped the long way around the circle — both controllers spun endlessly chasing it. Fixed by wrapping into `(-π, π]`. **(2) Ghost solves**: 0047's already-documented open near-pure-yaw mis-assignments land at wildly different headings with equally good reprojection error, and chasing one un-locks a heading that was already good. Fix: any error is trusted before the heading has ever locked (a boot offset up to 180° is legitimate), but once the error has been observed small (<15°, "locked"), a sudden large error (>60°) is skipped as a ghost rather than un-locking. **Result, same session**: both controllers converge and lock — left `-0.1°` after 240 corrections, right `0.0°` after 140. Wearer: "el derecho se termino acomodando a casi perfecto... lo tuve 100% bien por unos 10 segundos casi. Bien mapeado todo" — the first fully-correct controller in the project's history. Base: `b17ae1827` on `lab-full`, commit `d57f51374`. |

## 0068 — WMR_CONTROLLER_LEFT_GYRO_FIT: baked least-squares left-to-right matrix, UNSETTLED (2026-08-17, T208)

| patch | what |
|---|---|
| 0068 | With the sign flip fixed (0062) and heading anchored (0066/0067), the wearer's figure-8 on the left controller still "sigue acumulando algo y rotando de a poco drifteando sobre un eje fantasma medio combinado" — a small residual cross-axis misalignment a pure per-axis sign flip cannot remove, because non-commutative integration of even a 1-3° axis tilt winds up over a multi-turn motion instead of cancelling. Fitted from a labeled right-then-left capture (same protocol as 0062, taken **with** `WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT=1` already active, so the fit is relative to the already-sign-fixed left stream): per-phase dominant axes averaged and normalized, `M0 = A_right @ inv(A_left)` over the three phase pairs, orthogonalized via SVD (`det(M)` landed at `+1.0` without forcing it). Applies gyro-only — 0065 already measured the analogous accel extension makes things worse (precession) — gated `WMR_CONTROLLER_LEFT_GYRO_FIT` (default off, requires the Y-invert gate active; meaningless applied to the raw stream). **Honestly flagged UNSETTLED in the patch's own comment**: the fitted matrix deviates **21.8°** from identity — far beyond the 1-3° the figure-8's own qualitative description suggested — with post-fit per-phase residuals still 6-11° (down from 6.8/31.4/11.8° raw; the roll phase alone drove a 31° raw mismatch between hands). A single 8-rep-per-axis hand capture mixes real hardware asymmetry with the wearer's own left/right biomechanical asymmetry (PCA on the raw samples shows ~90%+ variance on one axis during the roll phase, for both hands independently — i.e. not sensor noise) — this sits at or below the hand-capture method's own noise floor. The live figure-8 A/B decides whether it graduates; if unclear, **the turntable protocol (constant angular rate, <1° floor, and the gain dimension a hand capture cannot measure at all) supersedes hand captures for this calibration class.** Base: `d57f51374` on `lab-full`, commit `2d7e83400`. |

## 0069 — turntable refit: roll machine-pinned, twist DOF honestly unresolved (2026-08-18, T209)

| patch | what |
|---|---|
| 0069 | The turntable audit **convicted 0068**: its roll handling was **154.8° off** the machine-measured target — the hand capture's roll phase (already flagged as the noisiest, 31° raw mismatch) had landed near worst case, and T208's figure-8 "closure" was yaw/pitch luck. Refit against the turntable's constant-rate roll data (slow fwd 0.288 rad/s + slow rev 0.279, the purity-verified modes): roll residual **0/7.2°** on held-out fwd/rev. **Structural limit stated honestly**: ONE turntable axis leaves the twist DOF about that axis undetermined, and the only available twist sources (the hand capture's pitch/yaw phases) disagree by **140.6°** at 46-58° internal noise each — `phi_pitch` chosen as less-bad and the ambiguity documented in the patch comment rather than papered over. Final residuals: roll 0/7.2, pitch 11.6, yaw carrying the 133° ambiguity. Wearer A/B matched the math: axes "girando como corresponden" but a constant roll-left+pitch-down offset on the left = the twist ambiguity made visible. The close was named in the commit itself: one more machine orientation (the 3-axis cardboard cradle) fully determines the matrix with zero human motion. Base: `2d7e83400` on `lab-full`, commit `eb642f0e9`. |

## 0070 — WMR_STICK_AUTOCENTER: per-stick center auto-calibration (2026-08-18, T209/WS2)

| patch | what |
|---|---|
| 0070 | WMR sticks ship with **no factory center calibration** (docs/23's Aircar row, 2026-08-12), and the wearer measures it directly: the left stick self-presses up+left, the right hard-left + slightly up — input drift, not pose drift (the T209 clarification that split WS2 out as its own workstream). During the first 500 samples / 5 s after the first stick packet, if the stick magnitude stays under 0.35 and unclicked, the resting mean becomes that stick's center offset, subtracted before the existing 0008 deadzone (which can then shrink from 0.15 toward 0.05). A grab or click during the window **aborts to plain deadzone with one WARN** — a wrong center is worse than none. Frozen offsets are logged as per-unit health data (same philosophy as the battery roster: per-hardware-unit numbers accumulate in the log history). Gated `WMR_STICK_AUTOCENTER`, default off pending the live A/B; `WMR_STICK_DEADZONE=0.15` became the launcher default the same night. Base: `eb642f0e9` on `lab-full`, commit `7c73ebc6a`. |

## 0071 — THE definitive left gyro matrix: machine-complete (2026-08-18, T210)

| patch | what |
|---|---|
| 0071 | **The mapping close.** With the cradle box built (second machine axis: ~yaw vertical on the turntable), the matrix is now derived from **4 machine correspondences** — T209 roll pairs + T210 cradle-yaw pairs, direction reversals pinning signs, both hands captured in both orientations — via Kabsch/SVD, `det=+1.0` unforced, **zero hand data anywhere**. The answer is physically interpretable: a near-clean **half-turn about −Y** (179.93° about (0.077,−0.997,0.001)) composed on 0062's Y-negation — the mirrored shells differ by half a turn about vertical, which is exactly what a mirrored left/right industrial design should produce. Residuals **uniform** across all four correspondences: 5.06/3.81/4.58/3.34° (RMS 4.25) vs 0069's 0/7.2/11.6/133.5 spread; full-stream verification median 3.5-4.6°. The twist moved **141.0° — within 0.4° of 0069's own documented 140.6° ambiguity: resolved, not re-guessed.** The FIT-active capture premise was verified empirically before trusting the data (7.4× residual discrimination un-fitting vs raw). **Wearer verdicts, same session**: "el 8 del joy izquierdo vuelve" (figure-8 closes), "los ejes están bien" (the constant roll-left+pitch-down offset is GONE). Known residual, named and owned: under heavy handling the left's yaw still winds slowly (~4° full-stream residual integrating); its natural healer is the 0066/0067 solve anchor, which starves exactly when hands park (sparse solves) — so the position-acquisition workstream cures both symptoms at once. Base: `7c73ebc6a` on `lab-full`, commit `535b7a75a`. |

## 0072 — WMR_HMD_GYRO_MOUNT_FIX: the HMD's own 7.34° gyro mounting misalignment (2026-08-18, T211)

| patch | what |
|---|---|
| 0072 | The head's twin of the controller-matrix saga. T211's chair-oscillation test (headset on the gamer chair — the turntable can't bear its weight — oscillated so bias cancels while a proportional leak accumulates) measured roll/pitch error growing **proportional to yaw traveled**: +0.09116 (axis0) / −0.08948 (axis2) per radian of cumulative yaw ≈ a 9% cross-axis leak. **The naive coefficient→axis reading is backwards**, caught before baking by three independent checks (exact kinematics `dR/dt = R[ω]×` at zero tilt gives `d(axis0)/dt = ω_z`, `d(axis2)/dt = −ω_x`; small-tilt-restricted regression on the real data; full nonlinear replay of the motion — all three agree): axis0's coefficient is the misaligned axis's **Z** component, axis2's is **minus X**. Misaligned axis V = (+0.08948, 0.99181, +0.09116), |leak| = 0.12774 → **7.339°**. `R_fix` = minimal rotation taking V onto true up, left-composed into `calib.gyro.transform` inside `wmr_hmd_get_imu_calib()` (Basalt consumes it as `M @ raw`, so the correction lands on top of the factory mix). Gyro-only, per 0065's accel lesson. Gated `WMR_HMD_GYRO_MOUNT_FIX`, default off. This reconciles the whole roll-drift history: at rest nothing amplifies the leak (T203's −0.027°/min sign-flipping noise); worn, it rides real head yaw (+0.84-0.93°/min, R²=0.80 — people yaw constantly, roll rarely); and it is NOT Basalt bias estimation under dynamics. **REFUTED same night (T212), before ever being enabled — keep default OFF forever.** Two held-out chair passes (the rigid-plane quorum run: 5686° yaw traveled; a clean headset-alone pass: 9518°) measured leak slopes of +0.001 to +0.011 °/° with R² 0.00-0.21 — the 9% leak did not reproduce. Worse, the original t211 dataset's own slope is unstable within its session (per-quarter axis0: +0.012→+0.090→+0.095→+0.189; axis2 flips sign in Q4) — a static mounting error must give a constant slope. And a signed cross-axis leak could never have explained T203's monotonic worn roll drift anyway (worn net yaw ≈ 0). The t211 correlation was a session-specific process (map/vision degradation), not device geometry. The patch stays in-tree as a documented negative result; **never enable it** — applying a 7.34° correction that doesn't exist would inject the very leak it claims to fix. The worn roll drift (+0.84-0.93°/min) reverts to OPEN, leading hypothesis back to Basalt gyro-bias estimation under dynamics (`gyro_bias_std`, WS5). Base: `535b7a75a` on `lab-full`, commit `b016ce4d2`. |

## 0073 — name the hand in the battery raw-byte log line (2026-08-18)

| patch | what |
|---|---|
| 0073 | The mik cell failure was diagnosed blind: the log said `81 -> 79` but not WHICH controller. `%s` from `base.base.str`, same as the keepalive line. Trivial, earned by a live failure. Base: `b016ce4d2`, commit `ed13e1395`. |

## 0074 — WMR_CONSTELLATION_YAW_PRIOR_DEG: the yaw-ghost gate (2026-08-18, T213)

| patch | what |
|---|---|
| 0074 | T213's WS3 trace capture converted "hands park" into a mechanism: **~180° yaw-flipped correspondence assignments** — structurally invisible to 0047's gravity gate (a half-turn about vertical preserves the down vector), left 13× worse than right (gate survival 5.3% vs 68.1%) while raw finds are *higher* on left; and the same ghosts starved 0066/0067's healer (post-lock, every left sample was a ghost the distrust rightly refused — ghosts still delivered *positions* though). **Code-confirmed loophole**: `pose_metrics_evaluate_pose_with_prior`'s `else if` accepts on reprojection+blob-count alone when `prior_must_match=false`, never re-checking orientation. The gate: in `constellation_sample_store` (the single caller of `m_relation_history_push`), when solve-yaw is locked, drop any sample whose bridged yaw deviates > threshold from the fusion heading — rejected ghosts never deliver position. Shares 0066's bridge math via a helper; snapshots under the existing `data_lock`; rate-limited reject log + counter. Structurally a no-op unless `SOLVE_YAW_CORRECT` is on and locked. **Known residual**: `Camera::pushPose` updates the tracker's own `last_known_pose` pre-gate, so ghosts still poison the tracker-internal recovery prior — full fix is tracker-side plumbing (future). Gated `WMR_CONSTELLATION_YAW_PRIOR_DEG` (default 0=off; live value 60). Base: `ed13e1395`, commit `21f26d360`. |

## 0075 — WMR_USER_PRESENCE: proximity sensor → XR_EXT_user_presence (2026-08-18)

| patch | what |
|---|---|
| 0075 | The G2's nose-bridge proximity sensor was always read (`control_ipd_value_decode` fills `wh->proximity_sensor`) and never consumed. Plugs into Monado's existing generic presence machinery (`supported.presence` + `XRT_INPUT_GENERIC_HEAD_DETECT` + `update_inputs`), same shape as the Rift CV1 driver — no OpenXR-layer changes needed. Threshold `!= 0` is PROVISIONAL (docs/22: never confirmed with a clean cover/uncover); INFO-logs every transition with the raw byte so the first live don/doff calibrates it. Default off; zero cost when off. Pairs with xrizer 0003 to unblock War Robots VR and give the showcase doff-to-pause. Base: `21f26d360`, commit `506bedafe`. |

## 0076 — trusted-orientation prior inside the correspondence search: the deep fix (2026-08-18, T215)

| patch | what |
|---|---|
| 0076 | 0074 rejects ghosts post-hoc — but by then the search already PICKED the ghost (true pose lost that frame) and `Camera::pushPose` poisoned `last_known_pose`. This closes the loop at the source, 8 files +515/−50, generic-tracker changes conservative: a new optional `get_trusted_orientation` callback on `t_constellation_tracker_tracking_source` (NULL for rift/pssense/wmr_hmd by construction — calloc'd structs) through which the WMR controller supplies its fusion heading, Rx180-bridged into LED-model convention, gated on `solve_yaw_locked` + the same `WMR_CONSTELLATION_YAW_PRIOR_DEG` knob (no new env). Tracker side: `pose_metrics_evaluate_pose_with_prior`'s reprojection-only `else if` (the T213-located loophole) now also requires trusted-yaw coherence; `pose_metrics_score_is_better_pose` prefers the passing lobe between two already-good candidates; `pushPose`'s `last_known_pose`/blob-marking update is gated on trusted-yaw only for opted-in calls (its unconditionality is documented load-bearing for ordinary reacquisition — byte-identical for every other device). **A/B measured (T215)**: left position presence 0.77→**4.55%** (6×), right 15.9→**30.3%**, anchor true-solve corrections 40→400; 334 tracker-side interventions while 0074's device-side layer dropped to 2 — the layering works exactly as designed. Wearer: what shows is honest and follows; left still ~95% parked = **TRUE-solve scarcity survives correct selection** — the next lever is SEEDING the search with the prior (generate the assignment from fusion attitude), not more filtering. Base: `506bedafe`, commit `d7eed079a`. |

## 0077 — WMR_CONSTELLATION_SEED_PRIOR: seeded recovery, layer 3 of the ghost saga (2026-08-18)

| patch | what |
|---|---|
| 0077 | T215 measured that judging candidates (0074 reject, 0076 prefer) is not enough — the left delivers position only 4.55% because the blind search rarely CONSTRUCTS the true-lobe assignment for its yaw-symmetric LED ring. This layer GENERATES the hypothesis: on every fast-path miss (both ordinary `tryDevicePose` attempts failed), compose a seed = `last_known_pose` position (a half-turn ghost's position error is small) + the trusted fusion orientation (0076's callback, same gating), then (1) `tryDeviceBlobRecovery` with the seed overriding the RANSAC-PnP initial guess — refinement starts in the TRUE local minimum instead of the ghost's — and (2) `tryDevicePose` with the seed as direct candidate when no labeled blobs exist. Also closes a residual 0076 gap: the un-seeded recovery call site never gated its RANSAC-PnP result against trusted yaw. Trigger choice documented: "after ghost rejection" is unobservable at any call site (a rejected ghost looks identical to found-nothing), and the miss-path placement subsumes it. Rate-limited per-device attempt/success counters. Gated `WMR_CONSTELLATION_SEED_PRIOR` (default off), byte-identical unset. **A/B DONE 2026-08-19 on the everyday rig (docs/55, T220): net-harmful AS LANDED (seed-poisoning runaway) — requires 0082's hardening, with which it is the best measured config. Wearer re-validation on dev still pending.** Base: `ed13e1395`→`d7eed079a` chain, commit `c5b8bbeb6`. |

## 0078 — WMR_CONTROLLER_HAPTICS: rumble plumbing, wire format honestly unverified (2026-08-18)

| patch | what |
|---|---|
| 0078 | "Otra cosa que no tenemos son los rumble" (user, showcase priority). The OpenXR half was already shipped (0003 binds `XRT_OUTPUT_NAME_G2_CONTROLLER_HAPTIC`) but `set_output` was never implemented for ANY WMR variant. Now: shared `wmr_controller_base_set_output` (hp + og), name/type validated, clean success no-op when `WMR_CONTROLLER_HAPTICS` is off, ≤0.01 amplitude no-op, 50 Hz per-controller throttle under `data_lock`, first-send INFO. **Wire truth table**: docs/09's Oasis disassembly proves Windows uses standard HID Haptics page 0x0E (Manual Trigger + Intensity usages) — but report IDs/offsets resolve dynamically (invisible in disassembly) and NO public source carries the tunnel byte layout (OpenHMD: HMD-only; Monado MRs: nothing; searched 2026-08-18). Candidate report `{0x06,0x03,0x03,intensity,duration_ms}` deliberately stays inside the one command family proven benign on this hardware (the status/IMU enable class). **UNVERIFIED until a controller physically buzzes** (the project's physical-verification rule applies to outputs too). Fuzz plan documented in the option comment (vary subtype; avoid the 0x00/0x04 families known to disrupt state); recovery if wedged = battery out/in. Live test: `WMR_CONTROLLER_HAPTICS=1` + SUPERHOT/Propagation trigger pull. Base: `c5b8bbeb6`, commit `fd58d9515`. |

## 0079-0082 — cross-rig A/B instrumentation fixes + 0077 hardening (2026-08-19, everyday system)

| patch | what |
|---|---|
| 0079 | Battery-scale comment confirmed (raw/255 == Windows HidP, docs/re-windows/03+06) + `WMR_CONTROLLER_TAIL_LOG` opt-in raw dump of the 12 undecoded trailing bytes (the Phase 3 mag instrument; produced docs/54's negative result). Commit `6c6d08a47`. |
| 0080 | The three per-device telemetry INFO lines (`get_tracked_pose`, gravity gate, yaw prior) now name the hand — they were unparseable in a combined two-controller log. Commit `09f580ed6`. |
| 0081 | `get_tracked_pose`'s throttled output log used a function-local static counter shared by BOTH hands: with calls interleaving evenly and an even modulo (90), the same hand wins the boundary every time and the other logs NOTHING (the 2026-08-11 note at the use site had already described this bug; the shared static crept back). Masked the left's whole stream in T220's first baselines. Per-device counter in `wcb->constellation`. **Any historical parsing of this log line is suspect.** Commit `6f63e9296`. |
| 0082 | 0077's first hardware run (T220): seed positions ran away 4m→12m, 110k attempts/session — `last_known_pose` is fed by pushPose's deliberately-unconditional update (accepts ungated position garbage; load-bearing, untouched) and the seeded attempts re-fed the poison. Fix inside `trySeededRecovery` only: prefer the predicted prior (relation history = gate-accepted samples only) over last-known, plus a 3m camera-distance plausibility bound with a rate-limited skip counter (33k poisoned attempts blocked in the validation run). With this, best measured config on the everyday rig: L 37.2% / R 22.2% pos_tracked (vs 7.9/0.8 baseline, 27.2/2.4 seed-off). Open: a few >3m seeds still passed (per-camera edge case?), and predicted-prior extrapolation itself reached 17m — bound it at the source next. Commit `9a797315a`. |

**A/B verdict (T220, docs/55): 0074+0076 validated cross-rig; 0077 requires 0082. The stack
is INERT without `WMR_CONTROLLER_SOLVE_YAW_CORRECT` (launcher sets it; a bare env A/B won't).**

| # | What & why (2026-08-19 late, T221/T222 — the trigger-blindness night) |
|---|---|
| 0083 | `WMR_CONTROLLER_CAM_EXPOSURE_US` / `WMR_CONTROLLER_CAM_GAIN` — manual override for the controller frames' FIXED 6000/100 exposure/gain (they never adapt; `WMR_AUTOEXPOSURE` is SLAM-only). A/B knob for T221's in-motion collapse (17k accepted at rest vs +0 in motion — 6 ms of exposure smears moving LED points). Defaults byte-identical; loud INFO line when non-default values run (hardware can clamp requests). Commit `5da4ccc1c`. |
| 0084 | **Pre-delivery trusted-gravity gate — T221's trigger-blindness fix.** `trySeededRecovery` fired ZERO times in a whole ghost-flood session: the tracker always "found" a wrong-lobe pose, delivered it, and 0074's device-side gate discarded 93-99.7% — from where the recovery trigger sits every ghost looked like a success, and the flood kept `solve_yaw_locked` from forming, so every yaw-gated layer was inert too. New OPTIONAL `get_trusted_gravity` tracking-source callback (gated ONLY on IMU flowing, NOT yaw lock — gravity is accelerometer truth without convergence) + `deviceGravityRejected` check at all three pushPose commit sites: a wrong-lobe candidate becomes an ordinary "not found" and the existing recovery ladder runs. Expected cascade: only true-lobe samples feed solve-yaw correction → lock can form under motion → 0076/0077 wake. Opt-in `WMR_CONSTELLATION_TRACKER_GRAVITY_GATE_DEG` (default 0; suggested 14; device-side gate stays as last line). rift/pssense byte-identical (optional callback, 0076's proven pattern). Wearer A/B pending. Commit `8cb184145`. |

## 0085 — the range check measured against the wrong frame (2026-08-19, T223, WORN)

| # | What & why |
|---|---|
| 0085 | **The bug that was eating whole sessions in silence.** `constellation_sample_store`'s sanity guard compared the sample's WORLD-frame position against a hardcoded 5 m — i.e. distance from the SLAM *tracking origin*, which also counts however far the origin has drifted. Measured worn, wearer sitting still: SLAM head pose at `(-3.50, +1.07, +7.66)`, **8.4 m from origin, no divergence reset logged** — so every CORRECT controller solve was also >5 m from origin and was dropped. The tracker went on producing good camera-relative poses (two hands 26 cm apart, 45 cm in front) at ~38/s while the driver's `sample_count` stayed frozen for minutes. Cured only by relaunch (re-anchors the origin near the wearer), which is why the failure looked intermittent and why every prior session decayed over its length. Invisible because the drop logged at `WMR_DEBUG`. **Fix = split one check into the two jobs it was doing**: (a) physical plausibility, *camera-relative*, in `Camera::pushPose` — carried as a new **per-device** `params.max_camera_range_m` (wmr 3 m; rift/pssense left at 0 = unbounded, since an external stationary camera legitimately sees objects metres away — a tracker-wide constant would have silently degraded them), gating the `last_known_pose` update as well as the publication so an impossible pose cannot become the next search's prior (0082's poisoning path); (b) absurdity, world-frame, still in the driver, now `WMR_CONSTELLATION_MAX_RANGE_M` (default **1000 m**, throttled `WMR_INFO`, names the drift interpretation). `=5` restores the old behaviour for an A/B; `=0.5` **reproduces the wearer-visible symptom on demand** (verified: wearer reported "los 2 joy anclados a dos metros a mi derecha en el mismo punto", the shared placeholder). Also logs the last fully-silent drop path (`camera has no world pose`). **Worn measurements, 60 s windows, same rig/session: baseline L 1.3% / R 2.0% → fix L 46.3% / R 47.2% → fix+0084@14° L 27.0% / R 1.8% → fix+0084@30° L 47.7% / R 45.5%.** Best worn numbers of the project, and the first time BOTH hands are present at once. Commit `df93406f9`. |

**0084's own A/B, finally measurable (it needs a working baseline to sit on):** at the suggested
14° the tracker-side gate is a NET NEGATIVE (right hand 47.2% → 1.8%, ~7000 rejects, delivery cut
4x). The rejected-angle distribution says why: real ghosts cluster at 75-105° and 135-180°, but 16
of 70 logged rejects sit at 15-30° — true-lobe samples with worn/in-motion gravity noise, far above
the 4.3-6.5° p90 the 14° default was calibrated from on a STATIC DESK capture. **At 30° the gate is
neutral on presence while still killing ghosts (~400 rejects): that is the measured value to use.**

## 0086 — make the yaw lock observable (2026-08-19, T223)

| # | What & why |
|---|---|
| 0086 | T223's named next lever needed an instrument before it could be worked at all. The residual after 0085 is the near-pure-yaw ghost class (jumps 79-100% horizontal, p50 0.35 m, both hands), the layer meant to catch it is the yaw prior, and it measured **inert**: zero rejections across a worn session while 3900 solve-yaw corrections ran. That was **ambiguous by construction** — "never locked" and "locked, and every sample agreed" are opposite diagnoses and produced identical logs. **What reading the code found is bigger than the missing log line: `solve_yaw_locked` is MONOTONIC.** It is set true the first time a gate-accepted sample lands within 15° of the fusion heading and **no code path ever clears it** (the 60° distrust window skips *learning* from a suspect sample but does not unlock). So "locked" means *has ever converged once*, not *is currently converged* — a lock acquired onto a wrong heading keeps asserting itself for the rest of the session. Two silent preconditions also surfaced: `apply_solve_yaw_correction` is reachable **only** from inside the gravity gate's sample-passed path (gate off ⇒ the lock can never form, silently), and it needs `WMR_CONTROLLER_SOLVE_YAW_CORRECT > 0`, whose own default is 0. Patch adds an unconditional `WMR_INFO` on acquisition (naming the hand per 0080, per-device counter per 0081) plus a throttled heartbeat every 300 gated samples, so a session that never locks **says so, repeatedly**, instead of being silent. Instrumentation only, no behaviour change. Built; not yet hardware-run. Commit `3854f3ac7`. |

**Next question this opens, and it is not the one we started with:** before asking why the yaw
prior never rejects, ask whether the lock it depends on is *honest*. A monotonic lock in a
ghost-flood regime can latch onto a wrong heading early and never let go.

## 0087-0088 — presence debounce, and letting the seeded hypothesis compete (2026-08-19, T224)

| # | What & why |
|---|---|
| 0087 | **Debounce for `XR_EXT_user_presence`.** T224's first hardware run of 0075 confirmed the chain works (worn = raw 1, resting = 0) and immediately showed why it could not be shipped as-is: through a real donning gesture the raw byte alternated **0,1,0,1** before settling. A title turns a presence toggle into a pause, so that flicker is a game pausing and unpausing in the wearer's face while they are still putting the headset on. Windows are **asymmetric on purpose** — `WMR_USER_PRESENCE_DON_MS` (250) to enter *worn*, `WMR_USER_PRESENCE_DOFF_MS` (1000) to leave it: a spurious resume is invisible, a spurious pause interrupts a session. Also stamps the **arrival** time of every proximity message (not just changes) and logs a throttled notice after 30 s of silence — the message is change-driven, so "the sensor calmly reports the same value" and "the companion died" are indistinguishable from the value alone, and T224 lost the doff measurement **twice** to exactly that ambiguity. The committed state is deliberately not cleared when the channel goes quiet: for a worn headset that is the safe direction. Still unmeasured (twice attempted): the doff transition itself, so both windows are choices made for their failure mode, not calibrated values. Commit `3fa3cc2b6`. |
| 0088 | **Two ways the heading-seeded hypothesis never got to compete.** (a) `pose_metrics_evaluate_pose_with_prior` granted `POSE_MATCH_GOOD` from two branches and only the else-if one (T213's loophole, closed by 0076) checked `trusted_yaw_ok`; the **prior-match branch accepted on reprojection alone** while a trusted heading disagreed, purely because the candidate landed inside the prior's own window — and that prior is fed by previously accepted samples, so one admitted mis-assignment becomes the reference that admits the next. Both branches now gate on the same already-computed boolean (vacuously true without a trusted orientation ⇒ rift/pssense byte-identical). (b) `WMR_CONSTELLATION_SEED_FIRST` (default **off**): the seeding layer 0077/0082 *is* "generate the assignment from the heading", but it runs only after every ordinary attempt fails — and the ordinary attempts seed PnP with the PREVIOUS orientation, so one that converges to a small-angle wrong local minimum inside the prior window returns first and seeding is never reached. The flag exists to A/B the reorder rather than to assert it. Commit `15214e63f`. |

**The ceiling, measured, and it is the honest headline of this pair:** the residual ghost is
**~13-25° of yaw ≈ a 1-2 LED slip around a 32-LED ring (~11° spacing)**, while the trusted
heading's own noise floor under worn motion is **10-30°**. Seeding can *narrow* the candidate
pool to the LEDs inside that cone; it cannot pick the right one within it. **Expect a better hit
rate, not the ghost's elimination.** The real lever is the heading's noise floor under dynamics —
the same gyro-bias-under-motion class as T203's round-map item 2 for the head channel — not the
correspondence search's architecture. This is the third time a threshold calibrated at rest has
failed under worn motion in this subsystem (0084 at 14°, the yaw prior at 60°, and now this).

## 0089 — blob ownership telemetry, and the hypothesis it killed (2026-08-19, T225)

| # | What & why |
|---|---|
| 0089 | Built to CONFIRM a hypothesis and it **refuted it the same night**, which is the best thing an instrument can do. T225 measured two consecutive worn windows — same build, same config, wearer changing nothing — inverting completely: **left 3.6% / right 62.1%, then left 74.5% / right 0.0%** (that 74.5% is the best single-hand figure this project has recorded). All-or-nothing with no middle ground looks exactly like a single-winner competition, and the code supports the story: every `t_blob` carries ONE `matched_device_id`, `tryDeviceBlobRecovery` needs ≥4 blobs already marked for that device, devices are iterated in fixed order. So: log, per device per frame, how many blobs it owns and whether that clears the 4-blob floor. Commit `c36953d2c`. |

**What it measured, and it does not say what it was built to say:** worn, both hands visible and
moving — mean **33 blobs present per frame**, and **both** devices own <1 on average, clearing the
floor in **10% of frames each** (8/81 and 8/81, symmetric). Room baseline with controllers hidden,
by docs/56's method: **p50 2 blobs = GREEN** (p90 13, max 23 — a tail worth tracing to a light
source eventually, not the cause here).

**Two corrections recorded rather than quietly dropped:**
1. The "blob flood" reading was hasty — 33 blobs with two controllers visible is *inside* docs/56's
   expected range (5-16 per visible controller plus a couple spurious). Nothing is swamped.
2. **The competition hypothesis is not supported by its own instrument.** With ~30 blobs unclaimed
   and neither hand reaching 4, nobody is hoarding: the failing hand has blobs available and still
   does not solve.

**A logical limit of the instrument itself, stated so it is not over-read:** blob marking happens
only *after* a successful solve (`markMatchingBlobs` runs from `pushPose`), so "owns few blobs" is
as much a *consequence* of failure as a possible cause. What separates them here is the unclaimed
surplus, not the ownership count.

**Net:** the failure is inside the correspondence search itself — not blob supply, not an unfair
split between hands. Which is where T224's ceiling argument already pointed: the candidate pool can
be narrowed, but with 10-30° of heading noise the right candidate cannot be picked within it.
**The hand inversion remains a measured, unexplained fact; only the proposed explanation is dead.**

## 0090 — companion hot-reconnect (2026-08-20, T227)

A companion silent for 500 ms is dead; re-find its current hidraw node by VID/PID, swap the handle
under `hid_lock`, re-assert the panel state. 13/13 forced re-enumerations recovered at 3.34 s
(the kernel's time, not ours). Full story docs/61; `scripts/usb-reset-device.py` is the
regression test. Retires `companion_errors` as a metric.

## 0091 — blob PHOTOMETRY per device (2026-08-20, T229/T230)

Logs per-blob area and brightness per controller: brightness saturates, area does not, which is
how the Windows-vs-Linux LED-drive asymmetry (2.45× blob area on the left ring under Windows)
became measurable. Instrument only; the LED-drive investigation is still queued.

## 0092 — pipelined pacer: advance past the previous GATE, not the shifted promise (2026-08-21, T244)

The pipelined model (T175) promised each frame one period after its gate slot, then required the
NEXT promise to clear the previous *promise* and added the shift again: promises two periods apart
by construction, every pipelined app at exactly half the panel rate. 44-45 → 58 fps alone; 89-90
with `U_PACING_APP_USE_MIN_FRAME_PERIOD=true` (now the launcher default), because the remaining
gap is `calc_app_period()` doubling on the structurally-bogus gpu column (docs/32). The whole
T243 "17-20 titles at 45/30 fps" class.

## 0093 — backlog-aware IMU clock offset (2026-08-21, T244)

A sample >50 ms late against `hw2mono` that arrived faster than real time is a draining backlog:
keep the held offset, stamp it late-but-correct. Late at the normal rate for 25 samples: genuine
offset change, re-seed. Kills the 3.5 s "from the past" rejection hole after every reader stall.

## 0094 — companion reconnect: stop blocking the IMU reader (2026-08-21, T244)

0090's post-reconnect proximity feature read never gets an answer and blocked 1.4-5.0 s inside
the shared run loop. Default off (`WMR_COMPANION_RECONNECT_RESYNC=1` re-enables); the run loop now
warns on any step >50 ms, which is the instrument that named it. With 0093: 66 natural drops in
one session, zero SLAM holes, wearer no longer relocated. docs/06.

## 0095 — join the camera USB thread in `wmr_camera_stop()` (2026-08-21, T244 close)

`wmr_camera_stop()` cancelled the transfers and deactivated the stream but never joined
`cam->usb_thread`, so `wmr_cam_usb_thread` could still be inside `img_xfer_cb() → pop_pose()`
while `wmr_hmd_destroy()` tore the tracker down on another thread — the teardown SIGSEGV on 20+
cores (`thread apply all bt`, NEXT-STEP's correction #1). Adds
`os_thread_helper_stop_and_wait(&cam->usb_thread)` right after the cancel loop, the precedented
pattern from `constellation_tracker_node_break_apart`. Vulnerable code is byte-identical to
upstream: upstreamable.

## 0096 — `wmr_camera_start()` never set `cam->running` (2026-08-22)

Which made 0095 dead code: `wmr_camera_stop()`'s `if (!cam->running) return;` guard skipped the
join (and the cancel loop) on every teardown. Sets `running = true` once all transfers are
submitted. **Not closed**: the same night a SIGSEGV with a DIFFERENT shape (directly in
`receive_frame`, `t_tracker_slam.cpp:2080`, with the main thread stuck in
`libnvidia-eglcore`/`ioctl`) showed a second race between the EGL/Vulkan teardown and the camera
thread that this join does not cover — race #2 in docs/06 / the 2026-08-22 plan (docs/67). Treat
"teardown crash fixed" as unverified until the EGL-side ordering is instrumented.

## 0097 — SLAM_PRED_FREEZE_POSITION + SLAM_PRED_NECK_ARM_MM (seated 6dof head)

Two env-gated refinements to `t_tracker_slam.cpp::predict_pose()` (both default off = no change)
that make seated head 6dof feel like 3dof — the 2026-08-26 wearer A/B on Aircar, "super similar
a windows" (docs/80). `SLAM_PRED_FREEZE_POSITION=1` holds position at the last SLAM anchor
(clears the linear-velocity valid bit before `m_predict_relation`) so a fast head yaw's real
arc velocity isn't extrapolated across the ~150 ms latency into a ~50 cm overshoot that
accumulated to metres. `SLAM_PRED_NECK_ARM_MM=<mm>` then swings the frozen eye along the
neck-pivot arc as orientation is predicted forward (`pos += (R_pred - R_anchor)·arm`), fixing
the orientation/position timestamp split; 150 mm measured best. The recommended seated recipe
also enables the existing `SLAM_CORRECTION_SPREAD_MS=50` (not new code) to stop the periodic
re-anchor snap. Auto-applied to Aircar by `scripts/vr-launcher.py`'s TITLE_PROFILES.

## 0098 — `WMR_FORWARD_ANGULAR_VELOCITY` (opt-in, default off)

`wmr_hmd_get_slam_tracked_pose()` always cleared `ANGULAR_VELOCITY_VALID_BIT` before returning,
so SteamVR's own photon-time extrapolation/reprojection always saw zero head angular velocity
regardless of real motion. Forwards the SLAM tracker's own already-predicted angular velocity
(not the 3dof path's stale `fusion.last_angular_velocity`), axis-corrected the same way position
already is. Independent origin, reimplemented fresh against this codebase: inspired by a gap the
same community fork this project has been reviewing (`Faulto/reverb-g2-linux`, see
`handoff-20260827-faulto-patches/`) found and fixed on their own fork. **Open risk, not
resolved**: whether this double-counts against 0097's own prediction when both are active —
not measured, flagged for whoever runs the wearer A/B.

## 0099 — `SLAM_SESSION_ANCHOR_RADIUS_CM` + `SLAM_QUAT_NORM_CHECK` (opt-in, both default off)

Two more divergence guards alongside 0023-a's speed-based one, for failure modes it cannot see:
slow accumulated drift (many small steps, none individually fast enough to trip the speed
threshold) and a corrupted orientation quaternion riding along a plausible-looking position.
Reuse the existing `auto_reset`→`tracker_reset()` response path verbatim, including 0057's
frame-continuity carry. `SLAM_SESSION_ANCHOR_RADIUS_CM` requires `SLAM_RESET_OFFSET_CARRY` on
(the default) — without it, logs a warning and stays off rather than silently no-op'ing on a
meaningless comparison. **Real, disclosed limitation**: because `reset_offset` re-anchors the
output pose onto wherever drift already carried it, a slow-drift trip is not self-healing the
way a speed-spike trip is — it can keep re-firing (rate-limited to the ~2s quiet window) until
real motion or the tracker's own loop closure brings position back under the radius; may be more
useful as a diagnostic signal than a recovery mechanism as shipped. Both checks compare via a
NaN-safe negated range rather than this file's usual direct-threshold form — two independent
adversarial reviews caught that a direct `x < lo || x > hi` form lets a NaN pass through
completely undetected, exactly the corrupted-pose case `SLAM_QUAT_NORM_CHECK` exists to catch.
Independent origin, reimplemented against this codebase's actual current machinery: inspired by
the same community fork's (`Faulto/reverb-g2-linux`) independently-arrived-at anchor-radius and
quaternion-sanity checks on a different Monado fork base. Reasoned addition, NOT a live-incident
fix — **NOT YET HARDWARE-VALIDATED**, both default off pending a wearer A/B.
