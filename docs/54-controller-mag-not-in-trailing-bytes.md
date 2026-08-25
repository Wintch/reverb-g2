# Phase 3 (magnetometer) live capture — the "12 unknown bytes" carry no continuous 3-axis signal, contradicts the RE hypothesis (2026-08-18)

## What was tried

`docs/re-windows/03-controller-packets.md`'s Phase 3 (see `docs/re-windows/WORKPLAN.md`) said
Windows reads a Mag X/Y/Z triplet (HID usages `0x485-0x487`) plus device-state fields from the
same 12 trailing bytes Monado's `wmr_controller_hp.c` has always discarded (the old
`/* Todo: More decoding here */` comment guessed a single 16-bit "probably mag" field —
structurally too small for 3 axes on its own), but flagged the exact sub-offsets as unpinned:
"likely by comparing a live hexdump against a Windows USB capture."

Added `WMR_CONTROLLER_TAIL_LOG=1` (opt-in, `wmr_controller_hp.c`) to raw-dump those 12 bytes
per packet, then captured live on real hardware: left controller actively rotated through
multiple axes (full circle, tilt up/down, roll) for ~20s, right controller mostly stationary,
both against the same running `monado-service`.

## Result: no continuous signal anywhere in the 12 bytes

- **Right controller (stationary), 4768 packets: exactly ONE pattern the entire time**
  (`0000 00000000 0002 0000 0000`) — completely flat.
- **Left controller (actively rotated through multiple axes), 15646 packets: only 3 unique
  patterns total**, and the only byte that ever changed took just three small values
  (`0x00`/`0x01`/`0x03`) at one fixed position; **the other 10 of 12 bytes stayed zero for the
  entire capture, including during active rotation.**

A real 3-axis magnetometer reading Earth's ambient field (~0.25-0.65 Gauss depending on
location) cannot legitimately read a flat zero at rest, let alone stay flat through a full
rotation that should sweep each axis through its own field component. The one byte that did
vary looks like a small state/event counter (button or motion-event related, given it only
moved on the actively-manipulated controller), not sensor data — consistent with the OLD
comment's alternate guess ("Unknown. Device state, etc.") for one of the *other* fields in that
region, just landing on a different byte than originally guessed.

## Read

**This contradicts the RE research's core assumption for Phase 3, at least for what this
44-byte input report actually carries on real hardware.** Leading hypotheses, none confirmed
this session:
1. The magnetometer needs an explicit enable/start command over HID that Windows' driver sends
   and this Linux driver never issues — the sensor may simply not be streaming.
2. Mag data arrives via a different HID report ID entirely, not folded into this same 44-byte
   motion-controller report `wmr_controller_hp_packet_parse` reads.
3. The decompiled Windows offsets/usages were correct for the driver's *internal* representation
   but map to a report structure this G2 unit's firmware doesn't actually send (revision
   difference, or the RE pass read calibrator/config data rather than the live streaming report).

## CLOSED 2026-08-25 — Windows capture confirms: not a magnetometer, and the "not done" step above is now done

Live USBPcap capture (`windows-kit2/results/frametype-capture-20260825.pcapng`, 730s, real
Cyberpilot session, both controllers on) gives the byte-for-byte Windows-side comparison this
doc asked for. Located the same 45-byte HID interrupt-IN report on the wire (bus 2, device
addr 5, endpoint `0x84`; byte 0 = `0x06` left / `0x0E` right, matching `wmr_protocol.h`), and
walked the parser's own byte consumption (`wmr_controller_hp_packet_parse`) to confirm the
trailing 12 bytes land at payload offset 32-43, same place `WMR_CONTROLLER_TAIL_LOG` already
dumps them.

**Result: Windows does NOT carry a Mag X/Y/Z triplet there either — confirmed, not just
consistent with this doc's negative result.** Across 126,371 reports spanning stationary,
deliberate multi-axis waving (both hands), and live gameplay motion:
- Bytes 0-5 of the 12: always exactly zero (same as the Linux capture found).
- Byte 6: a rotating status/phase tag (13-14 discrete values), correlation with gyro
  magnitude **0.0009** — not sensor data.
- Byte 7: a near-perfectly linear real-time ramp, slope ≈24.4-24.9 units/sec, **identical
  whether the controller is sitting still or being violently rotated** (50-100× gyro
  magnitude difference, same ramp rate, residual std <1 count).
- Bytes 10-11: a 16-bit little-endian hardware tick counter (byte 10 slope ≈152.6/s, byte 11
  = its own carry), same rate regardless of motion.
- Bytes 8-9: noisy, but correlation with gyro/accel magnitude ≤0.02 — ruled out too.

This **extends** rather than just reconfirms the original finding: this doc's 2026-08-18
Linux capture only ran ~20s and apparently caught the controller's ~0.5s post-power-on
transient (flat zero + one low cycling byte) — the fresh Windows capture shows the SAME
early-power-on shape (`00 00 00 00 00 00 00 03 00 00 00 00` at t=354.017s, right controller's
first packet) before settling into the always-changing counter content above. So the
original "flat zero" observation was real but incomplete, not wrong — the bytes do carry
real, changing content on longer sessions, it's just not sensor data.

**Verdict, high confidence**: these 12 bytes are firmware housekeeping (a tick/sequence
counter plus a rotating status byte), not a magnetometer, on either OS. Not chased further:
which report ID (if any) carries real magnetometer data was out of scope for this pass — the
same capture likely has a much larger (~381-byte) report on the same endpoint that's very
probably the headset's own IMU/camera-adjacent stream, unexamined for this question.
</content>
