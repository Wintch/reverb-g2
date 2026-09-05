# 105 — QR/marker wall stickers: investigation

**Trigger**: operator request, zero elaboration: "add an agent to investigate sticking
printed QR codes on the walls." No stated purpose. This doc investigates what it's most
plausibly for and how feasible each plausible purpose actually is, rather than assuming one.

## Two candidate purposes considered

1. **Fiducial markers for SLAM/VIO tracking robustness** — printed ArUco/AprilTag/QR
   patterns at known fixed wall positions, used by the tracking pipeline to
   re-localize/correct pose. Motivated by this project's real, documented tracking
   problems: anchor-drift resets, VIO scale snapping while walking, yaw drift on fast
   turns (`docs/104`, `project_aircar_yaw_drift_investigation`).
2. **A physical disorientation aid for the v0 passthrough viewer** — a crisp, printed,
   recognizable planar reference taped to a real wall, to give the eye something solid to
   anchor on in an otherwise low-res/grainy/laggy monochrome camera feed. Motivated by
   today's (2026-09-05) wearer feedback that raw passthrough felt disorienting, which the
   same session addressed by building a synthetic software floor-grid overlay.

## This is not a fresh idea — it was already scoped

`docs/08-passthrough-limits.md` (written 2026-08-06, updated live today 2026-09-05)
already contains a section titled **"v2 — Boundaries via markers"**, describing this exact
idea in the operator's own words at the time: *"have the system know where the walls are.
The idea proposed was to read markers placed in the environment."* The doc calls it
*"the most realistic path... and by far the cheapest"* and explicitly endorses fiducials:
*"Fiducial markers (ArUco/AprilTag) printed and stuck on the walls: they're detected very
well with low-resolution B/W cameras, they give full pose (position + orientation) per
marker, and detection is mature, lightweight code... Your instinct to use markers is the
right shortcut."* Today's update reconfirms v2 is unaffected by everything else learned
about this rig's camera geometry: *"it never depended on the cameras forming a stereo
pair, only on detecting fiducials with whichever single camera sees them, and 6DoF (needed
to place them in world space) is no longer blocked."*

So this request reads as the operator re-surfacing an idea from a month ago, now that its
stated blocker (6DoF stability) is resolved — not a new concept. That context strongly
favors purpose 1 as the *original* intent, though purpose 2 (today's disorientation
complaint) is a plausible independent or additional motivation and is assessed on its own
merits below. Both are covered rather than picking one.

## What already exists toward each purpose

### Purpose 1 (runtime SLAM/tracking correction) — partial, calibration-only, and disabled

Grepped `~/vr/basalt` and `~/vr/monado` (case-insensitive) for `marker`, `aruco`,
`apriltag`, `fiducial`, `qr`, `tag_detect`, `aptag`:

- **Basalt does have AprilTag code**, but it lives entirely in
  `src/calibration/calibraiton_helper.cpp` (`CalibHelper::detectCorners`,
  `#include <basalt/utils/apriltag.h>`) and `include/basalt/calibration/aprilgrid.h`. This
  is **Kalibr-style camera/IMU calibration tooling**: detecting a printed AprilGrid
  calibration board to solve for camera intrinsics/extrinsics — a one-time offline
  procedure, not a runtime pose-correction feature. The function is explicitly guarded off
  in this build with the comment *"Disabled to remove apriltag dependency for faster build
  times."* The `apriltag` library is still linked into `basalt_internal`
  (`CMakeLists.txt:476`) as a build dependency, but the actual detection call path is
  compiled out. **Basalt's real-time VIO estimator (`vio.cpp`, the sqrt/landmark-block
  optimizer code) has zero fiducial-related code** — every other "marker"/"qr" hit in
  Basalt is either a Pangolin UI plot marker (`plotter->AddMarker(...)`, unrelated to
  fiducials) or an `Eigen::QR` matrix factorization (unrelated to QR codes).
- **Monado's "marker" hits are all in the vendored upstream OpenXR spec header**
  (`src/external/openxr_includes/openxr/openxr_reflection.h`) — enum/struct name
  constants for vendor extensions Monado does not implement: ML's
  `XR_ML_marker_understanding` (ArUco/AprilTag/QR/barcode marker detector API), Varjo's
  `XR_VARJO_marker_tracking`, MSFT's `XR_MSFT_scene_marker` (explicitly includes QR code
  scanning), and the multi-vendor `XR_EXT_spatial_marker_tracking`. Confirmed by grepping
  `src/xrt` (Monado's actual runtime implementation tree, not the vendored spec) for any
  of these extension/type names outside the header: **nothing**. These are dead spec
  constants pulled in because the SDK header is vendored wholesale, not evidence of any
  working feature.

**Conclusion for purpose 1: no runtime marker-based tracking correction exists anywhere in
this stack.** The only fiducial-adjacent code is Basalt's offline calibration-board
detector, a genuinely different use case (one-time intrinsics/extrinsics solve vs.
continuous runtime re-localization), and it's currently disabled in this build besides.

### Purpose 2 (physical disorientation aid) — nothing code-side exists or is needed

No code is required for this purpose by definition — it's a physical object placed in the
room, viewed through the already-built v0 passthrough viewer. Grepped
`~/Documents/reverb-g2` and `~/vr` scripts/docs for existing mentions of "QR"/"marker"
outside the two source trees above: only `docs/08`'s own v2 section (the same one covered
above), `CLAUDE.md`'s unrelated `FAIL_MARKER` file-lock concept, and `jack-in-wayland.sh`'s
same `FAIL_MARKER` mechanism (a process-hygiene sentinel file, nothing to do with visual
fiducials). No prior work toward purpose 2 specifically — the floor-grid overlay built
earlier today is a *different, software-rendered* answer to the same disorientation
complaint, not a physical-marker one.

## Feasibility, each purpose separately

- **Purpose 2 (physical disorientation aid): trivial.** Print a high-contrast pattern
  (a QR code, an ArUco tile, or even just a bold checkerboard/logo) on paper, tape it to a
  wall in the passthrough viewer's field of view, put the headset on with v0 running
  (already built and headless-tested per `docs/08`'s latest entry), and look. Zero code,
  zero integration risk, ~30 minutes including printing. This is a pure UX experiment, not
  an engineering task.
- **Purpose 1 (runtime tracking correction): real integration project, multi-day.** Would
  require: (a) re-enabling or rewriting a *live* marker detector — Basalt's disabled
  calibration-time `ApriltagDetector` is the closest starting point but was never designed
  to run per-frame in the VIO loop; (b) a live camera-frame consumption path — today the
  only camera access is the debug `wmr_camera_dump_snapshot_pgm()` one-shot dump used for
  this investigation, not a continuous low-latency sink a detector could run against every
  frame (Basalt's actual VIO frame sinks are the real integration point, and they're
  wired for feature tracking, not tag detection); (c) a decision on fusion depth — tightly
  coupling detected marker poses into Basalt's optimizer is a real SLAM-research task,
  while a shallower alternative — treat a detected marker purely as a trigger for a
  discrete pose reset/recenter, sitting outside Basalt entirely — is far more tractable
  and mirrors the pattern already proven useful here (`xrizer` 0008's worn-validated
  "Recentrar" button per project memory). Even the shallow version needs new detector code
  plus a new Monado/OpenXR-level injection point that doesn't exist today. This is not a
  paper-and-tape task; budget it as a multi-day research-and-integration effort, not a
  quick patch.

## Camera hardware sanity check

From `~/vr/camera-calibration.json` and `~/vr/camera-expgain.json`, cross-checked against
`docs/08`'s own live-frame read from earlier today:

- All 4 cameras are **640×480 monochrome**, with `fx`≈270 px and `cx`≈324 px giving a
  "linear" field of view around 100° horizontal before accounting for distortion — and
  distortion here is heavy (`k1` up to 0.93–0.99 on cam2/cam3, 0.45–0.56 on cam0/cam1),
  confirming `docs/08`'s direct observation of visible fisheye barrel curvature in the
  saved frames. Real captured FOV is wider than the linear estimate at the edges.
- Exposure/gain (`camera-expgain.json`): **6000 µs (6 ms) exposure, gain 162–215** across
  the four cameras — a short-exposure/high-gain combination typical of tracking cameras
  tuned to freeze motion in dim rooms, at the cost of sensor noise. `docs/08` independently
  confirms "heavy sensor grain in the darker regions" from the actual saved PGM frames.
  Capture is also only **~30 fps** against the panel's 90 Hz.
- **Rough resolvability estimate for a printed marker at 1–3 m**: at ~6.4 px/degree in the
  central region (640 px / ~100°), a 20 cm marker subtends ~5.7° at 2 m (~36 px across) and
  ~3.8° at 3 m (~24 px across) — both within the range standard ArUco/AprilTag detectors
  handle reliably (typical minimum is roughly 20–30 px of marker span), though 3 m+ with a
  small marker gets marginal. A larger marker (25–30 cm) or staying under ~2.5 m keeps
  comfortable margin. High sensor grain is a real but secondary risk — printed
  black/white fiducial patterns are far more noise-tolerant than the natural-scene corner
  features Basalt's VIO already tracks successfully on these same noisy sensors, so if the
  existing VIO can track a room on this hardware, a marker (much higher local contrast)
  should be easier, not harder, to detect.
- **Verdict: hardware plausibly resolves a printed marker at demo-relevant wall distances.**
  Low resolution and heavy fisheye distortion are real constraints that argue for larger
  markers and closer placement, but nothing here rules the idea out — this matches
  `docs/08`'s independent (pre-existing) claim that fiducials are "detected very well with
  low-resolution B/W cameras," which is also consistent with general AR/robotics practice
  (ArUco/AprilTag were designed for exactly this sensor class). Framerate (30 fps) is a
  non-issue for a *static* wall marker used for occasional re-localization; it would only
  matter for something needing marker pose at full render rate.
- Live verification was not performed beyond this analysis: `monado-service` is currently
  running on the rig (PID 475377, idle — no OpenXR client attached), so no test capture
  was started to avoid disturbing a live process per this investigation's read-only
  mandate. The four existing `~/vr/camera{0-3}.pgm` dumps (headset resting on the desk,
  not worn, captured 2026-09-05 ~17:15) were sufficient to reason about resolution and
  noise without any new capture.

## Recommendation

**Pursue purpose 2 first; treat purpose 1 as scoped-but-parked.**

Purpose 2 costs almost nothing (paper, tape, ~30 minutes) and directly answers a complaint
raised *today*, on the exact viewer (v0 passthrough) that complaint was about. There is no
reason not to just try it.

Purpose 1 is technically sound — `docs/08` scoped it accurately a month ago and nothing
found here contradicts that — but it is a genuine multi-day integration project with no
existing runtime code to build from (only a disabled, calibration-only detector), and the
project's current active anchor-drift mitigations (the 3 m anchor + quaternion guard,
`xrizer`'s worn-validated Recentrar button, per `docs/104` and
`project_aircar_yaw_drift_investigation`) already address the practical symptom
(anchor/session drift) more cheaply than building camera-based fiducial fusion would.
Recommend picking purpose 1 back up only if those existing mitigations prove insufficient
in ongoing booth use — not as a default next step.

**Minimal concrete next steps:**
- Purpose 2: print one marker, tape it in view of the v0 passthrough camera, wear the
  headset, and just look — no code needed.
- Purpose 1 (if ever picked up): first re-enable Basalt's existing `ApriltagDetector`
  against a live frame feed purely to *log* detected marker poses next to Basalt's own
  estimated pose during a normal walk — to measure how much a correction would actually
  help — before writing any fusion or pose-injection code.
