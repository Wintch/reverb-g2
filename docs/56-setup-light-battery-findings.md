# Play-space setup criterion and the blob-flood diagnosis method (2026-08-18/19)

Companion to docs/55 (the A/B those findings gated). Everything here was measured live on the
everyday system with the tracker's own telemetry. No camera images were viewed; blob counts and
auto-exposure (AEG) state are the instruments, which is privacy-preserving by construction.

**Battery findings that used to live here** (fresh-alkaline ceiling of raw 208, the display
ceiling, fast alkaline sag, over-bright LEDs causing ghost solves, the swap-means-relaunch
hazard, the launcher feature wishlist) are consolidated in `docs/46` section 5.

## The objective "setup OK" criterion (measured, reusable)

With BOTH controllers hidden/off, `CONSTELLATION_TRACKER_LOG=trace` for ~25 s, count blobs per
camera (`fast processing for camera ... with N blobs`):

- **GREEN: <=3 spurious blobs per camera, and SLAM logs 0 `Tracker diverged ... Resetting` in
  30 s.** The good state measured: 2/0/0/0.
- With controllers visible expect ~5-16 blobs each on the cameras that see them (they BLINK, so
  counts fluctuate per frame). Never tell LEDs from spurious by count with a controller in view;
  always measure spurious with zero controllers visible.

**Setup that achieves it** (this room, generalizes):
1. The lamp/light source BEHIND the visor's plane, so no camera sees it. The side cameras aim
   outward/up and catch ceiling lights from almost any orientation; they are the usual offenders
   (one side camera sat at 26-34 spurious through three room arrangements until the source was
   physically behind the visor).
2. The background the cameras face: static textured furniture/wall with ZERO emitters. **PC
   status/RGB LEDs are perfect permanent spurious blobs**: a visor facing the PC measured
   66/53/23/25 spurious per camera (~87 constant false points, tracking unusable at ~1 % solve
   rate). Monitors count as emitters too.
3. Ambient light moderate: total darkness starves SLAM (measured: resets every ~8 s in a dark
   corner, the AEG pegs and features vanish); direct brightness floods blobs. The AEG is the
   light meter: SLAM-frame exposure converging mid-range (~300-6000 us, gain not pegged at 255)
   means enough light. `WMR_AUTOEXPOSURE` is on by default; controller frames are FIXED at
   6000/100 (`wmr_camera.c` hardcoded) and do not adapt.
4. Controllers 0.5-1.2 m from the visor for comfortable matching.

## Dim room, head SLAM (2026-08-23): runaways in the first minute

Aircar run, wearer seated from the start, dim room light, constellation OFF (head SLAM only).
Raw `tracking.csv` in 2 s buckets showed runaways at t+8-24 s (0.6 -> 8.6 m/s, cut by the
10 m/s auto-reset), t+34-46 s (reset #2) and t+52-74 s (peaked 3.8 m/s, **no reset**, raw pose
parked at 41 m); the last one and a later +10 m excursion coincide exactly with two short walks
(tens of metres of raw excursion; the wearer ended ~5 m outside the ship). Basalt received 300
frames/10 s at 40 ms end-to-end throughout, so this is not CPU starvation: it is the feature
supply in a dim room. Seated flying drifted ~0.33 m/min. A startup low-light warning (approved
2026-08-17) was never built; an in-session light A/B (same walk, room lit) is the next
measurement. `det(Q1Jl)==0` count: 63 worn, 2011 by teardown (mostly while resting).
