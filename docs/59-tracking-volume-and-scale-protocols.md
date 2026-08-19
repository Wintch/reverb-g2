# Tracking-volume and scale protocols: fixture design + three measurement procedures

**Status: DESIGNED, NOT YET RUN.** Every protocol in this document is a plan, written the
same session it was motivated by (T223, `docs/58`'s ADDENDUM) but before any of it was
executed with a real fixture. Where a number below comes from prior measurement it is cited;
everything else is a proposed target or threshold, marked as such.

## Why this document exists

`docs/58`'s ADDENDUM (2026-08-19, T223) opened three questions with a tape measure and
closed none of them, for one shared reason: a human placing a controller "at 50 cm" twice
produced readings 26 mm apart. That is not measurement noise in the tracker — it is
measurement noise in the *method*. Below ±3 cm, a tape and a hand cannot tell the tracker's
answer from the placer's error. All three open questions need better than ±3 cm:

1. **Absolute scale of the constellation solve has never been validated in this project.**
   At a tape-measured 50 cm the right controller read 0.551 m (σ 0.002) and, on a second
   placement, 0.525 m (σ 0.001) — sub-millimetre *repeatability*, which says nothing about
   *accuracy*. At a tape-measured 0.75 m the left controller read 0.556 m — 20 cm short, far
   beyond the ~5 cm offset expected from the camera's optical centre sitting behind the
   visor's front face. (`docs/58` ADDENDUM.)
2. **A visibility cliff sits somewhere between 50 cm and 75 cm.** With the headset
   deliberately aimed at two HID-verified-awake controllers: 50 cm gave 118 poses / 20 s
   (`processSampleFast +93`); 75 cm and 100 cm gave **zero** camera samples
   (`processSampleFast +0`) — not failed searches, no samples at all. An arm's reach is
   ~70 cm, so this edge, if real, bounds the usable play volume to less than a natural
   reaching pose. (`docs/58` ADDENDUM.)
3. **Gain buys range and pays in solve quality.** `WMR_CONTROLLER_CAM_GAIN=255` (patch
   0083; controller frames are otherwise fixed at 6000 µs / gain 100 and never adapt, unlike
   the SLAM cameras' auto-exposure, `docs/56`) turned the 75 cm zero into 87 poses — but
   those poses disagreed with the tape (left 0.556 m for 0.75 m; right 0.057 m, impossible),
   consistent with `docs/46`'s recorded correlation between over-bright LEDs and ghost
   solves. (`docs/58` ADDENDUM.)

All three protocols below reuse one fixture and one battery-control rule, and all three are
designed so that a **difference** between two measured points, not a single absolute
reading, carries the conclusion — because the one thing already proven is that a single
absolute reading cannot be trusted to ±3 cm by hand.

## 1. The fixture

### What it must control, and why

- **Distance** — the entire point. Needs to be settable and repeatable to a few millimetres,
  not the ~26 mm the hand-placement method delivered.
- **Height** — the constellation solve is 3D; an uncontrolled vertical offset changes the
  true straight-line camera-to-controller distance even when the horizontal placement looks
  identical. Fix the controller at head/camera height, not table height, unless the protocol
  explicitly says otherwise.
- **Orientation** — the LED ring's visible face changes with the controller's rotation
  relative to the cameras. A different orientation exposes a different subset of LEDs
  (`visible_leds` in the log line below), which changes `matched_blobs` and
  `reproj_err_px` independently of true distance. An unrepeatable orientation confounds
  every protocol here — a "worse" reading at a longer distance could just be a worse LED
  view, not a real range or scale effect. The fixture must hold the controller's **front
  face square to the headset** (the same face a wearer presents when reaching forward,
  since that is the pose these protocols exist to characterize) at every distance tested.
- **The reference point on the headset.** `docs/58`'s own ADDENDUM already states the trap:
  the camera optical centre is **not** the visor's front face, and the gap between them
  (order of a few cm) is exactly the kind of fixed offset that a naive single-distance
  reading cannot separate from a real scale error. This is *why* every protocol below is
  built on **differences between two or more distances** rather than one absolute reading —
  a fixed unknown offset (optical-centre-to-visor-face, or fixture-zero-to-controller-LED-
  centre) is a constant that **cancels** in a difference or in the intercept of a fitted
  line, and does not need to be measured directly. The fixture only needs one property to
  make this work: its own zero point must be a *fixed, repeatable* physical feature (e.g.
  the point where a string or rod attaches to the headset mount), not a moving human hand.

### Option A — string-and-knots (low effort, ~15 minutes to build)

Materials: a length of non-stretch string or twine (cotton kite string, not elastic), a
tape measure, tape or a binder clip, something to mark knots.

1. Anchor one end of the string to a fixed point on the headset itself — a strap buckle or
   the top strap's rear adjustment wheel is a good, low-torque attachment point that will
   not shift the visor's own pose when the string is pulled taut. Note *which* fixed point
   was used; that is the fixture's zero, and it must be the same point for the whole
   session.
2. With the string pulled straight and level (use a level or eyeball against a horizontal
   reference), tie a knot at each target distance measured from the anchor point (e.g. 30,
   40, 50, 60, 70, 80, 90, 100, 120 cm — space more densely near where the cliff is
   suspected, see protocol (b)).
3. To take a reading: pull the string taut, hold the controller at the knot for the target
   distance, orient its front face toward the headset (eyeball to within ~10-15°; this
   method cannot do better — see precision below), and trigger the capture.
4. **Precision this buys**: distance repeatability of roughly ±5-10 mm (limited by how
   consistently the string is pulled taut and how precisely the controller is centred on
   the knot) — a large improvement over the ~26 mm hand-placement error, but not
   millimetre-grade. Orientation control is the weak point of this option: ±10-15° by eye.
   Good enough to (a) fit a scale line across several distances and (b) bound the
   visibility cliff to within a knot spacing (recommend 5 cm spacing near the suspected
   edge). **Not** tight enough to trust a single gain-sweep quality comparison at the
   millimetre level — average multiple samples per point (see protocol (c)).

### Option B — rigid arm / boom (higher effort, ~30-45 minutes to build)

Materials: a straight rigid rod or dowel (a broom handle, closet rod, or similar — must not
sag under the controller's weight), a way to clamp or tape it to a fixed chair/table so one
end sits at a known, fixed position relative to where the headset will be worn, marked
distances along its length, and a simple bracket or cradle (folded cardboard, a cable tie
loop) at the working end to hold the controller in a fixed orientation.

1. Fix the rod's near end at a **known, reproducible position relative to the wearer's
   head** — the cleanest version of this is not attached to the headset at all: seat the
   wearer in a fixed chair, mark the chair and headset position on the floor with tape, and
   clamp the rod's near end to the chair itself at a marked height matching eye/camera
   height. This trades "attached to the headset" (Option A, simpler but the string moves
   with every head tilt) for "attached to a fixed chair the wearer sits still in" — more
   setup, much better repeatability, because the rod cannot droop or swing the way a
   pulled string can.
2. Build the cradle so the controller sits in it at one fixed orientation only (front face
   toward the headset) — a snug notch or a strip of tape across the controller's back is
   enough; the goal is that removing and replacing the controller returns it to the same
   orientation within a couple of degrees, not by eye each time.
3. Mark distances along the rod in the same way as Option A's knots.
4. **Precision this buys**: distance repeatability of ~2-3 mm (limited mainly by how well
   the cradle registers the controller each time), orientation repeatability of a few
   degrees (limited by the cradle's snugness). This is the version worth building before
   trusting protocol (a)'s scale fit to better than a centimetre, or before trusting
   protocol (c)'s quality comparison at each gain level to be measuring the setting and not
   fixture noise.

Either option: **take the wearer's head/eye height into account.** `docs/58`'s ADDENDUM
also corrected the standing eye height (1.70 m, was wrongly 1.76 m) and seated (1.35 m, was
an unverified 1.40 m) — mount the fixture so the controller sits at roughly the wearer's
seated eye/camera height, since that is the height these protocols are meant to
characterize (a controller held out in front at chest/eye height, not on the floor).

## 2. Battery control (applies to all three protocols)

Every open question above has battery brightness as a live, uncontrolled confound (`docs/46`
addenda, `docs/56` §Battery findings): dim LEDs starve blob detection, over-bright LEDs
correlate with ghost solves — a two-sided damage curve, not a simple "more charge is
better" one.

**Rule: every protocol run must start and end inside the same raw-byte band, and the choice
of band must be stated and held constant across all runs being compared.**

- The alert threshold is raw byte **85** (`docs/53`, cited in `docs/46` §3) — never start a
  run below this.
- `docs/46`'s linear voltage fit is validated only in the **~65-150** raw-byte band (settled
  NiMH, not fresh-off-charger, not under load-sag). This is the recommended band for these
  protocols precisely because it is the one range with a validated interpretation.
- **Byte > 150 is chemistry-ambiguous and additionally a known ghost-solve risk**, not just
  "extra safety margin": fresh alkaline reads ~208, fresh-off-charger NiMH reads ~204-206
  (`docs/46` addenda, both 2026-08-19), and `docs/56` recorded a fresh-alkaline (3.1 V)
  right hand hitting a 97% gravity-gate drop fraction versus 8% for the same hand on
  settled 2.5 V NiMH. Running these protocols on a freshly-charged or fresh-alkaline pair
  risks measuring the brightness confound instead of the thing under test.
- **Recommended band for these protocols: raw 100-150, settled NiMH (rested at least a few
  minutes after charging, not straight off the charger).** This sits inside the validated
  fit band and away from both the low-alert edge and the high/bright edge.
- Read the raw byte with `scripts/controller-battery-check.py` (or `preflight.sh`/
  `controller-pair-check.py`, §3) immediately before and after every window. **A window
  whose battery drifted outside the chosen band — in either direction — is void. Log it as
  void, do not average it in, and do not report its numbers as noisier-but-usable.** This
  is the same discipline the drop path in `docs/58` learned the hard way: a silently
  degraded sample looks like ordinary noise until someone checks.
- If left and right are on different chemistries or different charge states, treat them as
  two independent experiments — do not compare a fresh-alkaline right hand's numbers to a
  settled-NiMH left hand's.

## 3. Invalidation rules (read before running any protocol)

Learned directly from T223's own false starts (`docs/58` ADDENDUM, `docs/pruebas.jsonl`
T223):

1. **A window whose controllers were asleep is not a control.** T223's own adversarial
   subagent found that a "drift" window offered as evidence had the controllers powered
   off the whole time — it proved nothing, and the claim built on it had to be retracted.
   Verify both controllers are awake and HID-responding **before** starting the window, not
   just assumed from the LED.
2. **A window with the headset on the desk is not a control for anything worn.** The
   camera's field of view, exposure regime, and the wearer's own head micro-motion are all
   different worn vs. static-on-a-surface; a desk measurement bounds what the fixture and
   the geometry can do, but it is not a substitute for the worn number these protocols are
   ultimately in service of.
3. **Zero counters mean "no data," never "a result."** `docs/58`'s own trap, restated for
   this document: `processSampleFast +0` at 75 cm looks identical, in every available
   counter, to a dead pipeline. Do not report a zero-sample window as "0% solve rate" or
   "no ghosts" — it is not evidence of anything until liveness is independently confirmed
   (rule 4).
4. **Verify controller liveness before AND after every window**, not just before — a
   controller can auto-sleep mid-window (T223 lost its first 272 s measurement window this
   way, caught by the wearer, not the instrumentation). Verification tools:
   - `~/vr/preflight.sh` — direct HID probe, bypasses Monado, confirms the controller is
     alive and responsive independent of tracking state.
   - `python3 ~/vr/controller-pair-check.py` — pairing/registration check.
   Run one of these immediately before the window opens and immediately after it closes.
   If the post-check shows the controller went to sleep or dropped at any point during the
   window, the window is void — do not try to salvage the portion that looks clean, because
   there is no log line that reliably brackets exactly when within the window it happened.
5. **The discriminator for "genuine zero" vs. "pipeline dead":** bring the controllers back
   to a known-good distance (50 cm, per T223) and confirm samples resume immediately. If
   they do, the zero at the test distance was genuine; if they do not, the whole window
   (including any earlier "genuine zero" readings) is suspect and must be re-run after
   fixing whatever broke.

## 4. Protocol (a) — absolute scale

**Question**: does the constellation solve's reported distance scale correctly with real
distance, or is there a multiplicative scale error (as opposed to just the expected fixed
optical-centre-to-visor-face offset)?

**Design**: the unknown, fixed optical-centre offset is a constant added to every reading
at a given true distance. It cannot be removed by looking at one reading, but it drops out
of a **linear fit across multiple distances** — the offset becomes the fit's intercept, and
the *slope* is what tells you whether scale is correct, independent of where the zero point
actually sits.

**Varies**: true distance (fixture setting), 5+ points spanning the known-visible range,
e.g. 30, 40, 50, 60, 70 cm on the fixture from §1 (do not exceed the visibility cliff found
in protocol (b) — if 70 cm turns out to be past the edge, use the highest visible point
instead).

**Held constant**: orientation (controller front face toward headset, fixture-controlled),
height (fixture-controlled, at seated eye height per §1), battery band (§2, 100-150 raw,
same pair for the whole run), gain/exposure (leave at the driver default —
`WMR_CONTROLLER_CAM_GAIN` unset, 6000 µs / gain 100 — this protocol is about geometry, not
about the gain lever protocol (c) studies), lighting (the setup criterion from `docs/56`:
≤3 spurious blobs/camera with zero controllers visible, checked once at session start).

**Commands / env**:
```
# no gain/exposure override -- default fixed 6000us/gain100
WMR_CONSTELLATION_CONTROLLERS=1 CONSTELLATION_TRACKER_LOG=info ./scripts/jack-in-wayland.sh 1 6dof
```
Capture the driver's own `constellation sample #N` lines (throttled ~2/s at 30 fps,
`wmr_controller_base.c`):
```
constellation sample #<N>: pos=(x, y, z) matched_blobs=<n> visible_leds=<n> reproj_err_px=<f>
```
`pos` is in the camera-relative frame at this call site (pre-world-composition) — use its
magnitude, `sqrt(x^2+y^2+z^2)`, as the reported distance for this protocol; do not read the
world-frame position, which carries the SLAM origin's drift as an unrelated additive term
(`docs/58`'s whole subject).

**Record, per fixture distance**: at least 30 consecutive `constellation sample #` lines
(≈15 s at the ~2/s throttled rate), their mean and standard deviation of reported distance,
`matched_blobs`/`visible_leds`/`reproj_err_px` for the same window, raw battery byte before
and after.

**Samples**: 5+ fixture distances, each protocol-(a)-invalidation-checked (§3) before and
after.

**Decision rule** (verbatim):
> Fit reported distance = **slope** × true distance + **intercept** by least squares across
> the 5+ points. **Slope in [0.95, 1.05] means scale is correct** (matches the ordinary
> ±5% this project's own repeatability numbers already suggest is achievable by hand-eye
> placement error alone, so anything inside that band is indistinguishable from measurement
> noise, not evidence of an error) and the intercept is the true (offset + fixture-zero
> constant), not itself diagnostic of a bug. **Slope outside [0.90, 1.10] is a real scale
> error** worth chasing in the solver's own metric assumptions (e.g. a unit mismatch or a
> miscalibrated baseline in the LED constellation geometry) — a slope error is a
> *multiplicative* problem and cannot be fixed by adjusting an offset/intercept term.

## 5. Protocol (b) — visibility cliff mapping

**Question**: where exactly does the camera stop returning any samples, and is that a real
detection-range limit or a field-of-view / aiming artifact?

**Design**: T223 found 50 cm healthy (118 poses/20 s) and 75 cm/100 cm at zero
(`processSampleFast +0`) with the headset deliberately aimed at both controllers. The edge
sits somewhere in 50-75 cm and is currently unbounded to better than 25 cm.

**Varies**: distance only, swept in 5 cm steps from 50 cm to 100 cm using the fixture (this
directly needs the fixture — the hand-placement method that found the original cliff had no
way to space points finer than "50" and "75").

**Held constant**: orientation and height (fixture-controlled, front face toward headset,
same as protocol (a)), aiming (headset itself pointed directly at the fixture's controller
position for every distance — re-verify aim at each step, since the fixture is fixed but a
worn headset can drift; use a second person or a mirror to confirm the controller sits
centred in the camera's expected FOV, not near its edge), battery band (§2), gain/exposure
at default (same as protocol (a) — this protocol characterizes the *default* cliff; the
gain-sweep protocol (c) is what studies whether raising gain moves this edge, and should be
run only after this baseline is mapped).

**Commands / env**:
```
WMR_CONSTELLATION_CONTROLLERS=1 CONSTELLATION_TRACKER_LOG=trace ./scripts/jack-in-wayland.sh 1 6dof
```
At `trace` level the per-camera line is visible directly (`t_constellation_tracker.cpp`):
```
Starting fast processing for camera <ptr> with <N> blobs
```
and the delivered-pose counter `processSampleFast` cited in `docs/58` — count non-zero
returns over a fixed window at each distance.

**Record, per distance step**: window length (recommend 20 s, matching T223's own window),
raw count of `processSampleFast` successes in that window, blob count per camera from the
`trace` line, raw battery byte before/after, and — critically — a same-session bracketing
check at 50 cm (known-good) run immediately before and after each new distance, per the §3
rule 5 discriminator.

**Samples**: every 5 cm step from 50 to 100 cm (11 points), each independently
liveness-checked (§3) before and after.

**Decision rule** (verbatim):
> The cliff distance is the **shortest step, moving outward from 50 cm, at which the
> non-zero-sample rate drops below 10% of the 50 cm baseline rate AND the immediately
> following 50 cm bracketing check recovers to within 20% of the original 50 cm baseline**.
> The second clause is what discriminates a genuine detection-range limit from a
> field-of-view/aiming problem or a stalled pipeline: **if the bracketing check at 50 cm
> also fails to recover, the zero at the tested distance is NOT evidence of a range limit —
> it is evidence something broke (pipeline stall, controller sleep, aim drift) and the whole
> step must be discarded and re-run**, per §3 rule 5. Only a step that (i) reads near-zero
> itself and (ii) is bracketed by two healthy 50 cm checks counts as a located edge.

## 6. Protocol (c) — gain sweep scored on solve quality

**Question**: does raising `WMR_CONTROLLER_CAM_GAIN` past the default 100 buy usable range,
or does it only buy more *wrong* poses? T223's own first hardware run of gain=255 at 75 cm
produced 87 poses that disagreed with the tape by up to 20 cm (left) and were physically
impossible (right, 0.057 m) — the headline lesson is that **pose count alone is the wrong
metric**; this protocol is designed around metrics that actually catch that failure.

**Varies**: `WMR_CONTROLLER_CAM_GAIN` ∈ {100 (default/baseline), 150, 200, 255}, at a single
fixed fixture distance chosen to sit just past the visibility-cliff edge located by protocol
(b) — the whole point of raising gain is to recover a distance the default cannot see, so
testing it at a distance the default already handles fine is not informative.

**Held constant**: fixture distance (one value, the one just past the cliff), orientation
and height (fixture-controlled, same as (a)/(b)), battery band (§2 — this one matters
doubly here, since gain and battery brightness are two independent routes to the same
LED-saturation failure mode `docs/46` documents; do not let battery drift be a second
explanation for a quality change attributed to gain), exposure at default (6000 µs;
`WMR_CONTROLLER_CAM_EXPOSURE_US`, patch 0083, not varied by this protocol — a combined
exposure×gain sweep is future work, out of scope here).

**Commands / env**:
```
WMR_CONSTELLATION_CONTROLLERS=1 WMR_CONTROLLER_CAM_GAIN=<100|150|200|255> \
  CONSTELLATION_TRACKER_LOG=info ./scripts/jack-in-wayland.sh 1 6dof
```
Confirm the override took effect via the driver's own confirmation line (seen live in
T223): `Controller-tracking exposure/gain OVERRIDE: 6000/<gain>`.

**Quality metric — defined from what the logs actually expose**, not from pose count:

For each `constellation sample #N` line in the window, the log already carries
`matched_blobs`, `visible_leds`, and `reproj_err_px`. Define, per gain level:

- **`agree_frac`** — fraction of samples whose reported distance
  (`sqrt(x^2+y^2+z^2)`, camera-relative, per protocol (a)) falls within ±5 cm of the
  fixture's known true distance. This is the primary quality signal, because it is the one
  metric that directly caught T223's failure (poses that existed but were wrong).
- **`reproj_err_px`, mean and p90** — the solver's own internal residual; a ghost lobe can
  still reproject well (`docs/58`'s main narrative: a wrong-lobe solve can have reprojection
  error as good as the true one), so this is a secondary/diagnostic signal, not sufficient
  on its own, but worth recording since a spike here alongside a drop in `agree_frac` helps
  distinguish "solver confused" from "solver confident but wrong."
- **`matched_blobs` / `visible_leds` ratio, mean** — how much of the expected LED pattern
  is actually being matched; a low ratio at high gain is consistent with `docs/46`'s
  blob-bloom/saturation mechanism (neighbouring LEDs merging into one blob at high
  brightness), and would explain a quality drop mechanistically rather than just measuring
  it.
- **Distance spread**: σ of reported distance across the window (already used in `docs/58`
  ADDENDUM to characterize repeatability at 50 cm — 1-2 mm there). A rising σ at higher gain
  alongside a falling `agree_frac` indicates the extra poses are noise, not signal.

**Record, per gain level**: 30+ consecutive `constellation sample #` lines (or the largest
number obtainable in a 20 s window if the sample rate is low), `agree_frac`, mean/p90
`reproj_err_px`, mean `matched_blobs`/`visible_leds` ratio, distance σ, pose *count* (kept
for reference only — explicitly not the decision metric), raw battery byte before/after.

**Samples**: 4 gain levels × the fixed post-cliff distance, each independently
liveness-checked (§3).

**Decision rule** (verbatim):
> A gain level is a **net win over the default** only if it raises `agree_frac` above the
> default's own `agree_frac` at the same distance (the default may well score `agree_frac`
> ≈ 0 at a post-cliff distance, since by construction it delivers few or no samples there —
> in that case any level with `agree_frac` > 0 and reasonably tight distance σ is already an
> improvement). **A gain level that raises pose count but does NOT raise `agree_frac`
> relative to the previous level is not an improvement, regardless of how many more poses it
> produces** — this is the direct correction of T223's own gain=255 result, which produced
> more poses with worse agreement (left 20 cm off, right physically impossible) and would
> have looked like a win under a pose-count metric alone. **The recommended live gain
> setting is the lowest level tested whose `agree_frac` is at or near its maximum across the
> sweep** — not the highest gain that produces any poses at all — on the principle that
> unnecessary brightness only adds ghost-solve risk (`docs/46`) without a quality benefit
> once agreement has already peaked.

## 7. Open after these protocols run

These protocols are designed to close the three questions in §0/T223, not to reopen new
ones — but two things are already known to be out of scope and worth naming so they are not
conflated with a protocol result:

- **Combined exposure×gain sweep.** `WMR_CONTROLLER_CAM_EXPOSURE_US` (patch 0083) is held
  fixed at the driver default throughout; whether varying exposure and gain together buys a
  better quality/range tradeoff than gain alone is a separate, larger sweep, deliberately
  deferred.
- **The near-pure-yaw ghost class** (`docs/58`, "What is still open") is a correspondence
  problem, not a range or scale problem — a controller at the correct distance and gain can
  still be assigned a 180°-yaw-rotated pose. None of the three protocols here are designed
  to catch that failure mode (agree_frac as defined checks distance agreement, not
  orientation), and a clean result on all three protocols above should not be read as
  evidence that class is fixed.
