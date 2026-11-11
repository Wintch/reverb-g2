# Tracking-volume and scale protocols: fixture design + three measurement procedures

**Status (2026-11): designed, never run.** The fixture has not been built and protocols (a)-(c)
below have not been executed. They remain the stated next step in `docs/125` (plan) and
`docs/126` (which adds that the orientation confound makes any hand-held distance sweep
untrustworthy, and which retracted the "visibility cliff" as a distance effect and dropped
absolute scale from the suspect list; the protocols are now a way to confirm those, not the
leading lead). What *has* been used from this document: the **invalidation rules** (section 3,
cited by `scripts/constellation-session-report.py`) and the **battery-band rule** (section 2,
cited by `docs/125`). Numbers below come from prior measurement where cited; all thresholds are
proposed targets.

## Why this document exists

`docs/58`'s addendum opened three questions with a tape measure and closed none, for one reason:
a human placing a controller "at 50 cm" twice produced readings 26 mm apart. That is noise in the
*method*; below +-3 cm a tape and a hand cannot tell the tracker's answer from the placer's error.

1. **Absolute scale of the constellation solve has never been validated.** At a tape-measured
   50 cm the right controller read 0.551 m (sigma 0.002) and on a second placement 0.525 m
   (sigma 0.001): sub-millimetre *repeatability*, silent on *accuracy*. At a tape-measured 0.75 m
   the left controller read 0.556 m, 20 cm short, far beyond the ~5 cm expected from the
   camera's optical centre sitting behind the visor's front face.
2. **A visibility cliff sat somewhere between 50 and 75 cm.** Headset aimed at two HID-verified
   awake controllers: 50 cm gave 118 poses / 20 s (`processSampleFast +93`); 75 and 100 cm gave
   zero camera samples (`processSampleFast +0`). An arm's reach is ~70 cm, so the edge would
   bound the usable play volume below a natural reaching pose.
3. **Gain buys range and pays in solve quality.** `WMR_CONTROLLER_CAM_GAIN=255` (patch `0083`;
   controller frames are otherwise fixed at 6000 us / gain 100 and never adapt, unlike the SLAM
   cameras' auto-exposure, `docs/56`) turned the 75 cm zero into 87 poses, but they disagreed
   with the tape (left 0.556 m for 0.75 m; right 0.057 m, impossible), consistent with `docs/46`'s
   correlation between over-bright LEDs and ghost solves.

All three protocols reuse one fixture and one battery-control rule, and are designed so that a
**difference** between measured points, not a single absolute reading, carries the conclusion.

## 1. The fixture

It must control:

- **Distance**, settable and repeatable to a few millimetres (hand placement gave ~26 mm).
- **Height**: the solve is 3D; fix the controller at seated eye/camera height (seated 1.35 m,
  standing 1.70 m, per `docs/58`'s addendum), not table height.
- **Orientation**: the LED ring's visible face changes with rotation, exposing a different
  subset of LEDs (`visible_leds`), which changes `matched_blobs` and `reproj_err_px`
  independently of distance. Hold the controller's **front face square to the headset** at every
  distance.
- **A fixed, repeatable zero point.** The camera optical centre is not the visor's front face;
  that fixed unknown offset **cancels** in a difference or in the intercept of a fitted line, so
  it never needs measuring. The fixture only needs a zero that is a physical feature (e.g. where
  the string attaches to the headset), not a moving hand.

**Option A, string-and-knots (~15 min).** Non-stretch string anchored to a fixed headset point
(a strap buckle or the top strap's rear wheel: low torque, does not shift the visor), pulled
straight and level, with a knot at each target distance from the anchor (e.g. 30, 40, 50, 60,
70, 80, 90, 100, 120 cm; 5 cm spacing near the suspected edge). Hold the controller at the knot,
front face toward the headset (by eye, +-10-15 deg), and capture. Buys distance repeatability of
roughly +-5-10 mm; orientation is the weak point. Average several samples per point.

**Option B, rigid boom (~30-45 min).** A straight rod clamped to a fixed chair at seated eye
height, marked distances, and a cradle that holds the controller in one orientation. Buys ~2-3 mm
distance and a few degrees of orientation repeatability; build it before trusting protocol (a)
better than a centimetre or protocol (c)'s per-gain comparison.

## 2. Battery control (applies to all three protocols)

Battery brightness is a live confound for every question above (`docs/46` section 5):
dim LEDs starve blob detection, over-bright LEDs correlate with ghost solves.

**Rule: every run starts and ends inside the same raw-byte band, stated and held constant across
runs being compared.**

- The alert threshold is raw byte **85** (`docs/46` section 3); never start a run below it.
- `docs/46`'s linear fit is validated only in the **~65-150** band (settled NiMH, not
  fresh-off-charger, not under load sag). **Recommended band: raw 100-150, settled NiMH** (rested
  a few minutes after charging).
- **Byte > 150 is chemistry-ambiguous and a known ghost-solve risk**: fresh alkaline reads ~208,
  fresh-off-charger NiMH ~204-206, and a fresh-alkaline (3.1 V) right hand hit a 97 %
  gravity-gate drop fraction versus 8 % on settled 2.5 V NiMH (`docs/46` section 5).
- Read the byte with `scripts/controller-battery-check.py` immediately before and after every
  window. **A window whose battery drifted outside the band in either direction is void**: log it
  as void, do not average it in.
- If left and right are on different chemistries or charge states, treat them as two independent
  experiments.

## 3. Invalidation rules (used by the session-report tooling)

Learned from the false starts in `docs/58`'s addendum:

1. **A window whose controllers were asleep is not a control.** A "drift" window offered as
   evidence had the controllers powered off throughout; the claim built on it was retracted.
   Verify both controllers are awake and HID-responding before the window, not from the LED.
2. **A window with the headset on the desk is not a control for anything worn.** Camera FOV,
   exposure regime and head micro-motion differ; a desk window bounds what the fixture and
   geometry can do, not the worn number.
3. **Zero counters mean "no data", never "a result".** `processSampleFast +0` at 75 cm looks
   identical, in every counter, to a dead pipeline. Do not report it as "0 % solve rate" until
   liveness is independently confirmed (rule 4).
4. **Verify controller liveness before AND after every window**: a controller can auto-sleep
   mid-window (one 272 s window was lost this way, caught by the wearer, not the instrumentation).
   Use `scripts/preflight.sh` (direct HID probe, bypasses Monado) or
   `scripts/controller-pair-check.py`. If the post-check shows the controller slept or dropped,
   the window is void; do not salvage the clean-looking part, because no log line brackets when
   it happened.
5. **Genuine zero vs dead pipeline:** return to a known-good distance (50 cm) and confirm samples
   resume immediately. If they do, the zero was genuine; if not, the whole window, including
   earlier "genuine zero" readings, is suspect and must be re-run.

## 4. Protocol (a): absolute scale

**Question:** does the reported distance scale correctly with real distance, or is there a
multiplicative scale error (as opposed to the expected fixed offset)?

**Design:** the fixed optical-centre offset becomes the *intercept* of a linear fit across
distances; the *slope* says whether scale is correct regardless of where zero sits.

**Varies:** true distance, 5+ points in the visible range (e.g. 30, 40, 50, 60, 70 cm).
**Held constant:** orientation, height, battery band (section 2, same pair throughout),
gain/exposure at the driver default (`WMR_CONTROLLER_CAM_GAIN` unset), lighting meeting the
`docs/56` setup criterion (<=3 spurious blobs/camera with no controller visible).

```
WMR_CONSTELLATION_CONTROLLERS=1 CONSTELLATION_TRACKER_LOG=info ./scripts/jack-in-wayland.sh 1 6dof
```

Capture the driver's `constellation sample #N` lines (throttled ~2/s, `wmr_controller_base.c`):

```
constellation sample #<N>: pos=(x, y, z) matched_blobs=<n> visible_leds=<n> reproj_err_px=<f>
```

`pos` is camera-relative at this call site; use `sqrt(x^2+y^2+z^2)` as the reported distance,
not the world-frame position (which carries the SLAM origin's drift as an unrelated additive
term, `docs/58`). **Record per distance:** at least 30 consecutive sample lines (~15 s), the mean
and standard deviation of distance, `matched_blobs` / `visible_leds` / `reproj_err_px`, and the
battery byte before and after; liveness-check (section 3) before and after.

**Decision rule:** fit reported = **slope** x true + **intercept** by least squares. **Slope in
[0.95, 1.05]: scale is correct** (within hand-eye placement error). **Slope outside
[0.90, 1.10]: a real scale error** worth chasing in the solver's metric assumptions (unit mismatch,
miscalibrated LED-constellation baseline); a slope error is multiplicative and no intercept
adjustment fixes it.

## 5. Protocol (b): visibility cliff mapping

**Question:** where exactly does the camera stop returning samples, and is it a detection-range
limit or an FOV/aiming artifact?

**Varies:** distance only, 5 cm steps from 50 to 100 cm (11 points). **Held constant:**
orientation and height, aiming (headset pointed at the fixture's controller position at every
step; confirm the controller sits centred in the expected FOV, via a second person or a mirror),
battery band, gain/exposure at default (run protocol (c) only after this baseline).

```
WMR_CONSTELLATION_CONTROLLERS=1 CONSTELLATION_TRACKER_LOG=trace ./scripts/jack-in-wayland.sh 1 6dof
```

At `trace` the per-camera line is visible (`t_constellation_tracker.cpp`):
`Starting fast processing for camera <ptr> with <N> blobs`; count non-zero `processSampleFast`
returns (`docs/58`) over a 20 s window per distance. **Record:** window length, success count,
blobs per camera, battery before/after, and a **50 cm bracketing check** immediately before and
after each new distance (rule 5).

**Decision rule:** the cliff is the **shortest step, moving outward from 50 cm, where the
non-zero-sample rate drops below 10 % of the 50 cm baseline AND the next 50 cm bracketing check
recovers to within 20 % of the original baseline.** If the bracket also fails, the zero is NOT
evidence of a range limit (pipeline stall, controller sleep, aim drift): discard and re-run the
step. Only a step that reads near zero and is bracketed by two healthy 50 cm checks counts as a
located edge.

## 6. Protocol (c): gain sweep scored on solve quality

**Question:** does raising `WMR_CONTROLLER_CAM_GAIN` past 100 buy usable range or only more
*wrong* poses? The first gain=255 run at 75 cm produced 87 poses off by up to 20 cm and one
physically impossible, so **pose count alone is the wrong metric**.

**Varies:** `WMR_CONTROLLER_CAM_GAIN` in {100, 150, 200, 255} at one fixture distance just past
the cliff edge from protocol (b). **Held constant:** that distance, orientation, height, battery
band (doubly important: gain and battery brightness are two routes to the same LED-saturation
failure), exposure at 6000 us (`WMR_CONTROLLER_CAM_EXPOSURE_US`, patch `0083`, not varied; a
combined exposure x gain sweep is out of scope).

```
WMR_CONSTELLATION_CONTROLLERS=1 WMR_CONTROLLER_CAM_GAIN=<100|150|200|255> \
  CONSTELLATION_TRACKER_LOG=info ./scripts/jack-in-wayland.sh 1 6dof
```

Confirm the override with the driver line `Controller-tracking exposure/gain OVERRIDE: 6000/<gain>`.

**Quality metrics, per gain level** (from the `constellation sample #N` fields):

- **`agree_frac`**: fraction of samples whose distance (as in protocol (a)) is within +-5 cm of
  the fixture's true distance. The primary signal; it is the metric that catches "poses that
  exist but are wrong".
- **`reproj_err_px`, mean and p90**: secondary only; a wrong-lobe solve can reproject as well as
  the true one (`docs/58`), but a spike alongside a drop in `agree_frac` separates "solver
  confused" from "confident but wrong".
- **`matched_blobs` / `visible_leds` ratio, mean**: a low ratio at high gain fits the
  blob-bloom/saturation mechanism (neighbouring LEDs merging, `docs/46`).
- **Distance sigma**: rising sigma with falling `agree_frac` means the extra poses are noise.

Record 30+ consecutive sample lines (or the most obtainable in 20 s), the metrics above, pose
count (reference only), and battery before/after.

**Decision rule:** a gain level is a net win only if it raises `agree_frac` above the default's
at the same distance (the default may score ~0 past the cliff; any level with `agree_frac` > 0
and tight sigma is then already an improvement). **A level that raises pose count without raising
`agree_frac` over the previous level is not an improvement.** The recommended live gain is the
**lowest level whose `agree_frac` is at or near its sweep maximum**, since extra brightness only
adds ghost-solve risk (`docs/46`).

## 7. Out of scope

- **Combined exposure x gain sweep:** a larger sweep, deferred.
- **The near-pure-yaw ghost class** (`docs/58`, "What is still open") is a correspondence
  problem, not range or scale: a controller at the right distance and gain can still get a
  180-degree-yaw-rotated pose. `agree_frac` checks distance, not orientation, so a clean result
  on all three protocols is no evidence that class is fixed.
