# hello_xr player and controller-gizmo patches

`hello_xr` (OpenXR-SDK-Source, local branch `g2-360-viewer`) is extended here into a 360/VR180
player and a small display-diagnostics and controller-visualisation tool. Base: OpenXR SDK 1.1.62
(`c610211f38f4e1e4ac811ced6135e144eedc7cf2`). All 25 patches apply in order
(`applies-on-base.txt`, applied and built by `bootstrap-lab.sh`). The player's pipeline,
projections, controls and measurements are in `docs/02-player-360.md`; this file is only an index.

The series was re-exported on 2026-10-12 (`docs/147`): earlier exports mixed English and Spanish
help text, so some pre-images no longer matched. The final tree builds
(`ninja hello_xr`, FFmpeg and Pulse enabled).

## The player (0001-0016)

| # | What |
|---|---|
| 0001 | 360 equirect photo/video skybox viewer with NVDEC decode |
| 0002 | Decoder writes straight into GPU memory; VR180, flat and stereo projections |
| 0003 | Directory playlists, transport keys, full-rate 8K60 decode |
| 0004 | Seek and progress bar, controller-driven |
| 0005 | Trigger pause, grip recenter, hold-to-quit |
| 0006 | Frame-by-frame step |
| 0007 | Digital zoom (thumbstick Y, keyboard fallback) |
| 0008 | Fixes a loop-restart pacing bug (`loopOffset` overflow) |
| 0009 | Brightness control |
| 0010 | Overlay bars: reposition, fake stereo depth |
| 0011-0013 | Next and previous track on the controller; quits; rapid presses coalesced |
| 0014 | Head and controller poses logged once a second |
| 0015-0016 | Pose visualisation: a cube, then a three-axis gizmo per controller |

## Diagnostics and later features (0017-0025)

| # | What |
|---|---|
| 0017 | `HELLO_XR_TEST_PATTERN`: synthetic display-diagnostic modes (toggle, card, counter) for `docs/45`. Default rendering is byte-identical. The protocol has not yet been validated in a headset |
| 0018 | Solid per-axis colours on the gizmo bars (X red, Y green, Z blue, negative half dimmed) |
| 0019 | Coloured caps on the positive tip of each axis bar |
| 0020 | `HELLO_XR_DURATION_S`: internal timed run with a clean `END_SESSION` (0 = run forever). Note `scripts/play360.sh` separately wraps the player in `timeout` (default 300 s, `-t` to change) |
| 0021 | `HELLO_XR_AUDIO=1`: stereo audio through PipeWire's `pa_simple`, synced to video |
| 0022 | Xbox 360 gamepad fallback for pause, recenter, next, previous and quit |
| 0023 | Fixes the recenter sign (it doubled the head yaw instead of cancelling it) |
| 0024 | Seeks and frame steps work while paused, land on the requested frame, report position in file time |
| 0025 | Clock handed back to the wall clock when the audio ends (a non-looping file with audio used to freeze, and a playlist never advanced) |

0023-0025 are fixes from the 2026-10-12 review. They passed worn tests on 2026-10-13
(seek, frame step, recenter, audio hand-back, playlist; `docs/147`).

## Traps

- The player exits with status 0 and no error if its stdin is at EOF (`< /dev/null`). Launch it
  as `sleep N | hello_xr ...`. `monado-service` needs the opposite, `XRT_NO_STDIN=1`.
- If the default 360 photo cannot be opened the XR session dies and the compositor keeps
  presenting black. Set `HELLO_XR_PHOTO360` to an existing file.
