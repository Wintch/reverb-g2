# Camera clock-domain skew: root cause, fix, validation (2026-08-17)

**Resolved.** Camera frame stamps that reach Basalt ran ~630 ms in the future of the clock the
pose queries and the IMU-for-prediction use. The cause was the companion-storm backoff in
`wmr_run_thread` sleeping inside the shared HID read loop, which starved the IMU reads (fix:
monado `0055`). This document records the root cause, the fix, the validation, and the
measurement method.

## Root cause

monado `0049` rate-limited the companion device's failing retries by sleeping 10 ms
(`os_nanosleep`) **inside** `wmr_run_thread`'s single shared read loop (`control_read_packets`
and `hololens_sensors_read_packets` run sequentially in one thread sharing `wh->hid_lock`). With
the companion storm active (universal on this rig), that sleep capped the whole loop, IMU reads
included, at **~100 iterations/s against ~250 IMU packets/s produced**. The kernel-side ring
filled and pinned the IMU stream a fixed **~630 ms stale** at arrival. `hw2mono` (fit from IMU
arrival times) absorbed that lag instead of exposing it, pushing the *converted* camera frame
stamps ~630 ms into the future relative to query-now.

That one number is the 632-666 ms "magic number" seen as the collapsed pose interval in the SLAM
collapse (`docs/39`, which fixed the symptom: `processImu` blocking while the image time runs
ahead of the IMU stream), and it is also the constant ~1 s perceived head latency. Prediction
trusts the anchor's stamp, not its true content age, so dead reckoning only bridged the ~90 ms
the lying stamp admitted to; Monado does not re-stamp on delivery (`flush_poses` uses
`data.timestamp` verbatim), so the bias rode untouched to the application.

**It is a load-onset drift, not a startup constant.** An ingest-side diagnostic (monado `0053`,
logging raw camera-vs-IMU hardware-domain skew at the actual `cam_hw2mono` conversion site)
caught a session starting honest (skew -4..0 ms, converted camera stamps -4.5 ms in the past),
then ramping from -2.45 ms to +630 ms between frames ~300 and ~1200 (under 40 s, no app, no
wearer) and pinning there. This disproved a "startup-burst anchoring" hypothesis (the offset
estimator fitting during the ~19 buffered frames at process start). It also explains why the
collapse appeared only with `0049` and never before: the earlier failing companion read spun with
no pacing sleep, so nothing throttled the IMU side and the ring never filled.

Ruled out: `m_clock_windowed_skew_tracker` as a fix for the offset. It is a measured dead end
(`docs/pruebas.jsonl`, see `docs/39`): swapping it in zeroed dropped samples but made drift worse
(243 m and 1002 m on two runs against a 0.7-1.0 m baseline).

## Fix

monado `0055` keeps `0049`'s <=100 Hz companion retry ceiling but implements the backoff as a
**skip until `companion_backoff_until_ns`** instead of a sleep, so the shared loop's pace is
untouched (the hololens blocking read still paces the healthy loop).
`WMR_COMPANION_BACKOFF_BLOCKING=1` restores the old in-loop sleep for a direct A/B. See
`patches/monado/0053-0055` and `patches/monado/README.md`.

## Validation

Idle SLAM session with the storm active the whole time (39792 consecutive companion errors, the
exact old trigger). Raw cam-vs-IMU hardware-domain skew held **flat at -4..-0.7 ms over 8
minutes / 14400 frames** (old behaviour: +630 ms by frame 1200); converted camera stamps stayed
at -4.5 ms; the tracker's prediction anchor age reads the **true content age (~144 ms idle)**
instead of a lying 50-112 ms. A wearer feel-test passed: head rotation immediate, the constant
~1 s lag gone. Validated at mechanism level with the storm both active and idle.

**Cross-confirmation from Windows RE:** `MRUSBHost.dll` carries `IMUStaleDataDrop` /
`CameraReaderLoopRestartingIMU`, i.e. Windows' own driver explicitly detects and restarts a stale
IMU stream, a named failure class it guards against.

## How the bias was first measured

Monado patch `0052` adds a rate-limited (~1 line/s) `SLAM_INFO` at the dead-reckoning call site
in `predict_pose()` (`t_tracker_slam.cpp`):

```
pred: anchor age %.1f ms (when_ns=... rel_ts=...)
```

`when_ns` is the query clock (the clock the IMU-for-prediction rings live in); `rel_ts` is the
stamp on the anchor (the latest filtered SLAM pose) that dead reckoning integrates forward from.
Read interleaved within milliseconds with Basalt's own `vit_collapse IN ... t_ns=` lines (patch
`basalt/0003`, newest camera-frame stamp per ingested frame), two numbers come out of one log:

1. **Anchors LOOK 50-112 ms old** to the predictor (intermittent 677-810 ms spikes), which is why
   dead reckoning never trips its own staleness path (zero hits on the failure-path log line).
2. **Anchor CONTENT is ~630-700 ms stale.** Newest-camera-frame-stamp minus `when_ns` is **p50
   +578 ms, max +610 ms (n=121)**.

The gap between the two readings is the camera clock's forward bias. `pose-lag.py` agreed:
prediction contributes essentially nothing (delivered pose lags raw SLAM content by only +80 ms;
filtering-to-prediction residual +0.0 ms), so the staleness arrives already baked into the
anchor. The prediction path (`t_tracker_slam.cpp`, `t_dead_reckoning.c`, `m_predict.c`,
`m_filter_fifo.c`) has no horizon cap on anchor age and a no-partial-credit `return false`
fallback that silently delivers the bare stale anchor.

## Reproduce

`WMR_CONSTELLATION_CONTROLLERS=1 SLAM_LOG=info jack-in-wayland.sh 1 6dof`, wearer or turntable
load, basalt built with `VIT_COLLAPSE_LOG=1` set at launch. Grep `pred: anchor age` (monado log)
and `vit_collapse IN` (basalt log via the service's stdout/journal) for lines close together in
wall-clock time; subtract the newest `t_ns` in a nearby `vit_collapse IN` from the `when_ns` of a
nearby `pred:` line. For the ingest-side view, enable the `0053` diagnostic.
