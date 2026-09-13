# 125 — Controller 6DoF position: the root cause, and a plan that attacks it

**Wearer report, 2026-09-13:** *"los joys no respetan la posición. En 3dof logramos que andan
bien, en 6dof fallan bastante aún."*

This document is a read of the existing record, not new measurement. Everything numbered below
was measured in an earlier session and is cited to where it lives. The point of writing it is
that the constellation work stopped in late August at a **named next lever** that was never
taken, the work since then went to the head (SLAM/prediction), and the reasons the obvious fixes
are dead are spread across six documents. Anyone picking this up again needs all of it in one
place before touching code, or they will re-run an A/B that already has a verdict.

**Read before this:** `docs/58` (the range-check fix + its addendum), `docs/64`'s START HERE
blocks for T223/T224, `docs/40` (the CPU budget that bounds any search change), `docs/59` (the
fixture protocols, still unrun). `docs/83` §2 is the knob catalog.

---

## 1. "3dof works, 6dof fails" is the correct observation, and it is not a regression

In 3DoF the controllers have no position at all: `supported.position_tracking = false`, the pose
is the IMU fusion's orientation plus whatever arm model the application applies. Nothing can be
"wrong" with a position that is synthesised by the game from a stable orientation.

In 6DoF the constellation tracker publishes a real position, solved from the headset's cameras
seeing the controller's LED ring. That position is what is wrong. So the comparison is not
"6DoF broke something 3DoF had" — it is "6DoF adds a measurement, and the measurement is bad".
Any fix lives entirely in the constellation path.

## 2. Four distinct failure classes. Do not conflate them.

The record is explicit that these have different causes and different fixes, and that conflating
them has already cost a wrong call once.

| # | Class | Magnitude | Status |
|---|---|---|---|
| A | Near-pure-yaw ghost | **10-20 cm horizontal**, both hands | Root cause understood, unfixed — §3 |
| B | Visibility cliff | **zero samples past ~50-75 cm** | Measured once, unexplained, unfixed — §5 |
| C | Absolute scale never validated | left read **0.556 m** for a tape-measured **0.75 m** | Open question, never investigated |
| D | High-frequency jitter | **~1 cm**, both hands | Different class (re-triangulation "breathe", T203's round map item 6), never worked |

A wearer feels all four as "the hands are in the wrong place". B is the one most likely to
dominate the *felt* complaint: an arm's reach is ~70 cm, and past ~50-75 cm the tracker receives
**no camera samples at all** — not bad solves, none — so the hand stops being measured and coasts.
That is a showcase-grade limit and is not what the same hardware does on Windows.

## 3. Class A, stated precisely: a circular dependency, broken by gyro drift

The chain, each link measured:

1. The LED ring has **32 LEDs, ~11° apart**. A 1-2 LED slip in the blob↔LED correspondence
   produces a rotation of the solved pose about the vertical axis, which at ~0.45 m radius is a
   **10-20 cm purely horizontal displacement** — exactly the signature the wearer describes.
2. Choosing the right correspondence needs a trusted heading. The only heading available is the
   controller's own IMU fusion.
3. **That heading's noise under worn motion is 10-30°** — two to three LED spacings. The pool the
   heading can narrow to is therefore wider than the ambiguity it is meant to resolve.
4. The heading is corrected back from the constellation solve (`WMR_CONTROLLER_SOLVE_YAW_CORRECT`,
   patches 0066/0067). **So the solve needs the heading and the heading is fixed by the solve.**

That circle is the root cause. Everything that has been tried so far attacks it from inside the
circle, which is why none of it worked.

**Why the heading is noisy, from the code (`wmr_controller_base.c:1289`,
`m_imu_3dof.c:gyro_bias_auto`):** the fusion is a 3DoF complementary filter. Gravity observes
pitch and roll; **nothing observes yaw**, so yaw is a pure gyro integration. Gyro bias is
estimated by `M_IMU_3DOF_USE_GYRO_BIAS_AUTO`, which by construction only fires **while the
controller is still** — its whole basis is that a stationary gyro reads its own bias. Bias
measured on this hardware at rest: **72 °/min left, 20 °/min right**. Under motion — which is
when the wearer is looking at their hands — the bias is not re-estimated and the yaw integrates
freely. The class-A ghost is therefore worst exactly when it is most visible.

## 4. What is already dead. Do not re-run these.

Each of these was measured, and the measurement is in the record:

- **Tuning the gravity gate.** Blind to yaw by construction — yaw does not move the down vector.
  Also: at its suggested 14° it is a **net negative** (right hand presence 47.2% → 1.8%, delivery
  cut 4×) because that default came from a *static desk* capture. Worn value is
  `WMR_CONSTELLATION_TRACKER_GRAVITY_GATE_DEG=30`, already applied.
- **Tuning the yaw prior.** It is **provably inert** — zero rejections across a whole session
  while 3900 solve-yaw corrections ran with errors up to 22.8°. It cannot be tuned into
  usefulness: 98.8% of samples sit below 30°, and the ghost's own error lives inside the same
  band as the legitimate population (0-10° 8.2%, 10-20° 62.0%, 20-30° 27.8%). **No single global
  threshold can separate two populations that occupy the same band.** The yaw prior is the wrong
  instrument, not a mistuned one.
- **`WMR_CONSTELLATION_SEED_FIRST`.** A measured negative: a failing seeded attempt strips blob
  associations the ordinary path needs.
- **Waiting for `solve_yaw_locked`.** The lock is not the blocker; it forms under motion on both
  hands. Note also that it is **monotonic** — it means "has ever converged", never "is converged
  now", so it is not usable as a live trust signal without changing it.
- **"The left hand is worse."** Carried since T215 and destabilised: the hands **invert** between
  consecutive windows on identical config with the wearer changing nothing (L 3.6/R 62.1, then
  L 74.5/R 0.0). A blob-ownership competition was proposed as the explanation and **refuted by
  its own instrument** (0089: ~30 blobs sit unclaimed while neither hand reaches the 4-blob
  floor). Treat per-hand asymmetry as unexplained, not as a property of a hand.

## 5. Class B is separately actionable and may be the bigger felt win

Measured once, headset aimed at two HID-verified-awake controllers:

| distance | camera samples reaching the tracker |
|---|---|
| 50 cm | healthy — 118 poses / 20 s |
| 75 cm | **zero** |
| 100 cm | **zero** |

`WMR_CONTROLLER_CAM_GAIN=255` turns the 75 cm zero into **87 poses**, so the lever exists — but
those poses read 0.556 m for a tape-measured 0.75 m, and the other hand 0.057 m, i.e. gain buys
detections of poor quality — `docs/58`'s addendum reads this as the known correlation between
over-bright LEDs and ghost solves.

**A confound that invalidates any gain/exposure result taken carelessly:** the LEDs are powered
by the controller's own battery, and `docs/46` measured the cell sagging to ~79 (from a settled
~110-115) **under sustained constellation LED load**. Brightness is therefore a function of
charge state, and two runs at different battery levels are not comparable. `docs/59` §2 already
makes battery control a precondition of all three protocols — honour it.

**The trap this creates, already paid for once:** *no blobs at all is indistinguishable from a
dead pipeline* in every counter available. A blackout was diagnosed and retracted here.

`docs/59` designed three protocols for exactly this (absolute scale, visibility-cliff mapping,
gain sweep scored on solve quality) and **none has ever been run**, because all three need a
fixture that holds a controller at exact repeatable distances. A hand and a tape cannot resolve
scale better than ±3 cm — two placements a human called "50 cm" differed by 26 mm.

## 6. The enabler: there is no offline path for controllers, and that is what to build first

The head's equivalent problem was closed in a day once configs could be swept **without a
wearer** (`docs/124`): record one dataset, replay it through the real tracker, compare. The same
move is what makes class A tractable, because a heading/correspondence change needs many
iterations and each one currently costs a donning.

**It does not exist yet, and one assumption to the contrary is wrong.** The G2 runs two separate
camera streams with different exposures — `cam_sinks` for SLAM frames and `ctrl_cam_sinks` for
controller-tracking frames (`wmr_camera.c:222-223`, pushed at :683 and :718-719). The EuRoC
recorder is created **inside `t_tracker_slam.cpp`** (:2697), so it records the SLAM stream and
the headset IMU only. **The recorded datasets do not contain the controller-exposure frames, and
the controller LEDs are not in them.** They also contain no controller IMU, which arrives over
HID/Bluetooth and never passes through the tracker.

So the offline path needs, in order:

1. **A recorder on `ctrl_cam_sinks`** — the same `euroc_recorder_create` plumbing, attached to
   the controller frame stream instead of the SLAM one. Mechanically small; the recorder is
   already generic over sinks.
2. **A controller IMU log** alongside it, timestamped in the same clock. This is the part with no
   precedent in the tree and needs care: the constellation solve is only meaningful against the
   fusion state that existed at that frame.
3. **A headless driver** for the constellation tracker equivalent to `monado-cli slambatch`, so a
   recorded pair (frames + IMU) can be re-solved with different correspondence logic.
4. **A `predict-error.py` analogue** for controllers. The existing tool is generic in method
   (interpolate a reference at the sample's timestamp, express the error in body-local axes); it
   needs a controller reference, which is the open question of §7.

## 7. The honest hard part: there is no ground truth for a hand

The head instrument works because `tracking.csv` — Basalt's own later, unextrapolated estimate —
is a fair *local* reference over a ~150 ms horizon. A controller has no equivalent second
estimate. Candidates, none free:

- **A fixture** (`docs/59`): exact, but static only — it answers classes B and C, not A, which is
  a dynamics problem.
- **Solve self-consistency** (reprojection residual of the accepted correspondence): available
  per-frame and cheap, but a confidently wrong correspondence has a *low* residual — that is what
  makes it a ghost. Necessary, not sufficient.
- **Temporal consistency**: a 15 cm step in one frame is not a hand movement. This is the most
  promising instrument *and* the most promising fix, because the same signal serves both.
- **Ride-along with the head**: a controller held rigidly against the headset has a known relative
  pose. Awkward, but it turns a controller into something the SLAM pipeline can reference, and it
  is the only idea here that gives a real dynamic ground truth without new hardware.

## 8. Candidate root fixes, ranked

Everything here attacks the circle in §3 rather than thresholding inside it.

1. **Make yaw observable, so the fusion stops integrating blind.** The bias-under-motion gap is
   the named lever and is the most principled fix. Options: estimate bias during motion from the
   solve-yaw residual itself (a slow observer, not the current per-sample correction); or widen
   `gyro_bias_auto`'s stillness window so it fires more often in real use; or a temperature model,
   since the code already notes bias moves with temperature. Cheapest first experiment: log bias
   and heading residual over a worn session and see how much of the 10-30° is a slowly-varying
   bias (correctable) versus white noise (not).
2. **Temporal correspondence.** Once a correspondence is right, carry it forward and require
   evidence to change it, instead of re-solving blind every frame. Attacks the problem where it
   is decidable and is cheap in CPU — which matters, because `docs/40` showed the search has a
   real CPU budget problem and a 3 ms cap cuts real matches.
3. **Photometric / structural LED identification.** Patch 0091 already logs per-blob brightness
   per device; nobody has looked at whether it discriminates. If LEDs are distinguishable by
   anything other than geometry, the ambiguity that creates class A disappears entirely. Highest
   payoff, least evidence so far.
4. **T215's named surgery** — generate the assignment *from* the trusted heading rather than
   judging blind candidates. Recorded as the next lever by T224, then refined by a later reading:
   *"seeding narrows the pool; it cannot choose inside it"*, because the heading noise (10-30°)
   exceeds the LED spacing (11°). **So this is downstream of fix 1** and should not be attempted
   before the heading is better — it would inherit the same noise.

## 9. Proposed order of work

| Step | Cost | What it answers | Wearer time |
|---|---|---|---|
| 1. Build the fixture from `docs/59` Option A (string-and-knots) | ~15 min | Unblocks B and C, both unmeasured for a month | none |
| 2. Run protocols (a) absolute scale and (b) visibility cliff | ~1 h | Is the cliff real and still there? Is the solve's scale even right? | none |
| 3. Instrument the heading: log gyro bias + solve-yaw residual over a worn session | small patch | How much of the 10-30° is correctable bias? Decides whether fix 1 is real | one normal session, no extra donning |
| 4. Controller-frame EuRoC recorder + controller IMU log | medium patch | Makes every later iteration wearer-free | none after the first recording |
| 5. Headless constellation replay + error tool | larger | Turns class A into an offline sweep, as `docs/124` did for the head | none |
| 6. Attack class A per §8, ranked | — | — | one confirmation each |

Steps 1-3 are cheap, answer independent questions, and none of them needs the offline path to
exist. Step 2 in particular could change the whole priority order: if the cliff is the dominant
term, the wearer's complaint may be mostly class B, and class A is a smaller, later fight.

**Do not start at step 6.** The record's own lesson from this problem, earned four times over:
*a window with sleeping controllers or a headset on the desk is not a control, and its zeros are
not a result.* Every claim here that came from a measurement survived; every claim that came from
reasoning about the code was retracted.
