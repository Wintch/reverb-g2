# 08 — Passthrough and play-area limits (idea, not started)

**Status: noted on 2026-08-04. Nothing implemented.** Don't touch until 90Hz is closed out (ch. 04).

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
