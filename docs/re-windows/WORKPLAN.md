# Work plan — compile & validate the RE-driven fixes (comms ↔ dev)

Coordinated plan interleaving comms-box work (🖥️ write code/docs, compile-check —
where the Windows RE intel lives) with dev/hardware work (🔌 real build + headset-on
validation). Legend: 🖥️ = comms box (me), 🔌 = dev + you (physical/hardware).

## Context

We now have the full Windows WMR RE cross-reference (this folder). Active bugs, in
priority order:
1. **SLAM pose-rate collapse (T192–T195)** — blocks everything; fix first.
2. **Position pops** — the yaw/rotation timestamp jitter (`02`, `05`).
3. **Magnetometer decode bug** (`03`).
Companion storm backoff (`0049`) is **DONE** — hardware-verified in T192, not part of
this plan except that the SLAM collapse first surfaced alongside it.

Machine split: docs/patches sync via this canonical GitHub repo; **monado source
syncs via git bundle** (real commit objects, never patch replay — see `docs/30`).
Verification is **physical** (`CLAUDE.md`): headset-on, human confirms; no conclusion
from logs/FPS alone. Pin the machine first (`scripts/vr-power-setup.sh`).

## Phase 0 — Sync & handoff

- 🖥️ Commits prepared in this repo (RE docs + this plan). **Not pushed** — awaiting review.
- 👤 You review → we push.
- 🔌 Reconnect dev: USB reseat to **5/5** (per `docs/22`/T174 — winning cell = other
  rear port + flipped C-plug; verify `lsusb -t` 5/5, cameras at 5000M). Boot lab OS.
- 🔌 On dev: `git pull` this repo; pin the machine (`vr-power-setup.sh --apply`).

## Phase 1 — SLAM pose-rate collapse  (PRIORITY)

Why first: it drops head tracking to ~1.5 Hz permanently mid-session, so any pops/mag
validation is meaningless while it can fire. T194 reproduces it in <1 s with
SLAM+constellation alone (no app); T195 **ruled out the scheduler** → it's a
logical lock/queue/timeout in code. The near-constant ~632–648 ms interval reads like
a **fixed timeout firing repeatedly**.

- 🖥️ Prepare an instrumentation patch on `lab-full` (comms `~/Documents/linux_vr_base/monado`):
  - Log every SLAM pose-push timestamp + the read-loop wait/return times, to catch the
    exact transition at collapse onset.
  - Hunt a ~640 ms timeout (or a sum of timeouts) in the SLAM/source read path and the
    Basalt input queue (`basalt lab-current` already "bounds the optical-flow input
    queue and drops the oldest frame" — check for stall/backpressure there).
  - Instrument the **timestamp deltas** at onset (`02-clock-model.md`): if device
    timestamps go bad, the pipeline can gate/stall.
  - Cross-check against Windows' approach (`05`): rate-based staleness + **cross-stream
    restart** (`CameraReaderLoopRestartingIMU`) — Windows restarts a wedged stream
    instead of collapsing; that's the mechanism to borrow if a stream is wedging.
  - **Confirm pre-existing**: reproduce WITHOUT `0049` (open question from T192/T193).
  - Compile-check here → export bundle → dev.
- 🔌 On dev: rebuild (real ninja), reproduce the <1 s collapse, capture the
  instrumentation, headset-on confirm the tracking recovers with the fix. Log to
  `docs/pruebas.jsonl`.

## Phase 2 — Position pops

- 🖥️ Implement in `src/xrt/drivers/wmr/wmr_source.c` (the `m_clock_offset_a2b` /
  `hw2mono` path, ~line 180):
  - (a) **Decouple the offset-EMA update cadence from the IMU sample rate** — pre-filter
    over ~64 samples (~256 ms) and feed only the minimum-latency `(now_hw, now_mono)`
    pair per window (`02-clock-model.md`).
  - (b) **Add LKG / outlier rejection** to the offset update — reject an unusable update
    and keep last-known-good instead of smoothing every sample (`05`, Windows' optical
    timesync). Keep the existing `IMU_JITTER_MAX_NS`/`IMU_MIN_STEP_NS` floor as a net.
  - Compile-check → bundle → dev.
- 🔌 On dev: rebuild; validate with rotate-in-place + the **turntable at constant ω**;
  `HELLO_XR_POSE_STATS=1`; compare backwards-time events (baseline 281/session, p99
  14.7 ms) before/after. Headset-on: does rotation feel like Windows? Log Txxx.

## Phase 3 — Magnetometer decode  (small, high-confidence)

- 🖥️ Decode the real **3-axis mag** triplet from the controller report's undecoded
  trailing bytes (`03-controller-packets.md`); resolve the battery "UNVERIFIED SCALE"
  comment (Windows `(raw*100)/255` == Monado `raw/255`). Compile-check → bundle.
- 🔌 On dev: rebuild; sanity-check mag values feed the fusion; headset-on regression check.

## Sync mechanics (monado source, comms → dev)

1. 🖥️ All code changes on branch `lab-full` in comms `~/Documents/linux_vr_base/monado`;
   compile-check with the compiler command from the lab build's `compile_commands.json`.
2. 🖥️ `git bundle create <name>.bundle lab-full`, verify, copy to dev.
3. 🔌 dev: `git fetch <bundle> lab-full:lab-full` into `~/vr/monado`, checkout, real
   `ninja` build. **Never hand-apply loose patches** (divergent-history trap, T068).

## After each phase

Record the result in `docs/pruebas.jsonl` (new Txxx), update `patches/monado/` if the
change is keeper, and only then move to the next phase.
