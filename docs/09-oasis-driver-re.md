# 09 — What Windows sends to the G2 panel (read from the Oasis driver)

**Bottom line: the Oasis driver, which runs the G2 at 90 Hz on Windows, does NOT send the
headset any mode command. The only panel command that exists is "enable display",
and Monado already sends it.**

This closes, binary in hand, the hypothesis the project had been carrying for two chapters:
*"nobody is telling the headset to go to 90 Hz"*.

## Where this came from

On the rig's Windows disk, without booting Windows, mounting the NTFS partitions read-only:

```bash
sudo mount -t ntfs-3g -o ro,noatime /dev/nvme0n1p4 /mnt/win4
```

There are **two** WMR drivers installed by Steam, and the difference matters:

| | what it is | useful for this |
|---|---|---|
| `MixedRealityVRDriver` (Microsoft) | bridges SteamVR to the OS's WMR runtime | **no** — delegates, doesn't touch USB |
| `Oasis Driver for Windows Mixed Reality` (mbucchia) | standalone driver, talks to the headset **directly** | **yes** |

The mbucchia one is the one that matters. Its manifest binds to the Hololens Sensors by VID:PID, i.e. the same
device Monado uses:

```json
{ "name": "oasis", "hmd_presence": [ "045E.0659" ] }
```

Relevant binaries, in `bin/win64/`:

```
driver_oasis.dll        the SteamVR driver (imports HID.DLL directly)
HololensSensors.dll     sensors + panel, in userspace (imports HID.DLL directly)
MRUSBHost.dll           raw USB/HID layer
MROEMFwHost.dll         OEM firmware
unlock/unlock_wmr.exe   examined 2026-08-06, see below
```

The build path was left embedded: `D:\a\WMR-Standalone-Oasis-Driver\...\driver_oasis\HmdDriver.cpp`
— it's a GitHub Actions build, so a repo with that name exists. Not searched for.

## Method (no ghidra or radare2, just binutils)

1. `strings` to locate candidates.
2. `objdump -h` for the sections, and convert file offset → VA.
3. `objdump -d` and search for the string's VA in the disassembly: objdump already resolves
   rip-relative `lea` instructions, so xrefs can be found by text search.
4. For calls to imported APIs: `objdump -p` gives the thunk's RVA in the IAT, and you
   search for `call *0x...(%rip)  # 0x<thunk>` in the disassembly.

The script is in the lab repo as `scripts/xref.py` (usage:
`xref.py <dll> <asm> <substring>...`).

## What was found

### The only panel command: Display Enable

`driver_oasis.dll` has **only one** `HidD_SetFeature` call site in the entire binary:

```asm
mov  $0x2,%ecx     ; ReportType = HidP_Feature
mov  $0x3,%edx     ; UsagePage  = 0x03   (VR Controls)
xor  %r8d,%r8d     ; LinkCollection = 0
mov  $0x21,%r9d    ; Usage      = 0x21   (Display Enable)
mov  %r13d,0x20(%rsp)   ; the value (0/1)
call *... ; HidP_SetUsageValue
call *... ; HidD_SetFeature
```

`HololensSensors.dll` does the same thing, written differently — same page, same usage:

```asm
mov  $0x21,%r9d          ; Usage = 0x21
lea  -0x1e(%r9),%edx     ; UsagePage = 0x21-0x1e = 0x03
```

**Usage Page 0x03 / Usage 0x21 = "Display Enable" from the VR Controls HID Usage Table.** It's
exactly the `{0x04, 0x01}` from `wmr_hmd_screen_enable_reverb()`. Windows expresses it via
usages (letting the report descriptor decide the report ID); Monado writes the bytes by hand.
The effect on the headset is the same.

Difference of style, not content: the driver builds the report with `HidP_SetUsageValue` and
pulls the report ID from `HIDP_VALUE_CAPS` (`movzbl 0x2(%rax)` = `ReportID` field), instead of
hardcoding it.

### There is no refresh-rate command. It was searched for and isn't there.

Two false positives worth documenting so nobody chases them again:

**`HmdDriver_SetFrameRate` belongs to the cameras, not the panel.** It's an RPC method (the driver
uses ZMQ + jsoncpp) and its parameters give it away:

```
HmdDriver_SetFrameRate
    IspFrameRate
    SensorFrameRate
```

ISP = Image Signal Processor. It sits in the middle of the camera block
(`HmdDriver_GetCameraIntrinsics`, `HmdDriver_SetCameraCompatibilityMode`,
`HmdDriver_StartVideoStream`...). This matches the string in `HololensSensors.dll`:
`OV7251SetFrameRate: 90hz requested but not USB3.0SS` — the OV7251 is the tracking cameras'
sensor. **That 90 Hz is a different 90 Hz.**

**`Detected change of refresh rate %.0f -> %.0f` is SteamVR bookkeeping.** The code that
emits it reads property `0x7d2` (2002 = `Prop_DisplayFrequency_Float`) from the property
container, compares it against the stored value, and if it changed, walks an internal table of
modes computing `num/den` to update `0x7d1` (2001 = `Prop_SecondsFromVsyncToPhotons`). Not a
single byte goes out to the headset. `preferredRefreshRate` is the SteamVR settings key it
reads (it sits next to the string `steamvr` in `.rdata`).

The other four `HidP_SetUsageValue` calls in the driver are Usage Page `0x0E` (Haptics), usages
`0x21`/`0x23`, ReportType Output: controller rumble.

### Headset firmware strings (for whoever continues this)

`HololensSensors.dll` carries firmware log strings, useful as a hardware map:

```
Backlight_PowerOn / Backlight_PowerOff / BacklightState / DisplayPanel
SelectedRefreshRate          [%s] refresh_rate %d
panel_register_read   panel_backlight_duty   panel_brightness_control   panel_B9_check
[%s] left duty %d, right duty %d, frame timing %d, panel ID %d
[Panel %d]map BKLT current, left %dmA, right %dmA
Part: LIF-MD6000-6CSFBGA81
```

`LIF-MD6000` is a **Lattice CrossLink**, the headset's MIPI/DP bridge. The fact that the firmware has
a concept of `refresh_rate` and `SelectedRefreshRate` doesn't contradict the above: the panel
knows what refresh it's at — it simply **isn't told over HID from the host** — it infers it
from the video timing it receives.

## What is concluded, and what is NOT

**Concluded:** no proprietary command is missing. Monado's HID sequence is correct
and sufficient. The panel adopts the refresh rate of the video it receives. `docs/07-windows-hid-capture.md`
is now archived: there's no longer any need to boot Windows to capture anything.

This is the **second** time this hypothesis dies. The first was by argument (Project-VR
reaches 90 Hz without proprietary commands, commit `3e2e7ac`); this one is by direct evidence.
Between the two there was a stretch where `CLAUDE.md` still treated the hypothesis as alive and
cited it again as "the only one that explains the results." Corrected.

**NOT concluded:** that the problem is NVIDIA's by elimination. What remains open is
what about the 90 Hz video link the headset doesn't like — see the bandwidth analysis in
`docs/04-lab-90hz.md`, which also leaves the DSC theory in bad shape.

## Closed afterward (2026-08-05)

- **`unlock_wmr.exe`** turned out to be a lot more than its name suggests: it handles **direct mode and
  display state** (`DirectModeHelper_Ctor`, `DisableDirectMode`, `SetDisplayState`, `Direct Mode: %s`,
  *"Device does not need manual activation of the display"*), using
  `Windows.Devices.Display.Core`. And it carries GPU-vendor-specific paths: `ADL2_Display_*` and
  `agsSetDisplayMode` for **AMD**. In other words, on Windows an app can request arbitrary
  timings; on Linux NVIDIA does not allow it (measured: `vkCreateDisplayModeKHR` and
  `drmModeSetCrtc` reject anything not present in the EDID).
- **`MROEMFwHost.dll`** is **exclusively the firmware updater**: `BeginUpdate`,
  `CommitBuffer`, `CompleteUpdate`, checksum verification, `WriteData`. It looks up reports
  by HID *usage*. Its `ReadDeviceInfo` is used to decide whether an update is needed, not to read
  panel state. **There is no path there to query the ANX7530 at runtime.** Note that this
  binary CAN write firmware to the headset: territory not worth getting into without
  a very good reason.
- **`client_utility.exe`** is a Steam API helper (`STEAMSCREENSHOTS_INTERFACE_VERSION003`)
  and nothing else.

With that, all four Oasis driver binaries have been opened up, with nothing more to extract.

## Loose ends, not looked at

- `driver_oasis.dll` has `.detourc`/`.detourd` sections: it uses Microsoft Detours to
  hook APIs. What it hooks was not investigated.
- The partitions were mounted read-only at `/mnt/win{3,4,5}`. Unmount with
  `sudo umount /mnt/win3 /mnt/win4 /mnt/win5`.

## `unlock_wmr.exe`: doesn't send any pairing command (2026-08-06)

This binary was revisited specifically to look for the controller pairing
protocol, prompted by the fact that a hidden button in the battery compartment can unpair
a controller from the headset (see `docs/03-controllers.md`, section "Pairing" —
that's where the full conclusion is, this is the technical detail of where it came from).

Original repo: `github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality` — turned out to be
just an issue tracker with a wiki, no published source code. The wiki does have a page
`Pairing-Motion-Controllers` with the procedure (physical, controller button).

**Why there's no source (T239)**: `mbucchia` is Matthieu Bucchianeri, **a Microsoft engineer**
(by his own public statements, previously on the Mixed Reality/HoloLens team, still at Microsoft
though no longer on that team) who built Oasis in a personal capacity after 24H2 orphaned WMR
(`docs/10` has the deprecation timeline and primary source). He has stated he's bound by
Microsoft NDAs and won't open-source it, despite giving it away free on Steam — which is why
everything in this document had to come from disassembly rather than a repo.

Imports of `unlock_wmr.exe`: `SETUPAPI.dll` (`SetupDiGetClassDevsW`,
`SetupDiEnumDeviceInterfaces`, ...), `CFGMGR32.dll` (`CM_Get_Device_Interface_ListW`,
`CM_Get_Device_Interface_PropertyW`) and `HID.DLL` — no Bluetooth at all (`bthprops`,
`Windows.Devices.Bluetooth`, WinRT device-pairing APIs appear nowhere). Same
method as for Display Enable (`xref.py` over a complete `objdump -d`):

- Only call site of `HidP_SetUsageValue`/`HidD_SetFeature` in the entire binary: same
  arguments already documented above for Display Enable — `UsagePage=0x3`,
  `Usage=0x21`. **There is no second, separate HID command for pairing.**
- The function containing the strings `"Start pairing new %s motion controller"` /
  `"Unpairing previous %s motion controller"` / `"Timeout pairing %s motion controller"`
  is a polling loop with sleeps (`Sleep(100)` x60 ≈ 6s timeout) that calls a
  MessageBox-like function (comparing the result against 6/2 = IDYES/IDCANCEL) and strings like
  `"Found controller device (paired through Headset): %s"` — it's the UI waiting for
  `SetupDiGetClassDevsW` to see the controller's HID interface appear, not something that triggers
  pairing on the headset.

Conclusion: pairing is a radio handshake internal to the headset, triggered
physically (controller button), with no host command to replay. This confirms and closes
what `docs/03-controllers.md` already suggested from the start ("nothing needs to be paired on
Linux") — now with binary evidence, not just from reading the Monado driver.
