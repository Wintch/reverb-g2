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
`oculus/touch_controller` block of hello_xr.

**Why the WMR profile can't express the G2's buttons, precisely (T239)**: the generic
`microsoft/motion_controller` OpenXR profile models the *original* WMR controller, which has a
circular **touchpad** below the thumbstick — Acer, Samsung Odyssey, Lenovo Explorer, Dell Visor
and the first HP Reverb all shipped that hardware. **The G2 is the one model in the family that
removed the touchpad** for plain X/Y/A/B buttons, which is a real physical difference, not a
Monado quirk — confirmed against Monado's own source, where `wmr_controller_og.c` (touchpad,
serving `WMR_CONTROLLER_PID`/`ODYSSEY_CONTROLLER_PID`) and `wmr_controller_hp.c` (this headset's
`REVERB_G2_CONTROLLER_PID`, no touchpad) are two separate driver files, dispatched by controller
PID in `wmr_controller_create()`. Everything in this chapter is scoped to the G2's own controller
on purpose — that's the hardware on the bench — but `docs/62` carries the broader picture for
anyone adapting this project to a touchpad-equipped WMR controller instead.

Watch out for two details of the Touch profile:
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

### T238: the bytes AND the delivery mechanism are now solved -- one handshake detail remains

A USBPcap capture of a real Oasis pairing (right controller, the recovery pass) cracked two of
the three unknowns and corrected T236's conclusion:

1. **The command bytes are CONFIRMED CORRECT.** Oasis pairs with exactly `16 05 01` -- report
   0x16 (BT_CONTROL), 0x05 (PAIR), 0x01 (right). Byte for byte what T236 sent. So the enum was
   NOT an "unvalidated guess"; T236's inert-probe conclusion was wrong, and the reason it looked
   inert is (2).
2. **The delivery mechanism was the real bug.** BT-control commands must be sent as a HID
   SET_REPORT over the CONTROL endpoint (`bmRequestType 0x21`), which on Linux means
   `HIDIOCSFEATURE`, NOT `os.write()` to the interrupt-OUT endpoint. Proof it matters: the
   `0x17` controller-status we thought our `{0x16,0x17}` query fetched is **streamed passively**
   -- 16 packets arrive in 4 s with ZERO writes. So every `os.write` command (T236 and the early
   T238 tries) **never reached the command handler**. Via `HIDIOCSFEATURE` the device accepts it
   (`accepted=True`), and firing it on a controller in discovery visibly re-enumerates the radio
   -- the command is now landing.
3. **STILL OPEN: the completion handshake.** With bytes right and delivery right, the bond still
   does not form from Linux. Tried: single-shot, sustained resend, active polling, and passive
   listen (fire once, leave the radio alone -- since each control SET_REPORT re-enumerates the
   radio and hammering interrupts any pairing in progress). None completed. The capture shows
   Oasis did more around the PAIR: a `16 09` CMD_STATUS precursor per hand, and continuous
   PAIRING_STATUS polling on a **report-0x02 channel** whose *responses* (the state machine that
   drives completion) have not yet been decoded.

**NEXT STEP, offline, no headset needed**: mine the capture (`20of8.pcapng`) for the FULL
request/response sequence in the successful-pairing window -- both directions, all report IDs,
including the 0x02-channel responses -- to find what Oasis reads between PAIR and success (~7 s
later). Then replicate that exact dance. `controller-pair.py` is the harness (correct bytes +
correct delivery + resilient reopen + passive watch); it is one decoded handshake away.

**THE STATE MACHINE, decoded from the capture (T238, continued)**: the PAIR command makes the
headset's BT radio run a Bluetooth INQUIRY (scan). The headset narrates it in a debug log on
**report 0x05** (`WMR_BT_IFACE_MSG_DEBUG`, subtype 0x19), ASCII: right after Oasis's `16 05 01`
the capture shows `COMMAND_INQUIRY`, `inquiry started`, `discovering`, `PENDING 8`. So completion
= PAIR triggers inquiry -> the pulsing controller answers the inquiry -> bond -> 0x17 status
flips. `scripts/controller-pair-btlog.py` reads that log live.

**THE PRECISE REMAINING GAP**: fired from Linux via `HIDIOCSFEATURE` (accepted=True), our `16 05
01` produces **NO inquiry** -- report 0x05 stays silent, status stays UNPAIRED for the whole
window. Same bytes, same control-SET_REPORT channel, different effect. So the command reaches the
HID interface but does not reach the BT command handler that starts the scan. Device structure
that bounds the answer: the HoloLens Sensors (045e:0659) has **interface 2 = HID** (our hidraw2,
where 0x17 status streams and where we send) and **interfaces 3 & 4 = Vendor Specific** (no
hidraw). Candidates for the miss, in order: (a) report TYPE -- Windows may send PAIR as an
*Output* report via control SET_REPORT (wValue 0x02xx), while `HIDIOCSFEATURE` sends a *Feature*
report (0x03xx); the report descriptor of interface 2 would say whether 0x16 is Output-only; (b)
the exact wLength; (c) the command may belong to a vendor-specific interface (3/4), not the HID
one. tshark did not expose `usb.setup.wValue`/`wLength` for these transfers, so the report type
must come from the interface-2 HID report descriptor (`/sys/.../report_descriptor`), read offline.

**NEXT STEP, offline, no headset**: (1) parse interface 2's HID report descriptor to learn how
report 0x16 is declared (Output vs Feature); (2) if Output, send PAIR as an output report over
the control endpoint (raw USBDEVFS_CONTROL with bmRequestType 0x21, wValue 0x0216) rather than
HIDIOCSFEATURE; (3) confirm via the report-0x05 BT log that `inquiry started` appears. When the
inquiry fires from Linux, the bond should follow. This is a bounded HID-report-type problem, not
a mystery.

**RESUME-HERE for the pairing RE (T238 close), variables eliminated and the exact next steps.**
Everything below is confirmed against the capture and the device, so the next session does not
repeat any of it:

| variable | status |
|---|---|
| command bytes | `16 05 01`, identical to Oasis -- CONFIRMED |
| target interface | 2 (HID) -- CONFIRMED (bmRequestType 0x21 is a class-to-interface request; interface 2 is the only HID; interfaces 3/4 are vendor, not reachable by SET_REPORT) |
| report type | report 0x16 is declared OUTPUT, FEATURE and INPUT; interface 2 has NO OUT endpoint so os.write() output reports already route via control SET_REPORT (0x0216), and HIDIOCSFEATURE sends feature (0x0316) -- BOTH control variants tried, neither triggers the inquiry |
| report size | 63 data + 1 id = 64 bytes, exactly what we send -- CONFIRMED |
| state machine | PAIR -> BT inquiry, narrated on report 0x05 (`inquiry started`/`discovering`/`PENDING`) -- DECODED |
| the miss | our accepted `16 05 01` produces NO inquiry (report 0x05 silent, status UNPAIRED) |

**Tooling wall hit tonight**: tshark does NOT expose `usb.setup.wValue`/`wLength`/`wIndex` for
USBPcap control transfers (both `-T fields` and `-T json` returned empty), so Windows' exact
SET_REPORT parameters could not be read. **Next time: parse the pcapng raw (USBPcap packet header
carries the setup), or capture with `usbmon` on Linux where the setup IS exposed.**

**The two remaining hypotheses, in order, both offline-startable:**
1. **wLength**: Windows may send the SET_REPORT with a wLength SHORTER than 64 (e.g. 3). Read it
   from a raw pcapng parse; if shorter, send via raw `USBDEVFS_CONTROL` (bmRequestType 0x21,
   bRequest 0x09, wValue 0x0216 or 0x0316, wIndex 2, wLength = Windows') -- which needs the hid
   driver detached first (USBDEVFS_DISCONNECT + CLAIMINTERFACE; plain USBDEVFS_CONTROL to
   interface 2 returns EBUSY while the driver holds it).
2. **Sustained PAIRING_STATUS polling**: Windows sent `02 08` continuously (1263x) around PAIR;
   the inquiry may auto-abort without it. Our polling attempts churned on fd re-enumeration
   (a fixable tool bug, not fundamental). Fix the reopen path so polling is clean, then: PAIR
   once + steady `02 08` poll, watch report 0x05 for `inquiry started`.

Only step (1)'s send-test and step (2) need the controller in discovery -- ONE hold each, no more
blind attempts. `scripts/controller-pair-btlog.py` reads the BT log to confirm the inquiry fires.

**Recovery**: the right controller is unpaired; one Oasis pass on Windows restores it (the user
is dual-boot). The left stayed paired as the anchor throughout.

**Tooling-wall lead (everyday-system/comms session, 2026-08-20, no capture file in hand --
`20of8.pcapng` is not committed per the repo's own media-out policy and was not confirmed to
exist as a saved file at all; this is pure protocol/tooling research for next session to test
against the real capture, NOT a verified fix):**

1. **Check whether the queried frames are Setup-stage Control-Submit URBs at all before
   blaming tshark.** USBPcap's own capture header only carries the 8-byte USB Setup Packet
   (bmRequestType/bRequest/wValue/wIndex/wLength) on the **Submit** stage of a **Control**-type
   transfer; a Complete/status frame, or an Interrupt-endpoint frame (the streamed 0x17 status
   reports ride the interrupt endpoint, not control), structurally has no setup fields to show
   -- tshark returning empty for those is correct behavior, not a limitation. Before assuming a
   tshark/USBPcap defect, isolate to Control-type frames only and see if *any* frame in the
   whole capture ever populates `usb.setup.*`, e.g.:
   `tshark -r 20of8.pcapng -Y "usb.transfer_type == 0x02" -T fields -e frame.number -e usb.irp_info.direction -e usb.setup.bRequest -e usb.setup.wValue -e usb.setup.wLength`
   If the fields populate on other Control frames but not on the specific PAIR SET_REPORT
   frame, that's a real, narrower anomaly worth its own note. If they're empty across the
   *entire* capture, that points at a USBPcap-build/dissector-version gap (some older USBPcap
   builds are known to not surface the parsed setup fields in Wireshark's tree, per scattered
   Wireshark-bugzilla/USBPcap-issue reports -- not independently confirmed against this
   specific build, flagging as a lead only) rather than anything about this transfer.
2. **Manual raw-header parse, if (1) doesn't resolve it.** USBPcap's custom per-packet header
   (`USBPCAP_BUFFER_INFO`, documented in the USBPcap project's own headers) places the raw
   8-byte Setup Packet at a fixed offset ahead of the regular libpcap frame data specifically
   for Control-Submit URBs -- a short Python `struct.unpack` against those offset bytes would
   read bmRequestType/bRequest/wValue/wIndex/wLength directly, bypassing Wireshark's dissector
   entirely (the exact offset/layout was not re-verified here against USBPcap's current header
   source -- confirm against the installed USBPcap version's own docs/headers before coding
   this, don't assume the offset from memory).
3. **`usbmon` (already named as the fix in the table above) only solves HALF of this.** It
   exposes setup bytes for anything captured *on this Linux box* (`/sys/kernel/debug/usb/usbmon`
   prints the 8 setup bytes inline for every Control-Submit, e.g. `S Ci:1:001:00 -115 8 = 21 09
   03 16 ...`) -- genuinely useful for confirming exactly what OUR `HIDIOCSFEATURE`/raw-control
   send puts on the wire, immediately, no Windows needed. But it does **nothing** for reading
   Windows/Oasis's reference bytes, since that side was only ever captured once, on Windows, via
   USBPcap -- usbmon can't retroactively decode an existing Windows capture. Don't let "usbmon
   fixes it" quietly become the plan without noticing it only unblocks verifying the Linux side,
   not diffing against Windows' actual wLength (the open question in hypothesis 1 of the table
   two sections up).
4. **The report-type question (was this doc's original angle 2 candidate for the tooling gap)
   is NOT open** -- worth stating explicitly so it isn't re-investigated: the table above already
   confirms both the Feature-report (`HIDIOCSFEATURE`, wValue 0x0316) and Output-report (control
   SET_REPORT, wValue 0x0216) variants were sent and reached the interface (`accepted=True`);
   neither triggers the inquiry. So `HidD_SetFeature`/`HIDIOCSFEATURE` demonstrably DO produce a
   bus-visible, device-accepted control transfer here -- the remaining gap is `wLength` and/or
   the sustained-polling requirement (hypotheses 1 and 2 in the table above), not whether the
   command reaches the bus at all.

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

### T240 (2026-08-20, ~22:15-22:23): the real capture landed — tooling wall resolved, full handshake decoded, and Linux's remaining gap is narrower than thought

The capture the tooling-wall lead above was written blind for is now in hand:
`pairing_joys.pcapng` (1.5 GB, 266k packets, USBPcap on Windows 11 25H2, Wireshark 4.6.8), a
fresh Oasis unlock run that re-paired BOTH controllers in one session (screenshots `pairing.png`
/`pairing2.png` alongside it — the same "would you like to unpair it and pair a new Left motion
controller now?" dialog from `docs/31`). `20of8.pcapng` from T236/T238 is also confirmed to
exist on disk after all — the earlier "not confirmed to exist as a saved file" note was wrong,
it was just never checked from Linux. Both live on the Windows partition (`debug_vr/`), not
committed, per the repo's media-out policy.

**The tooling wall is resolved, and it was a namespace, not a USBPcap defect.** Hypothesis 1 from
the lead above was the right instinct (isolate to Control frames, check if setup fields populate
*anywhere*) but the wrong target field: Wireshark's USB HID dissector exposes the Setup-stage
fields under **`usbhid.setup.*`**, not `usb.setup.*` — `usbhid.setup.bRequest`,
`usbhid.setup.wValue` (with sub-fields `usbhid.setup.ReportID`/`usbhid.setup.ReportType`),
`usbhid.setup.wIndex`, `usbhid.setup.wLength`; the payload itself is `usbhid.data`
(`usbhid.data.report_id` for the ID byte). `usb.setup.*` stays empty for every HID-class control
transfer in this capture — not a build/dissector gap, just the wrong protocol prefix. Confirmed
against `-T json` on a known frame before trusting it. This unblocks re-reading `20of8.pcapng`
too, which was shelved under the same wrong assumption.

**The full BT pairing state machine, decoded end to end, both hands, this session:**

| t (s) | host → radio (report 0x16, Feature, confirmed exclusively — never Output) | radio-side log (report 0x05) |
|---|---|---|
| 182.1 | `16 09 00` (CMD_STATUS, hand=0) | routine status poll |
| 254.4 | `16 06 00` (UNPAIR, hand=0 = LEFT) | `HIDH_COMMAND_VIRTUAL_UNPLUG`, `COMMAND_DELETE_NVRAM_DATA` "special case unbonding device" |
| 255-276 | — | `BTM_PAIRED_DEVICE_LINK_KEYS_REQUEST_EVT` / `nvram_id is 0` repeating ~every 0.7-1.3s — the old-bond side still trying and failing to reconnect post-unbond |
| 276.9 | `16 05 00` (PAIR, hand=0) | `COMMAND_SET_VISIBILITY`→`COMMAND_SET_PAIRING_MODE`("pairing allowed 1")→`COMMAND_INQUIRY`→`inquiry started`, all within 10ms of the PAIR write |
| 283.3 | — | `inquiry complete`, **nothing found** — first attempt timed out, the controller wasn't in discovery yet |
| 370.4 | `16 07 00` — **new subtype, not in `wmr_protocol.h`, meaning unknown** | (no distinct log line attributable) |
| 373.9 | `16 09 00` | status check before retry |
| 380.9 | `16 05 00` (PAIR retry, hand=0) | same 3-step radio sequence, `inquiry started` |
| 382.1 | — | `Found by address: Motion Controller - Left`, RSSI -43 — **same physical BT address as before the unbond**, the controller keeps its factory address across erase/re-pair |
| 387.3-389.2 | — | `inquiry complete`→SDP→PnP/HID service found, Product ID `0x066a`→pairing IO caps exchange→**new** BR/EDR link key generated→NVRAM write→encrypted→`CONNECTED`. **~8.3s from PAIR to CONNECTED**, matching T238's "~7s" estimate |
| 395.5 | `16 09 01` (CMD_STATUS, hand=1) | status check for RIGHT |
| 423.4 | `16 05 01` (PAIR, hand=1 = RIGHT) | same 3-step sequence, `inquiry started` |
| 424.8 | — | `Found by address: Motion Controller - Right`, RSSI -53, own factory address, first try |
| 429.8-431.6 | — | same SDP/HID/pairing-caps/new-link-key/NVRAM/encrypt/`CONNECTED` sequence, **no explicit UNPAIR was sent for the right hand** — it re-paired directly on top of whatever bond state it had, the headset just allocated a fresh `nvram_id` |

**Confirms, corrects, and adds to the prior record:**

- **Hand-encoding is CONFIRMED, not ambiguous**: id byte `00` = left (both attempts), `01` = right
  — exactly the "0x06 left / 0x0E right"-style per-hand signal already inferred, now seen driving
  PAIR itself. T236's single right-hand `16 05 01` and this session's two left-hand `16 05 00`
  are consistent, not contradictory.
- **Report type is settled**: every `0x16` send in this whole session used Feature (`wValue`
  high byte `0x03`), zero as Output. T238's tooling-wall hypothesis (a) — that Windows might use
  Output while Linux's `HIDIOCSFEATURE` sends Feature — is now directly falsified by the
  reference capture: Windows uses Feature too, same as what Linux already sends.
- **`wLength` is 64, matching Linux's send exactly** — hypothesis 1 from the tooling-wall lead
  (shorter Windows `wLength`) is also falsified. Nothing left in the byte-level framing to blame.
- **The `0x02` report is a separate polling/query channel, not the command channel**: 1263
  sends of `02 08` (PAIRING_STATUS poll) over the session, plus rare `02 07`/`02 0b`/`02 06`/
  `02 04` — same subtype vocabulary as `0x16`, but as an Output report queried continuously,
  distinct from the Feature-report command path. Matches the "sustained polling" already
  suspected in hypothesis 2 of the tooling-wall lead, now with real numbers instead of a guess.
- **New, undocumented subtype `0x07`** sent once (`16 07 00`, t=370.4s) between the failed
  first attempt and the successful retry, with no radio-log line clearly attributable to it —
  candidate for "reset/cancel pairing mode before retrying", unconfirmed. Not in
  `wmr_protocol.h`'s enum; add it there as unknown before the next attempt.
- **The internal 3-step radio dance (`SET_VISIBILITY`→`SET_PAIRING_MODE`→`INQUIRY`) is driven
  entirely by the single host `16 05` write** — all three appear within one 10ms window right
  after it, with no other host command in between. This matches T238's own conclusion; nothing
  new needed on the host side to get from PAIR to an inquiry *starting*.
- **The re-enumeration hypothesis (device address 2→5, matching Oasis's "replug USB when asked"
  step) is weakened, not strengthened**: that address change happened once, early (~t=164s),
  a full two minutes before the first PAIR at t=276.9s — not freshly before each PAIR send. If a
  fresh re-enum were load-bearing for the radio to accept the command, it would need to be
  *immediately* before, which this capture doesn't show. Lower priority as the explanation for
  Linux's silent `16 05`.
- **BT addresses**: both controllers keep their factory Bluetooth address across an erase/
  re-pair (unbond then re-discover finds the *same* address, not a new one) — direct confirmation
  that "erase" only removes the *bond* (the link key), not the controller's own identity.
  Consistent with `docs/63`'s existing model that pairing is real BT bonding. Addresses
  themselves are treated like the serials in `docs/63` — deliberately not reproduced here.

**What's still genuinely open**: T238's own attempt sent `16 05 01` with confirmed-correct
bytes, Feature type, and wLength=64 — all three now triple-confirmed identical to what Windows
sent in this capture — and still got no inquiry. So the gap is NOT in the SET_REPORT itself.
Candidates worth checking next, in order: (1) the `02 08` sustained polling channel might be
what actually arms/keeps-alive the pairing window on the radio side, not a passive status read —
T238 tried "active polling" but its own reopen-path bug (fd churn on re-enum) may have prevented
a clean sustained `02 08` from ever landing; (2) command ordering — Windows always issues a
`16 09` (CMD_STATUS) status check shortly before each `16 05`, in both hands, both attempts;
Linux's harness doesn't currently replicate that precursor; (3) the newly-found `16 07` deserves
one deliberate probe on its own, non-destructively, the same way `0x08`/`0x04` were probed in
T236. None of these need a fresh capture — they're testable offline against the existing
`controller-pair.py`/`controller-pair-btlog.py` harness, then live with a controller in
discovery.

**Done offline, same session, zero hardware risk** (both controllers currently read
`paired, offline` — verified with `controller-pair-check.py` before touching anything, so there
was no free unpaired controller to test a real pairing against):

- (2) is now wired into `--handshake`: it re-sends `16 09` (CMD_STATUS) before every periodic
  `16 05` (PAIR) resend, not just once at the start. **Correction, caught 2026-08-20 late**: the
  original writeup said this "matches the capture's own pattern exactly" -- it doesn't. Re-checked
  the actual gaps: `16 09` at t=373.9s → `16 05` at t=380.9s is a **7s** gap, and `16 09` at
  t=395.5s → `16 05` at t=423.4s is **28s**. Not a tight precursor at all -- CMD_STATUS and PAIR
  are loosely interspersed, almost certainly each tied to separate Oasis UI events (a dialog
  opening, a button click), not a fixed short-interval command sequence. Harmless to keep sending
  it (an extra status query costs nothing), but it is NOT a validated match to Windows' timing,
  and should not be read as one when judging why the live retest still failed.
- (3) got its probe: `controller-pair.py --probe 0x07` — sends `16 07` alone (no controller id,
  same non-destructive shape as T236's original `0x08`/`0x04` probes) and watches report 0x05 for
  8s. **Result: `accepted=True`, silence** — no BT-log reaction, same as the reference capture's
  own `16 07 00` (T240's table above has no log line attributable to it either). Inconclusive but
  consistent: whatever `0x07` does, it likely needs a controller actually in discovery to show
  any effect, same constraint as `0x05` itself. Controllers confirmed still `paired, offline`
  immediately after — the probe is genuinely inert on an idle radio, not just quiet-but-working.
- (1) still needs a live attempt to test — sustained `02 08` polling can't be validated without
  watching whether it actually keeps a discovery window open, which only shows up against a real
  in-progress inquiry.

**What's left needs the user's hands**: both controllers are currently bonded again (last
night's Windows session paired both), so testing (1) for real means deliberately unbonding one
via the physical button first — the same one-way-on-Linux, Windows-recoverable operation as
every prior attempt. Not done without asking first.

### T240, live test (same session): the cleanest negative yet, and the framing hypothesis space is now exhausted

With the user holding the right controller's button, ran (1) for real, live, twice, right after
fixing a real bug the first run exposed:

- **First live run** (`--handshake right --now`) immediately spammed
  `[radio re-enumerated]` on every loop iteration for the full 35 s and never paired. Root cause
  found by re-reading the capture: the loop's `send_rid(0x02, 0x08)` was sending report `0x02` via
  `HIDIOCSFEATURE` (Feature, `wValue` high byte `0x03`), but T240's own table above already showed
  Windows sends report `0x02` as **Output** (`wValue` high byte `0x02`) — the wrong report type was
  being rejected by the device on every single send, forcing a reopen every iteration and almost
  certainly trampling any inquiry the radio might otherwise have started. Fixed: added
  `write_output()` (plain `os.write()` — interface 2 has no OUT endpoint, so a raw write already
  routes as a control SET_REPORT with the Output `wValue`, same mechanism T238 already documented
  for report 0x16) and switched the `0x02` poll to it. Also wired the `16 09` CMD_STATUS precursor
  into every periodic PAIR resend (previously sent once at the very start only), matching the
  capture's own pattern exactly.
- **Second live run**, corrected script: no more re-enumeration spam (confirms the fix), report
  `0x02` now accepted as Output on every send — but still 35 s, no pairing.
- **Third live run**, same corrected script, now also watching report `0x05` (the BT debug log
  decoded in the table above) live via a new `read_status(..., log_debug=True)` path: **total
  silence for the full 35 s**, controller confirmed pulsing (in discovery) the entire window. On
  Windows the identical `16 05` write produces `COMMAND_SET_VISIBILITY`→`COMMAND_SET_PAIRING_MODE`
  →`COMMAND_INQUIRY`→`inquiry started` within 10 ms. On Linux, nothing — not even a hint that the
  radio's own firmware logging noticed the write at all.
- **The interface-3/4 hypothesis is now closed too**, checked directly against the capture rather
  than inferred: every HID control transfer in the *entire* 444 s session — the PAIR/UNPAIR/
  CMD_STATUS Feature writes, the 1263 Output polls, even the routine `SET_IDLE` (0x0a) at
  interface claim — targets `wIndex 2` and only `wIndex 2`. Interfaces 3 and 4 see zero
  host-initiated traffic from Oasis, ever. So Windows isn't reaching the radio through some other
  interface Linux can't touch; it uses the exact same one we do.

**Net effect**: every variable at the USB-framing level — report ID, report type (Feature vs
Output), interface/`wIndex`, `wLength`, byte payload, command ordering (CMD_STATUS-before-PAIR),
sustained polling, and even the target interface itself — is now confirmed byte-for-byte identical
between what Linux sends and what the reference Windows capture shows working. And the radio's own
internal logging shows Linux's write produces literally no observable reaction, while Windows'
identical-looking write produces one within 10 ms. That gap can no longer be explained by anything
visible at the USB protocol layer captured here — it either isn't visible at this layer at all
(session/driver-state on the host side, something in exactly how Windows' HID stack sequences the
low-level transfer that a capture doesn't distinguish from ours), or something in the actual bytes
that hit the wire from Linux silently differs from what was intended despite `HIDIOCSFEATURE`/
`write()` reporting success. The right controller is unpaired; recover it with one Oasis pass on
Windows (dual-boot) when convenient — not urgent, but don't leave it that way indefinitely.

### T240, usbmon byte-diff (same session): the last unverified link checks out clean too

The user had root and ran it: `scripts/usbmon-trigger.py` (new, sends only the same two routine
reports `controller-pair-check.py`/the sustained poll already send in normal operation --
`16 09` CMD_STATUS and `02 08` PAIRING_STATUS, nothing destructive) while `cat
/sys/kernel/debug/usb/usbmon/4u` captured the bus. Result, straight from the capture:

```
S Co:4:003:0 s 21 09 0316 0002 0040 64 = 16090000 00000000 ...
C Co:4:003:0 0 64 >
S Co:4:003:0 s 21 09 0202 0002 0040 64 = 02080000 00000000 ...
C Co:4:003:0 0 64 >
```

`bmRequestType 0x21, bRequest 0x09 (SET_REPORT), wValue 0x0316/0x0202, wIndex 0x0002, wLength 64`
-- byte-for-byte identical to the Windows reference frames, **and the completion status is 0
(success) with all 64 bytes transferred**, both times. This was the one link in the chain not yet
independently checked: whether `HIDIOCSFEATURE`/`write()` might be silently mangling something
between the syscall and the actual wire bytes. It isn't. The USB transfer itself is provably
perfect and the device ACKs it at the protocol level -- and the radio's firmware still never
dispatches it into a BT command (per the report-0x05 silence above). **A clean ACK does not mean
the firmware chose to act on it**; those are two different layers, and this capture now proves
Linux gets the first one right and still doesn't get the second one.

**This closes off the entire USB-framing explanation space, definitively.** Every variable
checkable from a USB capture -- bytes, report type, interface, `wLength`, ordering, sustained
polling, and now the raw wire transfer itself -- is confirmed identical, confirmed ACKed, and the
firmware still stays silent. Whatever gates this is not visible to USBPcap or usbmon at all, which
narrows the remaining search to two places, neither explored yet: (1) something Oasis's *own
driver init* does once, early, on ONE of the OTHER USB endpoints of this same composite device --
the sensor collections `col01`/`col02`/`col03` under interface `mi_02` (visible in the original
PowerShell headset-detection log, `\\?\hid#vid_045e&pid_0659&mi_02&col0{1,2,3}#...`) or the
separate "presence device" (`03f0:0580`) -- that arms the radio for the rest of the session,
before anything this doc's tables have looked at; (2) BT radio-side state genuinely invisible to
USB (RF/timing arbitration internal to the WICED chip). (1) is fully checkable offline against
`pairing_joys.pcapng`, no hardware needed -- nobody has looked at those other collections yet.

### T240, mining the "other devices" angle (same session): a real decode, but a dead end for pairing

Checked (1) directly. `col01`/`col02`/`col03` turned out to be a non-issue: those are Windows PnP
device nodes for separate top-level HID *collections* inside the same physical interface
(`mi_02` = USB interface number 2, the one already fully swept above) -- not separate USB
interfaces, so they were already covered by the "every transfer targets `wIndex 2`" sweep. Nothing
new to check there.

The presence device (`03f0:0580`, bus 2 device address 4) was genuinely unexplored, and did have a
one-time exchange worth decoding: at t=175.56s, a `SET_REPORT` (report `0x50`, Feature, 64 bytes,
`50 01 00...`) immediately followed by a `GET_REPORT` for the same report ID. Pulled the raw
completion bytes (`tshark -x`, since this device's payload isn't dissected as `usbhid.data`):
`50 01 01 03 01 02 51 41 38 35 51 41 50 56 31 00 07 00 51 41 38 35 51 42 4c 56 31 00 32 31 51 41
38 35 51 44 50 56 31 00...` -- decodes as ASCII `QA85QAPV1`, `QA85QBLV1`, `QA85QDPV1`, **byte-for-
byte the same three OEM firmware strings from the original PowerShell detection log** (`OEMFW:
QA85QAPV1/1.2 | QA85QBLV1/7.0 | QA85QDPV1/50.49`). So report `0x50` is a firmware-version query,
not an unlock gate -- a nice incidental confirmation of the decode method, not a lead.

A second exchange nearby (t=178.63s and t=181.65s, ~3s apart: `SET_REPORT` report `0x04`, Feature,
2 bytes, `04 01` then `04 00`) remains unexplained -- same report-ID shape as the documented
Display Enable command (`docs/12`), but sent to a *different physical device* than the one Monado
already uses it on, so not necessarily the same function. **Ruled out as pairing-relevant by
timing, not by content**: checked the presence device's activity across the *entire* session --
it goes completely silent after t≈290s and has zero traffic anywhere near any of the three PAIR
attempts (t=276.9, 380.9, 423.4s). If this device armed something for pairing, it would need to
fire again before each attempt, the way `16 09` (CMD_STATUS) does on the sensors device; it
doesn't fire at all after the first two minutes of the session. This closes the "other devices"
angle for tonight -- nothing found there correlates with pairing.

**Two more checks, closing out the night for real:**

- **Polling density is NOT what makes it work.** The `02 08` sends look dense in aggregate (2124
  of 2147 have <5ms gaps) but that density is a one-time startup burst at t≈143-182s, unrelated to
  pairing -- the actual windows around all three PAIR attempts are sparse (5 sends across the
  entire 380-390s successful-pairing window, tens/hundreds of ms apart). A tight real-time polling
  loop is not the missing ingredient.
- **Correction, caught 2026-08-20 later the same night: a vendor channel DOES exist -- the "no
  vendor channel anywhere" line above was wrong as stated.** It was only checked for CONTROL-type
  (`usb.transfer_type==0x02`) HID-class transfers; a full sweep across every transfer type found
  substantial traffic on a genuine vendor-specific interface (`bInterfaceClass 0xff`, endpoints
  `0x81`/`0x82`/`0x84`/`0x85`) -- 189k isochronous IN packets on `0x84` alone, tens of thousands
  more on `0x82`/`0x85`, all on this same device. Traced to a real driver: the OS has a SEPARATE,
  distinct driver package installed for `USB\VID_045E&PID_0659&MI_03` -- `HololensSensorsWinUsb`
  (`hololenssensorswinusb.inf`, `[Microsoft.Section.NTamd64] %HsWinUsb% = HsWinUsb,
  USB\VID_045E&PID_0659&MI_03`), a WinUSB binding on interface **3**, entirely separate from
  interface 2's HID class driver that carries every command this whole investigation has been
  based on. This is a real, previously-missed structural fact, not a dead end to wave away without
  checking.
  **But checked, and it doesn't explain the pairing gap**: every one of those packets is
  CONTROL-type-absent -- only 2 standard (non-vendor, non-command) `GET_DESCRIPTOR` frames on this
  interface class in the whole session, zero vendor-class SET_REPORT-equivalent commands anywhere.
  The traffic rate is flat and unaffected by any pairing event -- sampled in 5s windows straddling
  the successful `t=380.9s` PAIR (`375-380s`: 902 packets, `380-385s`: 902, `385-390s`: 860,
  `390-395s`: 902) -- textbook fixed-rate sensor telemetry (almost certainly the IMU/camera
  stream, structurally distinct from the "sensors" HID collections `col01/02/03` discussed above),
  not a hidden command path. The corrected, fuller picture: interface 3 is real, used, and
  irrelevant to pairing specifically. Interface 2's HID `SET_REPORT` remains the only place any
  BT_CONTROL-shaped command was ever seen, on either OS.
- **The "Windows Settings → Bluetooth → Add device" path is not a missed lead** -- `docs/31`
  already researched and dismissed it (T235): it pairs to the *PC's own* radio, not the headset's,
  unvalidated for the G2, and the Oasis wiki (the actual reference for radio-equipped WMR
  headsets) never uses it. No third mechanism was overlooked.

**Honest state at close of T240**: every USB-visible avenue is now checked -- byte framing, wire
bytes (usbmon), report type, interface, ordering, sustained polling (including its real density),
every other USB device and every other request type in the composite headset, and the one
alternative pairing path the project's own docs mention. None of it explains the gap. What's left
is either something below the USB layer entirely (BT radio-internal state on the WICED chip,
invisible to any capture taken at the USB level) or something in exactly how Windows' HID class
driver sequences a transfer that neither USBPcap nor usbmon distinguishes from what Linux already
sends identically. This is a good, honest stopping point for the capture-mining thread -- it has
been thoroughly exhausted, not abandoned early. **This conclusion is superseded by T241 below --
there is now a real, untried lever.**

### T241 (2026-08-20, later the same night): a real driver stack was hiding in plain sight -- MotionControllerHid.dll / MotionControllerSystem.dll, never before examined

Prompted by the user recalling a separate MS Store app and a `docs/37` reference to a controller
driver "not yet obtained or examined by this project." That reference (`MotionController0669...`)
turned out to not even be necessary -- **the real thing was already sitting in this machine's own
`hololenssensors.inf` DriverStore package**, the exact same one `docs/09` already used for
`HoloLensSensors.dll`, right next to it, never opened:

- `MotionControllerHid.dll` (745 KB) and `MotionControllerSystem.dll` (1.3 MB) --
  `C:\Windows\System32\DriverStore\FileRepository\hololenssensors.inf_amd64_.../`.
- Both are the **real Microsoft WMR motion-controller driver stack**, internal codename
  **"CrystalKey"** (source paths embedded in the strings: `analog\oasis\crystalkey\hid\*.cpp`,
  `analog\input\controller\crystalkey\lib\*.cpp`). This is NOT Oasis's own code -- Oasis
  (`driver_oasis.dll`, `unlock_wmr.exe`) is the community/Valve layer on top; CrystalKey is
  Microsoft's own driver underneath it, present on every WMR-capable Windows box, and nobody in
  this project's whole pairing investigation (T235-T240) had opened it until now.
- **`MotionControllerHid.dll` contains an entire pairing state machine in its debug strings**:
  `bth_onPairingButtonPressed`, `bth_pairingProcessSendEnterPairingMode`,
  `bth_pairingProcessSendExitPairingMode`, `BTH_SendPairingButtonPressed`, `Enabling Pairing`,
  `Exiting Pairing`, `pairingProcess.state: %d`, `PAIRING_COMPLETE`, `Could not finalize
  handshake`, `Bth task tried to start HID traffic before paired!`, `HCI_CONTROL_HIDD_EVENT_OPENED
  unexpected, pContext->bPaired is FALSE`. This is the first direct evidence, anywhere in this
  project's research, of an explicit ENTER/EXIT pairing-mode step and a real gated "paired" flag
  that blocks HID traffic until set -- exactly the shape of thing that would explain tonight's
  clean negative (accepted write, silent firmware): **if entering pairing mode is a distinct
  command/step from PAIR (`16 05`) itself, sending only `16 05` -- everything this project has
  tried since T236 -- would be sending the second half of a two-step sequence without the first.**
- `MotionControllerSystem.dll` exports the higher-level API: `CrystalKeySendCommand`,
  `CrystalKeyWriteCommand`, `CrystalKeyReadCommand`, `CrystalKeySetLedPulseTrain` (very likely the
  actual LED slow-pulse-in-discovery command), `CrystalKeyGetBluetoothAddress`,
  `CrystalKeyInitializeDevice`, `CrystalKeyKeepAlive`, `CrystalKeySetToIdle`,
  `CrystalKeyOpenDevice`/`CrystalKeyCloseDevice`. A real, previously-unknown command API surface,
  distinct from and richer than the bare `wmr_protocol.h` enum this whole project has been working
  from.
- **Static disassembly hit a real wall tonight, not a dead end**: `objdump -d` on
  `MotionControllerHid.dll`, cross-referenced with `scripts/xref.py` against the pairing strings,
  found **zero direct code references** to any of them -- consistent with WPP-style software
  tracing (format strings compiled out of the normal code path, only resolvable with a matching
  PDB/TMF this project doesn't have). The exported `CrystalKeySendCommand` function WAS located
  (export ordinal 25, `objdump -x` -> RVA `0xdfe0`) and disassembled directly: it's a thin
  telemetry-wrapped shim that calls into unnamed internal functions (`0x180008924`,
  `0x180020818`) -- real logic, but raw `objdump` gives no symbol names past the export table, so
  tracing further needs a real decompiler (Ghidra), not more manual `objdump`/`strings` grinding.

**NEXT STEP, offline, no headset needed, and this is now the actual concrete lever**: load
`MotionControllerHid.dll` and `MotionControllerSystem.dll` into Ghidra (or equivalent), trace
`CrystalKeySendCommand`/`CrystalKeyWriteCommand` down to wherever they actually touch the USB
device (`HidD_SetFeature`/`DeviceIoControl`/whatever it turns out to be), and specifically locate
the `bth_pairingProcessSendEnterPairingMode` code path to recover the actual command it sends --
almost certainly a SEPARATE report/subtype from `WMR_BT_CONTROL_MSG_PAIR = 0x05`, sent BEFORE it.
If found, replicate that exact "enter pairing mode" command from Linux before firing `16 05`, and
this whole investigation's dead end may not be one.

### T241, Ghidra (2026-08-20, same night, `~/tools/ghidra_12.1.3_PUBLIC` -- new lab tool, installed this session): a bigger finding than expected -- this is a SECOND, INDEPENDENT sender talking to the same device

Ghidra 12.x dropped Jython; headless scripting here used a compiled Java `GhidraScript`
(`scripts/xref.py`'s objdump approach doesn't scale to this -- Ghidra's own decompiler and
reference engine do). Two concrete findings:

1. **`MotionControllerHid.dll` imports NO `HidD_SetFeature`/`HidD_GetFeature` at all.** Its only
   `HID.DLL` imports are read/parse-side: `HidP_GetCaps`, `HidP_GetButtonCaps`, `HidD_GetAttributes`,
   `HidD_GetHidGuid`, `HidD_GetPreparsedData`, etc -- capability enumeration and report-descriptor
   parsing, never a Feature-report send. This means **this DLL is architecturally incapable of
   sending the `16 05`/`16 09` Feature-report commands this whole investigation has been chasing
   since T236** -- those are, and can only be, Oasis's own doing (confirmed independently: Oasis's
   own `unlock_wmr.exe`/`driver_oasis.dll` DOES call `HidD_SetFeature`, per the original T236
   analysis).
2. **It DOES write to the device -- via raw async `WriteFile`, the Output-report path (report
   `0x02`'s channel), not Feature.** Traced the two actual `WriteFile` call sites: one
   (`crystalkeycache.cpp`) turned out to be writing a **local disk cache file**, not the device --
   a real dead end, correctly identified and discarded. The other
   (`FUN_18001dcb8`, `crystalkeydevice.cpp`) is the genuine device-write path: overlapped
   (asynchronous) `WriteFile` on a device handle, generic buffer/length passed in by its callers --
   this is a low-level plumbing function, not itself the site of any literal command bytes; the
   actual "enter pairing mode" payload lives further up its call chain, past what a WPP-obscured
   string search can locate (see below).

**Why this matters more than a missing byte would**: it means Windows pairing is not one program
(Oasis) sending the right bytes to a passive device -- it's **two independent OS-level actors
concurrently touching the same device over two different report channels**: Oasis over Feature
(`16 xx`, what this whole project has replicated and confirmed byte-identical) and Microsoft's own
CrystalKey/WMR-platform driver stack over Output (`02 xx`, what `MotionControllerHid.dll` actually
does, running as part of the Windows Holographic/WMR platform itself, independent of Oasis).
`bth_pairingProcessSendEnterPairingMode`'s literal command bytes could not be recovered tonight --
its trace string has **zero direct code references** in Ghidra's own analysis too (same WPP-style
compiled-out-of-the-normal-path pattern `scripts/xref.py` hit on `objdump` earlier), meaning static
disassembly alone cannot locate this call site without a matching PDB/TMF this project doesn't
have. Static RE of this specific function is very likely a dead end without one.

**Reframes the whole investigation's honest state**: every earlier negative in this doc (T240's
byte-for-byte USB parity, usbmon wire-level confirmation, silent report-0x05 debug log) was
measuring only the Oasis half of a two-actor protocol. It was never going to be enough on its own
-- Linux has replicated Oasis faithfully, but has nothing playing the role of the Microsoft WMR
platform driver running alongside it. **This is a materially different, and arguably more honest,
explanation for tonight's clean negatives than "some undiscovered byte."**

**NEXT STEP, needs a live Windows capture, not more static RE**: the `windows-kit/capture-bringup.ps1`
run the user already planned should specifically watch for **Output-report (`02 xx`, non-`08`)
traffic concentrated in the pairing window**, not just the already-decoded Feature-report sequence
-- if `MotionControllerHid.dll`'s pairing-mode Output writes are distinguishable from the routine
`02 08` poll by subtype or timing, THAT is the missing command, and it comes from a source (the
Windows platform driver) Linux has never even tried to imitate. Static RE of the exact bytes is
parked, not because it failed, but because it hit a real WPP-tracing wall that needs either a PDB
this project doesn't have or a live/dynamic trace (e.g. a debugger breakpoint on the real `WriteFile`
call inside `FUN_18001dcb8` during an actual Windows pairing) rather than more static disassembly.

**Related MS Store app, checked, not currently installed, low priority**: the user also flagged
"Windows Mixed Reality OpenXR Developer Tools" (`apps.microsoft.com/detail/9n5cvvl23qbt`,
Microsoft-published; own description: "Habilita Mixed Reality OpenXR Runtime, consulta el estado
del sistema y ejecuta la escena de demostración con tecnología de OpenXR"). Confirmed NOT present
in `Program Files\WindowsApps` on this machine. Reads as an OpenXR runtime-status/demo-scene tool,
not a driver -- lower-priority than the CrystalKey lead above, worth a quick look only if the
Ghidra/live-capture leads dry up.

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

### The bonding model, mapped (user's tested record, 2026-08-20)

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

### T242 (2026-08-20/21, same night): the real PAIR command decoded byte-for-byte from a live Windows capture — the framing was never the problem

Two USBPcap captures landed (`windows-kit`, taken via Wireshark's own dumpcap, not
`capture-bringup.ps1` this time): `pairing_joys.pcapng` (22:15:36-22:23:01, 1.5 GB,
hardlinked into `debug_vr/`, screenshots `pairing.png`/`pairing2.png` alongside it) and
`pairing2_joys.pcapng` (00:06:48-00:11:47 the following morning, 365 MB, the "long" one).
Both are `unlock_wmr.exe` sessions (`Oasis Driver for Windows Mixed Reality`), not Oasis's
normal runtime — the standalone pairing utility T236 already identified as the one that
calls `HidD_SetFeature`.

**Decoding method** (worth keeping as the standard recipe): `usb.bmRequestType==0x21` isn't
enough — tshark only populates `usb.setup.bRequest`/`usb.setup.wValue` for requests it
doesn't have a class-specific dissector for, and the USBHID dissector swallows those fields
for `SET_REPORT`. The field that actually carries the payload for these frames is
**`usb.data_fragment`**, not `usb.capdata` (that one is for interrupt/bulk transfers and
only had unrelated `"Dlo+"`-prefixed camera/IMU bulk noise on this device address). Filter:
`usb.bmRequestType==0x21 and usb.bus_id==2 and usb.data_fragment`, dump every distinct
first-byte prefix, and the `0x16`-prefixed ones — the BT-control report — jump straight
out from the routine `02 08` poll noise (>99% of the traffic).

**The real command, confirmed for the first time from the wire, not inferred:**

```
SET_REPORT, wValue=0x0316  ->  ReportID=22 (0x16), ReportType=FEATURE (3)
wIndex=2 (HoloLens Sensors interface), wLength=64
payload: 16 05 <controller_id> 00 00 ... (61 more zero bytes)
```

This is **structurally identical** to what `controller-pair.py` already sends —
`{0x16, 0x05, controller_id}` via `HIDIOCSFEATURE`, same report ID, same report type, same
interface. **The byte framing was never the bug.** T236's "it did NOT pair" negative needs a
different explanation now — sequence or timing, not an unknown byte.

**Full decoded timeline, capture 1** (`controller_id`: 0=left, 1=right, per
`controller-pair-check.py:14`, confirmed self-consistent with this capture's own
`Found controller device (paired through Headset): Left` console line preceding the dialog):

| t (s) | frame | meaning |
|---|---|---|
| 182.1 | `16 09 00` | CMD_STATUS query, left |
| 254.4 | `16 06 00` | **UNPAIR, left** |
| 276.9 | `16 05 00` | **PAIR, left** |
| 370.4 | `16 07 00` | **undocumented subcommand — not in `wmr_protocol.h`, never seen before** |
| 373.9 | `16 09 00` | CMD_STATUS query, left |
| 380.9 | `16 05 00` | PAIR, left (retry) |
| 395.5 | `16 09 01` | CMD_STATUS query, right |
| 423.4 | `16 05 01` | PAIR, right |

Capture 2 (the "long" one, next morning): `16 09 00` at 108.3s, `16 09 01` at 116.0s, then
`16 05 01` (PAIR, right) at 138.5s — a clean second right-hand attempt, no unpair.

**Open items, none resolved yet:**
- **`0x16 0x07`** — a real subcommand this project has never captured before. Unknown
  meaning; candidate guesses (a discovery-window ping, an RSSI/link-quality poll) are
  unverified.
- **The left-hand UNPAIR+PAIR is disputed.** The wire is unambiguous (table above) and the
  `controller_id=0 -> left` mapping predates tonight (`controller-pair-check.py`, and
  `docs/03` line ~487 citing T236's own right-hand `16 05 01`) — it isn't a fresh guess made
  to fit this capture. But the user's own recollection is "no toqué el izquierdo, le puse
  que no ahí" (didn't touch the left, clicked No on that dialog). Both can't be true.
  **Not resolved by memory of either side** — needs `controller-pair-check.py` against the
  physical controllers once the headset is back on a healthy USB2 branch (bonding lives in
  the headset radio, survives the OS that wrote it, so a Linux check answers it cleanly).
  Left the file open here on purpose instead of picking a side.
- **The timing between "controller enters discovery" and "host sends PAIR" is still
  unmeasured.** Capture 1's UNPAIR-to-PAIR gap was 22.5s, but that's however long it took a
  person to read the `pairing2.png` dialog and press the physical button, not a controlled
  measurement of the minimum window needed. **Next planned test, agreed with the user**: a
  short, deliberately-timed capture — hold the button, count seconds, THEN click OK — done
  with the **LEFT** controller (already disturbed tonight by the item above, so it's no
  longer a clean "untouched control" anyway; the right stays as the less-disturbed side).
  This is what actually lets `controller-pair.py` replicate the sequence instead of just the
  bytes.

### T243 (2026-08-21, ~00:47-00:51): the planned timed capture landed — a single clean LEFT
pairing with no UNPAIR and no `0x16 07`, and the internal WICED BT log gives byte-level status
semantics a live timeline for the first time

`pairing3.pcapng` (444 MB, 224 s, `debug_vr/`, dumpcap) is the deliberately-timed capture T242
asked for: LEFT controller only, via the `windows-kit/power-on.ps1` flow ("Start pairing new
Left motion controller" / "power on, press ok when ready"). Decoded with the same recipe as
T242 (`usbhid.data.report_id`, not `usb.capdata` — that field only carries the unrelated
`Dlo+` camera/IMU bulk stream on this device) plus one new field: `usbhid.data.report_id==5`
recovers the radio-side debug log as plain ASCII, not just the command bytes T242 had.

**The command side is a single clean attempt**: `16 09 00` (status, left) at t=141.3, `16 05 00`
(**PAIR, left**) at t=188.331, `16 09 01` (status, right — just a post-check, no PAIR sent for
right all session) at t=207.2. **No UNPAIR, no `0x16 07`.** The left controller paired first
try, which weakens T240's "`0x16 07` might be needed before a successful retry" candidate —
here there was no retry and no `0x16 07` and it still worked.

**Full radio-side timeline, this attempt:**

| t (s) | event |
|---|---|
| 188.334-188.339 | `16 05 00` → `SET_VISIBILITY`(discoverability 0, connectability 1) → `SET_PAIRING_MODE`("allowed 1") → `COMMAND_INQUIRY` → "inquiry started" — same <10ms 3-step dance T240 found, now on a first-try clean case |
| 189.514 | **"Found by address: Motion Controller - Left"**, RSSI -48 — only **1.17s** after inquiry started |
| 194.743 | "inquiry complete" — the scan still runs its full ~5.2s window even though the target was found almost immediately; BT inquiry has no early-exit |
| 194.746-196.620 | `HIDH_COMMAND_CONNECT` → SDP discover → Product ID `0x066a` found → HID service found → IO-caps exchange → **new link key generated, `nvram_id 22` allocated ("First time")** → encrypted → `CONNECTED` → controller's own feature reports (`0x4`,`0x7`,`0x8` — config/calibration blobs) pulled over the new link |

**PAIR-to-CONNECTED: 196.600 − 188.331 = 8.27s**, matching T238's ~7s estimate and T240's 8.3s
measurement almost exactly — this is evidently a stable, repeatable duration, not
attempt-dependent noise.

**Does NOT fully close T242's "unmeasured discovery-window timing" item.** This is one
real, controlled trial (the physical button was held before the operator pressed OK, per
`power-on.ps1`'s own prompt) and it shows the controller was already discoverable well within
the 1.17s-to-found mark — but a single sufficient delay doesn't establish the *minimum* window,
which needs several trials at deliberately shortened delays to find where it starts failing.
Left open for a real minimum-window characterization if it's ever needed.

**New, not in any prior capture: the headset gets its known controller addresses PUSHED to it
by the host at session start, independent of pairing.** Twice in this capture, both well before
the PAIR command (t=64.2 and t=117.5 — two back-to-back boot/reconnect passes), the host sends
`COMMAND_SET_LOCAL_BDA` (the headset's own embedded-host BT address), then
`COMMAND_SET_LEFT_REMOTE_BDA` / `COMMAND_SET_RIGHT_REMOTE_BDA`, logged by the radio as
`Provisioned MC_LEFT <b4:a9:fc:b2:2d:07>` / `Provisioned MC_RIGHT <b4:a9:fc:b2:26:2d>` — followed
immediately by `HIDH_COMMAND_ADD` and an NVRAM push for the **right** controller (already
bonded, reconnecting on its known link key). The left address provisioned here is the *same*
address later found by live inquiry during the actual pairing at t=189.5 — consistent with
T240's "addresses survive an unbond" finding, but this is the first time the *provisioning
step itself* (host telling the radio which BDA is "left"/"right") has been seen on the wire, as
distinct from the radio's own bond/NVRAM state. What this address is actually used FOR by the
radio (inquiry filtering? pure bookkeeping?) is not established — the later PAIR still ran a
real over-the-air inquiry scan rather than connecting directly to the provisioned address, so
it does not look load-bearing for pairing itself. Left as an open question, not a claim.

**Confirms the existing status-byte semantics live, for the first time watched in the same
capture as the command that causes them** (semantics already documented in
`controller-pair-check.py`/`docs/12`, byte2: `0x0` UNPAIRED, `0x1` OFFLINE, `0x2` ONLINE —
nothing new here, just the first live before/after): report `0x17` for the left controller
(`17 00 ...`) reads `17 00 00 00 00 00` (UNPAIRED) continuously from t=180 through t=196.324,
then at **t=196.556** (inside the same 50ms window as `BTM_PAIRED_DEVICE_LINK_KEYS_UPDATE_EVT`
→ `nvram_id` allocation in the debug log) flips to `17 00 01 5e 04 00`, then at t=196.606 to
`17 00 02 5e 04 6a` (ONLINE, VID/PID bytes populated) — a ~50ms UNPAIRED→OFFLINE→ONLINE
transition, synced tightly enough to the debug-log events to use as a cross-check in any future
capture. The right controller's status (`17 01 01 5e 04 6a 06`, paired-offline) never changed
across the whole 224s session — confirms it was never touched, only status-polled.

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

## T244 (2026-08-21): pairing3.pcapng re-mined offline — both open leads closed as clean negatives

Desk work from NEXT-STEP's path #4, over the same capture as T243 (87,102 frames, 224 s, tshark
4.4.16, `usb.bmRequestType==0x21 and usb.bus_id==2 and usb.data_fragment` plus
`usbhid.data.report_id==5` for the radio log). Device map on that bus: addr1 `04b4:6504` hub,
addr2 `045e:0659` HoloLens Sensors — **the device the PAIR goes to** — addr3 `0bda:4c15` audio,
addr4 `03f0:0580` companion. At t≈115.4-116.3 s HoloLens Sensors **re-enumerated on Windows too**
(addr2 → addr5, same VID:PID), which is why the provisioning narration appears twice.

**(a) The SET_LOCAL_BDA / SET_REMOTE_BDA "provisioning preamble" is not a host command.** The
radio log narrates it twice, byte-identical (t=64.231-64.247 on addr2, t=117.517-117.524 on
addr5): `COMMAND_SET_LOCAL_BDA 0x3` → `WMR Embedded Host Address [b4 a9 fc cf e7 22]` →
`COMMAND_SET_LEFT_REMOTE_BDA 0x13` / `Provisioned MC_LEFT <b4 a9 fc b2 2d 07>` →
`COMMAND_SET_RIGHT_REMOTE_BDA 0x14` / `Provisioned MC_RIGHT <b4 a9 fc b2 26 2d>` →
`COMMAND_SET_VISIBILITY 0x8` → `HIDH_COMMAND_ADD 0x1303` → `COMMAND_PUSH_NVRAM_DATA 0x5` /
`BR/EDR LinkKey 932159EF…` / `NVRAM write: 138`. In both windows the only host→device frames are
`GET_DESCRIPTOR STRING` boilerplate, empty interrupt-IN re-arms, and one `SET_IDLE` at t=63.028
(wValue 0, content-free). No `0x16`, no vendor request, nothing. **It is the WICED radio
re-loading its own NVRAM at chip init, once per enumeration** — docs/03's earlier "pushed by the
host" reading is withdrawn; the wire shows no push.

**(b) The Output-report `02` channel, whole capture.** Only two host→device report ids ever reach
HoloLens Sensors: `02` (851 frames on addr2, 1283 on addr5) and `16` (3 frames: `16 09 00`
@141.324, `16 05 00` @188.331, `16 09 01` @207.223). The complete `02` vocabulary is
`{04, 06, 07, 08, 0b}`, always the bare fixed frame `02 xx 00…00` (65 bytes), no parameter ever
varies. **`02 08` is not a heartbeat**: it is a dense post-enumeration burst (852 frames in 1.2 s
on addr2; ~1700 in 17 s on addr5, 133-150 s) and then silence — 150-224 s holds exactly the
three `16` frames, six `02 07` frames at **t=196.577-196.853**, and one `02 0b` at 214.897. The
six `02 07` bracket the radio's CONNECTED sequence (two before `hidh_con_ctrl_connected` at
196.589, four after the last config-pull at 196.620), replacing `02 08` entirely for 276 ms —
**8.2 s after PAIR, at controller connect**, not at pairing entry. T241's "MotionControllerHid.dll
sends an enter-pairing-mode command on `02 xx`" is therefore **not supported** by this capture; the
one real `02 07` event reads as a new-HID-device-attached polling-profile refresh. Worth one
targeted check later: does `02 07` also fire when an already-paired controller reconnects?

**Around PAIR itself (t=186-200), exhaustively**: seven host→device frames total — `16 05 00` and
the six `02 07`. Nothing precedes the PAIR on any report id, any device. The Linux-side pairing
attempt's framing (`16 05 0x`) stands as the complete host contribution visible on USB; what
remains unexplained about our negative (T235/T236) is not a missing preamble.
