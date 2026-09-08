# 119 — Draft bug report for BnuuySolutions/Ignition: X11 direct-mode crash, and a different stall under Wayland (NVIDIA + HP Reverb G2)

Prepared for filing at `github.com/BnuuySolutions/Ignition/issues` (repo had zero issues at
time of writing — first report of this combination). Not filed automatically; review before
submitting. Written to stand alone — a reader with no access to this repo's other docs should
be able to follow it.

---

**Title:** `vrcompositor` segfaults acquiring direct-mode display on X11; a different ~20s connection timeout under Wayland (NVIDIA RTX 3060 Ti + HP Reverb G2)

**Environment**
- GPU: NVIDIA GeForce RTX 3060 Ti, driver 595.71.05, VBIOS 94.04.46.80.80
- OS: Debian GNU/Linux 13 (trixie), kernel 6.12.107
- Desktop: GNOME on Xorg (X11) — confirmed via `loginctl show-session -p Type` = `x11`
- Headset: HP Reverb Virtual Reality Headset G2 (`03f0:0580`), Sensors FW 1.9.53, OEMFW
  `QA85QAPV1/1.2`, `QA85QBLV1/7.0`, `QA85QDPV1/50.49`
- SteamVR 2.16.7 (`beta` branch), Oasis Driver for Windows Mixed Reality 1.0.3
  (`6c0ad872fcc0ced8de31d6e6b70b4c3ffafcbec9`), `preview` branch dated 2026-09-06
- No Bluetooth adapter present on this machine (built-in or USB) — controllers were not part
  of this test

**Summary**

The driver itself loads correctly and fully identifies the real headset (firmware versions,
factory IPD calibration, sensor/presence HID paths all read back correctly through the
Wine/Proton bridge — this part works). `vrcompositor` then correctly enumerates the display via
X11 RandR, selects the true native 90Hz mode, and segfaults while acquiring NVIDIA's exclusive
"direct mode" display lease, taking `vrserver` down with it a few seconds later.

**Steps to reproduce**

1. Install Oasis (`preview` branch) and SteamVR (`beta` branch); install the bundled
   `70-wmr.rules`; replug the headset.
2. Launch SteamVR with the G2 connected via USB, on an X11 (not Wayland) session.
3. Ensure no other external OpenVR driver is racing for the "active HMD" slot (a
   faster-initializing virtual/software HMD driver, if one is registered, will otherwise win
   that race first and get rejected only afterward — make sure Oasis is the only HMD driver
   active for a clean repro).

**Expected:** SteamVR compositor initializes, real content renders to the panel at 90Hz.

**Actual:** `vrcompositor` correctly finds and selects the 90Hz mode, then crashes.

`vrcompositor.txt`:
```
Trying to match desired rate of 90.000000Hz.
3 modes on display: 0: 2880x1440@89.999001Hz, 1: 4320x2160@90.001007Hz, 2: 4320x2160@60.000004Hz.
Selected mode 1.
Failed to acquire xlib display
CHmdWindowSDL: Failed to create direct mode surface
CHmdWindowSDL: VR requires direct mode.
Failed to initialize compositor
Failed to start compositor: VRInitError_Compositor_CannotDRMLeaseDisplay
```

`journalctl` (kernel + systemd-coredump), same moment:
```
kernel: vrcompositor[110055]: segfault at 0 ip 000055b3544c0a86 sp 00007ffe9de04100 error 4
  in vrcompositor[1e6a86,55b35440b000+31a000] likely on CPU 5 (core 5, socket 0)
systemd-coredump: Process 110055 (vrcompositor) of user 1000 terminated abnormally with signal 11/SEGV
Backtrace (frames #0-#3 inside vrcompositor itself, then into NVIDIA's driver):
  #4  libnvidia-glcore.so.595.71.05 + 0x9f58bc
  #5  libnvidia-glcore.so.595.71.05 + 0xe52a01
  #6  libnvidia-glcore.so.595.71.05 + 0x9f5a74
```
(Several repeated crash instances captured with the same #4/#6 frames and a varying #5 offset —
`0xe3539d`, `0xe4665e`, `0xf5b619` across different attempts — consistent with the same call
path each time, hitting slightly different internal driver state.)

`vrserver` SIGABRTs ~3 seconds after `vrcompositor`'s SIGSEGV, consistent with its own
lost-master-process shutdown logic once the compositor it depends on disappears.

The panel does briefly show *something* during this — a flat, incorrect solid color, not
rendered VR content — before the whole stack tears down.

**A second failure mode found the same night, on Wayland (not requested/recommended, tried out of curiosity)**

This rig's Mutter compositor already does working DRM leasing for our own native OpenVR
driver, so we tried Wayland ourselves despite the docs saying not to. Result: direct mode and
native 90Hz actually succeeded here — no crash at all at the step that fails on X11:

```
Direct mode: enabled
Headset is using direct mode
Updated HMD Prop_DisplayFrequency_Float to 90.000000
```

It failed one step later instead, trying to stand up the camera/passthrough pipeline:

```
vkGetPhysicalDeviceFormatProperties2 returned zero modifiers for DRM format 0x30313050
Supports dmabuf formats + modifiers? - No!
Error connecting to camera block queue
Tracked Camera: Failed to create static GPU resources.
D3D11 Camera Initialization failure.
Failed to init compositor distort mailbox (error:6)
Failed to start compositor: VRInitError_Compositor_FailedToCreateMailbox
```

Setting `"camera": {"enableCamera": false}` in `steamvr.vrsettings` (disabling Room
View/passthrough) avoids that failure and gets one step further still, reaching SteamVR's own
Room Setup wizard — but `vrserver` then aborts a few seconds later on a generic, unnamed
timeout, every time, reproducibly:

```
Failed Watchdog timeout in thread Connection after ~20-21 seconds. Aborting.
```

Ruled out a conflict with our own native OpenVR driver running alongside Oasis (disabling it
entirely made no difference — identical timeout). One thing running continuously through every
attempt, on both X11 and Wayland, that we couldn't rule out as related: with no Bluetooth
adapter present on this machine, `oasis: Registering new controller: Built-in Bluetooth
Left/Right` retries once a second forever and can never succeed — the ~20s window is
suspiciously consistent with a fixed watchdog racing a loop that never yields, though we have
no way to confirm this from outside the driver.

**Additional notes**

Per the original announcement, the only personally-tested configurations were AMD GPU + HP
Reverb G2, and NVIDIA GPU + Samsung Odyssey+ — this NVIDIA + Reverb G2 pairing doesn't appear
to have been part of that validation, so this may be a genuinely new combination to look at
rather than a regression. Happy to gather a full core dump (`systemd-coredump` already has one
locally, `core.vrcompositor.1000...zst`) or run additional captures/debug builds if useful —
this is a fully wired, repeatable test rig, not a one-off report.
