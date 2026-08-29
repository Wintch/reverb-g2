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

## Faulto's Basalt 0014 (2026-08-27) — the same recall-cache leak, bounded independently

Faulto's fork independently found the same unbounded `patches` map Basalt's own comment flags
(`frame_to_frame_optical_flow.h:675` in our tree, same TODO in theirs) and shipped
`patches/basalt-wmr/0014-optical-flow-bound-feature-recall-patch-cache.patch` plus a
process-level backstop, `scripts/vrserver-memory-guard.sh` (commit `247f66a8`, same day as
ours). Their number: "one real session reached 49 GB in about an hour" (README.md,
`docs/troubleshooting.md`); ours: 18 GB RSS after three minutes at rest, 7.5 M patches,
+1,953/frame (docs/80) — same bug, same order of magnitude once normalized for session length.

**One container each, different policy.** Neither fork's 0014 touches a second map. Theirs
recomputes `live_landmarks` fresh from `latest_lm_bundle` on every call
(`0014.patch:140-144`) rather than persisting a stamp, so it never grew the `patch_last_seen`
container our 0018 had to fix — no second map to leak or to full-scan. Their "recent" grace is
ID-space (`last_keypoint_id - 4096`, `0014.patch:146-148`), ours is frame-count (default 90
frames = 3 s, `BASALT_RECALL_PATCH_GRACE_FRAMES`, our `0014...patch:684-694`). Theirs also
hard-caps the map at 16,384 entries and *stops inserting new patches* once that cap is full of
live/recent ids (`0014.patch:718`, `patches.size() < RECALL_PATCH_CACHE_MAX`) — a ceiling we
never adopted; our map grows to whatever the live set needs.

**The one genuinely new idea**: `vrserver-memory-guard.sh` watches `vrserver` RSS from outside
the process — warns at half of a 4 GB default limit, requires three consecutive over-limit
samples, then calls the launcher's `stop` and SIGKILLs after a 10 s grace. Orthogonal to any
recall-map fix; it would still catch a leak neither 0014 bounds.

**Would theirs keep our recall win? Very likely not, in our configuration.** J and its
descendant P2 (Aircar's shipped `SLAM_CONFIG`) both run recall on top of
`vio_marg_lost_landmarks: false`; docs/80 is explicit that recall's value there is
"re-attaching the **same** landmark IDs after a sweep," not landmark count. Our soaks in that
regime show the live+grace working set at 249 k (p50) to 385 k (p99.9) patches (I4), 325 k at
the end of the J run — one to two orders of magnitude above their 16,384 ceiling. Once
`live_landmarks` alone exceeds the cap, their insert guard (`0014.patch:718`) permanently stops
recording new patches: every keypoint born after that point has nothing to recall from later,
silently defeating what J/P2 depend on. Their cap reads as sized for stock recall with
`marg_lost_landmarks` at its default (on), not this project's wider window.

**Code risk in theirs**: `pruneRecallPatchCache()` runs unconditionally every frame
(`0014.patch:193`) and, once at the cap, does a full scan-and-erase of the whole map every
single frame from then on — the same unamortized-sweep shape our 0016 fixed, only worse (ours
was one frame in 30; theirs is every frame, forever). No env override to disable the cap for an
A/B. **Risk in ours**: two containers to keep in sync was a real latent cost until 0018.

**Recommendation**: don't adopt Faulto's 0014 in place of ours — it would quietly regress P2
once the cap fills. Do take `vrserver-memory-guard.sh` as a candidate for this repo's launcher,
independent of which map patch runs underneath. As an upstream contribution to Basalt: both
forks hit the same un-fixed TODO independently, worth reporting on its own; ours is the better
base patch to send, but should disclose the `marg_lost_landmarks: false` interaction —
upstream has likely only ever exercised recall with marg-lost on, the regime Faulto's cap
assumes.
