# 45 — Display-chain artifact diagnosis: the late color fill-in symptom (T206)

> ## STATUS AS OF 2026-08-17 (T206) — protocol designed, not run yet
>
> This document is the research pass the user asked for after naming a symptom he could no
> longer characterize by feel alone: a research agent surveyed how the display/HMD industry
> diagnoses this exact artifact class, and this file turns that survey into an ordered,
> buildable test protocol for this rig specifically. **Nothing below has been executed.**
> The next session should start at "The protocol" and work down in order — Step 0 costs
> nothing and should never be skipped.

## 1. The symptom, verbatim, and why it is a milestone

Session T206 (`docs/pruebas.jsonl`) was a triple-experiment wear session on the round-2
stack — `SLAM_CORRECTION_SPREAD_MS=120`, the keepalive v2 fix, and the leak cap all
together. The world-anchor result was the best this project has ever measured by feel:
*"bastante bien che. Solido... el fondo esta clavado mas bien. Parece muy estable, casi por
pixel."* Head rotation itself now "se refleja inmediato" — immediate, no perceptible lag.

That is the headline, but it is not why this document exists. With the gross lag and the
gross jitter both gone, the wearer reported something new, and said so in almost these
exact words:

> *"me cuesta probarlo a ese nivel ya, hay que confiar un poco en los numeros... cuando ya
> se dibujo todo, cuando lo senti ya perfecto al giro, ahi llega un update que termina de
> rellenar los colores solidos que no estaban del todo prendidos/apagados. Como una capa de
> reajuste."*

In English: once the frame has fully drawn and the turn already feels perfect, a further
update arrives that finishes filling in solid colors that weren't fully on or off yet — like
a settling/re-adjustment layer. He explicitly named candidate mechanisms himself — LCD
pixel-response/overdrive on the strobed panel, reprojection layering, a one-slot frame
re-show — and asked for two things: a synthetic + human test design (moving-square tests,
"panel rewrite time"), and a research pass on how this artifact class is diagnosed
professionally. This document is that pass plus the protocol it produced.

**Why this is a milestone rather than just another bug report.** Every prior artifact this
project chased — the CPU-runaway spin, the SLAM pose-rate collapse, the camera clock-domain
skew (`docs/39-slam-collapse-root-cause.md`, `docs/44-clock-domain-skew.md`) — was large
enough to describe unambiguously in words: freezes, jumps of meters, a flat one-second
delay. This one is not. The wearer's own framing — *"hay que confiar un poco en los
numeros"* — is him recognizing, correctly, that he has reached the resolution limit of
subjective wear-testing on this rig. Everything coarser than this has been found and mostly
fixed; what's left needs instrumentation finer than a human nervous system, which is a
genuinely different kind of problem from every prior chapter in this project. It also means
the bar for what counts as "fixed" has moved: `docs/06`'s original cutoff was "on par with
Windows or better," measured by feel. This symptom is downstream of that bar, not a
regression from it — "es importante mantener la barra," in the user's own words closing the
session, applies here as *don't declare a number "invisible" that a photon-counting
instrument can still see and a competent VR user occasionally can too.*

## 2. Hypothesis ranking

Ranked by how directly each one explains the specific shape of the report — a delayed
*color* fill-in, not a delayed *position* update, arriving after the geometry has already
settled.

### 2.1 Strobe crosstalk on the low-persistence backlight (leading hypothesis)

The G2's panel is a strobed, low-persistence LCD: for most of each frame period the
backlight is off, and it fires only for a short window once the pixels have (in theory)
finished transitioning to their new color. LCD pixels do not switch instantly — gray-to-gray
(GtG) transitions take a measurable fraction of a frame, and darker-to-mid-gray transitions
in particular are the slowest case for most LCD cell types. If the backlight strobe fires
*before* a given pixel's transition has actually completed, the eye is shown a photograph of
a color that is still mid-transition — not fully "on," not fully "off," exactly the wearer's
own words. The transition then keeps completing during the dark (backlight-off) portion of
that frame, invisibly, and by the *next* strobe it has caught up — which reads, subjectively,
as "a further update that finishes filling in the color" one frame after the geometry
already looked settled. This mechanism has a name in the display industry — **strobe
crosstalk** — and it is extensively characterized for competitive-gaming strobed monitors
(ULMB, DyAc, BenQ's blur-reduction modes), which are electrically the closest analog to a
WMR headset's own strobed backlight:

- [Blur Busters — Strobe Crosstalk: Why ULMB Is Limited To 120 Hz or 144 Hz](https://blurbusters.com/strobe-crosstalk-why-ulmb-works-only-at-120hz-or-144hz/):
  crosstalk appears as *"a faint super-sharp double-image chasing behind images,"* and is
  worse when GtG has not finished by the time of the flash.
- [Blur Busters — Advanced Strobe Crosstalk FAQ](https://blurbusters.com/faq/advanced-strobe-crosstalk-faq/):
  states the mechanism plainly — *"strobe crosstalk occurs when pixel transitions (GtG) are
  incomplete between strobe flashes; for zero strobe crosstalk, GtG needs to be completed in
  the black interval before the screen is flashed again"* — and gives the discriminator this
  project can actually test for: **crosstalk is systematically worse at the top and bottom
  edges of the panel**, because most LCD panels scan/refresh row-by-row from top to bottom,
  so rows nearer the end of the scan have had the least time to settle before the strobe
  fires, regardless of anything the compositor or the tracker did.
- [Blur Busters — LCD Motion Artifacts 101](https://blurbusters.com/faq/lcd-motion-artifacts/)
  and its companion [LCD Motion Artifacts: Overdrive](https://blurbusters.com/faq/lcd-overdrive-artifacts/)
  page separate this from two neighboring, easily-confused artifacts: plain **ghosting**
  (asymmetric-speed transitions trailing a moving edge) and **inverse ghosting / coronas**
  (response-time-compensation overdrive overshooting past the target color and bouncing
  back — a bright trailing corona rather than a dim lagging one). The wearer's report —
  colors that were *"not fully on or off"* catching up a frame later — is closer to plain
  incomplete-transition crosstalk than to overdrive overshoot, but the protocol below (2.4,
  the sharp-edge-card test) is designed to tell these apart rather than assume it.

**The row-scan discriminator is the cheapest test in this whole document**: if the fill-in
artifact is consistently stronger near the top or bottom of the FOV than in the vertical
center, that is strong, specific evidence for panel-electronics strobe crosstalk and *rules
out* anything at the compositor or tracking layer, which have no concept of "row of the
panel." Step 1 of the protocol is built around catching this signature directly.

### 2.2 Reprojection layering (secondary — plausible but should look different)

Monado's compositor can reproject a delivered frame against a newer predicted head pose
before scanout (the same mechanism as SteamVR's own reprojection/ASW-adjacent path — see
§3.4). If a corrected/reprojected frame differs from what was already latched into a
scanout buffer, a viewer could in principle perceive a "second layer" arriving after the
first. This is a real, live mechanism in this stack and should not be dismissed, but it
predicts a different symptom shape than what was reported: reprojection artifacts are
classically *geometric* (edges warp, disocclusion tears at depth boundaries) rather than
*photometric* (solid colors specifically looking incompletely on/off). The wearer's
description was unambiguously about color fill, not geometry — which is why this ranks
below the strobe-crosstalk hypothesis, not why it is dismissed. Step 2 of the protocol
(the sharp-edge card) is designed to separate this class of artifact from 2.1 directly, by
giving the eye a hard edge to judge geometric arrival against, independent of the fill
color.

### 2.3 One-slot frame re-show / pacing hiccup (secondary)

A missed compositor slot that re-displays the previous frame for one extra strobe, then
catches up, would also read subjectively as "a delayed update." This project already has an
instrument for exactly this question — `scripts/frame-pacing.sh` — and `docs/32`'s own
"blind to" table is explicit that it counts missed slots but is blind to latency; it is easy
to check and should be checked, but it does not explain a *color-specific* symptom (a
re-shown frame reproduces the previous frame's colors exactly, it does not produce a
partially-lit intermediate color), so it ranks below both hypotheses above.

### 2.4 The documented G2 warm-up ghosting confound (must be controlled for, not diagnosed)

Separately from any of the above, HP's own support documentation for the Reverb G2 — quoted
in the [Road to VR review](https://roadtovr.com/hp-reverb-g2-review/) — states that *"due to
the advanced design of the headset there may be some minor image ghosting in the first few
minutes when starting the device while cold until the headset lenses have the opportunity
to warm up."* This is a real, HP-acknowledged, temperature-dependent effect, and it is a
confound this project has never controlled for on any prior tracking or display measurement
— every session so far has started measuring within minutes of power-on. If T206's session
happened on a cold panel, some or all of the reported artifact could be this effect fading
out over the session rather than a fixed property of the pipeline. It costs nothing to rule
out and must be Step 0, before any of the real instrumentation below.

## 3. Methods catalog — how this class of artifact is diagnosed professionally

Surveyed from the VR/display industry and academic HCI literature, roughly in order of
how directly applicable each is to a from-scratch Linux rig with no lab hardware budget.

**Photodiode + oscilloscope (the industry ground truth).** The [Springer / Behavior
Research Methods paper on measuring motion-to-photon latency for sensorimotor VR
experiments](https://link.springer.com/article/10.3758/s13428-022-01983-5) (the same
methodology summarized on the [vrarwiki motion-to-photon latency
page](https://vrarwiki.com/wiki/Motion-to-photon_latency)) is the closest thing to a
citable academic standard: a photosensor pressed against the panel plus a microcontroller
or scope timestamps the exact moment light output changes, decoupled from any software's
self-reported timing (which the paper explicitly flags as unreliable — the measurement
process itself perturbs what it's measuring if done in software). This gives
microsecond-class resolution and can in principle resolve a strobe's actual rise/fall
envelope, not just "did a frame arrive." It needs hardware this project doesn't have
(photodiode, scope or fast ADC) and is listed here as the last-resort instrument, not
step 1.

**Purpose-built robotic test rigs.** [OptoFidelity's BUDDY](https://www.optofidelity.com/en/products/buddy)
class of product (see also its [motion-to-photon latency
explainer](https://www.optofidelity.com/insights/blogs/measuring-head-mounted-displays-hmd-motion-to-photon-mtp-latency))
is what headset manufacturers use on production lines: a 6DoF robot arm wears the headset,
a camera watches the panel at display refresh cadence, and the robot's own encoder trace
is compared against what the panel actually showed. This is the professional-grade version
of exactly the question T206 is asking, and it is included here purely as calibration for
scale — this project has no robot arm, and does not need one for a first diagnostic pass.

**Phone-camera-through-lens at 240-960 fps.** The practical, zero-cost version of the
photodiode method, and the one this project can actually run tonight. Philip Rosedale
(Second Life, High Fidelity) [documented the technique directly](https://medium.com/@philiprosedale/quick-hack-for-measuring-latency-238f8b7f5189):
hold a slow-motion phone camera so it frames both the physical motion cue and the display
response, then count frames between the two. The same class of camera-through-the-lens
capture is what the Springer paper above validates academically, and modern phone slow-mo
(240 fps common, 960 fp on many recent phones) gives roughly **4 ms per-frame resolution at
240 fps**, down to ~1 ms at 960 fps — coarse next to a photodiode, but far finer than
anything a human eye timing a "does it feel right" wear test can resolve, which is exactly
the gap the wearer asked this project to close. `docs/32-measurement-toolkit.md` already
flagged "a high-speed camera (a phone's 240 fps slow-mo is enough)" as a missing instrument
for exactly this class of question, before T206 gave it a concrete symptom to point at.
[Sensics' open-source Latency-Test](https://github.com/sensics/Latency-Test) is a related,
slightly heavier software+hardware kit built for the same purpose (any HMD, PC-side) and is
worth knowing about even though this project's phone-camera path is cheaper to stand up
first.

**Pursuit-camera photography and TestUFO patterns, for distinguishing artifact *classes*,
not just timing them.** [Blur Busters' pursuit-camera
technique](https://blurbusters.com/motion-tests/pursuit-camera/), built around the
[testufo.com/ghosting](https://testufo.com/ghosting) moving-UFO test pattern, is the
standard the monitor-review industry (including [RTings, who adopted the exact
technique](https://blurbusters.com/rtings-adopts-our-blur-test/)) uses to visually separate
**motion blur** (symmetric, sample-and-hold, an eye-tracking artifact — not applicable to a
strobed low-persistence panel), **ghosting** (asymmetric-speed GtG trailing an edge), and
**inverse ghosting / coronas** (RTC/overdrive overshoot, a bright rather than dim trailing
artifact). This is the direct academic ancestor of the "moving-square tests" the wearer
asked for by name. Pointed a phone camera at the panel while a known test pattern moves
across it, this gives a *photograph* of exactly which artifact class is present — a strictly
stronger result than a timing number alone, because it tells you *what* is happening, not
just *when*.

**Prior art that does NOT transfer to this rig, and why, so it isn't chased.** [SteamVR's
Frame Timing graph](https://developer.valvesoftware.com/wiki/SteamVR/Frame_Timing) and
[Meta's Performance HUD / Latency Timing
HUD](https://developers.meta.com/horizon/documentation/native/pc/dg-hud/) are the two
best-known "just turn on a HUD" answers to a VR-latency question, and both are worth
knowing about specifically to rule them out: this stack runs xrizer-over-Monado, not
SteamVR's own compositor and not the Oculus/Meta runtime, so neither overlay exists here and
neither can be enabled. [Monado's own frame-pacing
documentation](https://monado.pages.freedesktop.org/monado/frame-pacing.html) is the
correct in-tree reference for this runtime's actual timing model (`wake_up` /
`xrBeginFrame` / `xrEndFrame` / GPU-done markers, aligned to `VK_GOOGLE_display_timing`'s
naming) — but Monado ships no visual latency HUD at all, only the timing markers
underneath one. This project's own `docs/32-measurement-toolkit.md` (`pose-lag.py`,
`timing.csv` col2−col1, `frame-pacing.sh`) is the homegrown equivalent of that missing HUD,
already built and already proven on this exact rig (it is what found the 0.8 s Basalt
input-queue backlog behind `patches/basalt/0002`, and the +578 ms camera clock-domain bias
behind `patches/monado/0053-0055`, `docs/44`). It remains blind, by its own documented
design, to exactly the gap this symptom lives in — photon output on the panel itself — which
is the entire reason this document exists instead of another `pose-lag.py` run.

## 4. The protocol

Ordered cheapest-and-most-diagnostic first. Each step should rule in or out a specific
hypothesis from §2 before spending the effort on the next one; don't skip ahead.

### Step 0 — warm-up confound check (free, do this first, always)

Before touching anything else: reproduce the symptom on a **cold** panel (headset off for
at least 15-20 min, per §2.4) with the exact same content, and again on the **same panel
after 3 minutes of continuous scanout**. If the fill-in artifact is visibly stronger cold and
fades by the 3-minute mark, some or all of T206's report is HP's own documented warm-up
ghosting, not a pipeline bug — and every subsequent step needs a "warm panel" precondition
noted in its own results, the same way `docs/23`'s Proton titles now carry a "don't judge
pacing in the first minute" caveat for DXVK shader warm-up. This step needs nothing beyond
the headset and a stopwatch.

### Step 1 — static full-field color-toggle mode in the hello_xr player (zero head motion)

**Purpose: eliminate reprojection and tracking as candidate causes by construction, not by
argument.** With the headset completely still — ideally resting on a stand, not worn — no
tracking data changes, no reprojection correction has anything to correct against, and no
prediction window exists. If the fill-in artifact still appears under this condition, it
**cannot** be caused by SLAM, dead reckoning, the correction-spread mechanism, or
reprojection layering (§2.2) — those mechanisms are structurally incapable of producing an
artifact when the pose is constant frame to frame. What remains under this condition is the
panel/compositor/GPU pipeline itself: exactly the strobe-crosstalk hypothesis (§2.1) and the
one-slot re-show hypothesis (§2.3).

Add a test mode to the 360/VR180 player (`patches/hello_xr-player/`) that fills the full
visible field with a single flat color and toggles it on a fixed cadence, independent of any
loaded video or photo content:

- **A dark-to-mid-gray pair** — this is the slowest, most crosstalk-prone GtG transition on
  most LCD cell types (per Blur Busters' overdrive-artifacts page, §3 above), and the
  transition most likely to visibly reproduce *"colors that were not fully on or off"* if
  the strobe-crosstalk hypothesis is correct.
- **A black-white pair** as the maximum-contrast control — this is the easiest transition to
  judge by eye and the standard baseline every ghosting test in §3 uses.
- Toggle **every 8 frames at 90 Hz** first (~89 ms per color, slow enough to watch by eye and
  count), then repeat at the fastest cadence the panel can show (every frame, ~11 ms) once
  the slow version has been characterized — the fast cadence is what should visually
  reproduce T206's report if strobe crosstalk at normal content cadence is the mechanism.

### Step 2 — world-locked sharp-edge card with slow-GtG fill

**Purpose: separate edge/geometry arrival from color-fill arrival — the wearer's own
distinction**, restated as a test. Place a single flat card in the world, locked to a fixed
world position (not head-locked), with a hard geometric edge (e.g., a black border) and an
interior fill using the same slow dark-to-mid-gray transition as Step 1. This time the
headset *is* worn and the wearer *does* turn their head across the card. If the border/edge
of the card visually settles into place immediately on a turn while the interior fill
visibly continues catching up a beat later, that is a clean, directly-observed replication of
the exact phenomenon reported in T206 — geometry (which reprojection and tracking govern)
arriving on time, color (which panel electronics govern) arriving late — and confirms
§2.1 over §2.2 by direct comparison within a single test object rather than by inference
across two separate tests.

### Step 3 — head-locked frame-counter color patch + 240 fps phone camera

**Purpose: turn the subjective "a further update arrives" report into an objective frame
count.** Render a small, head-locked patch (so it stays in a fixed, known screen location
regardless of head motion, making it easy to keep framed in a handheld camera shot) that
displays a monotonically-incrementing frame number as a rendered digit or bar alongside the
same dark-to-mid-gray color-fill test from Step 1. Film the panel through the lens at
240 fps (or the phone's fastest available slow-mo mode — up to 960 fps on many recent
phones) per the Rosedale/Springer method in §3. Counting frames between the counter showing
frame N and the fill color actually reaching its full, settled value gives a direct
**frames-of-lag** number for the color-fill artifact specifically, with per-frame
resolution of roughly 4 ms at 240 fps (finer at 960 fps) — the first objective number this
symptom will have had, versus the wearer's honest but resolution-limited *"me cuesta
probarlo a ese nivel ya."**

**Photodiode/scope only as a last resort.** If Step 3's phone-camera number is ambiguous or
the artifact turns out to be faster than 240 fps can resolve cleanly, that is when to build
or borrow the photodiode + scope/microcontroller rig from the Springer paper's method (§3)
for microsecond-class numbers — not before, since it requires hardware this project doesn't
currently have and Step 3 is very likely to already answer the question this session is
actually asking.

**Implementation note.** The player's existing push-constant slots are informative here:
`patches/hello_xr-player/0002` through `0010` already fill every field in both push-constant
structs — `mode[4]` (x: projection type, with the eye index already packed into spare bits
per `0010`; y: progress fraction; z: bar alpha; w: quit-hold progress) and `panoFov` (x/y:
FOV half-angles; z: zoom; w: brightness). None of the four slots in either struct is free.
A new test-pattern mode needs either a genuinely new push-constant field or another
spare-bit trick in `mode.x` following `0010`'s own precedent (packing the eye index into bit
4 of an existing int) — that decision belongs to whichever patch implements Steps 1-3, not
to this document. A build task for this is already in flight in parallel with this write-up.

## 5. What each outcome would mean

- **If Step 1 alone reproduces the artifact** (static panel, zero head motion, zero
  tracking data in play): the cause lives in the panel/compositor/GPU display chain, full
  stop. Reprojection, prediction, `SLAM_CORRECTION_SPREAD_MS`, and every tracking-layer
  mechanism this project has spent T192-T206 tuning are structurally exonerated for this
  specific symptom. This would end the software/tracking hunt for this artifact and hand
  the question to panel electronics — strobe timing, GtG response curves, or the
  compositor's own scanout timing relative to the strobe window (`docs/16-lab-vblank.md`'s
  vblank/pixel-clock work is the closest existing instrument for that layer, though it was
  built for the 90Hz bring-up, not this).
- **If Step 1 does NOT reproduce it, but Step 2 does** (needs a moving head / world-locked
  content to appear): the mechanism is coupled to motion after all — most likely
  reprojection (§2.2) or a pacing interaction that only manifests under real angular
  velocity. That result hands the question back to this project's own toolkit: `docs/32`'s
  `pose-lag.py`, `timing.csv`, and `frame-pacing.sh` are exactly the instruments for
  correlating a compositor-side timing event against the moment the artifact is seen, the
  same way they already found the 0.8 s Basalt queue backlog and the +578 ms clock bias.
  This would turn the question from "which physical layer" into "which stage of the
  pipeline already being measured," which is a much cheaper investigation than Step 1's
  outcome.
- **If neither reproduces cleanly, or Step 0 explains most of it**: treat the T206 report as
  substantially or entirely the documented HP warm-up-ghosting effect (§2.4), note that in
  `docs/pruebas.jsonl`, and don't chase further hardware instrumentation for a symptom that
  turned out to already be a known, acknowledged, temperature-transient property of the
  panel rather than a bug in this project's own pipeline.
