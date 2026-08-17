# UI/visualization + optimization harvest from the Windows WMR stack

A **living** harvest doc: as we cross-reference the decompiled Windows stack
(`~/Documents/wmr-ghidra/decompiled/` native, `~/Documents/wmr-oasis-mixedreality/
dotnet-decompiled/` managed — both out of git, NDA), we mine two extra veins beyond
protocol/tracking: **(1) UI/visualization patterns** (for the 360 player, a future
calibrator, in-headset settings/overlays) and **(2) optimization shortcuts**. Cross-ref
agents should append findings here. Describe behavior/patterns, not raw code.

## 1. UI / visualization

### 1a. Typed settings model + controls (the calibrator/settings UI toolkit)
- `SettingsModel.dll` (see `07-calibrator-and-settings.md` §D): typed settings — `Bool/Float/Int/Option` — each
  with `MinValue/MaxValue/StepAmount/KeptDecimalPlaces/DefaultValue/CurrentValue` and an
  `ArrowDirection` (`StepDirection`) hint; grouped by `CategoryType`; persisted via
  `ISettingStorage`; reactive (`INotifyPropertyChanged`); XML schema.
- `SettingsControls.dll` (WPF): the matching widgets — a **`Stepper`** control with a
  `StepDirection` dependency property (default `UpDown`), a **`ToggleSwitch`**, a
  `HideableLabel`, and value converters (Boolean→Visibility, Division/Multiplication for
  scaled displays, DefaultValueBold to highlight non-default values).
- **Takeaway**: a float tunable renders as a Stepper (min/max/step + arrow hint), a bool as
  a ToggleSwitch, an enum as an option list. The `ArrowDirection`/`Stepper` pair is the
  ready-made shape for the **guided-IPD "keep turning →/←" UX** (`07-calibrator-and-settings.md` §C).

### 1b. Interactive 2D UI as a VR overlay (player HUD, in-headset menus/calibrator)
- `OpenVROverlay.WPF.dll` → `OpenVRDashboardOverlay`: the full recipe to put an interactive
  2D UI into VR. Render a WPF visual to a `RenderTargetBitmap` → copy into a **staging
  `Texture2D` → output `Texture2D` (D3D11)** → `OpenVR.Overlay.SetOverlayTexture`;
  `SetOverlayWidthInMeters(3)`; a **dedicated render thread** (`RenderProc`); redraw is
  **event-driven** (poll `PollNextOverlayEvent`, redraw on change/visible only).
- Interaction: `OverlayInteractionHandler` + `OverlayHitTester` map controller-ray/laser
  events (`VREvent_MouseButtonDown/Up`, mouse-move) to WPF hit-testing
  (`VisualTreeHelper` filter/result callbacks) → real clickable UI from a laser pointer.
- **Monado/OpenXR analog**: a quad/composition layer with a rendered texture + a
  controller-ray intersection test. This is the blueprint for the player's on-screen
  bars/menus (today hand-placed, `docs/02`) and a future in-headset settings/calibrator.

### 1c. Hand/controller presence
- `ControllerHandPresence.dll` (native, 1081 funcs) — how Windows models controller/hand
  presence/visualization. Mine for the player/menus if we render controllers.

## 2. Optimization shortcuts

- **Compute-once cached scale, no per-sample work** — the HUP↔QPC time conversion caches a
  single scale factor forever (validity = infinite), vs Monado re-fitting an offset every
  IMU sample (`02-clock-model.md`). Both a correctness win (pops) and a cost win.
- **Event-driven overlay redraw + double-buffered staging texture + dedicated thread**
  (1b) — render UI only on change/visibility, not per frame; keep the compositor thread free.
- **Explicit exposure/gain + IMU throttle** — Windows sets camera exposure/gain rather than
  churning an adaptive loop, and throttles the IMU when idle ("Could not set IMU throttle
  state", `05-timesync-keepalive-imu.md`) → power + CPU. Relevant since raw tracking CPU is the current ceiling
  (SLAM ~2 + constellation ~2 cores, per project-g2-controller-6dof).
- **SLAM efficiency to mine (now decompiled)** — the `HeTCore.MRSensorFusion.*` set is
  Windows' SLAM: `Relocalizer`, `KeyframeCreator`, `Bundler` (bundle adjustment),
  `FrontEndController`/`BackEndController`, and `MRSensorFusionHetDefaultTopology` (the
  pipeline graph config, only 31 funcs — reads like a wiring manifest). Compare keyframe
  selection / BA scheduling / relocalization against Basalt for CPU-reduction ideas and to
  understand the head-tracking quality baseline. `SpatialStore.dll` + `PassthroughSource.dll`
  = spatial anchors/persistence.

## Decompiled inventory (all local, NDA, out of git)
Native (`~/Documents/wmr-ghidra/decompiled/`, 25 files, 77 MB): controller/tunnel/IMU
(`MotionControllerSystem/Hid`, `MRUSBHost`, `TrackableDeviceHid`, `MROemFwHost`,
`MRSensorFusion`), SLAM (`HeadTrackerMR`, `HeTCore.*`, `HoloLensSensors`, `CalibrationApi`,
`AMCCore`, `PassthroughSource`, `SpatialStore`), integration (`driver_oasis`,
`driver_Holographic`, `Microsoft.MixedReality.Input`, `ControllerHandPresence`).
Managed (`~/Documents/wmr-oasis-mixedreality/dotnet-decompiled/`, via ILSpy):
`SettingsModel.cs`, `SettingsControls.cs`, `OpenVROverlay.WPF.cs`, `OpenVRManaged.cs`.
Not yet done (managed, low priority): `OpenVRSettingsUX.resources.dll` (localized strings).
