# 31 — Windows bring-up on the current stack, and what errors 108 / 422 actually mean

The Linux side of this project has a step-by-step gate that tells you which physical thing to
fix (`scripts/power-on.py`); on Windows every failure arrives as a bare four-digit code with
no map. This is that map, plus `windows-kit/power-on.ps1`, its script. It was written after
two sessions of "headset not detected" on two different Windows machines.

Everything marked **[lab]** was measured on this hardware. Everything marked **[upstream]**
comes from the Oasis driver's own wiki or its issue tracker and has *not* been reproduced
here — it's included because it names failure modes we would otherwise rediscover blind.
Sources at the end.

## What the current Windows stack even is

Microsoft removed Windows Mixed Reality from Windows 11 24H2. The Mixed Reality Portal,
"Windows Mixed Reality for SteamVR" (Steam app 719950) and the WMR OpenXR runtime are all
gone or inert. A G2 on a current Windows install is a paperweight until something replaces
that layer, and today the only thing that does is the **Oasis Driver for Windows Mixed
Reality** (Steam app 3824490, by mbucchia). **[upstream]**

**What Oasis actually is — the part that confuses everyone, including us:**

- It is a **SteamVR driver** (`driver_oasis`), i.e. a DLL that `vrserver.exe` loads on its
  own every time SteamVR starts. That is the part that does the real work: headset
  tracking, controller tracking, and the rendering pipeline into the panel. It is never
  "launched" by you; if it isn't loaded, SteamVR simply has no headset.
- The thing that appears in your Steam library as an app is **a setup tool**, not the
  driver. Its jobs are: install/register the driver, run the **unlock** procedure, and help
  with controller pairing. After that it has no runtime role — leaving it installed and
  never opening it again is the correct steady state. **[upstream + lab]**
- The **unlock** is a one-time-per-context step, not a launch step. It must be re-run:
  once per PC, once per headset, after pairing each new controller, after a Windows
  in-place upgrade/reinstall, and **after a GPU change**. Ordinary Windows Updates don't
  count. **[upstream]** This is why a machine that worked last month can start failing
  after hardware moves around.
- Note for anyone reading `docs/09`: the `driver_oasis.dll` disassembled there for the
  90 Hz investigation is this same driver. Its only panel command is *Display Enable*;
  there is still no refresh-rate command anywhere in it. **[lab]**

Requirements worth stating because they are hard gates, not suggestions: Windows 11 24H2 or
newer (23H2 works with a manual "disable the Mixed Reality device in Device Manager" step,
Windows 10 is unsupported), an NVIDIA or AMD RX5000+ GPU (Intel unsupported), SteamVR
installed, and **the headset on USB 3.0 — controller tracking does not work over USB
2.0**. **[upstream]**

## The script

```powershell
powershell -ExecutionPolicy Bypass -File .\windows-kit\power-on.ps1          # diagnose
powershell -ExecutionPolicy Bypass -File .\windows-kit\power-on.ps1 -Tune    # + apply tuning (admin)
```

Without `-Tune` it only reads (Device Manager, the registry, Steam's config files) and
needs no administrator. It walks the same five steps as the Linux `power-on.py`: USB census
split by branch, which port, controller pairing, software state, verdict — and when a step
fails it prints the physical ladder and waits for the reseat instead of just reporting a
code. It also reports every setting in "Tuning Windows for measurements" below; `-Tune`
(administrator) is what actually changes them.

For the 90 Hz-era captures (USBPcap, dxdiag, EDID) the tool is still
`windows-kit\run-diagnostics.ps1` — a different job, see `windows-kit\README.txt`.

**Status: written without a PowerShell available to syntax-check it, not yet run on Windows.**
Treat its first run as a test of the script as much as of the headset, and fix it in place.

## What the lab Windows install says (offline audit)

The Windows system partition was mounted read-only from Linux and read directly, which is
worth doing before any reboot: it answers questions that would otherwise cost a boot cycle
each. Everything in this section is **[lab]**, read off this install (24H2, build 10.0.26100).

**The single most useful thing found — it turns the 108 story from a correlation into a
mechanism.** The two drivers' manifests declare which headset they claim:

```jsonc
// steamapps/common/Oasis Driver for Windows Mixed Reality/driver.vrdrivermanifest
{ "name": "oasis",        "hmd_presence": [ "045E.0659" ] }
// steamapps/common/MixedRealityVRDriver/driver.vrdrivermanifest   (the old WMR one)
{ "name": "holographic",  "hmd_presence": [ "*.*" ], "alwaysActivate": false }
```

`045E.0659` **is the HoloLens Sensors device — the SuperSpeed branch**. So Oasis literally
does not activate unless that device is enumerated. A seat that gives you only the USB2
branch (companion + audio present, cameras absent) leaves SteamVR with no driver claiming a
headset, and that *is* error 108. Not "probably related": the driver's own activation
condition is the exact device our seat lottery drops.

The rest of the audit:

- `LastKnown.ActualHMDDriver = "oasis"`, `HMDModel = "HP Reverb Virtual Reality Headset
  G2"`, and a `HMDSerialNumber` matching the unit (value redacted — this repo is public;
  read it yourself from `Steam\config\steamvr.vrsettings` if you need to compare units).
  **Oasis has already worked on this install**, so the
  unlock was done at least once, which removes "missing unlock" from the top of the 108
  suspect list and pushes USB to the top, exactly where the manifest points.
- SteamVR 2.16.7, **stable branch** (no `betakey` in any of the three appmanifests), so the
  "422 comes from the beta" story does not apply here.
- **The old WMR driver is still installed AND still registered.** `openvrpaths.vrpath`
  lists both `MixedRealityVRDriver` and the Oasis directory as external drivers, and app
  719950 is installed. On 24H2 that driver has no runtime behind it, its manifest claims
  *any* headset (`*.*`), and Oasis's own troubleshooting guide says to disable every
  non-Oasis add-on. It can be disabled offline by adding to `Steam\config\steamvr.vrsettings`:

  ```json
  "driver_holographic" : { "enable" : false },
  ```

  That is the same thing SteamVR writes when you uncheck an add-on under Settings →
  Startup/Shutdown → Manage Add-Ons, so the revert is to re-check it there (or delete those
  three lines). This is a **hypothesis, not a proven fix**: it is the best 422 candidate visible from
  outside Windows.
- No `C:\ProgramData\WindowsHolographicDevices`; the per-user `SpatialStore` exists. If 422
  survives everything else, that directory is the "clear environment data" target.
- No `hiberfil.sys` → fast startup is already off, which is why the partition could be
  mounted read-write from Linux at all.

## Tuning Windows for measurements

A tracking-cost number captured on a machine that is free to downclock, park cores or
suspend USB is not comparable to the Linux numbers it is measured against. `windows-kit\power-on.ps1` **reports** all of these; with
`-Tune`, from an **administrator** PowerShell, it applies them.

| Setting | Why it matters here |
|---|---|
| USB selective suspend **off** | The one that overlaps this project's oldest ghost: a branch that "drops on its own" reads exactly like the marginal contact in `docs/22`. Rule it out before blaming the cable again. |
| Per-device USB power management **off** | Device Manager's "let the computer turn off this device", on the hubs the headset hangs from — same failure mode, different knob. |
| High performance plan, CPU min/max **100%** | Core parking and frequency scaling make a CPU-cost baseline unrepeatable. |
| PCIe ASPM **off** | Link power states add latency spikes on the GPU and USB controllers. |
| Fast startup **off** (`powercfg /h off`) | Boots from a real cold state, so a measurement isn't inheriting a frozen kernel from days ago — and it leaves NTFS clean, which is what lets Linux mount `C:` read-write to read the results. |
| Sleep / display / disk timeouts **never** | A long unattended capture must not be interrupted. |
| Game DVR **off** | Background recording steals GPU time silently. |

The equivalent by hand, if you'd rather not run the script (admin PowerShell):

```powershell
powercfg /setactive SCHEME_MIN
powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 `
                                          48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0   # USB suspend
powercfg /setacvalueindex SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 `
                                          ee12f906-d277-404b-b6da-e5fa1a576df5 0   # PCIe ASPM
powercfg /setacvalueindex SCHEME_CURRENT 54533251-82be-4824-96c1-47b60b740d00 `
                                          893dee8e-2bef-41e0-89c6-b55d0929964c 100 # CPU min
powercfg /change standby-timeout-ac 0 ; powercfg /change monitor-timeout-ac 0
powercfg /setactive SCHEME_CURRENT
powercfg /h off
```

Undo: `powercfg /setactive SCHEME_BALANCED`, `powercfg /h on`, and set the USB
`EnhancedPowerManagementEnabled` / `SelectiveSuspendEnabled` values back to 1.

**Read the current values from the registry, not from `powercfg /query` output** — the
output is localized and parsing it breaks on a localized Windows. The script reads
`HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes\<active>\<sub>\<setting>`,
which is language-independent. The GUIDs above are not localized either.

Not changed, but worth knowing when comparing latency numbers: hardware-accelerated GPU
scheduling (`HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\HwSchMode`, 2 = on).

## The error index

### 108 — "Headset not detected"

**What it means mechanically**: SteamVR has no HMD at all. Not "the headset is broken" —
*no device ever reached the driver*. It is the same generic code SteamVR shows for any
missing headset of any brand. **[upstream]**

**What it has meant on this hardware, every single time**: the headset's USB enumeration
was incomplete — specifically the SuperSpeed branch (hub `04B4:6504` + HoloLens sensors
`045E:0659`) had not come up, leaving only the USB2 branch (hub `04B4:6506` + companion
`03F0:0580` + audio `0BDA:4C15`). **[lab]**

That is not a coincidence, and the audit above proves why: **Oasis's manifest activates the
driver only when `045E.0659` — the SuperSpeed-branch sensors device — is present.** The
cause is the **seat lottery** documented in `docs/22` — a marginal C-plug/adapter contact
that engages *one* pin group per insertion. WMR/Oasis needs the SuperSpeed link, so a
USB2-only seat produces a headset that Windows partially sees (audio device appears,
companion appears) and SteamVR completely doesn't. Two different Windows machines showed
"not detected" for this one reason. **[lab]**

**Fix, in order** — identical to the Linux ladder because it's the same physical fault:

1. Rear USB3 port fed by the CPU. Front-panel and chipset ports have never worked for this
   headset on any machine here.
2. **Same port**, rotate the USB-C plug 180° inside the C-to-A adapter and reseat firmly.
   This is the move that won after ten seatings.
3. Another rear port.
4. Visor-end connector (behind the magnetic gasket), then everything at once — USB + DP +
   18.5 V brick out for a minute.

Success looks like **all five devices present in Device Manager**, not "the headset shows
up". `power-on.ps1` reports the two branches separately for exactly this reason.

**If you get 5/5 and still see 108**, the physical layer is fine and the next suspect is
software: the Oasis driver not registered in `%LOCALAPPDATA%\openvr\openvrpaths.vrpath`
(fresh Windows/Steam installs lose this) — re-run the unlock from the Oasis app.
**[upstream]**

### 422 — "SteamVR encountered an unexpected problem"

**What it means mechanically**: SteamVR *started* and then something failed underneath it.
This is the important distinction from 108: 108 is "nothing plugged in as far as I'm
concerned", 422 is "I was up and the driver let me down". Consequently **moving the cable
does not fix a 422** — if reseating changed anything, you were looking at a 108-class
problem. **[upstream + inference; the discriminator has not been run here yet]**

It is downstream of a stack that has to get far enough to fail, so it is inherently
intermittent where 108 is deterministic.

**Suspects, in the order worth checking:**

1. **SteamVR safe mode.** After certain crashes SteamVR disables third-party add-ons, then
   fails on the next start. Check SteamVR → Settings → Startup/Shutdown → Manage Add-Ons
   (needs Advanced Settings) and make sure `oasis` is **on**. **[upstream]**
2. **The unlock needs re-running**: GPU changed, Windows reinstalled/in-place upgraded, or a
   controller newly paired. **[upstream]** Seen live here: the first attempt failed to even
   find the presence device, a reseat fixed enumeration, and re-running unlock then succeeded
   (see "Live capture" below). [Oasis issue #48](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/issues/48)
   independently reports the G2 as unusually USB-port-sensitive **specifically under Oasis**,
   including ports that worked under the old WMR runtime; community guidance is that most 422
   reports are resolved by trying a different USB port. **[upstream, anecdotal, no mechanism
   published]**
3. **SteamVR beta.** Multiple reports of 422 appearing on the beta branch and going away on
   the stable one. Opt out before debugging anything else. **[upstream]**
4. **Corrupt environment data.** Clear `C:\ProgramData\WindowsHolographicDevices` and
   `%LocalAppData%\WindowsHolographicDevices`, then re-run Room Setup. **[upstream]**
5. **GPU driver settings** reset to defaults; on hybrid-GPU laptops this is a known 422
   trigger (not our case: both lab machines are desktops with a single discrete GPU).
   **[upstream]**

## Live capture of a 108-class recovery (`unlock_wmr.exe` console)

Three console captures taken back-to-back on the lab machine's Windows side (a Windows-only
SSD that stays mountable read-only from Linux). Between capture 1 and 2 the only change was a
**visor-end cable reseat**. They settle one question about `unlock_wmr.exe`'s scope:
**it provisions the headset AND the controllers in one pass**, not just the display/HID
unlock `docs/09` covered. Device instance IDs are elided here.

**Capture 1: fails at the USB2 branch, before it reaches unlock**

```
Found headset: HP Inc. VR3000-0XX (HP Reverb Virtual Reality Headset G2)
Found sensors device: \?\hid#vid_045e&pid_0659&mi_02&col01#...   (three of them: col01/02/03)
SensorsFW: 1.9.53
[Error] I can't find the USB OEM connection to your headset :(
```

The three "sensors device" lines are one physical interface (`045e:0659`, HoloLens Sensors, the
SuperSpeed branch) exposing three HID collections. **"I can't find the USB OEM connection"** is
the tool's name for a missing **presence device, `03F0:0580`** (the USB2 companion): the
SuperSpeed branch is alive and the USB2 branch is absent, the same signature as the Linux-side
seat lottery (`docs/22`), on a different OS with a different tool.

**Capture 2: after the reseat, the presence device is found and unlock runs**

```
SensorsFW: 1.9.53
Found presence device: \?\HID#VID_03F0&PID_0580#...
OEMFW: QA85QAPV1/1.2 | QA85QBLV1/7.0 | QA85QDPV1/50.49
Display EDID: 220e:36c1
Windows version: 10.0.26200 (10.0.26100.9168)
Nvidia Driver Version: 610.47 (r610_45)
Direct Mode: Successfully initialized NvAPI
Direct Mode: Failed to initialize LiquidVR: Did not find AMD GPU (This is expected if you do not have an AMD GPU)
Found display output with WMR EDID: \?\DISPLAY#HPN36C1#...
  Unlocking headset...
[Info] Unlocked your Windows Mixed Reality headset for use with Oasis.
       Please disconnect and reconnect the headset now. Press OK when done.
```

**Capture 3** (after the requested disconnect/reconnect) adds the two Realtek USB audio
endpoints, then `Clearing Motion Controller cache...`, `Found controller device (paired
through Headset): Left`, and the dialog "A Left motion controller is currently paired, would
you like to unpair it and pair a new Left motion controller now?". That string is the
`"Found controller device (paired through %s): %s"` format seen earlier in the `docs/09`
disassembly, here firing live.

What the captures add:

- **Three OEM firmware components, not one**: `QA85QAPV1/1.2`, `QA85QBLV1/7.0`,
  `QA85QDPV1/50.49` (application / bootloader / DisplayPort-bridge banks by naming pattern;
  matches the multi-bank DFU description in `docs/12`). First captured version numbers; worth
  diffing against a capture taken after any firmware update.
- **`Display EDID: 220e:36c1`** is the known ManufID `0x220E` (EDID spelling; DPLib reads
  `0x0E22`) = `HPN`, product `0x36c1` (`docs/12`, `docs/26`).
- **`HololensSensorsWinUsb.inf`** binds `USB\VID_045E&PID_0659&MI_03` as a raw WinUSB device (no
  kernel driver; a userspace app opens it via `DeviceInterfaceGUID
  {61bd6c28-9f10-426e-aa65-729d4656f6a2}`). The interface layout is in `docs/12` (USB topology).
- **The reseat was binary, not "more solid contact"**: it changed whether the USB2 branch
  enumerated at all. Once it did, unlock, audio and controller re-pairing all followed.

### Port-swap A/B: identity is not the failure mechanism

Hypothesis tested: moving the headset to another port invalidates a stored device identity.
Method: `Get-PnpDevice` / `Get-PnpDeviceProperty -KeyName DEVPKEY_Device_ContainerId` (no admin
needed) over all 9 device nodes behind the hub, baseline vs. a second rear USB 3.x port, diffed
programmatically. **Of 9 lines, exactly 2 changed, both the presence device (`03f0:0580`), and
only `Status` (`OK` -> `Unknown`); `InstanceId` and `ContainerId` stayed byte-identical.**
`Status=Unknown` on a device Windows can still name is the ghost / not-present signature: the
identity is remembered, the device is just not on the bus. SteamVR threw 422 in the new port.

**Conclusion:** a port change does not break Oasis by invalidating stored identity. It can
(port-dependent, mechanism unknown) knock out the USB2/companion branch's enumeration
entirely, the same SuperSpeed-solid / USB2-fragile split as the orientation A/B (`docs/22`).
Port choice joins plug orientation as a second confirmed trigger for that fault. Returning to
the original port restored 5/5 (checked from the Linux side with `lsusb`). Scope limits: this
explains *this* 422, not every 422 (the suspects above stay live), and it says nothing new
about 108. A methodology near-miss worth keeping: the first post-swap capture was
byte-identical to the baseline (a copy-paste slip, caught by diffing before it was trusted as
a null result).

Related findings from the same Windows disk (read off a read-only mount):

- **ContainerID** of the presence device and of the sensors device is the same value: the
  parent Cypress hub's own hardware serial (`<HUB-CONTAINER-ID>`, also reported by
  `lsusb -v -d 04b4:6504` / `-d 04b4:6506` on Linux), reformatted as a GUID. Windows groups both
  branches as one physical object, keyed to fixed silicon, not to the port.
- **Registry export method:** raw `strings` on a hive gives false negatives (value names are
  stored 8-bit, and one key's values are not stored next to its name). Use `chntpw`'s
  `reged -x <hive> HKEY_LOCAL_MACHINE\SYSTEM '<path>' out.reg`, or `regipy`.
- **`HololensSensors.inf`** (version `10.0.19041.2054`, still in `DriverStore`) declares
  `Class = Holographic` (`{d612553d-06b1-49ca-8938-e39ef80eb16f}`) and one WDF property
  (`DeviceGroupId = "MixedRealityHmd"`, power/idle grouping, not identity). Neither the ClassGuid
  nor the string "Holographic" appears anywhere in the SYSTEM hive: on 24H2/25H2 the class is
  fully purged, so the INF is dead weight and `unlock_wmr.exe` / Oasis cannot be routing through
  it. This fits `docs/09`: Oasis works purely through generic USB/HID `SetupAPI` / `CfgMgr32`.

### Floor / height calibration storage (registry audit, null result)

No native WMR floor-height schema is visible on a 24H2 install: the Holographic registry keys
are empty stubs and the spatial store (`...\WindowsHolographicDevices\SpatialStore\...\HeTDb.edb`)
holds only a SLAM pose graph with no floor or height scalar. The only floor-like value on the
box is derived by SteamVR Room Setup into `config\chaperone_info.vrchap` (separate `seated` and
`standing` reference poses; `standing.translation.y` is an origin offset, not a stored user
height). Whether a pre-24H2 install ever stored an explicit height value is unknown.

### 498 — "Failed to lease display"

Not a Windows error. It is what SteamVR **native on Linux** reports when `vrcompositor` cannot
take the headset's connector. If you see 498 while chasing a Windows problem, two
investigations are crossed. **[lab]**

## The cable landmine: v1 vs v2

**The Oasis unlock tool hangs on the "EDID identification" step with the Reverb G2 v1 cable
(PN `L72080-001`) and completes normally with the v2 cable (PN `L72080-002`).** The reporter
tested three headsets: both v1 units hung, the v2 unit unlocked, and swapping cables made all
three work. Root cause unknown upstream. **[upstream]**

**If the unlock hangs, check the part number printed on the cable first.** This concerns the
unlock tool only: a v1 cable can drive the G2 at 90 Hz for hours on Windows and Linux. **[lab]**
It also gives a replacement cable a justification independent of the marginal-contact fault
in `docs/22`.

## What Oasis actually does: two functions

**Function 1: USB activation, bound to ONE port, and only a CPU-fed USB3 port.** Oasis
activates the USB on a *single* port, the one active when setup/pairing was done. The binding
survives across sessions and only ever succeeds on a **CPU-fed USB3** port. Both conditions
were tested here: being a technically valid port is necessary but not sufficient, since an
equally valid CPU port that is not the bound one **fails** until Oasis is relaunched to
re-bind. The port-swap A/B above is the measured signature: identity unchanged, companion
flips to `Status: Unknown`.

The Linux census explains why only that socket class works:

| socket type | SS branch | USB2 branch (companion) | what Oasis sees |
|---|---|---|---|
| CPU-fed USB3, good seat | yes | yes | **both branches, works** |
| chipset USB3 (this board) | yes | no (`error -71`) | sensors but no companion, fails |
| black USB2 | no | yes | companion but no SuperSpeed, **WMR refuses** (`docs/22`) |

Oasis needs the full 5-device census exactly like the Linux launcher does. The difference:
Oasis *binds* the result to the port (host-side state), while Linux re-discovers by identity
on every launch and holds no binding at all.

**Function 2: controller pairing.** Oasis ties the controllers to the headset's internal
radio. The battery-compartment button ERASES the assignment, and only the Windows side can
recreate it. **Linux reads the state** (`scripts/controller-pair-check.py`, `docs/03`) **but
cannot create it**, the last named Windows dependency in this project.

**Pairing fallback:** the original Mixed Reality Portal still runs on any pre-24H2 Windows, so
adopting a controller needs *a* Windows once (an old install or spare disk), not the current
one kept online.

**The fight predates Oasis.** With the original Microsoft WMR driver on a new motherboard,
the same combination (headset activation plus controller pairing) fought the same way, and
the original driver surfaced nothing useful while failing (no indication of which port,
branch or step). Oasis reimplemented the combination, not the pain. Budget for a fight on
any first bring-up on fresh hardware, on either driver and OS. The missing diagnostic (what is
failing, which branch, which port) is what this repo's Linux tooling (`scripts/find-port.sh`,
the census) fills.

### The port binding: observation solid, mechanism NOT established

- **Oasis's own wiki never documents port binding.** Its re-run triggers are per computer, per
  headset, after a new controller, after a Windows reinstall, after a GPU change; a port move
  is not listed. The binding is community-observed (issue #48: *"The HP Reverb G2 is very picky
  about USB ports. Even if the port you used previously with WMR worked well, it might not with
  Oasis"*, closed "not planned") and reproduced here.
- **Microsoft's WMR error codes name real per-port mechanisms**: **4-1** = SuperSpeed link
  mandatory (*"unable to create a USB 3.0 SuperSpeed connection"*); **7-12** = xHCI drivers
  that cannot handle the **ContainerID descriptor** *"which aggregates the different parts of
  the Mixed Reality headset into a cohesive unit"* (our five-device census in Microsoft's
  words); **7-13** = controllers lacking **ITP** (isochronous timestamps) break camera-frame
  timing; **4-4** = port stuck in Compliance Mode.
- **Cross-check:** the A/B shows ContainerID/InstanceId identical across ports with only
  `Status: Unknown`, which argues for a live enumeration/link failure on that port, not identity
  ghosting. Yet "relaunch Oasis and it re-binds" says host-side association state exists too.
  Both observations stand; do not present either alone as the explanation.
- **The unlock is host-side only:** its official *revert* is CRU's `reset-all.exe` (a registry
  EDID-override cleaner, the same mechanism class as `patches/nvidia/0004`); its "deep cleanup"
  touches only `C:\ProgramData\WindowsHolographicDevices` and the LocalAppData twin; the wiki
  states Oasis cannot write headset firmware. Nothing the Windows side does marks the headset,
  consistent with Linux finding zero state to migrate.
- **The original MRP was port-sensitive too** (Microsoft's setup FAQ: "plug the headset into
  different ports... uninstall and reinstall WMR").

**A Windows-side fix from the community record:** an "invisible" controller with visibly DIM
LEDs is associated with a corrupted host-side calibration cache. Deleting
`C:\Windows\ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\MotionController\Calibration`
lets it rebuild. (Monado also caches controller calibration host-side: `cache_filename` in
`wmr_controller_base.c`.)

## Bring-up checklist for a fresh Windows machine

1. Windows 11 24H2 or newer, current GPU drivers, SteamVR installed.
2. Headset on a **rear, CPU-fed USB 3.x port**; DP straight into the GPU; 18.5 V brick in.
3. Run `windows-kit\power-on.ps1`; expect 5/5 devices before doing anything else.
4. Pair the controllers **via Oasis's unlock flow** (it prompts per controller, left first;
   hold the button until the slow pulse). The old "Settings > Bluetooth > Add device" path from
   Microsoft's generic WMR guide pairs to the **PC's** radio, is unvalidated for the G2 (whose
   controllers belong on the *headset's* radio), and is never used for radio-equipped headsets
   in the Oasis wiki. Prefer the Oasis flow.
5. Launch the Oasis app **once**, run "unlock your headset & controllers", unplug/replug the
   headset's USB when it asks (leave DP connected), power-cycle the controllers when asked.
6. Room Setup.
7. From then on: just start SteamVR. The Oasis app stays installed and closed.

`windows-kit\power-on.ps1` is deliberately ASCII-only (Windows PowerShell 5.1 reads BOM-less
UTF-8 as ANSI), and any `.bat` wrapper needs CRLF line endings (LF-only breaks parenthesised
`if` blocks).

## Sources

- Oasis Driver wiki: [Home](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki),
  [Troubleshooting Guide](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Troubleshooting-Guide),
  [Known Issues](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Known-Issues),
  [Pairing Motion Controllers](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Pairing-Motion-Controllers),
  [Unlock procedure](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Procedure-to-unlock-headset-and-controllers-for-Oasis)
- [Issue #19: unlock hangs with the G2 v1 cable (L72080-001)](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/issues/19)
- [Issue #26: error 422 on HP Reverb G2](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/issues/26)
- [Issue #48: G2 is USB-port-sensitive under Oasis](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/issues/48)
- [SteamVR "Headset not detected (108)" discussion](https://steamcommunity.com/app/719950/discussions/0/3183345176718736883/)
- This repo: `docs/22` (link anatomy, the seat lottery), `docs/09` (what `driver_oasis.dll`
  sends to the panel), `docs/pruebas.jsonl` (measurement ledger).

## Background references (retired Microsoft pages and a community preservation guide)

Microsoft's WMR documentation is retired (its banner says it "may not be updated in the
future") and WMR devices lose all support after November 2026. Verbatim copies were removed
from this repo; the pages and what they contribute:

- **Microsoft Learn, "Windows Mixed Reality enthusiast documentation"**, section root
  `https://learn.microsoft.com/en-us/windows/mixed-reality/enthusiast-guide/`, pages "Before you
  start" and "Get help with PC compatibility" (last updated 01/2023 and 11/2025). Wayback:
  `https://web.archive.org/web/*/learn.microsoft.com/en-us/windows/mixed-reality/enthusiast-guide/*`.
  Content: WMR is **not supported on Windows 11 24H2 and newer** (support limited to Windows 10
  20H2 through Windows 11 23H2); a WDDM 2.2+ GPU; Bluetooth, USB 3.0 and display adapters; an
  open room for the boundary.
- **The one checkable PC-compatibility claim:** the compatibility page names the **Etron** USB
  host chipset as incompatible and says to check that Device Manager's "eXtensible Host
  Controller" entry ends in "Microsoft" (the inbox xHCI driver, not a vendor one). Checked with
  `lspci -nnk` on the lab machine: both host controllers are native AMD (`02:00.0` AMD 400
  Series chipset xHCI, chipset-attached; `09:00.3` AMD Matisse USB 3.0, CPU-attached), with no
  Etron or other discrete USB controller, so this failure class does not apply here.
- **Community preservation guide** (r/HPReverb, "Usability of Reverb G2 with WMR after November
  2026": `https://www.reddit.com/r/HPReverb/comments/1b9v0y3/usability_of_reverb_g2_with_wmr_after_november/`;
  not independently verified here). A recipe for an all-offline WMR install: keep a Windows 10
  22H2 / 11 23H2 ISO, the WMR device driver `10.0.19041.2054` (hash-identical to the one on the
  lab Windows disk), the Feature-on-Demand packages, the SteamVR and "Windows Mixed Reality for
  SteamVR" directories, and the Store packages (Mixed Reality Portal, HP Reverb G2 VR Headset
  Setup, OpenXR for WMR, fetched with `store.rg-adguard.net`). Caveat from the thread: some
  WMR components are embedded in the OS itself and cannot be preserved by saving installers.
  It also confirms the Holographic device class was removed in 24H2.
