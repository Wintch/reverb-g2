# 62 — Who else can use this, and what exactly transfers

Most of this repo is G2-specific, but several findings and tools apply to other orphaned
headsets and to USB devices in general. This note lists exactly what transfers and what does not.

## It started as an NVIDIA bug, and that was the tip of it

This repo exists because a headset would not light at 90 Hz. The root cause turned out to be
**NVIDIA clamping the link to 6 bpc because the sink's EDID leaves colour depth undeclared**
(`docs/13`, `docs/14`, PR
[NVIDIA/open-gpu-kernel-modules#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275)) —
and **the fix is not G2-specific**.
`nvt_edid.c` branches on the DisplayID version and the 1.x path never writes `digital.bpc`, so
the clamp is unavoidable for **any DisplayPort sink carrying a DisplayID 1.x extension that
leaves depth undefined**. Every such sink is a display that works at one refresh rate and mysteriously does not at
another, on one vendor's driver.

## What is actually general here

The G2-specific parts of this project — the 6 bpc EDID clamp, the constellation solver, the WMR
protocol — transfer to nothing. **Three things do**, and they are the ones that cost the most
time to learn:

1. **A tethered device is not one USB device, it is a tree — and a subtree can come up alone.**
   The failure that ate weeks here was never "it does not work". It was `2/5`: part of the tree
   enumerating perfectly while another part never appears, which looks like a working device with
   a mysterious software fault. **A census by branch, not a yes/no presence check**, is the single
   most transferable idea in this repo. (`scripts/usb-port-map.sh`, `docs/00`)
2. **Sockets on the same machine are not equivalent, and the OS will not tell you.** Rear ports
   split across two xHCI controllers with no visible marking, `ID_PATH` reports the two as
   identical, and the manual does not mention it. The fix — **address sockets by root-hub port
   topology** (`/sys/bus/usb/devices/usbN/N-0:1.0/usbN-portM`, which exists for every physical
   port, occupied or not) — is device-independent and works for anything that plugs into USB.
3. **The kernel's `Cannot enable. Maybe the USB cable is bad?` is a guess, and it names the wrong
   suspect.** Measured here on a perfectly good cable in the wrong socket. Anyone debugging any
   USB device has read that line and bought a cable because of it.

And one lesson that is not about USB at all: **the first signal a person sees is usually the one
that lies.** Here it is the HP logo, which lights from power + HID alone and means nothing about
video, socket or tracking. Every device has one of these. Find it and warn about it *before* the
operator looks, not after.

## Directly reusable, today, with a VID/PID list change

Every other **Windows Mixed Reality** headset. They share the exact architecture this tooling
assumes: a `Microsoft HoloLens Sensors` device (`045e:0659`) carrying cameras, IMU and the
controller tunnel, plus a **per-vendor companion device** carrying panel control, IPD and
proximity — the same two-branch split, the same failure modes, the same "logo without video".
The list below is from Monado's own driver (`src/xrt/drivers/wmr/wmr_common.h`), so it is not
guesswork:

| Vendor | VID | Companion PID | Model |
|---|---|---|---|
| HP | `03f0` | `0367` | VR1000 |
| HP | `03f0` | `0c6a` | Reverb G1 |
| HP | `03f0` | `0580` | **Reverb G2** (this project) |
| HP | `03f0` | `0680` | Reverb G2 Omnicept |
| Lenovo | `17ef` | `b801` / `b800` | Explorer (with / without controllers) |
| Dell | `413c` | `b0d5` | Visor |
| Samsung | `04e8` | `7310` / `7312` | Odyssey / Odyssey+ |
| Acer | `0502` | `b0d5` / `b0d6` | AH100 / AH101 |
| Medion (Quanta) | `0408` | `b5d5` | Erazer X1000 |
| Fujitsu | `04c5` | `15b9` | FMVHDS1 |

**What it takes**: `usb-port-map.sh`'s `G2_IDS` becomes a per-model table. Everything else — the
ladder, the branch census, the controller check, the ledger, the plain-language lines — is
already device-agnostic. The activation step is one genuinely per-model piece, and `panel.py`
already documents which command each family wants (`wmr_hmd.c` has separate Reverb and Odyssey
activation paths).

**Controller hardware is not uniform across the family, but it is already handled upstream.** Everything in `docs/03` about this
project's controllers — the X/Y/A/B layout, the thumbstick behaviour, the input fixes in
`patches/monado/0001-0008` — describes **this specific model's controller**, because that's the
unit on the bench. **Every WMR controller up to and including the original HP Reverb (G1) had a
circular touchpad below the thumbstick — Acer, Samsung Odyssey/Odyssey+, Lenovo Explorer, Dell
Visor, the first HP Reverb.** The G2 is the one model in the VID/PID table above that **removed
the touchpad** in favour of plain A/B/X/Y buttons — a real physical difference, not a driver
quirk, and it has a live consequence even on Windows: many WMR-era games map primary interaction
to the touchpad, and G2 owners are stuck emulating it by holding a face button while moving the
thumbstick.

Checked directly against Monado's source (`src/xrt/drivers/wmr/`): the
touchpad path is **not missing upstream** — `wmr_controller.c`'s `wmr_controller_create()`
already switches on controller PID, and `wmr_controller_og_create()` (in `wmr_controller_og.c`,
"og" = the touchpad-equipped reference design shared by `WMR_CONTROLLER_PID` and
`ODYSSEY_CONTROLLER_PID`) fully implements `TRACKPAD`, `TRACKPAD_CLICK` and `TRACKPAD_TOUCH` as
real inputs, separately from `wmr_controller_hp_create()`/`wmr_controller_hp.c` for
`REVERB_G2_CONTROLLER_PID`. So a touchpad-equipped WMR controller is closer to the "VID/PID-list
change" category than to "real work". The open question for a real port is whether that PID
switch already covers Acer/Lenovo/Dell/first-gen-HP (all likely `WMR_CONTROLLER_PID`, the shared
reference design) or whether any of them needs its own case; this has not been checked against
real hardware.

**Why this matters beyond us**: these are all discontinued, WMR support was removed from Windows
11 24H2, and the machines that ran them are being thrown out. A working Linux bring-up procedure
is the difference between a landfill and a headset, and most of these models have *nobody*
documenting them.

## Reusable with real work, same failure shape

Tethered headsets that also present a multi-device tree behind an inline hub or breakout box, so
a partial enumeration is possible and looks like something else:

- **Valve Index** — camera, audio and HID behind the headset's own hub.
- **HTC Vive / Vive Pro** — the link box is a hub; partial enumeration is a known support case.
- **Oculus Rift CV1 / DK2** — headset hub plus separate tracking cameras; the cameras were
  famously sensitive to *which* USB controller they were on, which is finding #2 above, from 2016.
- **Pimax, Varjo, Bigscreen Beyond** — same tether-plus-hub topology.

For these the census and the socket-addressing transfer as-is; the activation rung and the
protocol do not.

## The wider orphan list

**Windows 11 24H2 removed Windows Mixed Reality outright**, retiring headsets from HP, Samsung,
Acer, Lenovo, Dell, Asus and Medion in a single update. Two independent efforts answered that:
**Oasis**, a community SteamVR driver that bypasses the deprecated Mixed Reality Portal (the
"Oasis" referenced throughout this repo; `docs/09` has the detail), and the Linux side:
**Monado** plus **Envision** as its front end. Platform history and primary sources are in
`docs/10`.

Beyond WMR, the same "the vendor is gone, the hardware is fine" pattern:

| Hardware | State | What transfers from here |
|---|---|---|
| **All WMR headsets** (table above) | platform removed 24H2 | everything: census, sockets, activation ladder |
| **Oculus Rift CV1 / DK2** | runtime discontinued | census + socket addressing. Their **cameras were famously sensitive to which USB controller they sat on, in 2016** — finding #2 of this document, a decade early. Monado's constellation code we depend on is Rift-derived (`t_rift_blobwatch`) |
| **OSVR HDK 1 / HDK 2** (Razer + Sensics) | abandoned, open API | census + socket addressing |
| **Sony PSVR 1** on PC | never officially supported | the inline "processor unit" is the same shape as this cable's active repeater box |
| **HTC Vive / Vive Pro** | link box = a hub | partial enumeration is a known support case |
| **Pimax 4K / 5K / 8K, Varjo VR-1/VR-2/XR-1, StarVR** | discontinued or enterprise-orphaned | census + socket addressing |
| **Valve Index, Bigscreen Beyond, Somnium VR1** | current | the socket and cable diagnostics apply to any tether |

These are units sitting in drawers because *nothing tells their owner whether the thing is
broken or just plugged into the wrong hole*. That question is answerable with one command.

Where this work would be useful to others: the **[Linux VR Adventures wiki](https://wiki.vronlinux.org/docs/hardware/)**
and the **[Gentoo VR wiki](https://wiki.gentoo.org/wiki/Virtual_Reality)** already collect
per-headset Linux status, and neither has per-board USB socket data for anything.

## If you have one of these

If you have one of these devices and want its bring-up validated or the tooling adapted to it,
open an issue on this repository. Whatever gets measured ends up in this repo, working or not.

Please include the exact model, the
motherboard, and the output of `./scripts/usb-port-map.sh map`, which is most of the diagnosis.

## Not headsets, same class of bug

Anything where a single cable presents several USB devices and a subset can fail while the rest
looks healthy: **USB docking stations** (display works, ethernet missing), **audio interfaces**
(playback works, MIDI missing), **capture cards**, **microscope/industrial cameras** on
controller-sensitive bulk streams. The generic form of the tool is *"census a device tree by
branch, name the socket, and refuse to accept a partial as a pass"*, and none of that is VR.

## What would be needed to make this genuinely usable by someone else

Honest gaps, so nobody thinks this is further along than it is:

- The tool hardcodes one model's five VID/PIDs. Multi-model support is a table, not a rewrite,
  but it does not exist yet.
- The ledger is local (`~/vr/usb-port-ledger.jsonl`). The interesting version is *shared*: "on
  this board, these sockets work" is exactly the knowledge that should be pooled across users,
  and per-board port maps are the kind of thing nobody has ever collected.
- Everything is Linux-only and sysfs-based. The Windows equivalent exists in `windows-kit/` but
  was written for a different question.
- Two boards have been mapped (ASUS TUF B450M-PLUS II and Gigabyte A520M K V2, see `docs/63` and
  `docs/a520m-rear-usb3-port-pairs.png`), with only a few socket types on each.
