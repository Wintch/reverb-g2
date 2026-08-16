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

## Battery status (investigated 2026-08-09, wired 2026-08-13)

**UPDATE 2026-08-13:** the "small, same-pattern fix" this section used to end on is now
written — `patches/monado/0040` (not yet rebuilt/verified on real hardware; see the
patches README entry). It wires the already-parsed `last_inputs.battery` byte into
`xrt_device::get_battery_status`, so `libmonado`'s `mnd_root_get_device_battery_status`
can query it without needing the OpenXR extension work described below at all — that
extension is still not implemented and still not needed for this. Real motivation: a
live session went unnoticed with a dying right-controller battery until its optical
constellation tracking starved (dimmer LEDs, fewer detected blobs) and the wearer saw
that hand anchored meters off, with no warning before the session started.
`scripts/controller-battery-check.py` is the consumer side, run from `vr-launcher.py`
right after Monado comes up and before the game/player launches. **The byte-to-fraction
scale is explicitly unverified** — nothing found anywhere (this tree, the Windows HID
capture in `docs/09`, any WMR community writeup) documents whether the raw byte is
already a 0-100 percentage, a raw ADC count, or something else; `out_charge = raw / 255`
is the least-committal reading, not a confirmed calibration, and the driver now logs
every time the raw byte changes specifically so the real scale can be worked out later
against a genuine charge/discharge cycle. The rest of this section, below, is the
original investigation and is still accurate as background.

**New lead on the scale question, same day, from a direct user question** ("hay un
setting en Windows que indica si es pila 1.2V recargable o 1.5V comun -- sospecho que
aparte de reflejarlo en % de carga no hace nada"). Searched this whole repo first for a
prior note matching that -- found none (`docs/pruebas.jsonl` T104's battery
investigation and `docs/02`'s roadmap entry are the only prior mentions, neither
mentions battery chemistry), so if it was written down before, it isn't in this repo.
Investigated directly instead, using a real local copy of the Windows Oasis driver
(`/mnt/videos/SteamLibrary/steamapps/common/Oasis Driver for Windows Mixed Reality/
bin/win64/`, same disassembly method as `docs/09-oasis-driver-re.md`, via
`scripts/xref.py`):

- `driver_oasis.dll` contains the literal config key string `using_1v2_batteries`
  (a real Windows setting, not a guess), read via a generic config-lookup call right
  next to the code that reads the controller's HID battery field. The disassembly
  shows that boolean gating a choice between two different cached lookups (two
  distinct GUID-shaped queries), whose result is multiplied (`mulss`) into the battery
  reading before it's reported onward as a device property. **The user's suspicion is
  confirmed to the extent this disassembly shows it**: nothing in the surrounding
  function touches tracking, pairing, or haptics -- it reads as a battery-chemistry
  *display calibration curve* (alkaline AA and NiMH rechargeable have different
  voltage-discharge curves for the same remaining charge, so converting a raw
  voltage/ADC reading to an accurate percentage needs to know which curve to apply),
  not a functional setting. Caveat: this is `strings` + `objdump` + manual reading, no
  decompiler -- confident, not 100% proven.
- Same driver reads the value via the **standard USB HID usage** `Generic Device
  Controls (page 0x06) / Battery Strength (usage 0x20)`
  (`HID_USAGE_PAGE_GENERIC_DEVICE` / `HID_USAGE_GENERIC_DEVICE_BATTERY_STRENGTH` in the
  strings), which the HID spec defines as a percentage -- a real, if indirect, hint
  that the *scale* question in `patches/monado/0040`'s big caveat leans toward
  already-normalized rather than a raw 0-255 ADC count. `HololensSensors.dll` (the
  DLL that actually speaks the wire protocol, same one `docs/09` already used) has a
  matching `COMMAND_SET_BATTERY_LEVEL 0x%x` trace string, very likely the same field
  `wmr_controller_hp.c` calls `battery`, named "level" rather than "voltage" or "adc".
- **Not chased further, deliberately**: pinning down the exact logical min/max the
  device's own HID report descriptor declares for that field (which is what would
  actually settle the scale) needs either the raw report-descriptor bytes or decoding
  the two chemistry-curve constant blobs referenced above -- real next-session work if
  the scale still matters once `patches/monado/0040` has a real charge/discharge log to
  correlate against. `out_charge = raw / 255` in that patch is left as-is, not flipped
  to `/100`, specifically because the failure mode of guessing wrong is asymmetric:
  under-reporting (255-scale on a truly 0-100 field) makes the low-battery alert fire
  EARLY, which is annoying but safe; over-reporting the other way would make it miss a
  real low battery, which is the whole point of building this. Safer wrong guess, not a
  confirmed one.

**The raw data already exists — it's just never surfaced anywhere an application can see
it.** Came up from a player-side feature idea (a colored light per controller — red/yellow/
white — drawn at its tracked position when a session starts). Investigated whether Monado
exposes battery level at all before promising anything.

**Nothing reaches OpenXR today.** The real spec extension is
`XR_EXT_interaction_profile_battery_state_display` (not `XR_EXT_battery_status`, which
doesn't exist) — Monado's `oxr_extension_support.py` (the master list it generates dispatch
from) has no entry for it, and nothing in `src/xrt/state_trackers/oxr/` mentions battery at
all. The headers to build against it ARE already vendored
(`src/external/openxr_includes/openxr/openxr.h`, matching the SDK this project builds
`hello_xr` against) — the extension would need implementing in Monado from scratch, it's not
a missing build dependency.

**Monado has its own internal battery plumbing, but no driver implements it.**
`xrt_device` (`src/xrt/include/xrt/xrt_device.h`) has a `get_battery_status(xdev,
out_present, out_charging, out_charge)` vtable slot, wired through to Monado's own IPC
(`ipc_handle_device_get_battery_status`) and `libmonado`'s monitoring API
(`mnd_root_get_device_battery_status`) — this is Monado's introspection/telemetry tooling,
separate from OpenXR entirely. Every device currently falls back to the stub
`u_device_ni_get_battery_status()` (`u_device_ni.c:186`), which just reports
not-implemented.

**The G2 controllers' own driver already parses the byte and throws it away.** Both
`wmr_controller_hp.c` (the HP Reverb G2 controllers specifically) and `wmr_controller_og.c`
read a raw `uint8_t battery` straight out of the controller's HID input report
(`wmr_controller_hp.c:277`, `last_input->battery = read8(&p);`, stored in the
`last_input`/`last_inputs` struct). It's only ever surfaced through Monado's generic debug-
variable system (`u_var_add_u8(..., "input.battery")`, viewable live in `monado-gui`) — never
wired into `get_battery_status`, never reaches an application. `wmr_hmd.c` has no battery
handling at all, which is expected — the G2 headset itself is USB/wired-powered, no battery
to report.

**What real work this would take, if picked up:** two changes, both in `~/vr/monado`, not
`hello_xr`: (1) normalize the already-parsed `last_input.battery` byte into a real
`get_battery_status` implementation for the WMR controller driver — **done 2026-08-13,
`patches/monado/0040`, not yet rebuilt/verified, see the update at the top of this
section**; (2) implement `XR_EXT_interaction_profile_battery_state_display` in Monado's
OXR layer from scratch (it doesn't exist there today) so an application (`hello_xr`, an
in-game HUD light) can query it. (1) alone was enough for the startup-validator alert,
since that goes through `libmonado` directly, not through an OpenXR extension — (2) is
only needed if something in-headset (not just the pre-session console) should ever show
battery. Only after both land does drawing anything in `hello_xr` become possible.

**Deliberately bundled with real controller position (6DoF) tracking, not started now.**
The player-side design (a light drawn AT the controller's actual position in space) is only
meaningful once controller position tracking is real — today controllers are 3DoF-only
(rotation, no real position; see "What's still missing" above and the paused constellation-
tracking effort). User's call: test this together with that work once it resumes, not as a
standalone task now.

## Auto-sleep / standby (observed, not protocol-captured)

**Symptom, first noted 2026-08-13 (T181)**: a controller left motionless for ~15 minutes
powers itself off — LED off, and its solves before that point degrade to garbage
near-origin poses (1.4-1.7 px reprojection error, fitting ambient IR blobs instead of the
real constellation pattern; the constellation gravity gate correctly rejects these too).
Re-attach of an already-registered controller after a mid-session power-on works without a
Monado/service restart (distinct from T043's no-hot-add finding, which is about
*unregistered* devices at startup, not this).

**Almost certainly deliberate power-saving, not a defect** — this is standard behavior
across essentially every Bluetooth-class wireless VR controller (Oculus/Meta Touch, Vive
wands, PSVR, and WMR motion controllers specifically), all of which auto-sleep after
inactivity to avoid draining the battery with the controller left idle. Worth stating
plainly so it doesn't get chased as a bug: it very likely isn't one.

**What's genuinely NOT established, so this isn't overclaimed**: no HID command or protocol
byte for this has ever been captured from this project's own data. `docs/12`'s protocol
reference only documents the **panel's** power on/off (`SET_FEATURE {0x04, 0x01}` /
`{0x04, 0x00}`) — nothing about a controller-side sleep timer or wake command. "It's
protection" is a well-grounded inference from general industry knowledge plus the observed
symptom (LED off, clean re-attach, no crash), not something read off the wire here. If this
is ever worth pinning down precisely, a `capture-hid.sh`-style USB capture spanning a
controller's actual sleep transition would be the way to get a real answer instead of an
inference.
