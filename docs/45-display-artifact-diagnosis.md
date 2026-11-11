# 45: Display-chain artifact diagnosis, the late color fill-in symptom

> **Status: protocol designed, never executed.** Nothing below has been run on the headset.
> The synthetic test patterns exist (`patches/hello_xr-player/0017`, `HELLO_XR_TEST_PATTERN`) but
> are not verified in-headset. Start at "The protocol" and work down in order; Step 0 costs
> nothing and should never be skipped.

## 1. The symptom

After the 2026-08-17 round-2 stack (`SLAM_CORRECTION_SPREAD_MS=120`, keepalive v2 fix, leak cap)
head rotation felt immediate and world anchoring very stable. With the gross lag and jitter gone,
the wearer reported something new and hard to characterize: once a frame has fully drawn and the
turn already feels perfect, a further update arrives that finishes filling in solid colors that
were not fully on or off yet, like a settling or re-adjustment layer. The candidate mechanisms
named were LCD pixel response/overdrive on the strobed panel, reprojection layering, and a
one-slot frame re-show.

This symptom sits at the resolution limit of subjective wear-testing. Earlier artifacts (CPU
spin, SLAM collapse, clock skew: `docs/39`, `docs/44`) were large enough to describe in words;
this one needs instrumentation finer than a human, and the "fixed" bar moves with it: do not
declare a number invisible that a camera can still see.

## 2. Hypothesis ranking

Ranked by how directly each explains a delayed *color* fill-in arriving after the geometry has
settled (not a delayed *position*).

### 2.1 Strobe crosstalk on the low-persistence backlight (leading)

The G2 panel is a strobed, low-persistence LCD: the backlight is off for most of each frame and
fires for a short window once pixels have (in theory) finished transitioning. Gray-to-gray (GtG)
transitions take a measurable fraction of a frame, dark-to-mid-gray being the slowest on most
cell types. If the strobe fires before a pixel's transition completes, the eye sees a color still
mid-transition; it finishes during the dark interval and has caught up by the next strobe, which
reads as "a further update that fills in the color". This is **strobe crosstalk**, well
characterized on strobed gaming monitors (ULMB, DyAc), electrically the closest analog:

- [Blur Busters, Advanced Strobe Crosstalk FAQ](https://blurbusters.com/faq/advanced-strobe-crosstalk-faq/):
  crosstalk occurs when GtG is incomplete between strobe flashes. **Discriminator: crosstalk is
  systematically worse at the top and bottom edges of the panel**, because most LCDs scan
  row-by-row and rows near the end of the scan have had the least time to settle.
- [Blur Busters, LCD Motion Artifacts: Overdrive](https://blurbusters.com/faq/lcd-overdrive-artifacts/)
  separates plain ghosting (asymmetric transitions trailing an edge) from inverse ghosting /
  coronas (overdrive overshoot, a bright trailing corona). The report is closer to incomplete
  transition than to overshoot; the sharp-edge card test (Step 2) tells them apart.

**The row-scan discriminator is the cheapest test here**: a fill-in artifact consistently
stronger near the top or bottom of the FOV than at the vertical center is strong evidence for
panel-electronics crosstalk and rules out the compositor and tracking layers, which have no
concept of a panel row.

### 2.2 Reprojection layering (secondary)

Monado's compositor can reproject a delivered frame against a newer predicted pose before
scanout; a corrected frame differing from one already latched could read as a "second layer".
Reprojection artifacts are classically *geometric* (warped edges, disocclusion tears), not
*photometric* (solid colors looking incompletely on/off), so it ranks below 2.1. Step 2 separates
the two.

### 2.3 One-slot frame re-show / pacing hiccup (secondary)

A missed compositor slot re-displaying the previous frame for one strobe would read as a delayed
update. `scripts/frame-pacing.sh` counts missed slots (`docs/32` notes it is blind to latency);
check it, but a re-shown frame reproduces the previous colors exactly rather than producing a
partially-lit intermediate, so it does not explain a color-specific symptom.

### 2.4 The documented G2 warm-up ghosting confound (control for, do not diagnose)

HP's support documentation, quoted in the [Road to VR review](https://roadtovr.com/hp-reverb-g2-review/),
says there may be minor image ghosting in the first few minutes from a cold start until the
lenses warm up. No prior measurement here controlled for it (every session started measuring
within minutes of power-on), so some or all of the artifact could be this effect fading. It is
Step 0.

## 3. The protocol

Ordered cheapest-and-most-diagnostic first; each step rules a hypothesis in or out before the next.

### Step 0: warm-up confound check (free, always first)

Reproduce the symptom on a **cold** panel (headset off at least 15-20 min) with the exact same
content, and again on the same panel after 3 minutes of continuous scanout. If the artifact is
visibly stronger cold and fades by minute 3, some or all of it is HP's documented warm-up
ghosting, and every later step needs a "warm panel" precondition noted in its results. Needs only
the headset and a stopwatch.

### Step 1: static full-field color toggle (zero head motion)

**Purpose: eliminate reprojection and tracking by construction.** With the headset completely
still (ideally on a stand), no tracking data changes, so reprojection has nothing to correct and
no prediction window exists. If the artifact still appears it cannot be caused by SLAM, dead
reckoning, the correction-spread mechanism or reprojection; what remains is the
panel/compositor/GPU pipeline (hypotheses 2.1 and 2.3).

Fill the full visible field with a single flat color toggling on a fixed cadence, independent of
loaded content:

- **A dark-to-mid-gray pair**: the slowest, most crosstalk-prone GtG transition, the one most
  likely to reproduce "colors not fully on or off".
- **A black-white pair** as the maximum-contrast control.
- Toggle **every 8 frames at 90 Hz** first (~89 ms per color, slow enough to watch and count),
  then every frame (~11 ms), the cadence most likely to reproduce the report.

### Step 2: world-locked sharp-edge card with slow-GtG fill

**Purpose: separate edge/geometry arrival from color-fill arrival.** Place a flat card locked to
a fixed world position with a hard edge (black border) and the same slow dark-to-mid-gray
interior fill as Step 1, worn, turning the head across it. If the edge settles immediately while
the interior fill catches up a beat later, geometry (reprojection/tracking) is on time and color
(panel electronics) is late, confirming 2.1 over 2.2 within a single test object.

### Step 3: head-locked frame-counter patch + high-speed phone camera

**Purpose: turn the subjective report into a frame count.** Render a small head-locked patch (a
fixed screen location, easy to keep framed) showing a monotonically increasing frame number next
to the Step 1 color fill, and film the panel through the lens at 240 fps (up to 960 fps on many
phones). Counting frames between the counter showing frame N and the fill reaching its settled
value gives frames of lag for the fill-in specifically, at ~4 ms per frame at 240 fps (~1 ms at
960). The method follows [Rosedale's slow-motion phone-camera latency
hack](https://medium.com/@philiprosedale/quick-hack-for-measuring-latency-238f8b7f5189) and the
photosensor approach of the [motion-to-photon latency paper in Behavior Research
Methods](https://link.springer.com/article/10.3758/s13428-022-01983-5). A photodiode plus
scope/microcontroller (microsecond-class, but hardware not currently available) is the last
resort if 240 fps is ambiguous.

SteamVR's Frame Timing graph and Meta's Performance HUD do not apply: this stack runs
xrizer-over-Monado, and Monado ships no visual latency HUD (only the timing markers beneath one,
see [Monado frame pacing](https://monado.pages.freedesktop.org/monado/frame-pacing.html)). The
homegrown equivalent is `docs/32` (`pose-lag.py`, `timing.csv`, `frame-pacing.sh`), which is
blind to photon output on the panel itself, the gap this symptom lives in.

**Implementation.** `patches/hello_xr-player/0017` provides the three modes via
`HELLO_XR_TEST_PATTERN` (toggle, card, counter). The player's push-constant structs were already
full, so the modes reuse dead slots (`fovTangents` becomes `tintColor` after the mode's early
return; the counter packs into `mode.x`'s high bits). Unset, rendering is byte-identical to before.

## 4. What each outcome would mean

- **Step 1 alone reproduces the artifact** (static panel, no tracking data in play): the cause is
  in the panel/compositor/GPU display chain. Reprojection, prediction and
  `SLAM_CORRECTION_SPREAD_MS` are structurally exonerated for this symptom, and the question
  passes to panel electronics: strobe timing, GtG response, or compositor scanout timing relative
  to the strobe window (`docs/16-lab-vblank.md` is the closest existing instrument).
- **Step 1 does not reproduce it but Step 2 does** (needs motion / world-locked content): the
  mechanism is coupled to motion, most likely reprojection (2.2) or a pacing interaction under
  real angular velocity. `pose-lag.py`, `timing.csv` and `frame-pacing.sh` then correlate a
  compositor-side timing event with the moment the artifact is seen.
- **Neither reproduces, or Step 0 explains most of it**: treat the report as HP's documented
  warm-up ghosting (2.4) and do not chase further hardware instrumentation.
