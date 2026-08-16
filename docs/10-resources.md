# 10 — Resources: everything that explains how this rig works

Index of sources for understanding the G2 at a low level. What's already been read is marked; what
hasn't is left as an explicit pending item so we don't have to search for it again from scratch.

## On this disk, right now (the most valuable stuff)

The rig's NTFS partitions get mounted read-only without booting Windows:

```bash
sudo mount -t ntfs-3g -o ro,noatime /dev/nvme0n1p4 /mnt/win4
```

### Oasis Driver — `/mnt/win4/SteamLibrary/steamapps/common/Oasis Driver for Windows Mixed Reality/`

**The most important resource we have.** A standalone driver by **Matthieu Bucchianeri**
(`mbucchia`), released for free on Steam on 2025-08-29 following the removal of WMR: it talks to
the headset directly over HID/USB, without going through the Windows WMR runtime. It's *the*
driver that runs the G2 at 90 Hz.

- [Steam page](https://store.steampowered.com/app/3824490/Oasis_Driver_for_Windows_Mixed_Reality/)
- [Repo and wiki](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality)

**Only supports NVIDIA.** It's the inverse asymmetry to ours: on Windows the path that works is
NVIDIA's; on Linux the only credible 90 Hz report *was* with AMD (Monado issue #332).
**Resolved 2026-08-06: the asymmetry is gone** — NVIDIA/Linux reaches clean 90 Hz once the
EDID bpc-clamp bug is patched (`docs/13`, `docs/19`), so "only AMD works on Linux" is
historical, not current.

| file | what it is | status |
|---|---|---|
| `bin/win64/driver_oasis.dll` | SteamVR driver (imports `HID.DLL` directly) | **read** (ch. 09) |
| `bin/win64/HololensSensors.dll` | sensors + panel in userspace; contains **firmware** strings | partially read |
| `bin/win64/MRUSBHost.dll` | raw USB/HID layer (`MrUsbDevice_SendHidCommand`, `CrystalKey*`) | exports read |
| `bin/win64/MROEMFwHost.dll` | OEM firmware (`OemFwDevice_ReadDeviceInfo/WriteFirmware`) | closed without reading — see `docs/09` "Closed afterward (2026-08-05)" |
| `unlock/unlock_wmr.exe` (611 KB) | "unlock" tool | closed without reading — same section of `docs/09` |
| `bin/win64/client_utility.exe` | client utility (launched by the driver) | closed without reading — same section of `docs/09` |
| `tracing/DriverTracing.wprp` + `Capture-ETL.bat` | the driver's ETW tracing profile | **not yet looked at** |
| `bin/win64/PassthroughSource.dll` | camera passthrough | **not yet looked at** — relevant to ch. 08 |
| `bin/win64/CalibrationAPI.dll` | camera/display calibration | not yet looked at |

The `DriverTracing.wprp` is interesting: it defines the driver's ETW providers, meaning it names
its internal subsystems. It's a free index of how it's organized.

`driver_oasis.dll` uses **Microsoft Detours** (`.detourc`/`.detourd` sections): it hooks some API.
Which one wasn't investigated.

### Microsoft's driver — `/mnt/win5/.../MixedRealityVRDriver/`

The bridge from SteamVR to the OS's WMR runtime. **Less useful**: it delegates to Windows, doesn't
touch USB. Useful only for comparison.

### `HoloLensSensors_10.0.19041.2054.zip` — local only, not in git

Full driver package (3 `.inf`, 3 `.cat`, all DLLs incl. `MROEMFwHost.dll`,
`SpatialStore.dll`, `MotionControllerSystem.dll`) for the exact driver version this lab's
Windows install already runs — the one the r/HPReverb preservation thread names (`docs/31`).
Kept **outside git, local only** (this repo went public 2026-08-06; redistributing Microsoft's
compiled binaries in a public repo is a different risk than the plain-text pages already
archived in `docs/35`/`docs/36`). Verified 2026-08-16 by `md5sum`: `HololensSensors.dll`,
`MROEMFwHost.dll` and `HololensSensors.inf` in the zip are **byte-identical** to what's
already installed in this machine's `DriverStore\FileRepository\hololenssensors.inf_amd64_*`
— confirms it's genuine, adds nothing new to reverse (already fully read, see `docs/31`'s
"Live capture" section for the `HololensSensors.inf` content, `Class = Holographic`,
`DeviceGroupId = "MixedRealityHmd"`). The zip's third INF, `HmdMonitors.inf`, additionally
confirms `Monitor\HPN36C1` (this exact headset) is a first-class entry in Microsoft's own WMR
HMD monitor list, alongside Acer/Lenovo/Fujitsu/Dell/Samsung/ASUS entries — no port/identity
mechanism in it, just `HMDDevicePresent=1`. If this file is needed again: it's wherever the
user's local downloads/`SHARED/` land it — ask, don't assume a path, since it's untracked by
design.

## Windows 11 context (as told by the user)

- **Windows 11 no longer ships WMR support.** Microsoft removed it; an **intermediate driver** is
  needed — which is exactly the Oasis driver above. With that, the headset "worked really well"
  at 90 Hz.
- **The original WMR driver should still be on the Microsoft Store.** Worth downloading: it's the
  other half of the story (the one Microsoft discontinued) and it may have panel logic that Oasis
  doesn't.
- **`fpsVR`** (a Steam app, installed at `/mnt/win4/.../fpsVR/`) measures the performance of
  everything inside SteamVR: frametimes, GPU/CPU, reprojection. **It's tricky to get it working
  properly**, but once it's running it's the measurement instrument that Linux lacks. Blocked by
  the same thing as all SteamVR here (see ch. 06).

## This repo's own tools

| script | what for |
|---|---|
| `scripts/hmd-modeset.c` | arbitrary modeset on the headset via DRM lease, without Monado |
| `scripts/panel.py` | turns the panel on/off via HID, without Monado |
| `scripts/drmprops.c` | reads `non-desktop` and connector modes from the kernel |
| `scripts/check-lease.sh` | does the compositor offer the connector for leasing? |
| `scripts/xref.py` | string xrefs in PE binaries, using only binutils |
| `scripts/capture-hid.sh` + `analyze-hid.py` | HID capture and diff via usbmon |

## The product

- [HP Reverb G2 — HP's page](https://www.hp.com/gb-en/tech-takes/gaming/review/hp-reverb-g2-review.html)
  — official specs and presentation. Discontinued; useful as a reference for what the manufacturer
  states (2160x2160 per eye, 90 Hz, Valve optics, Valve audio).

## Upstream and community

- **[Project-VR](https://github.com/AshishKumar4/Project-VR)** — where the 3 patches to 595-open
  came from. Reports the G2 at `4320x2160@90` on an RTX 4080. Uses GNOME 50 / mutter **patched**,
  SteamVR, its own WMR fork inside `vrserver`, and its `g2ctl` orchestrator.
- **Monado** — `src/xrt/drivers/wmr/`. `wmr_hmd.c:767` `wmr_hmd_activate_reverb()`,
  `wmr_hmd.c:846` `wmr_hmd_screen_enable_reverb()`. The WMR driver came out of reverse
  engineering OpenHMD.
- **OpenHMD** — origin of the `{0x50,0x01}` "hack" that Monado cargo-cults for the G1.
- NVIDIA threads:
  - [Reverb G2 won't go past 60Hz](https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744) — bug **5923212**, confirmed by NVIDIA, still open as of 610.43.02 (Jul 2026).
  - [DRM lease impossible on any display server](https://forums.developer.nvidia.com/t/nvidia-proprietary-non-open-modules-completely-unable-to-acquire-a-drm-lease-on-any-display-server-all-known-nvidia-drivers-any-hardware/341244) — **no longer applies to us**: with mutter the lease works (ch. 04).
- **HID Usage Tables**, page `0x03` "VR Controls": usage `0x20` Stereo Enable, `0x21`
  **Display Enable**. It's the command used by both HP and Monado.

## Headset hardware (measured / read from firmware)

- **Display bridge: Analogix `ANX7530`** (DP -> MIPI DSI, rated for VR up to 120 Hz), plus an
  `ANX7688`. Confirmed by the firmware's version string: `STM:..;DFU:..;ANX7688:..;ANX7530:..`.
  There's also an **STM32** and a **DFU** path (`bridge_fw_check_update`,
  `bridge_fw_switch_bank`, `QCI_FEATURE_ERASE_FLASH`, `QCI_FEATURE_DFU_NEW`,
  `SMARTBRIDGE_UNINITIALISED`): the bridge firmware is field-updatable, in banks.
- **The Lattice CrossLink `LIF-MD6000-6CSFBGA81` is NOT the video bridge** — it's the camera
  aggregator. It was flagged as the prime suspect and that was a mistake: its datasheet doesn't
  mention DisplayPort, and in the Acer WMR teardown the same chip fills that role while the real
  bridge is an ANX7530.
- Panels: two, with PWM backlight control (`panel_backlight_duty`,
  `[%s] left duty %d, right duty %d, frame timing %d, panel ID %d`).
- Cameras: 4x **OV7251** 640x480 mono 8-bit (2560x480 framebuffer). The firmware logs
  `OV7251SetFrameRate: 90hz requested but not USB3.0SS` — that 90 Hz refers to the cameras.
- EDID modes (read from the kernel, confirmed via `hmd-modeset list`):

  | idx | mode | pixel clock | htotal x vtotal |
  |---|---|---|---|
  | 0 | 4320x2160@90 | 905150 kHz | 4420 x 2276 |
  | 1 | 2880x1440@90 | 428580 kHz | 2980 x 1598 |
  | 2 | 4320x2160@60 | 709150 kHz | 4420 x 2674 |

- USB: 5 devices (ch. 00). The companion is `03f0:0580` (Quanta QHMD A85V).
  **Measured today: HID screen-off can make it RE-ENUMERATE** and change hidraw node.

## Data from the user (2026-08-04), not yet verified

- **The USB3 connection had to hang off a port wired to the CPU, not the chipset.** It was hard to
  get working even when supported. This matches ch. 00 and explains why the port diagnosis was so
  laborious.
- **HAGS** (Hardware Accelerated GPU Scheduling) **enabled caused low framerates on Windows.**
  This is a technical data point, not an anecdote: HAGS changes who schedules GPU work and touches
  the presentation path. The fact that a scheduler change degrades the G2 suggests this headset is
  more sensitive to frame delivery timing than an ordinary display. Live lead.
- On Windows 11, WMR support lasted until recently and was only just cut; that's where the "hack"
  drivers on Steam come from (Oasis being exactly that). **Verified (2026-08-05)**: Microsoft
  announced the deprecation in December 2023 and removed WMR in **Windows 11 24H2**, at which
  point the G2 stopped working even via SteamVR. Anyone staying on Windows needs to remain on
  23H2 or install Oasis.
- The user offered to make captures on Windows if needed. Not needed today (ch. 07 archived), but
  if we ever need to see how the link negotiation happens, it should be set up properly for them.

## Project's stated goal

Ship a **universal driver + basic toolkit** so the G2 stays useful on Linux and people can build
on top of it. The headset is cheap today, has good optical quality, and Microsoft and HP
abandoned it: there are thousands out there working and nobody has properly repurposed them.

## What's still needed

1. ~~**Analogix ANX7530 datasheet.**~~ **Obtained (2026-08-05):** the official Product Brief
   (AA-004263-PB-7, Analogix, May 2018), hosted by the manufacturer itself at
   [analogix.com](https://www.analogix.com/en/system/files/AA-004263-PB-7-ANX7530_Product_Brief.pdf)
   — not versioned in-repo (it carries a reproduction copyright notice, same policy as
   the FCC PDFs below). It's only the marketing brief
   (2 pages, no register map), but it confirms two things from a primary source: the DisplayPort
   link cap is **HBR2.5 (6.75 Gbps/lane), not HBR3**, and there's an explicit spec line —
   **"DisplayPort Receiver Input Bandwidth supports up to 4K x 2K x 60Hz"** — stating the refresh
   ceiling, not just bandwidth. Detail on how this intersects with the `docs/16` factorial in
   `docs/19-nvidia-bug-5923212-followup.md`. The full technical datasheet (with registers/PLL) is
   still pending, if we ever need to go deeper — Analogix normally provides it under NDA, it isn't
   public.
2. ~~**Original WMR driver from the Microsoft Store**~~ **Investigated (2026-08-05): not what's
   needed.** `id=56265` and the archive.org zip turned out to be the same
   content: `HololensSensors_*.zip` (4.7–6.9 MB), the driver for
   **sensors/IMU** (`HID\VID_045E`, tracking), not the display pipeline — it doesn't mention
   ANX7530, DisplayPort, or 90Hz because that isn't this component. The archive.org listing
   separately has the `.cab` files for
   `Microsoft-Windows-Holographic-Desktop-FOD-Package` (~1.5 GB each, various Win10/11
   builds) — the actual Feature-on-Demand for the holographic shell — not extracted yet;
   it can be listed with `cabextract -l` without downloading the full package, pending if needed.
   **More importantly: this probably doesn't close anything.** Oasis itself (ch. 09, already
   disassembled) doesn't touch video timing at all — only HID/USB for tracking and
   `Display Enable`. If the driver that DOES achieve 90 Hz doesn't touch the video mode, the
   refresh negotiation happens entirely inside Windows's NVIDIA driver (a stock OS component), not
   any Microsoft/HP component — so neither the FOD nor the original portal will
   explain the mechanism. Detail in `docs/19-nvidia-bug-5923212-followup.md`. Also
   found reports of "black screen at 90Hz" with the original Microsoft Portal on AMD
   and NVIDIA — the G2's 90 Hz seems fragile even on the reference platform, not
   exclusive to this lab.
3. `unlock_wmr.exe`, `MROEMFwHost.dll`, `client_utility.exe`, `DriverTracing.wprp`.
4. A **firmware dump** of the headset, if `MROEMFwHost` allows reading it
   (`OemFwDevice_ReadDeviceInfo`).

## FCC filings: what's there and what isn't (verified 2026-08-05)

Grantee **Quanta Computer Inc**, code **HFS**. The filings are public:
[HFS-A85Q](https://fccid.io/HFS-A85Q) (G2) and [HFS-A85R](https://fccid.io/HFS-A85R)
(Omnicept). We don't store them here — download them from there and process them with
`scripts/pdf2md.py`, which converts the PDF to markdown and extracts the images with no
dependencies.

| document | A85Q (G2) | A85R (Omnicept) | status |
|---|---|---|---|
| **Internal photos** | 512 KB | 1 MB | **available** — the PCB photos |
| Sketch for Reference | 150 KB | 181 KB | available |
| External Photos | 578 KB | 682 KB | available |
| Test Setup Photos | 443 KB | 600 KB | available |
| Test Report | 2.1 MB | 3 MB (x2) | available |
| User Manual | 4.9 MB | 3.3 MB | available |
| **Block Diagram** | 140 KB | 69 KB | **CONFIDENTIAL, metadata only** |
| **Schematics** | 789 KB | 1.1 MB | **CONFIDENTIAL, metadata only** |

**The G2's schematics and block diagram exist and were filed with the FCC, but Quanta requested
long-term confidentiality — they aren't public.** That was the big prize, and it's out of reach.
The internal photos, though, are, and that's where the part numbers come from.

Useful administrative data: grant date 2020-06-05 (A85Q) and 2020-09-30 (A85R),
test lab SGS Taiwan, TCB Telefication B.V., declared model `A85Q`/`A85R`, band
2402-2480 MHz (controllers' Bluetooth), power 0.015 W.

### FCC internal photos: analyzed, and they do NOT give up part numbers (2026-08-05)

Downloaded from fccid.io and processed with `scripts/pdf2md.py` (78 images extracted from the two
filings; the PDFs are not in the repo).
**The pages are scanned at ~130 DPI**: the G2 board, at ~100 mm, spans about
680 pixels, i.e. ~7 px/mm. A chip's silkscreen marking is smaller than that. It was zoomed up to
10x and the main IC is a black square with no visible text.

What was obtained:

- **Readable silkscreen markings on the G2 board (`A85Q`)**: `MCU Download` — a
  programming header, presumably for the STM32 — and **`DES JTAG`** next to a
  connector. `DES` is most likely *deserializer*, i.e. the video chip: **there's a JTAG header
  accessible on the bridge**. Data kept on file in case we ever need to talk to it directly.
- **The `A85R` is the Omnicept**, and its photos are of the **Tobii** eye-tracking
  board (the logo reads perfectly). It's a different SKU and a different board: not useful for the
  video chain.
- G2 main board: ~100 mm wide.

**Why it's not worth pursuing further.** This line of investigation existed back when we thought
the fault was in the headset. The RX 7800 XT A/B test (Monado issue #332) shows that **the
same headset, with the same bridge and the same panels, reaches 90 Hz with AMD**. The
headset's hardware is exonerated, and the exact part number of the backlight driver no longer
changes any decision.

If it's ever needed, the way forward isn't the FCC — its resolution is what it is —
but a community teardown with macro photos, or opening up the headset. Neither is worth the risk
today.

### The Omnicept: the same headset inside, with an extra sensor

The **HP Omnicept** (SKU `VR3000-0XX`, FCC filing `HFS-A85R`) is a G2 with eye-tracking
by Tobii added. Same bridge, same panels, same WMR protocol — Monado already recognizes its
USB PID (`0x0680`) and maps it to the same `WMR_HEADSET_REVERB_G2` we use (verified in
`origin/main`, `wmr_prober.c`). **Whatever we learn here about 90 Hz should apply to it
directly**, with no extra work: it's the same display path.

The eye-tracking itself is another story — there's no Tobii driver anywhere in Monado, nor
any open prior art to build from (unlike WMR, which came out of years of reverse
engineering on OpenHMD). We're not pursuing it: we don't have the hardware.

**If you have an Omnicept, or have a spare one to donate to this investigation**, let us
know — running `docs/16-lab-vblank.md` on one would confirm whether the 90 Hz finding applies
to the headset in general or is specific to our unit.
