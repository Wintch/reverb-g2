# 03 — G2 WMR Controllers: current status, fixes, and roadmap

## How the controllers communicate

The G2 controllers do NOT talk Bluetooth to the PC: they talk **real Bluetooth to the
headset's internal radio** (FCC filing: band 2402-2480 MHz, 0.015 W, "controllers' Bluetooth" —
`docs/10`), and their packets travel **tunneled through the same HID stream**
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
  device (045e:0659) that Monado already uses — no **PC-side** Bluetooth is involved
  (this machine has no BT hardware, `systemctl is-active bluetooth` → inactive, and it
  doesn't matter). *(Corrected T235: this line used to say "no Bluetooth involved anywhere",
  which conflated the host with the link — the controller↔headset link IS real Bluetooth,
  2402-2480 MHz per the FCC filing; it is only invisible to the PC.)* Protocol read directly from Monado's
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

### Addendum 2026-08-20 (T234): the operational record disagrees — treat the button as ONE-WAY until tested with a safety net

The conclusion above — *"purely physical and OS-independent, no host tool needed"* — came from
string/import analysis of `unlock_wmr.exe` and **was never hardware-tested** (the section itself
says so: *"if the hidden button is ever tested…"*). The user's operational record, stated
2026-08-20, points the other way: **controller pairing is one of the two things Oasis actually
provides** (the other being a relaunch to reassign the USB port), **Linux has no pairing path at
all**, and the physical button **erases** the assignment.

What each side of the record actually establishes:

- **Agreed by both**: the battery-compartment button ERASES the pairing. That part is not in
  dispute, and it is the dangerous half.
- **The 2026-08-06 analysis** proved only that `unlock_wmr.exe` sends no pair command — it did
  *not* analyze Oasis's own pairing flow (`docs/31` shot 3 captures Oasis driving an
  unpair/re-pair dialog: *"would you like to unpair it and pair a new Left motion controller
  now?"*), and a wait-UI in one binary does not prove no host trigger exists in another.
- **This repo's own Windows checklist** (`docs/31`, fresh-machine step 4) pairs controllers via
  *Windows Settings → Bluetooth → Add device* with the button held — a third host-side path. So
  the record already contains **two Windows-side pairing flows and zero Linux ones**.

**Operational rule until this is settled: on a Linux-only bench, the pairing button is ONE-WAY.
Do not press it unless a Windows machine with Oasis is available to re-pair.** If the
OS-independent hypothesis is ever tested, do it deliberately: `controller-pair-check.py` before
and after, ONE controller only, Windows ready as recovery. If the hypothesis holds
(`UNPAIRED → ONLINE` with no host involved), Linux loses its last controller dependency; if it
fails, you have lost nothing you could not restore.

**Why this matters beyond caution**: spare controllers exist and are cheap
(`TPC-Q077-C1`/`M09967-001` right, `-C2`/`-002` left — `docs/63`), and a second-hand spare
arrives paired to *someone else's headset* or to nothing. Today, adopting one **requires a
Windows session**. That is the last named Windows dependency in this project. If it ever needs
killing, the RE target is Oasis's pairing flow, same method as `docs/09`.

**Verified live 2026-08-20 (T234)**: with the service down, `controller-pair-check.py` read both
controllers as `paired, offline` (VID 045e PID 066a) straight over HID. Two facts fall out: the
pairing *state* is fully readable from Linux at any moment, and **the pairing itself persists in
the headset's radio** — through months of power cycles, USB storms, port changes and two
operating systems. What Linux cannot do is *create* one; the table of Oasis functions and their
Linux equivalents is in `docs/31`.

### RESEARCHED IN DEPTH 2026-08-20 (T235, agent sweep): the pairing command EXISTS, unused, in Monado's own header

The "purely physical, OS-independent" hypothesis and the operational record are now reconciled,
and the answer is better than either: **the host arms the headset's radio with a documented
command, and Monado already knows it.** `wmr_protocol.h`, in our own tree:

```c
/* Messages we can send the G2 via WMR_MS_HOLOLENS_MSG_BT_CONTROL (0x16) */
WMR_BT_CONTROL_MSG_ONLINE_STATUS  = 0x04,
WMR_BT_CONTROL_MSG_PAIR           = 0x05,   // <- never sent by any code path
WMR_BT_CONTROL_MSG_UNPAIR         = 0x06,   // <- never sent by any code path
WMR_BT_CONTROL_MSG_PAIRING_STATUS = 0x08,
WMR_BT_CONTROL_MSG_CMD_STATUS     = 0x09,
```

The only sender in the whole driver is the status query (`wmr_hmd.c:2445`). So the wire format
for **pair and unpair is already reverse-engineered and sitting unused** — Linux pairing is not
impossible, it is *unimplemented*, with the target enum named in the header. The research swept
Monado's gitlab, OpenHMD (issue #232 is an unanswered stub) and the forums: **nobody, anywhere,
has ever paired WMR controllers from Linux.** A scoped, unclaimed feature.

**The corrected model** (supersedes the 2026-08-06 "no host involvement" hypothesis — that
analysis looked at `unlock_wmr.exe`, which indeed sends nothing, but Oasis's *pairing flow* is a
different code path): host sends `{0x16, 0x05}` to arm the radio → controller enters discovery
via the button (slow pulse) → conventional BT bond forms. Microsoft's own guide confirms the
bond semantics: *"Motion controllers only support being paired to one PC at a time"* — a
single-peer bond living in the controller and the radio, like any BT peripheral.

**Oasis's flow, from its wiki (primary source, fetched)**: exit SteamVR → run "unlock" → replug
USB when asked → it prompts **per controller, LEFT first** → button held until slow pulse → OK →
repeat for the right → power-cycle both. Re-run triggers per the wiki: once per computer, per
headset, after pairing a new controller, after a Windows reinstall, after a GPU change.

**Hand slots are fixed by design, three independent signals**: the controllers broadcast their
own handedness in their BT names ("Motion controller - Left"/"- Right"); the protocol has
dedicated per-hand channels (`0x06` left, `0x0E` right); and the part numbers differ
(`M09967-001`/`-002`). Nobody on record has tried forcing a right unit into the left slot.

**What this queues** (NEXT-STEP): a small Monado patch sending PAIR/UNPAIR plus
`PAIRING_STATUS` polling. If it works, the battery-compartment button stops being one-way on
Linux and the LAST Windows dependency dies. Until it is implemented AND tested, the one-way rule
below stands unchanged.

### DECISION on the currently-unpaired right controller (T236): it is the capture subject, do not waste it

State after the failed attempt: **left `paired`, right `UNPAIRED`.** The instinct is to re-pair
the right immediately on Windows. **Don't do it casually — capture it.** The next step toward
Linux pairing is USBPcap of a *real* Oasis pairing, and a pairing capture needs an unpaired
controller to pair. We have exactly one, already in the right state. So on the next Windows boot:

1. Install USBPcap (once).
2. Start capture on the **HoloLens Sensors** USB device (`045e:0659`) — the controller pairing
   tunnels through it, the same HID we already read from.
3. Re-pair the right controller through the Oasis unlock flow (left is already bonded).
4. Stop the capture. **That one action both recovers the controller AND yields the real pairing
   wire format** — the payload behind `{0x16, 0x05, …}` that the inert enum guess was missing.

Then decode the capture (`docs/09` method / `scripts/analyze-hid.py`), implement the true framing
in `controller-pair.py`, and the world-first is back on the table with real ammunition instead of
guesses. **Do NOT keep firing speculative byte layouts on Linux in the meantime** — that is
flailing; the capture is the disciplined path. A single controller (the left) is enough for every
hardware check queued (thread names, benchmark, 0090 storm) until then.

### RESULT (T236): the simple framing does NOT pair — a real negative, and the honest record

We tried it. The world-first attempt **failed**, and that is worth as much on file as a success
would have been. What actually happened, corrected against the excitement:

- **The unpair was the PHYSICAL BUTTON, not a host command.** Holding the right controller's
  battery button (powered on) took it `paired/online → UNPAIRED`, observed live from Linux at
  01:32:24. Linux *read* the transition; it did not cause it.
- **`{0x16, 0x05}` (PAIR) does nothing observable**, with or without a controller-id byte, over
  40 s with the controller in discovery (slow pulse). Right stayed `UNPAIRED` throughout.
- **The enum values past 0x17 appear INERT.** A non-destructive probe sent `0x16` with subtypes
  `0x08` (PAIRING_STATUS), `0x04` (ONLINE_STATUS) and `0x05` (PAIR); **every one returned the
  identical `CONTROLLER_STATUS` (0x17) stream** and nothing else — e.g. `1700015e046a06` (left,
  offline, 045e:066a) and `17010000000000` (right, UNPAIRED). The firmware treats them like a
  status poll, or does not implement them. So `WMR_BT_CONTROL_MSG_PAIR = 0x05` etc. are
  **unvalidated RE guesses**, not a working command — the header comment "Messages we can send"
  is aspirational, and the fact that only `0x17` is ever actually sent by Monado is consistent
  with nobody having confirmed the rest.

**What this means**: Linux pairing is still unclaimed, and the real handshake is NOT the
one-byte subtype. Concrete next step, and it is scoped: **capture Oasis's actual pairing packets
with USBPcap on Windows during a real pair**, decode the true framing (likely a payload carrying
the controller's BT address, possibly via the `BT_IFACE` path), then implement THAT. `docs/09`'s
method applies. Until then, `controller-pair.py` stays as the harness (it sends cleanly and reads
correctly) but its PAIR does not work, and that is stated in the script.

**Recovery**: the right controller is unpaired and re-pairs in one Oasis pass on Windows — the
pre-agreed safety net, which is exactly why the experiment used one controller with recovery
available. The left was untouched as a live control throughout.

### `controller-pair.py` — the first-ever Linux WMR pairing attempt (T236, poshalim)

### `controller-pair.py` — the first-ever Linux WMR pairing attempt (T236, poshalim)

Built on the research above. `scripts/controller-pair.py` sends `WMR_BT_CONTROL_MSG_PAIR`
(`{0x16, 0x05, controller_id}`) — the command documented in `wmr_protocol.h` and never sent by
any code, on any OS's Monado, ever. **Dry run passed (2026-08-20)**: with both controllers
paired, `--arm-only` sent `0x05` for the right hand and the radio accepted it without error and
without disturbing either bond. So the command is safe to send; whether it *pairs* is the open
experiment.

**Safety model, which is the design and not a caveat:**
- It sends **only PAIR (0x05), never UNPAIR (0x06).** A host-side unpair has unknown semantics
  (one bond or both? which slot?), and the physical button already erases deterministically and
  aimed. There is no reason to give an unknown destructive command a trigger. UNPAIR is not
  wired.
- The **erase is always the physical button** — known, one controller at a time, recoverable.
  Linux only ever attempts the *rescue*. The worst case is "PAIR did nothing", not "we lost a
  bond we can't get back".
- **One controller at a time**, the other left paired as a live control, and a Windows/Oasis
  bench available as the recovery path before starting.

**The experiment nobody has run**, needing a hand on the physical button:
1. `controller-pair-check.py` → confirm both `paired`.
2. Hold the RIGHT controller's battery-compartment button until the LEDs pulse slowly (this
   both ERASES its bond and enters discovery).
3. `controller-pair-check.py` → confirm right now reads `UNPAIRED` (the clean before-state; this
   is what makes the result unambiguous — a fresh `paired` afterward can only have come from us).
4. `controller-pair.py right` → it arms the radio and watches for `UNPAIRED → paired`.
5. If it takes: **the last Windows dependency is dead and the G2 runs end-to-end on Linux from
   bare hardware.** If not, `docs/03`'s recovery (pair once on Windows) restores it, and the
   tool prints the wire-format variables worth varying (id-byte position, an `ONLINE_STATUS`
   0x04 pre-arm) for the next attempt.

### The bonding model, mapped (user's tested record, 2026-08-20)### The bonding model, mapped (user's tested record, 2026-08-20)

It is not an analogy — it is Bluetooth bonding, and it behaves like any BT device:

- **The bond lives in the controller + headset radio pair**, one headset at a time. It persists
  through months of power cycles, USB storms, port changes and OS changes (verified live, above).
- **Hold the battery-compartment button a few seconds** → the bond is ERASED *and* the controller
  enters discovery (slow LED pulse). From there **any G2 can adopt it** — "reasignar de equipo",
  exactly like re-pairing a BT peripheral to a new phone.
- **Adoption is one controller at a time, per hand slot**: Oasis asks for each hand separately
  (its own dialog: *"A Left motion controller is currently paired, would you like to unpair it
  and pair a new Left motion controller now?"* — the headset holds a LEFT slot and a RIGHT slot).
- **Calibration travels with the controller, so an adopted spare arrives fully calibrated**:
  `docs/47` Layer 2 — the factory calib blocks (gyro/accel matrices, LED model) live in the
  controller and the stack reads them **at every connect** (`wmr_controller_base.c`, "Parsed N
  LED entries from controller calibration"). Re-bonding loses nothing.

**What this unlocks for the recycling mission**: controllers are migratable between G2 units —
a spare (`M09967-001`/`-002`, `docs/63`) or the survivors of a dead headset can be adopted by any
living one, arriving with their own calibration. The single gate, unchanged: **adoption itself
needs the Windows/Oasis side today**, which is why the button stays one-way on a Linux-only
bench (addendum above).

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

## 2026-08-17 — the orientation saga: right hand solved, left hand 95% there

`docs/pruebas.jsonl` T206-T208. The long-standing controller-orientation debt (`docs/03`'s
own "What's still missing" #2, and 0047's still-open "near-pure-yaw mis-assignments"
paragraph) went from a vague "orientation is still wrong with constellation alone" to a
precisely diagnosed, mostly-fixed state in one night, via two new instruments this project
now treats as standard.

**The new instruments.** (1) The **labeled-motion capture**: still 10s → several reps of
pure pitch → still → pure roll → still → pure yaw → still, per hand, same session, with
`WMR_CONTROLLER_CALIBRATION_LOG=1`, segmented offline by gyro magnitude into a per-phase
dominant-axis table. This is what actually located the defect — a plain live A/B, tried
first (`patches/monado/0061`), only burned a candidate and taught the negative lesson that
composing rotations can never fix a reflection. (2) The **figure-8 test**: a real 3D
figure-8 traced by the wearer's hand while watching the gizmo. Cheap and decisive — it
discriminates a **constant offset** (the figure-8 closes, just rotated) from **precession**
(it winds up extra turns and never closes), which no static or single-motion capture can
tell apart. Both instruments needed the controller-pose gizmo to actually render correctly
first — it didn't, until `patches/hello_xr-player/0005-hello_xr-*` fixed a per-face-color
mesh bug that made every axis bar read as a multicolor smear (found while trying to use
0016's gizmo for exactly this). `patches/hello_xr-player/0006-hello_xr-*` then added
positive-tip caps so handedness reads at a glance.

**Right hand: fully correct, first time in this project's history.** The labeled capture
showed the right controller's raw fused orientation already matches the OpenXR grip
convention exactly (pitch+X, roll−Z, yaw+Y — R = identity), matching the wearer's own
"derecho bien". The only defect this hand had was the missing absolute yaw reference (see
below), and with that fixed, T208 recorded the project's first-ever fully-correct
controller: "el derecho se termino acomodando a casi perfecto... lo tuve 100% bien por unos
10 segundos casi. Bien mapeado todo."

**Left hand: the dominant defect is fixed, a small residual remains.** The same labeled
capture showed the left controller matches the right on pitch and roll but comes out
yaw-inverted — two axes correct, one sign-flipped, which is a **reflection** (determinant
−1). This is provably unfixable by composing any fixed quaternion onto the output (a
composition of proper rotations is always itself a proper rotation, det +1), which is
exactly why the whole prior A/B menu — including 0047's live `WMR_CONTROLLER_WMR_AXES` try
and 0061's plain conjugate — never worked. `patches/monado/0062`
(`WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT`) fixes it at the source: negate the LEFT controller's
calibrated gyro Y before fusion. `patches/monado/0063` then logged both hands' factory
calibration matrices and their determinants and found **all eight proper** — the reflection
is not a recoverable factory-calibration artifact; its true origin (raw ADC axis wiring, or
a per-hand device-frame convention Microsoft handles driver-side) is still unknown.
`patches/monado/0064` tried extending the same negation to the accelerometer, reasoning
from a frame-reconciliation algebra that predicted a coherent `diag(1,-1,1)` on both
sensors; `patches/monado/0065` retracted it the same night after the wearer's figure-8
showed the two-sensor version **precesses** (winds up extra turns) while the gyro-only
version closes — gyro-only stands, and the accel extension is kept in the tree as a
documented negative result, not deleted.

**With the sign flip fixed, what remained was heading, not axes** — no magnetometer means
nothing anchors yaw the way gravity anchors pitch/roll, so boot attitude was simply adopted
as heading. `patches/monado/0066` (`WMR_CONTROLLER_SOLVE_YAW_CORRECT`) closes that by
nudging fusion's heading toward gate-accepted constellation solves (reusing 0047's own
Rx180 gravity-gate bridge), gain-limited and capped per step. Its first hardware contact
(T208) immediately caught two real bugs in the same log — an unwrapped yaw error stepping
the long way around the circle into endless rotation, and 0047's already-documented
near-pure-yaw ghost solves un-locking a good heading — both fixed same-hour in
`patches/monado/0067`. After the fix, both controllers converge and lock: right to `0.0°`
in 140 corrections, left to `-0.1°` in 240.

**What's left, precisely scoped**: the left controller's figure-8 still "sigue acumulando
algo y rotando de a poco drifteando sobre un eje fantasma medio combinado" — a residual
cross-axis misalignment beyond the pure sign flip, on the order of a few degrees, that
integrates visibly over a multi-turn motion even though it reads as imperceptible in a
single static capture. `patches/monado/0068` (`WMR_CONTROLLER_LEFT_GYRO_FIT`) bakes a
least-squares-fitted left-to-right correction matrix from a labeled two-hand capture, but
is **explicitly flagged unsettled in its own comment**: the fit deviates 21.8° from
identity — far more than the 1-3° the figure-8's qualitative description suggested — and a
single 8-rep-per-axis hand capture cannot cleanly separate real hardware asymmetry from the
wearer's own left/right biomechanical asymmetry. The live figure-8 A/B decides whether it
graduates; if unclear, the named next step is a turntable protocol (constant angular rate,
sub-1° floor, and the gain dimension a hand capture cannot measure at all), which
supersedes hand captures for this calibration class.

**Net effect on item 2 of "What's still missing" above**: constellation-fed 6DoF
orientation is no longer an open problem for the right hand, and is down to a small,
bounded, actively-being-fitted residual for the left. Position acquisition slowness
(parked-at-anchor, late jumps toward real positions) remains the separate, still-open
constellation-matching thread.
