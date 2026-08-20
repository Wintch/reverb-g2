# 63 — Hardware map: every part we can name, and every one we cannot

**Born 2026-08-19 (T231) at the user's request: "asegurate de mapear todo el hardware. Tener
referencias. Me avisas y las busco."** The knowledge existed — it was just scattered across
`docs/10` (firmware strings and FCC filings), `docs/12` (protocol and video chain) and `docs/00`
(USB topology), so nobody could see what was *missing*. This is one table, and the last column is
the point: **what is actually confirmed, what is inferred, and what nobody here has ever
identified.** The gaps at the end are a shopping list for someone with a screwdriver or a better
search engine.

Confidence is stated per row and means exactly this:
- **confirmed** — read from the device, its firmware, or its own datasheet.
- **inferred** — a strong chain of reasoning from something confirmed, but never seen directly.
- **unknown** — nobody here has identified it. Not "probably X". Unknown.

## Headset — video chain

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| DP → MIPI DSI bridge | **Analogix ANX7530** | Firmware version string `STM:..;DFU:..;ANX7688:..;ANX7530:..`; [product brief](https://www.analogix.com/en/system/files/AA-004263-PB-7-ANX7530_Product_Brief.pdf) obtained, rated for VR to 120 Hz | **confirmed** |
| Second Analogix part | **ANX7688** | Same firmware string. Its role here is *not* pinned down — the part is a USB-C/DP alt-mode + HDMI bridge, which does not obviously fit a headset that receives plain DP | **confirmed present, role unknown** |
| Bridge MCU | **STM32** (exact model unknown) | `STM:` in the version string; `MCU Download` silkscreen on the A85Q board; DFU paths in firmware (`bridge_fw_check_update`, `bridge_fw_switch_bank`, `QCI_FEATURE_ERASE_FLASH`) — the bridge firmware is field-updatable in banks | **confirmed family, model unknown** |
| Bridge debug access | **`DES JTAG` header** on the main board | Readable silkscreen in the FCC teardown photos. `DES` ≈ deserializer, i.e. the video chip. **There is a JTAG header on the bridge** | **confirmed** |
| Panels | 2 × LCD, 2160×2160, 90 Hz, PWM backlight | `panel_backlight_duty`, `[%s] left duty %d, right duty %d, frame timing %d, panel ID %d` in firmware; modes read from EDID | **confirmed behaviour, part unknown** |
| EDID modes | `4320x2160@90` (905150 kHz), `2880x1440@90` (428580), `4320x2160@60` (709150) | Read from the kernel, verified with `hmd-modeset list` | **confirmed** |

## Headset — tracking and sensors

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| Cameras | 4 × **OmniVision OV7251**, 640×480 mono 8-bit, 2560×480 combined framebuffer | Firmware logs `OV7251SetFrameRate: 90hz requested but not USB3.0SS` | **confirmed** |
| Camera aggregator | **Lattice CrossLink `LIF-MD6000-6CSFBGA81`** | Datasheet + the Acer WMR teardown, where the same chip fills this role. **Was once wrongly called the video bridge — it is not**, its datasheet does not mention DisplayPort | **confirmed** |
| IMU | — | Nobody here has identified it | **unknown** |
| Proximity sensor (nose bridge) | — | Its *data* is fully characterised (binary 1/0, `WMR_CONTROL_MSG_IPD_VALUE`, debounce measured in T225) but the part is not | **unknown** |
| IPD adjustment | motorised/encoded, value reported over HID | Same message carries it | **confirmed behaviour, part unknown** |

## Headset — USB and audio

| Device | ID | What it is | Confidence |
|---|---|---|---|
| SuperSpeed hub | `04b4:6504` | Cypress, in the cable's active box | **confirmed** |
| USB2 hub | `04b4:6506` | Cypress `CY4603` per its own USB strings | **confirmed** |
| Sensors | `045e:0659` "HoloLens Sensors" (Microsoft) | Cameras, IMU and the controller radio tunnel. Enumerates at SuperSpeed *or* high speed (measured T231) | **confirmed** |
| Companion | `03f0:0580` "QHMD A85V" (Quanta) | Panel on/off, activation, IPD, proximity. Almost certainly the STM32 above | **confirmed device, inferred silicon** |
| Audio | `0bda:4c15` (Realtek) | Speakers + mic | **confirmed** |
| Speakers / mic | — | Off-ear speakers, mic array size unknown | **unknown** |

## Cable and power — the part that has caused the most trouble

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| Cable type | **Active**, with an inline box | Measured: the box contains USB hub silicon and a DP repeater (`docs/22`) | **confirmed** |
| Inline USB hub | Cypress (`04b4:650x`) | Enumerates as such | **confirmed** |
| **DP repeater in the box** | — | Its *existence* is established by the cable anatomy; **the chip has never been identified**, and it is the prime suspect in years of link faults | **unknown — highest-value gap** |
| Revisions | v1 and **rev2A** (rev2A adds a button v1 lacks) | User knowledge, community record (`docs/22`) | **confirmed** |
| PSU | 12 V barrel | Measured | **confirmed rating, part unknown** |

## Controllers

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| Tracking LEDs | ring of **32** IR LEDs | Constellation model in the WMR calibration data; ~11° spacing derived in T224 | **confirmed count** |
| LED drive | **no host command exists** | The WMR controller protocol carries no brightness/power/PWM command, and `docs/12` records none (verified T229) | **confirmed absence** |
| IMU | — | Data fully characterised (gain 0.9905 L/R, wobble <1°, T212 quorum test); part unknown | **unknown** |
| Radio | Bluetooth, tunnelled through the headset's HoloLens device | `docs/03` | **confirmed path, part unknown** |
| Battery | 2 × AA | Measured extensively (`docs/46`) | **confirmed** |
| MCU | — | | **unknown** |

## Regulatory / teardown references

| Reference | What it is | Where |
|---|---|---|
| **FCC ID `HFS-A85Q`** | The G2 itself. Grantee Quanta Computer, grant 2020-06-05 | [fccid.io/HFS-A85Q](https://fccid.io/HFS-A85Q) |
| **FCC ID `HFS-A85R`** | The **Omnicept** — a different SKU; its teardown photos are of the **Tobii** eye-tracking board | [fccid.io/HFS-A85R](https://fccid.io/HFS-A85R) |
| Internal photos | 78 images extracted; scanned at ~130 DPI ≈ **7 px/mm**, which is *below* silkscreen legibility — the main IC is a black square with no readable text even at 10× | local, not in repo |
| Schematics / block diagram | **Filed with the FCC and permanently withheld** at Quanta's request | not obtainable |

## What is worth going to find

Ordered by what it would actually unlock, not by how easy it is:

1. **The DP repeater chip in the cable's inline box.** Years of link faults point at that box
   (`docs/22`), the rev2A "fix" is a lottery, and we cannot even name the part. A photo of the
   board inside the box — the box opens — would answer it in one step. **Highest value.**
2. **The headset's IMU part.** Roll drift under motion is an open problem attributed to
   gyro-bias-under-dynamics (`docs/pruebas` T203 item 2). Knowing the part means knowing its
   spec'd bias stability, which turns "the drift seems high" into "the drift is 3× spec" or "we
   are asking too much of a cheap part".
3. **The controller IMU and MCU.** Same reasoning, plus it bears on the LED question: whether
   LED drive is regulated at all is a property of that board.
4. **The panel part number.** Would settle whether the 90 Hz limit is the panel or the bridge,
   which is the question this whole repo started from.
5. **The exact STM32 model.** With `MCU Download` and `DES JTAG` headers on the board, a named
   part is the difference between "there is a JTAG header" and actually talking to it.
6. **ANX7688's role.** A USB-C/DP-alt-mode bridge inside a headset fed by plain DP does not
   obviously make sense; something about the link topology is not understood.

**How to help:** clear photographs of board silkscreen at legible resolution — the FCC scans are
too coarse by roughly a factor of three. The G2 opens; the cable box opens. Anything readable
goes straight into the table above.
