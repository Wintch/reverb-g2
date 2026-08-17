# Windows vs. Monado WMR controller (Cyk) packet — cross-reference (2026-08-17)

Follow-up to `01-ghidra-firstpass.md` ("What to decompile next", item 1).
Cross-references the reverse-engineered Windows controller tunnel/HID report
handling against Monado's `src/xrt/drivers/wmr/wmr_controller_*` parser, to see
whether Monado's empirically-derived 44-byte fixed-offset packet layout is
actually correct and complete.

Sources (out-of-git/NDA, only behavior/offsets recorded here, no large raw
decompiled blocks):
- `MRUSBHost.dll.all.c` — `MrUsbDevice_Cyk{Get,Set}FeatureReport`,
  `CykSetOutputReport`, `RegisterCykInputReportCallback/EventsCallback`.
- `MotionControllerHid.dll.all.c` — `CrystalKeyReadCommand`,
  `CrystalKeySendCommand`, `CrystalKeyStartIMUStream`, and the device-open /
  field-decode routines in `analog\oasis\crystalkey\hid\crystalkeydevice.cpp`
  (function names lost, but the `.cpp` path + line numbers survive in the
  decompiler's inlined logging strings).
- Monado: `wmr_controller_protocol.h/.c`, `wmr_controller_base.c`,
  `wmr_controller_hp.c` (and `wmr_controller_og.c`, identical layout),
  `wmr_hmd_controller.c`, `wmr_hmd.c`, `wmr_protocol.h`.

## 1. Headline finding: Windows does not use fixed byte offsets

`MotionControllerHid.dll`'s device-open path does **not** hardcode a byte
layout for the input report. At open time it calls `HidP_GetLinkCollectionNodes`
on the device's own HID **report descriptor** and walks the returned link
collections, matching each collection's `LinkUsage` against six fixed IDs and
caching the matching collection *index* (not a byte offset) in the device
struct:

| LinkUsage (hex) | Cached at struct+ | Collection name (from the error string emitted if missing) |
|---|---|---|
| `0x10` | `+0x58` | "Flags" (buttons + analog controls) |
| `0x73` | `+0x5a` | "Accel" |
| `0x76` | `+0x5c` | "Gyro" |
| `0x83` | `+0x5e` | "Mag" |
| `0x13` | `+0x60` | "Blob" (generic byte-blob / calibration channel) |
| `0x20` | `+0x62` | "Battery Percentage" |

If any of the six is missing from the descriptor, device open fails outright
("Could not find X Collection in HID Descriptor"). Field values are then read
per-frame with `HidP_GetScaledUsageValue` / `HidP_GetUsageValue` against a
vendor usage page (`0xFE`) scoped to each collection's index — i.e. Windows
asks the HID stack "give me usage 0x453 inside collection N", and the OS HID
parser (which already parsed the report descriptor) resolves that to whatever
byte/bit offset and Report-Descriptor-declared scale/units the firmware
happens to use.

Monado, by contrast, treats the whole 44-byte payload as an opaque
fixed-offset C struct (`wmr_controller_hp_packet_parse`, and identically
`wmr_controller_og.c`) with a hardcoded `if (len != 44)` check and manual
`read8/read16/read24/read32` cursor walks, plus its own scale constants
(`/(98000/2)` for accel, `*0.00001f` for gyro) instead of reading the
descriptor's logical-min/max + unit exponent. **This works only because the
firmware's report descriptor happens to lay these fields out in a stable,
contiguous order** — Monado has no way to detect a firmware/descriptor
revision that reorders or resizes a field; Windows would still work (it
re-reads the descriptor every time), Monado would silently misdecode.

## 2. Field-by-field mapping

Extraction order confirmed in the Windows field-decode routine (constant
Usage IDs on page `0xFE` unless noted; each collection's own scale factor is
a decompiler global with no readable value, `a cached internal global` etc. — the same
"decompiler can't show the literal, but the role is unambiguous from use"
situation as `02-clock-model.md`):

| # | Windows: collection / usage | Windows semantic | Monado: byte offset* / field | Confidence | Notes |
|---|---|---|---|---|---|
| 1 | Accel usage `0x453` | Accel X (scaled) | offset 8-10, `acc[0]` (24-bit) | High | Both put Accel-X first. |
| 2 | Accel usage `0x454` | Accel Y (scaled) | offset 11-13, `acc[1]` | High | Same scale factor as X in both. |
| 3 | Accel usage `0x455` | Accel Z (scaled) | offset 14-16, `acc[2]` | High | Same scale factor as X/Y in both. |
| 4 | Accel usage `0x434` | 4th scalar *in the Accel collection*, own distinct scale factor | offset 17-18, `imu.temperature` (16-bit) | Medium-high | Position matches exactly (right after accel XYZ, before gyro) and it is scaled *differently* from X/Y/Z in Windows too — consistent with a temperature channel riding in the accel collection. Not 100%: the decompile never surfaces a literal usage name, only the usage ID and its position. |
| 5 | Gyro usage `0x457` | Gyro X (scaled) | offset 19-21, `gyro[0]` (24-bit) | High | |
| 6 | Gyro usage `0x458` | Gyro Y (scaled) | offset 22-24, `gyro[1]` | High | |
| 7 | Gyro usage `0x459` | Gyro Z (scaled) | offset 25-27, `gyro[2]` | High | |
| 8 | Gyro usage `0x529`, **unscaled** `HidP_GetUsageValue` | Raw tick counter → timestamp | offset 28-31, `imu.timestamp_ticks` (32-bit) | High | See §3, timestamp handling matches almost exactly. |
| 9 | Mag usage `0x485/0x486/0x487` | Mag X/Y/Z (scaled, one shared factor) | **not decoded** — inside Monado's 12 "unknown" trailing bytes (comment: `read16 // probably mag`, `read32`, `read16 x3`) | Medium | See §4 — Monado's own comment guesses "mag" for a single 16-bit field, but Windows reads Mag as **three** separate scaled values, not one. Field almost certainly present in the trailing 12 bytes Monado never parses; exact sub-offsets not pinned in this pass. |
| 10 | Mag "timestamp" | Not re-read from the report — Windows just **copies the same 64-bit IMU timestamp** computed at #8 into the mag output slot | n/a | High | Mag and accel/gyro share one clock domain on this device; no separate mag timestamp field exists to look for. |
| 11 | Battery: Usage Page `6` ("Generic Device Controls"), usage `0x20` ("Battery Strength"), Battery-Percentage collection, **unscaled** `HidP_GetUsageValue` | raw 0-0xFF, then Windows computes `percent = (raw * 100) / 255` | offset 7, `battery` (8-bit), Monado computes `out_charge = raw / 255.0f` | **High — confirms Monado, resolves the open TODO** | `raw/255.0` and `(raw*100)/255` are the same ratio. Monado's `wmr_controller_hp.c` comment marks this "UNVERIFIED SCALE" — this cross-ref settles it: Monado's existing formula is correct. Safe to delete the "unverified" caveat (or downgrade it to "confirmed against Windows' own HidP scaling, 2026-08-17"). |
| 12 | Flags collection (buttons, thumbstick, trigger, squeeze, click bits) | Not individually traced this pass — confirmed as **one combined collection** distinct from Battery | offset 0-6: buttons byte, 12-bit thumbstick X/Y, trigger, squeeze/touchpad, 2nd buttons byte | Low-medium | Windows models Battery as a *separate* collection from Flags, while Monado's wire layout places the battery byte physically adjacent to (right after) the two button bytes. Not a contradiction — a HID report can group bytes contiguously on the wire while the descriptor declares them in different logical collections — but it does mean Monado's assumption that "battery sits right after buttons" is not something this pass independently verified against Windows; it was already validated live (2026-08-13 changelog note in `wmr_controller_hp.c`) so treat that as the stronger evidence, not this cross-ref. |
| 13 | "Blob" collection | Generic byte-blob command/response channel — collection exists, not traced to specific commands this pass | Monado's `wmr_controller_fw_cmd` / `wmr_controller_fw_cmd_response` block-read protocol (`prefix/cmd_id/block_id/addr` → `blk_remain/len/data[68]`) | Medium | Conceptually the same purpose (firmware/calibration block reads, `CrystalKeyGetCalibrationBlob` in `01-ghidra-firstpass.md`) but see §5 — Windows appears to route this over **Feature** reports, Monado over plain **Output/Input** reports. |

*Monado byte offsets are relative to the 44-byte payload, i.e. **after**
stripping the outer tunnel-wrapper byte and the
`WMR_MOTION_CONTROLLER_STATUS_MSG` (0x01) inner-type byte — see §6 for the
full outer framing.

## 3. Timestamp / wraparound handling — matches

Windows feeds the raw tick value from usage `0x529` through two small helper
functions that compare it against the previously-stored tick value and flag
a wraparound when the delta looks like `> 0x7ffffffe` in magnitude (a
classic 32-bit-rollover heuristic), logging via ETW when it fires. This is
the *same* strategy `wmr_controller_hp_packet_parse` already implements:

```c
uint32_t prev_ticks = last_input->imu.timestamp_ticks & UINT32_C(0xFFFFFFFF);
last_input->imu.timestamp_ticks &= (UINT64_C(0xFFFFFFFF) << 32u);
last_input->imu.timestamp_ticks += (uint32_t)read32(&p);
if ((last_input->imu.timestamp_ticks & UINT64_C(0xFFFFFFFF)) < prev_ticks) {
    last_input->imu.timestamp_ticks += (UINT64_C(0x1) << 32u); // wrap
}
```

**Not a bug.** Worth noting for the still-open clock-domain issue
(`02-clock-model.md`, `project_g2_controller_6dof`): this is the
controller's own local tick counter (`WMR_MOTION_CONTROLLER_NS_PER_TICK` =
100 ns/tick in Monado), a *different* clock domain from the HUP/QPC headset
IMU clock that doc 13 pinned. Monado converts controller ticks to its
timeline with a flat multiply-by-100ns and no epoch anchoring to the host
clock — the same "pure linear scale, no additive offset" shape doc 13 found
for HUP↔QPC. If the controller timestamp path also shows a drifting offset
symptom, the same fix direction (anchor via frequency ratio to a shared
epoch, don't estimate a running offset) is worth testing there too — not
confirmed in this pass, flagged for follow-up.

## 4. Discrepancies / candidate gaps in Monado

1. **Mag data is not decoded at all.** Windows explicitly reads a 3-axis
   scaled Mag vector from its own HID collection. Monado's parser has a
   single-line comment guessing one 16-bit field is "probably mag" — Windows
   proves that guess structurally wrong (mag is 3 values, not 1) and that the
   real mag triplet is somewhere in the 12 bytes Monado currently discards
   entirely (`read16`, `read32`, `read16 x3` in the "Todo: More decoding
   here" block of both `wmr_controller_hp.c` and `wmr_controller_og.c`).
   Not currently used for anything in Monado's controller tracking (no mag
   fusion), so this is a missing-feature gap, not a correctness bug — but if
   mag-assisted yaw correction is ever wanted for the controllers, this is
   where it lives.
2. **Battery scale — resolved, not a discrepancy.** See mapping row 11:
   Monado's `raw/255.0f` matches Windows' `(raw*100)/255` exactly. Recommend
   updating the "UNVERIFIED SCALE" comment in
   `wmr_controller_hp_get_battery_status()`.
3. **Command/blob channel likely uses the wrong report type.** See §5.
4. **Architecture-level fragility, not a byte-level bug today:** Monado's
   `len != 44` fixed-size check plus manual cursor decode has no fallback if
   a firmware update changes field order/size — Windows re-derives the
   layout from the descriptor every device-open. If a G2 firmware update
   ever ships a reordered/resized report, Monado's parser fails silently
   (wrong values, not a crash — `read24`/`read16` never bounds-check against
   a *declared* field boundary, only against the fixed 44-byte total). No
   evidence this has happened; noted as a structural risk, not an observed
   bug.
5. **Flags-collection bit layout not independently cross-checked.** This
   pass didn't trace individual button/thumbstick/trigger usage IDs inside
   the Flags collection (time-boxed out — the extraction function uses a
   different, smaller struct offset scheme (`param+0xb`) that wasn't
   resolved to specific usage IDs). Monado's button bit mapping is validated
   live in practice (controllers are playable, per
   `project_g2_controller_6dof`), so this is a low-priority gap, listed for
   completeness rather than urgency.

## 5. Transport: Output/Input reports (Monado) vs. Feature reports (Windows) — open question

`MRUSBHost.dll` exports three distinct primitives for the controller tunnel:
`MrUsbDevice_CykSetOutputReport`, `CykSetFeatureReport`, and
`CykGetFeatureReport`. Their bodies are thin dispatch-table forwarders (the
actual HID I/O happens in a different, uninlined compilation unit), but the
three are clearly differentiated at this layer — the Set variants pass a
different first argument to the shared dispatch icall (`0` for Output,
`1` for Feature), and Get is a separate exported symbol entirely.

Monado's tunnel (`wmr_hmd_controller.c` → `wmr_hmd.c`) sends **everything** —
both the async ~45-byte input stream *and* the `wmr_controller_fw_cmd`
block-read command/response protocol used for calibration and config reads
— over plain `os_hid_write`/`os_hid_read` (regular Output/Input reports via
hidraw). It never calls `os_hid_get_feature`/`os_hid_set_feature`, even
though Monado's `os_hid` abstraction has both available
(`src/xrt/auxiliary/os/os_hid.h`).

**Medium confidence, flagged not asserted:** this pass did not trace which
specific Windows commands route through `CykSetFeatureReport`/
`CykGetFeatureReport` vs `CykSetOutputReport` — it's plausible Windows uses
Feature reports specifically for the synchronous "Blob" (calibration/
firmware) channel and Output/Input for the async streams, which would make
Monado's "everything over Output/Input" choice a functional simplification
that happens to work (many hidraw/USB-HID stacks alias Output and Feature
reports for HID class devices that don't distinguish them in firmware) rather
than a bug. Worth revisiting only if the fw-cmd retry/timeout path
(`wmr_controller_send_fw_cmd_retry`, already hardened against dropped
replies per its own comment) shows further reliability issues.

## 6. Outer tunnel framing (Monado-side baseline, for context)

Not reverse-engineered from Windows this pass (Monado's own header/dispatch
code, included here because the mapping table above is relative to it):

- HMD-side USB HID report IDs: `WMR_MS_HOLOLENS_MSG_LEFT_CONTROLLER = 0x06`,
  `..._RIGHT_CONTROLLER = 0x0E` (`wmr_protocol.h`). Minimum accepted size is
  45 bytes (`hololens_handle_controller_packet`, `wmr_hmd.c:345`); no exact
  max-size check.
- `wmr_hmd_controller_create(..., hmd_cmd_base, ...)` is called with
  `hmd_cmd_base = 0x5` (left) / `0xD` (right) (`wmr_hmd.c:204`).
- **Inbound**: `receive_bytes_from_controller` does `buffer[0] -=
  hmd_cmd_base`, turning `0x06 - 0x05 = 0x01` (left) / `0x0E - 0x0D = 0x01`
  (right) — both resolve to the single inner type
  `WMR_MOTION_CONTROLLER_STATUS_MSG = 0x01` before
  `wmr_controller_hp_packet_parse` ever sees the buffer.
- **Outbound**: `send_bytes_to_controller` does `outbuf[0] += hmd_cmd_base`.
  Monado's fw-cmd protocol and the "enable status reports"/"imu on" commands
  all start with inner byte `0x06` (`WMR_CONTROLLER_FW_CMD_INIT(0x06, ...)`,
  `wmr_controller_base.c:950-952`) — coincidentally the same numeral as the
  left-controller *inbound* report ID, but a different byte in a different
  direction/offset scheme. The actual outer USB report ID Monado writes for
  commands is `0x06 + hmd_cmd_base` = `0x0B` (left) / `0x13` (right).

## 7. Summary table (confidence-ranked)

| Confidence | Findings |
|---|---|
| High | Accel/Gyro XYZ order and position match exactly. Timestamp raw-tick + 32-bit wraparound handling matches. Battery scale (`raw/255`) confirmed correct — resolves Monado's own "unverified" comment. |
| Medium-high | The 16-bit field Monado calls `imu.temperature` is very likely correct (position + distinct-scale-factor match in Windows' Accel collection). |
| Medium | Mag XYZ is a real, undecoded 3-axis field hiding in Monado's 12 "unknown" trailing bytes — not the single 16-bit field the code comment guesses. "Blob" collection ~ Monado's fw-cmd block-read protocol, purpose-equivalent. |
| Medium (flagged, not asserted) | Windows may route the Blob/calibration channel over HID Feature reports while Monado uses only Output/Input reports for everything — functional risk, not a proven bug. |
| Low | Flags-collection (buttons/stick/trigger) bit-level usage IDs not independently traced this pass; Monado's existing bit mapping is validated by live play-testing instead. |

## Next targets

1. Pin the exact sub-offsets of the Mag triplet within Monado's 12
   "unknown" bytes (likely by comparing a live hexdump against a
   Windows USB capture, now that we know *what* to look for).
2. Trace which Windows commands actually use `CykSetFeatureReport`/
   `CykGetFeatureReport` vs `CykSetOutputReport` to settle §5.
3. Resolve `a cached internal global` (the 5-entry table `CrystalKeyUsesSpatialAck`
   checks) — likely the actual firmware command-ID values, which would let
   Monado's `0x00/0x02/0x03/0x04` fw-cmd IDs be cross-checked by name.
