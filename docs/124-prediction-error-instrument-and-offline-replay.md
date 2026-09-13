# 124 — Prediction error got an instrument, and config sweeps stopped needing a wearer

Date: 2026-09-13

Two things landed this session, and the second exists because of what the first found.

## 1. The `SLAM_PRED_NECK_ARM_MM` sweep, worn — and the instrument that was missing

`docs/100` staged `test-591360-predict` (`SLAM_PREDICTION_TYPE=2` + `FREEZE_POSITION=1` +
`NECK_ARM_MM=100` + `CORRECTION_SPREAD_MS=50`) in 2026-09-05 and it only ever got one hedged
verdict — *"feels pretty good, I think better, but hard to confirm"*. It was never closed out with
the pointed, Aircar-style protocol `docs/100` §5 itself prescribed. This session ran that protocol:
four worn arms, `NECK_ARM_MM` 0 / 100 / 150 / 200, everything else identical, asking specifically
about the fast-turn feeling rather than "does it feel good".

**The wearer's verdicts, in their own terms:**

| arm | slow / medium | fast turns | new artifact |
|---|---|---|---|
| 0 mm | perfect, "native / 3dof" | re-settles, but with a noticeable delay; mildly nauseating | none |
| 100 mm | perfect | re-settles more nimbly | a short redraw now appears at *medium* speeds, slightly more often |
| 150 mm | — | similar to 100 | yaw **overshoot** ("it carries me further than I turned") + pitch sag |
| 200 mm | — | similar to 150 | yaw overshoot slightly worse; redraw gone, only position delay left |

**None of the existing tools could see any of this.** `scripts/slam-analysis/` measured jumps,
drift and latency — all properties of the *tracker*. Every `SLAM_PRED_*` knob acts on the
*prediction* layer downstream of it, so the artifacts they introduce had no instrument at all and
could only ever be judged by a wearer. That is the gap `predict-error.py` fills.

**Method:** `t_tracker_slam.cpp` pushes `prediction.csv` as `{when_ns, predicted_pose}` — each row
is the runtime's claim about where the head *is* at `when_ns`. `tracking.csv` is pushed as
`{frame_ts, raw_pose}`, Basalt's own later, unextrapolated estimate for that same instant. So
interpolating `tracking.csv` at a prediction row's timestamp gives the reference the prediction was
trying to anticipate, and the difference is prediction error. Errors are reported in head-local
axes (right / up / back), because that is how they are felt, and binned by the true angular rate,
because both artifacts are rate-dependent by construction.

Reference caveat, stated plainly: `tracking.csv` is Basalt's estimate, not external ground truth.
It drifts and the anchor guard yanks it. That makes it useless as an absolute position reference —
but the tool only ever reads it across a ~150 ms prediction horizon and drops samples near guard
resets, so what survives is a fair *local* reference.

**What it measured, from the four worn arms (already recorded — `VR_DEMO_RECORD=1` writes the CSVs,
so this was answered retroactively with no extra headset time):**

| neck-arm | horiz @ yaw >120°/s | vert @ pitch >60°/s | horiz @ 10-30°/s | at rest (p90) |
|---|---|---|---|---|
| **0 mm** | **72 mm** | +18 / −17 mm | **10 mm** | **5 mm** |
| 100 mm | 93 mm | +28 / −29 mm | 15 mm | 27 mm |
| 150 mm | 119 mm | +45 / −32 mm | 18 mm | 24 mm |
| 200 mm | 119 mm | +44 / −34 mm | 22 mm | 16 mm |

Every column is monotonic in the knob, and each one matches a specific thing the wearer said:
"it carries me further in yaw" is 72 → 119 mm; "pitching drops me" is −17 → −34 mm; "a short
redraw at medium speeds" is 10 → 15 mm crossing into perceptibility.

**The code says why.** The neck-arm term is `position += (R_pred − R_anchor) · arm` with
`arm = (0, 0.6, −0.8) · len` — 60 % up, 80 % forward. A yaw sweeps that lever horizontally, a pitch
sweeps it vertically. Lengthening it amplifies both sweeps past what the head actually did.

**Conclusion: the neck-arm is the wrong lever.** It does not fix the lag, it trades a slow
re-settle for a sustained directional error, which is worse — a snap is one event, an overshoot is
wrong for the whole turn. `0 mm` wins on every measured axis and introduces no artifact.

**And the residual complaint was diagnosed from the source, not guessed.** The wearer reported a
position delay when *walking* in all four arms equally — so not the neck-arm. It is
`SLAM_PRED_FREEZE_POSITION=1` doing exactly what it documents: holding position flat across the
whole ~120–190 ms anchor-age gap. `SLAM_PRED_POSITION_HORIZON_MS` (lab patch 0100, default **0 =
off**) is the knob built for precisely this — bounded extrapolation of the real SLAM velocity, with
`SLAM_PRED_POSITION_MAX_SPEED_CM_S` (default 150) already guarding the relocalisation-spike tail
that burned the first attempt on 2026-08-27. **It has never been tested on Dalí.** That is the
sweep this session set up.

## 2. Record once, replay any config — no wearer, no headset

Four worn arms cost four donnings, and no two donnings repeat the same head motion: the arms above
had to be binned by angular rate before they could even be placed side by side. Monado's euroc
player replays a recorded dataset through the **real** tracker and the **real** prediction code, so
every config sees byte-identical input.

Offline reimplementation of the prediction maths was considered and rejected: it consumes the raw
gyro FIFO, which no CSV contains. Replaying through the real code also removes any fidelity risk.

```
record-euroc.sh [name]                       # ~5 min worn, spoken routine, writes a EuRoC dataset
replay-euroc.sh <dataset> <label> [K=V ...]  # one config, headless, reports via predict-error.py
```

### Five things had to be fixed, none of them obvious

- **`WMR_DISABLE`** (lab patch 0105). The prober selects the first builder *certain* it can create
  a head, and a connected G2 always makes the `wmr` builder certain. **The first replay reading of
  the session was the real cameras on a desk**, looking completely healthy, and was reported as
  "replay works" before the builder line in the log gave it away
  (`Selected wmr because it was certain it could create a head`). Check for that line before
  believing any service-path replay.
- **Use `monado-cli slambatch`, not the service.** The Euroc HMD is a tracking device with no
  `compute_distortion`, so the real compositor **segfaults** building its distortion buffers;
  `XRT_COMPOSITOR_NULL=1` gets past that, but then this tree's customised 360 `hello_xr` dies on
  its own right after creating swapchains. The batch path needs no compositor and no client at all.
- **`SLAM_BATCH_POLL_HZ`** (lab patch 0106). `slambatch` polled the pose at 5 Hz purely to notice
  tracking had stopped, and prediction only ever runs *inside* `get_tracked_pose` — so
  `prediction.csv` came out ~34× too sparse to characterise. Now 170 Hz, like a real session.
- **`cam_count` off `playback`, not `dataset`** (same patch — a plain upstream bug). A G2 dataset
  records all four cameras while SLAM runs on two; sizing the tracker off the dataset makes it wait
  for cam2 forever (`Expected cam2 frame, received cam0`).
- **`cam-calib` in the Basalt TOML.** Live, the WMR driver reads the headset's factory calibration
  and hands it to `t_slam_create`; `slambatch` builds a *default* config with none, so Basalt aborts
  with `Missing IMU calibration`. The harness derives a 2-camera file from the G2's own dump — the
  full 4-camera one trips `calib_cam_count == cam_count`.

Two smaller traps worth keeping: `slambatch` spawns a thread on `getchar()`, so `</dev/null` is an
instant EOF and the run ends before it starts (the harness holds stdin open with a long `sleep`);
and the *service* path needs `XRT_NO_STDIN=1` for the mirror-image reason — its IPC mainloop
`epoll`s stdin, which `epoll_ctl` rejects for `/dev/null`.

Also: with prediction enabled the runner never terminates on its own. Its stop condition is two
poses 0.2 s apart comparing equal, and a predicted pose keeps moving against an ever-newer
`when_ns` after playback ends. The harness bounds the run by the dataset's own length instead.

### Validated against the worn run

Same config (`NECK_ARM_MM=0`), replay vs. the worn arm:

| | worn | replayed |
|---|---|---|
| horiz @ yaw >120°/s | 71.7 mm | **67.8 mm** |
| vert @ pitch >60°/s | +18.5 mm | **+23.1 mm** |
| vert @ pitch <−60°/s | −17.3 mm | **−14.1 mm** |

The fast-motion bins — where the artifacts live — reproduce within 6–25 %. The at-rest floor is
higher replayed (7.7 vs 0.6 mm) because the recorded routine is deliberately more vigorous than
gameplay, which also puts ~7× more samples in the fast bins.

### The routine was rewritten after the first take

The first recording mixed axes in a "free movement" block and said "shake your head" — it produced
**10 tracker resets against 0** in a real gameplay session, and a yaw sample and a pitch sample
landing in each other's bins cannot be undone in analysis. The rewrite: **one axis at a time**, a
marked pause between every segment, smooth rather than violent, roll included (never asked for
before, yet the neck-arm lever is `(0, 0.6, −0.8)`, so a roll swings the eye laterally too), and
segment boundaries written to `segments.csv` in `CLOCK_MONOTONIC` so analysis can cut exactly
"fast yaw" instead of inferring it from a rate bin. Second take: **0 guard trips.**

The routine also does not start on a timer — it waits for a go signal, because the first take was
lost to a wearer still donning while the countdown ran.

## 3. What actually limits this, and why it must run serially

Measured on a live replay (`monado-cli slambatch`, 12-thread box):

| | value |
|---|---|
| process CPU | 310 % of 1200 % (~26 % of the machine), load 2.5 |
| frame interval | 33.2 ms (30 Hz, as recorded) |
| frontend (optflow + detection) | **14.5 ms p50 / 16.7 ms p90** |
| full pipeline, frame → delivered | 23.7 ms p50 / 27.3 ms p90 |
| disk | ~13 MB/s (7 GB over 537 s) |
| RAM | 181 MB RSS |
| GPU | **zero** — the batch path has no compositor and renders nothing |

**The current bottleneck is the deliberate 1× pacing, not compute.** The prediction horizon is a
wall-clock quantity — the gap between the anchor and "now" — so replaying faster would change the
very thing being measured. `EUROC_MAX_SPEED=0` and `EUROC_USE_SOURCE_TS=0` are load-bearing.

If that constraint were dropped (valid only for pure *tracking* comparisons, never for prediction),
the ceiling is the Basalt frontend at 14.5 ms/frame → ~69 fps → **~2.3× real time**. Not 10×. A
9-minute dataset would still take ~4 minutes.

**Do not run configs in parallel to save wall-clock.** Each run uses ~3 of 12 cores, so 3–4 would
fit and a 40-minute sweep would drop to ~12 — and the result would be worthless. The evidence is in
the numbers above: this same frontend measures **14.5 ms isolated vs. 24.1 ms in `docs/113`**, where
a game was running alongside. Same code, same 30/2 density; the difference is CPU contention.
Contention inflates pipeline latency, pipeline latency *is* the prediction horizon, and the
prediction horizon is the quantity under test. Parallel runs would each measure a different
machine, varying with how they happened to overlap.

**Corollary worth remembering when quoting these numbers:** the replay measures a *less loaded*
machine than a real game session. It is sound for comparing configs against each other — identical
conditions, which is the whole point — but its absolute values should not be cited as in-game
truth.

## Status

- `predict-error.py`, `record-euroc.sh`, `replay-euroc.sh` in `scripts/slam-analysis/`; monado
  patches 0105–0106 vendored.
- Clean reference dataset: `/mnt/resolve_test/g2-datasets/headref2_20260913171334` (7 GB, 16106
  frames, 133381 IMU rows, 12 labelled segments, 0 guard trips).
- `SLAM_PRED_POSITION_HORIZON_MS` sweep (0/30/60/90 at `NECK_ARM_MM=0`) running against it.
- Still owed: one worn confirmation of whatever the sweep favours. The millimetres only narrow the
  search space — the feeling is still the verdict.

See also: `docs/113` (the redraw is pose staleness — the tracker-side half of this story),
`docs/100` (where `test-591360-predict` was staged and left hedged), `patches/monado/README.md`
0100 and 0105–0106.
