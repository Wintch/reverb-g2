# 08 — Passthrough and play-area limits

**Status: noted 2026-08-04, feasibility investigated 2026-09-05, v0 built and
headless-tested the same day.** ~~Don't touch until 90Hz is closed out (ch. 04).~~ 90Hz was
closed out 2026-08-06 (`docs/19`) — the gate is lifted. See "v0 built and live-tested
(2026-09-05)" at the end for what exists today; v1/v2 below remain unstarted.

**2026-09-05: the open question this doc left hanging — whether any 2 of the 4 cameras
form a usable human-eye-like stereo pair — has now been answered with real calibration
numbers, a live frame capture, and a read of Monado's actual passthrough-extension code.
Verdict: no. See "Reality check (2026-09-05)" at the end. v1 (reprojected stereo) is not
a good match for this hardware; v0 (flat, unreprojected, effectively monocular — the same
ceiling as Windows' own Flashlight) is the realistic near-term deliverable. The 6DoF
blocker this doc names below is also stale: 6DoF has worked reliably since the yaw-ghost
fixes (`docs/55`) and is in daily booth use (`docs/95`, `docs/104`) — that dependency is
no longer the obstacle, camera geometry is.**

## The idea

Two related things, requested by the user:

1. **Passthrough**: take the video feed from the headset's cameras and reproject it inside,
   like the Quest's mode where you see the surroundings so you don't bump into things while
   a game is starting up, or when you get close to a wall.
2. **Boundaries**: have the system know where the walls are. The idea proposed was to **read
   markers** placed in the environment.

## Why this is plausible here

A good part of the scaffolding is already in the rig:

- The G2 has **4 tracking cameras**, and Monado's WMR driver already brings them up
  (`WMR_CAMERAS=1`; today we run with `0` because we measured that turning them off
  doesn't change the 90Hz, ch. 06).
- Monado already parses the **headset calibration** stored in its firmware — it uses it
  for tracking. The cameras' intrinsics/extrinsics come from there, no need to calibrate
  by hand.
- We already have our **own player** (patched `hello_xr`, ch. 02) with a texture and
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

**The most realistic path for what you asked for, and by far the cheapest.** Fiducial
markers (ArUco / AprilTag) printed and stuck on the walls: they're detected very well
with low-resolution B/W cameras, they give full pose (position + orientation) per marker,
and detection is mature, lightweight code. With three or four markers per wall, you
define the play volume without dense SLAM.

The "no markers" alternative —reconstructing the environment and detecting planes— needs
dense SLAM and is an entirely separate project. **Your instinct to use markers is the
right shortcut.**

## Parked idea (2026-08-06): a custom frontend/shell inside the headset

User request, Johnny Mnemonic reference: an "operating system" or 3D shell inside the
headset — browse a directory and open videos from there, instead of launching
`play360.sh` by hand from a terminal. **Not researched yet**: what already exists for
Linux/Wayland/OpenXR to build on (embedded VR compositors, Wayland shells for XR, things
like what we already found today researching players — `xr-video-player`, etc. — but for
a file browser instead of a single video). Take this up as its own research session before
designing anything.

## The dependency we need to face head-on

**v1 and v2 need 6DoF, and 6DoF doesn't work today.** Basalt diverges (ch. 03 and 06) and
all the 360/video work is done in `3dof` mode. Without head position you can't reproject
correctly or know how far you are from a wall.

So the real order is: **90Hz → stable 6DoF → reprojected passthrough**. v0 can be
slipped in earlier, and it's actually worth doing, because it cheaply answers the
format, resolution, and latency questions needed to design the rest.

## Concrete first step when this is resumed

```bash
# Bring up with cameras and see what they actually report (format, resolution, fps)
cd ~/vr && WMR_CAMERAS=1 XRT_COMPOSITOR_LOG=debug ./jack-in.sh 3dof
grep -iE "camera|stream|format|fps" ~/vr/jack-in.log
```

Note the results here. All the design above depends on those numbers, and today they're
just assumptions.

## Reality check (2026-09-05)

Prerequisite work landed since this doc was written: camera-frame-dump (Monado
`e4b153db2`, reverb-g2 `b168b74`) plus the 2026-09-05 calibration-exposure patch put both
the per-camera factory calibration (`~/vr/camera-calibration.json`, sourced from
`wmr_hmd_write_cam_calib_snapshot()` in `wmr_hmd.c`) and live PGM snapshots
(`~/vr/camera{0..3}.pgm`, from `wmr_camera_dump_snapshot_pgm()` in `wmr_camera.c`) on
disk with no wearer needed. That finally answers the questions this doc could only guess
at.

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

### 2. Live capture ("look at the actual images")

Monado had run in `WMR_CAMERAS=1` mode earlier the same day (2026-09-05, ~14:22 local),
so fresh synced dumps already existed — no need to start a new session against an idle
rig. Pulled `~/vr/camera{0..3}.pgm`, converted to PNG, and looked at them directly (headset
was resting on the desk at capture time, not worn — so this shows sensor/format/distortion
characteristics, not a wearer's forward view):

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
viewing, on top of the already-known monochrome/fisheye/30fps limits. Even with 6DoF now
solid, "half the work already exists" was optimistic: `comp_main` would need a
`create_passthrough`/`layer_passthrough` implementation written from scratch — Monado's
existing passthrough code doesn't help here, it's Qualcomm's own unwired plumbing.

**v0 (flat, unreprojected, single-camera view shown to both eyes) is the realistic
ceiling** — the same thing Windows' Flashlight already does (this doc's own prior finding:
Flashlight is monocular, 1 of 4 cameras). It needs no OpenXR passthrough extension, no
compositor backend, and no reprojection math: just the camera-frame-dump path (already
live) fed as a texture into a quad layer in our own player (ch. 02), duplicated to both
eyes. That's the concrete next step if this is picked back up — not a new v1 design, v0
exactly as scoped in 2026-08, now unblocked by real numbers instead of assumptions.

**v2 (marker-based boundaries) is unaffected by any of this** and remains the cheapest,
most realistic path to the user's actual "know where the walls are" request — it never
depended on the cameras forming a stereo pair, only on detecting fiducials with whichever
single camera sees them, and 6DoF (needed to place them in world space) is no longer
blocked.

## v0 built and live-tested (2026-09-05)

Built, not just scoped: cam0's live feed, flat, unreprojected, shown identically to both
eyes — the same ceiling as Windows' own Flashlight on this headset (a single camera's feed
for orientation help, nothing smarter). **Status: working prototype**, headless-tested
against the real rig; no worn test yet.

### What was built

`hello_xr`'s own player (ch. 02) already had everything except a live-updating source:
NV12 texture upload into a ring of staging buffers, a YUV→RGB conversion pass, and a
`PROJ_FLAT` + mono render path already proven live on ordinary 2D clips (forced via
`-p flat -e mono`). The only missing piece was a frame producer that isn't ffmpeg decoding
a video file.

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

cam0, not cam1/2/3: it's the one Monado's own `wmr_hmd.c` already treats as the "front"
camera (`P_ht0_me`, the head-tracking-cam0-to-middle-of-eyes transform; `entry_cam0_sink`).
The calibration read earlier in this doc has cam1 ~20° off-axis and cam2/cam3 ~176-179° off
— pointed almost the opposite way — so cam0 is the only sensible single-camera choice here.

Committed: `OpenXR-SDK-Source` commit `7e43d92` ("360 viewer: live camera-feed source (docs/08
passthrough v0)"), touching only `video360.cpp`. The tree had unrelated uncommitted work in
progress in other hello_xr files (a GPU-load-sweep feature, Aircar trigger-debug logging) at
the time — left untouched, not part of this commit.

### Live headless test (2026-09-05, ~15:00)

`pgrep -af monado-service` was checked fresh immediately before acting each time (a
concurrent, unrelated lease/relaunch-race investigation was using this same rig earlier the
same afternoon — monado-service was seen up, then down, within a few minutes, before I ever
touched anything). Confirmed genuinely idle (stable "down" across repeated checks) before
bringing up my own session.

Brought up with `./jack-in-wayland.sh up 1 ctrl` (`WMR_CONSTELLATION_CONTROLLERS=0`): cameras
on, head 3dof, no SLAM/Basalt, no controller constellation — the fastest path to fresh
`cameraN.pgm` dumps without 6dof's known jitter (ch. 06) or needing any controller powered
on (nothing here reads controller input). `camera0.pgm` updated within 1s of bringup,
confirming the cameras were actually streaming before the player ever launched.

`play360.sh` then ran for 25s against `camera0.pgm`. Results:

- hello_xr's own log: `video360: '/home/iam/vr/camera0.pgm' 640x480 live camera feed (docs/08
  v0 - flat, unreprojected)`, followed by the banner correctly reading `MODO: PLANO` / mono /
  `640x480` / `camera-pgm (live, v0 flat, no reprojection)` — projection and stereo forced
  exactly as requested, nothing misdetected.
- 8 staging buffers allocated (0.4 MB each, 4 MB total) — the normal `Video360::kFrameBuffers`
  ring, same as video/photo mode.
- Ran the full 25s with no crash, no new warnings beyond two pre-existing, unrelated Vulkan
  validation PERF notices (`vertex attribute ... not consumed by vertex shader` — present
  regardless of source, not new here) and the routine client/service git-tag mismatch notice
  (`IPC_IGNORE_VERSION=1` already covers this, same as every other player launch).
- Teardown via `./jack-in-wayland.sh down` succeeded (`rc=0`); the usual 10s SIGTERM→SIGKILL
  escalation on monado-service happened, same as documented pre-existing behavior for this
  script, not something this change introduced.
- No stray processes or IPC socket left behind afterward (`pgrep`/socket check both clean).

**Visual sanity check, without a wearer:** hello_xr running via the DRM-lease `wayland-direct`
backend has no desktop-visible companion/mirror window to screenshot (confirmed: the
dashboard's own window-capture heuristic, pointed at the session during this test, picked up
the Steam client instead — there was nothing else mapped for it to find). So orientation/scale
was instead sanity-checked the way this doc's own "concrete first step" suggested: pulling the
actual `camera0.pgm` frame captured mid-test (same file, same instant the player was reading
it) and looking at it directly. Right-side-up, correctly proportioned, fisheye vignetting and
sensor grain exactly matching the earlier "Live capture" section's findings — not upside down,
not mirrored, not corrupted, not absurdly zoomed. Since the code path is a byte-for-byte copy
with no transform of its own, and the flat/mono render path itself is unmodified, proven-good
code already used by ordinary 2D clips, this is good evidence the quad shown in the headset
would present the same way — but it is evidence about the *source frame*, not a direct look at
the *compositor's output*.

### What this headless test can and cannot tell us

**Can confirm:** the pipeline runs end to end (file recognized, opened, staged, rendered for
the full duration); the compositor is receiving and (per the mtime-driven queue logic)
updating frames, not stuck on one static image; no crash under a real 25s run; the source
frame orientation/scale is sane.

**Cannot confirm without a wearer:** whether the result is actually *usable* for orientation —
comfort, perceived latency, whether the ~1fps update rate (see below) reads as "a slow but
workable aid" or "distractingly stale," none of that is measurable from outside the headset.
**This was a headless sanity check, not a validation of the feature's actual purpose.**

### Known limitation carried forward, not yet addressed

The camera dump (`wmr_camera.c`'s `WMR_CAMERA_SNAPSHOT_THROTTLE`, a compile-time constant of
30) is throttled to **~1fps**, tuned for the web dashboard's live tracking-camera card, not for
this. `PollCameraLoop`'s own poll cadence (33ms, ~30Hz) is deliberately faster and decoupled
from that throttle, so a future faster dump is picked up with no code change here — but as it
stands today, the actual update rate a wearer would see is ~1fps against the panel's 90Hz.
Whether that's "good enough to see where the table is" (this doc's own bar, set in the
original "Realistic expectations" section above) or too slow to be useful is exactly the
question a worn test needs to answer, not something to guess at from a log file.

### Concrete next step

A real worn test. What to check, specifically:

- **Does it help at all for orientation** — can the wearer tell which way they're facing and
  roughly what's in front of them, or is monochrome+fisheye+~1fps too degraded to read?
- **Latency/staleness feel** — does the ~1fps cadence read as usable, or does head movement
  outpacing the feed feel disorienting/nauseating (this is exactly the kind of thing this
  project's own rule holds a human verdict as decisive on, not an agent's guess)?
- If ~1fps reads as clearly too slow: raising `WMR_CAMERA_SNAPSHOT_THROTTLE` (or making it an
  env-configurable value instead of a compile-time constant) is the next lever, cross-checked
  against the dashboard feature it was originally tuned for so raising it doesn't regress that.

## Booth dead-time audit: bounding the black/blank window between demo content (2026-09-05)

Operator's ask, direct quote: "para la demo tendria que siempre haber video directamente en
lugar de fondo negro... como hacemos para acotar la ventana del tiempo muerto entre renders?"
— for the booth, there should always be live video visible instead of black, and we should
bound the dead-time window between renders. This section traces where black/blank actually
happens, with real measured numbers, not estimates.

### 1. Cold-start latency, measured live (today's `passthrough-fast` cycle, 15:36-15:37)

Chained from real timestamps captured during today's own passthrough test cycle (no synthetic
benchmark):

- **Pre-monado phase** (already measured/documented, T050 in `docs/22`, not re-derived here):
  `panel.py activate` -> DP connector actually flips to `connected` in ~0.5s on 3 clean
  back-to-back runs, or ~6s right after a prior failed attempt. `jack-in-wayland.sh` also pays
  a fixed `WMR_DISPLAY_INIT_SLEEP_SECONDS=2` wait here.
- **`monado-service` start -> "Socket ready"**: `jack-in-wayland.prev.log`'s mtime (the log
  rotation happens right as the new `monado-service` process starts) reads
  `2026-09-05 15:36:31.623`; `/tmp/jackin-passthrough-fast.log`'s mtime (its last line is
  "Socket ready") reads `2026-09-05 15:36:45.675`. **Measured: 14.05s**, covering DRM lease
  grant, `wayland-direct` compositor backend init, 4320x2160@90Hz mode set, and idle-blank
  suppression, attempt 1/3 (no retries needed this run).
- **App-side, once monado/lease is already warm**: `ps -o lstart` for the live `hello_xr`
  process (pid 405854) reports exec at `15:37:34`; its own first OpenXR log line
  (`xrCreateInstance`) is stamped `15:37:35.053` (~1.0s — dynamic linking + Vulkan instance
  creation); the full `XR_SESSION_STATE` chain IDLE->READY->SYNCHRONIZED->VISIBLE->FOCUSED
  completes at `15:37:35.359`, i.e. **~305ms** after instance creation. So once monado/the
  lease are already up, an app reaches FOCUSED/visible in **~1.3s from process launch** — this
  leg is not the problem.
- **Realistic scripted cold total** (no human gap): ~2s (fixed sleep) + ~0.5-6s (DP flip) +
  14.05s (measured compositor/lease pipeline) + ~1.3s (app to FOCUSED) **≈ 18-24s** from
  `jack-in-wayland.sh up` to first real pixel, dominated by the 14s compositor/lease step.
- Caveat: today's actual manual test had a 49s *human* gap between "Socket ready" and the
  `hello_xr` launch (operator typing the launch command by hand) — not a system number, but it
  flags that whoever/whatever triggers the app matters: `vr-launcher.py` launching immediately
  removes this gap for real demo titles.

### 2. Teardown/relaunch transitions — the actually dangerous gap

This is where the booth risk concentrates, not cold start:

- Already confirmed live minutes before this investigation: a `-t 300` client timeout expiring
  mid-wear with no new client immediately taking the lease leaves the panel
  **backlight-on-but-blank** — `docs/22`'s step-0 discriminator describes exactly this state
  ("the panel auto-powers-off if no real video signal follows fast enough" after a logo flash),
  not a hardware fault.
- `docs/22` (2026-09-05 night entry) and `docs/102` both independently document that Monado's
  compositor does **not** automatically re-offer a dropped/withdrawn DP lease to a new client —
  recovery needs an explicit `monado-service` kill + `rm` the IPC socket + fresh `up`, i.e. the
  full ~18-24s cold pipeline from item 1 again.
- `docs/102` also measured the teardown side: `jack-in-wayland.sh down` needed the SIGKILL
  escalation ("still running after 10s, escalating to SIGKILL") whenever a real OpenXR client
  was still attached — confirmed as normal behavior in that doc, independent of the specific
  relaunch-race bug it was chasing.
- Net: a full `down`->`up` title switch, worst *normal* case, costs **~10s (teardown SIGKILL
  wait) + ~18-24s (fresh compositor/lease) ≈ 28-34s** of blank/backlight-only panel. And if
  nobody notices, it is **unbounded, not just slow** — `docs/22` documents this exact
  stale-lease state persisting until an operator manually intervenes.
- Read `~/vr/vr-launcher.py`: it brings up Monado via `jack-in-wayland.sh` then routes to
  whichever demo title was selected. There is currently **no fallback/always-on layer** in that
  routing — a title's exit (clean or timeout) just ends the session and leaves whatever state
  teardown left the panel in.

### 3. The passthrough viewer's own black margins (v0, `-p flat -w 100`)

Real geometry, not a visual guess:

- `projection360.cpp`'s Flat-mode math: `halfFovX = tan(SCREEN_FOV/2)`,
  `halfFovY = halfFovX / perEyeAspect`, where `perEyeAspect` is the *camera frame's own* aspect
  ratio (640x480 = 1.333). With `SCREEN_FOV=100`: horizontal fill = 100°, vertical fill =
  `2*atan(tan(50deg)/1.333)` ≈ **83.6°**.
- Real physical per-eye FOV, logged live by `wmr_hmd_create` this session (radians converted):
  eye0 ≈ 93.2°H x 92.7°V, eye1 ≈ 93.3°H x 92.7°V.
- Net: horizontally the flat quad (100°) already meets/slightly exceeds the physical FOV
  (93.2-93.3°) — **no black margin left/right**. Vertically it under-fills: 83.6° vs ~92.7°
  physical, leaving **~9° total (~4.5° top + ~4.5° bottom, ~10% of the vertical field) as
  black letterbox bars**.
- Camera calibration (fx≈270.8, image width 640, from `camera-calibration.json`) implies the
  real fisheye lens's own native horizontal FOV ≈ `2*atan(320/270.8)` ≈ **99.5°** — i.e. the
  current `w=100` setting is already an honest, non-stretched match to the real lens; the
  vertical letterbox exists because the source is 4:3 and the headset's per-eye field is
  closer to 1:1, not because of an arbitrary choice.
- Pushing to a full dome (`HalfEquirect180`/`Equirect360`) would stretch the real ~93-100°
  image by roughly **1.8-2x** to cover 180-360° — a real, flagged accuracy tradeoff (the room
  would appear roughly twice as wide as it actually is), **not recommended** for this use case.
- Cheaper option: raising `HELLO_XR_SCREEN_FOV` to ~108-110° would close the vertical
  letterbox at a much smaller ~9-11% linear stretch (109/99.5) beyond the lens's own native
  FOV, with horizontal already tolerating a similar small overfill today. One-line env change,
  worth doing, but secondary to item 2 below — it doesn't touch the actual dead-time window.

### 4. Other black sources checked (not re-litigating the open bugs, just relevance)

- **GNOME desktop idle-blank** (`idle-delay=60s`): this is the desktop monitor, not the HMD
  panel. Correctly suppressed on `up` ("Idle-blank suppressed for this session.") and restored
  on `down` ("Idle-blank restored (60s)."), both confirmed live today in
  `/tmp/jackin-passthrough-fast.log` and `/tmp/jackin-down.log`. Not a wearer-facing risk.
- **`presence.conf` / `PRESENCE_ENABLE`**: currently `0` deliberately (`docs/98`/`101`/`103`'s
  restore bug is unresolved, confirmed broken 0-for-2 as of 2026-09-05 night). While `0` it
  cannot blank the panel during wear. Flag for the booth specifically: re-enabling it before
  that restore bug is fixed would add a **second, independent** black-during-wear mechanism on
  top of whatever teardown gap remains from item 2 — worth keeping `PRESENCE_ENABLE=0` for the
  booth on its own merits, regardless of when the general fix lands.

### Recommendation, ranked

1. **(Primary)** Give `vr-launcher.py` an always-on fallback: the instant a demo title's
   OpenXR client exits (clean or timeout), immediately relaunch the v0 passthrough viewer
   (`hello_xr` + `camera0.pgm`, `HELLO_XR_FIXED_POSE=1`) as the default "between things" layer,
   instead of leaving the panel on whatever state teardown left it in. This converts today's
   actual failure mode — an *unbounded*, operator-dependent black window — into a *bounded*
   ~28-34s worst-case relaunch (measured in item 2), with nothing left to chance.
2. **(Follow-on, bigger win)** Investigate whether Monado's compositor can hand the DRM lease
   to a second client without a full `monado-service` kill+restart. Today it demonstrably
   cannot (`docs/22`'s stale-lease finding), which is why every title switch pays the full
   ~18-24s cold-compositor cost on top of the ~10s teardown wait. If that's fixable, the
   fallback's own relaunch gap would drop from ~28-34s toward the ~1.3s app-level number from
   item 1 — worth scoping as a separate Monado-level change, not blocking on it for now.
3. **(Cheap, secondary)** Bump `HELLO_XR_SCREEN_FOV` from 100 to ~108-110 to remove the ~10%
   vertical letterbox, at a modest additional ~9% linear stretch beyond the lens's own native
   FOV. Does not touch the dead-time problem, just tightens the passthrough's own coverage. Do
   **not** move to a 180°/360° dome mode for this camera — that would roughly double the
   apparent size of everything in view.
4. Keep `PRESENCE_ENABLE=0` for the booth explicitly until the restore bug (`docs/98`/`101`/
   `103`) is fixed — re-enabling it early would add a second black-during-wear mechanism on top
   of whatever the fallback above still leaves unbounded.
