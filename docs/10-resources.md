# 10 — Resources: everything that explains how this rig works

Index of sources for understanding the G2 at a low level.

## Oasis Driver for Windows Mixed Reality

**The most important external resource.** A standalone driver by **Matthieu Bucchianeri**
(`mbucchia`), released for free on Steam on 2025-08-29 following the removal of WMR: it talks to
the headset directly over HID/USB, without going through the Windows WMR runtime. It is *the*
driver that runs the G2 at 90 Hz on Windows 11. NVIDIA only. Its author is a Microsoft engineer
building it in a personal capacity; the GitHub repo is an issue tracker and wiki with no source
(he has said he is bound by NDAs), even though the driver is distributed for free.

- [Steam page](https://store.steampowered.com/app/3824490/Oasis_Driver_for_Windows_Mixed_Reality/)
- [Repo and wiki](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality)

The asymmetry used to run the other way: on Windows the path that works is NVIDIA's, and the
only credible early Linux 90 Hz report was with AMD (Monado issue #332). **The asymmetry is gone**:
NVIDIA/Linux reaches clean 90 Hz once the EDID bpc-clamp bug is patched (`docs/13`, `docs/19`).

What is in the install, and what has been read (analysis in `docs/09`):

| file | what it is | status |
|---|---|---|
| `bin/win64/driver_oasis.dll` | SteamVR driver (imports `HID.DLL` directly; uses Microsoft Detours) | **read** (ch. 09) |
| `bin/win64/HololensSensors.dll` | sensors + panel in userspace; contains **firmware** strings | partially read |
| `bin/win64/MRUSBHost.dll` | raw USB/HID layer (`MrUsbDevice_SendHidCommand`, `CrystalKey*`) | exports read |
| `bin/win64/MROEMFwHost.dll` | OEM firmware (`OemFwDevice_ReadDeviceInfo/WriteFirmware`) | **read** (firmware updater only, `docs/09`) |
| `unlock/unlock_wmr.exe`, `bin/win64/client_utility.exe` | unlock tool, client utility | **read**: `unlock_wmr.exe` handles direct-mode/display state and controller provisioning, no pairing command; `client_utility.exe` is a Steam API helper (`docs/09`) |
| `tracing/DriverTracing.wprp` + `Capture-ETL.bat` | the driver's ETW tracing profile (names its internal subsystems) | not looked at |
| `bin/win64/PassthroughSource.dll`, `CalibrationAPI.dll` | camera passthrough, calibration | not looked at (passthrough: ch. 08) |

**Microsoft's own SteamVR driver** (`MixedRealityVRDriver`) just delegates to the OS WMR runtime
and does not touch USB: useful only for comparison. The `HoloLensSensors_10.0.19041.2054` driver
package (3 `.inf`, 3 `.cat`, DLLs incl. `MROEMFwHost.dll`) is the sensors/IMU driver (`HID\VID_045E`),
not the display pipeline; it is not redistributed here, and its `HmdMonitors.inf` confirms
`Monitor\HPN36C1` (this headset) is a first-class entry in Microsoft's WMR monitor list.

**No official original Microsoft/HP driver is downloadable anymore.** Windows Mixed Reality Portal
was never a standalone package (Windows Update pushed it), and Microsoft's own Learn page for it is
marked archived and retired. HP's G2 support page may point back to Oasis (unconfirmed). The only
path found to the actual APPX packages is the Reddit-sourced offline-install recipe via
`store.rg-adguard.net`. The Microsoft Store `id=56265` / archive.org zip is the sensors driver
above, not a display driver; since Oasis (which achieves 90 Hz) does not touch video timing at all,
the refresh negotiation happens inside Windows' stock NVIDIA driver, so neither the Holographic FOD
nor the original portal would explain the mechanism. Reports of "black screen at 90 Hz" with the
original Portal on AMD and NVIDIA suggest 90 Hz is fragile even on the reference platform.

**`fpsVR`** (a Steam app) measures everything inside SteamVR (frametimes, GPU/CPU, reprojection):
the measurement instrument Linux lacks, though hard to get working and blocked by the same thing
as all SteamVR here (see ch. 06).

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
- The Analogix ANX7530 Product Brief (AA-004263-PB-7, May 2018, hosted by
  [analogix.com](https://www.analogix.com/en/system/files/AA-004263-PB-7-ANX7530_Product_Brief.pdf),
  not versioned here) confirms from a primary source that the DisplayPort link cap is **HBR2.5
  (6.75 Gbps/lane), not HBR3**, and states **"DisplayPort Receiver Input Bandwidth supports up to
  4K x 2K x 60Hz"**. The full datasheet (registers/PLL) is under NDA, not public. See
  `docs/19-nvidia-bug-5923212-followup.md`.
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
  **Measured: HID screen-off can make it RE-ENUMERATE** and change hidraw node.

## The Windows 11 deprecation of WMR

Microsoft announced the deprecation in December 2023 and removed WMR in **Windows 11 24H2**, at which
point the G2 stopped working even via SteamVR; anyone staying on Windows must remain on 23H2 or
install Oasis (the "hack" drivers on Steam).

Read directly off Microsoft's own [Deprecated features in the Windows client](https://learn.microsoft.com/en-us/windows/whats-new/deprecated-features)
page (the row is dated **December 2023**), quoted in full because a reader will want the exact
wording, not a paraphrase:

> "Windows Mixed Reality is deprecated and will be removed in Windows 11, version 24H2. This
> deprecation includes the Mixed Reality Portal app, Windows Mixed Reality for SteamVR, and Steam
> VR Beta. Existing Windows Mixed Reality devices will continue to work with Steam through
> November 2026, if users remain on their current released version of Windows 11, version 23H2.
> After November 2026, Windows Mixed Reality will no longer receive security updates, nonsecurity
> updates, bug fixes, technical support, or online technical content updates."

Two dates, not one: the platform was **pulled from 24H2** (removed outright, which is what this
project ran into), but a 23H2 install with the old Mixed Reality Portal keeps working — informally,
by staying off the update — **until November 2026**, when Microsoft stops servicing it entirely.
Secondary reporting (Neowin, Techzine) adds a second tier: **November 2027 for commercial Windows
editions**, one year longer than consumer — not itself confirmed against a Microsoft primary
source, flagged here as unverified rather than silently adopted. **No official reason was given**
on that page or anywhere else Microsoft has published — no adoption numbers, no cost rationale,
nothing beyond the bare deprecation notice. Anything about *why* (low VR adoption, Microsoft's
focus shifting to HoloLens/enterprise) is industry speculation, not a Microsoft statement, and
should be labelled as such if it goes in a report.

**It was not just the G2.** WMR launched October 2017 (Windows 10 Fall Creators Update) as a
multi-vendor platform, and the 24H2 removal orphaned all of them in the same update: HP (WMR
headset 2017, Reverb 2019, **Reverb G2** 2020), Lenovo Explorer (2017), Dell Visor (2017),
Samsung Odyssey (2017) / Odyssey+ (2018), Acer AH101 (2017) / OJO 500 (2019), Asus HC102 (2018).
(`docs/62` already carries the VID/PID table for reusing this repo's tooling against any of
them.) **No manufacturer, including HP, has ever published total units sold** for any WMR
headset — the closest public proxy is the Steam Hardware Survey, where the whole WMR family
polls in the low single digits of percent among Steam VR users, dwarfed by Quest and Index. HP
was rumoured to be exiting the VR market as early as October 2022 (UploadVR, sourced to a Reddit
claim of a leaked internal remark); HP's on-record reply at the time was noncommittal corporate
language, not a denial, and the company gave no public update either way before deprecation made
the question moot. Treat the sales-figures gap as permanent, not as something more searching will
fix — every source above independently confirms nobody outside Microsoft/HP has this number, and
neither company has released it.

**The community answer, both sides of the OS split**: **Oasis**, credited and detailed further
in `docs/09` and `docs/62` — worth adding here because it is not an anonymous project: its author,
Matthieu Bucchianeri (`mbucchia`), is **a Microsoft engineer** (per his own public statements,
formerly on the Mixed Reality/HoloLens team, still at Microsoft though not on that team now) who
built it in a personal capacity. That is also the documented reason `docs/09` already found the
GitHub repo to be source-less — an issue tracker and wiki, no code: he has said he is bound by
Microsoft NDAs and will not open-source it, even though he distributes it for free on Steam. On
Linux, the equivalent role is filled by **Monado + Envision**, which is what this entire repo is
built on.

## Project's stated goal

Ship a **universal driver + basic toolkit** so the G2 stays useful on Linux and people can build
on top of it. The headset is cheap today, has good optical quality, and Microsoft and HP
abandoned it: there are thousands out there working and nobody has properly repurposed them.

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

> **`VR3000-0XX` is the base Reverb G2's own model number** (read off the physical label, `0XX` a
> wildcard for regional variants), not the Omnicept's SKU; `docs/31` records the live readout
> `Found headset: HP Inc. VR3000-0XX (HP Reverb Virtual Reality Headset G2)`. The Omnicept is a
> separate SKU (e.g. `3A7X9AA#ABA`). The FCC split stands: `HFS-A85Q` = G2, `HFS-A85R` = Omnicept.

The **HP Omnicept** (FCC filing `HFS-A85R`) is a G2 with eye-tracking
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
