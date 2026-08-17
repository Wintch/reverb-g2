# Constellation correspondence-search CPU blow-up — bounded with a per-model deadline (2026-08-17)

Found while attacking the sustained CPU / SLAM-frame-drop load on the everyday system
(KDE/X11/NVIDIA-550/60Hz, same physical rig, turntable fixture). Root-caused live with a
poor-man's `gdb` profiler (no `perf` on this box; `perf_event_paranoid=3`).

## Symptom

With the runtime under sustained load, `monado-service` sat at a high CPU average and, in
the worst case (**controllers powered OFF**), **three threads pegged at ~90-100 % in state
`R`** — a total ~614 % CPU (6.1 cores of work). `syscall: running` + `wchan: 0` on all three
confirmed a **userspace busy-loop**, not I/O wait. It was NOT the companion storm (log
errors were rate-limited by `657bcd8af`, ~17 in 20k lines) and NOT Basalt.

## Root cause: the LED↔blob correspondence search has no time budget

All three pegged threads were in the constellation correspondence search
(`src/xrt/tracking/constellation/correspondence_search.c`), same stack on each:

```
lambdatwist_p3p                       (P3P pose solve)
  check_led_against_model_subset
  select_k_blobs_from_n               (C(5,3) blob subsets)
  check_leds_against_anchor
  select_k_leds_from_n                (C(8,3) LED subsets)
  generate_led_match_candidates
  search_pose_for_model               (per model, per frame)
```

`search_pose_for_model()` runs, for each model (controller) every frame:

```
for l in model->num_points (32 LEDs):        # anchor LED
  generate_led_match_candidates(...)          # C(8,3) LED × C(5,3) blob × P3P
  if strong match: return                     # <-- the ONLY early-out
```

The search is bounded only by recursion depth (`MAX_BLOB_SEARCH_DEPTH=5`,
`MAX_LED_SEARCH_DEPTH=8`) and **short-circuits only on `POSE_MATCH_STRONG`**. There is **no
wall-clock deadline** — `search_start_time` exists but is compiled out unless `DUMP_TIMING`
and is used only for logging. So on any frame with **no strong match**, the full
combinatorial expansion runs to completion across all blobs × 32 model LEDs × the depth
combinatorics × P3P solves, on 4 cameras, for both controllers.

The pathological case is precisely **no real target present**:

- **Controllers OFF** → no real LEDs, only spurious blobs from room light → the match fails
  every frame → full exhaustive search every frame → 3 pegged cores. (Counter-intuitively
  *worse* than controllers-on-and-spinning ~158 %: a real target yields a strong match that
  prunes early; a failed match never prunes.)
- **Many spurious blobs** (bright/mixed room light produced 200+ blobs/frame on one camera
  in earlier testing) inflate the per-anchor combinatorics on top of that.

## Fix: a per-model wall-clock deadline (env-gated, opt-in)

`search_pose_for_model()` now computes a local deadline before the anchor loop and stops
searching that model for the frame once it is exceeded, keeping the best match found so far:

```c
static int64_t search_budget_ns = -1;   // read WMR_CONSTELLATION_SEARCH_BUDGET_US once
if (search_budget_ns < 0) {
    const char *env = getenv("WMR_CONSTELLATION_SEARCH_BUDGET_US");
    search_budget_ns = (env != NULL) ? (int64_t)atoll(env) * 1000 : 0;   // default 0 = OFF
}
const uint64_t search_deadline =
    (search_budget_ns > 0) ? os_monotonic_get_ns() + (uint64_t)search_budget_ns : 0;

for (l = 0; l < model->num_points; l++) {
    if (search_deadline != 0 && os_monotonic_get_ns() > search_deadline) break;
    ...
}
```

Rationale: a real target normally produces a **strong match early** (the existing early
return) long before the budget, so the deadline only bites the pathological no-match case; a
pose missed on one frame is recovered on the next (the search runs every frame). Default
`WMR_CONSTELLATION_SEARCH_BUDGET_US=0` preserves the original unbounded behaviour; set e.g.
`3000` to cap each per-model search at 3 ms. Monado `lab-full`,
`src/xrt/tracking/constellation/correspondence_search.c`.

## Validation (2026-08-17, everyday system, controllers OFF = worst case)

| | no budget | `WMR_CONSTELLATION_SEARCH_BUDGET_US=3000` |
|---|---|---|
| `monado-service` CPU | ~468 % avg, **614 %** peak, **3 cores pegged @ ~90-100 % R** | **261 %**, **no pegged cores** (top thread ~40 %, state S) |

The 3-core busy-loop is gone. On a 6-core box that reclaims ~3.5 cores of pure waste that
occurs whenever controllers are off or blobs are spurious.

## Important correction: this is NOT the cause of the SLAM frame drops

The hypothesis that drove this investigation — "constellation search steals CPU and starves
the SLAM frontend into dropping frames" — was **refuted by the data**. With the budget on,
CPU fell from 614 % to 261 % but the SLAM input-frame **drop rate barely moved (~11→~10
/s)** and `vit_collapse OUT wall_ms` stayed ~45 ms. The drops have a **separate** cause:
Basalt's own optical-flow frontend. A clean `vit_of total_ms` reads **mean 35.4 ms, 37 % of
frames > 33 ms**, and the hot Basalt thread is in
`basalt::detectKeypointsWithCells ← addPointsForCamera ← addPoints ← processFrame` — i.e.
**keypoint (re)detection cost exceeding the ~33 ms camera frame interval**, independent of
constellation and of the `processImu` collapse (docs/39). That is a distinct SLAM-frontend
throughput issue (detection frequency / cell config / max keypoints / image quality), to be
investigated separately — ideally on dev at 90 Hz where the judder is actually felt, since
optical-flow cost is build/driver-dependent.

## Controllers-ON A/B (2026-08-17): the 3 ms budget DOES cut real matches — do not default it on

The remaining gate — "does the budget harm real tracking?" — was tested with a controller
spinning on the turntable, budget ON (3 ms) vs OFF (0), same lighting/position:

| | poses found | failed to find | `monado-service` CPU | mean blobs/obs |
|---|---|---|---|---|
| budget **ON** (3 ms) | **0** | 1603 | 313 % | 26.9 (max 63) |
| budget **OFF** (0) | **19** | 1304 | 409 % | 22.2 (max 62) |

So the 3 ms deadline is **too tight for this box's blob-swamped scene**: with ~22-27 blobs per
observation (real LEDs + spurious room-light blobs) the exhaustive search sometimes needs more
than 3 ms to find the valid P3P among the noise, and the budget cuts it off first. The prediction
that "a real target matches well inside the budget" held only for a clean scene; under swamping it
does not. **Conclusion: keep the budget default OFF; do not ship 3 ms as-is.**

Two things are true at once, and it matters not to conflate them:
1. The budget **does** kill the pathological no-target CPU runaway (614 %→261 %, above) — a real,
   keepable effect.
2. It **also** costs real matches when the scene is noisy — a real regression.

The dominant problem on this box is upstream of the budget entirely: **blob swamping.** Even with
the budget OFF, tracking barely works here (19 found vs 1304 failed = ~1.4 %), because mean 22-27
blobs/frame (a controller shows ≤~16 LEDs to a camera) means the frames are heavily contaminated by
room-light blobs — the long-known exposure/lighting/threshold issue on the everyday system. The
matcher is being asked to find a needle in a pile of needles every frame.

### Refined fix direction (not yet implemented)

A blanket wall-clock budget is the wrong lever because it penalises the legitimate-but-hard match
identically to the hopeless no-match. Better options, to design/test (ideally on dev, where
controller tracking is validated and lighting is controlled):

- **Blob-count / swamping guard** — if a camera reports more than ~N blobs, the scene is too noisy
  for a reliable match anyway (and that is exactly when the search explodes); reject or subsample
  the frame. Kills the CPU runaway *and* the swamped-match cost, without time-cutting a clean-scene
  match. Pairs with the deferred `pixel_threshold`/`blob_required_threshold` tuning.
- **Controller-present gate** — skip the exhaustive full search when the controller has not been
  seen recently (handles the controllers-off case directly, zero cost to real tracking).
- **A much larger budget** (e.g. 10-15 ms) as a pure runaway backstop — still << the full
  exhaustive expansion that pegged the cores, but generous enough not to cut clean matches. Weakest
  of the three; only a safety net.

## Status

- Constellation search budget (`WMR_CONSTELLATION_SEARCH_BUDGET_US`): **implemented; kills the
  no-target CPU runaway (validated); but the controllers-ON A/B shows 3 ms cuts real matches —
  stays default OFF.** Needs the refined guard above (blob-count cap / controller-present gate)
  before it can default on. Monado `lab-full` `22ec60f3b`.
- Blob swamping (mean 22-27 blobs/frame under room light): **the real controller-tracking blocker
  on the everyday system — exposure/threshold, pre-existing, orthogonal to the search budget.**
- SLAM frame drops (optical-flow keypoint detection): **open, separate issue** (docs/42 Thread 3).
