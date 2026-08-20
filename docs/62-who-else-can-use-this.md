# 62 — Who else can use this, and what exactly transfers

**Written 2026-08-19 (T231), on the user's observation: "esto que estamos haciendo lo tuvo que
haber hecho bien HP desde el principio, pero es un pie para dispositivos similares."** He is
right on both halves, and the second half is worth being precise about — "it might help others"
is a nice feeling, while *this list* is a thing someone can act on.

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
user looks, not after.

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
already device-agnostic. The activation step is the one genuinely per-model piece, and
`panel.py` already documents which command each family wants (`wmr_hmd.c` has separate Reverb and
Odyssey activation paths).

**Why this matters beyond us**: these are all discontinued, WMR support was removed from Windows
11 24H2, and the machines that ran them are being thrown out. A working Linux bring-up procedure
is the difference between a landfill and a headset — and unlike the G2, most of these models have
*nobody* documenting them.

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
- Only one board has been mapped (ASUS TUF B450M-PLUS II) and only three socket types on it.
