# Turntable test fixture (constant-ω controller spin)

A motorized turntable spinning a WMR controller at a selectable, ~constant angular
velocity. Cheap, hands-free, repeatable, precise, and it can run unattended for an
hour or more. It replaces manual arm-waving, which is imprecise, tiring, and
impossible to repeat. First proven useful 2026-08-17 (see "Proven use" below).

## Why it is much more than validation

A constant-ω, hands-free, long-duration, repeatable motion source is a general test
instrument, not just a way to confirm a fix:

1. **Calibration ground truth.** Constant ω is a known gyro input → gyro **scale
   factor**; the controller at rest → gyro **bias**. The rest + constant-spin pair is
   the core of the IMU calibration the calibrator needs (see `docs/re-windows/07`).
2. **Repeatable regression / A/B.** Identical motion for two builds lets you compare
   drift/jitter *directly* — e.g. the pops fix `WMR_CLOCK_MIN_LATENCY` on vs off under
   the exact same ω. Hand motion cannot be repeated, so it cannot A/B.
3. **Hands-free soak / load generator.** Sustained IMU + constellation + CPU load for
   as long as needed (1 h+). This is what made the **SLAM pose-rate collapse (T192-T195)
   reproducible on demand** — it needs ~10 min of sustained SLAM+constellation load, and
   the turntable supplies it hands-free while keeping the controller awake. Also the
   right tool for companion-storm / CPU-pin soaks.
4. **Constellation tracking validation.** A moving, repeatable LED target for the
   constellation tracker — measure pose stability, the near-pure-yaw position pops, and
   blob detection under real motion instead of a static controller.
5. **Judder / camera-in-display stimulus** (Vector A). Constant rotation is a clean,
   repeatable motion for the through-the-lens judder measurement
   (`reverb-g2-linux/scripts/analyze-panel-judder.py`).
6. **Cross-machine reproducibility.** Same fixture + same ω → comparable results on dev
   vs the everyday system. Since it is the same physical rig (only the SSD is swapped),
   a result that reproduces under the identical turntable motion on both is strong.

## Speeds

The turntable has selectable speeds. Sweeping ω separates rate-dependent effects — gyro
scale linearity, constellation tracking quality vs angular velocity, judder vs motion
speed — that a single speed would hide.

## Practical notes

- It keeps the WMR controller **awake** — otherwise it goes to standby, the LEDs
  dim/blink, and constellation blob detection dies regardless of lighting.
- It stimulates the controller's own IMU and the head cameras' view of the LEDs
  (constellation). It does **not** directly drive the head SLAM (a different pipeline);
  its role in the SLAM-collapse repro is to keep the *constellation* pipeline loaded, not
  to move the head. Keep this split in mind when reading results.
- Instrument the pipeline you are actually measuring: `VIT_COLLAPSE_LOG` for the SLAM/VIO
  path, `CONSTELLATION_TRACKER_LOG` for the controller/constellation, `HELLO_XR_POSE_STATS`
  for pose jitter.

## Proven use (2026-08-17)

Made the SLAM pose-rate collapse reproducible on the everyday system (KDE/X11/NVIDIA-550/
60Hz), hands-free, twice in a row (~10 min onset each), which enabled the live root-cause
narrowing: the collapse is upstream of the VIO backend (optimize/marginalize stay ~2 ms,
state bounded) — it is in the **optical-flow frontend** — and it is **independent of the
companion storm** (reproduced with ~10 companion errors, no storm) and of the environment
(a completely different stack from the lab where it was first caught).
