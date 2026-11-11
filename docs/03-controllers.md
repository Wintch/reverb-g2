# 03 — G2 WMR Controllers: status, fixes, pairing protocol, and open items

Later controller work lives in other docs: 6DoF root cause and plan in `docs/125-controller-6dof-root-cause-and-plan.md`
and `docs/126-constellation-blob-ownership.md`; the controllers on a host Bluetooth adapter in
`docs/136-g2-controllers-system-bluetooth.md` (and `docs/138-oasis-ignition-system-bt-controllers.md` for Oasis/SteamVR);
the input map in `docs/49-controller-input-map.md`; battery management in `docs/46-battery-management.md`.

## How the controllers communicate

The G2 controllers do NOT talk Bluetooth to the PC: they talk **real Bluetooth to the
headset's internal radio** (FCC filing: band 2402-2480 MHz, 0.015 W, "controllers' Bluetooth" —
`docs/10`), and their packets travel **tunneled through the same HID stream**
that carries the headset's IMU, camera timestamps, and status (`wmr_hmd_controller.c`).
Key consequence: during firmware/calibration reads for a controller, everything else shares
the channel — and that's where the fragility lived.

No pairing is needed on Linux for a normal session: the bond lives in the headset radio and
survives power cycles, USB re-enumerations and OS changes. Turn the controllers on **before**
monado-service starts: they are only surfaced to the runtime while the headset device is being
created, and there is no hotplug path (see "What was broken" and "Auto-sleep" below). Creating
a *new* bond through the headset radio is the part Linux cannot do yet (see "Pairing").

## What was broken (upstream, verified by reading the code on 2026-08-04)

**Connection:**
- A single 250ms timeout per firmware command, with no retry at any level.
  A lost reply (very frequent on a shared channel) = controller NULL **for the entire session**.
- The controller status request was sent ONCE at startup. A controller powered off at
  that moment = invisible forever.
- Wait WITHOUT timeout for the first status: a lost reply would hang the entire startup
  (upstream had it marked with @todo).
- Unconditional 10ms sleep per chunk made the calibration read take seconds —
  widening the failure window.
- On the direct BT transport (other WMR headsets): a transient read error would kill
  the thread permanently while the device remained registered (mute controller).

**Inputs (driver bugs, not even transport-related):**
- Stick with no clamp on the negative end (-1.0005, violates OpenXR) and no deadzone → drift.
- The grip click received the analog value: any light pressure = click.
- **Haptics dead for a double reason**: an output name that the bindings never reference
  + `set_output` never implemented.
- Input timestamps always 0 (breaks OpenXR's `lastChangeTime`).
- Typos: x/y labels swapped in the debug GUI, loop using `inputs[0]` instead of `inputs[i]`.

## What we fixed (`patches/monado/`, see its README for current numbering and upstream MR status, `docs/18`)

| Fix | What it does |
|---|---|
| Inputs | stick clamp+deadzone, correct squeeze_click, haptic output name, timestamps, typos |
| Firmware reads | 3x retry with backoff, pacing 10ms→1ms, leak fix |
| Status wait | bounded startup wait (~10 s) for both controllers, re-requesting status once per second inside the window (`patches/monado/0003`); the periodic re-request was dropped (`docs/18`) |
| Direct BT thread | tolerates transient errors (gives up after 10 in a row) |
| `wmr_controller_hp.c` | missing native remap to `microsoft/motion_controller` (`patches/monado/0011`, below) |

### The native `microsoft/motion_controller` profile never bound anything

Found while verifying the player's thumbstick seek (`docs/02-player-360.md`): the
stick did nothing. `wmr_controller_hp.c` (the HP-specific driver, not the generic
WMR one) identifies itself as `XRT_DEVICE_HP_REVERB_G2_CONTROLLER` and names its inputs
`XRT_INPUT_G2_CONTROLLER_*` — but it only ships remap tables (`binding_profiles[]`) for
the `XRT_DEVICE_TOUCH_CONTROLLER` and `XRT_DEVICE_SIMPLE_CONTROLLER` profiles. It's missing
the one for the native `XRT_DEVICE_WMR_CONTROLLER` profile (the one corresponding to
`/interaction_profiles/microsoft/motion_controller`, what hello_xr and most apps
request for WMR hardware).

`oxr_input.c:get_binding()` only resolves a binding if the device name matches
the direct profile's, **or** if there's a remap table for that profile — with neither of
these two conditions, it silently discards the binding (`profile->xname != xdev->name && xbp == NULL`).
Consequence: on real G2 hardware, **no binding under `microsoft/motion_controller`
ever resolved** — not just the thumbstick, but also grip/squeeze/quit for that profile.
Fix: `wmr_inputs[]`/`wmr_outputs[]` plus an entry in `binding_profiles[]` for
`XRT_DEVICE_WMR_CONTROLLER`, same pattern as the existing touch/simple tables.

**The patch alone was not enough for hello_xr** (verified against
`oxr_interaction_profile_array.c:134-172`): active-profile selection walks
`xdev->binding_profiles[]` **in order** and settles on the first profile the app has
suggested. Entry [0] of the driver is the remap to Oculus Touch (the G2 has X/Y/A/B, which
the WMR profile can't express), so hello_xr — which suggests bindings for Touch —
always gets the `oculus/touch_controller` profile, never WMR. That was also what masked the
bug: pose/grab/quit worked via Touch. The patch matters for apps that only suggest the WMR
profile (the common case for WMR-era apps); for our player the real fix was to mirror its
bindings (seek/pause/recenter) into the `oculus/touch_controller` block of hello_xr.

**Why the WMR profile can't express the G2's buttons:** the generic `microsoft/motion_controller`
OpenXR profile models the *original* WMR controller, which has a circular **touchpad** below the
thumbstick — Acer, Samsung Odyssey, Lenovo Explorer, Dell Visor and the first HP Reverb all
shipped that hardware. **The G2 is the one model in the family that removed the touchpad** for
plain X/Y/A/B buttons — a real physical difference, not a Monado quirk. Monado has two separate
driver files, dispatched by controller PID in `wmr_controller_create()`: `wmr_controller_og.c`
(touchpad, `WMR_CONTROLLER_PID`/`ODYSSEY_CONTROLLER_PID`) and `wmr_controller_hp.c` (this headset's
`REVERB_G2_CONTROLLER_PID`, no touchpad). This chapter is scoped to the G2's own controller;
`docs/62` carries the broader picture for touchpad-equipped controllers.

Two details of the Touch profile: `menu` only exists on the left hand (suggesting it for the
right makes the ENTIRE `xrSuggestInteractionProfileBindings` fail), and `squeeze` only has a
`value` (float) component — a boolean action bound there is legal, Monado applies a 0.7
threshold to it (`oxr_input_transform.c:323-326`).

The player prints, when the controllers connect, the active profile per hand
(`Active profile /user/hand/...`) and the source of each action — for any dead input,
check that first.

Expected net effect of the fixes: controllers connect reliably when powered on before monado-service (a failed fw-read
is retried; controllers that are off at startup are not hot-added), sticks stay centered
without drift, and grip behaves correctly.

## How to verify

```bash
./jack-in.sh 3dof     # controllers on BEFORE launching (no hotplug path)
grep -E "left:|right:" ~/Documents/linux_vr_base/jack-in.log
# should say: left: HP Reverb G2 Left Controller / right: HP Reverb G2 Right Controller

# debug GUI with per-controller panels (live sticks, battery, IMU):
XRT_DEBUG_GUI=1 on the service; see the "WMR HMD" panel and each controller's panel.
```

Connection stress test: 10 service startup cycles with controllers powered on
→ must connect 10/10 (before: ~50%). Stationary sticks must read exactly (0,0).

## What's still missing (and why)

1. **Vibration over the headset tunnel**: the output name now resolves, but the tunnelled wire command
   for the motor is not decoded. Over the host-Bluetooth path the haptics format is known and works
   (Output report id 4, `docs/136`); a `set_output` plumbing patch for the tunnelled path is in
   `patches/monado/unapplied/` (0078).
2. **Positional tracking (6DoF)**: the stock WMR driver is orientation-only by code
   (`position_tracking = false`). The optical **constellation** infrastructure exists upstream
   and builds in our tree; the headset camera separates controller frames (frametype 0x2) and the
   LED geometry is parsed from the controller's own calibration. Wiring, root causes and
   measurements are in `docs/125` and `docs/126`.
3. The deep refactor of fw-read (a state machine in the dispatch instead of stealing the
   stream) — upstream already requests this in an @todo; our retries make it unnecessary in
   practice, but it's the elegant solution to propose in an MR.

## Pairing

### Link model and bonding

Pairing is literal Bluetooth bonding between a controller and the headset radio:

- **The bond lives in the controller + headset radio pair**, one headset at a time ("Motion
  controllers only support being paired to one PC at a time"). It persists through months of power
  cycles, USB storms, port changes and OS changes (verified live: `controller-pair-check.py` reads
  `paired, offline`, VID 045e PID 066a, straight over HID with the service down).
- **Hold the battery-compartment button a few seconds** → the bond is ERASED *and* the controller
  enters discovery (slow LED pulse). From there any G2 can adopt it, like re-pairing a BT peripheral
  to a new phone. The erase is the physical button, never a host command.
- **Adoption is one controller at a time, per hand slot**: Oasis asks for each hand separately
  (*"A Left motion controller is currently paired, would you like to unpair it and pair a new Left
  motion controller now?"*, `docs/31`). Hand slots are fixed by design: the controllers broadcast
  their handedness in their BT names ("Motion controller - Left"/"- Right"), the protocol has
  per-hand channels, and the part numbers differ (right `M09967-001`, left `-002`, `docs/63`).
- **Calibration travels with the controller**: the factory calibration blocks (gyro/accel
  matrices, LED model) live in the controller and are read at every connect (`docs/47` Layer 2),
  so a re-bonded or adopted spare arrives fully calibrated. Controllers are migratable between G2
  units.
- Both controllers keep their factory Bluetooth address across an erase/re-pair; "erase" removes
  only the link key. (The addresses themselves are not reproduced in this repo; placeholders such as
  `<CTRL-BDA-A>` are used below.)

**Bench rule: on a Linux-only bench the pairing button is ONE-WAY.** Do not press it unless a
Windows machine with Oasis is available to re-pair (or the host-adapter route of `docs/136`). If
pairing is ever tested from Linux, do it deliberately: `controller-pair-check.py` before and after,
ONE controller only, a recovery path ready, the other controller left paired as a live control.

**Two ways to get a bond on Linux today:** (a) bond the controllers to a *host* Bluetooth adapter
(works, `docs/136`; Monado's `wmr_bt_controller.c` then drives them, and Oasis/SteamVR does too,
`docs/138`); (b) pair them to the *headset* radio, which still requires Windows/Oasis (this section).

### Reading pairing state

```bash
./scripts/controller-pair-check.py [seconds]   # default 6s
```

Sends the status request (report `0x16`, subtype `0x17`) to the HoloLens Sensors device
(045e:0659) and decodes the response per controller. Works with or without `monado-service`
running (the hidraw can be opened more than once). The `0x17` status packets are actually
**streamed passively** (16 packets in 4 s with zero writes), so the request is not what produces
them. Layout: one packet per controller, byte 2 = `0x0` UNPAIRED, `0x1` OFFLINE, `0x2` ONLINE, followed by VID/PID
once paired (e.g. `17 00 02 5e 04 6a` = left, online, 045e:066a; `17 01 00 00 00 00 00` = right,
unpaired). `unlock_wmr.exe` (the Oasis "unlock" utility) was disassembled with the method of
`docs/09-oasis-driver-re.md`: its only `HidD_SetFeature` call is the same Display Enable command
Monado already sends, plus a ~6 s PnP-polling loop — it is a UI that waits for the controller, and
carries no pair command itself. The pairing traffic comes from Oasis's driver.

### The decoded PAIR protocol (from live Windows USBPcap captures of Oasis pairings)

`wmr_protocol.h` already names the BT-control subtypes, and Monado only ever sends the status query:

```c
/* Messages we can send the G2 via WMR_MS_HOLOLENS_MSG_BT_CONTROL (0x16) */
WMR_BT_CONTROL_MSG_ONLINE_STATUS  = 0x04,
WMR_BT_CONTROL_MSG_PAIR           = 0x05,
WMR_BT_CONTROL_MSG_UNPAIR         = 0x06,
WMR_BT_CONTROL_MSG_PAIRING_STATUS = 0x08,
WMR_BT_CONTROL_MSG_CMD_STATUS     = 0x09,
```

**The command, as seen on the wire (Oasis):**

```
SET_REPORT, bmRequestType 0x21, wValue=0x0316  ->  ReportID 0x16, ReportType FEATURE (3)
wIndex=2 (HoloLens Sensors HID interface), wLength=64
payload: 16 05 <hand> 00 00 ... (61 zero bytes)        hand: 00 = left, 01 = right
```

- Delivery is a HID SET_REPORT over the CONTROL endpoint, which on Linux means `HIDIOCSFEATURE`.
  `os.write()` of report 0x16 does not reach the command handler.
- Interface 2 is the only HID interface; interfaces 3/4 are vendor-specific (a WinUSB binding on
  interface 3 carries fixed-rate IMU/camera streams) and see zero host-initiated commands from
  Oasis. Every control transfer in the 444 s session targets `wIndex 2`.
- Subtypes seen: `16 09 <hand>` (CMD_STATUS) loosely interspersed with the pairing UI events (not a
  tight precursor of PAIR: gaps of 7 s, 28 s, 47 s before, 19 s after); `16 06 <hand>` (UNPAIR) once in
  one capture, left; **`16 07 00`**, undocumented, once, between a failed first attempt and the
  successful retry (a later single clean left pairing needed neither; a probe of `16 07` alone on
  an idle radio is accepted and silent, unknown meaning); the right hand has re-paired directly
  on top of an existing bond with no UNPAIR.
- Host→headset Output report `02 xx 00...` (65 bytes) is a separate channel with the fixed
  vocabulary `{04,06,07,08,0b}`: `02 08` is a dense post-enumeration burst (the config-block reader in
  `wmr_hmd.c`), not a pairing poll or heartbeat; six `02 07` frames bracket the radio's CONNECTED
  event ~8 s after PAIR (a polling-profile refresh on a new HID device, not an enter-pairing-mode
  command). Around PAIR itself (t = -2..+12 s) the only host frames are `16 05` and those `02 07`.

**Host commands in the long two-controller Oasis session** (`unlock_wmr.exe`, t in seconds; the single-hand
captures are consistent with it):

| t (s) | host → radio (report 0x16, Feature only, never Output) | radio-side result |
|---|---|---|
| 182.1 | `16 09 00` (CMD_STATUS, left) | routine status |
| 254.4 | `16 06 00` (UNPAIR, left) | `COMMAND_DELETE_NVRAM_DATA` "special case unbonding device" |
| 276.9 | `16 05 00` (PAIR, left) | inquiry started; `inquiry complete`, nothing found at 283.3 (controller not yet in discovery) |
| 370.4 | `16 07 00` (undocumented) | no attributable log line |
| 373.9 / 380.9 | `16 09 00` / `16 05 00` (retry) | `Found by address: Motion Controller - Left`, RSSI -43, same BT address as before the unbond; CONNECTED at ~389 (new link key) |
| 395.5 / 423.4 | `16 09 01` / `16 05 01` (PAIR, right) | found first try, RSSI -53, CONNECTED at ~431; no UNPAIR was sent for the right hand |

A second capture ("long", next morning) shows `16 09 00`, `16 09 01`, then `16 05 01` (right) with no unpair.

**Oasis's flow** (from its wiki): exit SteamVR → run "unlock" → replug USB when asked → it prompts **per
controller, LEFT first** → hold the hidden button until the slow pulse → OK → repeat for the right →
power-cycle both. Re-run once per computer, per headset, after pairing a new controller, after a Windows
reinstall or a GPU change. Adopting a second-hand spare (`TPC-Q077-C1`/`-C2`, `docs/63`) arrives paired to
someone else's headset or to nothing, so it currently needs this flow.

**The radio-side state machine** (the headset narrates it as ASCII on report `0x05`,
`WMR_BT_IFACE_MSG_DEBUG`, subtype 0x19; report `0x03` carries the firmware log, 8 fixed 63-byte
records after one `Dlo+` magic). One clean left pairing (host `16 05 00` at t=188.331):

| t (s) | event |
|---|---|
| 188.332 | 0x03: `Received pair request MC: 0`, `New pairingStatus: 1` (+1 ms) |
| 188.334-188.339 | 0x05: `COMMAND_SET_VISIBILITY` → `COMMAND_SET_PAIRING_MODE` ("pairing allowed 1") → `COMMAND_INQUIRY` → `inquiry started`, all within ~10 ms of the PAIR write; 0x03 `CmdStatus Success` at 188.341 |
| 189.514 | `Found by address: Motion Controller - Left`, RSSI -48 (1.2 s after the inquiry started) |
| 194.743 | `inquiry complete` (the scan always runs its full ~5.2 s) |
| 194.746-196.620 | `HIDH_COMMAND_CONNECT` → SDP → Product ID `0x066a` → HID service → IO-caps exchange → **new BR/EDR link key** → NVRAM write → encrypted → `CONNECTED`; the controller's own feature reports (`0x4`,`0x7`,`0x8`: config/calibration blobs) are then pulled |

**PAIR-to-CONNECTED is a stable ~8.3 s** (8.27, 8.3, ~7 in three captures). The first attempt in
the long capture timed out (`inquiry complete`, nothing found) because the controller was not yet in
discovery; a retry succeeded. The minimum discovery window has not been characterized.
UNPAIR (`16 06 00`) logs `HIDH_COMMAND_VIRTUAL_UNPLUG` / `COMMAND_DELETE_NVRAM_DATA`, then ~20 s of
`BTM_PAIRED_DEVICE_LINK_KEYS_REQUEST_EVT` as the old bond retries.
The `0x17` status flips UNPAIRED → OFFLINE → ONLINE within ~50 ms of the link-key event
(`17 00 00 00 00 00` → `17 00 01 5e 04 00` → `17 00 02 5e 04 6a`), a tight cross-check for
any future capture.

**The "provisioning preamble" is not a host command.** At every enumeration the radio log shows
`COMMAND_SET_LOCAL_BDA` (`WMR Embedded Host Address [<CTRL-BDA-C>]`), `COMMAND_SET_LEFT_REMOTE_BDA`
(`Provisioned MC_LEFT <<CTRL-BDA-A>>`), `COMMAND_SET_RIGHT_REMOTE_BDA` (`Provisioned MC_RIGHT
<<CTRL-BDA-B>>`), `HIDH_COMMAND_ADD` and `COMMAND_PUSH_NVRAM_DATA`. In both windows of the capture
the only host→device frames are string-descriptor boilerplate, empty interrupt re-arms and one
content-free `SET_IDLE`: the WICED radio is reloading its own NVRAM at chip init, not receiving a push.
Windows re-enumerates the sensors device too (address 2 → 5), so this appears once per enumeration.

**Capture-decoding recipe.** tshark exposes HID-class setup fields under `usbhid.setup.*`
(`bRequest`, `wValue` with `ReportID`/`ReportType`, `wIndex`, `wLength`), not `usb.setup.*`; the SET_REPORT
payload is in `usb.data_fragment` (`usbhid.data` / `usbhid.data.report_id` also work), not
`usb.capdata`. Filter `usb.bmRequestType==0x21 and usb.bus_id==2 and usb.data_fragment`, list the
distinct first-byte prefixes: the `0x16` frames stand out from the `02 08` noise (>99% of traffic).
`usbhid.data.report_id==5` recovers the radio's debug log as ASCII, `==3` the firmware log.
`usbmon` (`/sys/kernel/debug/usb/usbmon`) shows the setup bytes of what Linux itself sends, but cannot
decode an existing Windows capture. Captures are large (0.4-1.5 GB) and are not committed.

### Negative results: PAIR from Linux does not start the inquiry

`controller-pair.py` sends `{0x16, 0x05, hand}` and is the harness (correct bytes, correct delivery,
resilient reopen, passive watch). On a genuinely unpaired controller in discovery (slow pulse) it
**never pairs**: the radio's 0x05 log stays completely silent for 35-40 s windows, where Windows' identical
write produces `inquiry started` within 10 ms. Ruled out, each checked against the Windows capture
or on the wire:

- **Command bytes** (`16 05 01` / `16 05 00`): identical to Oasis.
- **Report type** (Feature vs Output), **report size** (64 bytes), **`wLength`** (64), **interface/`wIndex`** (2): identical.
  Report 0x16 is declared Output, Feature and Input in the descriptor; both control variants were tried.
- **Delivery path**: `usbmon` shows our send as `21 09 0316 0002 0040`, completion status 0, all 64 bytes
  transferred, byte-for-byte the Windows frame. The device ACKs it at the USB level and the firmware
  still does not act on it; a clean ACK does not mean dispatch.
- **Ordering and polling**: a `16 09` before PAIR, sustained `02 08` polling, single-shot, sustained
  resend, active polling, and fire-once-then-listen (each SET_REPORT re-enumerates the radio, so
  hammering interrupts a pairing in progress) all fail. A bug in an early harness (sending `02` as
  Feature, rejected on every send and forcing a re-enumeration loop) was fixed and the negative held.
- **Other USB devices/interfaces**: the presence device (03f0:0580) exchanges only a firmware-version
  query (`50 01` → ASCII `QA85QAPV1`, `QA85QBLV1`, `QA85QDPV1`) and a pair of `04 01` / `04 00`
  Display-Enable-shaped reports early on, and is silent around every PAIR; the `col01/02/03` nodes
  are Windows PnP collections inside interface 2.
- **Enum values past 0x17 looked inert** in an early `os.write` probe (all answered by the same `0x17`
  stream): that probe never reached the command handler (see delivery above) and proves nothing about
  the subtypes.
- **Enter-pairing-mode second command**: `MotionControllerHid.dll` / `MotionControllerSystem.dll`
  (the Microsoft "CrystalKey" WMR driver stack in the same DriverStore package as `HoloLensSensors.dll`)
  contain `bth_pairingProcessSendEnterPairingMode` and a gated "paired" flag in WPP-trace strings with
  no code references (a PDB/TMF would be needed), and `MotionControllerHid.dll` imports no
  `HidD_SetFeature` (it writes Output reports via async `WriteFile`). The capture shows no such command
  on the wire ("`02 xx`" traffic around PAIR is only the `02 07` connect refresh), so this lead is
  not supported.
- **Windows Settings → Bluetooth → Add device** pairs to the PC's own radio and is not the Oasis path
  (`docs/31`).

The gap is therefore not in anything visible at the USB layer. What is left is either host-side
driver or session state invisible to USBPcap/usbmon, or radio-internal state.
**Untried leads** (desk research of 2026-10-10; no PAIR was sent):

1. **Oasis 1.0.4 ships a Linux `pair_bluetooth.sh` launch option** (Steam app 3824490,
   "to pair motion controllers on Samsung Odyssey+, HP Reverb and HP Reverb G2"; the Oasis wiki says it
   works like the controller part of the Windows unlock). Not read yet. Toemmsen's Wine patch
   (`Toemmsen96/oasis-bt-patch`) concerns already-paired controllers, not PAIR.
2. **thaytan's wmr-utilities** (`gitlab.freedesktop.org/thaytan/wmr-utilities`, `hp-reverb-g2-pairing.c`,
   BSL-1.0): sends `16 05 <0|1>` once as a 64-byte Feature report, then polls `16 09 <n>` and reads the
   reply flag (0 complete, 1 pending, 3 in progress, 2 failed, 4/5 paired, 6 unpaired), then `16 08` /
   `16 04` for MAC/VID/PID/online. Same wire bytes as ours; the differences are the access path
   (default hidapi-**libusb**, which detaches usbhid and claims the interface, where we always used
   hidraw with usbhid bound) and that it reads the `0x16` replies. A flag-0 reply prints "completed"
   with no message and send errors are not checked, so only the final MAC/VID line proves success.
3. **None of our Linux attempts decoded the 0x03 firmware log or the 0x16 replies**, so "the MCU never
   dispatches the command" and "it dispatches and declines" are still indistinguishable.
   `scripts/controller-pair-v2.py` has a reader thread started before any send, decoding 0x03 (all 8
   records), 0x05, 0x16 and 0x17 into JSONL + console. Modes: `--listen`, `--status L|R`,
   `--single-pair L|R` (exactly one `16 05`, gated by `--i-understand-this-erases-the-current-bond`;
   `16 06`/`16 07` are refused at the send layer), `--windows-preamble` (replays the capture's host setup
   before PAIR), `--dry-run`, `--selftest PCAP` (17/17 against the reference capture). The `16 08` reply
   layout is taken from wmr-utilities' struct and is unverified.

**Plan, cheapest first** (one controller in discovery, Monado stopped; a controller that pairs leaves
its host-adapter bond, `docs/136` has the way back): (a) `--single-pair` watching 0x03; (b) wmr-utilities
`--pair 0 -v` with both backends; (c) `--windows-preamble`; (d) read Oasis's `pair_bluetooth.sh`.
`controller-pair.py` never wires UNPAIR (unknown bond/slot semantics; the erase is always the physical
button); `scripts/controller-pair-btlog.py` reads the 0x05 log live.

## Battery status

**The raw data already exists; the question is only surfacing it.** `wmr_controller_hp.c` and
`wmr_controller_og.c` read a raw `uint8_t battery` from the controller's HID input report
(`last_input->battery = read8(&p)`), originally exposed only through the debug GUI
(`u_var_add_u8(..., "input.battery")`; `patches/monado/0040` now also feeds it to `libmonado`, below). `wmr_hmd.c` has no battery handling, as expected for a
wired headset.

- **Monado's internal plumbing**: `xrt_device::get_battery_status(xdev, out_present, out_charging,
  out_charge)` is wired to IPC and to `libmonado` (`mnd_root_get_device_battery_status`), but every
  driver fell back to the not-implemented stub. `patches/monado/0040` wires the parsed byte into it
  (`out_charge = raw / 255`), so `libmonado` clients can query it. `scripts/controller-battery-check.py`
  is the consumer, run from `vr-launcher.py` after Monado comes up and before the game/player starts.
  Motivation: a live session went unnoticed with a dying right-controller battery until its optical
  tracking starved (dimmer LEDs, fewer blobs) and that hand anchored meters off.
- **Nothing reaches OpenXR.** The real extension is `XR_EXT_interaction_profile_battery_state_display`
  (`XR_EXT_battery_status` does not exist); Monado has no entry for it and the headers are already
  vendored, so it would need implementing in Monado's OXR layer from scratch. Only needed if something
  in-headset (a per-controller colored light, a HUD) should show battery; the pre-session `libmonado`
  check does not need it.
- **The byte-to-fraction scale is 0-255.** Confirmed in `docs/46`: Windows' own HID scaling,
  `(raw*100)/255`, equals Monado's `raw/255.0f` (patches `0040`/`0079`). What the byte means
  physically (cell chemistry, charge curve) is covered in `docs/46`. `scripts/controller-battery-check.py`
  displays percent against a visual ceiling of 208 (`min(100, raw/208)`), because raw/255 showed a
  brand-new cell as a misleading 82 %; the driver logs every change of the raw byte.
- **The Windows `using_1v2_batteries` setting** (a literal config key in `driver_oasis.dll`, found with
  `strings` + `objdump` via `scripts/xref.py`, no decompiler) gates a choice between two cached lookups
  whose result is multiplied (`mulss`) into the battery reading before it is reported as a device
  property. It reads as a chemistry *display calibration curve* (alkaline AA vs 1.2 V NiMH rechargeable
  discharge differently), not a functional setting: nothing around it touches tracking, pairing or haptics.
  Pinning down the report descriptor's logical min/max would settle the scale; not chased further.

## Auto-sleep / standby (observed, not protocol-captured)

A controller left motionless for ~15 minutes powers itself off (LED off); its solves before that point
degrade to garbage near-origin poses (1.4-1.7 px reprojection error, fitting ambient IR blobs instead of the
constellation pattern; the constellation gravity gate correctly rejects them). Re-attach of an
already-registered controller after a mid-session power-on works without a Monado restart (distinct
from the finding that *unregistered* devices at startup are not hot-added).

This is almost certainly deliberate power saving (standard for wireless VR controllers), not a defect.
No HID command or protocol byte for it has been captured: `docs/12` only documents the panel's power
on/off (`SET_FEATURE {0x04, 0x01}` / `{0x04, 0x00}`). "It's protection" is an inference from industry
behavior plus the observed symptom; a `capture-hid.sh`-style capture spanning a sleep transition would
settle it.

## Controller orientation: right hand solved, left hand nearly there

The long-standing orientation debt (constellation-fed orientation wrong for one hand) was diagnosed
with two instruments this project now treats as standard:

1. **Labeled-motion capture**: still 10 s → several reps of pure pitch → still → pure roll → still →
   pure yaw → still, per hand, with `WMR_CONTROLLER_CALIBRATION_LOG=1`, segmented offline by gyro
   magnitude into a per-phase dominant-axis table. A plain live A/B tried first only burned a candidate
   and taught the lesson that composing rotations can never fix a reflection.
2. **Figure-8 test**: a real 3D figure-8 traced by the wearer's hand while watching the gizmo. It
   separates a **constant offset** (the figure-8 closes, just rotated) from **precession** (it winds up
   extra turns and never closes), which no static or single-motion capture can tell apart.
   Both instruments need the controller-pose gizmo to render correctly, which required fixing a
   per-face-color mesh bug in the player (`patches/hello_xr-player/0016`, `0018` and `0019`: gizmo, per-axis
   colours and positive-tip caps that make handedness readable at a glance).

**Right hand: correct.** The raw fused orientation already matches the OpenXR grip convention
(pitch +X, roll -Z, yaw +Y; R = identity). Its only defect was the missing absolute yaw reference
(below); with that fixed it was fully correct for the first time.

**Left hand: dominant defect fixed, small residual.** The left controller matches the right on pitch and
roll but is yaw-inverted: two axes correct, one sign-flipped, a **reflection** (determinant -1). A fixed
quaternion composed onto the output can never fix that (a composition of proper rotations is proper),
which is why the earlier A/B menu (live axis transforms, a plain conjugate) never worked.
`WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT` (`patches/monado/0062`) negates the left controller's
calibrated gyro Y before fusion. Logging both hands' factory calibration matrices and determinants
showed **all eight proper**, so the reflection is not a recoverable factory-calibration artifact; its
origin (raw ADC axis wiring, or a per-hand frame convention Microsoft handles driver-side) is unknown.
Extending the negation to the accelerometer (reasoned from a frame-reconciliation algebra) was reverted
(`patches/monado/0064`) after the figure-8 showed the two-sensor version precesses while gyro-only closes.

**Heading, not axes, was what remained.** With no magnetometer nothing anchors yaw the way gravity anchors
pitch/roll, so boot attitude was adopted as heading. `WMR_CONTROLLER_SOLVE_YAW_CORRECT`
(`patches/monado/unapplied/0066`) nudges fusion's heading toward gate-accepted constellation solves
(reusing the Rx180 gravity-gate bridge of `unapplied/0047`), gain-limited and capped per step. First
hardware contact caught two bugs, an unwrapped yaw error stepping the long way around the circle and
near-pure-yaw ghost solves un-locking a good heading, both fixed in `unapplied/0067`. After the fix both
controllers converge and lock: right to `0.0°` in 140 corrections, left to `-0.1°` in 240.

**What is left**: before the matrix fit, the left controller's figure-8 drifted slowly about a combined phantom axis, a few
degrees of cross-axis misalignment beyond the sign flip that integrates over a multi-turn motion yet is
imperceptible in a static capture. The turntable/cradle fit of the left gyro matrix was done and shipped as
`patches/monado/0071` (`WMR_CONTROLLER_LEFT_GYRO_FIT`) together with `0062`, leaving a residual of about 4 degrees
(RMS 4.25 degrees at fit; see `docs/47`). The heading-correction experiments `0066`/`0067` remain
unapplied (`patches/monado/unapplied/`). Position acquisition
slowness remains the separate constellation-matching thread (`docs/125`, `docs/126`).
