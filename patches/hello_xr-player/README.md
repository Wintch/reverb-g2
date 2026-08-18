# hello_xr player & controller-gizmo patches

`hello_xr` (OpenXR-SDK-Source, local branch `g2-360-viewer`) is this project's own OpenXR
test client, extended into a real 360/VR180 player and, more recently, a live display-
diagnostics and controller-visualization tool. Base: **OpenXR SDK 1.1.62**
(`c610211f38f4e1e4ac811ced6135e144eedc7cf2`, the SHA `bootstrap-lab.sh sources` pins).
Apply with `git am` — but read the numbering-collision box below first; applying this
directory's `*.patch` glob in plain lexical order is not the right build order.

## This directory holds TWO separate patch tracks that share numbers 0004-0006

The display-diagnostics + controller-gizmo track (2026-08-17, T206/T207,
`docs/45-display-artifact-diagnosis.md`) was briefly vendored as 0004-0006, COLLIDING with
the original 360-viewer track's own 0004-0006 (0001-0016, 2026-08-04 through 2026-08-11) —
caught by this documentation pass and **resolved the same day by renumbering the new track
to 0017-0019**. The numbering is now strictly sequential, so a plain lexical shell glob
(what `scripts/bootstrap-lab.sh`'s `OpenXR-SDK-Source am .../hello_xr-player/*.patch` does)
produces the correct order again: the full 360-viewer track first (0001-0016), then the
gizmo/diagnostics track on top (0017-0019) — which is also the required semantic order,
since the gizmo track was written against a tree that already had 0016's three-axis gizmo
in it (0018's own diff modifies the gizmo-drawing code 0016 introduces).

**A second, independent gap, found by comparing the patches' own diff headers** (their
`index <blob>..<blob>` lines are content-addressed and don't require cloning upstream to
compare): 0016 (the last 360-viewer patch) leaves `openxr_program.cpp` at blob `85accae`,
but `0018-hello_xr-solid-per-axis-RGB-colors-on-the-controller.patch`'s own diff expects
that file to start from blob `ba6b781` — a blob that doesn't appear anywhere else in this
directory's patch chain. Something touched `openxr_program.cpp` between 0016 and the gizmo
track that isn't captured as an exported patch here. This is the same "known sync gap"
failure class `patches/monado/README.md` documents for its own 0016/0017 — **applying the
full 0001-0016 + 0017/0018/0019-hello_xr sequence in the right macro order is NOT yet
confirmed to `git am` cleanly end to end**, only individually self-consistent within each
track. Treat this directory the way that one is treated: don't hand-apply intent onto a
drifted tree, re-export from a clean checkout before trusting a from-scratch build.

## 0001-0016 — the 360/VR180 player

Full detail on every one of these lives in `docs/02-player-360.md`, the player's living
reference (pipeline, projections, controls, measurement) — this table is a pointer, not a
duplicate.

| patch | what |
|---|---|
| 0001 | The player's foundation: 360 equirect photo/video skybox viewer with NVDEC decode. |
| 0002 | Decoder writes straight into GPU memory; VR180/flat/stereo projection support. |
| 0003 | Directory playlists, transport keys, full-rate 8K60 decode. |
| 0004 | Seek and progress bar, controller-driven. |
| 0005 | Trigger pause, grip recenter, hold-to-quit. |
| 0006 | Frame-by-frame step (arrow keys, `<`/`>` fallback). |
| 0007 | Digital zoom (controller thumbstick Y, keyboard fallback). |
| 0008 | Fixes a loop-restart pacing bug (`loopOffset` overflow). |
| 0009 | Brightness control (Touch controller A/B). |
| 0010 | Overlay bars: reposition, fake stereo depth. |
| 0011 | Next track on the controller (Touch Y, left hand). |
| 0012 | Previous track, controller-driven quits. |
| 0013 | Coalesces rapid next/prev presses into one track change. |
| 0014 | Logs head and both controller poses once a second. |
| 0015 | Draws a cube at each tracked pose again (debug visualization). |
| 0016 | Draws a three-axis gizmo per controller instead of a plain cube — the base 0018-hello_xr (below) then fixes the coloring on. |

## 0004-0006 (second series) — the T206 display-artifact diagnostic + controller-gizmo track (2026-08-17)

Written the same night as `docs/45-display-artifact-diagnosis.md` and the controller-
orientation saga (`patches/monado/0061-0068`, `docs/03-controllers.md`'s 2026-08-17
section) — the labeled-motion-capture method that cracked the left-controller sign flip
(monado 0062) depended on the gizmo actually rendering correctly, which it didn't until
0005 below.

| patch | what |
|---|---|
| `0017-hello_xr-display-test-pattern-modes-toggle-card-coun.patch` | `HELLO_XR_TEST_PATTERN` — three env-selected synthetic display-diagnostic render modes, built for `docs/45`'s protocol after the wearer named a "late color fill-in" artifact that numbers alone couldn't pin down (T206: "cuando ya se dibujo todo... ahi llega un update que termina de rellenar los colores solidos"). **Toggle**: full-field color flips at a known frame cadence — zero geometry, zero motion, so reprojection/tracking are physically ruled out as the cause of anything seen in this mode; includes a documented slow gray-to-gray transition pair for the known GtG-response case. **Card**: a world-locked sharp-edge card, separating edge arrival from color-fill arrival in time. **Counter**: a head-locked binary frame counter plus RGB phase, built for 240fps camera-through-lens counting. Push-constant budget was already at Vulkan's 128-byte minimum, so the three modes reuse dead slots rather than growing the layout (`fovTangents` becomes `tintColor` after the mode's early return; the counter packs into `mode.x`'s high bits). Unset (default): byte-identical rendering to before this patch. **Not yet verified in-headset** — this project's own rule is that verification is physical, and nobody has put the headset on with any of these three modes running yet. See `docs/45-display-artifact-diagnosis.md`. Commit `d388b9264`. |
| `0018-hello_xr-solid-per-axis-RGB-colors-on-the-controller.patch` | Fixes a bug in the visualization tool 0016 (360-viewer track) had just built, found while trying to use it: the controller pose gizmo already drew three elongated bars, but all three reused the ordinary per-FACE-colored cube mesh — stretched into bars, the long side faces showed OTHER axes' colors, so every bar read as a multicolor smear. Part of T206's own "the cross is one thing, the rotation axes another" confusion during the labeled-capture method (monado 0062) was this visualization lying to the wearer's eyes, not the tracking. Bars are now centered on the pose (the +/- split is real geometry, unchanged) and colored procedurally in the vertex shader instead of per-face: X=red, Y=green, Z=blue, negative half dimmed to 0.25x brightness so direction reads at a glance — every face on a bar now agrees. Ordinary cubes (`GizmoAxis=-1`, the default) are bit-for-bit untouched. Wearer-confirmed: "colores solidos" — the fix that made the labeled-capture method (monado 0062/0063) usable at all. Commit `3cc2ff7af`. |
| `0019-hello_xr-solid-color-caps-on-the-positive-tip-of-eac.patch` | Wearer request made mid-debugging (T206): an asymmetric end marker per axis bar — a red cap on +X, green on +Y, blue on +Z, nothing on the negative ends — so handedness reads at a glance and a displaced rotation pivot becomes visually obvious (the caps move rigidly with their bar). Tip cubes reuse 0005's hue path via a new code range (`GizmoAxis = axis + 3`) but skip the local-position sign test that splits a bar into a bright/dim half — a tip cube tagged with the bar's own code would itself render half bright/half dim, since that test works in local-frame space, not world placement. Commit `b1e97f6b2`. |

**Not yet built or hardware-verified as of this writing** — the same session moved on to
the controller-orientation fixes these tools enabled (`patches/monado/0062` onward) using a
live lab binary; whether the test-pattern modes (0017-hello_xr) themselves have been put on
the headset is tracked separately in `docs/45`, currently still "protocol designed, not run
yet" as of T206.
