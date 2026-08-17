# WMR driver Ghidra first-pass — findings (2026-08-16)

Headless triage (Ghidra 12.1.2) of the WMR sensor/controller driver DLLs
extracted from the Windows install (`hololenssensors.inf` DriverStore package).
Project: `~/Documents/wmr-ghidra/` (out of git — NDA). Reports:
`~/Documents/wmr-ghidra/reports/*.report.txt`. This file describes *behavior and
API surface* only (safe to share/contribute upstream) — not decompiled code.

Only export/function/string names are recorded here; these map the Windows stack
onto Monado's `src/xrt/drivers/wmr/` so we know what "correct" looks like.

## Codenames (important for reading everything else)

- **CrystalKey / "Cyk"** = the WMR **motion controller**. Its HID API lives in
  `MotionControllerHid.dll`; the host/brain in `MotionControllerSystem.dll`
  (`CrystalKeyHostCreate/Destroy`, 4743 functions, COM-style).
- **Oasis** = Microsoft's internal codename for the headset IMU/sensor path
  (seen in `MRUSBHost.dll` strings; mbucchia's "Oasis Driver" borrows the name).
- **Hatchet / "HUP"** = the sensor-fusion transport (`MRSensorFusion.dll`),
  a pipe-based device with its own time domain ("HUP time").

## Controller command surface — `MotionControllerHid.dll` (CrystalKey, 42 exports)

The whole controller control channel Monado has been reverse-engineering piecemeal
is a clean named API here:

- `CrystalKeyStartIMUStream` / `CrystalKeyStopIMUStream` — IMU stream control
- `CrystalKeySetLedPulseTrain` — **drives the controller LED blink pattern**
  (the constellation LEDs the headset cameras track). Internally gated by a
  "led pulse train updated event" and a "led not controllable event".
- `CrystalKeyGetCalibrationBlob` — the factory calibration blob (the IMU↔LED
  model bridge Monado extracts and applies the Rx180 frame flip to)
- `CrystalKeyGetTimesync` — controller/host **time synchronization**
- `CrystalKeyKeepAlive` — explicit controller **keepalive** (relevant to the
  USB2-hub-reset / HID-keepalive suspicion in `docs/06`)
- `CrystalKeySendCommand` / `CrystalKeyReadCommand` — generic command channel
- `CrystalKeyGetBluetoothAddress`, `...GetDeviceStatus`,
  `...RegisterForDeviceStateChange`, `...ReadFirmwareVersion`
- string signals: `Could not set IMU throttle state`, `IdledOut`

## USB tunnel / IMU host — `MRUSBHost.dll` (35 exports)

This is the headset-side USB host that **tunnels the controller** and carries
the IMU/camera — i.e. Monado's companion/hololens-sensors read path and the
"tunnelled controller packets":

- `MrUsbDevice_CykGetFeatureReport` / `CykSetFeatureReport` / `CykSetOutputReport`
  — **the controller (Cyk) tunneled through the HMD's USB** via HID reports
- `MrUsbDevice_RegisterCykInputReportCallback` / `RegisterCykEventsCallback`
  — inbound controller report + event delivery
- `MrUsbDevice_RegisterImuCallback` / `RegisterCameraCallback` — IMU/camera streams
- `MrUsbDevice_RegisterBtPairingEventCallback` — BT pairing events
- `MrUsbDevice_ReadCalibration` / `ReadCalibrationHeader` — headset calibration
- `MrUsbDevice_GetSensorHwInfo`, `QueryUsbSpeed`, `ResetDevice`, `EraseFlashlog`,
  `OpenForFirmwareData`, `WriteDataBlob`
- IMU lifecycle/robustness strings worth noting vs our companion-storm work:
  `Imu Init` / `Imu Stop`, `OpenIMUStream` / `CloseIMUStream`, `ImuReaderLoopExit`,
  **`IMUStaleDataDrop`** (explicit stale-sample handling), `SendImuStopRequestRetries`,
  **`CameraReaderLoopRestartingIMU`** (the camera loop can restart the IMU),
  `OasisIMUFirstFrameReceived`, `OasisIMUInvalidSentinel`

## LED constellation model — `TrackableDeviceHid.dll` (15 exports)

The controller-as-tracked-object API — exactly the LED geometry Monado rebuilt:

- `TrackableDeviceGetLedPlacements` — **the LED positions** (constellation model)
- `TrackableDeviceGetLedModes` — LED modes
- `TrackableDeviceGetCapabilities`, `GetDataInfo` / `GetDataInfoByType`

## Sensor-fusion time domain — `MRSensorFusion.dll` (Hatchet/HUP, 43 exports)

**Directly relevant to the constellation clock-domain bug** (the multi-second,
non-constant offset between tracker timestamps and Monado's `at_timestamp_ns`,
still open per project-g2-controller-6dof). Windows converts explicitly
between device "HUP" time and host "SoC QPC" time, with a validity window:

- `HatchetHupConvertTimeHupNsToSocQpc` / `HatchetHupConvertTimeSocQpcToHupNs`
- `HatchetHupConvertTimeHupTicksToSocQpc` / `...SocQpcToHupTicks`
- `HatchetHupGetConvertTimeValidityPeriod` — the conversion is only valid for a
  bounded period (implies periodic re-sync), which is likely why a naive fixed
  offset drifts in our implementation
- `HatchetHupDeviceHandshake`, pipe/completion-port plumbing

## What to decompile next (targeted, byte-level)

1. `MRUSBHost.dll`: the `Cyk*FeatureReport` / `RegisterCykInputReportCallback`
   handlers → exact controller report IDs, sizes, and field layout of the
   tunnelled controller packets (cross-ref `wmr_controller_protocol.c`).
2. `MRSensorFusion.dll`: `HatchetHupConvertTimeHupNsToSocQpc` +
   `GetConvertTimeValidityPeriod` → the real HUP↔QPC time model to fix our
   clock-domain gating (Vector D / the position pops).
3. `MotionControllerHid.dll`: `CrystalKeySetLedPulseTrain` and
   `CrystalKeyGetTimesync` → LED pulse-train format and controller timesync.
4. Second pass: the `HeTCore.MRSensorFusion.*` set (BackEnd/FrontEnd/Fuser/
   Relocalizer/KeyframeCreator) = Windows' SLAM, for head-tracking comparison.

## HUP↔QPC time conversion — decompiled behavior (2026-08-16)

Decompiled the six `HatchetHupConvertTime*` exports + `...ValidityPeriod` +
`...DeviceHandshake` (raw C kept out of git at
`~/Documents/wmr-ghidra/reports/MRSensorFusion.hup-qpc-time.c`). Behavior only:

**The conversion is a pure linear frequency-ratio SCALE, with NO additive
offset.** Each direction lazily computes one `double` scale factor (once, then
caches it in a global) and multiplies:

- `HupTicksToSocQpc`:  `qpc = hup_ticks * (qpc_freq / hup_tick_freq)`
- `HupNsToSocQpc`:     `qpc = hup_ns    * (qpc_freq / 1e9)`
- `SocQpcToHupNs`:     `hup_ns   = qpc * (1e9 / qpc_freq)`   (+ a 2^63 wrap guard)
- `SocQpcToHupTicks`:  `hup_ticks = qpc * (hup_tick_freq / qpc_freq)`

The QPC frequency is fetched once via a CFG-guarded indirect call (unresolved —
shape matches `QueryPerformanceFrequency`); the "current time" path when no input
is given calls `QueryPerformanceCounter`.

**Two decisive facts:**
1. `HatchetHupGetConvertTimeValidityPeriod` returns **0xFFFFFFFF / 0xFFFFFFFF**
   (max) for both out-params → the conversion never expires. No periodic re-sync.
2. `HatchetHupDeviceHandshake` is a **no-op stub** (`SetLastError(0); return 1;`).

**Interpretation — matters for the position pops (Vector D).** Windows treats the
device (HUP) clock and the host QPC as the **same timebase/epoch**, differing only
by tick rate. There is *no* per-sample offset and *no* running-offset estimation —
it just rescales by the fixed frequency ratio, forever.

This contradicts Monado's current model, which assumed a large, drifting
multi-second OFFSET between the constellation tracker's timestamps and
`at_timestamp_ns` (see project-g2-controller-6dof, the unresolved clock-domain
caveat). The drift we measured is therefore most likely **not** a real clock
offset needing resync, but one of: wrong frequency/units applied to the device
timestamp, referencing a host clock that isn't the device's QPC-equivalent base,
or an unhandled 64-bit timestamp wrap (Windows guards exactly one wrap in
`SocQpcToHupNs`). **Fix direction to test**: convert device timestamps to Monado's
clock with a fixed frequency ratio against a common epoch (like Windows), instead
of estimating a running `cam_hw2mono`-style offset. Cross-check against
`wmr_source.c`'s controller-tracking timestamp path.

**Next micro-target**: resolve the CFG-guarded icall and the globals
`a cached internal global` (hup tick freq), `a cached internal global` (expected 1e9), `a cached internal global`
(wrap threshold) to pin the exact constants.

## How to reproduce

`WmrFirstPass.java` (in `linux_vr_base/ghidra-scripts/`) is the postScript.
```bash
/opt/ghidra_12.1.2_PUBLIC/support/analyzeHeadless ~/Documents/wmr-ghidra WMR \
  -import <dll> ... \
  -scriptPath ~/Documents/linux_vr_base/ghidra-scripts \
  -postScript WmrFirstPass.java ~/Documents/wmr-ghidra/reports \
  -analysisTimeoutPerFile 900
```
Re-run just the report on an already-imported DLL: add `-process '<name>.dll'
-noanalysis` instead of `-import`.
