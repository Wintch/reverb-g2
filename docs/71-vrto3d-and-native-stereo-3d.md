# 71 — VRto3D install + Crysis 2's native stereo 3D confirmed working on Linux

**Status: partial win, 2026-08-24. VRto3D installed and working as a SteamVR driver.
Crysis 2's own in-game Stereo 3D (Side-by-Side) confirmed rendering split on screen
(user-verified, per this project's physical-verification rule). NOT yet confirmed:
how VRto3D actually ingests a game's own native-SBS output window — that's the open
item for next time.**

## Why this exists

Follow-up to the user's question: do simple stereo-3D VR ports of known titles still
exist (anaglyph/shutter-glasses style — 2 camera angles feeding a "big screen" in a
headset, not full positional VR)? The user specifically remembered having a VorpX
license back in the DK2 era. Full research trail and the parked title wishlist
(Painkiller, Richard Burns Rally, Diablo 3, a truck sim) are in agent memory
(`idea_vorpx_stereo3d_dk2_titles`), not this repo — this doc covers only what was
actually built/tested on this rig.

## VorpX is Windows-only; the modern, Linux-capable answer is VRto3D

[VorpX](https://www.vorpx.com/) hooks the DirectX driver directly — no Wine/Proton
path exists for it, dead end for this all-Linux rig. Its modern, actively-developed,
**genuinely Linux-native** analog is
[VRto3D](https://github.com/oneup03/VRto3D) (`oneup03`, current release V5.0.0): a
SteamVR driver, same direct-mode architecture on Linux as on Windows (no capture
chain), that repacks stereo frames into SBS/TAB/interlaced/checkerboard/anaglyph for
whatever display the user points it at. Compatible mods per its own compatibility
list: HelixVision DX9, NoMoreFlat, REALVR, REFramework, UEVR, UUVR, and VorpX itself
(VorpX's *output* can apparently feed VRto3D on Windows — irrelevant here since VorpX
itself won't run on this rig at all).

**Important architecture correction, learned live**: VRto3D does not generate stereo
from a flat game — "VRto3D itself does not 'fix' games for 3D, but it allows you to
run VR modded (fixed) games on a 3D Display." It needs the game to already produce a
stereo pair on its own, via one of:
- A genuine **VR mod** (NoMoreFlat, RealVR, UEVR, REFramework) — heavy D3D11/12
  hooks, largely AAA-title-specific, unconfirmed under Proton for any of them.
- A game's own **native Side-by-Side/Top-and-Bottom** output — no mod needed at all.
  This is the row that matters for this rig: "Native SbS/TaB: Win/Linux — cross
  platform."

## Finding a real native-3D title from the owned library

Checked candidates against
[PCGamingWiki's Glossary:Native 3D](https://www.pcgamingwiki.com/wiki/Glossary:Native_3D)
(a maintained list distinguishing genuine engine-native stereo 3D from third-party
mod fixes). Two real, owned hits in the **native** (non-modded) list:
**Crysis 2** and **Sniper Elite V2**. Notably, **Portal is on neither list** —
contradicts the folklore assumption that every early-2010s Valve/Source title got
Nvidia 3D Vision support; don't assume it without checking.

Also worth recording since it surprised us: several owned titles are in
PCGamingWiki's *modded* list (need NoMoreFlat/RealVR/UEVR/REFramework, not confirmed
on Proton) — **Metro 2033 Redux, Metro: Last Light Redux, Half-Life, Cyberpunk 2077
(RealVR specifically), Quake II RTX, Fallout 4, Dark Souls Remastered** among them.
None of these were attempted this session.

## Installing VRto3D on Linux

```bash
curl -L -o vrto3d-linux64.tar.gz \
  "$(curl -s https://api.github.com/repos/oneup03/VRto3D/releases/latest \
     | grep -o 'https://[^"]*linux64\.tar\.gz')"
tar -xzf vrto3d-linux64.tar.gz && cd vrto3d-linux64
./install.sh
```

The installer auto-discovers Steam + SteamVR (`steamapps/common/SteamVR`), copies the
driver to `SteamVR/drivers/vrto3d`, and sets `forcedDriver: vrto3d` +
`requireHmd: true` in `steamvr.vrsettings` (backed up first, reversible with
`install.sh --uninstall`). **This only affects SteamVR** — the G2's actual runtime on
this rig is Monado/xrizer, not SteamVR, so forcing SteamVR's HMD driver doesn't touch
the real VR pipeline. Needs `sudo usermod -aG input $USER` + re-login for hotkeys/
gamepad control of the on-screen VRto3D OSD (`Ctrl+Home`).

## Crysis 2: same NTFS/Proton gotchas as docs/70, plus two new ones

Crysis 2 Maximum Edition (appid 108800) lives on the same shared NTFS library as
Cyberpunk. Every issue from docs/70 repeated, plus two new title-specific ones:

### 1. Same NTFS prefix-symlink failure as Cyberpunk, but silent this time

Unlike Cyberpunk's loud `OSError: [Errno 22]` crash, Crysis 2's prefix directory
looked complete (`system.reg`, `user.reg`, `drive_c/` all present) — but
`pfx/dosdevices/` was silently empty, no `c:` symlink at all. Same root cause
(ntfs-3g can't hold the reparse point), same fix: relocate `compatdata/108800` to a
local ext4 symlink target. **Lesson**: don't just check the prefix directory
exists — check `dosdevices/` actually has a `c:` entry before trusting a "successful"
prefix creation on this library.

### 2. CryEngine's own "Unsupported GPU" dialog is a documented Wine bug, not ours

First launch showed:

> Unsupported video card detected! ... "NVIDIA GeForce RTX 3060 Ti (GA104)" [vendor
> id = 0x10de, device id = 0x2486] — Video memory: 246 MB

**Root cause, confirmed via
[Wine Bugzilla #35860](https://www.winehq.org/pipermail/wine-bugs/2018-October/501110.html)**:
Wine's WMI implementation misreports the GPU's `PNPDeviceID`/video memory to any
CryEngine 3.x title (Crysis 2, Batman: Arkham Asylum, MechWarrior Online all hit
this identically) — the engine reads garbage/near-zero VRAM via WMI and throws up
this warning. **It is not specific to this GPU, this distro, or this project's
Proton setup** — still open in Wine 12+ years after the report.

The dialog is backed by CryEngine's own watchdog thread, which kills the process
("Runaway thread" x5 in `Game.log`, followed by a clean-looking PAK-closing shutdown
sequence) if the dialog isn't answered within roughly a second — **too fast for
either scripted `xdotool` clicks or an attentive human to reliably beat under
Proton Experimental**, where the MessageBox itself was slow enough to paint that the
watchdog fired first almost every time (confirmed: 3 automated attempts, all
auto-canceled with no window ever catchable; ruled out our own `system.cfg` edits as
the cause by reverting them and reproducing the same failure).

**Fix that worked: switch to GE-Proton.** Same appid, moved to its own prefix
(`~/proton-prefixes-external/108800-ge-proton11-5`, keeping `108800-experimental`
untouched — same don't-share-prefixes-across-Proton-builds discipline as docs/70) via
`CompatToolMapping` in `config.vdf`. GE-Proton still hits the *same* WMI misreport
(246 MB logged again) — GE's bundled patches don't fix the underlying WMI bug — but
its dialog rendering was slow enough on the *first* real attempt that a human could
click OK before the watchdog fired. **This looks like a timing coincidence, not a
guaranteed fix** — don't assume GE-Proton reliably beats this watchdog every time; it
happened to work once here.

Once past the dialog, the log immediately shows the corrected picture: `Video memory:
4095 MB`, `DX11 supported: yes`, `Final rating: Machine class 4` — the misreport only
affects that one early WMI probe, not the actual runtime.

## Crysis 2's native Stereo 3D — confirmed, physically, by the user

In-game **Options → Stereo 3D Options** menu (a real settings screen, not a
console-only cvar — the `r_StereoDevice`/`r_StereoMode`/`r_StereoOutput` cvars added
to `system.cfg` earlier turned out to be redundant with this UI and were reverted):

- `STEREO 3D`: Disabled → **Enabled** (row select + Right arrow to toggle, not a
  direct click on the value — a plain click on the value text did nothing)
- `STEREO MODE`: **Side-by-Side** (already the default)
- `FLIP EYES`: No

After `APPLY` and switching to fullscreen at native resolution (the menu's own hint:
"You might need to run the game in the native resolution of the screen and in
fullscreen mode to experience stereo 3D"), **the user confirmed the screen visibly
split into two halves** — genuine native dual-view stereo rendering, working on
Linux via GE-Proton. Per this project's own rule (docs root `CLAUDE.md`: "if a human
hasn't seen it, it isn't verified"), this is a real, physically-verified result, not
a log-inferred one.

## What's NOT done yet

The confirmed SBS output above is Crysis 2 drawing its own squished side-by-side
frame directly into its desktop window — **it has not been routed through VRto3D at
all**. VRto3D's own "Native SbS/TaB" compatibility row implies it CAN ingest exactly
this kind of output, but the exact mechanism (window capture? a specific launch
wrapper? something else entirely) was not identified this session — VRto3D's normal
architecture (SteamVR compositor → driver-allocated Vulkan images via dmabuf)
describes how it captures actual OpenVR-submitting apps, not an arbitrary non-VR
game's own SBS window. **Next step, not started**: read VRto3D's source/wiki
specifically for how a native-SBS non-VR title is supposed to be pointed at it,
before assuming Crysis 2's SBS output is "one step from working in the headset."

## Files / state touched

```
~/.steam/debian-installation/steamapps/common/SteamVR/drivers/vrto3d/    new
~/.steam/debian-installation/config/steamvr.vrsettings                  edited (forcedDriver: vrto3d)
~/.steam/debian-installation/config/config.vdf                          edited (CompatToolMapping: 108800 -> GE-Proton11-5-x86_64)
~/proton-prefixes-external/108800-ge-proton11-5/                        new -- GE-Proton's prefix (currently active)
~/proton-prefixes-external/108800-experimental/                         new -- Proton Experimental's prefix (parked, broken NTFS-era artifacts already cleaned)
/mnt/videos/SteamLibrary/steamapps/compatdata/108800                    symlink -> the GE-Proton prefix above
"Crysis 2 Game of the Year/system.cfg"                                  unchanged net (stereo cvars added then reverted -- redundant with in-game menu)
```

`sudo usermod -aG input iam` was also run (user-applied) for VRto3D's OSD hotkeys —
needs a re-login to take effect, not yet verified.
