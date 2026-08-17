# Camera clock-domain skew (T196-T198) — ROOT CAUSE PROVEN for the 632-666 ms magic number and the constant ~1 s wearer lag

> **Status: PROVEN, not yet fixed.** The camera frame timestamps that reach Basalt (and
> stamp its output poses) run **p50 +578 ms (max +610, n=121) in the FUTURE** of the clock
> that pose queries and IMU-for-prediction live in. This is a single, stable, code-level
> bias — not hardware, not CPU load, not the scheduler (already ruled out, T195) — and it
> unifies three findings that until tonight looked like three separate problems.

## The one number, and how it was measured

Monado patch `0052` adds a rate-limited (~1 line/s at 250 Hz) `SLAM_INFO` at the dead-reckoning
call site in `predict_pose()` (`t_tracker_slam.cpp`):

```
pred: anchor age %.1f ms (when_ns=... rel_ts=...)
```

`when_ns` is the query clock (the same clock the IMU-for-prediction rings live in);
`rel_ts` is the timestamp on the anchor (the latest filtered SLAM pose) that dead reckoning
integrates forward from. Read live and interleaved within milliseconds with Basalt's own
`vit_collapse IN ... t_ns=` lines (patch `basalt/0003`, which log the newest camera-frame
stamp on every frame Basalt ingests), two numbers came out of the same log:

1. **Anchors LOOK 50-112 ms old** to the predictor (intermittent 677-810 ms spikes), which
   is why dead reckoning never trips its own staleness/failure path — a live grep for the
   failure-path log line came back with **zero hits** across the whole session. Dead
   reckoning is healthy and always runs.
2. **Anchor CONTENT is ~630-700 ms stale.** Newest-camera-frame-stamp minus `when_ns`, taken
   from the same interleaved log, is **p50 +578 ms, max +610 ms (n=121)**: the camera
   timestamps that end up in that anchor are, at the moment they were captured, already
   ~0.6 s ahead of the clock the query itself reports as "now".

Put the two together: the anchor's *stamp* says it's fresh (50-112 ms old); the anchor's
*content* is actually ~630-700 ms old. The gap between those two readings is exactly the
camera clock's forward bias. Dead reckoning is not broken — it is doing exactly what it is
told, integrating from a timestamp that lies about how old the data underneath it is.

## What one bias explains, all at once

**docs/39's collapse mechanism.** `docs/39-slam-collapse-root-cause.md` root-caused the
T192-T195 SLAM pose-rate collapse to `processImu()` blocking on a large IMU catch-up
because "each processed image is ~600 ms newer than the previous one" — i.e. the image
timestamp runs ahead of the arriving IMU stream. `patches/basalt/0007`/`0008` fix the
*symptom* (don't block indefinitely waiting for IMU to catch up to a timestamp that was
never going to arrive on time) and are verified working on real hardware (T196: 11 minutes
under the exact minimal repro that used to collapse in under a second, `imu_ms` mean 0.0066
ms vs the old ~600 ms pin). Tonight's finding says *why* the image timestamp was ahead of
IMU in the first place: it isn't ahead of the IMU stream specifically, it's ahead of the
shared clock domain both are measured against, by a bias that happens to be close to that
same ~600 ms.

**The 632-666 ms "magic number."** T192/T194/T195 measured the collapsed pose interval as
suspiciously tight — 632-666 ms, roughly ±1% jitter — across every run, including across
entirely separate `monado-service` processes and (T39's own note) a completely different
machine. That stability is exactly what a fixed, code-level conversion bias looks like:
not organic system noise, not hardware, a constant baked in near session start (see
hypothesis below) and then held for the life of the process.

**The constant ~1 s wearer latency.** T197's wearer session on the collapse-fixed stack
found the lag is not rate, it's a flat, constant delay — "muy claro y sin cortes, pero con
delay constante de aprox 1 segundo", present from the very first head movement and not
draining at rest. `pose-lag.py` in the same session showed prediction contributes
essentially nothing (delivered lags raw SLAM content by only +80 ms; filtering→prediction
residual +0.0 ms / 0.00%) — the staleness is not being introduced or hidden downstream, it
arrives already baked into the anchor. Because dead reckoning trusts the anchor's stamp
(50-112 ms old) rather than its true content age (~630-700 ms), it only ever integrates the
~90 ms the stamp admits to — the other ~0.6 s of real staleness is invisible to a predictor
that has no reason to distrust its own timestamps. Monado does not re-stamp on delivery:
`flush_poses` uses `data.timestamp` verbatim, so the bias that enters at the camera-to-mono
conversion rides untouched all the way to the application.

## What produced this proof, in order

1. A sonnet agent read the full prediction path end to end — `t_tracker_slam.cpp`,
   `t_dead_reckoning.c`, `m_predict.c`, `m_filter_fifo.c`, `wmr_hmd.c`/`wmr_source.c` — and
   found the anchor source (`slam_rels.get_latest`), the IMU rings it predicts from
   (`gyro_ff`/`accel_ff`, 1000-entry count-bound), that there is **no horizon cap** on how
   old an anchor can be, and a no-partial-credit `return false` fallback path that silently
   delivers the bare stale anchor on failure — plus the fact that the failure path already
   logs by default, which turned out to be moot (zero hits).
2. `monado/0052` added the 12-line diagnostic above at the one call site that discriminates
   "anchor looks fresh but isn't" from "anchor is genuinely fresh." Off nothing — it is
   diagnostic-only INFO, always on at `SLAM_LOG=info`, ~1 line/s.
3. One service cycle (panel stayed dark on the first attempt — the companion device had
   re-enumerated after the service already opened it, a known, already-documented class of
   fault, not a new one) and the log carried both anchor ages and interleaved
   `vit_collapse IN` camera-frame stamps within milliseconds of each other, which is what
   let the two be subtracted directly instead of inferred.

## Honest scope

- **This was measured at the tracker layer** (Monado's `predict_pose`, cross-referenced
  against Basalt's own `vit_collapse IN` stamps), **not yet at the ingest site itself.** The
  claim is "the timestamps Basalt/Monado's tracker see are +578 ms ahead of query-now," not
  yet "here is the exact line in `wmr_source.c` that produces the bias."
- **The startup-burst hypothesis (below) is a hypothesis, not a measurement.** It is
  consistent with everything observed (constant per session, portable across machines,
  indifferent to load) but has not been isolated with a direct before/after log at the
  conversion site.
- **The relationship between +578-610 ms and the 632-666 ms collapse period is close but
  not identical**, and that gap is noted here rather than explained away. They may be the
  same constant measured two different ways (session-start anchoring vs. steady-state
  collapse period) or two related-but-distinct numbers; nothing in tonight's data settles
  which.

## Next step, surgical

Read `wmr_source.c`'s `cam_hw2mono` / clock-offset estimation path and log, at the ingest
push site, `converted_ts - os_monotonic_get_ns()` directly — a three-line diff that turns
"the tracker sees a +578 ms bias" into "here is where it enters and why." **Leading
hypothesis**: the offset estimator anchors its fit during the startup burst of ~19 buffered
camera frames that arrive at process start (19 × 33 ms ≈ 630 ms) — close to both the
measured bias and the collapse period — which would make the bias a constant fixed near
session start, and therefore: constant per session (matches), portable across machines
(matches, it's arithmetic not hardware), and indifferent to load (matches, nothing in T196
or T197 moved it by re-loading the CPU or changing thread counts).

**Minefield, do not step in it**: `m_clock_windowed_skew_tracker` is an in-tree,
already-tried "obvious" fix for exactly this kind of clock-offset problem, and it is a
**measured dead end** (`docs/pruebas.jsonl` T162, referenced again in `docs/39`): swapping
it in took dropped-sample counts to zero and made drift *worse* — 243 m and 1002 m on two
runs against a 0.7-1.0 m baseline. Whatever fixes the ingest-site bias, it should not be
that tracker.

## Reproduce

`WMR_CONSTELLATION_CONTROLLERS=1 SLAM_LOG=info jack-in-wayland.sh 1 6dof`, wearer or
turntable load, basalt built with `VIT_COLLAPSE_LOG=1` set at launch. Grep
`pred: anchor age` (monado log) and `vit_collapse IN` (basalt log via the service's
stdout/journal) for lines close together in wall-clock time; subtract the newest `t_ns` seen
in a nearby `vit_collapse IN` from the `when_ns` of a nearby `pred:` line.
