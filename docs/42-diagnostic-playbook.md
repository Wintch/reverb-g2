# Diagnostic playbook — how the 2026-08-17 tracking bugs were found (step by step)

This is the narrated reasoning path of one long diagnostic session on the everyday system
(KDE/X11/NVIDIA-550/60 Hz, same physical rig as dev — only the SSD is swapped — with the
turntable fixture from `docs/38`). It is written to be **reused as a method**, not just read:
each step is `Symptom → Hypothesis → How tested → Result → Conclusion`, and it is meant to seed
future **automation** of hardware/driver diagnostics (see the last section, and the tool
reference in `docs/41`).

## The one rule that made this work

**Every hypothesis was tested against live data before it was believed, and a refuted
hypothesis was treated as progress, not failure.** Most of the guesses below were *wrong* — and
each wrong guess, measured and discarded, narrowed the search until the real cause had nowhere
left to hide. When a prediction failed, the instrumentation was doing its job. Do not skip the
measurement because a hypothesis "obviously" holds; the ones that felt most obvious (companion
storm, constellation-starves-SLAM) were the ones that fell.

The tools used at each step (env-gated instrumentation, the poor-man's `gdb` profiler, `top -H`,
`/proc/<tid>/{syscall,wchan}`, `perf`, the turntable) and exactly how to run them are in
**`docs/41` (diagnostic toolkit)**. This document is the *why* and the *order*; that one is the
*how*.

---

## Thread 1 — SLAM pose-rate collapse (root-caused, fixed, validated)

The headline symptom: after some minutes of load the SLAM output pose rate collapses from a
healthy ~30 Hz to ~1.5 Hz and never recovers. Detail and the final fix live in `docs/39`; this is
the path that got there.

### Step 1.1 — Make it reproducible before diagnosing anything
- **Symptom:** collapse appears "sometimes" during long sessions — not on demand, so unmeasurable.
- **Hypothesis:** a sustained SLAM + constellation load triggers it.
- **How tested:** put a controller on the turntable (`docs/38`) at constant ω, hands-free, and
  let it soak.
- **Result: CONFIRMED.** The collapse reproduced twice in a row at **~10 min onset**, hands-free.
- **Conclusion:** now it is a repeatable experiment. Everything below depends on this — you cannot
  bisect a bug you cannot summon.

### Step 1.2 — Is it the companion storm / error 0049?
- **Symptom:** a known companion-error storm (2026-08-16: 472k errors, 430 % CPU) was the prime suspect.
- **Hypothesis:** the collapse *is* the storm.
- **How tested:** reproduced with only ~10 companion errors present (no storm).
- **Result: REFUTED.** Collapse happened with no storm.
- **Conclusion:** independent of the companion path.

### Step 1.3 — Is it the environment (dev/Wayland/90 Hz specific)?
- **Hypothesis:** it is something about the lab stack.
- **How tested:** reproduced on a completely different stack (this everyday system, X11/KDE/60 Hz).
- **Result: REFUTED.** Same collapse.
- **Conclusion:** a portable Basalt-pipeline bug, not environment-specific.

### Step 1.4 — Is it CPU scheduling?
- **Hypothesis:** the compositor/SLAM threads are being starved by the scheduler.
- **How tested:** an earlier perf trace (T195) already covered this.
- **Result: REFUTED.** No scheduling smoking gun.
- **Conclusion:** the stall is inside the pipeline, not around it. Instrument the stages.

### Step 1.5 — Is it the VIO backend / unbounded window growth?
- **Symptom:** collapse looks like the optimiser bogging down.
- **Hypothesis:** `optimize()`/`marginalize()` time or the sliding-window state grows without bound.
- **How tested:** env-gated `vit_vio` logging in `sqrt_keypoint_vio.cpp::optimize_and_marg`.
- **Result: REFUTED.** At collapse `opt_ms ≈ 2–3 ms`, `marg_ms ≈ 0.2 ms`; `frame_states=2`,
  `frame_poses=7`, `marg_H=57`, `landmarks ≈ 29` — small and **stable**, not growing.
- **Conclusion:** the backend is innocent. The cost is upstream, in the frontend.

### Step 1.6 — Is it optical-flow keypoint growth or a patches/recall leak?
- **Hypothesis:** the frontend accumulates keypoints or leaks recall patches.
- **How tested:** `vit_of` logging of `keypoints` and `patches` in the optical-flow frontend.
- **Result: REFUTED.** `keypoints` stable ~300; `recall` disabled (`patches=0`), so the known
  patches-leak cannot apply.
- **Conclusion:** not keypoint compute either. Time each *stage* of the frontend loop directly.

### Step 1.7 — Which stage actually eats the 600 ms?
- **How tested:** `vit_loop` logging split the frontend into `pop_ms` (image-queue wait) and
  `imu_ms` (`processImu` duration).
- **Result: CONFIRMED — the cause.** At collapse `imu_ms = 573–634 ms` while every other stage is
  `< 10 ms` (`pop_ms ≈ 0.0004 ms`, `processFrame ≈ 10 ms`, VIO ≈ 3 ms). `imu_ms` alternates
  ~600 ms / ~0.001 ms frame-to-frame, matching the bimodal output.
- **Conclusion:** `FrameToFrameOpticalFlow::processImu()` blocks. It integrates IMU up to the
  current image timestamp with a **blocking** `input_imu_queue.pop`. Once frames drop, each
  processed image is ~600 ms newer than the last and the image time runs *ahead of the arriving
  IMU stream*, so the loop waits in real time for 250 Hz IMU to catch up — ~600 ms per frame,
  self-sustaining (the block delays the frontend → more images pile up and drop → bigger jumps).

### Step 1.8 — The clock cross-check (a wrong fix that proved the right thing)
- **Hypothesis:** the position "pops" and this collapse share a clock-drift root; the pops fix
  `WMR_CLOCK_MIN_LATENCY=1` should also delay/prevent the collapse.
- **How tested:** ran the identical repro with only that flag added.
- **Result: half CONFIRMED, half REFUTED.** Onset moved **~10 min → ~27 s** (first `imu_ms>300`
  at frame 823) — a single change to the `hw2mono` update path moved onset ~20×, so the
  **shared clock root is real**. But it made things *worse*, not better: the min-latency
  implementation leaves `hw2mono` stale, diverging faster. The fix is **counterproductive; do not
  deploy** (kept only as a negative result).
- **Conclusion:** fix `processImu` directly — it stops the collapse regardless of clock behaviour
  and is contained. The clock/pops root is real but needs a different, harder approach.

### Step 1.9 — The fix and its validation
- **Fix:** `BASALT_IMU_NONBLOCK_CATCHUP` — the catch-up loop switches the blocking pop to
  `try_pop` and extends the last sample to the image time when the queue empties, instead of
  stalling. It is a **strict no-op on the healthy path** (`try_pop` == the old blocking pop
  whenever the 250 Hz IMU is already ahead of the image time, i.e. always except during the
  pathological empty-queue collapse).
- **How validated:** turntable soak with the flag on, **> 15 min (919 s uptime)**, well past the
  ~10 min onset. **Zero collapse.** Over 18 419 clean `imu_ms` samples the max was **99 ms** (rare
  transient, self-recovering), typical ~0.002 ms; cooler stayed quiet (no CPU spin). Two
  independent watchers agreed.
- **Result:** default flipped **ON**. See `docs/39`.

---

## Thread 2 — Constellation correspondence-search CPU blow-up (found, fixed)

Started as "attack the sustained CPU and the SLAM frame drops." Full write-up in `docs/40`.

### Step 2.1 — Where is the CPU actually going?
- **Symptom:** `monado-service` sits at a high CPU average; the felt problem is rotational judder,
  which points at frame-timing under load.
- **Hypothesis (initial):** the turntable's constellation load (tracking the spinning controller)
  steals CPU from SLAM.
- **How tested:** per-thread snapshot with `top -H` under load.
- **Result: partial.** With the controller **spinning**, load was a distributed ~10 %-per-thread
  TBB pool (~158 % instant). But then the user turned the **controllers off** — and CPU *rose* to
  **614 %** with **3 threads pegged at ~90–100 % in state `R`**. Counter-intuitive: idle target,
  higher CPU.
- **Conclusion:** the profile changed shape (distributed pool → 3 pegged cores) exactly when the
  controllers went off. Classify those 3 threads.

### Step 2.2 — Busy-loop or blocked?
- **How tested:** `/proc/<pid>/task/<tid>/{syscall,wchan}` on the 3 pegged TIDs.
- **Result:** all three `syscall = running`, `wchan = 0` → **running in userspace, not blocked in
  any syscall = a busy-loop**, not I/O wait. (And *not* the companion storm: log errors were
  rate-limited, ~17 in 20 k lines.)
- **Conclusion:** something spins in userspace when the controllers are unreachable. Get its stack.

### Step 2.3 — What is it spinning on? (poor-man's gdb profiler)
- **How tested:** no `perf` yet (`perf_event_paranoid=3`), so `gdb -p PID -batch -ex "thread apply
  all bt"`, matched to the hot TIDs.
- **Result:** all three threads in the **constellation correspondence search**
  (`src/xrt/tracking/constellation/correspondence_search.c`):
  `search_pose_for_model → generate_led_match_candidates → select_k_leds_from_n /
  select_k_blobs_from_n → check_led_against_model_subset → lambdatwist_p3p` (plus Eigen
  `vec3_normalize` in the same math).
- **Conclusion:** the combinatorial LED↔blob matcher is the hog, not the companion path and not
  Basalt.

### Step 2.4 — Why does it explode with no target?
- **How tested:** read the search driver. It runs, per model per frame, over all blobs × all 32
  model LEDs with depth combinatorics (`MAX_BLOB_SEARCH_DEPTH=5`, `MAX_LED_SEARCH_DEPTH=8`) and
  a P3P solve per candidate. `search_start_time` exists but is compiled out unless `DUMP_TIMING`
  and used only for logging — **there is no wall-clock budget.** The only early-out is
  `POSE_MATCH_STRONG`.
- **Result:** with controllers off there are no real LEDs, only spurious room-light blobs, so the
  match **fails every frame → never prunes → full exhaustive expansion every frame**, across 4
  cameras × 2 controllers. That is why it is *worse* than controllers-on: a real target yields a
  strong match that prunes early.
- **Conclusion:** classic un-bounded search that degenerates in its no-match worst case.

### Step 2.5 — The fix and its validation
- **Fix:** `WMR_CONSTELLATION_SEARCH_BUDGET_US` — a per-model wall-clock deadline computed before
  the anchor loop; once exceeded the search stops for that model this frame, keeping the best
  match so far. Default `0` (off, unbounded) preserves old behaviour; `3000` caps each per-model
  search at 3 ms. A real target normally matches well inside the budget, so the deadline only
  bites the pathological no-match case; a pose missed on one frame is recovered on the next.
- **How validated (controllers OFF = worst case):** `614 % → 261 %`, **pegged cores gone** (top
  thread ~40 %, state `S`).
- **Result:** kills the no-target CPU runaway — real, keepable. Default left OFF pending a
  controllers-ON real-tracking check (Step 2.6). See `docs/40`.

### Step 2.6 — Does the budget harm real tracking? (the gate — and it failed)
- **Hypothesis:** a real target matches well inside 3 ms, so the budget should not cost real poses.
- **How tested:** controller spinning on the turntable, budget ON (3 ms) vs OFF (0), same
  lighting/position; counted poses found vs "failed to find a pose".
- **Result: REFUTED — the budget cuts real matches.** Budget ON: **0** found / 1603 failed. Budget
  OFF: **19** found / 1304 failed. Under this box's blob-swamped scene (mean 22-27 blobs/obs, real
  LEDs buried in spurious room-light blobs) the search sometimes needs > 3 ms to find the valid P3P,
  and the deadline cuts it off first.
- **Conclusion:** do **not** default the 3 ms budget on. It needs a smarter guard than a blanket
  wall-clock cap (blob-count/swamping guard, or a controller-present gate — see `docs/40`). And note
  the bigger finding hiding underneath: even budget-OFF, tracking barely works here (~1.4 % success)
  — the **blob swamping** (an exposure/threshold issue) is the real controller-tracking blocker on
  the everyday system, orthogonal to the search budget. A clean-lighting re-test belongs on dev.

---

## Thread 3 — The SLAM frame drops (re-attributed; still open)

### Step 3.1 — Did fixing the constellation CPU stop the drops?
- **Symptom:** ~1/3 of SLAM input frames drop steadily; `vit_collapse OUT wall_ms` averages ~45 ms.
- **Hypothesis:** the constellation search was starving the SLAM frontend of CPU → drops; the
  search budget should fix them.
- **How tested:** measured drop rate and CPU with the budget on vs off, same conditions.
- **Result: REFUTED.** CPU fell `614 % → 261 %` but the drop rate barely moved (`~11 → ~10 /s`),
  and `OUT wall_ms` stayed ~45 ms.
- **Conclusion:** constellation CPU was real waste but **not** the drop cause. Look inside the SLAM
  frontend itself.

### Step 3.2 — What is the SLAM frontend actually spending its frame on?
- **How tested:** clean `vit_of total_ms` (matching the full line to dodge log interleaving) plus a
  `gdb` stack of the hot Basalt thread.
- **Result:** `vit_of` mean **35.4 ms**, max 173.6 ms, **37 % of frames > 33 ms**; the hot thread
  is `basalt::detectKeypointsWithCells ← addPointsForCamera ← addPoints ← processFrame ←
  processingLoop`.
- **Conclusion:** the optical-flow **keypoint (re)detection** cost exceeds the ~33 ms camera frame
  interval, so the frontend cannot keep up and drops frames. This is **distinct** from the
  `processImu` collapse (Thread 1) and from constellation (Thread 2).
- **Next probe (open):** why is `addPoints` running so often (keypoints lost each frame? image
  quality? cell config? max-keypoints?). **Better chased on dev at 90 Hz**, where the judder is
  actually felt and where optical-flow cost — being build/driver-dependent — is the relevant number.

---

## Toward unattended diagnostics ("arkade vr")

The end goal is a VR station that runs itself and, when something fails, already has everything on
hand to diagnose it — low-maintenance, self-sufficient. Most of the checks above are mechanical
enough to automate; each became a one-line signal once understood:

- **Per-thread CPU-peg detector + busy-loop classifier.** Watch `top -H`; for any thread pegged
  near a full core, read `/proc/<tid>/{syscall,wchan}`. `syscall=running` + `wchan=0` = userspace
  busy-loop → capture a `gdb`/`perf` stack automatically and file it. (This is exactly how Thread 2
  was found.)
- **Collapse detector.** Trip when `imu_ms` (or `OUT wall_ms`) sustains above a threshold (e.g.
  > 300 ms) for N consecutive frames. Cheap, and it distinguishes the Thread-1 collapse from
  ordinary load.
- **Drop-rate monitor.** Track the cumulative `dropped` counter's slope; a steady positive slope
  under static conditions is the Thread-3 signature.
- **Constellation search-time watchdog.** With the per-model budget in place, log/alert when the
  deadline fires often — it means either no target (expected) or a real matching problem.

**Standing agenda item (not yet done):** the `*_LOG=trace` / `VIT_COLLAPSE_LOG` firehoses used
throughout this session are **investigation-only**. In an unattended autostart they must be **OFF
by default** (they add I/O and interleave across threads, corrupting naive parsing — see `docs/41`).
The autostart script needs **clear modes**: either you enter to continue dev work (verbose,
interactive), or the station shuts down cleanly and **writes nothing extra** when idle. No stray
logs, no half-open sessions — "these things don't ask to be fed."

See also `docs/38` (turntable fixture), `docs/39` (collapse root cause + fix), `docs/40`
(constellation CPU blow-up + fix), and `docs/41` (diagnostic toolkit — the exact commands).
