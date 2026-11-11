# 129 — Phase A of the hare_ware handoff: exposure x LED intensity on a G2, run for real

Date: 2026-09-23. Desk session, headset connected, both controllers powered on throughout,
nobody wearing anything; controllers placed in front of the headset by hand. Covers Phase A of
the hare_ware A/B handoff (exposure x LED intensity). Phase B (building and running hare_ware's
branch) was not run.

## Caveats, stated up front

- **Right controller never registered, in any of the four runs** (`WARN [wmr_hmd_create] Failed
  to request controller status from HMD`). This is the pre-existing controller startup-race bug
  (see `docs/03-controllers.md`) recurring, not something Phase A caused: every number below is
  device 0 (left) only. Three back-to-back down/up cycles with both controllers powered on did
  not fix it, matching the earlier "left wins every time" finding.
- **No battery-level readings** (`controller-battery-check.py` needs the libmonado connection
  that each teardown removes), so the numbers can be neither blamed on nor cleared of a battery
  effect.
- **Room light not characterised** beyond "moderately lit room, not dark"; no lux measurement.
  A dark room or a headset-hand distance mismatch can produce a zero that looks like a real
  result.
- Each run's window is a few minutes, single session, n=1 per cell, like the earlier numbers
  this compares against.

## Results

| Run | Exposure/gain | LED intensity | Poses found (device 0) | Max blobs/frame seen | Notes |
|---|---|---|---|---|---|
| A1 | 6000/100 (default) | 0 | 1826 | 21 | Also: 9 contested-blob-recovery attempts, **1 succeeded** (`device 0 RECOVERED via all-blobs search after 19 consecutive deep-search failures`); device 1 attempted recovery 4 times, never succeeded, 0 poses all session. First confirmed non-zero success for the 2026-09-14 `CS_FLAG_MATCH_ALL_BLOBS` fix (previous count was 0/15). 559 "Tracker is likely running slow" warnings. |
| A2 | 6000/100 (default) | 200 | 530 | 26 | Higher peak blob count than A1; single-session, not a controlled A/B, but directionally consistent with driving the LEDs helping. |
| A3 | 400/1 | 0 | **0** | 0 (zero `blob ownership` lines in ~750 log lines) | Clean reproduction of the earlier "black" result: short exposure, no LED command, this G2, this light: nothing detected at all. |
| A4 | 400/1 | 200 | **970** | 9 | **Short exposure DOES work on this G2 once the LEDs are driven at the Windows-style intensity.** Fewer simultaneous blobs than A1/A2 (9 vs 21/26; plausibly the short exposure only catches the brightest, closest LEDs), but consistently above the 4-blob floor and far more accepted poses than A1 in a comparable window. |

## What this means for the hare_ware issue and our own defaults

The issue we posted (`hare_ware/monado` #1) said our 400/1-black-vs-6000/100-clean numbers were
taken with the LEDs at firmware default (no intensity command at all) and might not carry over
to a stack that drives them. **A3 vs A4 is exactly that test, and the answer is that they do not
carry over.** A short exposure is not inherently unworkable on a G2 controller camera; it needs
the LED drive to go with it.

For our own stack, A1 (the current default) already works and has more simultaneous blobs than
A4. Whether A4's shorter exposure buys anything real (lower motion blur in fast motion was the
original hypothesis) was **not tested**: all four runs were at rest, desk-only, with no
deliberate fast motion despite the plan asking for a 30 s fast-motion window per run. That
comparison is still open.

## Fresh evidence for the blob-ownership investigation

A1's full log (19634 lines, `WMR_LOG` effectively `debug` because `jack-in-wayland.sh dev`
hard-sets it, which also gave per-frame `markMatchingBlobs`/`pushPose` lines) is richer than
anything `docs/125`/`docs/126` had: 9 contested-recovery attempts, one real success, and
multiple frames with 13-21 blobs where recovery still failed.

**Mechanism of A1's one successful contested recovery:** at the frame
`device 0 RECOVERED via all-blobs search after 19 consecutive deep-search failures`, the very
next lines show `markMatchingBlobs` assigning 8 of device 0's 32 LEDs against the 21 blobs
visible, then `pushPose`: `RANSAC-PnP refinement for device 0 from 21 blobs had 8 LEDs with 8
inliers`. A clean, unanimous inlier set, not a marginal recovery.

**Placing device 1's failures in `t_constellation_tracker.cpp`:**

- `tryDeviceBlobRecovery` (the fast path, which logs `RANSAC-PnP recovered pose was good enough`
  / `... failed`) requires **>= 4 blobs already marked for that device** before it runs
  (`needed_blobs = 4`; the function's own comment calls it "the path that wins most frames").
  In this log **every occurrence of that log line is for device 0** (1095+243+210+49+48+46+37+...);
  device 1 has **zero**. This is exactly the pre-condition `docs/125`/`docs/126` named, seen in an
  actual session.
- The contested-blob escalation (`CS_FLAG_MATCH_ALL_BLOBS`) lives in `processSampleSlow` and
  **does not go through `tryDeviceBlobRecovery`**: it calls
  `correspondence_search_find_one_pose()` directly. Its failure is logged with `CT_TRACE`, not
  `CT_INFO`: `"Camera %p slow processing for device %d failed to find a pose"`.
- **`CT_TRACE` is gated by `CONSTELLATION_TRACKER_LOG`, a separate env var from `WMR_LOG`.**
  These runs never set it, so **the one log line that would explain WHY device 1's escalated
  search still fails was never emitted.** `trySeededRecovery` (the other rescue path) is in the
  same boat: 83/83 of its `CT_INFO` lines are device 0.

**Net result:** the trace narrows the open question from "why does the ownership fix not fully
work" to a precise one: does device 1's contested/seeded search (a) never find *any*
geometrically consistent candidate, (b) find one that then fails RANSAC-PnP, or (c) find one that
passes PnP but is gravity-rejected (`deviceGravityRejected`) as a wrong-lobe ghost? **No log
captured so far can answer it.** It needs a re-run with `CONSTELLATION_TRACKER_LOG=trace` (in
addition to `WMR_LOG=info`, both exported explicitly since `dev` mode hard-sets
`WMR_LOG=debug`), same desk setup, headset and both controllers on.

## Also noted

`jack-in-wayland.sh down` needed the 10 s-grace SIGKILL escalation in **5 of 5** teardowns here,
matching 5/5 from 2026-09-14 (10/10 overall). Worth investigating directly.

## Not done

- Phase B (build hare_ware's branch, run the B1-B9 checklist).
- The 30 s deliberate-fast-motion half of Phase A's own protocol.
- Battery-level and precise light readings per run.
- The `CONSTELLATION_TRACKER_LOG=trace` re-run described above.
