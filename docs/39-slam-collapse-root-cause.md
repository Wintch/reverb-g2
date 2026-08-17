# SLAM pose-rate collapse (T192-T195) — ROOT CAUSE found (2026-08-17)

Root-caused on the everyday system (KDE/X11/NVIDIA-550/60Hz, same physical rig, SSD
swap) with staged env-gated instrumentation in Basalt (`VIT_COLLAPSE_LOG=1`; commits on
basalt `lab-current`, bundle `basalt-collapse-instr.bundle`). The turntable
(`docs/38`) made it reproducible on demand (~10 min onset, hands-free).

## Root cause: `processImu()` blocks integrating a large IMU gap

**`FrameToFrameOpticalFlow::processImu()`** (`frame_to_frame_optical_flow.h`) integrates
IMU from the previous frame's time up to the current image's timestamp with a
**blocking** pop:

```cpp
while (data->t_ns <= curr_t_ns) {        // integrate up to the image time
  pim.integrate(*data, ...);
  input_imu_queue.pop(sample);           // BLOCKING pop
}
```

When the collapse is running, each processed image is ~600 ms newer than the previous
one (drop-oldest on the bounded `input_img_queue` discards ~18 frames between the ones
that get processed). `processImu` must then integrate a ~600 ms IMU gap — and because the
image timestamp is **ahead of the arriving IMU stream**, the blocking pop waits in real
time for the IMU (250 Hz) to catch up to the image time: **~600 ms of blocking per frame.**
It is self-sustaining: the block delays the frontend → more images pile up and drop →
bigger time jumps → more IMU to wait for.

## Evidence (per-stage timing at collapse)

At collapse (`vit_collapse OUT wall_ms` ≈ 590-604 ms), everything except processImu is fast:

| Stage | ms at collapse | log |
|---|---|---|
| `processImu` (IMU catch-up) | **573-634 ms** | `vit_loop imu_ms` |
| image-pop wait | ~0.0004 ms | `vit_loop pop_ms` |
| `processFrame` (optical flow) | ~10 ms | `vit_of total_ms` |
| VIO `optimize()`+`marginalize()` | ~3 ms + 0.2 ms | `vit_vio` |

`imu_ms` alternates ~600 ms / ~0.001 ms frame-to-frame, matching the bimodal output
pattern. Nothing else is near 600 ms.

## What it is NOT (ruled out by data, in order)

- **The companion storm / 0049** — reproduced with ~10 companion errors, no storm.
- **The environment** — reproduced on a completely different stack from the lab.
- **CPU scheduling** — T195's perf trace already ruled it out.
- **The VIO backend** — `optimize`/`marginalize` stay ~2-3 ms; state (`frame_states`,
  `frame_poses`, `marg_H`, `landmarks`) is small and **bounded**, not growing.
- **Optical-flow compute / keypoint growth** — `processFrame` ~10 ms; `keypoints` stable
  ~300; `recall`/`patches` off (`recall_enable=false`), so the patches leak does not apply.

## Onset after ~10 min, and a likely shared root with the position pops

The collapse takes ~10 min to onset — something builds until the image timestamp first
runs far enough ahead of the IMU to trigger a block, after which the vicious cycle makes
it permanent. The image clock (`cam_hw2mono`) drifting ahead of the IMU clock (`hw2mono`)
is exactly the clock-domain instability behind the **position pops** (see
`docs/re-windows/02` + `05`): `hw2mono` is re-fit from noisy arrival timestamps every
sample, so it wanders. **Hypothesis to test:** the pops fix `WMR_CLOCK_MIN_LATENCY=1`
(stabilises `hw2mono`) may also delay or prevent this collapse. If so, the two bugs share
one root.

## Fix directions (to design + test)

1. **Do not block indefinitely in the IMU catch-up.** In the
   `while (data->t_ns <= curr_t_ns)` loop, use a non-blocking / time-bounded pop: if the
   IMU queue is exhausted before reaching the image time, stop and predict from what was
   integrated instead of stalling. (Most direct, contained.)
2. **Cap the integration window / reset on a large time jump.** If
   `curr_t_ns - prev_t_ns` is far beyond a frame period (frames were dropped), skip the
   full re-integration; there is already a divergence auto-reset to lean on.
3. **Address the upstream clock divergence** (shared with the pops) so the image timestamp
   does not run ahead of the IMU in the first place.

## Reproduce

`WMR_CONSTELLATION_CONTROLLERS=1 VIT_COLLAPSE_LOG=1 jack-in-wayland.sh 1 6dof`, controller
spinning on the turntable to sustain the load; the collapse onsets at ~10 min. Watch
`grep -E 'vit_loop|vit_collapse OUT' jack-in.log` — `imu_ms` climbing to ~600 ms while
`OUT wall_ms` collapses to ~1.5 Hz is the signature.
