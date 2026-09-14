# Controller constellation: it is blob ownership, not optics (2026-09-13)

One session, three lab patches, and a retraction of a conclusion reached earlier in the same
session. The headline: **the "visibility cliff" this project has carried since August is not a
distance effect at all**, and the failure it names lives in blob→device correspondence, where
docs/125's class-A work already was.

Setup for everything below: headset **stationary** on a desk facing forward, `ctrl` mode
(`WMR_SLAM=0 WMR_CAMERAS=1`, constellation on), so the tracking origin is the head and a sample's
distance from origin is its hand-to-camera range. Operator holds the **right** controller only —
the left one's cells were flat all evening — at tape-marked distances, 20 s windows, on
operator-confirmed start. Right-controller battery raw 83 or 103 depending on the block, noted per
measurement.

Instruments, all new this session:

| patch | option | what it logs |
|---|---|---|
| **0109** | `WMR_CONSTELLATION_RAW_SAMPLES_LOG` | every sample at the top of `constellation_sample_store`, **before** any gate |
| **0110** | `WMR_CONTROLLER_LED_DUMP` | factory per-LED position and normal, once at init |
| **0111** | `WMR_CONSTELLATION_BLOB_TELEMETRY` | per-observation blob count, size and brightness at the sink, **above** the `num_blobs == 0` early return |

0107's `WMR_CONTROLLER_HEADING_CSV` sits *after* the gravity gate and counts what survives; 0109
counts what the tracker produced; 0111 counts what the cameras produced. Three different
quantities, and the session needed all three to tell its failures apart.

---

## 1. The finding: the device owns none of the blobs

Four windows, gain 100, operator stationary, right controller only:

| window | constellation samples | blobs/frame | blob size p50 | brightness p50 |
|---|---|---|---|---|
| 75 cm | **380** (19.0/s) | 5.61 | 22.67 px | 0.385 |
| 100 cm | **0** | 6.44 | 22.14 px | 0.444 |
| 75 cm again | **0** | 5.78 | 22.50 px | 0.476 |
| 75 cm, after a full Monado restart | **0** | 6.26 | 19.80 px | 0.478 |

Detection is healthy in **every** window, including all three zeros. At 1 m the cameras saw *more*
blobs, the same size, *brighter* than at 75 cm — and solved nothing. The share of frames with zero
blobs is 25.0% everywhere, which is simply the one camera of four that cannot see the controller.

The tracker's own telemetry names the failure:

```
blob ownership: device 0 holds 0 of 15 blobs this frame
                (BELOW the 4-blob floor tryDeviceBlobRecovery needs)
```

Zero of fifteen, on every sampled frame, with **only one device registered** — so this is *not*
T225's two-hands-competing-for-a-shared-pool mechanism. A single device, up to 15 healthy blobs in
front of it, no competitor, and it acquires none of them.

The message also names a deadlock worth stating on its own: **recovery requires 4 already-owned
blobs, and a device sitting at 0 can never climb to 4.** Whatever drops ownership to zero is
therefore permanent for that session — and a full Monado restart did not clear it either, so
acquisition itself is failing, not just re-acquisition.

**Consequence for docs/125's taxonomy:** class B ("visibility cliff") collapses into class A's
territory. It is correspondence, not optics, not range, not light. One broken thing, not two.

## 2. RETRACTED: the visibility cliff as a distance effect

Earlier in this same session, measured in increasing-distance order with the zero last and **no
control window afterwards**, this document reported 610 samples/20 s at 50 cm, 634 at 75 cm and 0
at 1 m, and concluded a hard wall between 77 cm and 1 m. §1 ran the missing control. The same
distance that gave 380 gave zero fifteen minutes later, twice, once from a cold start.

**The failure varies with time, all-or-nothing, not with range.** Every range attribution in that
table is confounded. The wall is not established, and neither is the older "zero past ~50-75 cm"
reading it was itself correcting.

Three explanations were built on that table during the session and all three are void:

- **neighbour blobs merging** — dead: blobs are 20-22 px and well separated, and nothing about
  their separation changes between 75 cm and 1 m.
- **sub-pixel emitters** — dead, and wrong by a factor of twenty. A 3 mm aperture predicts ~1 px at
  1 m; measurement says 20-22 px. The fixed-focus fisheye cameras spread each LED over tens of
  pixels. **Never reason about blob size from emitter geometry on this hardware — measure it.**
- **"brightness therefore helps / hurts"** — void in both directions, since there is no established
  distance effect left for brightness to act on.

## 3. Lab patch 0108 (LED pulse train) must stay OFF

Monado has never sent the constellation LED pulse train Windows sends ~15×/s
(`CrystalKeySetLedPulseTrain`). 0108 adds it: report `0x03` + `hmd_cmd_base` → HMD reports
`0x08`/`0x10`, `fill_led_pulse_train_packet()` ported from Jan Schmidt's `fill_timesync_packet()`
(thaytan/monado `dev-constellation-controller-tracking`, same BSL-1.0). Packet format verified
three ways that agree: thaytan's implementation, his 2019 OpenHMD constant, and a field-by-field
decode of the real Windows USBPcap capture — `06 21 03 00 00 00 00 00 00 80 2c` decodes to
intensity 200, ts 0, U2 800, flags 1, ts_ctr 1, all five matching the documented defaults.

**Measured: turning it on destroys constellation tracking.** One raw sample arrived in a
four-minute session across three distances; the control arm produced 610 and 634 in single 20 s
windows at the same distances on the same battery charge. Critically it fails at **50 cm too**,
where the control arm was healthy — this is not a range effect.

The rings *do* get visibly brighter to the eye, so the command reaches the device and does
something real. It just leaves the LEDs useless to the tracker.

Suspected mechanism: Windows recomputes the packet's 55-bit `TS` from the predicted next camera
exposure, and 0108 resends a constant `ts=0`, so the train free-runs and need not be lit during
the cameras' short exposure windows. A higher duty cycle reads as "brighter" to an eye and is
worth nothing to a sensor that looks for a few hundred microseconds at a time.

**The default of 0 is load-bearing, not a formality.** Do not flip it.

Watch item: the intensity-200 run logged one `wmr_hmd_controller_create: Failed to create
controller` the control run did not. It recovered, and one sample against one proves nothing, but
tunnel traffic for controller 0 overlapping controller 1's creation handshake is a plausible
mechanism.

## 4. The LED command is a per-controller SERVO, run open-loop

Operator, comparing the two OSes directly:

> *"la diferencia es que en Windows un solo joy queda más luminoso, el otro no. En Linux ambos
> quedan más brillosos."*

That names the other missing half, and it lines up with a measurement this repo already had and had
not connected:

- **T230 photometry**: on Windows the left ring photographs at ~2.45× the blob area and ~1.9× the
  flux of the right; on Linux the two are identical and both dim.
- **docs/re-windows/04 §3**, over all 10,503 pulse-train commands in the capture: report `0x08`
  commands ~1.3-1.4× the on-time of `0x10`, and the difference is driven by the `count` field, not
  the period.
- **thaytan's branch**, since `1d67d4d` (Beyley Cardellio, 2025-05-17): a closed loop nudges
  intensity from the tracker's measured blob brightness — `−3` above 70, `+10` below 30.

So Windows does not *set* a brightness, it **servos one per controller with blob photometry as
feedback**. The two rings differ because they converge to different operating points. **The
asymmetry is the loop working**, and the older reading of it as a hardware difference between
controllers was backwards.

0108 supplies the actuator and neither of its controllers — no clock to align to, no loop around
it. That is why it is worse than silence.

## 5. Absolute scale is sound — retire that suspect

docs/125 listed absolute scale as never validated, on one hand reading 0.556 m against a 0.75 m
tape. Measured here inside single windows, so **independent of the retracted cliff reading**:

- 50 cm tape → p50 **0.490 m** (min 0.480, max 0.511) — 2% low
- 75 cm tape → p50 **0.767 m** (min 0.741, max 0.792) — 2% high

Two percent, opposite directions, ~3 cm spreads. The solve's metric scale is fine, and since it
holds at both distances it is not a uniform scale factor either.

## 6. The real LED geometry (patch 0110, right controller)

Device data, so this survives everything above. It is **not a ring of 32 evenly-spaced LEDs 11°
apart**, which is what docs/125 assumed. Two concentric shells on the two faces of a shallow cone:

| shell | count | radius | z extent | mean normal z |
|---|---|---|---|---|
| outward-facing | **18** | 51.4–58.7 mm | −9.4 … +6.8 mm | −0.33 |
| inward-facing | **14** | 44.4–50.7 mm | −8.5 … +6.3 mm | +0.35 |

Angular gaps are irregular within each shell: outward 16.5°–25.9° (mean 20.0°), inward 21.0°–30.4°
(mean 25.7°). **Nearest-neighbour distance in 3D: min 12.4 mm, median 14.6, max 20.4.**

A product photo of the G2 pair shows only the outer 18; a first-generation WMR controller
photographed from above shows the inner ones, so the two-shell design is WMR-wide rather than a G2
peculiarity. Raw dump: `docs/data/g2-right-controller-leds-20260913.txt`.

Only the right controller was dumped. The left is presumably a mirror image — unverified.

## 7. docs/125's yaw-symmetry premise is not supported

docs/125 founds the yaw-flip ghost on the ring being "near-symmetric under that half-turn", which
would let correspondence return a wrong-yaw pose fitting as well as the true one. Tested against
the dumped geometry — rotate the pattern about its axis, measure how far each LED lands from the
nearest original:

| rotation | mean displacement |
|---|---|
| 100° | 7.1 mm |
| 160° | 7.4 mm |
| **180°** | **8.5 mm** |
| 260° | 7.1 mm |
| 340° | 9.2 mm |

**No rotation maps the pattern onto itself, and 180° is among the worst** — 100° and 260° are
closer to a self-mapping than the half-turn. The layout is deliberately irregular, as a
constellation designed for unique correspondence should be.

**But the margin is thin, and that is the finding.** 8.5 mm is 58% of the median spacing; in pixels
the yaw-flip discriminant is only **4.6 px at 50 cm and 2.3 px at 1 m**, and the tracker only ever
sees the subset whose normals face it, which is far more ambiguous than the whole.

So the ghost is **not forced by symmetry**. It is a signal-to-noise problem in correspondence — and
that reframing changes the plan. Better blob centroiding, more correspondences carried into the
fit, and rejecting under-determined solves are all live; *"the geometry is ambiguous and we are
stuck"* had no way out. It also sits in the same place §1 landed, which is the first time these two
threads have pointed at one subsystem.

## 8. Method notes — this protocol produced four bad readings in one session

Kept in full, because three of them were caught only by a repeat and the fourth by a contradiction.

- **A 90 s sweep ran with nobody holding a controller.** The timed script started its phases before
  the operator was in the room. Every phase now waits for out-of-band operator confirmation and
  nothing self-starts.
- **A "75 cm" window was measured from 1 m.** The operator had not moved back. Caught only because
  the result was surprising enough to re-run.
- **A confident "no blobs at all → DETECTION limit" verdict was a parsing bug.** The analyser tested
  `"n=0" in line`, which also matches inside `min=0`, so it misread nearly every real frame as
  empty. Caught by the contradiction with 380 solved poses in the same window. Now
  `re.search(r"\\bn=(\\d+)", line)`.
- **`grep -c` chained with `|| echo 0`** yields `0\\n0` on zero matches, since grep exits 1, which
  broke the arithmetic mid-measurement. Fixed with `c=$(grep -c ...); echo "${c:-0}"`.
- **A guard read the device role line once, immediately after the IPC socket appeared**, and
  aborted a healthy session — the roles are logged later. It now waits with a timeout.

And the confound that outranks all of them:

> **Wrist orientation swings the sample rate by ~10×** — 18/s to 175/s while hunting the camera
> cone in a single 90 s window. That is far larger than any effect a distance sweep is trying to
> resolve, and **a hand-held protocol cannot hold it fixed.** docs/59's string-and-knots fixture,
> designed in August and never built, exists precisely to remove it. **No further hand-held
> distance sweeps.** Nothing range-related can be trusted until orientation is mechanically fixed.

A standing rule earned twice tonight: **always re-run a zero before believing it.** A zero from an
operator who is not where you think they are is indistinguishable from a zero from a physical limit.

## 9. What this changes, and what is next

**For docs/125:**

- Class B ("visibility cliff") is retracted as a distance effect and folded into correspondence.
- The "32 LEDs ~11° apart" figure is wrong; real within-shell spacing is 20-26° and irregular.
  The conclusion survives with inverted arithmetic — at ~20°, **one** correspondence slip displaces
  the hand ~16 cm, landing in the observed 10-20 cm, so the symptom is a *single* slip.
- The heading-noise link weakens correspondingly: 10-30° of heading noise is about **one** real
  spacing, not "two to three".
- The near-symmetric-ring premise is not supported (§7).
- Absolute scale leaves the suspect list (§5).

**Next, in order:**

1. **Why does the device own zero blobs?** This is now the whole problem. `num_blobs_for_device`,
   the ownership assignment, and the acquisition path that is supposed to run when ownership is 0
   are where to look. The 4-blob recovery floor and its deadlock are a concrete, testable starting
   point.
2. **Build docs/59's fixture** before any further geometry or range work. Fifteen minutes, and
   without it the orientation confound invalidates the measurement.
3. **Dump the left controller** when it has cells, to confirm the mirror assumption.
4. **Not** the LED brightness path — not 0108, not porting thaytan's timesync. §1 shows amplitude
   is not the constraint; the blobs are already plentiful, large and bright when tracking fails.
