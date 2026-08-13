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
