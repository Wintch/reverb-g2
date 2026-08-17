# Windows WMR ↔ Monado cross-reference — synthesis & action list (2026-08-17)

Consolidation of the four cross-reference passes (`02-clock-model.md`–`05-timesync-keepalive-imu.md`) done against
the decompiled Windows WMR driver stack (`~/Documents/wmr-ghidra/`, out of git, NDA).
Ordered by priority against the project goals: position pops first, then protocol
correctness/robustness, then tracking-quality opportunities. Confidence noted per item.

## P1 — Position pops (Vector D): two converging fixes in the clock path

Both land in `src/xrt/drivers/wmr/wmr_source.c` (the `m_clock_offset_a2b` call at
`:180`) and the constellation timestamp path. **High value, testable on lab.**

1. **Decouple the offset EMA update cadence from the IMU sample rate** (`02-clock-model.md`).
   Monado re-fits `hw2mono` from `os_monotonic_get_ns()` stamped at arrival, every
   sample at 250 Hz (α=0.95, offset-only, no skew) → USB/scheduling jitter leaks in
   (measured in-tree: 281 backwards-time events/session, p99 14.7 ms vs 4 ms period).
   Fix: pre-filter over a short window (~64 samples ≈ 256 ms), feed the EMA only the
   minimum-latency `(now_hw, now_mono)` pair per window; scale `IMU_FREQ` down to match.
   *Confidence: high (decompiled + in-tree measurements). A naive port of the Rift
   `m_clock_windowed_skew_tracker` was already tried and reverted — drift regressed.*
2. **Add an outlier / last-known-good (LKG) rejection guard to the offset update**
   (`05-timesync-keepalive-imu.md`). Windows' controller↔optical timesync (`crystalkeytimesync.cpp`,
   called once per optical/constellation frame) rejects an unusable timesync transform
   ("LKG time sync transformation is not usable") and keeps the last good one instead
   of adopting it. Monado smooths *every* sample with no reject path. This is the direct
   analog of the constellation timestamp path that produces the pops.
   *Confidence: medium-high (call-site traced; see truncation caveat below).*

These are complementary: (1) stops jitter leaking in continuously; (2) stops a single
bad update from poisoning the estimate.

## P2 — Controller packet protocol (`03-controller-packets.md`)

3. **Magnetometer decode is wrong** (bug). Windows decodes a **3-axis Mag** vector from
   its own HID collection. Monado has only a one-line guess ("probably mag") on a single
   16-bit field inside its 12 undecoded trailing bytes — structurally wrong (mag needs 3
   values). The real triplet is almost certainly in those unparsed bytes. Fixing it gives
   the fusion a real mag reference. *Confidence: medium-high.*
4. **Battery scale confirmed correct** — Windows `(raw*100)/255`, Monado `raw/255.0f` =
   same ratio. Just resolve the "UNVERIFIED SCALE" comment in
   `wmr_controller_hp_get_battery_status()`. *Confidence: high. Trivial.*
5. **Accel/Gyro/timestamp layout + 32-bit tick wraparound match** both sides — no change
   needed, but it validates Monado's core decode. *Confidence: high.*
6. **Architectural direction (not a quick fix)**: Windows parses the HID report descriptor
   at open time (`HidP_GetLinkCollectionNodes` → named Flags/Accel/Gyro/Mag/Blob/Battery
   collections, `HidP_GetScaledUsageValue`); Monado hardcodes a 44-byte fixed-offset
   struct. Descriptor-driven parsing would be more robust across firmware/variants.
7. **Transport gap (flagged, unproven)**: Windows uses distinct Output/Feature/GetFeature
   report paths for the tunnel; Monado only ever uses plain HID Output/Input, never
   Feature reports. Worth confirming whether any command should be a Feature report.

## P3 — IMU stream robustness (`05-timesync-keepalive-imu.md`) — relevant to companion-storm/stability

8. Windows has: **rate-based** staleness (window/`StaleDataHz`, not single-sample),
   **cross-stream self-healing** (`CameraReaderLoopRestartingIMU` — the camera loop
   restarts a wedged IMU), **separate supervised reader threads per stream**, and IMU
   **timestamp rollover detection**. Monado's single combined reader loop (companion +
   hololens-sensors) kills the whole thread at 10 failures, no rate window, no rollover,
   no cross-stream restart — a wedged IMU takes controller tracking down with it.
   Direction: split the reader threads and/or add rate-windowed staleness + rollover +
   cross-stream restart. *Confidence: medium (string/symbol-level; truncation caveat).*

## P4 — LED constellation tracking (`04-led-model.md`) — opportunity, not a bug

9. LED **geometry matches** (32 LEDs, pos+normal; Windows reads it live via HID Feature,
   Monado from the factory calibration blob). But **Windows drives a LED pulse train**
   (`CrystalKeySetLedPulseTrain`: count 1-399 / mode 1-4 / period / duration, ~11-byte
   report) and **Monado sends no LED commands at all** (only fixed activation + haptics).
   Monado already has the generic machinery (`t_led_sync_refinement.{h,c}`) wired only to
   the `pssense` driver — a concrete in-repo blueprint to add pulse-train/LED-sync to WMR,
   potentially improving blob detection and camera-exposure alignment. *Confidence: high
   that the gap exists; effect on tracking is unmeasured.*

## Corrections to prior project assumptions

- **Keepalive myth busted** (`05-timesync-keepalive-imu.md`): `CrystalKeyKeepAlive` is a dead stub
  (`ERROR_CALL_NOT_IMPLEMENTED`); Windows sends **no** discrete keepalive. `docs/06`'s
  "missing keepalive packet causes the USB2 hub reset" theory is not supported. The
  defensible read is a **traffic-density** difference (Windows keeps the hub busy with
  continuous controller output reports; Monado goes quiet after startup). Update `docs/06`.

## Caveats

- `MRUSBHost.dll.all.c` and `MotionControllerHid.dll.all.c` decompiled only ~6-10% of the
  address space (Ghidra auto-analysis didn't discover functions in much of the range), so
  the **IMU-robustness and optical-timesync findings (P1.2, P3) are strong hypotheses from
  strings/symbols + call-sites, not confirmed control flow.** Firm them up with a targeted
  re-decompile of the specific address ranges (aggressive function discovery) before
  treating them as settled.

## Recommended order to implement (all on lab-full, hardware-verified)

1. P1.1 + P1.2 together (the pops — highest goal-value, and the fix is localized).
2. P2.3 mag decode (real bug, small) + P2.4 battery comment (trivial).
3. Firm the truncation, then P3 IMU robustness.
4. P4 LED pulse train (bigger, tracking-quality upside).
