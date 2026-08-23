# Play-space setup criterion, the blob-flood diagnosis method, and new battery findings (2026-08-18/19)

Companion to docs/55 (the A/B those findings gated). Everything here was measured live on the
everyday system with the tracker's own telemetry — no camera images were ever viewed; blob
counts and AEG state are the instruments (privacy-preserving by construction).

## The objective "setup OK" criterion (measured, reusable)

With BOTH controllers hidden/off, `CONSTELLATION_TRACKER_LOG=trace` for ~25s, count blobs per
camera (`fast processing for camera ... with N blobs`):

- **GREEN: ≤3 spurious blobs per camera, and SLAM logs 0 `Tracker diverged ... Resetting` in
  30s.** The good state measured tonight: 2/0/0/0.
- With controllers visible expect ~5-16 blobs each on the cameras that see them (they BLINK —
  counts fluctuate per frame; never try to tell LEDs from spurious by count with a controller
  in view, always measure spurious with zero controllers visible).

**Setup that achieves it** (this room, generalizes):
1. The lamp/light source BEHIND the visor's plane — no camera sees it. The side cameras aim
   outward/up and catch ceiling lights from almost any orientation; they are the usual
   offenders (one side camera sat at 26-34 spurious through three room arrangements until the
   source was physically behind the visor).
2. The background the cameras face: static textured furniture/wall with ZERO emitters. **PC
   status/RGB LEDs are perfect permanent spurious blobs** — tonight a visor facing the PC
   measured 66/53/23/25 spurious per camera (~87 constant false points, tracking unusable at
   ~1% solve rate). Monitors count as emitters too.
3. Ambient light moderate: total darkness starves SLAM (measured: resets every ~8s in a dark
   corner — the AEG pegs and features vanish); direct brightness floods blobs. The AEG is the
   light meter: SLAM-frame exposure converging mid-range (~300-6000us, gain not pegged at 255)
   = enough light. `WMR_AUTOEXPOSURE` on by default; controller frames are FIXED at 6000/100
   (`wmr_camera.c` hardcoded) and do not adapt.
4. Controllers 0.5-1.2m from the visor for comfortable matching.

## Battery findings (extends docs/46)

1. **Fresh-alkaline ceiling: raw byte 208** (Energizer MAX, genuinely new, first reading
   2026-08-19 ~23:34 local install). This BREAKS docs/46's linear voltage model (it would
   imply 1.85V/cell — impossible for alkaline): the byte is NOT linear across the full range;
   docs/46's fit is valid in the NiMH band it was fitted on (~65-150). Prior "fresh alkaline
   = 152" (T216) was actually a WORN pair, per the user.
2. **Displayed percent now uses a visual ceiling of 208** (`controller-battery-check.py`):
   `pct = min(100, raw/208*100)`. Thresholds stay in RAW bytes (85 = warning), which is what
   docs/46 calibrated. Rationale: raw/255 showed a brand-new cell as "82%", which reads as
   half-worn to a human.
3. **Alkalines sag fast under LED load** — tonight's worn pair went raw 119→79 (~45 min of
   LEDs on); T216's pair 152→75 in one session. Emergency tier only, as already documented.
4. **Over-bright LEDs appear to CAUSE ghost solves** (new, needs a controlled follow-up): with
   3.1V fresh alkalines the right hand's gravity-gate drop fraction hit 97% at baseline
   (vs 8% for the same hand on 2.5V NiMH hours earlier, same room class) and its yaw lock
   couldn't settle (±28 deg residual swings). Suspected mechanism: blob bloom/saturation
   merges neighboring LEDs and shifts centroids, so the solver lands on mirror lobes. So the
   damage curve is TWO-sided: dim LEDs starve blob detection (T167), over-bright LEDs corrupt
   correspondence. NiMH's flat 1.2V discharge sits in the sweet spot — alkaline's 1.5V start
   may simply be too hot for this LED driver. "Hay que investigar bien qué impacto tiene" —
   this is the concrete experiment: same controller, same scene, cells at 3.1V vs 2.6V vs
   2.4V, measure ghost fraction.
5. **The mid-session battery-swap hazard is now 2-for-2**: both swaps tonight forced a service
   relaunch anyway (late-attached controllers get no constellation registration/role — Monado
   device list is fixed at startup). Treat "swap cells" as "relaunch the session" always.

## User-facing battery feature (user's spec, 2026-08-19, for vr-launcher/ARkade)

- Battery TYPE selectable per profile in the user menu (chemistry/brand), plus its mAh.
- From type+mAh+the measured discharge curves (docs/46 + tonight's data): show **estimated
  remaining session time**, not just a percent.
- Note in the UI that estimates assume an UNMIXED pair; mixed cells fall back to generic
  conservative values.
- Battery affects TRACKING before it affects power-off (T167 dim-LED starvation; tonight's
  over-bright corruption): the warning must be **proactive** ("charge/swap before the next
  session"), not reactive ("it died") — the perfect-service line for the commercial-showcase
  framing.


## Addendum 2026-08-23 (T245, docs/67 S1) — dim room, head SLAM: three runaways in the first minute, scale lost when walking

Aircar run #1, wearer seated from the start, room light "tenue" (wearer's word), constellation OFF
(head SLAM only). Raw `tracking.csv` in 2 s buckets: runaways at t+8-24 s (0.6 → 8.6 m/s, cut by
the 10 m/s auto-reset), t+34-46 s (reset #2), t+52-74 s (peaked 3.8 m/s, **no reset**, raw pose
parked at 41 m) — the last one and a later +10 m excursion coincide exactly with the wearer's two
short walks (00:12, 00:15: *"I ended ~5 m outside the ship; A recentres"*). Basalt received 300
frames/10 s at 40 ms end-to-end throughout, so this is not starvation: it is the feature supply in
a dim room. Seated flying drifted ~0.33 m/min (T163's 0.37). **The startup low-light warning (memory
`idea_low_light_tracking_warning`, approved 2026-08-17, never built) moves to the front of the
queue; the in-session light A/B (same walk, room lit) is the next measurement.** `det(Q1Jl)==0`
count: 63 worn, 2011 by teardown (mostly while resting).
