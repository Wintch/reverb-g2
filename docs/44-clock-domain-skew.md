# Camera clock-domain skew (T196-T200) — ROOT CAUSE FOUND, FIXED, AND VALIDATED (2026-08-17)

> ## RESOLVED (2026-08-17, T199) — the whole T192-T199 saga closes here
>
> **The bias documented below is real but was mis-framed: it is a load-onset DRIFT, not a
> constant.** A fresh, ingest-side diagnostic (monado `0053`, logging RAW cam-vs-IMU
> hardware-domain skew at the actual `cam_hw2mono` conversion site, not inferred from the
> tracker layer) caught a session starting **honest** — cam-vs-IMU skew −4..0 ms, converted
> camera stamps only −4.5 ms in the past — then **ramping from −2.45 ms to +630 ms between
> frames ~300 and ~1200 (under 40 s, no app, no wearer)** and pinning there rock-stable.
> This kills both the "constant bias baked in at session start" framing of this document's
> title and the "startup-burst anchoring" hypothesis in its own "Next step" section below —
> see the superseded notes inline.
>
> **Root cause**: `0049`'s companion-storm backoff slept 10 ms via `os_nanosleep` **inside**
> `wmr_run_thread`'s single shared read loop (`control_read_packets` and
> `hololens_sensors_read_packets` run sequentially in one thread, sharing `wh->hid_lock` —
> T194). With the companion storm active (universal, T183/T188/T189/T190), that sleep
> capped the whole loop — hololens/IMU reads included — at **~100 iterations/s against
> ~250 IMU packets/s actually produced**. The kernel-side ring filled and pinned the IMU
> stream a fixed **~630 ms stale** at arrival; `hw2mono` (fit from IMU arrival times)
> absorbed that lag instead of exposing it, pushing the *converted* camera frame stamps
> ~630 ms into the future relative to query-now. That one number is the 632-666 ms "magic
> number" chased across T192-T199: it produced docs/39's image-ahead-of-IMU stall (the
> SLAM pose-rate collapse), and separately the wearer's constant ~1 s perceived head
> latency (T197) — prediction trusts the anchor's stamp, not its true content age, so dead
> reckoning only ever bridged the ~90 ms the lying stamp admitted to. **It also answers why
> the collapse appeared WITH 0049 and never before it**: T193's pre-0049 45-minute run
> never collapsed because the failing companion read back then spun **without any pacing
> sleep** in the loop at all — nothing throttled the hololens/IMU side, so the ring never
> filled in the first place.
>
> **Fix**: monado `0055` keeps 0049's ≤100 Hz companion retry ceiling but implements the
> backoff as a **skip until `companion_backoff_until_ns`** instead of a sleep — zero impact
> on the shared loop's pace (the hololens blocking read still paces the healthy loop).
> `WMR_COMPANION_BACKOFF_BLOCKING=1` restores the old in-loop sleep for a direct A/B.
>
> **Validation**: idle SLAM session, storm ACTIVE the whole time (39792 consecutive
> companion errors — the exact old trigger condition). cam-vs-IMU raw hardware-domain skew
> held **flat at −4..−0.7 ms over 8 minutes / 14400 frames** (old behavior: +630 ms by
> frame 1200), converted camera stamps steady at −4.5 ms (honest past), and the tracker's
> prediction anchor age finally reads the **true content age (~144 ms idle)** instead of a
> lying ~50-112 ms.
>
> **Independent cross-confirmation via Windows RE**: `MRUSBHost.dll` carries
> `IMUStaleDataDrop` / `CameraReaderLoopRestartingIMU` — Windows' own driver explicitly
> detects and restarts a stale IMU stream, i.e. defends against exactly this failure class.
> This project only found it by living through it; Microsoft's own driver treats it as a
> known, named failure mode worth guarding against.
>
> **Scope, stated plainly**: validated at mechanism level with the storm both active and
> idle. **Wearer feel-test: PASSED (T201, ~06:17): "perfecto! se fue"** — head rotation immediate,
> the constant ~1 s lag of T197 should be gone. See `docs/pruebas.jsonl` T199-T200,
> `patches/monado/0053-0055`, and `patches/monado/README.md`'s entries for the same.
>
> The investigation record below is kept intact as history; read the superseded notes
> inline before trusting its "Next step" and "Honest scope" sections on their own.

> **Status at the time this was written (superseded above): PROVEN, not yet fixed.** The
> camera frame timestamps that reach Basalt (and stamp its output poses) run **p50 +578 ms
> (max +610, n=121) in the FUTURE** of the clock that pose queries and IMU-for-prediction
> live in. This is a single, stable, code-level bias — not hardware, not CPU load, not the
> scheduler (already ruled out, T195) — and it unifies three findings that until tonight
> looked like three separate problems.

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
  **SUPERSEDED (T199): disproven, not just unmeasured.** The ingest-side diagnostic this
  section's own "Next step" called for (`0053`) found the bias is NOT fixed at session
  start — a fresh session starts honest (−4..0 ms) and only reaches +630 ms after a ~40 s
  ramp, once the companion storm's backoff crosses its failure threshold. It is a
  load-onset drift, not a startup constant. See the resolution section at the top.
- **The relationship between +578-610 ms and the 632-666 ms collapse period is close but
  not identical**, and that gap is noted here rather than explained away. They may be the
  same constant measured two different ways (session-start anchoring vs. steady-state
  collapse period) or two related-but-distinct numbers; nothing in tonight's data settles
  which.

## Next step, surgical

> **SUPERSEDED (T199): executed, and the leading hypothesis below was DISPROVEN by the
> very first capture, not confirmed.** `0053` did exactly what this section asked for —
> raw skew logged at the `cam_hw2mono` ingest site itself — and the first session it
> caught started honest (−4..0 ms), ruling out a fixed startup-burst anchor. The real
> mechanism is 0049's in-loop sleep starving the shared read thread once the companion
> storm's backoff engages, producing a DRIFT that ramps in ~40 s rather than a constant
> fixed at process start. See the resolution section at the top of this document and
> `patches/monado/0055`. Kept below for the reasoning record only.

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
