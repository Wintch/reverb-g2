# 85 — Faulto/reverb-g2-linux patch review, and two new divergence guards from it (2026-08-27)

A community fork ([`Faulto/reverb-g2-linux`](https://github.com/Faulto/reverb-g2-linux), see
[Wintch/reverb-g2#1](https://github.com/Wintch/reverb-g2/issues/1)) built a SteamVR+Lighthouse+
Index setup off this repo's patches. Reviewed all 7 of their non-verbatim patches (deep review,
ultracode, from the everyday-system session) against this project's actual current code — full
writeup in `handoff-20260827-faulto-patches/HANDOFF.md` on the everyday system. Two findings
applied here today; the rest (SteamVR-side bounded tracking volume, per-axis one-euro filter
split, Basalt landmark recall, Space Calibrator UX ideas, an NVIDIA driver 610/Blackwell
`minBpc` gap) are documented there, not applied — see that file for why each was or wasn't
taken.

## Applied: patches 0098, 0099

Both opt-in, both default off, both build clean (`ninja` in `~/vr/monado/build`, all targets).
See `patches/monado/README.md`'s own entries for the technical detail; summary here:

- **0098 `WMR_FORWARD_ANGULAR_VELOCITY`** — forwards the SLAM tracker's own angular velocity to
  SteamVR instead of always reporting zero, so SteamVR's photon-time extrapolation has real
  rotational data. Open risk not yet measured: possible double-counting against 0097's own
  prediction (`SLAM_PRED_FREEZE_POSITION`) when both are active.
- **0099 `SLAM_SESSION_ANCHOR_RADIUS_CM` + `SLAM_QUAT_NORM_CHECK`** — two more divergence guards
  next to 0023-a's speed-based one: slow accumulated drift, and a corrupted orientation
  quaternion. Real, disclosed limitation: a slow-drift trip is not self-healing the way a
  speed-spike trip is (see the in-code CAVEAT comment) — may be more useful as a diagnostic
  signal than a recovery mechanism until/unless the response path is special-cased for this
  failure mode specifically.

## Process note: two independent adversarial reviews caught a real bug before this shipped

The first draft of 0099 compared a corrupted value against a threshold directly
(`qnorm < 0.5 || qnorm > 1.5`) — which is exactly the form 0043 and other existing guards in
this file already use. Two independent reviewer agents, working from the live uncommitted diff
on this machine (not a description of it), both independently found the same defect: a
comparison against NaN is always false in IEEE-754, so that form lets a NaN quaternion — the
literal motivating case the check exists to catch — pass through completely undetected. Fixed
to a negated inclusive range (`!(qnorm >= 0.5 && qnorm <= 1.5)`) before commit, confirmed with a
standalone test. Same review pass also caught `SLAM_QUAT_NORM_CHECK` not gating on
`auto_reset.enabled`/`quiet_until` like every other guard in the file (reset-loop risk during
the post-reset settle window), and `SLAM_SESSION_ANCHOR_RADIUS_CM` not requiring
`SLAM_RESET_OFFSET_CARRY` (meaningless comparison if carry is off) — both fixed the same way.
Worth remembering as a general lesson for this file specifically: it already has an established
`x < lo || x > hi` idiom elsewhere for non-NaN-risk cases, and a naive new guard copying that
idiom for a NaN-motivated check is a natural, easy-to-miss mistake.

## Not done this session — needs a real wearer

Neither 0098 nor 0099 has been run on the actual headset. Both ship default-off specifically
because of this — flip them on for a real session before trusting either beyond "it compiles
and the logic is sound on paper."

## Follow-up, same day: wired into the launcher for the first real wearer test

`scripts/vr-launcher.py`'s `TITLE_PROFILES` for Aircar (`1073390`) and Cyberpilot (`1056970`),
both 6dof, now set `WMR_FORWARD_ANGULAR_VELOCITY=1`, `SLAM_QUAT_NORM_CHECK=1`, and
`SLAM_SESSION_ANCHOR_RADIUS_CM=300` (300cm — a generous first-pass radius for seated cockpit
head movement, chosen to avoid false-triggering on normal play while still catching a real
runaway like the "tens of metres" ones seen in dim-room sessions, T245). Both titles already carry
0097's own prediction recipe (`SLAM_PRED_FREEZE_POSITION`/`SLAM_PRED_NECK_ARM_MM`), so this is the
first time 0098 runs alongside that — the double-counting risk named above is now live and
untested, not just theoretical. Build unchanged (already compiled per the section above); this
was purely env-var wiring, no rebuild needed. First wearer session with these on is the actual
test — watch for overshoot on fast turns (0098×0097 interaction) and for `Tracker diverged`
log spam (0099's radius too tight for the title's real movement).

## First wearer result, same day (2026-08-27): guards clean, 0098 does not fix the known issue

Caught a real, if brief and unplanned, wearer session on Aircar 6dof (launched for an unattended
soak, the wearer put the headset on mid-soak). Two separate results, worth keeping apart:

- **Divergence guards (0099): clean.** ~12 minutes total runtime, `grep -c "Tracker diverged"` = 0
  the entire session, including the worn portion with real head motion. No false-positive resets.
  Session ended cleanly (`client_disconnected` → `END_SESSION`, no coredump, no SIGSEGV) when the
  wearer closed the game. Not a full validation (a false-positive is a rate question, not a
  binary one 12 minutes can fully settle), but a real, clean first data point in the right
  direction.
- **0098 (`WMR_FORWARD_ANGULAR_VELOCITY`): no perceived effect.** Wearer's own words: "seguía
  desviando bastante al girar rápido, pero se acomodaba. No parece cambiar nada" — the known
  fast-turn drift-then-settle behavior (the exact gold→approved blocker named in `DEMO_LAUNCHES`:
  a felt ~100-200ms positioning-latency on fast full-axis head motion) is unchanged with 0098 on.
  Reads as a real negative, not an inconclusive one: the double-counting risk against 0097 flagged
  above never got a chance to matter, because the intended benefit (smoother SteamVR-side
  reprojection from real angular velocity instead of zero) doesn't show up in the felt symptom at
  all. Plausible reading: the bottleneck this title's blocker traces to (SLAM anchor-age /
  prediction latency, Monado-side) sits upstream of where 0098 acts (SteamVR's own photon-time
  extrapolation) — forwarding a better velocity number to a stage that isn't where the delay
  lives wouldn't be expected to help. Not chased further this session -- worth deciding explicitly
  whether 0098 stays on (harmless, no observed downside either) or gets reverted to reduce
  variables, before the next real attempt at the gold→approved blocker itself.
