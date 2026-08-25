# Windows vs. Monado constellation-LED model — cross-reference (2026-08-17)

Follow-up to `01-ghidra-firstpass.md` (LED constellation model /
`TrackableDeviceHid.dll` section, and the `CrystalKeySetLedPulseTrain` item
under "what to decompile next"). This pass decompiles both symbols and
cross-references against Monado's `src/xrt/drivers/wmr/` and
`src/xrt/tracking/constellation/`.

Sources: `MotionControllerHid.dll.all.c` and `TrackableDeviceHid.dll.all.c`
decompiled (`~/Documents/wmr-ghidra/decompiled/`, out-of-git/NDA). Only
behavior, formulas, and named constants are recorded here — no raw
decompiled code blocks beyond the few one-liners already safe to quote
(debug source paths, HID API calls).

## 1. Windows LED geometry — `TrackableDeviceGetLedPlacements` / `GetLedModes`

Both are thin wrappers (`TrackableDeviceHid.dll`, offsets `0x77b0`/`0x7840`)
around an internal device object. They expose **two separate, independently
sized pieces of data**:

- **`GetLedModes`** returns a single byte read from a fixed struct offset
  (`+0x98`) on the device object — an LED-mode count/bitmask, not
  per-LED. Monado has no equivalent concept at all (see §4).
- **`GetLedPlacements`** returns an array the caller sizes/copies: element
  stride is fixed at **24 bytes**, count = `(end - start) / 0x18`, read from
  a `ushort` count field. 24 bytes matches a **6 × 4-byte-field record**
  (confirmed by the populate routine below striding pointers by 6 dwords per
  entry, i.e. `puVar11 = puVar11 + 6`).

The array is **not** read out of a static blob at a fixed offset. It is
populated by a call whose signature is unambiguous because it takes a
Windows *HID parser* API by literal argument, not a wrapped one:

```
HidP_GetUsageValueArray(2 /*Feature*/, 8 /*UsagePage*/, LinkCollection, 0x58 /*Usage*/,
                         dst, count*0x18, PreparsedData, Report, ReportLength)
```

**Usage Page `0x08` is the standard USB-HID "LEDs and Indicators" page.**
So on Windows, LED geometry is pulled live out of the connected device's own
HID **Feature Report**, addressed through the standard HID usage-value
mechanism (self-describing via the report descriptor), not decoded from a
private binary blob. This is a genuinely different data source than the
"factory calibration blob" (`CrystalKeyGetCalibrationBlob`, §3) — Windows
apparently carries the same LED geometry in two places: a HID-descriptor
usage-page-8 array (`TrackableDeviceHid.dll`, live device query) and inside
the JSON calibration blob (`MotionControllerHid.dll`, the one Monado
reverse-engineered — see §2).

Each 24-byte / 6-field record has no field-name strings anywhere in the
binary (no `"Normal"`/`"Position"` strings found), so the **position+normal**
interpretation below is inferred structurally, not read off a string — but
it is a strong inference: it is exactly the record shape (3 floats + 3
floats) Monado's own independently reverse-engineered JSON schema uses for
the same object (§2), and "per-LED position + outward normal" is the
textbook constellation-LED model (used the same way by Rift CV1/DK2 and
PSVR). Confidence: high on record size and Position/Normal semantics via
cross-correspondence, medium on exact field order/units (not independently
verified byte-for-byte against a captured sample in this pass).

Coordinate frame / units were not independently pinned in this pass (no
raw floats were captured); Monado's parser (§2) treats them as meters in
the controller's local calibration frame, consistent with how the values
are consumed geometrically (LED radius and camera-facing dot products all
assume metric world units).

## 2. Monado's LED model — `wmr_config.c` / `wmr_controller_base.c`

Monado parses the JSON calibration blob under `CalibrationInformation ->
ControllerLeds` (an array), one entry per LED, each with a `"Position"` and
a `"Normal"` field (3-float arrays):

```c
// src/xrt/drivers/wmr/wmr_config.h
struct wmr_led_config { struct xrt_vec3 pos; struct xrt_vec3 norm; };
// WMR_MAX_LEDS 40; wmr_controller_config.led_count / .leds[]
```

Parsing: `wmr_controller_led_config_parse()` in `wmr_config.c:467-493`,
called from `wmr_controller_config_parse()` (`wmr_config.c:569-590`), which
errors out if `ControllerLeds` isn't found/an array. This structurally
matches §1's inferred pos+normal record exactly (3+3 floats), just sourced
from JSON text instead of a live HID Feature Report.

These get copied 1:1 into the constellation tracker's LED model in
`wmr_controller_base_add_to_constellation_tracker()`
(`wmr_controller_base.c:1190-1239`):

```c
wcb->constellation.leds[i] = (struct t_constellation_tracker_led){
    .position = wcb->config.leds[i].pos,
    .normal   = wcb->config.leds[i].norm,
    .radius_m = WMR_CONSTELLATION_LED_RADIUS_M,          // 0.003f, hardcoded
    .visibility_angle = WMR_CONSTELLATION_LED_VISIBILITY_ANGLE, // 75 deg, hardcoded
    .id = i,
};
```

`radius_m` and `visibility_angle` are **not** in the 24-byte Windows record
either (that record is 6 floats = pos+normal only, no size/cone field
visible) — so this isn't a case of Monado dropping Windows-provided data,
it's Monado supplying its own constant where Windows likely instead relies
on measured photometric brightness (blob size/intensity) rather than a
fixed geometric cone. Worth flagging as a modeling difference but not a
"missing field" bug.

Per-controller LED count on the G2 is 32 (confirmed elsewhere in the
project — `wmr_controller_base.c:1008` comment: "5-6 blobs matched out of
32 LEDs"), well under `WMR_MAX_LEDS=40`.

The LED-model ↔ IMU-fusion frame bridge (`Rx180`, y/z flip) was determined
empirically by Monado (Wahba solve on paired rotations, `T181`,
2026-08-13) — not read out of Windows source in this pass; `01-ghidra-firstpass.md`
flagged it as "the missing piece," and `wmr_controller_base.c:1013-1051`
documents it as measured, not reverse-engineered from Windows.

**Verdict: geometry matches structurally (position + normal, 3+3 floats,
same 32-LED count).** Units/frame convention were independently validated
by Monado's own measurement, not derived from the Windows binary, so this
is corroboration rather than newly transferred information.

## 3. Windows `CrystalKeySetLedPulseTrain` — pulse-train command

`MotionControllerHid.dll`, offset `0xcdd0`. Source paths embedded in the
debug strings (`analog\oasis\crystalkey\hid\crystalkeyhid.cpp` /
`crystalkeydevice.cpp`) confirm this is genuine, unobfuscated debug info —
high confidence in the structure below.

```
CrystalKeySetLedPulseTrain(handle, param_2:u64, param_3:u32, param_4:u32,
                            param_5:i32, param_6:u32*, param_7, param_8)
```

`CrystalKeySetLedPulseTrain` itself is a thin validating wrapper; the real
work (validation + packing) is in an internal helper (`crystalkeydevice.cpp`,
`SetLedPulseTrain`-equivalent, decompiled at `18001c294`):

- **`param_3`** — pulse **count**, validated `1 ≤ param_3 ≤ 399`. Packed
  into a **9-bit** field.
- **`param_5`** — **mode**, valid values `{1,2,3,4}`. Packed into the
  report; when `mode ∈ {1,2}` a custom period is honored, when
  `mode ∈ {3,4}` the period is forced to a default.
- **`param_4`** (only used/validated when `mode ∈ {1,2}`) — a **period**
  value in the Windows API, range **1000–5000 (µs, i.e. 1–5 ms)**, must be
  even (`(period-1000) & 1 == 0`). Stored as `(period-1000)/2`, an
  **11-bit** field — i.e. steps of 2 µs across a 4 ms window. When
  `mode ∈ {3,4}` this is forced to 1000 µs (1 ms) regardless of the caller's
  input.
- **`param_2`** — a 64-bit **duration** value, range-checked to be under
  ~2^55 via a standard compiler magic-number division (consistent with a
  unit conversion, e.g. a finer input tick converted to the report's native
  unit — the exact divisor/units were not pinned in this pass). Packed as a
  **55-bit** field, the dominant payload of the report.
- **`param_6`** (out) — receives a **rotating 2-bit sequence/request ID**
  (cycles 1→2→3→1…, 0 skipped), stored alongside the pending-request state.
  This ID round-trips into the packed report too, so the device can
  correlate/ack a specific pulse-train update.
- **`param_7`/`param_8`** — stashed as an 8+8-byte pair on the device
  object (offsets `+0x3a0`/`+0x3a8`); shape matches an
  async-completion callback + context (consistent with `01-ghidra-firstpass.md`'s "led
  pulse train updated event" / "led not controllable event" strings).

**Delivery is asynchronous**: the setter just validates, packs fields into
device-object state, sets a dirty flag (`+0x36c = 1`), and signals a
`SetEvent()` to wake a worker thread. That worker thread (separately
decompiled, `~18001d...`) is what actually serializes the packed fields
into an **11-byte HID report body** (sequence ID · count · duration in the
low/high halves, mode · period in the remaining bits) and writes it out —
gated by a `HidP`-style overlapped I/O sequence with its own `ResetEvent`
pair, i.e. a normal async HID output-report write, not a per-frame/per-blob
call. This is a **connection/mode-setup command**, issued when the blink
pattern needs to change (e.g. tracking start/stop, or a period retune) —
not something re-sent every camera frame.

Net effect: **Windows can explicitly command the controller's blink
pattern** — pulse count, pulse duration, and a 1–5 ms adjustable period —
through a real, gated (device confirms via event) command channel. This is
architecturally the same shape as CV1/PSVR-style "LED sync" protocols: a
count + duration + period, tunable to line up with camera exposure timing.

### CONFIRMED LIVE ON THE WIRE, 2026-08-25

This static-decompile prediction was verified against a real Windows USBPcap capture
(`windows-kit2/results/frametype-capture-20260825.pcapng`, 730s, real Cyberpilot session,
both controllers on) -- the command is genuinely sent, and its wire shape matches this
section's prediction closely enough to confirm it, not just correlate with it:

- **Report ID `0x08`** for one controller, **`0x10`** for the other (the two controller
  instances mirror every report ID with a fixed `+8` offset) -- `SET_REPORT`, Output type,
  `wLength=12` (1 report-ID byte + the predicted 11-byte body), sent to `045e:0659` (the
  same HID tunnel that carries the controllers' own `0x06`/`0x0E` motion reports).
- The HID Report Descriptor itself (read live from the capture) declares report `0x08`'s
  Output collection as exactly **88 bits = 11 bytes** -- the only report ID on the device
  with that shape.
- Content match: bits[8:9] cycle **1→2→3→1→2→3...**, never 0, across 5,124/5,379 occurrences
  (the doc's "rotating 2-bit sequence ID, 0 skipped"); bits[10:18] (9 bits) land in **[1,399]**
  for 100% of samples, hitting the doc's declared boundary exactly (max observed: 399).
- Timing match: each controller's first `0x08`/`0x10` write lands ~2-3s after that
  controller's own motion-report stream begins (tracking start), and its last write
  coincides almost to the frame with that stream's last packet (tracking stop) -- exactly
  the "sent once when the blink pattern needs to change" delivery model this section
  predicted from the decompile, not a per-frame command.
- Both controllers get an **identical first command** at connection (`06 21 03
  00 00 00 00 00 00 80 2c`: seq=1, count=200, mode_raw=0, period=1000µs) before diverging.

**Still open after this pass** (flagged honestly, not guessed further): an unexplained
leading byte before the modeled seq/count/mode/period/duration fields (the doc's own field
list only accounts for 79 of the body's 88 bits); `period_raw` was observed spanning its
full range under every `mode_raw` value rather than being gated to two of four as the
API-level description implies; the 55-bit `duration` field's ~10^16 magnitude doesn't
cleanly read as milliseconds or correlate with capture-relative time (a masked/truncated
high-res absolute timestamp is a plausible guess, unverified); and which of `0x08`/`0x10`
is left vs. right was not determined (no per-hand labeling event in this capture).

**Not yet done**: porting this to `wmr` (`t_led_sync_refinement` per this file's own §5
plan) -- deliberately not attempted from this analysis pass alone given the open questions
above, especially the unexplained leading byte and unverified duration units. Replicating a
still-partially-understood command to real hardware needs those closed first, or at minimum
an explicit, deliberate decision to try it anyway with the risk named.

## 4. Monado's LED control on WMR — none

Grepping `src/xrt/drivers/wmr/` for `pulse`, `blink`, `strobe`: **zero
hits.** The only bytes Monado ever writes to a WMR controller are:

```c
// src/xrt/drivers/wmr/wmr_controller_base.c:950-953 (fixed 64-byte reports, report ID 0x06)
const unsigned char wmr_controller_status_enable_cmd[64] = {0x06, 0x03, 0x01, 0x00, 0x02};
const unsigned char wmr_controller_imu_on_cmd[64]        = {0x06, 0x03, 0x02, 0xe1, 0x02};
```

...plus haptic-vibration output reports (`XRT_OUTPUT_NAME_G2_CONTROLLER_HAPTIC`
etc., `wmr_controller_hp.c`/`wmr_controller_og.c`). No LED-mode, no
pulse-train, nothing on the LED usage page. **Monado's WMR controllers run
on whatever blink pattern the firmware defaults to on connect/power-on**,
with no explicit request for a specific count/duration/period and no
attempt to synchronize the blink to camera exposure.

This is not a gap unique to WMR in the codebase, though — Monado **already
has the generic machinery** for exactly this, just wired to a different
controller family:

```
src/xrt/tracking/constellation/t_led_sync_refinement.{h,c}
```

`t_led_sync_refinement` models blink `duration_ns`, a `latency offset`
search, and edge-alignment ("align blink rising edge with exposure falling
edge" / vice versa) against camera exposure timing — i.e. the same
count/duration/period concept as `CrystalKeySetLedPulseTrain`, generalized.
It is used by exactly one driver:

```c
// src/xrt/drivers/pssense/pssense_driver.c
next_blink_time = ...;                      // scheduled against camera exposure
next_blink_time += timing_fudge_100us ...;  // fudge to center blink in exposure
.led_blink = {0xFF, 0xFF, 0xFF, 0xFF}        // output report field actually sent
```

So the WMR driver is the outlier: the constellation-tracking infrastructure
it feeds (`t_constellation_tracker.cpp`) is shared with `pssense`, but only
`pssense` drives its controller's LEDs; WMR only *reads* whatever the
controller is already doing.

## 5. Gap list — things Windows does that Monado doesn't

1. **Explicit pulse-train command.** Windows sends a validated, gated
   (async-acked) command specifying pulse count (1–399), duration, and a
   1–5 ms period, via `CrystalKeySetLedPulseTrain`. Monado never issues any
   LED command to a WMR controller — it only sends a fixed "status enable"
   and "IMU on" report at connect.
2. **Exposure-synchronized blinking.** Windows' pulse-train mechanism is
   the natural place to line the blink window up with camera exposure
   (same shape as Monado's own `t_led_sync_refinement`, which exists in
   this repo but is wired only to `pssense`, not `wmr`). WMR blob detection
   currently has no equivalent — it detects whatever the controller
   free-runs at.
3. **Live LED-placement query via HID usage page 0x08.** Windows can pull
   LED geometry directly from the connected device's HID Feature Report
   (`TrackableDeviceGetLedPlacements`), independent of the factory
   calibration blob. Monado only has the JSON-blob source; if that blob is
   ever missing/stale/wrong for a given firmware revision, Monado has no
   fallback live-query path.
4. **A separate `GetLedModes` concept.** Windows models an LED "modes"
   byte distinct from placements; Monado has no equivalent field or
   concept at all.
5. **Per-request correlation ID.** Windows' pulse-train setter returns a
   rotating request ID so the caller can track which pulse-train update
   the device actually applied/acked. Not applicable to Monado since it
   never issues the command in the first place, but relevant if a WMR
   pulse-train implementation is ever added — the device-side protocol
   expects this ID round-tripped.

## 6. What this doesn't establish

- Byte-exact values for the packed pulse-train report (report ID, exact
  bit offsets within the 11-byte body) were not pinned — the packing
  routine was read at the field/bit-width level (9-bit count, 11-bit
  period, 55-bit duration, 2-bit sequence ID), not captured against a real
  USB trace.
- Whether firing an equivalent pulse-train report at a WMR controller from
  Linux would actually change its blink behavior (vs. being ignored/NAKed
  by firmware) is unverified — this pass is static analysis only, nothing
  was tried against real hardware.
- The Windows HID-usage-page-8 LED placement path (§1) and the JSON
  calibration-blob LED array (§2/§3's sibling data) were not cross-checked
  against each other for exact numeric agreement (no raw sample captured
  from either in this pass) — that they describe "the same 32 LEDs" is an
  inference from matching record shape and count context, not a byte diff.

## Bottom line

Geometry (position + normal, 32 LEDs) cross-checks structurally clean —
Monado's independently-reconstructed JSON schema matches the shape Windows
reads live off the HID LED usage page. The real, actionable gap is
behavioral: **Windows explicitly programs the controller's blink
count/duration/period and Monado does not touch it at all**, despite
already having the generic exposure-sync machinery (`t_led_sync_refinement`)
built and proven on `pssense`. Porting that machinery to WMR — using the
`CrystalKeySetLedPulseTrain` field layout above as the target report shape
— is the concrete next step if constellation blob detection/tracking
quality needs improving.
