# 130 — SLAM_PRED_POSITION_HORIZON_MS swept offline: a real candidate, not yet worn-confirmed

Date: 2026-09-23. Closes the sweep `docs/124` set up (the position-horizon knob had never been
tested on Dalí) using the offline replay path, no headset needed. The dataset is the one
validated against a worn run in docs/124. All four configs were replayed serially, at 1x, per the
offline-sweep rules (see `docs/124` §3).

## What was compared

| label | knobs |
|---|---|
| `shipped-dali` | none: the actual Dalí profile, with no `SLAM_PRED_FREEZE_POSITION`, raw unclamped Basalt position (per `vr-launcher.py`'s own comment, "on purpose") |
| `full-freeze` | `SLAM_PREDICTION_TYPE=2 SLAM_PRED_FREEZE_POSITION=1 SLAM_PRED_NECK_ARM_MM=0 SLAM_PRED_POSITION_HORIZON_MS=0`: the config the 2026-09-13 neck-arm sweep used (0 mm arm, its established winner; pre-0115, see the caveat in docs/124), horizon off |
| `horizon50` | same + `SLAM_PRED_POSITION_HORIZON_MS=50 SLAM_PRED_POSITION_MAX_SPEED_CM_S=150` |
| `horizon100` | same, `HORIZON_MS=100` |

## Result: the horizon knob is a clean win over BOTH alternatives, on every axis measured

| | overall p50 | overall p90 | overall p99 | walk-fwd p50 | walk-side p50 |
|---|---|---|---|---|---|
| shipped-dali | 6.3mm | 50.6mm | 107.3mm | 16.6mm | 20.3mm |
| full-freeze | 6.1mm | 49.7mm | 109.5mm | 16.4mm | 20.4mm |
| **horizon50** | **4.0mm** | **33.5mm** | **77.2mm** | **9.6mm** | **11.7mm** |
| **horizon100** | **3.8mm** | **33.4mm** | 79.2mm | **9.5mm** | **11.6mm** |

`shipped-dali` and `full-freeze` are statistically the same on every segment: freezing position
outright neither helps nor hurts versus the unclamped default in this replay. Both horizon
variants beat both of them by roughly 40% on the walk segments and by a similar margin on every
yaw/pitch bin and every single-axis routine segment (yaw-slow/med/fast, pitch-slow/med/fast,
roll-slow/fast) without exception. horizon100 edges out horizon50 on p50/p90; horizon50 edges out
horizon100 on p99 (77.2 vs 79.2 mm); either would be a reasonable pick.

On this replay the previously untested `SLAM_PRED_POSITION_HORIZON_MS` lever is a strict
improvement over what Dalí ships today.

## Why this is a candidate, not a shipped change

- **This is a replay, not a worn confirmation.** `docs/124`'s validation showed replay numbers
  track a worn run within 6-25% on the fast-motion bins that matter here: good, not identity.
  Per the project's standing rule (`CLAUDE.md`: "verification is physical"), a wearer has to feel
  it before it goes into a shipped profile.
- **The recording is Aircar-shaped, not Dalí-shaped.** It was built for the seated,
  cockpit-style neck-arm sweep: smooth, deliberate single-axis motion. Dalí is head-gaze
  navigation, and its real motion profile was never characterised. The improvement direction is
  unlikely to reverse, but the *magnitude* on Dalí's real usage is unmeasured.
- **`vr-launcher.py`'s comment says the unclamped choice for Dalí was deliberate** ("the only
  approved title that receives Basalt's position unclamped"), but does not record *why* beyond a
  lighting caveat unrelated to this knob. Confirm or re-derive the rationale before assuming this
  sweep supersedes it.
- No fps/CPU cost was measured for this knob (the extra branch in `t_tracker_slam.cpp` is a
  handful of scalar ops, so a real regression is unlikely, but unlikely is not measured).

## Recommended next step

A short worn Dalí session, `horizon100` (or `horizon50`) vs the current default, asking
specifically about the walking-delay feel this sweep targets (the same "ask about the specific
artifact, not 'does it feel good'" protocol as the neck-arm sweep). If confirmed, promote into
`TITLE_PROFILES["591360"]` in `vr-launcher.py` as a deliberate, documented change, citing this
sweep.
