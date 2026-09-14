# Controller LED pulse train, and where the visibility cliff actually is (2026-09-13)

Session result. Four measurements, three of which contradict something this project believed.

Setup, identical across both arms: headset **stationary** on the desk facing forward, `ctrl` mode
(`WMR_SLAM=0 WMR_CAMERAS=1`, constellation on), so the tracking origin is the head and a sample's
distance from origin *is* its hand-to-camera range. Operator holds the **right** controller only
(left set aside), at tape-marked 50 / 75 / 100 cm, 20 s per window, wrist orientation held as
constant as a person can. Right-controller battery read **raw 83 in both arms** — the same cell
state, so nothing below is a battery artifact.

Instrument: `WMR_CONSTELLATION_RAW_SAMPLES_LOG` (patch 0109), one line per sample at the very top
of `constellation_sample_store`, **before every gate and guard**. This is deliberately a different
quantity from `WMR_CONTROLLER_HEADING_CSV` (0107), which sits after the gravity gate and therefore
counts what survives. This one counts what the cameras produced.

> # ⚠ RETRACTION — read this before anything below
>
> **The cliff table in §1 does not measure distance, and §4's explanations of it are all void.**
>
> §1 was measured in increasing distance order — 50, 75, then 100 cm — with the zero at the end,
> and no control window was run back at a short distance afterwards. A later session ran that
> missing control (patch 0111, blob telemetry), and the result kills the reading:
>
> | window, all at gain 100, operator stationary | constellation samples |
> |---|---|
> | 75 cm | **380** |
> | 100 cm | 0 |
> | **75 cm again** | **0** |
> | **75 cm, after a full Monado restart** | **0** |
>
> The same distance that produced 380 produced zero fifteen minutes later, twice, including once
> from a cold start. **The failure varies with time, not with distance.** Everything §1 attributes
> to range is therefore confounded, and the "wall between 77 cm and 1 m" is not established.
>
> **What the blob telemetry shows instead, and this part is solid:** detection is healthy in every
> window, including every zero one. 4-15 blobs per frame, **p50 blob size ~20-22 px** (not the
> sub-pixel emitters §4 hypothesised — that estimate was wrong by a factor of twenty, because the
> fixed-focus fisheye cameras spread each LED over tens of pixels), brightness ~0.4-0.5, and the
> same 25% zero-blob frame share at 75 cm and at 1 m. At 1 m the cameras saw **more** blobs, the
> same size, **brighter** than at 75 cm — and solved nothing.
>
> **The failure is entirely in blob→device ownership.** The tracker's own telemetry says so:
>
> ```
> blob ownership: device 0 holds 0 of 15 blobs this frame
>                 (BELOW the 4-blob floor tryDeviceBlobRecovery needs)
> ```
>
> Zero of fifteen, every sampled frame. And in this session **only one controller was registered**
> — the left one's cells were flat — so this is not T225's two-hands-competing-for-a-shared-pool
> mechanism. A single device, with up to 15 healthy blobs in front of it and nobody to compete
> with, acquires none of them. Note also the deadlock in that message: recovery needs 4 owned
> blobs, and a device at 0 can never reach 4.
>
> **What survives from below:** §2 (patch 0108 destroys tracking, keep it at 0), §2b (the command
> is a per-controller servo we ran open-loop), §3 (absolute scale is sound — that was measured
> against a tape within a single window and does not depend on the cliff reading), §4's *factory
> LED geometry* (two concentric shells, 18 outward + 14 inward, dumped from the device) and §4's
> *rotational asymmetry result* (no rotation self-maps, 180° is among the worst). Those are
> measurements or device data. §4's three successive *explanations* of the wall — neighbour
> merging, sub-pixel emitters, and the brightness reversal built on them — are all void, since
> there is no established distance effect left for them to explain.
>
> **Method lesson, the third time tonight:** the controller's wrist orientation swings the sample
> rate by ~10× (§5), which is far larger than any effect this protocol was trying to resolve, and
> a hand-held protocol cannot hold it fixed. docs/59's string-and-knots fixture — designed in
> August, never built — exists precisely to remove this. **Do not run another distance sweep by
> hand.** Nothing distance-related here can be trusted until orientation is mechanically fixed.

## 1. The numbers

| | 50 cm | 75 cm | 100 cm |
|---|---|---|---|
| **control** (no LED command, historical behaviour) | **610** (30.5/s) | **634** (31.7/s) | **0**, repeat **1** |
| **LED intensity 200** | **0** | **0**, repeat **0** | **1** |
| measured distance, control arm | p50 **0.490 m** | p50 **0.767 m** | — |

Both 100 cm arms produced one lone sample each, reading `dist=0.122` and `dist=0.153` against a
1 m tape. Those are failed solves reporting a number, not weak detections.

## 2. Lab patch 0108 (LED pulse train) must stay OFF — it destroys constellation tracking

In the whole 4-minute intensity-200 session, across three measurement windows at three distances,
**one** raw sample arrived. The control arm produced 610, 634, and 7284 (a 90 s free hunt). The
cameras were healthy throughout — `clockskew` lines flowing, `WMR camera started` logged, both
controllers registered with the tracker.

The wearer independently reported the rings looked **brighter** to the eye in this arm, and the
command is confirmed present in the live service environment (`WMR_CONTROLLER_LED_INTENSITY=200`,
`WMR_CONTROLLER_LED_HZ=15`). So the command is reaching the device and doing something real. What
it is not doing is leaving the LEDs visible to the tracker.

**The mechanism this points at** (consistent with everything measured, not independently proven):
Windows syncs the pulse train to camera exposure through the packet's 55-bit `TS` field, which is
the entire point of the timesync half of the command. 0108 resends a **constant** `ts=0`, so the
train free-runs. The tracking cameras expose in short windows; a free-running train is simply not
guaranteed to be lit during them. A higher duty cycle reads as "brighter" to a human eye while
being worth nothing to a 
sensor that only looks for a few hundred microseconds at a time.

This is the exact failure the 0108 commit message called out in advance as the unvalidated half of
the change, and the reason it shipped defaulting to 0. That default is what kept the rig working;
treat it as load-bearing, not as a formality.

**So the honest verdict is not "LED intensity does not help".** It is **"the LED command without
exposure timesync is worse than sending nothing"**. The hypothesis that Windows' brighter rings
help tracking is untested either way — testing it requires plumbing `wmr_camera.c`'s exposure
timestamps into the packet, which is a much larger change than 0108 was.

## 2b. The operator's asymmetry observation names the missing half exactly

Wearer, same session, comparing the two OSes directly:

> *"la diferencia es que en Windows un solo joy queda más luminoso, el otro no. En Linux ambos
> quedan más brillosos."*

That is the whole diagnosis in one sentence, and it lines up with a measurement this repo already
had but had not connected:

- **T230 photometry**: on Windows the left ring photographs at ~2.45× the blob area and ~1.9× the
  flux of the right; on Linux the two are identical and both dim.
- **docs/re-windows/04 §3**, extracting all 10,503 pulse-train commands from the capture: report
  `0x08` commands ~1.3-1.4× the on-time of `0x10` (mean 681,751 vs 496,987), and the difference is
  driven by the `count` field, not the period.
- **thaytan's branch**, since `1d67d4d` (Beyley Cardellio, 2025-05-17): a closed loop nudges the
  intensity field from the tracker's own measured blob brightness — `−3` above 70, `+10` below 30
  or under >20 m/s².

So Windows is not *setting* a brightness. It is **servoing one, per controller, with measured blob
brightness as the feedback signal**. The two rings differ because they converge to different
operating points — different distance, angle, occlusion, LED efficiency, cell voltage. The
asymmetry is the loop working, not a fault, and the older reading of it as "one controller is
brighter than the other, so it's the hardware" was backwards.

0108 sends a fixed 200 to both, open-loop. Both rings therefore come out identical and bright,
which is exactly what the operator reports and exactly what an open-loop actuator does.

This makes the gap sharper than §2 alone stated. The LED command has **two** halves this stack does
not have: the exposure timesync (`TS`), and the brightness servo (`count`, driven by blob
photometry). 0108 supplies the actuator and neither controller. That is why turning it on is worse
than leaving it off — an actuator with no loop around it and no clock to align to is a fixed
disturbance injected into a system that was previously just quiet.

Both halves already exist in thaytan's branch and neither is upstream. That branch, not this patch,
is the thing to port if this line is ever picked up again.

## 3. Absolute scale is fine — retire that suspect

`docs/125` lists absolute scale as never validated, on the strength of one hand reading 0.556 m
against a 0.75 m tape. Measured here on the control arm, tight distributions both times:

- 50 cm tape → p50 **0.490 m** (min 0.480, max 0.511) — **2% low**
- 75 cm tape → p50 **0.767 m** (min 0.741, max 0.792) — **2% high**

Two percent, in opposite directions, with spreads of ~3 cm. The solve's metric scale is sound.
Whatever produced the old 0.556 m reading, it was not a scale error — and since scale holds at both
distances, it was not a uniform scale factor either.

## 4. The cliff is real, it is a WALL, and it is not where docs/125 puts it

`docs/125` says 75 cm yields zero samples. **That is wrong for raw samples**: 75 cm yields 634 in
20 s, statistically indistinguishable from 50 cm's 610. The cliff sits between **77 cm** (the
largest distance actually measured, p50 0.767) and **1 m**.

More important than the location is the *shape*. 31.7/s → 0 with nothing in between. An optical
brightness limit degrades: fewer blobs, noisier poses, scale starting to lie. None of that happened
— the 75 cm window was as clean and as well-scaled as the 50 cm one, and then there was nothing.

**CORRECTED twice in the same session, and the second correction is from real data.** This
section first explained the wall as neighbouring LEDs merging into one blob, computed from a
planar ring of 32 evenly-spaced emitters. Lab patch **0110** then dumped the actual factory
geometry off the device. The measured numbers in §1 are unaffected; the explanation built on top
of them was wrong twice and is now, at least, grounded.

### The real emitter geometry (patch 0110, right controller, 2026-09-13)

Not a ring. **Two concentric shells on the two faces of a shallow cone:**

| shell | count | radius | z extent | mean normal z |
|---|---|---|---|---|
| outward-facing | **18** | 51.4–58.7 mm | −9.4 … +6.8 mm | −0.33 |
| inward-facing | **14** | 44.4–50.7 mm | −8.5 … +6.3 mm | +0.35 |

A product photograph shows only the outer 18; the other 14 sit on the inside of the dish and face
inward. The cone is shallow — z spans under 2 cm against a ~12 cm diameter.

Angular gaps are irregular within each shell: outward 16.5°–25.9° (mean 20.0°), inward 21.0°–30.4°
(mean 25.7°). **Nearest-neighbour distance in 3D: min 12.4 mm, median 14.6 mm, max 20.4 mm.**

The earlier assumption of an 11.66 mm even chord was structurally wrong but numerically close —
about 25% low against the real median, i.e. conservative rather than fanciful.

### Why neighbour-merging is the weaker explanation

At `fx = 270.8486`, the 12.4 mm minimum neighbour separation projects to **6.7 px at 50 cm,
4.5 px at 75 cm, 3.4 px at 1 m**. Three and a half pixels apart is tight but generally resolvable,
and nothing about it changes sharply between 75 cm and 1 m.

An individual emitter aperture (~3 mm) projects to **1.63 / 1.08 / 0.81 px** at the same three
distances. The wall falls exactly where each LED drops **below one pixel**. A sub-pixel point
source failing to register as a blob at all is a much better fit to a hard cutoff than two
resolvable neighbours suddenly confusing each other.

This is a hypothesis, not a measurement — the 3 mm aperture is estimated from a photograph, and it
is now the only estimated quantity left in the argument.

### This reopens the LED-brightness question — §2 did not close it

The first version of this section concluded "more brightness makes it worse, blooming merges blobs
sooner". Under the corrected model that is backwards. **A brighter point source blooms across more
pixels, which is exactly what a sub-pixel emitter needs in order to be detected at all.**
Brightness is a live lever on this wall.

So §2 must not be read as "LED intensity does not help at range". §2 measured that an
**unsynchronised** LED command destroys tracking at *every* distance, including 50 cm where the
control arm was healthy. The experiment never reached the question of intensity versus range,
because the timesync defect broke it first. **The brightness hypothesis is untested, not refuted.**

### What the geometry says about docs/125's yaw ghost — the premise is not supported

docs/125 founds the yaw-flip ghost on the ring being "near-symmetric under that half-turn", which
is what would let correspondence return a wrong-yaw pose fitting as well as the true one. Tested
directly against the dumped geometry — rotate the whole pattern about the ring axis, then measure
how far each LED lands from the nearest original LED:

| rotation | mean displacement |
|---|---|
| 100° | 7.1 mm |
| 160° | 7.4 mm |
| **180°** | **8.5 mm** |
| 260° | 7.1 mm |
| 340° | 9.2 mm |

**No rotation maps the pattern onto itself, and 180° is among the worst, not the best.** 100° and
260° are closer to a self-mapping than the half-turn is. The pattern is deliberately irregular, as
a constellation designed for unique correspondence should be.

**But the margin is thin, and that is the real finding.** 8.5 mm is 58% of the 14.6 mm median
spacing, and in pixels the yaw-flip discriminant is only **4.6 px at 50 cm and 2.3 px at 1 m**.
The tracker also never sees all 32 — only the subset whose normals face the camera — and a subset
of an irregular pattern is far more ambiguous than the whole.

So the correction is one of framing, and it changes what to do about it. Not *"the geometry is
ambiguous and we are stuck with the ghost"*, which is where docs/125 leaves it, but *"the
discriminating signal exists and is small"*. The second is attackable: better blob centroiding,
more LEDs carried into the fit, or rejecting solves that rest on too few correspondences. The
first had no way out.

Caveat: only the **right** controller was dumped — the left one's cells were flat that night. The
left is presumably a mirror image, unverified.

## 5. Method notes, because two of tonight's readings were artifacts

- A `0` from a stationary operator who is not where you think they are looks exactly like a `0` from
  a physical limit. Tonight produced two of them: one full 90 s sweep run with nobody holding a
  controller, and one "75 cm" window measured from 1 m. Both were caught only because a control
  measurement was repeated. **Always re-run a zero before believing it.**
- The free hunt (`led_hunt.sh`, speaks "te veo" on each new sample) went from 18/s to 175/s as the
  operator found the camera cone. Controller *orientation* moves the sample rate by ~10x, far more
  than the distances under test. Any cross-arm comparison has to hold wrist attitude fixed, and
  that is a real limit on how fine a difference this protocol can resolve.
- Scripts: `led_measure.sh` (one window, operator-confirmed, never self-starting),
  `led_hunt.sh`, `led_arm.sh`. Nothing auto-starts — an earlier timed version began its phases
  before the operator was in the room.

## 6. What this changes for docs/125

- **Remove** absolute scale from the open-suspect list (§3 above).
- **Correct** the cliff's location: 75 cm is healthy, the wall is 77 cm–1 m.
- **Reframe** the LED lead: not a fix to try, a change that is actively harmful until exposure
  timesync exists. The `WMR_CONTROLLER_LED_INTENSITY=0` default stays.
- **Add** the resolution hypothesis as the leading explanation for the wall, pending the ring-diameter
  check.
- **Still open, untouched tonight:** the yaw ghost, which is a different failure and is what the
  wearer actually feels as "los joys no respetan la posición" inside arm's reach. Nothing here
  addresses it.
