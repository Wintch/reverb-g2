# 130 — SLAM_PRED_POSITION_HORIZON_MS swept offline: a real candidate, not yet worn-confirmed

Date: 2026-09-23, autonomous/no-wearer session on iashur. Closes the sweep `docs/124` set up
("It has never been tested on Dalí") using the offline replay path, no headset needed. Dataset:
`/mnt/resolve_test/g2-datasets/headref2_20260913171334` (the same one validated against a worn
run in docs/124). All four configs replayed serially, 1x, per
[[project_offline_slam_config_sweeps]]'s rules.

## What was compared

| label | knobs |
|---|---|
| `shipped-dali` | none — today's actual Dalí profile: no `SLAM_PRED_FREEZE_POSITION`, raw unclamped Basalt position (per `vr-launcher.py`'s own comment, "on purpose") |
| `full-freeze` | `SLAM_PREDICTION_TYPE=2 SLAM_PRED_FREEZE_POSITION=1 SLAM_PRED_NECK_ARM_MM=0 SLAM_PRED_POSITION_HORIZON_MS=0` — the config the 2026-09-13 neck-arm sweep used (0mm arm, its own established winner), horizon off |
| `horizon50` | same + `SLAM_PRED_POSITION_HORIZON_MS=50 SLAM_PRED_POSITION_MAX_SPEED_CM_S=150` |
| `horizon100` | same, `HORIZON_MS=100` |

## Result: the horizon knob is a clean win over BOTH alternatives, on every axis measured

| | overall p50 | overall p90 | overall p99 | walk-fwd p50 | walk-side p50 |
|---|---|---|---|---|---|
| shipped-dali | 6.3mm | 50.6mm | 107.3mm | 16.6mm | 20.3mm |
| full-freeze | 6.1mm | 49.7mm | 109.5mm | 16.4mm | 20.4mm |
| **horizon50** | **4.0mm** | **33.5mm** | **77.2mm** | **9.6mm** | **11.7mm** |
| **horizon100** | **3.8mm** | **33.4mm** | 79.2mm | **9.5mm** | **11.6mm** |

`shipped-dali` and `full-freeze` are statistically the same on every segment (both routine
segments and yaw/pitch-rate bins) — freezing position outright neither helps nor hurts versus
today's unclamped default, in this replay. Both horizon variants beat both of them by roughly
40% on the walk segments and by a similar margin on every yaw/pitch bin and every single-axis
routine segment (yaw-slow/med/fast, pitch-slow/med/fast, roll-slow/fast) without exception.
horizon100 edges out horizon50 on p50/p90; horizon50 edges out horizon100 on p99 (77.2 vs 79.2ms)
— the two are close enough that either would be a reasonable pick.

**This directly answers the open question left in `docs/124`/`docs/113`/`docs/128`**: the
never-tested `SLAM_PRED_POSITION_HORIZON_MS` lever is not just "worth trying" — on this replay it
is a strict improvement over what Dalí actually ships today.

## Why this is a candidate, not a shipped change

- **This is a replay, not a worn confirmation.** `docs/124`'s own validation showed replay numbers
  track a worn run within 6-25% on the fast-motion bins that matter here, which is good but not
  identity. Per this whole project's standing rule (`CLAUDE.md`: "verification is physical" /
  [[feedback_verify_rendered_not_source]]'s general form), this result needs a wearer to actually
  feel it before it goes anywhere near the booth profile.
- **The recording is Aircar-shaped, not Dalí-shaped.** `headref2` was built for the seated,
  cockpit-style neck-arm sweep — smooth, deliberate single-axis motion. Dalí is head-gaze
  navigation; its actual motion profile (how much walking/turning a guest really does staring at
  a sphere) was never characterized. The improvement direction is unlikely to reverse, but the
  *magnitude* on Dalí's real usage pattern is unmeasured.
- **`vr-launcher.py`'s comment says the unclamped choice for Dalí was deliberate** ("the only
  approved title that receives Basalt's position unclamped"), but the comment doesn't record
  *why* beyond a lighting caveat (the dark-room P2 gate-run invalidation, which is unrelated to
  this knob). Worth confirming with whoever made that call, or re-deriving it, before assuming
  this sweep supersedes it.
- No fps/CPU cost was measured for this knob specifically (the extra branch in
  `t_tracker_slam.cpp` is cheap — a handful of scalar ops — so a real regression is unlikely, but
  "unlikely" is not "measured").

## Recommended next step

A short worn Dalí session, `horizon100` (or `horizon50`) vs the current shipped default, asking
specifically about the walking-delay feel this sweep targets — the same "ask about the specific
artifact, not 'does it feel good'" protocol the 2026-09-13 neck-arm sweep used. If confirmed,
promote into `TITLE_PROFILES["591360"]` in `vr-launcher.py` as a deliberate, documented change
(not a silent default flip), noting this sweep as the evidence.

Raw CSVs and full per-segment/per-bin tables: `iashur:/mnt/vrtmp/replay-{shipped-dali,full-freeze,
horizon50,horizon100}-*/out/`. Driver script and per-config `.out` logs:
`iashur:~/vr/logs/horizon-sweep-20260923/`.
