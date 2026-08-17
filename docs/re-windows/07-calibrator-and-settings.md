# Calibrator + Settings system — design sketch (parked, to explore later)

Vision (user, 2026-08-17): a **real calibrator** and a **real settings/preferences
system** so the rig can actually be tuned, instead of the scattered `WMR_*` env
vars we set by hand today. Everything settable should have a named variable and
live in a persistent config, with a calibration flow that produces the values.

Not being built yet — this is the scope + candidate variables to return to. Many
of these map directly to APIs the Windows RE surfaced (see `01-ghidra-firstpass.md`–`05-timesync-keepalive-imu.md`):
Windows exposes LED modes, timesync, and the calibration blob as clean calls.

## A. Calibrator (produces values, ideally from guided procedures)

| What | Procedure | Produces / variable |
|---|---|---|
| **Height / floor** | Place a controller flat on the floor, hold; measure player standing height (pending procedure from project-g2-controller-6dof, "es importante!") | `floor_offset_m`, `player_height_m` |
| **Gyro bias** | Joy at rest ~2–5 min (constant zero) | `gyro_bias[3]` per controller |
| **Gyro scale** | Joy on the turntable at constant ω (known rate) | `gyro_scale[3]` |
| **IMU↔LED frame bridge** | Factory calibration blob (`CrystalKeyGetCalibrationBlob`) + the Rx180 flip already found; allow override | `imu_to_led_rot` (Rx180 default) |
| **Camera↔IMU time** | The clock model fix (`02-clock-model.md`) — fit skew+offset once, stably | `clock_skew`, `clock_offset`, `clock_fit_tau` |
| **Joy jitter (blobs)** | False blobs near bright lights (T150) | `blob_pixel_threshold`, `blob_required_threshold` |
| **Scale/floor sanity** | Move a real object exactly 1 m, compare reported displacement | (validation, not a stored value) |

## B. Settings / preferences (persistent, tunable)

Grouped, with the env var we use today where one exists → target config key.

**Display**
- 60↔90 Hz switch — `XRT_COMPOSITOR_DESIRED_MODE` → `refresh_hz` (60|90). Physical
  verification required (panel on), per `CLAUDE.md`.
- Reprojection / pacing — `U_PACING_APP_PIPELINED`, `VK_KHR_present_wait` feedback
  (from the judder work) → `pacing_mode`, `reprojection` on/off.

**Tracking**
- `WMR_CONSTELLATION_CONTROLLERS` → `controllers_6dof` (on/off; off lowers CPU-spin risk)
- `WMR_CONSTELLATION_GRAVITY_GATE_DEG` (default 14) → `gravity_gate_deg`
- `WMR_CAMERAS` → `tracking_cameras` (on/off)
- One-euro filter (orientation): mincutoff, beta, prediction horizon → `oneeuro_mincutoff`, `oneeuro_beta`, `predict_ms`
- Camera exposure/gain (per the controller-blob fix, 6000/100 on this unit) → `cam_exposure`, `cam_gain`

**Controllers / input**
- Stick deadzone — `WMR_STICK_DEADZONE` → `stick_deadzone`
- **Button/stick remap** → `button_map` (per-controller action map), `stick_invert`, `stick_curve`
- Squeeze/trigger thresholds → `trigger_threshold`, `squeeze_threshold`

**Auto-shutoff / power**
- Controller standby timeout (LEDs blink/dim when idle — kills blob detection) →
  `controller_standby_s`; whether to keep-alive to prevent it (`CrystalKeyKeepAlive`,
  see `05-timesync-keepalive-imu.md`) → `controller_keepalive` on/off
- IMU idle throttle (Windows has one: "Could not set IMU throttle state") → `imu_throttle`
- Panel/display power-off preference → `panel_autooff_s`

**Diagnostics / logging** (already env vars)
- `CONSTELLATION_TRACKER_LOG`, `WMR_LOG`, `WMR_CONTROLLER_CALIBRATION_LOG`,
  `HELLO_XR_POSE_STATS` → `log_*` toggles

## C. User profiles (multi-user) — REQUIRED

The calibrator must be **profile-based** (one named profile per person). We didn't
have a formal profiles doc, but the two key per-user mechanisms were already worked
out and just need to be wrapped in a profile:

**Per-USER values (keyed to the person):**
- **Height / floor** — the real mechanism is already documented (lab `NEXT-STEP.md`,
  "Floor/height calibration"): Monado has no floor calibration; the WMR driver
  doesn't set `supported.stage`, so `LOCAL_FLOOR == root` and the floor is *assumed*
  1.6 m below the headset at startup (`1.6` hardcoded in `target_builder_helpers.c`).
  The only knob is `XRT_TRACKING_ORIGIN_OFFSET_Y = (headset height at startup) − 1.6`.
  It can be trimmed **live** via `XRT_DEBUG_GUI=1` → the "Pose Offset" field
  (`wh->offset`) before being fixed. → profile key `player_height_m` → computed
  offset applied at `monado-service` start (must be at that height on start, root is
  pinned there).
- **IPD** — the headset reports the **physical** IPD slider position over the
  companion channel: `WMR_CONTROL_MSG_IPD_VALUE` (0x01) → `wh->raw_ipd`
  (`wmr_hmd.c:control_ipd_value_decode`, `wmr_hmd.h:raw_ipd`). IPD is inherently
  per-user; a profile stores the expected value. → `ipd_mm`.
  - **Guided IPD calibration UX (user idea, 2026-08-17):** once a profile's IPD is
    set well ONCE, the calibrator remembers it and actively guides the person back to
    it — read the live `raw_ipd` off the companion channel and show "keep turning the
    slider →/←" with the direction and remaining delta, stopping when it matches the
    stored value. Turns re-fitting the headset per person into a guided step instead of
    a guess. Needs the companion channel healthy (it's the same channel the T188
    storm/fix touches — see project-g2-controller-6dof).
- Comfort/filter prefs, button map, refresh preference (from §B) → per profile.

**Device-level values (shared across users, keyed by CONTROLLER SERIAL, not person):**
gyro bias/scale, LED model, camera exposure — keyed by serial (left `A85K...`,
right `a85k...`). A profile references these; it doesn't own them.

**Switching:** select profile → apply the per-user values; device calibration is
auto-selected by connected serial. **Watch the recenter↔height conflict** (T080):
recenter via `reset_tracking_space(Standing)` clobbers the height calibration — a
profile system must re-apply the height offset after a recenter, or recenter only
X/Z+yaw and preserve Y.

## D. Architecture notes (for later)

**Reference blueprint — Microsoft's own WMR `SettingsModel.dll`** (decompiled to C#
via ILSpy, `~/Documents/wmr-oasis-mixedreality/dotnet-decompiled/SettingsModel.cs`,
NDA/local). It's a clean, proven typed-settings model we can mirror:
- A `SettingType` base (`INotifyPropertyChanged`) with typed subclasses:
  `BoolSettingType`, `FloatSettingType`, `IntSettingType`, `OptionSettingType`
  (+ `OptionSettingItemType` for enum choices).
- `FloatSettingType` carries exactly the fields a tunable needs: `MinValue`,
  `MaxValue`, `StepAmount`, `KeptDecimalPlaces`, `DefaultValue`, `CurrentValue`
  (read/written through storage), and **`ArrowDirection` (enum `StepDirection`)** —
  i.e. Microsoft already models the "which way to nudge" hint. **This is the direct
  analog of the guided-IPD UX above** ("keep turning →/←"): every stepping setting
  can carry its own direction hint.
- `CategoryType` groups settings; `ISettingStorage` abstracts persistence;
  `SettingsManager.InitFromXml`/`InitFromCode` load a schema; changes are reactive
  (`SettingChangedEventArgs` + `INotifyPropertyChanged`). Schema is XML-serialized.

Takeaway for our system: model each tunable in §B as a typed setting with
min/max/step/default (+ arrow hint where guided), grouped by category, behind a
storage interface, with per-profile overrides layered on top (§C). We don't need to
invent the shape — this is a validated one to borrow.

### Original architecture notes

- Persist to a config file (TOML/JSON) under the user's config dir; env vars remain
  an override layer for quick experiments.
- Per-controller calibration keyed by serial (left `A85K...`, right `a85k...`).
- The calibrator should reuse the headless/telemetry verification approach already
  proven (debug-GUI / `get_tracked_pose` log), not require a visual scene.
- Cross-check each stored value against what Windows computes for the same device
  (the decompiled `CrystalKey*`/`TrackableDevice*`/`Hatchet*` APIs) as ground truth.

## Status

Parked 2026-08-17 — explore after the current Windows cross-reference lands
(`02-clock-model.md`–`05-timesync-keepalive-imu.md`). Related: project-g2-controller-6dof (calibration/pops),
project-vr-rig-plan (rig goals).
