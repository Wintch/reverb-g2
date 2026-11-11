# 85 — Community-fork patch review, and two new divergence guards from it (2026-08-27)

A community fork ([`Faulto/reverb-g2-linux`](https://github.com/Faulto/reverb-g2-linux)) built a
SteamVR + Lighthouse + Index setup off this repo's patches. Its 7 non-verbatim patches were reviewed
against this project's actual code. Two findings were applied (patches 0098 and 0099, below); the
rest (SteamVR-side bounded tracking volume, a per-axis one-euro filter split, Basalt landmark recall,
Space Calibrator UX ideas, an NVIDIA 610/Blackwell `minBpc` gap) were not taken here.

## Applied: patches 0098, 0099

Both opt-in, both default off, both build clean. Technical detail is in `patches/monado/README.md`.

- **0098 `WMR_FORWARD_ANGULAR_VELOCITY`** forwards the SLAM tracker's own angular velocity to
  SteamVR instead of always reporting zero, so SteamVR's photon-time extrapolation has real
  rotational data.
- **0099 `SLAM_SESSION_ANCHOR_RADIUS_CM` + `SLAM_QUAT_NORM_CHECK`**: two more divergence guards next
  to 0023-a's speed-based one, for slow accumulated drift and for a corrupted orientation quaternion.
  Limitation: a slow-drift trip is not self-healing the way a speed-spike trip is (see the in-code
  CAVEAT comment), so it is more useful as a diagnostic signal than as a recovery mechanism unless the
  response path is special-cased for that failure mode.

Launcher wiring: `scripts/vr-launcher.py` `TITLE_PROFILES` for the two seated 6dof titles set
`SLAM_QUAT_NORM_CHECK=1` and `SLAM_SESSION_ANCHOR_RADIUS_CM=300` (a generous radius for seated
cockpit head movement that still catches the "tens of metres" runaways seen in dim rooms).
`WMR_FORWARD_ANGULAR_VELOCITY` was removed from those profiles after the test below.

## Lesson: a NaN-motivated guard must not copy the `x < lo || x > hi` idiom

The first draft of 0099 compared the quaternion norm directly (`qnorm < 0.5 || qnorm > 1.5`), the form
0043 and other existing guards in the file use. Two independent reviews of the live diff both found the
same defect: a comparison against NaN is always false in IEEE-754, so that form lets a NaN quaternion,
the literal case the check exists to catch, pass undetected. Fixed to a negated inclusive range,
`!(qnorm >= 0.5 && qnorm <= 1.5)`, and confirmed with a standalone test. The same review caught
`SLAM_QUAT_NORM_CHECK` not gating on `auto_reset.enabled` / `quiet_until` like every other guard (reset-loop
risk during the post-reset settle window) and `SLAM_SESSION_ANCHOR_RADIUS_CM` not requiring
`SLAM_RESET_OFFSET_CARRY` (meaningless comparison if carry is off); both were fixed the same way.

## Worn results

- **Divergence guards (0099): clean.** About 12 minutes on a seated 6dof title with real head motion:
  `grep -c "Tracker diverged"` = 0, no false-positive resets, clean session end (no coredump, no
  SIGSEGV). A false-positive rate cannot be fully settled by 12 minutes, but it is the right first
  data point.
- **0098: no perceived effect.** The known fast-turn drift-then-settle behaviour (a felt ~100-200 ms
  positioning latency on fast full-axis head motion) was unchanged with it on. Reading: the delay lives
  upstream of where 0098 acts (SLAM anchor age / prediction latency, Monado side, versus SteamVR's own
  photon-time extrapolation), so a better velocity number at a stage that is not the bottleneck does not
  help. Harmless, no observed downside; removed from the profiles to reduce variables.

## The fork's Basalt 0014 vs. our recall-cache patch

The fork independently found the same unbounded `patches` map that Basalt's own TODO flags
(`frame_to_frame_optical_flow.h`), and shipped a bounded-cache patch plus a process-level backstop,
`scripts/vrserver-memory-guard.sh`. Their number: one session reached 49 GB in about an hour; ours: 18 GB
RSS within about two to three minutes at rest, 7.5 M patches, +1,953/frame (docs/80). Same bug.

- **One container each, different policy.** Theirs recomputes `live_landmarks` fresh from
  `latest_lm_bundle` on every call, so it never grew the `patch_last_seen` container our 0018 had to fix.
  Their "recent" grace is ID-space (`last_keypoint_id - 4096`); ours is frame-count (default 90 frames =
  3 s, `BASALT_RECALL_PATCH_GRACE_FRAMES`). They hard-cap the map at 16,384 entries and **stop inserting
  new patches** once the cap is full of live/recent ids; ours has no ceiling.
- **Their cap would defeat our recall win in our configuration.** The shipped Aircar `SLAM_CONFIG` runs
  recall on top of `vio_marg_lost_landmarks: false`, where recall's value is re-attaching the *same*
  landmark IDs after a sweep. Our soaks show the live+grace working set at 249 k (p50) to 385 k (p99.9)
  patches, one to two orders of magnitude above 16,384. Once `live_landmarks` alone exceeds the cap, their
  insert guard permanently stops recording, so every later keypoint has nothing to recall. Their cap
  reads as sized for stock recall with `marg_lost_landmarks` on.
- **Code risk in theirs**: `pruneRecallPatchCache()` runs every frame and, once at the cap, does a full
  scan-and-erase of the whole map every frame, the same unamortized-sweep shape our 0016 fixed (worse:
  every frame, forever). No env override to disable the cap for an A/B.
- **The genuinely new idea**: `vrserver-memory-guard.sh` watches `vrserver` RSS from outside the process
  (warns at half of a 4 GB default limit, requires three consecutive over-limit samples, then stops the
  launcher and SIGKILLs after a 10 s grace). It is orthogonal to any recall-map fix and would catch a leak
  neither patch bounds; worth adopting in a launcher.

**Verdict**: do not adopt their 0014 in place of ours (it would quietly regress the shipped config once
the cap fills); take the memory-guard idea. For an upstream Basalt contribution, ours is the better base
patch but must disclose the `marg_lost_landmarks: false` interaction, since upstream has likely only
exercised recall with marg-lost on.
