# 03 — G2 WMR Controllers: current status, fixes, and roadmap

## How the controllers communicate

The G2 controllers do NOT talk Bluetooth to the PC: they are factory-paired with the
headset's internal radio, and their packets travel **tunneled through the same HID stream**
that carries the headset's IMU, camera timestamps, and status (`wmr_hmd_controller.c`).
Key consequence: during firmware/calibration reads for a controller, everything else shares
the channel — and that's where the fragility lived.

No pairing needed on Linux. Just turn them on (and with our patches, it no longer
matters if they're turned on after monado-service starts — see below).

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

## What we fixed (patches/monado/0001-0008; renumbered 2026-08-05 when splitting them into 4 upstream MRs, see docs/18)

| Patch | What it does |
|---|---|
| 0003 | Inputs: stick clamp+deadzone, correct squeeze_click, haptic name, timestamps, typos |
| 0004 | 3x retry with backoff on firmware reads + pacing 10ms→1ms + leak fix |
| 0005 | Status re-request every 5s while a controller is missing + bounded startup wait (3s) |
| 0006 | Direct BT thread tolerates transient errors (gives up after 10 in a row) |
| 0007 | `wmr_controller_hp.c`: missing native remap to `microsoft/motion_controller` (see below) |

### 0007 — the native `microsoft/motion_controller` profile never bound anything (2026-08-06)

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
ever resolved** — not just the new thumbstick, but also grip/squeeze/quit for that profile.

**Second pass (same day, verified against
`oxr_interaction_profile_array.c:134-172`):** the patch above is correct but was NOT
enough for hello_xr, because active-profile selection walks
`xdev->binding_profiles[]` **in order** and settles on the first profile the app has
suggested. Entry [0] of the driver is the remap to Oculus Touch (the G2 has X/Y/A/B, which
the WMR profile can't express), so hello_xr — which suggests bindings for Touch —
always gets the `oculus/touch_controller` profile, never WMR. That was also what was
masking the bug: pose/grab/quit worked via Touch. Patch 0011 is valid for apps that
only suggest the WMR profile (the common case for WMR-era apps); for our player the
real fix was to mirror the player's bindings (seek/pause/recenter) into the
`oculus/touch_controller` block of hello_xr. Watch out for two details of the Touch profile:
`menu` only exists on the left hand (suggesting it for the right makes the ENTIRE
`xrSuggestInteractionProfileBindings` fail), and `squeeze` only has a `value` (float)
component — a boolean action bound there is legal, Monado applies a 0.7 threshold to it
(`oxr_input_transform.c:323-326`).

The player now also prints, when the controllers connect, the active profile per hand
(`Active profile /user/hand/...`) and the source of each action — for any dead input,
check that first.

Monado fix: added `wmr_inputs[]`/`wmr_outputs[]` + an entry in `binding_profiles[]` for
`XRT_DEVICE_WMR_CONTROLLER`, same pattern as the existing touch/simple tables
(exported as `patches/monado/0011`).

Expected net effect: controllers always connect (even if a fw-read fails, it retries;
even if they're off at startup, they show up when turned on), sticks stay centered
without drift, and grip behaves correctly.

## How to verify

```bash
./jack-in.sh 3dof     # controllers on before OR after, no longer matters
grep -E "left:|right:" ~/Documents/linux_vr_base/jack-in.log
# should say: left: HP Reverb G2 Left Controller / right: HP Reverb G2 Right Controller

# debug GUI with per-controller panels (live sticks, battery, IMU):
XRT_DEBUG_GUI=1 on the service; see the "WMR HMD" panel and each controller's panel.
```

Connection stress test: 10 service startup cycles with controllers powered on
→ must connect 10/10 (before: ~50%). Stationary sticks must read exactly (0,0).

## What's still missing (and why)

1. **Vibration**: the output now resolves, but the wire command for the motor isn't
   documented anywhere in the Monado tree and we're not going to invent bytes against a
   firmware. Possible sources: USB captures on Windows (usbpcap) or thaytan's tree.
2. **Positional tracking (6DoF)**: the WMR driver is orientation-only by code
   (`position_tracking = false`, hardcoded position). BUT the **constellation tracking**
   infrastructure (optical LED-based tracking) already exists upstream, compiles in
   our build (`libconstellation.a`), the headset camera already separates controller
   frames (frametype 0x2 — today they die in a debug sink), and the LED geometry is
   already parsed from the controller's own calibration and discarded. What's missing is
   wiring it up: ring occlusion model, moving-camera mosaic, and camera/IMU temporal
   alignment. There are two reference drivers in the tree (rift, pssense) and a fork that
   has it working for WMR (thaytan `dev-constellation-controller-tracking`, the base for
   Project-VR's work). This is THE big next step after 90Hz.
3. The deep refactor of fw-read (a state machine in the dispatch instead of stealing the
   stream) — upstream already requests this in an @todo; our retries make it unnecessary in
   practice, but it's the elegant solution to propose in an MR.

## Pairing (investigated 2026-08-06)

Origin: the controllers have a small button hidden inside the battery compartment.
Pressing it unpairs them from the headset. The question was whether a tool is needed on
Linux to re-pair them, and what protocol it speaks.

**Conclusion, with evidence (not a hypothesis):**

- Pairing status is queried with a normal HID command to the same Hololens Sensors
  device (045e:0659) that Monado already uses — there's no Bluetooth involved anywhere
  (not even from the host: this machine has no BT hardware, `systemctl is-active bluetooth`
  → inactive, and it doesn't matter). Protocol read directly from Monado's
  `wmr_hmd.c`/`wmr_protocol.h`: report `0x16` with subtype `0x17`
  (`WMR_MS_HOLOLENS_MSG_CONTROLLER_STATUS`) requests status; the response arrives as
  report `0x17`, one packet per controller, with `UNPAIRED` / `OFFLINE` / `ONLINE`
  (plus VID/PID if paired).
- **There's no proprietary "pair" command to send over USB.** `unlock_wmr.exe` (the
  "Procedure to unlock headset and controllers for Oasis" referenced by the Oasis wiki,
  see below) was examined with the same binutils method from `docs/09-oasis-driver-re.md`:
  its only `HidD_SetFeature`/`HidP_SetUsageValue` call site sends exactly the same
  "Display Enable" command (Usage Page 0x03 / Usage 0x21) that Monado already sends —
  nothing new. The rest of its relevant imports are `SetupDiGetClassDevsW` /
  `CM_Get_Device_Interface_ListW` (PnP device enumeration) with a ~6s polling loop
  (`Timeout pairing %s motion controller` if it doesn't show up in time) — it's a UI that
  waits for the controller to appear, not something that triggers pairing.
- **The pairing handshake happens entirely through the headset's internal radio**,
  triggered by the controller's physical button: holding it down until the LED
  starts pulsing slowly enters discovery mode, and the headset resolves it in firmware,
  without the host sending anything special. Procedure documented in the Oasis wiki
  (`Pairing-Motion-Controllers`): turn on the controller (Windows button), open the
  battery compartment, hold the small button until the slow pulse.

**Practical consequence:** there's no need to write a "linker/pairer" — the procedure
is purely physical and OS-independent. The only thing missing on the Linux side was the
ability to *verify* the state before/after, which is what the checker below does. If the
hidden button is ever tested, running the checker before and after should show the
`UNPAIRED → OFFLINE/ONLINE` transition without needing any other software.

### Pairing checker

```bash
./scripts/controller-pair-check.py [seconds]   # default 6s
```

Sends the status request (report `0x16`/subtype `0x17`) directly to the Hololens
Sensors device and decodes the response per controller. Works with or without
`monado-service` running (the hidraw can be opened more than once in parallel). Tested
2026-08-06 with both joysticks off: correctly reported `vinculado, offline` with the
controller's real VID:PID (045e:066a) for both left and right — confirms the protocol
read is correct.

Source of the investigation: `docs/09-oasis-driver-re.md` (same disassembly method,
applied to `unlock_wmr.exe` instead of `driver_oasis.dll`/`HololensSensors.dll`).
