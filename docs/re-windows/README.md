# Windows WMR ↔ Monado reverse-engineering cross-reference

Behavioral findings from reverse-engineering the official Windows WMR driver stack
(HP Reverb G2), cross-referenced against Monado's `src/xrt/drivers/wmr/` and the
constellation/SLAM code, to guide fixes for the open tracking bugs.

## Important: NDA / what is and isn't in this repo

These docs describe **behavior, APIs, field layouts, formulas, and design patterns
only** — they are safe to publish and to use when contributing upstream. The **raw
decompiled code stays off git entirely**, on the comms box only (extracted from a
local Windows install, Ghidra 12.1.2 + ILSpy). Do not commit or circulate the
decompiled binaries or decompiler output. Line-number references (e.g. "line 836")
point at those local artifacts and won't resolve on dev.

Decompiled scope (local, comms box): the full `hololenssensors.inf` driver stack
(controller/tunnel/IMU, `MotionController*`, `MRUSBHost`, `TrackableDeviceHid`,
`MROemFwHost`, `MRSensorFusion`), the Windows SLAM stack (`HeadTrackerMR`,
`HeTCore.MRSensorFusion.*`, `HoloLensSensors`, `CalibrationApi`), the integration
layer (`driver_oasis`, `driver_Holographic`, `Microsoft.MixedReality.Input`,
`ControllerHandPresence`), and the managed settings/UI (`SettingsModel`,
`SettingsControls`, `OpenVROverlay.WPF`).

## Index

| Doc | What |
|---|---|
| `00-decompilation-method.md` | Tooling, extraction, target inventory, method (reproduce) |
| `01-ghidra-firstpass.md` | First-pass triage: exports/strings per DLL, codenames (CrystalKey/Oasis/Hatchet), the HUP↔QPC discovery |
| `02-clock-model.md` | **HUP↔QPC time model vs Monado's `hw2mono` — the pops** |
| `03-controller-packets.md` | Controller tunnel packet layout vs `wmr_controller_protocol` (the **3-axis mag bug**) |
| `04-led-model.md` | LED geometry match + the LED **pulse-train** gap |
| `05-timesync-keepalive-imu.md` | Optical timesync (LKG guard), keepalive myth, IMU robustness |
| `06-synthesis.md` | **Prioritized action list** — read this to decide what to implement |
| `07-calibrator-and-settings.md` | Calibrator + settings + **user profiles** design (IPD-guided UX) |
| `08-ui-optimization-harvest.md` | UI patterns (VR overlay recipe, typed settings) + optimization shortcuts |

## Top actionable findings (see `06-synthesis.md` for the full list)

1. **Position pops** — Monado re-fits a clock offset from noisy arrival timestamps
   every IMU sample (250 Hz, offset-only EMA); Windows uses a fixed frequency-ratio
   with no per-sample re-fit, and its *optical* timesync rejects unusable updates
   (last-known-good) instead of smoothing them in. Two converging fixes in
   `wmr_source.c` (`02-clock-model.md` + `05-timesync-keepalive-imu.md`).
2. **Magnetometer decode bug** — Monado guesses a single 16-bit "probably mag"
   field; Windows decodes a real **3-axis** mag vector. The triplet is in Monado's
   undecoded trailing bytes (`03-controller-packets.md`).
3. **Keepalive myth busted** — Windows sends no discrete controller keepalive; the
   USB2-hub-reset is a traffic-density difference, not a missing packet
   (`05-timesync-keepalive-imu.md`, correction to `docs/06`).
4. **LED pulse train** — Windows drives a pulse train; Monado sends no LED commands.
   Blueprint already in-tree (`t_led_sync_refinement`, wired only to `pssense`).

## Relevance to the active SLAM pose-rate collapse (T192–T195)

The newly-caught SLAM collapse (healthy ~17 Hz → abrupt permanent ~1.5 Hz, near-
constant ~632–648 ms interval; reproduces in <1 s with SLAM+constellation; ruled out
as a scheduler problem → "a lock/queue/timeout in code") lines up with several
threads here: a near-constant interval reads like a **fixed timeout firing
repeatedly**, and the timestamp/clock handling (`02`), the IMU-stream staleness /
cross-stream-restart differences (`05`), and the Basalt queue behavior are the first
places to look. See `../re-windows/WORKPLAN.md`.
