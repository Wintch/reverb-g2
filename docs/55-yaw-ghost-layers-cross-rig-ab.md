# Yaw-ghost layers (0074/0076/0077) cross-rig A/B: layers 1+2 validated, 0077's first hardware run found and fixed a seed-poisoning runaway (2026-08-18/19)

Everyday system (KDE/X11, 60Hz, unpatched 550 driver), headset on desk, controllers moved by
hand in front of it. Binary: dev's `lab-full` tip `fd58d9515` + 4 new commits (see
`patches/monado/0079-0082`). This is the first measurement of the yaw-ghost layer stack on a
second rig, and the **first hardware execution of 0077 (`WMR_CONSTELLATION_SEED_PRIOR`) ever**.

## Method (after several false starts — see "instrumentation traps" below)

Per-phase service relaunch (the knobs are `DEBUG_GET_ONCE`), identical ~2min choreography per
phase (45s varied movement, 45s slow pure yaw, 30s still), user marks start/end in chat, log
parsed only inside the marked window. `hello_xr` drives `get_tracked_pose` (windowed
compositor, panel off — nobody wears the headset). Metrics per hand from INFO-level counters:
accepted `sample_count` delta, `pos_tracked` ratio (throttled get_tracked_pose log), gravity
gate drops, yaw-prior rejects, solve-yaw-correct convergence, seed attempt/success/skip.

Environment control turned out to be EVERYTHING (docs/56): the confirmation series below ran
at 3-of-4 cameras zero spurious blobs, SLAM zero resets, batteries stable per-phase.

## Confirmation series (clean windows, same environment, same choreography)

| Config | Left acc | Left pos_tracked | Right acc | Right pos_tracked |
|---|---|---|---|---|
| A: all layers off | +845 | 7.9% | +51 | 0.8% |
| B: `SOLVE_YAW_CORRECT=0.05` + `YAW_PRIOR_DEG=60` (0074+0076) | +4263 | **27.2%** | +83 | 2.4% |
| C: B + `SEED_PRIOR=1` (0077 as landed) | 647* | 3.9%* | 1623* | 12.0%* |
| D: B + `SEED_PRIOR=1` + hardening fix (0082) | **+9114** | **37.2%** | **+5891** | **22.2%** |

(*C parsed over its whole run — no start mark that phase; direction is unambiguous anyway.)

**Reads:**
- **0074+0076 validated cross-rig**: left 5x accepted, 3.4x pos_tracked over baseline. The
  lock converges exactly as on dev (first correction -57 deg → <1 deg residual).
- **0077 as landed is net-harmful for an already-working hand and its seed loop runs away**
  (see below) — but even broken it lifted the drowning right hand 0.8→12%, showing the rescue
  mechanism itself is sound.
- **0077 + hardening (0082) is the best config measured on this rig, both hands**, including
  a 28x rescue of the right hand that every other config left at ≤2.4%.
- Right's baseline collapse (0.8%, 97% of its solves gravity-dropped) correlates with its
  brand-new 3.1V alkaline cells — over-bright LEDs appear to CAUSE ghost solves (docs/56).

## The 0077 bug, measured live

Seed positions logged during C ran away from the real controllers (~1m from the cameras):
`0.22,-1.00,-4.19` → `-4.29,4.75,-2.53` → `-0.92,-0.51,11.67` (12m!), 110k+ attempts/session.
Mechanism: the seed's position source was the tracker-internal `last_known_pose`, which
`pushPose` updates **unconditionally even for post-refinement-REJECTED samples** (documented
as load-bearing for ordinary reacquisition; 0076 only gated it for yaw-disagreeing samples —
position garbage that agrees on yaw, or arrives pre-lock, still writes through). Each doomed
seeded attempt re-fed the poison: a positive feedback loop. The first seed of the session was
already 4.19m off — the poisoning happens in ordinary operation; seeding just amplifies it.

## The fix (commit `9a797315a`, patch 0082)

Two changes inside `trySeededRecovery`, `pushPose` deliberately untouched:
1. **Position-source order reversed**: prefer the predicted prior (relation history —
   driver-gate-ACCEPTED samples only) over `last_known_pose`; last-known stays as the
   never-accepted-yet fallback.
2. **3m plausibility bound** on the seed's distance from the camera, with a rate-limited
   skip counter (`seed-prior: SKIPPING ...`). In D it blocked 33k+ poisoned attempts (priors
   drifting 5.9→17m) while sane ~0.65m seeds sailed through and rescued both hands.

## Open items

- **Some >3m seeds still passed the bound in D** (an attempt logged at world pos
  `0.66,-2.25,4.85` ≈ 5.4m while skips were firing) — possibly a per-camera-transform
  edge case or frame mismatch in the clamp. The guard is clearly load-bearing already;
  this residual needs a fresh-eyes pass. Also: the PREDICTED prior itself reached 17m —
  prediction extrapolation from stale samples flies away; worth bounding at the source too.
- Right-hand lock quality under bright LEDs stayed poor (residual ±28 deg swings in D even
  while pos_tracked hit 22%) — the brightness→ghost mechanism (docs/56) is the suspect, not
  the layers.
- Dev's T215 numbers (left 4.55%, right 30.3%) vs this rig's D (37.2%/22.2%) are not directly
  comparable (worn vs desk, 90 vs 60Hz, different rooms) — only within-rig deltas transfer.

## Instrumentation traps found (cost ~1.5h of invalid phases; all fixed in 0079-0081)

1. **The whole layer stack silently does nothing without `WMR_CONTROLLER_SOLVE_YAW_CORRECT`**
  (default 0 = lock never establishes → 0074/0076/0077 all inert). Dev's launcher sets it;
  a bare env-only A/B doesn't. First phase-B ran as an accidental second baseline.
2. **`get_tracked_pose`'s throttled log used a function-local static counter shared by both
  hands** — with calls interleaving evenly and an even modulo, the SAME hand wins the modulo
  boundary every time and the other hand logs NOTHING. Masked the left's entire stream and
  produced a false "left = 0 accepted" baseline. (The comment above that line already
  described this exact bug from 2026-08-11; the shared static had crept back.) Per-device
  counter now (0081).
3. The three per-device telemetry lines (get_tracked_pose / gravity gate / yaw prior) carried
  no hand identity — unparseable in a combined log (0080).
4. Controllers that wake AFTER `monado-service` starts stream packets (battery parses!) but
  get no constellation registration and no left/right role — Monado's device list is fixed at
  startup. Looks exactly like "tracking dead". Relaunch with controllers already awake.
5. Controllers die in the service down/up gap (T215's keepalive nuance) — re-wake before
  every phase relaunch, verify `Registered with constellation tracker` count == 2.

## ADDENDUM 2026-08-19 (~02:30, lab/dev, WORN) — the dev-rig re-run: the seed layer never fired, and the reason is architectural (T221)

T220's closing instruction was executed on the lab/dev machine, headset actually worn:
0082 build (`lab-full` = `9a797315a`), `SOLVE_YAW_CORRECT=0.05 YAW_PRIOR_DEG=60
SEED_PRIOR=1`, constellation on, marked choreography windows.

**Result: the A/B could not measure the seed layer, because the seed layer never
engaged — 0 `trySeededRecovery` attempts across the whole night.** Two gates blocked it:

1. **Trigger blindness (the finding that matters).** Seeding triggers on the tracker-side
   fast path *failing to find a pose*. In tonight's regime the tracker **always found a
   pose** — a wrong-lobe ghost — which the **driver-side** gravity gate (0074) then
   discarded (+3800/+3750 drops per hand in one 4.6-min window; 93–99.7% of candidates).
   The tracker never learns its poses are being thrown away downstream, so the rescue
   layer is structurally blind to exactly the failure mode it exists for. The everyday
   rig's T220 test never hit this because its failure mode was "no solves at all" (which
   does trip the trigger). **Named fix direction: feed the driver-gate rejection signal
   back to the tracker (or evaluate the yaw prior tracker-side, before delivery), so
   seeding triggers on "pose delivered but rejected", not only on "no pose found".**
2. **Lock chicken-and-egg.** Seeding also requires `solve_yaw_locked`. Under motion the
   lock never formed on either hand (left crawling 53°→18.7°, right oscillating ±30°);
   at rest both hands locked within ~3 min (L 0.7°, R −0.8°). The precondition for
   rescue only becomes true when rescue is no longer needed.

**Rest vs motion, quantified (the sharpest such measurement the project has):** the right
hand accepted **17k+ samples in ~15 min stationary on the desk**, then **+0 accepted in a
4.9-min worn choreography window** (left: +3). pos_tracked in the final locked-at-pickup
window: **left 1/145 (0.7%), right 0/145 (0%)** — far below even T215's own worn baseline
(4.55%/30.3%), a regime difference this session could not explain (environment,
choreography and build all differ; only within-night deltas are trusted, and T215's
numbers keep their pre-0081 asterisk).

**Battery chemistry retraction:** the right hand ran kub+rio **NiMH fresh off the
charger**, reading raw **191–206** — fresh NiMH overlaps docs/46's fresh-alkaline ceiling
(208). The early-night "hot alkalines" attribution was wrong; raw >150 does not identify
chemistry. Both hands (settled NiMH left at ~103 included) drowned in ghosts equally under
motion, so brightness alone does not explain this regime.

**Ops facts from the same night** (details in T221): a silent windowed-compositor fallback
hit the *Wayland* launcher (docs/51's class; recovered with
`XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="HP Inc."` + retry, attribution unsettled, override
now baked into `jack-in-wayland.sh`); `hello_xr` self-exits at ~300 s even with stdin held
open (instrumented windows need a fresh player per run); a companion USB2 re-enumeration
mid-session preceded a total constellation-candidate blackout once (stale-fd class).
