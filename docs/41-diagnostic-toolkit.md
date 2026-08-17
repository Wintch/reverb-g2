# Diagnostic toolkit — tools we used and why (2026-08-17)

A reproducible, headset-agnostic-where-possible reference of every diagnostic tool used to
root-cause the SLAM pose-rate collapse (docs/39), the constellation correspondence-search CPU
blow-up (docs/40), and the SLAM optical-flow frame drops. The goal is that someone can replay
this method on another HMD, or on the dev machine, without rediscovering the tooling. For the
step-by-step reasoning path and conclusions, see the playbook in docs/42.

## Approach (read first)

- **Measure before fixing.** Every fix in this session was preceded by a measurement that
  pinned the mechanism. Several attractive hypotheses were killed by data (see docs/42).
- **Every hypothesis is a testable prediction.** Turn each guess into a number you can read
  from a log or a profiler, then go look. A refuted hypothesis is progress, not a setback.
- **Env-gate everything.** Instrumentation and candidate fixes are behind environment
  variables so you can A/B them on the exact same rig, and so they can be turned OFF in an
  unattended run. Turntable motion (docs/38) makes the "same rig" repeatable.

---

## perf — sampling profiler (which functions burn CPU)

- **Purpose:** find the hot functions in a running process without stopping it. First reach
  for this when a process is eating CPU and you want to know *where*.
- **Availability this session:** installed mid-session (`perf` v6.12.101). The kernel had
  `kernel.perf_event_paranoid = 3`, which **blocks kernel-stack sampling**; userspace-only
  sampling still works. For kernel frames: `sudo sysctl kernel.perf_event_paranoid=1` (or run
  `sudo perf`).
- **Usage:**
  ```bash
  perf record -F 999 -p <PID> -g -o out.perf -- sleep 8
  perf report -i out.perf --stdio | head -40
  ```
- **What to look for:** the top self-time symbols and their call chains (`-g`). Symbols are
  real if the target is built `RelWithDebInfo` (both monado and Basalt are here).
- **Gotchas:** `perf_event_paranoid` value matters (`>=2` disallows kernel profiling, `>=3`
  restricts more); a warning about "kernel profiling" does not mean userspace sampling
  failed. Set it permanently in `/etc/sysctl.conf` if you want kernel stacks routinely.

## Poor-man's gdb profiler — the star of this session

When `perf` was not yet available, this cracked the constellation CPU blow-up. It is a
"sampling by hand": stop the process briefly, dump every thread's stack, detach.

- **Purpose:** identify exactly what a pegged thread is doing, by call stack, when you can't
  use perf.
- **Usage (find the hot threads, then read their stacks):**
  ```bash
  # 1) per-thread CPU, hottest first
  top -H -b -d 2 -n 2 -p <PID> | awk '/COMMAND/{h=1;next} h&&NF>10' | sort -k9 -rn | head -6

  # 2) classify a hot TID without stopping anything
  cat /proc/<PID>/task/<TID>/syscall   # "running" = in userspace, not in a syscall
  cat /proc/<PID>/task/<TID>/wchan     # "0" = not sleeping in the kernel
  awk '{print $3}' /proc/<PID>/task/<TID>/stat   # R = running, S = sleeping

  # 3) dump all thread stacks (brief stop, then detaches)
  gdb -p <PID> -batch -nx -ex "set pagination off" -ex "thread apply all bt 12" > bt.txt
  # map a hot LWP to its stack:
  grep -nE 'LWP <TID>' bt.txt
  ```
- **Key signature:** `syscall = running` **and** `wchan = 0` **and** state `R` = a **userspace
  busy-loop** burning a core (not blocked on I/O). That is what exposed the unbounded
  constellation search — three threads all in `lambdatwist_p3p ← ... ← search_pose_for_model`.
- **Gotchas:**
  - All monado threads share the process name `monado-service` (none call
    `pthread_setname_np`), and `top -H`'s COMMAND column truncates to it. **Map threads by
    stack, not by name.**
  - `/proc/<PID>/task/<TID>/stack` (kernel stack) needs root and only shows the kernel side;
    the gdb userspace backtrace is what you want here.
  - gdb `-p` briefly SIGSTOPs the whole process. Safe for a not-worn headset in a diagnostic
    session (the DRM lease is kernel-side and survives a brief stop); avoid it while a user is
    actively in-headset.

## top -H — per-thread CPU

- **Purpose:** see how CPU splits across a process's threads (one pegged core vs. a
  distributed thread pool tells you busy-loop vs. parallel numeric work).
- **Usage:** `top -H -b -d 2 -n 2 -p <PID>` — take the **second** sample (the first is a
  cumulative average, not the instantaneous delta).
- **What to look for:** `%CPU` is **per core** (a single thread can read up to 100%). One
  thread at ~100% `R` = a busy-loop; a cluster of ~10% threads = a parallel worker pool (e.g.
  Basalt/TBB). Note that `ps -o %cpu` reports a **lifetime average**, which can differ a lot
  from the instantaneous `top` figure — cross-check both.

---

## Env-gated instrumentation & fix toggles

These are read from the environment by monado/Basalt at launch (via `jack-in.sh`, which
propagates ambient env). They are **firehoses** meant for investigation — in an unattended
run they must be OFF (see the standing agenda in docs/42).

| Variable | Pipeline | What it logs / does |
|---|---|---|
| `VIT_COLLAPSE_LOG=1` | Basalt SLAM/VIO | Per-frame `vit_collapse IN/OUT` (wall_ms, frame-ts gap, input queue depth, `dropped`), `vit_loop` (`pop_ms` image-wait, `imu_ms` processImu time), `vit_of` (optical-flow `total_ms`, keypoints, patches), `vit_vio` (optimize/marginalize ms, state sizes). This is the SLAM-collapse instrument (docs/39). |
| `CONSTELLATION_TRACKER_LOG=trace` | Controller constellation | Blob observations, pose solves, samples, reproj error, matched_blobs. **Separate from `WMR_LOG`** — don't confuse them; `WMR_LOG=trace` is an unrelated USB/IMU firehose. |
| `HELLO_XR_POSE_STATS=1` | OpenXR client | Per-frame pose jitter/quality numbers from the `hello_xr` client. |
| `BASALT_IMU_NONBLOCK_CATCHUP` | Basalt frontend | The processImu collapse fix (docs/39). **Default ON** now; set `=0` to restore the old blocking pop for an A/B. |
| `WMR_CONSTELLATION_SEARCH_BUDGET_US` | Constellation search | Per-model correspondence-search wall-clock deadline in microseconds (docs/40). **Default `0` = off/opt-in**; e.g. `3000` caps each per-model search at 3 ms. |
| `WMR_CONSTELLATION_CONTROLLERS=1` | Constellation | Enables the controller constellation path at all (not exported by `jack-in.sh` — set it explicitly, or nothing tracks controllers). |

**Parsing trap (important).** monado/Basalt log these per-frame lines with `iostream` from
several threads at once. The writes **interleave and concatenate numbers** — e.g. two lines
collapse into `66.40690.001804`, or a timestamp bleeds into an `imu_ms` field
(`136615764332720.003196`). A naive `grep -oE 'imu_ms=[0-9.]+'` then reports impossible values
(a `max` of 99 with a `count>300` of 9). **Always match the full, anchored, clean line before
extracting**, e.g.:
```bash
grep -oE '^vit_of total_ms=[0-9.]+ recall_ms=[0-9.]+ keypoints=[0-9]+ patches=[0-9]+$' log \
  | sed -E 's/vit_of total_ms=([0-9.]+).*/\1/'
grep -oE '^vit_loop pop_ms=[0-9.eE+-]+ imu_ms=[0-9.eE+-]+$' log | sed -E 's/.*imu_ms=//'
```

---

## Turntable fixture — constant-ω load & stimulus

- **Purpose:** a cheap motorized turntable spinning a controller at a selectable, ~constant
  angular velocity. Hands-free, repeatable, and runnable for an hour+. It is what made the
  SLAM collapse reproducible on demand (~10 min of sustained load) and is the repeatable
  stimulus for A/B tests and gyro calibration. Full write-up: **docs/38**.
- **What to look for:** it keeps the controller **awake** (otherwise LEDs dim/blink and blob
  detection dies) and drives the controller IMU + the head cameras' view of the LEDs. It does
  **not** move the head, so it loads the *constellation* pipeline, not head SLAM directly —
  keep that split in mind when reading results.
- **Gotcha:** sweep its speeds to separate rate-dependent effects; and remember that a
  constellation-heavy load can still starve unrelated pipelines via shared CPU.

## Through-the-lens camera + `scripts/analyze-panel-judder.py`

- **Purpose:** measure rotational judder / dropped displayed frames by filming the panel
  *through the lens* with a high-frame-rate camera while the scene rotates, then counting how
  many camera frames each displayed frame persists for (irregular persistence = judder).
- **Usage:** high-fps capture through the lens → `ffmpeg` frame extraction → the OpenCV script
  (`reverb-g2-linux/scripts/analyze-panel-judder.py`) for the per-frame luminance/diff series.
- **Gotcha (critical):** **do not film at an exact multiple of the refresh rate** (e.g. 90 Hz)
  — the aliasing hides the very drops you are trying to see. The script warns when the camera
  fps is a multiple of 90.

---

## Process hygiene (between runs)

- Kill cleanly (`kill -TERM`, escalate to `-KILL` only if needed), verify the PID is gone, and
  **remove the stale IPC socket** before relaunching:
  ```bash
  kill -TERM <PID>; sleep …; kill -0 <PID> 2>/dev/null && kill -KILL <PID>
  rm -f /run/user/1000/monado_comp_ipc
  ```
- Confirm which shared library is actually loaded (monado dlopens Basalt at runtime):
  ```bash
  grep -i basalt /proc/<PID>/maps | awk '{print $6}' | sort -u
  tr '\0' '\n' < /proc/<PID>/environ | grep -E 'BUDGET|NONBLOCK|CONSTELLATION|COLLAPSE'
  ```
  — this catches "I rebuilt but the old `.so`/env is still live" before it wastes a run.

---

This toolkit and the docs/42 playbook are the human-readable seed of the unattended
"arkade vr" hardware/driver diagnostic automation — a station that runs itself and has every
diagnostic already at hand when something fails.
