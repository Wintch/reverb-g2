# 119 — Draft bug report for BnuuySolutions/Ignition: vrcompositor segfault in libnvidia-glcore during direct-mode acquisition (NVIDIA + HP Reverb G2)

Prepared for filing at `github.com/BnuuySolutions/Ignition/issues` (repo had zero issues at
time of writing — first report of this combination). Not filed automatically; review before
submitting. Written to stand alone — a reader with no access to this repo's other docs should
be able to follow it.

---

**Title:** `vrcompositor` segfaults inside `libnvidia-glcore.so` acquiring direct-mode display (NVIDIA RTX 3060 Ti + HP Reverb G2, X11)

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

**Additional notes**

Per the original announcement, the only personally-tested configurations were AMD GPU + HP
Reverb G2, and NVIDIA GPU + Samsung Odyssey+ — this NVIDIA + Reverb G2 pairing doesn't appear
to have been part of that validation, so this may be a genuinely new combination to look at
rather than a regression. Happy to gather a full core dump (`systemd-coredump` already has one
locally, `core.vrcompositor.1000...zst`) or run additional captures/debug builds if useful —
this is a fully wired, repeatable test rig, not a one-off report.
