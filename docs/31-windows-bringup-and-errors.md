# 31 — Windows bring-up on the current stack, and what errors 108 / 422 actually mean

**Born 2026-08-13 (T172), after two sessions of "headset not detected" on two different
Windows machines.** The Linux side of this project has a step-by-step gate that tells you
which physical thing to fix (`scripts/power-on.py`); the Windows side had nothing, so every
failure there arrived as a bare four-digit code with no map. This is that map, plus
`windows-kit/power-on.ps1`, its script.

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
  never opening it again is the correct steady state. **[upstream + user's own observation]**
- The **unlock** is a one-time-per-context step, not a launch step. It must be re-run:
  once per PC, once per headset, after pairing each new controller, after a Windows
  in-place upgrade/reinstall, and **after a GPU change**. Ordinary Windows Updates don't
  count. **[upstream]** This is why a machine that worked last month can start failing
  after hardware moves around — which is exactly what happened here in T171.
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

**Status: written 2026-08-13, not yet run on Windows** (this repo's machine boots Linux;
there is no PowerShell here to even syntax-check it). Treat its first run as a test of the
script as much as of the headset, and fix it in place — that's cheaper than the alternative
of having nothing.

## What this machine's Windows install actually says (offline audit, 2026-08-13)

The Windows system disk (`nvme0n1p3`) was mounted from Linux and read directly, which is
worth doing before any reboot: it answers questions that would otherwise cost a boot cycle
each. Everything in this section is **[lab]**, read off this install.

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
  unlock was done here at least once — which removes "missing unlock" from the top of the
  108 suspect list and pushes USB to the top, exactly where the manifest points.
- SteamVR 2.16.7, **stable branch** (no `betakey` in any of the three appmanifests), so the
  "422 comes from the beta" story does not apply here.
- **The old WMR driver is still installed AND still registered.** `openvrpaths.vrpath`
  lists both `MixedRealityVRDriver` and the Oasis directory as external drivers, and app
  719950 is installed. On 24H2 that driver has no runtime behind it, its manifest claims
  *any* headset (`*.*`), and Oasis's own troubleshooting guide says to disable every
  non-Oasis add-on. **Disabled offline** by adding to `Steam\config\steamvr.vrsettings`:

  ```json
  "driver_holographic" : { "enable" : false },
  ```

  That is the same thing SteamVR writes when you uncheck an add-on under Settings →
  Startup/Shutdown → Manage Add-Ons, so the revert is to re-check it there (or delete those
  three lines). This is a **hypothesis being acted on, not a proven fix**: it is the best
  422 candidate visible from outside Windows, and the next boot is what tests it.
- No `C:\ProgramData\WindowsHolographicDevices`; the per-user `SpatialStore` exists. If 422
  survives everything else, that directory is the "clear environment data" target.
- No `hiberfil.sys` → fast startup is already off, which is why the partition could be
  mounted read-write from Linux at all.

## Tuning Windows for measurements

This matters for `docs/30`'s tracking-cost baseline: a number captured on a machine that is
free to downclock, park cores or suspend USB is not comparable to the Linux numbers it's
supposed to be measured against. `windows-kit\power-on.ps1` **reports** all of these; with
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
output is localized and parsing it breaks on a Spanish Windows. The script reads
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
`03F0:0580` + audio `0BDA:4C15`). **[lab, T171 + user report T172]**

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
   This is the move that actually won in T171, after ten seatings.
3. Another rear port.
4. Visor-end connector (behind the magnetic gasket), then everything at once — USB + DP +
   12 V brick out for a minute.

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

That also explains the "sometimes" the user reports: it is downstream of a stack that has
to get far enough to fail, so it's inherently intermittent where 108 is deterministic.

**Suspects, in the order worth checking:**

1. **SteamVR safe mode.** After certain crashes SteamVR disables third-party add-ons, then
   fails on the next start. Check SteamVR → Settings → Startup/Shutdown → Manage Add-Ons
   (needs Advanced Settings) and make sure `oasis` is **on**. **[upstream]**
2. **The unlock needs re-running** — GPU changed, Windows reinstalled/in-place upgraded, or
   a controller was newly paired. Given this project just rearranged two machines and moved
   the SSD around, this is a strong candidate right now. **[upstream]** Confirmed live
   2026-08-16 (see "Live capture" below): first attempt failed to even find the presence
   device, a reseat fixed enumeration, re-running unlock then succeeded and a long session
   followed. Separately corroborated by [Oasis issue #48](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/issues/48):
   the G2 is reported unusually USB-port-sensitive **specifically under Oasis**, including
   ports that worked fine under the old WMR runtime — no maintainer-confirmed mechanism, but
   independent evidence this isn't just our cable being odd. Community guidance found the
   same night: *"9 out of 10 error 422 issues are resolved by... trying a different USB
   port... even if a USB port worked well previously with WMR, it might not work with
   Oasis."* **[upstream, anecdotal — no mechanism published]**
3. **SteamVR beta.** Multiple reports of 422 appearing on the beta branch and going away on
   the stable one. Opt out before debugging anything else. **[upstream]**
4. **Corrupt environment data.** Clear `C:\ProgramData\WindowsHolographicDevices` and
   `%LocalAppData%\WindowsHolographicDevices`, then re-run Room Setup. **[upstream]**
5. **GPU driver settings** reset to defaults; on hybrid-GPU laptops this is a known 422
   trigger (not our case — both machines here are desktops with a single discrete GPU).
   **[upstream]**

## Live capture, 2026-08-16 — a 108-class recovery caught mid-sequence, verbatim

Three phone photos of `unlock_wmr.exe`'s console, taken back-to-back on this lab machine's
Windows side. **Correction from the first version of this note**: not a single-disk
dual-boot — Linux runs from its own SSD, and the `nvme0n1` drive (partition `p3`, see "What
this machine's Windows install actually says" above) is a second, physically separate SSD in
the same box, Windows-only. Both are visible simultaneously in `lsblk`, so `nvme0n1p3` can
still be mounted read-only from this Linux session without rebooting. Between shot 1 and shot 2 the user did
a **visor-end cable reseat**, nothing else. Transcribed in full because every device
instance ID in it is directly checkable against the registry, and because it settles one
question about `unlock_wmr.exe`'s scope that was only inferred before: **it provisions the
headset AND the controllers in one pass**, not just the display/HID unlock docs/09 covered.

**Shot 1 — fails at the USB2 branch, before it ever reaches unlock:**

```
Found headset: HP Inc. VR3000-0XX (HP Reverb Virtual Reality Headset G2)
Found sensors device: \?\hid#vid_045e&pid_0659&mi_02&col01#9&11ae2a37&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}
Found sensors device: \?\hid#vid_045e&pid_0659&mi_02&col02#9&11ae2a37&0&0001#{4d1e55b2-f16f-11cf-88cb-001111000030}
Found sensors device: \?\hid#vid_045e&pid_0659&mi_02&col03#9&11ae2a37&0&0002#{4d1e55b2-f16f-11cf-88cb-001111000030}
SensorsFW: 1.9.53
[Error] I can't find the USB OEM connection to your headset :(
```

All three "sensors device" lines are the same physical interface (`vid_045e&pid_0659` =
HoloLens Sensors, the SuperSpeed branch) exposing three HID collections (`col01/02/03`) —
consistent with the already-documented 3DoF/tunnel HID layout. **"I can't find the USB OEM
connection"** is the tool's plain-English name for exactly the fault this project has been
chasing all week: it's asking for the **presence device, `VID_03F0&PID_0580`** — the USB2
companion — and it's not enumerated. This is a clean, independent, Windows-side echo of the
2/5 seat (`docs/pruebas.jsonl` T184): SuperSpeed branch alive, USB2 branch absent, same
signature, different OS, different tool.

**Shot 2 — after the reseat, presence device found, unlock runs clean:**

```
[... same three "sensors device" lines, byte-identical instance IDs ...]
SensorsFW: 1.9.53
Found presence device: \?\HID#VID_03F0&PID_0580#8&2513e90&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}
OEMFW: QA85QAPV1/1.2 | QA85QBLV1/7.0 | QA85QDPV1/50.49
Display EDID: 220e:36c1
Windows version: 10.0.26200 (10.0.26100.9168)
Nvidia Driver Version: 610.47 (r610_45)
Direct Mode: Successfully initialized NvAPI
Direct Mode: Failed to initialize LiquidVR: Did not find AMD GPU (This is expected if you do not have an AMD GPU)
Found display output with WMR EDID: \?\DISPLAY#HPN36C1#5&15f15d47&0&UID28933#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}
  Unlocking headset...
[Info] Unlocked your Windows Mixed Reality headset for use with Oasis.
       Please disconnect and reconnect the headset now. Press OK when done.
```

New facts, not previously in this repo:

- **Three OEM firmware components, not one**: `QA85QAPV1/1.2`, `QA85QBLV1/7.0`,
  `QA85QDPV1/50.49`. Naming pattern suggests Application/Bootloader/DisplayPort-bridge
  firmware banks — matches `docs/12`'s STM32 DFU description (`bridge_fw_check_update`,
  multiple flash banks) but this is the first time actual version numbers were captured.
  Worth diffing against a future capture if a firmware update is ever applied.
- **`Display EDID: 220e:36c1`** matches the already-known ManufID `0x220E` = `HPN` and
  product `0x36c1` from `docs/12`/`docs/26` — cross-check, not new, but confirms the tool
  reads the same EDID this project has been fingerprinting all along.
- The display device path's `UID28933` is a **separate identity from the presence device's
  HID path** — one is keyed off the GPU's DP output, the other off the USB HID enumeration.
  If Oasis's unlock record ties both together, a USB-port-only change (DP staying put)
  could still invalidate just the HID half. Relevant to the port-swap test below.

**Shot 3 — after the disconnect/reconnect the dialog asked for, then controller pairing:**

```
[... same three "sensors device" lines AND the same presence device line, byte-identical
     instance IDs, including "8&2513e90&0&0000" — see note below ...]
Found audio device: {0.0.0.00000000}.{ac17aa27-f06f-465f-b0a5-03005094e115} (Speakers (Realtek USB2.0 Audio))
Found audio device: {0.0.1.00000000}.{b518559e-2e91-4db9-944d-acf3357947e4} (Microphone (Realtek USB2.0 Audio))
Clearing Motion Controller cache...
Looking for Windows Mixed Reality motion controllers...
Found controller device (paired through Headset): Left
[Info] Your headset is capable of pairing motion controllers directly with the headset.
       A Left motion controller is currently paired, would you like to unpair it and pair
       a new Left motion controller now? If you press No, your current pairing will be
       left untouched.
```

**The user's read of all three, and it holds up**: this is *not* a loose/flaky physical
contact story — the reseat didn't make a marginal connection "more solid," it changed
whether the USB2 branch enumerated at all (binary, not intermittent), and once it did, the
whole rest of the chain (unlock, audio, controller re-pairing, and later a long, clean,
excellent-tracking session) fell into place and stayed stable. `docs/09`'s
`"Found controller device (paired through %s): %s"` string was known from the 2026-08-06
disassembly but never seen fire live with real data before this.

**Control data point for the port-swap test** (see the plan below, "Suspects" item 2): the
presence device's instance ID suffix, **`8&2513e90&0&0000`, is byte-identical between shot
2 and shot 3** — i.e. surviving a real USB disconnect/reconnect *in the same port*. If a
future capture in a **different** port changes that `2513e90` segment, it's consistent with
Windows deriving it from enumeration location (topology-sensitive, breaks on port change
even with a real serial present — all four devices in this chain report proper hardware
serials, checked live on the Linux side the same night, see `lsusb -v`); if it stays the
same, the ID is keyed off something port-independent (most likely the parent hub's serial,
`EE4482CE...`, shared identically by both the SuperSpeed and USB2 personas of the same
Cypress chip) and the community's port-sensitivity reports (see below) would need a
different explanation than "location-based instance ID."

### The registry, read directly off this box's `nvme0n1p3` (2026-08-16, same night)

Two corrections first: this is **not** single-disk dual-boot — Linux runs off its own SSD;
`nvme0n1` is a second, physically separate Windows-only drive in the same box, mountable
read-only from Linux without a reboot (`mount -t ntfs-3g -o ro,uid=1000,gid=1000
/dev/nvme0n1p3 /mnt/win3`). And raw `strings`/byte-proximity guessing on the hive turned out
to be unreliable and was abandoned mid-attempt (a "ContainerID" text search near our device's
byte offset came up empty even though the value demonstrably exists — value names in this
hive are stored narrow/8-bit, not UTF-16, and cells for one key's values are not guaranteed
to sit near the key name in the file). `chntpw`'s `reged -x <hive> HKEY_LOCAL_MACHINE\SYSTEM
'<path>' out.reg` gives a clean, correct, recursive export instead — use that, not manual
`strings`.

**The actual export of the presence device's Enum key, `ControlSet001\Enum\HID\
VID_03F0&PID_0580\8&2513e90&0&0000`:**

```
"ContainerID"="{ee4482ce-afe7-5844-820a-73f26905a52f}"
```

**This is the parent Cypress hub's own hardware serial** (`EE4482CEAFE75844820A73F26905A52F`,
read live via `lsusb -v -d 04b4:6506` and `-d 04b4:6504` on the Linux side the same night —
both the SuperSpeed and USB2 personas of the one physical chip report it identically),
reformatted as a GUID, not anything port-derived. **Confirmed identical on the sensors
device too** (`ControlSet001\Enum\HID\VID_045E&PID_0659&MI_02&Col01\9&11ae2a37&0&0000`,
same export method): both branches — SuperSpeed and USB2, the two that have spent all week
enumerating independently of each other (T184) — carry the exact same `ContainerID`. Windows
groups them as one physical object correctly, keyed to fixed silicon, not to which port they
happen to be plugged into right now.

**This complicates, not confirms, the port-swap hypothesis** — if Windows' own "is this the
same physical thing" answer is container-ID-based and container ID is serial-derived, a port
change alone shouldn't invalidate it. What's left open is the OTHER identifier in the same
export, the instance-ID suffix (`8&2513e90&0&0000`) — a hash of the parent's path, which
may or may not itself be location-sensitive independent of ContainerID. **If Oasis's own
unlock bookkeeping happens to key off that suffix (or the raw device path string it's
embedded in) instead of ContainerID, a port change could still break it even though Windows
itself would know better.** That is now the specific, falsifiable thing the pending port-swap
test settles: watch both fields, not just whether unlock succeeds or fails.

**RESOLVED, same night (`docs/pruebas.jsonl` T185): the identity hypothesis is dead, and
it's actually good news.** Full A/B done with `Get-PnpDevice`/`Get-PnpDeviceProperty
-KeyName DEVPKEY_Device_ContainerId` (no admin needed — cleaner than reading the hive by
hand) across all 9 device nodes behind the hub, baseline vs. a second, genuinely different
rear USB 3.x port. Diffed programmatically: **of 9 lines, exactly 2 changed — both belonging
to the presence device (`03f0:0580`) — and only their `Status` (`OK` → `Unknown`), not their
`InstanceId` or `ContainerId`, which stayed byte-identical.** `Status=Unknown` on a device
`Get-PnpDevice` can still name by ID is the classic ghost/non-present signature: Windows
remembers exactly who this is, it's just not on the bus right now. The SuperSpeed/sensors
branch (`045e:0659`) didn't move at all. SteamVR did throw 422 in the new port, and the user
correctly didn't bother re-testing it once the PnP data already explained why. **Conclusion:
port changes don't break Oasis by invalidating some stored identity — they can (not always,
port-dependent, mechanism still unknown) knock out the USB2/companion branch's enumeration
entirely, the exact same SuperSpeed-solid/USB2-fragile split T184 already characterized with
the orientation A/B test.** Port choice joins orientation as a second confirmed trigger for
the same underlying fault; *why* either one flips the USB2 branch is still open. One methodology
near-miss worth keeping: the user's first pasted post-swap capture was byte-identical to the
baseline (diffed and confirmed) — a copy-paste accident, caught by the user's own instinct
before it was trusted as a real null result. The careful second capture is what's recorded
here.

**Scope correction, same night, flagged by the user before it hardened into an overclaim**:
this rules out identity-mismatch as the mechanism for *this specific* 422 — it does **not**
establish that 422 is always a hardware/enumeration issue. The suspects list two sections up
("422 — Suspects, in order worth checking": safe mode, unlock needing re-run, beta channel,
corrupt environment data, GPU driver reset) is still live for *other* 422 occurrences; this
test just adds one more, confirmed, concrete cause to the pile — a ghosted companion device —
without closing the others. And **108 is a separate error with its own already-documented
mechanism** (tied to the SuperSpeed/`045E.0659` branch specifically being absent, not the
companion) — don't read this section as extending to 108, the two shouldn't be conflated.

**Closed out, same session**: reconnected to the original port, checked from the Linux side
(`lsusb` + sysfs mtimes, not PowerShell — genuine cross-OS validation) — full 5/5, freshly
enumerated (~3.5 min old at check time, matching the reconnect). The ghosted branch recovered
on its own. **But say precisely what this test actually resolved, not more**: the project's
real open question — why the USB2/companion branch sometimes fails to enumerate and how to
force it reliably — is exactly as open as it was before tonight. What got resolved is
narrower: a competing hypothesis born from tonight's own photos ("maybe this is a missing
software provisioning step, not hardware") was tested and killed — `unlock_wmr.exe`
succeeding turned out to be downstream of the companion device already being enumerated, not
a cause of it. Net effect: the original active-cable-hub-firmware hypothesis survives, gains
USB port choice as a second confirmed trigger alongside T184's orientation finding, and still
has no confirmed fix.

**Also confirmed from the driver side, reading Microsoft's own `HololensSensors.inf`
straight out of this machine's `DriverStore\FileRepository`** (no download needed — it's
already installed here, version `10.0.19041.2054`, exactly the version named in the Reddit
thread cited below): the INF declares `Class = Holographic`, `ClassGuid =
{d612553d-06b1-49ca-8938-e39ef80eb16f}` — a real, formal Windows Device Setup Class, not
just an SteamVR driver-manifest name — and sets one WDF grouping property via `AddReg`:
`HKR, "WUDF", "DeviceGroupId", REG_SZ, "MixedRealityHmd"` (coordinates power/idle state
across the composite device's several interfaces; documented Microsoft mechanism, not
identity/provisioning — no `ContainerID` directive anywhere in the INF, confirming Windows
assigns that on its own, not something HP/MS hand-configured). **Checked live: neither the
ClassGuid nor the literal string "Holographic" appears anywhere in this machine's SYSTEM
hive** — the class really has been fully purged on this Windows 11 24H2/25H2 build (matches
a r/HPReverb comment, "the entire class has been removed" — see Sources). The INF sitting in
DriverStore is dead weight, not bound to anything live. Practical upshot: whatever
`unlock_wmr.exe`/Oasis does, it cannot be routing through this old Microsoft Holographic-class
machinery — it's gone — reinforcing docs/09's finding that Oasis works purely off generic
USB/HID `SetupAPI`/`CfgMgr32` calls.

- [r/HPReverb — "Usability of Reverb G2 with WMR after November 2026"](https://www.reddit.com/r/HPReverb/comments/1b9v0y3/usability_of_reverb_g2_with_wmr_after_november/) —
  preservation guide for the original WMR stack (not Oasis), useful for two things: confirms
  the Holographic device class was fully removed in 24H2 ("the entire class has been
  removed"), and one commenter (`divxmaster`) mentions needing to "change two reg entries
  under Holographic" to get an offline install working — unspecified which, not chased
  further, noted as a lead if the port-swap test comes back needing one.

### 498 — "Failed to lease display"

Not a Windows error at all. It is what SteamVR **native on Linux** reports when
`vrcompositor` can't take the headset's connector (T170). If you see 498 while chasing a
Windows problem, you've crossed wires between two different investigations. **[lab]**

## The cable landmine: v1 vs v2, and why it matters here

**The Oasis unlock tool hangs on the "EDID identification" step with the Reverb G2 v1 cable
(PN `L72080-001`), and completes normally with the v2 cable (PN `L72080-002`).** The
reporter tested three headsets: both v1 units hung, the v2 unit unlocked, and swapping
cables made all three work. Root cause unknown upstream. **[upstream]**

This matters more to this project than to most: our whole cable saga (`docs/22`) is about
an early-production cable, and "buy the rev2A replacement" has been on and off the table
four times. **If the unlock hangs, check the part number printed on the cable before
concluding anything else** — that turns an unexplained hang into a known, documented,
purchasable fix. It also gives the rev2A purchase a second, independent justification that
has nothing to do with the marginal contact.

Note that this is specifically about the *unlock tool*, not about running the headset: this
cable has driven the G2 at 90 Hz for hours on Windows and on Linux. **[lab]**

## Bring-up checklist for a fresh Windows machine

1. Windows 11 24H2 or newer, current GPU drivers, SteamVR installed.
2. Headset on a **rear, CPU-fed USB 3.x port**; DP straight into the GPU; 12 V brick in.
3. Run `windows-kit\power-on.ps1` → expect 5/5 devices before doing anything else.
4. Pair the controllers: Settings → Bluetooth & devices → Add device → Bluetooth, with the
   pairing button inside each battery compartment held until the LED pulses.
5. Launch the Oasis app **once**, run "unlock your headset & controllers", unplug/replug the
   headset's USB when it asks (leave DP connected), power-cycle the controllers when asked.
6. Room Setup.
7. From then on: just start SteamVR. The Oasis app stays installed and closed.

## What is physically on the Windows disk

Dropped there from Linux on 2026-08-13 (the partition mounts read-write because fast
startup is off — see the audit above), at **`C:\reverb-g2\`**:

| File | What it is |
|---|---|
| `LEEME.txt` | Spanish quick start: the two errors, the physical ladder, what was changed offline and how to revert it, unlock/pairing, the cable PN warning |
| `diagnostico.bat` | Double-click → runs `power-on.ps1` read-only, no admin |
| `tunear-admin.bat` | Double-click → self-elevates and runs `power-on.ps1 -Tune` |
| `power-on.ps1` | The script itself (ASCII-only on purpose: Windows PowerShell 5.1 reads a BOM-less UTF-8 file as ANSI, and the console codepage mangles accents even when it doesn't) |
| `31-windows-bringup-and-errors.md` | This document |

Batch files are written with CRLF — a `.bat` with LF-only endings can misparse
parenthesised `if` blocks, which is exactly what the self-elevation wrapper uses.

Older folders from previous sessions are left untouched: `C:\debug_vr\` and
`C:\reverb-baseline\` (copies of the 90 Hz capture kit and `docs/30`).

## Sources

- Oasis Driver wiki — [Home](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki),
  [Troubleshooting Guide](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Troubleshooting-Guide),
  [Known Issues](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Known-Issues),
  [Pairing Motion Controllers](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Pairing-Motion-Controllers),
  [Unlock procedure](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/wiki/Procedure-to-unlock-headset-and-controllers-for-Oasis)
- [Issue #19 — unlock hangs with the G2 v1 cable (L72080-001)](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/issues/19)
- [Issue #26 — error 422 on HP Reverb G2](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality/issues/26)
- [SteamVR: "Headset not detected (108)" discussion](https://steamcommunity.com/app/719950/discussions/0/3183345176718736883/)
- This repo: `docs/22` (link anatomy, the seat lottery), `docs/09` (what `driver_oasis.dll`
  sends to the panel), `docs/30-windows-tracking-baseline-plan.md` (why we boot Windows at
  all), `docs/pruebas.jsonl` T171/T172.
