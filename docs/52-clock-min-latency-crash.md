# `WMR_CLOCK_MIN_LATENCY` re-test (Phase 2, position pops) — CRASHES near-instantly, worse than previously known, do not ship (2026-08-18)

## Context

`WMR_CLOCK_MIN_LATENCY` (`wmr_source.c`, opt-in, default OFF) was written 2026-08-17 as the
Phase 2 fix from `docs/re-windows/WORKPLAN.md` (position pops / timestamp jitter): instead of
re-fitting the IMU→monotonic clock offset from every single 250 Hz sample, it buffers a
64-sample window, keeps the least-delayed `(hw, mono)` pair, and blends only that into the
offset once per window with an outlier/last-known-good guard. The 2026-08-17
`handoff-20260817/HANDOFF.md` already flagged it as excluded from that day's dev handoff:
*"a known-bad negative result (it accelerated the [SLAM pose-rate] collapse ~10 min → 27 s)"* —
but that test pre-dated the SLAM-collapse fix (`BASALT_IMU_NONBLOCK_CATCHUP`, see
[[docs/39]]) landing on dev, so today's goal was to re-test it now that the confound is gone.

## What actually happened: an immediate crash, not a slow collapse

**A/B test, both runs `WMR_CONSTELLATION_CONTROLLERS=1 VIT_COLLAPSE_LOG=1`, otherwise
identical rig/build:**

- **`WMR_CLOCK_MIN_LATENCY=0` (baseline): clean 17-minute soak, zero
  `IMU clock-offset jitter absorbed` events.** (Notably fewer than the historical 281-event/
  17-min measurement from `docs/39` — plausibly cleaner USB/scheduling conditions today, not
  a code change; the per-sample EMA path is unmodified.)
- **`WMR_CLOCK_MIN_LATENCY=1`: crashed within the first ~15-30 seconds**, total log 112 lines.
  Sequence:
  ```
  WARN [receive_frame] Rejecting insane forward jump: cam0 frame (...) is 2522999814021 ns
       ahead of last accepted (...) -- dropping bundle, keeping baseline
  WARN [receive_frame] Dropping frame bundles: cam0 frame (...) is older than the last
       accepted (...) by -2522999814021 ns (1 dropped so far)
  WARN [receive_frame] Camera clock re-baselined forward by 2523032958271 ns (confirmed by
       consecutive frames), accepting
  ```
  i.e. the windowed offset estimate jumped by **~2523 seconds (~42 minutes)** in one window,
  Monado's own frame-bundle re-baseline safety net decided (wrongly) that this was a genuine
  device-clock discontinuity and accepted it, and the corrupted timestamp then reached Basalt,
  which crashed on an out-of-bounds Eigen assertion (`Block.h:146`,
  `startRow <= xpr.rows() - blockRows` failed — a sliding-window/marginalization index going
  negative or past bounds from the huge implied frame gap). 7 threads hit the same assertion
  near-simultaneously before the process died (SIGABRT), consistent with several in-flight
  frames all reaching the poisoned state at once. `monado-service` fully exited; USB stayed
  healthy throughout (no hardware fallout).

## Read

**This is a real, previously-underestimated bug in the windowed offset code, not a milder
"accelerates an unrelated collapse" side effect.** The `~42-minute` jump size is a strong clue:
`wmr_source.c`'s window-seed logic (`if (ws->hw2mono == 0) { ws->hw2mono = cand; }`) has no
sanity check on the very first seed value, and the code applies the same `ws->hw2mono` /
`ws->cam_hw2mono` offset to **both** the IMU timeline and the camera timeline
(`receive_cam0`'s `ws->cam_hw2mono = ws->hw2mono` snapshot) — a single bad windowed candidate
poisons both consumers at once, unlike the per-sample EMA path where one bad sample only nudges
the estimate 5%. Not fully root-caused this session (no time-boxed budget left for it); the
seed path and/or a raw-hardware-timestamp wraparound not being handled by the min-tracking are
the leading suspects for where the ~42-minute value comes from.

## Verdict

**Do not flip `WMR_CLOCK_MIN_LATENCY` on, anywhere, as-is.** This is stronger evidence than the
2026-08-17 finding: it's not merely suboptimal under one interaction, it can crash the service
outright, independent of the (now-fixed) SLAM collapse. Phase 2 of
`docs/re-windows/WORKPLAN.md` needs a real fix to the windowed-candidate logic (at minimum: sanity-bound
the first seed, and re-derive `IMU_JITTER_MAX_NS`-style bounds-checking for the windowed path,
which currently has none) before it's worth re-testing, not just a re-test under today's
cleaner baseline conditions.
</content>
