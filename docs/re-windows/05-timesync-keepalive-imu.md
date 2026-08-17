# 16 — Timesync / keepalive / IMU-robustness cross-reference (2026-08-17)

Follow-up to `01-ghidra-firstpass.md` and `02-clock-model.md`.
Cross-references the Windows WMR controller/HMD driver stack (decompiled,
NDA, out of git at `~/Documents/wmr-ghidra/`) against Monado's
`src/xrt/drivers/wmr/` for two open issues: the USB2-hub-reset/keepalive
suspicion in `docs/06`, and the companion-storm/IMU-freeze bug audited in
`docs/10`. Behavior only — no raw decompiled blocks beyond a couple of
one-line log-format strings already safe to quote.

Sources: `MotionControllerHid.dll` (controller HID API, "CrystalKey"),
`MotionControllerSystem.dll` (host orchestration, "the brain"), `MRUSBHost.dll`
(HMD-side USB/IMU/camera host, "Oasis") — all decompiled + Ghidra
`DefinedStrings` reports under `~/Documents/wmr-ghidra/`. Monado:
`wmr_hmd.c`, `wmr_controller_base.c`, `wmr_bt_controller.c`.

## 1. Timesync

**Windows.** There are two distinct mechanisms, easy to conflate:

- `crystalkeytimesync.cpp` (evidenced by exports `CrystalKeyGetTimesync` /
  `CrystalKeySetOpticalTimesync` and strings `HidOpticalTimesyncAligned`,
  `HidOpticalTimesyncMisalignment`, `HidTimesyncOffsetNs`,
  `HidTimesyncOffsetAccuracyNs` ×3, `HidTimesyncSampleStored`,
  `HidTimesyncBoundsMisalignment`) is the **controller-HID-clock ↔
  optical/camera-clock** correlation — exactly the clock pairing behind the
  constellation-tracker timestamp problem in `02-clock-model.md`
  (`project_g2_controller_6dof`'s Vector D "position pops").
- The **`MRSensorFusion.dll` HUP↔QPC** pairing documented in `02-clock-model.md` is a
  *different* clock pair (device sensor-fusion pipe time ↔ host QPC) and
  behaves oppositely: pure fixed-frequency scale, **zero offset, no resync**.
  Do not generalize that "no offset" conclusion to the optical/controller
  pairing below — the two mechanisms are unrelated.

`CrystalKeyGetTimesync` itself (`MotionControllerHid.dll @0x18000dc40`) is a
critical-section-guarded **read of a cached offset**, not a synchronous
device query — it just returns whatever the last update stored. Decompiled
`MotionControllerSystem.dll` (the host orchestration layer, line ~108756)
shows where that cache gets fed: inside the **per-optical-frame** handler
(the same function that logs `"Unknown frame type was given to Optical
Sync"`), i.e. it runs once per incoming constellation/tracking frame, not on
a fixed timer:

1. `CrystalKeyGetTimesync(controller, 0)` — read the current cached
   controller→host offset.
2. A bounds check against a threshold (`param_1[0x32]*3/2`) — if the delta
   between candidate offsets is too large, it logs `"LKG time sync
   transformation is not usable."` (LKG = Last Known Good) and **keeps the
   previous value** instead of adopting the new one.
3. If a valid optical solve completes, `CrystalKeySetOpticalTimesync
   (controller, new_offset_hi, new_offset_lo)` pushes the freshly computed
   correlation back into the driver, logged on failure as
   `"m_ramp->SetOpticalControllerToHostTimesync() failed, err=%x"`.

So Windows maintains a **live offset + accuracy estimate**, refreshed once
per successful optical/constellation solve, with an explicit outlier guard
(reject-and-keep-last-good, not adopt-and-smooth). This is a materially
different design from a single fixed offset or a smoothed running average.

Separately, the per-device output-report telemetry struct
(`MotionControllerDeviceOutputReportStats[Verbose]`) tracks independent
Success/Failure counters for `TimesyncReport` alongside `LedPulseTrainReport`,
`CmdReport`, `UpdaterReport`, and generic `OutputReport`, plus an
`OutputReportSuccessRetryCountMean` — confirming Timesync is sent to the
controller as its own retried output-report type, not merely queried.

**Monado.** `grep -r timesync src/xrt/drivers/wmr/` returns nothing —
Monado does no explicit host↔controller or controller↔camera timesync
exchange at all. It relies entirely on device-reported per-sample tick
timestamps for *within-packet* relative ordering (`gyro_timestamp[i]` ×
`WMR_MS_HOLOLENS_NS_PER_TICK`) and host arrival time as the timebase anchor
(`wh->fusion.last_imu_timestamp_ns = os_monotonic_get_ns()`, `wmr_hmd.c:428,
476`). For the constellation-tracking clock domain specifically, `wmr_source.c`
uses `m_clock_offset_a2b`: a single scalar offset with exponential smoothing
— no accuracy/uncertainty term, no alignment/misalignment state, no
outlier/bounds guard (per `02-clock-model.md`).

**Recommendation.** This sharpens `02-clock-model.md`'s fix direction concretely: don't
just fit a better fixed offset — replicate the *shape* of
`crystalkeytimesync.cpp`'s model. Add an outlier guard around
`m_clock_offset_a2b` updates in `wmr_source.c` that rejects an incoming
sample when it deviates from the current offset by more than a threshold
(mirroring the "LKG… not usable" reject-and-keep-last-good behavior), instead
of blindly folding every sample into the exponential smoother. That is a
Monado-side implementation task and doesn't require further RE — the
mechanism is now clear enough to design from.

## 2. Keepalive

**Windows — controller side.** `CrystalKeyKeepAlive`
(`MotionControllerHid.dll @0x18000e140`) is a **dead stub**: it unconditionally
logs an error (`crystalkeyhid.cpp` line 0x706) and returns
`0x80070078` (`ERROR_CALL_NOT_IMPLEMENTED`) without ever touching the device.
`KeepAlive` has **zero** matches anywhere in the 6.8 MB decompiled
`MotionControllerSystem.dll` (the host orchestration layer) either. The
per-report-type output-stats struct enumerates exactly five tracked report
types — generic `Output`, `Timesync`, `LedPulseTrain`, `Cmd`, `Updater` —
with no sixth "keepalive" counter. **In this driver generation, Windows does
not send a discrete keepalive HID packet to the controller.** Its aliveness
is an emergent property of continuous LED-pulse-train + timesync + generic
command traffic, each independently retried, not a dedicated ping.

**Windows — HMD companion side (the actual hub-reset suspect).**
`docs/06`'s hypothesis is about the HMD's own companion/control HID device
(`03f0:0580`), tunneled through the same USB2 hub — that's `MRUSBHost.dll`
(Oasis) territory, not `MotionControllerHid.dll` (CrystalKey/controller)
territory. `MRUSBHost.dll` has **zero** case-insensitive matches for
`keepalive` or `throttle` anywhere in either its decompiled `.c` or its
`DefinedStrings` report. This is a soft negative, not a confirmed absence:
the decompiled `.c` for this DLL only reaches address `~0x18001915` out of
328 functions before truncating (see caveat), well short of most of the
address range this cross-reference cares about, so a keepalive mechanism
could still exist further in.

**Monado.** No `keepalive` string anywhere in `src/xrt/drivers/wmr/`.
`control_read_packets()` (`wmr_hmd.c:614`, the companion/HMD-control read
path) only ever calls `os_hid_read` — it never writes to the device in
steady state. The only writes to the companion/HMD device anywhere in the
file are one-shot: `screen_on`/`screen_off` (`wmr_hmd.c:890,956`, sent once
at panel enable/disable) and the startup config read (`wmr_hmd.c:987`).
There is no periodic write of any kind keeping that channel "warm."

**Recommendation.** The evidence does not support "Windows sends a keepalive
packet Monado is missing" as literally stated — no such packet exists on the
controller side either, and the companion side is unresolved (not confirmed
absent, just not found). The more defensible read: Windows keeps the shared
USB2 hub link continuously busy via the controller's LED-pulse-train +
timesync + cmd report cadence (tunneled through the same hub as the
companion device), whereas Monado's WMR driver is comparatively silent
(passive reads only) once calibration/config are done. If the hub-reset is a
traffic-pattern issue rather than a power issue (`docs/06`'s own conclusion),
the actionable next step is not "find and replicate a keepalive packet" but
"audit whether Monado's controller output cadence (`wmr_controller_base.c`
LED-pulse-train interval) is as frequent/regular as Windows's" — that's the
one channel confirmed periodic on both sides. Re-running the `MRUSBHost.dll`
headless decompile with a longer/targeted range is the concrete next RE step
if the companion-side keepalive question needs a real answer.

## 3. IMU robustness

**Windows** — string/symbol evidence only (see caveat: mostly unreached by
the current decompile). Two cooperating mechanisms stand out by name:

1. **Rate-based staleness, not single-sample panic.** `IMUStaleDataDrop`
   (two independent call sites), `ImuStaleDataBurst`, `StaleDataHz` — pairing
   a "burst" event with an explicit "Hz" metric implies stale samples are
   tracked as a *rate over a window*, with action taken once the rate
   crosses a threshold, not on the first stale sample.
   `ImuTimeDistortionDetected` is a separate, apparently more serious event.
2. **Cross-stream supervision.** `CameraReaderLoopRestartingIMU` — the
   camera/vision reader loop can proactively restart the IMU stream, i.e.
   IMU liveness is monitored from *outside* the IMU's own reader loop and
   self-heals by reopening it (`OpenIMUStream`/`CloseIMUStream`,
   `SendImuStopRequestRetries`, `ImuInitRetries` are all present — stop-then-
   reopen is itself retried, not a single attempt). Separate named
   thread-exit events for IMU vs. generic HID comms
   (`ImuReaderLoopExit` ×2, `HidCommsThreadExit` +
   `WaitingForHidCommsThreadExit`) imply IMU, camera, and command/HID
   traffic run on **separate, independently-supervised reader threads** —
   consistent with the separately-registrable callbacks
   (`RegisterImuCallback` / `RegisterCameraCallback` /
   `RegisterCykInputReportCallback`).
3. Controller-side IMU timestamp integrity is checked explicitly too
   (`MotionControllerHid.dll`): `MotionControllerImuOutOfOrder`,
   `Timestamp will roll after IMU timestamp` /
   `Timestamp rolled before IMU timestamp` /
   `Detected IMU timestamp rollover` / `m_ImuTimestampRollOverCounter` — a
   rollover-aware timestamp state machine with a running counter, plus a
   registry-tunable `ImuRateLimit` and an exposed `ImuIsStreaming` liveness
   flag.

**Monado** (post-`657bcd8af`, per `docs/10`). A single reader thread
(`wmr_run_thread`) handles companion **and** hololens-sensors (IMU +
tunnelled controller packets) reads sequentially in one loop; per-controller
Bluetooth reads are a separate thread. Health handling:

- Companion: consecutive-error counter, never gives up, backs off to ~100 Hz
  retry past 50 failures (`wmr_hmd.c:642-655`).
- Hololens sensors (IMU + controller tunnel): consecutive-error counter,
  **gives up and kills the whole HMD read thread at 10 failures**
  (`wmr_hmd.c:527-533`), flat 10 ms sleep on failure — no rate/window
  concept.
- BT controller: same 10-strikes-then-give-up pattern in its own thread.

No rate-based staleness classification (single consecutive-count threshold
only). No IMU timestamp rollover detection. No cross-stream restart —
nothing external watches the hololens_sensors (IMU) stream and restarts it;
if it dies, the one shared thread just exits, taking companion reads *and*
the controller USB tunnel down with it, since they share the same loop and
the same failure budget. There is no Monado equivalent of "camera loop
notices IMU died and restarts just the IMU," because Monado has no separate
camera-adjacent reader loop to do the noticing from.

**Recommendation.** The most substantive gap found in this cross-reference.
Two scoped follow-ups, ordered by effort:

1. **Cheap, high value.** Replace the hololens_sensors "die at 10 consecutive
   failures" policy (`wmr_hmd.c:527-533`) with a rate-based window (e.g.
   failures/second over a rolling interval) instead of a raw consecutive
   count — mirrors `IMUStaleDataDrop`/`StaleDataHz`. This would let a brief
   burst during panel power-up or a hub hiccup survive without killing
   tracking, while a genuinely sustained dropout still triggers give-up.
2. **Architectural, larger.** Monado's single combined reader thread has no
   analogue to "camera loop restarts IMU" — a real design gap, not a bug fix.
   Worth flagging for `project_g2_controller_6dof`: it's the reason a wedged
   IMU currently takes controller tracking down with it (same device, same
   thread, same failure counter), where Windows's per-stream thread
   separation specifically avoids that coupling.
3. **IMU timestamp rollover.** Not checked in this pass — worth a quick grep
   of whether `WMR_MS_HOLOLENS_NS_PER_TICK`'s raw tick counter has any
   rollover guard in `wmr_hmd.c`. Windows dedicates a counter and two
   distinct log messages (roll-before vs. roll-after) to this, suggesting
   it's a real, previously-hit condition on this hardware family rather than
   theoretical.

## Caveat: both DLL decompiles are truncated

Despite the "Full decompilation of X.dll" banner, `MRUSBHost.dll.all.c` and
`MotionControllerHid.dll.all.c` only emit C up to roughly address
`0x18001915` (MRUSBHost, ~217/328 functions) and `0x18002fb6`
(MotionControllerHid) respectively — well short of where the IMU-lifecycle
strings (`0x1a800+`) and the timesync/output-report-stats strings (`0x3a000+`)
actually live. Everything in sections 1–3 about those specific mechanisms is
therefore **string/symbol-level evidence from the Ghidra `DefinedStrings`
report and cross-DLL call sites in `MotionControllerSystem.dll`**, not
verified decompiled control flow for the IMU-loop internals. It is internally
consistent and specific enough to act on (see recommendations above), but
should be treated as a strong, well-corroborated hypothesis rather than a
confirmed protocol description.

Concrete next RE step if this needs firming up: re-run the headless batch
(`WmrFirstPass.java`, `01-ghidra-firstpass.md`) targeting just
`crystalkeytimesync.cpp`'s call site (`~0x18001ed2c` in
`MotionControllerHid.dll`) and the IMU/camera reader loops in
`MRUSBHost.dll` (`~0x18001b000`-`0x18001e000`), with a longer per-function
timeout instead of a whole-DLL dump.
