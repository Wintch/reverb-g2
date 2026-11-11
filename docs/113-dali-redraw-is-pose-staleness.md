# 113 — Dalí: the redraw was pose staleness. Density 30/2 + scale 85, and four retractions

**Date:** 2026-09-07. **Status:** shipped (commit `61d4b34`) and worn-validated.

The long-standing complaint on this title (Dalí, 6DoF): slow movement is almost perfect, fast
movement shows a visible "redraw". This file records what answered it, including the four
conclusions stated along the way that later had to be withdrawn. The retractions are kept in
place: three of them were stated as established before the control that refuted them had been
run, and a reader who only sees the tidy ending will make the same mistake again. The
session-anchor guard mechanism behind the "jump" is in §4.

---

## 1. What the redraw actually is

Not a rendering problem and not the GPU. **It is pose staleness.**

Basalt's optical-flow stage was taking ~36 ms inside a 33 ms camera interval — **200 of 200
frames over budget** — so the pose handed to the compositor was chronically late and `age_out_ms`
compounded to a p50 of **100.8 ms**. At a rate this far over budget the lateness does not settle;
each frame starts further behind than the last until the queue drops one.

Detection density 30/3 → **30/2** (grid unchanged, points per cell 3 → 2) brings the same worn
measurement to **age_out p50 36.7 ms, 11/200 over budget**. Verdict, worn: medium
movement went from a constant redraw to "looks perfect".

The cost is landmarks: p50 **69 → 31** (`light-preflight.sh`, verdict OK on both). With half the
evidence the one_euro filter damps an anchor correction less, so the *visible* jump grows from
1.15 m to 1.53 m median. The wearer accepted that trade explicitly: it is outweighed by no longer
having a constant redraw on medium movements.

**`grid30-cell2` dominates `grid36-cell3`** and the latter is not a useful middle step: fewer
keypoints (1835 vs 2071) but **twice** the landmarks (31 vs 15) and the same latency win. If a
retreat from 30/2 is ever needed it has to go back toward the baseline, not toward 36/3.

## 2. Render scale 85

Separate axis, same day. After a GPU swap the rig ran on a 210 W power cap, and at scale 100 Dalí no
longer reproduced its 250 W sign-off: **2/8** 20-second windows ≥ 89 fps versus 6/8 before, with
fps tracking time-at-cap through the clock. At scale 85: **7/8** windows ≥ 89 fps, spread 0.55 —
better than the original approval. Worn verdict: plays very well, the lower resolution is not
bothersome.

**Never sign off a title's GPU headroom from an unworn capture.** An unworn pass the same morning said the
210 W cap was not the constraint; the worn pass reversed it (35 % of samples at the cap, clock
down to 1740 MHz). The headset being worn changes the GPU load enough to invert the conclusion.

## 3. The thread confound (why the CPU number from the sweep is not quotable)

The sweep's hand-written variant TOML carried `num-threads=4`, while `TITLE_PROFILES["591360"]`
ships `SLAM_THREADS=6`. **Every density run of the sweep therefore ran Basalt at 4 threads against
a 6-thread baseline**, which confounds the sweep's CPU figure (356 % → 261 %) beyond use.

The latency figure is *not* confounded, in the safe direction: fewer threads makes the tracking
stage slower, so 36.7 ms was measured with a handicap. Confirmed afterwards — at 6 threads with
30/2 the static measurement reads `vit_of` 22.8 ms and `age_out` **31.5 ms with 0/200 over
budget**.

Root cause of the confound, and the fix now in the tree: handing a ready-made TOML through
`SLAM_CONFIG` freezes the thread count into it. `jack-in-wayland.sh` gained
**`SLAM_G2_CONFIG_FILE`**, which swaps the Basalt pipeline JSON while still letting jack-in
generate the TOML, so `num-threads` keeps following `SLAM_THREADS`. **Never hand-write a variant
TOML again.**

## 4. The session-anchor radius A/B — a lever that only changes the texture

`SLAM_SESSION_ANCHOR_RADIUS_CM` 300 → 150, everything else held: raw jump 3.15 → 1.36 m, visible
jump 1.53 → **0.69 m**. Exactly halved, as predicted — the jump *is* the radius, because drift
walks out to the boundary and the guard pulls it back.

It did not help. Even short movements showed a slight but visible readjustment, a
high-frequency redraw: halving the radius only trades few-big corrections for many-small ones.
Many-small reads as jitter; few-big is marginally preferred. The radius stays at 300.

At radius 150 a sustained ~1.0 m vertical drop lasted 26 s (t=38..66 s) at 1.3 m total
displacement — just under the 1.5 m trigger, so nothing rescued it. A guard radius set below the
drift it is meant to catch is worse than a wider one.

### 4.1 Which pose stream the wearer feels (CSV puzzle)

Confirmed from `t_tracker_slam.cpp`, not just logs:

- `tracking.csv` (~28 Hz): raw SLAM but **rebased by `reset_offset` before the write** (so it is
  not the raw signal it looks like); `SLAM_RESET_OFFSET_CARRY=0` restores the literal teleport.
- `filtering.csv` (~180 Hz): predict_pose, `apply_correction_spread`, filter. **This is the
  stream the application receives and what the wearer physically feels.**
- `prediction.csv` (~180 Hz): raw prediction, no correction spread.

A reset re-anchors onto the last known-good pose, so a clean isolated reset is invisible in every
stream. But the guard check and every reset are gated on `nts > quiet_until`, and each reset sets
`quiet_until = nts + 2 s`: a **2-second blind window per reset in which divergence is not
checked**. Overshoot Basalt produces while re-localising inside it reaches `filtering.csv` and the
compositor unclamped. In an observed runaway (191 resets in ~28 min, almost all ~3.0-3.13 m,
the same magnitude as the guard's 3 m radius), two post-reset windows showed 2.6-6.0 m position
excursions in 33-300 ms with only ~2-9 deg of rotation, and no rotation near 180 deg existed at
any timescale: a felt "went down about a meter and rotated" event was a real fast yaw landing at
the same moment as a position collapse leaking through the blind window, not the reset snap. A
post-update gate (`post-update-verify.sh`: patches applied, 90 Hz negotiated at 90.001 Hz through
both the DRM-lease path and the real Monado path) cleared the kernel/driver update as the cause.
Candidate guard fixes, never implemented: shrink the `quiet_until` window, or have repeated
same-direction resets nudge `reset_offset` back toward the anchor.

## 5. Four retractions

### 5.1 "The guard fires on legitimate movement" — WRONG

Every reset fires at `dist_before ≈ radius`. That is the trigger condition and says nothing about
cause; it was read as an invisible wall being bumped into. Refuted by the vertical
axis: at radius 500 the recorded height range is **6.94 m**. A head does not move 6.94 m
vertically. It was drift.

### 5.2 "The VIO drifts metres at rest / is fundamentally broken" — WRONG, and stated as decisive

A stationary headset **on the desk** reported 76.4 m of travel in 3.9 min with 23 guard trips.
This was presented as conclusive. It was an artifact of the test: the cameras were
aimed at close-range desk surface — no parallax, a degenerate VIO scene.

| headset position | density | phantom path | guard trips |
|---|---|---|---|
| lying on the desk | 30/2 | 76.4 m | 23 |
| lying on the desk | 30/3 | 37.1 m | 10 |
| **propped, facing the room** | 30/2 | **1.7 m** | **0** |
| **propped, facing the room** | 30/3 | **2.4 m** | **0** |

Propped facing the room the tracker is essentially perfect: v_p95 0.03 m/s, zero trips.

### 5.3 "30/2 doubles the drift" — WRONG, same artifact

76.4 m vs 37.1 m came from the desk runs. In a good scene the two densities are indistinguishable
(1.7 vs 2.4 m, 30/2 marginally *better*). The profile promotion stands unchanged.

### 5.4 "The recall-cache leak explains the reset storm" — ruled out, correctly this time

A 22-minute session was clean for 10 minutes and then reset every ~15 s, which looks exactly like
something accumulating. Every frontend stage is **flat** across the session (recall 0.02–0.05 ms,
tracking ~16 ms at minute 0 and minute 21). Nothing accumulates, and Faulto's Basalt patch 0014
does not apply here.

The real explanation is duller and is its own lesson: **minutes 1–9 have a distance spread of
~20 cm — the wearer was standing still.** Resets track movement. Always check the spread before
reading a time trend as degradation.

Also ruled out with data: the guard's documented `RESET_OFFSET_CARRY` pinning caveat (34 of 35
resets are isolated single events; the position returns well inside the radius), and room light
(`light-preflight.sh` verdict OK).

## 6. The donning-position A/B — negative

Hypothesis, from §5.2: the approved operator rule has the headset **on the desk** while the title
loads (~60 s), so Basalt initialises *and captures its session anchor* in the one scene measured
to invent tens of metres. Candidate fix costing no code: prop it facing the room instead.

Two 4-minute worn arms, same wearer, same routine, profile as shipped, worn window isolated with
a `CLOCK_MONOTONIC` marker so the pre-don and post-doff segments do not pollute it:

| | pre-don trips | worn path | worn resets | pose latency med | p90 | frontend med |
|---|---|---|---|---|---|---|
| A: against the wall, close surface | 2 | 27.7 m | 0 | 39.2 ms | 48.0 | 25.8 ms |
| B: propped facing the room | 0 | 44.5 m | 4 | 39.4 ms | 49.9 | 25.3 ms |

The placement check worked — 2 pre-don trips vs 0, matching §5.2 — and bought nothing. Drift was
*worse* in the good-scene arm, and pose latency is identical over ~7200 samples each (2 % over
the 33 ms interval in both).

**The wearer felt a large difference anyway** (A: redraw on fast movement; B: much better, redraw
barely noticeable), with no measured correlate.

**The A/B was not blinded.** The wearer knew which arm was the candidate and what result was
hoped for. Either the difference is real in a variable not being measured, or it is expectation,
and this design cannot distinguish them. A blinded repeat is the only way to settle it — offered,
deferred, not run. **Do not resurrect the donning-position idea without it.**

## 7. What shipped

`TITLE_PROFILES["591360"]` in `vr-launcher.py`:

- `XRT_COMPOSITOR_SCALE_PERCENTAGE` 100 → **85**
- **density 30/2** via `SLAM_G2_CONFIG_FILE` → `~/vr/basalt-g2-config-d30x2.json`
- `SLAM_THREADS` stays **6**, `SLAM_SESSION_ANCHOR_RADIUS_CM` stays **300**

The shared `basalt-g2-config.json` is **unchanged at 30/3** — Aircar and Cyberpilot still use it
and neither was measured at the lower density.

Measured on the shipped profile, worn: **pose latency 39 ms median, 2 % of frames over budget**,
guard trips 0 and 4 per 4 worn minutes — against ~100 ms `age_out` and 15–35 trips earlier the
same day.

**Open flag:** 30/2 has only ever been worn at 4 threads and the profile runs 6. Promoted anyway
because the axes are independent stages — density is detection (sequential), threads are tracking
(the tbb-parallel stage, 20.4 → 12.4 ms at 6). The §3 static run supports it. If a future worn
session feels worse, drop `SLAM_THREADS` to 4 **before** touching the density.

## 8. Method notes worth more than the result

- **Drift and "redraw" are different failures and they moved in opposite directions.** Judge
  a redraw complaint on `received_by_monado - frames_original_timestamp` from `timing.csv`, never
  on position ranges, which do not diagnose a latency complaint.
- **`VR_DEMO_RECORD=1` writes per-session pose CSVs** under
  `~/vr/logs/demo-sessions/<run>/slam/` (live: `/mnt/vrtmp/slam-<ts>/`). Every worn run launched
  from the launcher is measurable afterwards, with no special instrumentation and no dependence on the
  jack-in log surviving. A baseline comparison was nearly lost to a sweep script that
  truncates that log.
- **The recorder persists its session directory asynchronously**, so
  `ls -dt ~/vr/logs/demo-sessions | head -1` right after a run returns the *previous* session.
  Match by `slam_config_final` in `summary.json`, never by recency. This mislabelled a result
  before it was caught.
- **Basalt only emits `vit_*` while an OpenXR client holds a live session**, and
  `VIT_COLLAPSE_LOG=1` is opt-in. A bare compositor produces a perfectly healthy session that
  measures nothing.
- **`SLAM_WRITE_CSVS` flushes when the tracker is destroyed.** A hard `jack-in down` kills the
  service first and leaves the CSV directory empty.
- **`pgrep -f <pattern>` over ssh matches your own command line**, killing the shell (exit 255)
  or counting itself as a phantom orphan. Bracket the first character:
  `pgrep -f "[d]reamsofdali.exe"`.

## 9. Still open

1. **The blinded repeat** of §6, to decide whether the felt A/B difference is real.
2. **Drift while worn** is real (3–4 m ranges) and unexplained — but it is *not* what the wearer
   is complaining about, which was the day's central confusion.
3. `test-591360-predict` remains unvalidated and now needs `XRT_COMPOSITOR_SCALE_PERCENTAGE=85`
   added to match the shipped profile.

## 10. Tools written for this

In `scripts/slam-analysis/`, all reading the per-session pose CSVs written by
`VR_DEMO_RECORD=1`. Each answers exactly one question and is blind to the others — see
[32](32-measurement-toolkit.md) for why that matters:

| tool | question it answers |
|---|---|
| `count-jumps.py` | how many pose discontinuities, and how big |
| `motion-norm.py` | resets normalised by path length and fast-motion time |
| `cluster.py` | are the resets isolated events or one episode re-firing |
| `anchor-dist.py` | distance-from-anchor distribution, and where resets sat in it |
| `yaxis.py` | sustained level shifts (the "fell to the floor" report) |
| `pinning.py` | is the output pinned at the radius after the first trip |
| `recall-trend.py` | does any frontend stage grow over a session |
| `worn-window.py` | restrict any of the above to the worn segment via a monotonic marker |
| `pose-latency.py` | end-to-end pose latency — the redraw metric |
| `static-drift.sh`, `static-recorded.sh`, `don-ab.sh` | the harnesses |
