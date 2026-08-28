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
| 0002 | measured 2026-08-13 (T180), wearer verdict pending | Caps `input_img_queue` at 2 (was 10) and makes `push_frame` drop the OLDEST frame instead of blocking. With the optical flow slower than the camera (~26 fps processed vs 30 in, at every thread count tried) the 10-slot queue sat permanently full: pure latency, every frame ~380 ms old before the frontend saw it, and the pose Monado anchors dead reckoning to was 0.5–0.9 s stale — measured as the delivered head pose wandering 10–25 mm at rest over a raw SLAM at 0.3–0.9 mm. `vio_enforce_realtime` drops downstream of this queue and measurably does nothing here. After: frame→pose age p50 819 ms → **109 ms**, delivered position residual at rest p50 9.8 mm → **0.57 mm** (p90 24.6 → 1.23). Deterministic mode keeps the lossless blocking push. |
| 0003 | instrumentation, verified live 2026-08-17 (T192-T195) | `VIT_COLLAPSE_LOG=1` on `vit_tracker`: logs input-side (`push_frame`) and output-side (`pop_state`) rate, frame-timestamp spacing, input-queue depth, and cumulative drops. Written to diagnose the T192-T195 SLAM pose-rate collapse (abrupt, permanent ~17 Hz → ~1.5 Hz, near-constant ~640 ms stall) — the discriminator for input starvation / bad timestamps / queue backpressure at onset. Off by default, one getenv. |
| 0004 | instrumentation, verified live 2026-08-17 | `VIT_COLLAPSE_LOG` deep-VIO variant: times `optimize()` vs `marginalize()` separately and logs `frame_states`/`frame_poses`/`landmarks`/marg-prior dimension per frame, looking for a structure that grows unbounded over the collapse's ~10 min onset. Reproduced the collapse live on a second, completely different machine (KDE/X11/NVIDIA-550/60Hz) with no companion storm at all — confirming it's a portable Basalt VIO bug, not an environment or hardware artifact. Off by default. |
| 0005 | instrumentation, verified live 2026-08-17 | `VIT_COLLAPSE_LOG` frontend variant: times `processFrame` and `recallPoints()` and logs tracked-keypoint count plus the `patches` map size (a suspected leak per `addPoints`'s own TODO, though `recall_enable=false` here so it doesn't apply). Localized the stall to upstream of the VIO backend — 0004 already showed `optimize`/`marginalize` staying ~2-3 ms with bounded state. Off by default. |
| 0006 | instrumentation, verified live 2026-08-17 | `VIT_COLLAPSE_LOG` loop-wait variant: times the input-image pop wait and `processImu` specifically, inside the optical-flow loop. Confirmed the ~600 ms is in `processImu`'s blocking IMU catch-up, not compute — `processFrame` (~10 ms) and VIO opt/marg (~2 ms) both stay fast during the collapse. Off by default. |
| 0007 | root-cause fix, default OFF at this commit, 2026-08-17 | **The fix.** `BASALT_IMU_NONBLOCK_CATCHUP=1` switches `processImu`'s IMU catch-up from a blocking `input_imu_queue.pop` to `try_pop`: integrate whatever is buffered and extend the last sample to the image timestamp, instead of blocking in real time for the 250 Hz IMU stream to catch up. Root cause (`docs/39`): during the collapse each processed image is ~600 ms ahead of the arriving IMU (frames dropped ~18-at-a-time off the bounded `input_img_queue`), so the blocking pop stalls ~600 ms per frame — and the stall itself causes more frames to pile up and drop, making it self-sustaining. Strict no-op on the healthy path: `try_pop` returns exactly what the blocking pop would whenever the IMU is ahead of the image time, i.e. always except during the pathological empty-queue collapse. Default OFF, pending a drift A/B — see 0008. |
| 0008 | validated 2026-08-17, default ON | Flips `BASALT_IMU_NONBLOCK_CATCHUP`'s default to ON — unset, or set to anything not starting with `0`/`f`/`F`, now enables it; set `=0` to restore the old blocking behaviour for an A/B. Validated over a >15 min turntable soak (919 s uptime, well past the ~10 min collapse onset): **zero collapse**, 18 419 clean `imu_ms` samples with max 99 ms (rare, self-recovering) against the old permanent ~600 ms pin, cooler quiet the whole time. Two unrelated things surfaced under the same sustained load, both explicitly **not** a regression of this fix (`imu_ms` itself read ~0.002 ms typical): ~3997 cumulative dropped frames and `OUT wall_ms` averaging ~47 ms, plus `monado-service` at ~468% CPU — root-caused separately in `docs/40-constellation-search-cpu-blowup.md` to Basalt's own optical-flow keypoint-detection cost exceeding the camera frame interval (unrelated to this patch or to constellation), with the constellation correspondence-search CPU sink addressed independently by `patches/monado/0051`. |
| 0009 | measured NEGATIVE result, 2026-08-17 (T197) | `BASALT_VISION_NONBLOCK` (default ON) caps `vision_data_queue` — the OF→VIO handoff, the third and last blocking latency reservoir on the live path after 0001 (state output) and 0002 (image input) — at capacity 2 (was 10) and pushes into it drop-oldest, same policy as the other two. Written against a measured plateau: with the VIO backend saturating at ~63-66 ms/frame, the stock capacity-10 blocking queue fills once during an early burst and (arrival rate == service rate) never drains, pinning delivered-pose age at capacity × service time ≈ 632 ms — T192/T194's collapse period, finally sourced to a second, independent mechanism from 0007/0008's `processImu` block. **Measured counterproductive on the very next relaunch**: with drop-oldest, the backend only ever consumes the newest survivor (frames arrive ~400 ms apart), every one of them crosses the keyframe threshold, and per-frame cost explodes 66 → ~400 ms (full `optimize`+`marginalize` every time) — a self-reinforcing ratchet down to **2.5 Hz output**, the old collapse signature reborn. Superseded by `0010` in the same session; kept as the documented negative result, not reverted. See `docs/pruebas.jsonl` T197. Base: `ae697f9` on `lab` (on top of `2a67f76`). |
| 0010 | validated 2026-08-17 (T197), same-session correction of 0009 | Demotes drop-oldest to opt-in (`BASALT_VISION_DROP_OLDEST=1`, default OFF) and makes the default push into the capacity-2 `vision_data_queue` **blocking**. Keeps 0009's actual fix (short queue, ~632 ms latency reservoir gone) while moving the shedding back to the input side, where 0002's drop-oldest already runs at an equilibrium the backend tolerates (~66-72 ms/frame at rest, most frames non-keyframe) instead of forcing every surviving frame past the keyframe threshold. Confirmed live in the same session: backend back to 66-72 ms/frame at rest. `BASALT_VISION_DROP_OLDEST=1` is kept only to reproduce 0009's negative result on demand. See `docs/pruebas.jsonl` T197. Base: `696a02f` on `lab`. |
| 0011 | validated 2026-08-17 (T204/T205) | Caps `ExecutionStats::add()`'s per-key `data_` vectors (`std::vector<double>` and `std::vector<Eigen::VectorXd>` overloads both) at 65536 entries instead of appending unconditionally. On the live Monado path these vectors are pure dead weight — appended on every VIO solve, some keys once per Gauss-Newton iteration, never read, never cleared — and were found to be the dominant term of a measured **~72 MB/h RSS growth over a 9h session (356 MB → 1 GB)**. Offline evaluation runs, which *do* read these via `print()`/`save_json()` against a finite dataset, rarely reach the cap; a live session now simply stops accumulating past it instead of growing for the process lifetime. Bounded worst case: 65536 doubles × ~16 keys ≈ 8 MB. Found by the same night's parallel leak-hunt workstream that also produced `patches/monado/0060`'s `pose_destroy` fix. Base: `time_utils.cpp` on `lab`, commit `ae2e9dae3`. |

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

## 0013 — `VIT_DUMP_CALIB=<path>`: dump the live calibration as a Basalt JSON (2026-08-27)

The calibration Basalt actually runs with (cameras + IMU, pushed by Monado's WMR driver
through `add_camera_calibration`/`add_imu_calibration` from the headset's own config) only
ever crossed the VIT interface at runtime — nothing exported it, so `basalt_vio` could not
replay a recorded `EUROC_RECORD=1` dataset with the numbers the live tracker used. In
`Tracker::Implementation::initialize()`, once both calibrations are applied and asserted
present, serialize `calib` with the same `cereal::JSONOutputArchive` `print_calibration()`
already uses, to the given file. Env-gated, default off, no other effect.

Why: Aircar 6dof drifts metres on fast yaw, and per-frame data (docs/80, 2026-08-27 night)
shows the backend landmark count collapsing under yaw (p10 = 0 above 90 °/s) while the
frontend keeps ~2600 keypoints. Testing backend configs live costs a wearer session each;
with this dump plus one recorded session, `scripts/replay-basalt-variants.py` replays every
config offline against the identical input. The offline runner itself (`basalt_vio`,
`src/vio.cpp`) is built in a **separate** `~/vr/basalt/build-tools` dir with
`BASALT_BUILD_SHARED_LIBRARY_ONLY=OFF` — it needs Pangolin unconditionally (`vio.cpp`
includes its headers; `BASALT_BUILD_VISUALIZATION=OFF` does not remove that) but never opens
a window with `--show-gui 0`. The production `libbasalt.so` in `build/` stays Pangolin-free
(re-checked after this patch: `nm -D | grep -c pangolin` = 0).

## 0014 — `prunePatches()`: bound the recall patch map (2026-08-27)

`optical_flow_recall_enable` (landmark recall — re-find a landmark that left the frame and
came back, exactly the sweep-and-return case a fast yaw produces) had an unbounded memory
leak: `addPointsForCamera()` saves a pyramid patch for **every** newly detected keypoint and
nothing ever erased them (Basalt's own "TODO: Patches are never getting deleted"). Measured
live with the G2 lying still: +1,953 patches/frame, 7.5 M patches and an **18 GB RSS after three
minutes** — killed before it OOM'd the 32 GB box. The same run showed what recall is worth: the
backend's landmark count went from p50 12 / p10 5 to **p50 70 / p10 55** over the same frames
(with `vio_marg_lost_landmarks: false`, which recall needs — see docs/80), at 0.2 ms p99.

A patch is only ever read by `recallPointsForCamera()` for ids in `latest_lm_bundle` (the
backend's live landmark set). `prunePatches()` runs once per frame after `filterPoints()`:
stamps every id currently tracked in any camera or present in the latest bundle with
`frame_counter`, and once a second erases patches unseen for more than `grace` frames. The
bundle arrives asynchronously a few frames behind the frontend; the default grace of 90 frames
(3 s at 30 fps) covers that lag with margin. `BASALT_RECALL_PATCH_GRACE_FRAMES` overrides it;
`0` restores the old unbounded behaviour for an A/B. `patches.at()` → `find()` in the recall
loop so a pruned id means "cannot recall this one", never `std::out_of_range` on the frontend
thread. No effect at all when recall is off (the default). Soak results in docs/80.

## 0015 — build recall patches in parallel in `addPointsForCamera()` (2026-08-27)

With recall on, the frontend's new hot spot was not recall itself (~1 ms p99) but building the
`levels+1` pyramid patches for each of the ~2,000 keypoints detected per frame, in a sequential
loop: frontend `total_ms` p50 28 → 42–49 ms, p99 40 → 100–117 ms on the G2 — over the 33 ms
frame budget at the median (soaks G′ and I, docs/80). Every patch is independent (reads the
const pyramid, writes its own storage), so they are now built first with `tbb::parallel_for`
over the detections, then the original sequential bookkeeping runs (id assignment,
`addKeypoint`, map insertion — cheap). Same patches, same ids, same order; Basalt's own quirk
of sampling pyramid 0 for every camera is untouched. No effect when recall is off. The
measurement of what it buys is the I2 soak (I on 0015) in docs/80: ~4 ms at the median
(42 → 38), less than hoped — the p99 was somewhere else (0016).

## 0016 — amortize `prunePatches()`' sweep (2026-08-27)

0014 erased the whole recall patch map (200–400k entries) once every 30 frames, in one frame.
Measured live (K soak on 0015): **63 of 63 frontend frames over 80 ms sat exactly on
`frame_counter % 30 == 0`** — p50 88 ms on the sweep frames vs 37.7 ms on every other. Now the
sweep frame only snapshots the key set (a flat copy of ids, ~1 ms) and each following frame
checks-and-erases 1/29th of the snapshot, so the erasures spread evenly across the second; keys
inserted after a snapshot are looked at next second. `patch_last_seen`'s patch-less entries age
out on a separate phase (`frame % 30 == 15`). Same bound, same grace, no full-map pass in a
single frame. No effect when recall is off. Measured by the I4 soak (I on 0016) in docs/80.

## 0017 — `VIT_CAM_TIME_OFFSET_NS`: shift the camera frame stamps against the IMU (2026-08-27)

The wearer's yaw recording (docs/80, `euroc-yaw_20260827170436`) replayed offline with the
camera timestamps moved by −10 / −5 / +5 / +10 ms and the IMU untouched: the position drift
over ten 400–600 °/s head turns went **0.24 / 0.30 / 0.96 (unshifted) / 1.72 / 4.21 m** —
monotonic, huge, and yaw-specific (pitch and roll barely move), i.e. the frame stamps Monado
hands to Basalt are *later* than the exposure by at least 5–10 ms. Basalt has a
`calib.cam_time_offset_ns` field for exactly this but never applies it (the line in
`sqrt_keypoint_vio.cpp` is commented out), so this patch adds the one knob that exists: an
env-gated `int64` added to `partial_frame->t_ns` where the frame enters the tracker
(`vit_tracker.cpp`, `push_img_sample`); the cam0/camN equality assert is adjusted to match;
`frames_original_timestamp` and the IMU path are untouched. Negative = earlier. Default 0 = no
effect. The dataset shift used offline and this variable have the same sign. The value is
being pinned by the J-config sweep (−5 … −30 ms) in docs/80; the permanent fix belongs in how
Monado's WMR camera driver stamps frames, once the number is known. *(Pinned the same night:
−5 and −10 ms tie, −15 is worse; Monado patch 0101 `WMR_CAM_TS_MID_EXPOSURE` is the driver-side
form. Worn, −7 ms was indistinguishable from 0 on config J.)*

## 0018 — `prunePatches()`: no full scan of `patch_last_seen` (2026-08-27)

0016 amortized the sweep of `patches` but left `prunePatches`' other map on a full walk every 30
frames: `patch_last_seen` entries without a patch (bundle ids from before a reset, ids detected
while recall was off) were aged out by iterating the whole map (~300 k entries) in one frame —
the exact unamortized-sweep shape 0016 had just removed one map over, and a likely part of the
p99 tail measured live on config J (frontend p99 77 ms). Now `patch_last_seen` is only stamped
for ids that own a patch (`patches.count()` guard, ~2.5–5 k hash lookups per frame), which
makes it a subset of `patches`' keys, so the existing amortized sweep erases an expired
patch and its stamp together and nothing is left behind; the separate scan is gone. Same grace,
same bound, no behaviour change when recall is off. Found by the frontend code read in docs/80.

## 0019 — per-stage timing in the `vit_of` line (2026-08-27)

`recall_ms` only brackets `recallPoints()`; the recall-gated patch build lives in `addPoints()`
and `prunePatches()` runs after `filterPoints()`, so "recall p99 2.8 ms" next to a 46 ms
frontend was attributing nothing. With `VIT_COLLAPSE_LOG=1` the line now ends with
`pyr_ms= track_ms= detect_ms= filter_ms= prune_ms=` (steady-clock deltas: pyramid build;
frame-to-frame tracking; `addPoints()` = FAST detection + cam0→camN matching + the patch build;
`filterPoints()`; `prunePatches()`), appended after the existing fields so every parser that
reads the first five keeps working. Zero cost when the env var is unset (the stamps are inside
`if (of_log)`). The first frame prints zeros. Use it before turning any frontend knob.

## 0020 — `age_in_ms` / `age_out_ms` on the collapse-log lines (2026-08-28)

`vit_collapse IN` now ends with `age_in_ms` = now − frame stamp (exposure → tracker input:
USB transfer, decode, hw2mono, input queue) and `vit_collapse OUT` with `age_out_ms` = now −
frame stamp (exposure → pose out of the VIO). `std::chrono::steady_clock` is `CLOCK_MONOTONIC`
on glibc, the clock Monado stamps frames with, so the subtraction is meaningful. Together with
Monado's 0102 (`pose age ms`, display side) this splits the wearer's latency into transport /
Basalt / Monado. First worn numbers (Aircar, config P2): transport **11.4 ms flat** (p99
13.3), Basalt in→out **p50 59 / p90 170 / p99 265 ms** with the frontend at 29 / 39 / 53 —
the tail is queueing, not processing (→ 0021). Only under `VIT_COLLAPSE_LOG=1`.

## 0021 — `VIT_QUEUE_DEPTH`: both live queues to n (default 2) (2026-08-28)

The image input queue and the optical-flow → VIO queue were each capped at 2 (0002 / the
`BASALT_VISION_NONBLOCK` block) when the backend was saturated at ~66 ms per frame
(2026-08-17). With config P2 the backend runs 17 ms p50 / 32 p90 — not saturated — and
0020 showed the pose leaving Basalt up to 170–265 ms after exposure: 2 + 2 slots let the
pipeline run four frames deep after a single slow frame. `VIT_QUEUE_DEPTH=1` bounds that to
~2 frames + processing; a frame is dropped only on a real stall (the IMU covers 33 ms). The
2026-08-17 negative result for drop-oldest on the vision queue (every surviving frame became a
keyframe) needed a saturated backend and 400 ms gaps; it is re-checked, not assumed. Default 2
= unchanged; clamped to [1, 10]; deterministic mode ignores it as before.
