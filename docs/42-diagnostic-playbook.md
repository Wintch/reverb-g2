# Diagnostic playbook: how the 2026-08-17 tracking bugs were found

This is the reasoning path of one long diagnostic session on the everyday system
(KDE/X11/NVIDIA-550/60 Hz, same physical rig as dev, with the turntable fixture from
`docs/38`). It is written to be **reused as a method**: each step is
`Symptom -> Hypothesis -> How tested -> Result -> Conclusion`, and it seeds future
**automation** of hardware/driver diagnostics (last section). The tools and exact commands are in
`docs/32` (measurement toolkit); this document is the *why* and the *order*. The full root-cause
write-ups are `docs/39` (SLAM collapse) and `docs/40` (constellation CPU blow-up).

## The one rule

**Test every hypothesis against live data before believing it, and treat a refuted hypothesis as
progress.** Most guesses below were wrong, and each measured-and-discarded guess narrowed the
search. The ones that felt most obvious (companion storm, constellation starves SLAM) were the
ones that fell.

---

## Thread 1: SLAM pose-rate collapse (root-caused, fixed, validated)

Symptom: after some minutes of load the SLAM output pose rate collapses from ~30 Hz to ~1.5 Hz and
never recovers. Detail and fix: `docs/39`.

### Step 1.1: make it reproducible first
- **Symptom:** collapse appears "sometimes" during long sessions, so it is unmeasurable.
- **Hypothesis:** sustained SLAM + constellation load triggers it.
- **How tested:** controller on the turntable (`docs/38`) at constant omega, hands-free soak.
- **Result: CONFIRMED.** Collapse reproduced twice at **~10 min onset**.
- **Conclusion:** a repeatable experiment; you cannot bisect a bug you cannot summon.

### Steps 1.2 to 1.6: ruled out
- Companion storm / error 0049: collapse reproduced with only ~10 companion errors, no storm.
- Environment (dev/Wayland/90 Hz): same collapse on a different stack (X11/KDE/60 Hz), so it is a
  portable Basalt-pipeline bug.
- CPU scheduling: an earlier perf trace showed no scheduling smoking gun.
- VIO backend / window growth: env-gated `vit_vio` logging in
  `sqrt_keypoint_vio.cpp::optimize_and_marg` showed `opt_ms` about 2-3 ms, `marg_ms` about 0.2 ms
  and small, stable state sizes at collapse.
- Optical-flow keypoint growth / patches leak: `vit_of` logging showed `keypoints` stable at ~300
  and `recall` disabled (`patches=0`).

### Step 1.7: which stage eats the 600 ms?
- **How tested:** `vit_loop` logging split the frontend loop into `pop_ms` (image-queue wait) and
  `imu_ms` (`processImu` duration).
- **Result: CONFIRMED, the cause.** At collapse `imu_ms = 573-634 ms` while every other stage is
  under 10 ms; `imu_ms` alternates ~600 ms / ~0.001 ms, matching the bimodal output.
- **Conclusion:** `FrameToFrameOpticalFlow::processImu()` integrates IMU up to the image timestamp
  with a **blocking** `input_imu_queue.pop`. Once frames drop, image time runs ahead of the
  arriving 250 Hz IMU stream and the loop waits ~600 ms per frame, self-sustaining.

### Step 1.8: the clock cross-check (a wrong fix that proved the right thing)
- **Hypothesis:** the position "pops" and this collapse share a clock-drift root, so the pops fix
  `WMR_CLOCK_MIN_LATENCY=1` should delay the collapse.
- **Result: half confirmed, half refuted.** Onset moved from ~10 min to ~27 s, so the shared clock
  root is real, but the min-latency path leaves `hw2mono` stale and diverges faster. Do not deploy
  it (negative result; see `docs/52` and `docs/44`).

### Step 1.9: fix and validation
- **Fix:** `BASALT_IMU_NONBLOCK_CATCHUP`: the catch-up loop uses `try_pop` and extends the last
  sample to the image time when the queue empties. It is a strict no-op on the healthy path.
- **Validated:** turntable soak with the flag on, 919 s (past the ~10 min onset): zero collapse,
  max `imu_ms` 99 ms over 18 419 samples. Default flipped ON.

---

## Thread 2: constellation correspondence-search CPU blow-up (found, fixed)

Full write-up: `docs/40`.

### Step 2.1: where is the CPU going?
- **Symptom:** `monado-service` at high average CPU; rotational judder under load.
- **How tested:** per-thread snapshot with `top -H`.
- **Result:** with the controller spinning, a distributed ~10 %-per-thread TBB pool (~158 %). With
  the **controllers off**, CPU *rose* to **614 %** with **3 threads pegged at 90-100 % in state
  `R`**. Idle target, higher CPU.

### Step 2.2: busy-loop or blocked?
- `/proc/<pid>/task/<tid>/{syscall,wchan}` on the pegged TIDs: `syscall = running`, `wchan = 0`
  means a userspace busy-loop, not I/O wait (and not the companion storm).

### Step 2.3: what is it spinning on? (poor-man's gdb profiler)
- No `perf` yet (`perf_event_paranoid=3`), so `gdb -p PID -batch -ex "thread apply all bt"`
  matched to the hot TIDs: all three in the constellation correspondence search
  (`correspondence_search.c`: `search_pose_for_model -> generate_led_match_candidates ->
  select_k_leds_from_n / select_k_blobs_from_n -> check_led_against_model_subset ->
  lambdatwist_p3p`).

### Step 2.4: why does it explode with no target?
- The search runs per model per frame over all blobs x 32 model LEDs with depth combinatorics
  (`MAX_BLOB_SEARCH_DEPTH=5`, `MAX_LED_SEARCH_DEPTH=8`) and a P3P solve per candidate. There is
  **no wall-clock budget**; the only early-out is `POSE_MATCH_STRONG`. With controllers off there
  are only spurious room-light blobs, so the match fails every frame, never prunes, and expands
  fully across 4 cameras x 2 controllers.

### Step 2.5: fix and validation
- **Fix:** `WMR_CONSTELLATION_SEARCH_BUDGET_US`, a per-model wall-clock deadline; default `0` (off),
  `3000` caps each search at 3 ms.
- **Validated (controllers OFF):** `614 % -> 261 %`, pegged cores gone.

### Step 2.6: does the budget harm real tracking? (the gate, and it failed)
- **How tested:** controller spinning on the turntable, budget 3 ms vs 0, same lighting; counted
  poses found vs "failed to find a pose".
- **Result: REFUTED.** Budget ON: **0** found / 1603 failed. Budget OFF: **19** found / 1304
  failed. In this box's blob-swamped scene (mean 22-27 blobs/obs) the search sometimes needs more
  than 3 ms to find the valid P3P.
- **Conclusion:** do not default the 3 ms budget on; it needs a smarter guard (blob-count guard or
  controller-present gate, see `docs/40`). Underneath: even budget-OFF tracking barely works here
  (~1.4 % success), so blob swamping (an exposure/threshold issue) is the real
  controller-tracking blocker on the everyday system.

---

## Thread 3: the SLAM frame drops (re-attributed)

### Step 3.1: did fixing the constellation CPU stop the drops?
- **Symptom:** ~1/3 of SLAM input frames drop steadily; `vit_collapse OUT wall_ms` averages ~45 ms.
- **Result: REFUTED.** CPU fell `614 % -> 261 %` but the drop rate barely moved (`~11 -> ~10 /s`).
  The constellation CPU was waste but not the drop cause.

### Step 3.2: what is the SLAM frontend spending its frame on?
- **How tested:** clean `vit_of total_ms` (matching the full line to dodge log interleaving) plus a
  `gdb` stack of the hot Basalt thread.
- **Result:** `vit_of` mean **35.4 ms**, max 173.6 ms, **37 % of frames > 33 ms**; hot thread:
  `basalt::detectKeypointsWithCells <- addPointsForCamera <- addPoints <- processFrame <-
  processingLoop`.
- **Conclusion:** optical-flow keypoint (re)detection exceeds the ~33 ms camera frame interval, so
  the frontend drops frames. Distinct from the `processImu` collapse and from constellation. Open
  question: why `addPoints` runs so often; best chased on dev at 90 Hz.

---

## Toward unattended diagnostics

The end goal is a VR station that, when something fails, already has everything on hand to
diagnose it. Most checks above are mechanical enough to automate:

- **Per-thread CPU-peg detector + busy-loop classifier.** Watch `top -H`; for any thread near a
  full core, read `/proc/<tid>/{syscall,wchan}`. `syscall=running` + `wchan=0` = userspace
  busy-loop: capture a `gdb`/`perf` stack automatically and file it (how Thread 2 was found).
- **Collapse detector.** Trip when `imu_ms` (or `OUT wall_ms`) sustains above a threshold (e.g.
  300 ms) for N consecutive frames; distinguishes the Thread-1 collapse from ordinary load.
- **Drop-rate monitor.** Track the slope of the cumulative `dropped` counter; a steady positive
  slope under static conditions is the Thread-3 signature.
- **Constellation search-time watchdog.** With the per-model budget in place, alert when the
  deadline fires often: either no target (expected) or a real matching problem.

**Standing agenda item:** the `*_LOG=trace` / `VIT_COLLAPSE_LOG` firehoses are
investigation-only. In an unattended autostart they must be **OFF by default** (they add I/O and
interleave across threads, corrupting naive parsing, see `docs/32`). The autostart script needs
clear modes: interactive dev (verbose), or clean shutdown that writes nothing extra when idle
(`docs/43`).

See also `docs/38` (turntable fixture), `docs/39`, `docs/40`, and `docs/32` (exact commands).
