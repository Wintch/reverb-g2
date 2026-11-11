# 08 — Passthrough and play-area limits

**Status.** v0 (flat, monocular camera passthrough) is built and has been worn-tested; v1
(reprojected stereo) is ruled out by the camera geometry; v2 (marker-based boundaries) is
unstarted. The passthrough work was scoped when head-SLAM 6DoF collapsed, so anything that
needed head position used controller-only tracking (`ctrl` mode). **That collapse has since
been root-caused and fixed** (see `docs/39-slam-collapse-root-cause.md`,
`docs/44`, basalt patch 0008 and monado patch 0055), and 6DoF is now in use (README,
`docs/23`); the "Basalt/6DoF verdict" section below is historical. The final verdicts are in
"Reality check", "v0 built", and "What was learned afterwards" below.

## The idea

Two related goals:

1. **Passthrough**: take the video feed from the headset's cameras and reproject it inside,
   like the Quest's mode where you see the surroundings so you don't bump into things while
   a game is starting up, or when you get close to a wall.
2. **Boundaries**: have the system know where the walls are. The proposed approach is to **read
   markers** placed in the environment.

## Why this is plausible here

A good part of the scaffolding is already in the rig:

- The G2 has **4 tracking cameras**, and Monado's WMR driver already brings them up
  (`WMR_CAMERAS=1`; the 3dof mode sets `WMR_CAMERAS=0`, and the default 6dof mode needs the
  cameras on for SLAM).
- Monado already parses the **headset calibration** stored in its firmware — it uses it
  for tracking. The cameras' intrinsics/extrinsics come from there, no need to calibrate
  by hand.
- We already have our **own player** (patched `hello_xr`, `docs/02-player-360.md`) with a texture and
  projection pipeline, which is more than half the work of displaying anything inside the
  headset.

## Realistic expectations for the cameras

Before getting excited, this isn't going to look like the Quest 3:

- The G2's cameras are **monochrome**, for tracking, not color. **Passthrough is going to
  be black and white.** There's no way to get color out of a sensor that doesn't capture
  it.
- They're **wide-angle / fisheye**, spaced farther apart than the eyes, and pointing
  outward. Reprojecting that to each eye's actual position isn't just pasting two images
  together: there's distortion and parallax to correct.
- Resolution and frame rate: **verify before designing anything.** The fastest plan is to
  bring up Monado with `WMR_CAMERAS=1` and see what format and fps it reports. If the
  cameras run at 30 fps and the panel at 90, passthrough will be juddery and we'll need to
  decide whether to interpolate or accept it.

For the actual purpose —**not bumping into things**— none of this is disqualifying. B/W,
with some distortion, at 30 fps, is perfectly enough to see where the table is.

## Paths, in order of difficulty

### v0 — See the cameras, without reprojecting (doesn't depend on anything pending)

Show the raw stream on a flat layer inside the headset, like a "floating window". Ugly but
useful, and it lets us measure what the cameras actually deliver. **This is the only item
on this list that can be done today**, because it doesn't need 6DoF or parallax
correction.

### v1 — Reprojected stereo passthrough

The two front cameras → one per eye, with undistort and reprojection using the firmware
calibration. Without depth information, we have to assume a plane at a fixed distance:
objects at that distance look correct, closer ones "swim". This is what first-generation
passthrough did and it's acceptable for orienting yourself.

### v2 — Boundaries via markers

**The most realistic path for room boundaries, and by far the cheapest.** Fiducial
markers (ArUco / AprilTag) printed and stuck on the walls: they're detected very well
with low-resolution B/W cameras, they give full pose (position + orientation) per marker,
and detection is mature, lightweight code. With three or four markers per wall, you
define the play volume without dense SLAM.

The "no markers" alternative —reconstructing the environment and detecting planes— needs
dense SLAM and is an entirely separate project. Markers are the right shortcut.

## Parked idea: a custom frontend/shell inside the headset

An "operating system"-style 3D shell inside the headset (browse a directory, open videos
from there instead of launching `play360.sh` from a terminal). Not researched: it needs a
survey of embedded VR compositors and Wayland shells for XR (`xr-video-player` and similar
cover a single video, not a file browser) before any design.

## Dependency on head tracking

v1 and v2 need the head's position to reproject correctly or to know the distance to a
wall. Head-SLAM 6DoF is the weak link (see "Basalt/6DoF verdict" at the end), which is one
more reason v1 is not worth building. v0 needs none of it.

## Reality check

The per-camera factory calibration (`~/vr/camera-calibration.json`, written by
`wmr_hmd_write_cam_calib_snapshot()` in `wmr_hmd.c`) and live PGM snapshots
(`~/vr/camera{0..3}.pgm`, from `wmr_camera_dump_snapshot_pgm()` in `wmr_camera.c`) are
available on disk without a wearer. They answer the questions the first draft could only
guess at.

### 1. Camera geometry — do any 2 cameras form a human-eye-like stereo pair?

Reading `~/vr/camera-calibration.json` (cam0's pose is the identity/reference frame,
cam1-3 poses are relative to it):

| pair | baseline | relative rotation | verdict |
|---|---|---|---|
| cam0–cam1 | **108.2 mm** (`sqrt(0.1065²+0.0041²+0.0186²)`) | **~20.0°** toe (`2·acos(0.984841)`), mostly yaw | only forward-facing pair; still wrong for eyes |
| cam0–cam2 | 137 mm | **~176°** (`2·acos(0.0357)`) | cam2 points almost the opposite way from cam0 — a side/downward tracking camera, not forward |
| cam0–cam3 | ~42 mm (irrelevant) | **~179°** (`2·acos(0.00498)`) | same story as cam2 |

This matches `wmr_hmd.c`: cam0/cam1 are the only pair Monado itself treats as a stereo
unit (`wmr_hmd_hand_track()` wires `slam_sinks->cams[0]`/`cams[1]` through a shared
`entry_cam0_sink`/`entry_cam1_sink`, and `wmr_hmd_guess_camera_orientation()` computes a
"front camera" twist angle from `P_ht0_me`, the head-tracking-cam0→middle-of-eyes
transform Monado already carries for exactly this reason — cam0 is known, by Monado's own
code, not to sit at the eye). cam2/cam3 are auxiliary wide-angle trackers facing away from
straight-ahead and are not stereo-pair candidates at all.

So cam0/cam1 is the only candidate, and it's a bad one for eyes:

- **Baseline 108 mm vs. human IPD ~54–74 mm (median ~63 mm)** — about 1.5–2x too wide.
- **~20° mutual toe-in vs. ~0° (human eyes are essentially parallel at
  conversational/room distance)**. A 20° toe converges the pair's optical axes at
  `108mm / (2·tan(10°)) ≈ 31 cm` — this rig is built to stereo-match at *hand/controller
  distance*, not room-scale. Show that raw to each eye and distant objects will show
  double (diplopia); only things ~30 cm out line up.
- Cameras are **monochrome 640×480** (confirmed straight from the JSON `image_size`), with
  strong fisheye distortion (cam2's own `k1=0.93, k2=0.99` shows just how aggressive these
  lenses are, even though it's not the candidate pair).
- Capture is **~30 fps** against the panel's 90 Hz (`wmr_camera.c`'s own comments: "Tracking
  frames usually come at ~30fps") — a 3:1 mismatch, so raw display would judder without
  frame-hold/interpolation.

**Verdict: geometry rules out a real stereo pair.** This isn't a software problem to
engineer around — the two candidate sensors are physically mounted and aimed for
short-range hand/controller tracking, not for standing in for a pair of human eyes.

### 2. Live capture

Fresh synced dumps of `~/vr/camera{0..3}.pgm` were converted to PNG and inspected (headset
resting on a desk, not worn, so this shows sensor, format and distortion characteristics, not
a wearer's view):

- All 4 frames are genuinely **different, mostly non-overlapping scenes** — consistent
  with the calibration angles above (cam0/cam1 only ~20° apart, cam2/cam3 pointed almost
  the opposite way). There is no framing where all 4 look at "the same room."
- **Confirmed monochrome**, visible **fisheye barrel curvature** (a straight desk edge and
  wall-floor line both bow across the frame in cam1 and cam3), and **heavy sensor grain**
  in the darker regions — these are low-light tracking sensors, not passthrough-grade
  optics.
- No obvious rolling-shutter tearing or corruption; frames are clean single exposures, so
  whatever the eventual passthrough is, raw frame quality itself isn't the blocker —
  geometry and mounting are.

### 3. Prior art — does Monado already have a passthrough extension to build on?

Yes and no. Monado's OpenXR state tracker already contains `XR_FB_passthrough`:
`src/xrt/state_trackers/oxr/oxr_passthrough.c` and `oxr_api_passthrough.c` (145 + 205
lines, `Copyright 2023-2024, Qualcomm Innovation Center` — contributed for Qualcomm's own
XR reference platform, not written with the G2 in mind). It defines the full
create/destroy passthrough + passthrough-layer + `xrt_layer_passthrough_data` API surface
in `xrt_compositor.h`.

**But there is no real backend behind it for this rig.** `create_passthrough` /
`layer_passthrough` are only implemented in the *client-side* compositor wrappers
(`comp_vk_client.c`, `comp_gl_client.c`, `comp_d3d11_client.cpp`, `comp_d3d12_client.cpp`)
— these just forward the IPC call outward. `comp_main` — the actual Linux/NVIDIA
rendering compositor this rig runs — has **zero** implementation of either function.
Calling `XR_FB_passthrough` today would enumerate as a supported extension and then do
nothing: there's no compositor code that turns a passthrough layer into camera pixels on
screen. It's API scaffolding built for Qualcomm's own (closed) compositor backend, not a
usable feature here.

Also checked: **no Quest/Oculus driver exists in Monado** (`src/xrt/drivers/` has nothing
matching `quest`/`oculus`/`ovr`) — Quest runs Meta's own runtime, not Monado, so there's no
local driver code for "how Quest does passthrough" to read for architecture patterns
either. The Qualcomm state-tracker code above is the only passthrough-shaped prior art in
this tree.

### Verdict

**Real reprojected stereo passthrough (v1) is not worth building on this hardware.** The
only forward-facing pair is toed-in for ~30 cm hand-tracking distance, not room-scale
viewing, on top of the already-known monochrome/fisheye/30fps limits. "Half the work already exists" was optimistic: `comp_main` would need a
`create_passthrough`/`layer_passthrough` implementation written from scratch — Monado's
existing passthrough code doesn't help here, it's Qualcomm's own unwired plumbing.

**v0 (flat, unreprojected, single-camera view shown to both eyes) is the realistic
ceiling** — the same thing Windows' Flashlight already does (this doc's own prior finding:
Flashlight is monocular, 1 of 4 cameras). It needs no OpenXR passthrough extension, no
compositor backend, and no reprojection math: just the camera-frame-dump path (already
live) fed as a texture into a quad layer in our own player (`docs/02-player-360.md`), duplicated to both
eyes. That's the concrete next step if this is picked back up — not a new v1 design, v0
exactly as scoped in 2026-08, now unblocked by real numbers instead of assumptions.

**v2 (marker-based boundaries) is unaffected by any of this** and remains the cheapest,
most realistic path to "know where the walls are" — it never
depended on the cameras forming a stereo pair, only on detecting fiducials with whichever
single camera sees them. Placing them in world space needs a tracked pose, which controller
(`ctrl`) tracking can provide without head SLAM.

## v0 built and worn-tested

cam0's live feed, flat, unreprojected, shown identically to both eyes: the same ceiling as
Windows' own Flashlight on this headset (one camera's feed for orientation help, nothing
smarter). Worn-tested after the fixes below; verdict at the end of this document.

### What was built

The `hello_xr` player (`docs/02-player-360.md`) already had everything except a live source:
NV12 texture upload into a ring of staging buffers, a YUV-to-RGB pass, and a `PROJ_FLAT` +
mono render path (forced via `-p flat -e mono`). The missing piece was a frame producer that
is not ffmpeg decoding a file.

`Video360::Open()` (`OpenXR-SDK-Source/src/tests/hello_xr/video360.cpp`) now recognizes a
`.pgm` path as a live camera dump instead of a video file. No ffmpeg is touched in this
mode: a new `PollCameraLoop()` thread (replacing `DecodeLoop()`) polls the file's mtime and,
on change, copies its raw 8-bit grayscale bytes straight into a free NV12 staging slot's Y
plane — byte-for-byte, since a PGM P5 row already IS a tightly packed 8-bit luma row — with
the UV plane pinned to neutral (0x80). The sensor is monochrome, so there's no chroma to
synthesize, and centered-zero chroma makes the existing shared shader output R=G=B=Y
regardless of which color matrix it assumes. Everything downstream (`graphicsplugin_vulkan.cpp`'s
`LoadVideo()`/`UpdateVideoTexture()`, the staging-buffer ring, the flat/mono render path)
needed **zero changes** — it was already generic over `Video360`'s public interface.

Usage:

```bash
./play360.sh -p flat -e mono -w 60 -t 25 ~/vr/camera0.pgm
```

cam0 is the right single camera: it is the one Monado's `wmr_hmd.c` already treats as the
"front" camera (`P_ht0_me`, `entry_cam0_sink`); cam1 is ~20 degrees off-axis and cam2/cam3
point almost the opposite way.

The passthrough changes live in the lab trees (`video360.cpp` of the hello_xr player and
`wmr_camera.c` of Monado); they are not part of the published `patches/` series.

### Headless sanity test

With cameras on, head 3dof, no SLAM and no controller constellation
(`./jack-in-wayland.sh up 1 ctrl`), `camera0.pgm` updated within 1 s of bring-up and
`play360.sh` ran 25 s against it: the log reads `640x480 live camera feed`, the banner shows
flat / mono / `camera-pgm`, 8 staging buffers of 0.4 MB are allocated, no crash, no new
warnings, clean teardown. The source frame (pulled mid-test) was right-side-up and
correctly proportioned. A headless run cannot say whether the view is usable for
orientation; only a wearer can (comfort, latency feel, how the update rate reads).

## What was learned afterwards (worn iterations)

### Frame rate and latency

- The driver's snapshot dump was throttled to ~1 fps (`WMR_CAMERA_SNAPSHOT_THROTTLE`, tuned
  for the dashboard's camera card). `WMR_CAMERA_SNAPSHOT_RATE_DIVISOR=1`, plus dumping from
  the controller-tracking frame type too, raises it to ~90 fps.
- The player's `PollCameraLoop()` polled the file's mtime every 33 ms, which silently capped
  the observed rate near 30 fps no matter how fast the driver dumped; a 4 ms poll interval
  removes the cap.
- `WMR_CTRL_EXPOSURE_FOLLOW_SLAM` fixes a brightness flicker caused by the two camera frame
  types (SLAM vs controller tracking) using different exposures.
- A `camera<N>.pgm.ts` sidecar carries a `CLOCK_MONOTONIC` write time (not the device's own
  tick clock, which is a different domain). Measured write-to-poll staleness: mean ~2.5-3 ms,
  worst ~48 ms, ~90 samples/s. The disk-write/poll bridge is therefore not the source of the
  felt redraw on fast head turns. Camera exposure time and the decode-render-present chain
  after the poll were not measured.
- With the quad head-locked (`HELLO_XR_FIXED_POSE=1`) there is no geometry artifact from
  turning: any redraw feel on fast turns is capture-to-display latency. Raw passthrough has
  no stable virtual horizon, which is why it feels worse than a SteamVR game at similar
  latency.
- Occasional felt jolts coincide with Monado's `Fake pacer fell behind` warnings (software
  frame pacing fallback, present on every NVIDIA Linux session; multi-period jumps track the
  G2 USB port fault, `docs/22-cable-connector-diagnosis.md`). Not passthrough-specific.

### Fisheye correction

The calibration JSON carries `fx, fy, cx, cy, k1..k6, p1, p2` per camera. Read from Basalt's
`fisheye624_camera.hpp`, the model is Basalt's `Fisheye624Camera`: a Kannala-Brandt
equidistant radial term (order-12 odd polynomial in theta with `k1..k6`), a Brown-Conrady
tangential term (`p1, p2`), and an optional thin-prism term that is zero in this rig's
calibration. Forward distortion (undistorted ray to raw pixel):

```
xp, yp = undistorted normalized ray (x/z, y/z), Basalt/OpenCV convention: +Y down, Z forward
rp = sqrt(xp^2 + yp^2); th = atan(rp)
theta_dist = th * (1 + k1*th^2 + k2*th^4 + k3*th^6 + k4*th^8 + k5*th^10 + k6*th^12)
xr, yr = theta_dist * (xp, yp) / rp
rd2 = xr^2 + yr^2
dx_tan = (2*xr^2 + rd2)*p1 + 2*xr*yr*p2
dy_tan = (2*yr^2 + rd2)*p2 + 2*xr*yr*p1
u = fx*(xr + dx_tan) + cx;  v = fy*(yr + dy_tan) + cy
```

The inverse has no closed form, so the fragment shader keeps sampling forward: for each
output pixel it builds the undistorted rectilinear ray, forward-distorts it (`Cam0Distort`
in `frag.glsl`, `PROJ_FLAT` branch) and samples the raw frame there. Corners outside cam0's
real 640x480 frame are masked black. cam0's constants are baked into the shader (the push-
constant block is already at the 128-byte limit, and only cam0 is read; a second live camera
needs a real uniform buffer). It is on by default under `HELLO_XR_FIXED_POSE` and can be
forced off with `HELLO_XR_PASSTHROUGH_FISHEYE_CORRECT=0` for A/B. Verified by matching
`distort()` term by term and by a synthetic straight-line grid forward-projected through the
same lens model, which the shader path recovers as straight lines. A wearer's A/B on a
door frame or monitor bezel was not recorded.

### Synthetic geometry in the passthrough view

- **Reference frame.** The video is head-locked (the camera already bakes head rotation into
  the frame), but world-anchored geometry (floor, room box) must use the real live head
  orientation with the same recenter-yaw and projection (`layerView.fov`, same digital zoom)
  as the video. Freezing the orientation makes the grid glue to the screen; using raw
  `layerView.pose` ignores the recenter-yaw and makes it drift by a constant offset. Composing
  one quaternion and inverting the whole rigid body is only valid for pure yaw: with pitch and
  a non-zero recenter-yaw it diverges (up to 145 NDC units at yaw 90 / pitch 30 / recenter 30).
- **z-fighting.** `Pipeline::CreateGraphics` hardcoded `depthWriteEnable = VK_TRUE` for every
  pipeline. The fullscreen photo/video pass draws at clip depth 0.0 (nearest possible), so it
  stamped the whole depth buffer and no cube could ever pass the depth test. Depth write is
  now off for the photo/video pipeline only.
- **Controller gizmos.** Require `XR_SPACE_LOCATION_POSITION_TRACKED_BIT`, not just VALID: an
  untracked controller is pinned by Monado at a placeholder offset, which in `ctrl` mode is the
  tracking origin, i.e. at the wearer's own head. On dropout the last tracked pose is held.
- **Floor height.** Monado's legacy space overseer puts Stage 1.6 m below Local;
  `XRT_TRACKING_ORIGIN_OFFSET_Y = real eye height - 1.6` (set by `jack-in-wayland.sh` from
  `VR_POSTURE` and `EYE_HEIGHT_STANDING_M` / `EYE_HEIGHT_SEATED_M` in `~/vr/vr-profile.conf`)
  already calibrates Stage's Y=0 to the real floor. Ruled out: recomputing the floor from
  `headY - 1.6` in the player, because it reintroduces the 10 cm error the profile exists to
  remove (25 cm for a seated wearer). `recenter_local_spaces` only touches Local and
  local_floor, never Stage, so a Stage floor that looks wrong usually means the headset was not
  worn and upright when tracking was established (the "headset on the desk until loaded" rule).
- **Room box.** A placeholder, `PushRoomBox` (gray walls, white floor), sized to the room and
  centred on the tracking origin. Not calibrated to the real room; a perimeter-walk capture
  with a controller is the intended replacement.
- **Yaw drift.** 3DoF yaw is pure gyro integration with no magnetometer, so a ~15 degree
  offset after ~4.5 h is expected, not a defect.

### Basalt/6DoF verdict

- **Historical: head-SLAM 6DoF originally collapsed.** Enabling it collapsed the camera
  snapshot rate from ~90 to ~3 samples/s and felt severely disorienting. This was later
  root-caused and fixed (IMU catch-up and companion backoff: `docs/39-slam-collapse-root-cause.md`,
  `docs/44`, basalt patch 0008, monado patch 0055). The earlier CPU-scheduling theory (the
  `wmr_cam_usb_thread` camera thread not running `SCHED_FIFO` while Basalt's worker threads
  starved it at a load average of ~4-5) is not the root cause: the real-time-preemption theory
  was tested and disproved (`patches/monado/README.md`, patch 0050), and the camera-thread
  priority change was never measured to matter.
- The older "Basalt diverges at ~3 degrees stationary jitter" note was very likely a stale
  build artifact (the same-week rebuild measured 0.001-0.006 degrees). The real open problem
  is positional VIO divergence under real motion (a live session tripped the 3 m anchor-guard
  reset 191 times in 28 minutes, masked by a reset-to-last-pose guard), see
  `docs/80-aircar-6dof-yaw-drift-plan.md` and `docs/113-dali-redraw-is-pose-staleness.md`.
- **Use `ctrl` mode** (`WMR_SLAM=0 WMR_CAMERAS=1`): cameras on at full rate, Basalt off,
  controller constellation tracking instead. The plain `3dof` mode of `jack-in-wayland.sh`
  sets `WMR_CAMERAS=0` and silently disables the feed (symptom: a stale `camera0.pgm`).
  A walk-the-perimeter room capture using the controller as the tracked point does not depend
  on any SLAM fix.

### Current state of v0

Worn verdict: apart from the pacer jolts above, the v0 monocular passthrough (~90 fps
observed, unified exposure, no geometry artifacts, no z-fighting) is a solid experience for
orientation. Still open: camera exposure time and the render-chain latency are unmeasured;
the fisheye on/off A/B is not worn-verified; v2 markers
and the perimeter capture are unstarted.
