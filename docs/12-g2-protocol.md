# 12 — HP Reverb G2 Protocol: Reference

Everything we know about the headset protocol, in one place. It's the foundation on which a
driver or toolkit can be built.

Items marked **[OURS]** were discovered in this project and are not documented anywhere else
we know of. Items marked **[MONADO]** come from the upstream WMR driver, which in turn came
from reverse engineering OpenHMD.

---

## 1. USB Topology

The G2 presents **five** devices. If any is missing, the problem is the port or the cable —
not the software (ch. 00).

```
3-1    04b4:6506  Cypress   internal USB2 hub              480M
3-1.2  0bda:4c15  Realtek   USB audio (speakers + mic)    480M
3-1.3  03f0:0580  Quanta    "QHMD A85V" = COMPANION        12M   <- control HID
4-1    04b4:6504  Cypress   SuperSpeed hub                5000M
4-1.1  045e:0659  Microsoft "HoloLens Sensors"          5000M   <- IMU + cameras + config
```

The two that matter for the protocol are the **companion** (`03f0:0580`) and the
**HoloLens Sensors** (`045e:0659`). Both expose `hidraw` and are accessible from the
`plugdev` group.

**[OURS]** The screen-off command can cause the **companion to re-enumerate**, changing
`hidraw` node (observed `hidraw8` → `hidraw7`). Never cache the path: you have to re-scan by
VID:PID. This also explains the "random USB2 hub resets" that the project had as an
unexplained annoyance: they aren't random, they're triggered by the screen-off.

**[OURS, from Microsoft's own driver INFs, 2026-08-16]** `045e:0659` (HoloLens Sensors) is
itself composite, with (at least) three distinct interfaces, each bound differently by
Microsoft's stack:

```
MI_02  ->  HololensSensors.inf (Class=Holographic)  ->  3 HID collections (col01/02/03)
           the headset/controller-tunnel HID reports; this is the only one this project's
           own stack (Monado/hidraw) has ever used.
MI_03  ->  HololensSensorsWinUsb.inf (Class=USBDevice, WINUSB.INF)  ->  raw WinUSB claim,
           DeviceInterfaceGUID {61bd6c28-9f10-426e-aa65-729d4656f6a2}. No kernel-side driver
           at all -- a userspace app opens it directly. Never explored from this project's
           side; the likely candidate is the raw bulk-transfer camera/sensor data path that
           Microsoft's own MRUSBHost.dll pulls from, separate from the HID control channel.
MI_04  ->  HololensSensors.inf again, but the OTHER device entry -> bound into the formal
           Holographic device class (ClassGuid {d612553d-06b1-49ca-8938-e39ef80eb16f}) with
           WUDF DeviceGroupId="MixedRealityHmd" for coordinated power/idle state. Bookkeeping
           only (see docs/31) -- not itself a data path.
```

Also confirmed, and already independently satisfied: `HololensSensorsWinUsb.inf` explicitly
disables USB idle/autosuspend for MI_03 (`DeviceIdleEnabled=0`). This project's own
`scripts/71-usb-no-autosuspend.rules` already disables autosuspend for all of `idVendor==045e`
at the whole-device level (superset of Microsoft's per-interface setting, Linux doesn't do
per-interface power control the way Windows' AddReg can) — checked 2026-08-16, not a gap.

---

## 2. Message Types

**[MONADO]** `wmr_protocol.h`:

```c
#define WMR_MS_HOLOLENS_MSG_SENSORS           0x01  // IMU stream, ~250 Hz
#define WMR_MS_HOLOLENS_MSG_CONTROL           0x02  // config read responses
#define WMR_MS_HOLOLENS_MSG_DEBUG             0x03  // FIRMWARE LOG  <-- see §6
#define WMR_MS_HOLOLENS_MSG_BT_IFACE          0x05
#define WMR_MS_HOLOLENS_MSG_LEFT_CONTROLLER   0x06
#define WMR_MS_HOLOLENS_MSG_RIGHT_CONTROLLER  0x0E
#define WMR_MS_HOLOLENS_MSG_BT_CONTROL        0x16
#define WMR_MS_HOLOLENS_MSG_CONTROLLER_STATUS 0x17

// from the COMPANION:
#define WMR_CONTROL_MSG_IPD_VALUE     0x01  // proximity + IPD
#define WMR_CONTROL_MSG_UNKNOWN_02    0x02
#define WMR_CONTROL_MSG_DEVICE_STATUS 0x05  // PANEL STATUS  <-- see §5
```

---

## 3. Panel Power-On

### 3.1 Activation Sequence (Reverb G1 and G2)

**[MONADO]** `wmr_hmd_activate_reverb()`, `wmr_hmd.c:767`. Goes to the **companion**:

```
sleep 300 ms                    ("this is what Windows does")
x4:  SET_FEATURE {0x50, 0x01}   (64 bytes)   <- "hack" inherited from OpenHMD, from the G1
     GET_FEATURE  0x50
     sleep 10 ms
GET_FEATURE 0x09   -> returns the SERIAL NUMBER in ASCII  (e.g. "REDACTED")
GET_FEATURE 0x08   -> returns the UID in ASCII
GET_FEATURE 0x06   -> zeros
SET_FEATURE {0x04, 0x01}        <- screen enable
```

**[OURS] `{0x04,0x01}` alone is NOT enough.** Without the full sequence the headset stays
completely off, it doesn't even show the HP logo. Implemented in `scripts/panel.py
activate`.

**[MONADO]** Activation **is NOT the same across brands**: the Samsung Odyssey and Odyssey+
do `GET 0x16 / 0x15 / 0x14` instead of the `0x50` loop and the `0x09/0x08/0x06` gets.

**[MONADO]** Of the 12 headsets in Monado's `headset_map[]`, **only 4 have an activation
function**: Reverb G1, Reverb G2, Odyssey and Odyssey+. Lenovo Explorer, Dell Visor, Acer
AH100/AH101, Medion Erazer and Fujitsu have `NULL` — Monado doesn't know how to power on
their panel. This is a real gap for any "universal driver" goal.

### 3.2 Power On / Off

**[MONADO]** `wmr_hmd_screen_enable_reverb()`, `wmr_hmd.c:846`:

```
SET_FEATURE {0x04, 0x01}   power on
SET_FEATURE {0x04, 0x00}   power off
```

**[OURS, from HP's driver]** Windows sends **exactly the same thing**, just expressed via HID
usages instead of raw bytes: **Usage Page `0x03` (VR Controls) / Usage `0x21` (Display
Enable)**, ReportType Feature. The driver builds the report with `HidP_SetUsageValue` and
gets the report ID from `HIDP_VALUE_CAPS`. The effect on the headset is identical. See ch. 09.

---

## 4. What DOESN'T Exist: a Refresh-Rate Command

**[OURS]** We disassembled the complete **Oasis** driver — all four binaries — which is what
runs the G2 at 90 Hz on Windows by talking to the headset directly, without going through
the OS's WMR runtime. **Its only panel command is Display Enable.** There is no mode,
refresh, or resolution command (ch. 09).

Independent confirmation: **thaytan**, author of Monado's WMR driver, states that after the
*enable display* command nothing over USB influences the mode — the negotiation is entirely
DisplayPort at the GPU driver level.

**The panel adopts the timing of whatever video signal it receives.** Period.

---

## 5. `DEVICE_STATUS` (0x05) — Panel Status  **[OURS]**

The companion emits a **33-byte** report when screen status changes. It's the only
*sink*-side instrumentation that exists: everything else (Vulkan, the NVIDIA log) reports
success with a dead panel.

### Decoded Fields

| offset | field | evidence |
|---|---|---|
| 0 | `0x05` (message type) | — |
| 1 | *backlight on* (sometimes `1`) | see the warning below |
| 2 | screen enabled: `0`→`1` with screen-enable | isolating HID activation without video |
| **5** | **refresh rate in decimal** | `0x3c`=60, `0x5a`=90, across two different resolutions |
| 9, 10 | unknown, change per mode | — |
| **11** | tracks the refresh: `0x1e`(30) at 60Hz, `0x14`(20) at 90Hz | — |
| 12 | unknown: `02` in two modes, `04` in `4320x2160@90` | — |
| 14, 15 | unknown: `77 00` or `77 77` | — |
| **19-20** | **htotal**, little-endian | `44 11`=4420, `a4 0b`=2980 |
| **21-22** | **vtotal**, little-endian | `72 0a`=2674, `3e 06`=1598, `e4 08`=2276 |
| 24-31 | unknown: `00 80` repeated, or `ff ff` | — |

### Measured Reference Messages

```
60Hz  4320x2160 WORKS  05 00 01 01 00 3c 00 00 00 05 2c 1e 02 00 77 00 00 00 06 44 11 72 0a 01 00 80 00 80 ff ff ff ff 02
90Hz  2880x1440 FAILS  05 00 01 01 00 5a 00 00 00 0c 1a 14 02 00 77 00 00 00 06 a4 0b 3e 06 01 00 80 00 80 ff ff ff ff 02
90Hz  4320x2160 FAILS  05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 01 00 80 00 80 00 80 00 80 02
```

The three refresh/htotal/vtotal values match **exactly** with the EDID modes. And with HID
activation but **no video**, those fields come back as zero — meaning the headset fills them
in by **measuring**, not by repeating what it was told.

**Conclusion: the headset receives and measures the correct timing at 90 Hz too.**

### Warning About Byte 1

We thought we had an automatic success detector: `byte 1 = 1` appeared in 3 of 3 messages
from the working mode and 0 of 8 from the failing ones, and it matches Monado's comment for
the G1 (*"once the HMD screen backlight visibly powers on"*). **It didn't survive
validation**: tested twice against the known-good 60 Hz mode, one run showed "FAILS" and the
other emitted no messages. It appears **only sometimes**. It's useful as a clue, **not as an
instrument**.

**Verification remains PHYSICAL.**

### How to Capture It

`scripts/panel-status.py`. Messages are only emitted **when something changes**: you have to
be listening *during* activation or a mode change, not at steady state.

---

## 6. `0x03 DEBUG` — the Headset's Firmware Log  **[OURS]**

The G2 emits its own firmware log **in ASCII**, over the HoloLens Sensors interface.
**509-byte** packets with several entries concatenated and zero-padded.

### Format of Each Entry

```
magic "Dlo+" | 4 bytes timestamp | 2 bytes sequence | 1 byte level | ASCII text \0
```

### Captured Entries

```
RequestImuDisable forSpi=0
ImuDisable Req=0 Spi=0
RequestImuEnable forSpi=0
ICMStart
ICM start status=0
ERROR: CommandSet st 0, cmd 0, reqCmd 23
```

### How to Unblock It

**The channel is SILENT** until something performs the headset's configuration sequence
(§7). `hmd-vk` doesn't do it and nothing comes out; `monado-service` does, and the channel
starts talking. Tool: `scripts/fwlog.py`.

### What It DOESN'T Say

**[OURS]** The firmware **doesn't log a single panel error at 90 Hz**. The
`ERROR: CommandSet st 0, cmd 0, reqCmd 23` that appears every 5s is **identical at 60 Hz and
at 90 Hz** — it's noise from the controllers subsystem (`reqCmd 23` = `0x17
CONTROLLER_STATUS`), and the control rules it out as a lead. The `DMA CMT ERR` that another
user reported in Monado issue #332 **doesn't reproduce here**.

---

## 7. Reading Configuration Blocks

**[MONADO]** `wmr_config_command_sync()`. Goes to the **HoloLens Sensors**: a 64-byte output
report `{0x02, type, 0...}` is written and it reads until receiving a report whose first byte
is `0x02` (`MSG_CONTROL`).

Full sequence to read the calibration block:

```
{0x02, 0x0b}   start
{0x02, 0x06}   block type
{0x02, 0x08}   repeat; buf[1]==0x01 = more data, buf[2] = length, data in buf[3..]
```

The blob comes obfuscated with a fixed-key XOR (`wmr_config_key` in Monado) and inside
carries a header with manufacturer, device, serial, UID and revision, plus a JSON.

**[OURS]** Dump from ours:

```
Manufacturer: HP Inc.
Device:       VR3000-0XX          <- matches the SKU from FCC filing HFS-A85R
Serial:       REDACTED
UID:          {EE4482CE-AFE7-5844-820A-73F26905A52F}
Revision:     RevB.N.J   (2020-10-30)
```

**The JSON is pure camera calibration** — `CalibrationInformation`, `Intrinsics`,
`ModelParameters`, `Rt`, `SensorWidth/Height`, `Shutter`, `ThermalAdjustmentParams`. **Not a
single display, panel, or refresh key.** Line closed.

---

## 8. Video Chain

```
GPU ──DisplayPort 1.4── ANX7530 ──2x MIPI-DSI── 2x LCD panel ── backlight (driver ?)
                        (Analogix)                (2160x2160 each)
```

- **`ANX7530`** (Analogix): DP→MIPI DSI bridge. Two independent outputs, one per panel, 8
  lanes at 1.5 Gbps = **12 Gbps per output**. Per panel at 90 Hz you need
  2160×2160×90×24bpp = **10.08 Gbps**: it fits, with little margin. Its product brief is
  titled *"up to 4K × 2K @ 60Hz"*. **No DSC** on the MIPI output. Configured over **I2C from
  the headset's STM32**, not from the host. No public register datasheet.
- **`ANX7688`** (Analogix): also present. Its datasheet places it on the host side
  (HDMI2.0+USB3.1 → USB-C); **no source explains what it does inside the headset**.
- **STM32** with a **DFU** path and firmware banks (`bridge_fw_check_update`,
  `bridge_fw_switch_bank`, `QCI_FEATURE_ERASE_FLASH`). HP's `MROEMFwHost.dll` is the updater.
  **It can write firmware to the headset**: don't touch it without a very good reason.
- **Panels**: part `AA029M48000 REV.02` labeled "JDP"; commercial candidate **Sharp
  LS029B3SX06/06A**, 2.9″, 2160×2160, CG-Silicon LTPS, 2-channel × 4-lane MIPI-DSI, **no
  integrated backlight**.
- **Backlight driver**: **no public data**. The FCC photos aren't enough to resolve it
  (ch. 10).
- **`LIF-MD6000`** (Lattice CrossLink): **is NOT the video bridge** — it's the aggregator for
  the 4 cameras. It was mistakenly flagged as the bridge and this was corrected.
- **Useful board silkscreen labels** (FCC photos): `MCU Download` and **`DES JTAG`**. There's
  a JTAG accessible to the video chip.

### EDID Modes

| idx | mode | pixel clock | htotal × vtotal | at 24bpp |
|---|---|---|---|---|
| 0 | 4320x2160@90 | 905150 kHz | 4420 × 2276 | 21.73 Gbps |
| 1 | 2880x1440@90 | 428580 kHz | 2980 × 1598 | 10.29 Gbps |
| 2 | 4320x2160@60 | 709150 kHz | 4420 × 2674 | 17.02 Gbps |

3-block EDID: base + CEA + embedded **DisplayID 1.2** (tag `0x70`) with two **Type I**
Detailed Timing descriptors. ManufID `0x220E` = `HPN`. (This line used to say "DisplayID
2.0 / Type VII" — the same error that had to be corrected in the published NVIDIA report;
see the correction section in `docs/13`. The distinction matters: the 1.x parser path in
NVKMS is exactly where the 6bpc clamp lives.)

**Watch out with the DisplayID pixel clock: it's in units of 10 kHz, not kHz.**
Misreading it gives "9 Hz" and "6 Hz" — it happened.

---

## 9. Tools in This Repo

| script | what it does |
|---|---|
| `panel.py` | `activate` / `on` / `off` / `cycle` the panel over HID, without Monado |
| `panel-status.py` | listens for `DEVICE_STATUS` (§5) |
| `fwlog.py` | decodes the firmware log (§6) |
| `hmd-vk.c` | modeset and presentation via Vulkan display, without Monado or OpenXR |
| `hmd-modeset.c` | modeset via KMS — **doesn't work on NVIDIA**, kept because the failure is informative |
| `lease-planes.c` | what objects mutter's lease brings |
| `drmprops.c` | `non-desktop` and connector modes, from the kernel |
| `check-lease.sh` | does the compositor offer the connector for leasing? |
| `decode-status.sh` | automated matrix for decoding `DEVICE_STATUS` |
| `hunt-debug.py` | hunts for non-sensor messages on both interfaces |
| `testlog.py` | physical test log with textual verdict |
| `hmd-watch.py` | proximity + motion, to know whether the user looked |
| `xref.py` | string xrefs in PE binaries, using only binutils |
| `pdf2md.py` | PDF → markdown + image extraction, no dependencies |
| `collect-nv.sh` | NVIDIA driver logs in all three modes (needs root) |

---

## 10. Methodology Rules This Project Paid Dearly For

1. **Panel verification is PHYSICAL.** Vulkan and OpenXR report success and 90.0 fps with the
   panel completely black. The NVIDIA log reports a successful attach in all three modes,
   without a single error. **No software instrument distinguishes success from failure.**
2. **Every measurement needs its control, run the same day.** Four findings from a single
   session died once the control was run against them: the `18 bpp`, the automatic byte-1
   detector, the `DMA CMT ERR`, and the reading that the failure was in the headset.
3. **Tests can't expire while the human is watching.** That's why `hmd-vk` holds the image
   indefinitely and `testlog.py` records the textual verdict with an ID.
4. **When closing out a line of investigation, update `CLAUDE.md` in the same commit.** An
   already-discarded hypothesis stayed alive there for a few hours and got cited again as
   "the only one that explains the results".
