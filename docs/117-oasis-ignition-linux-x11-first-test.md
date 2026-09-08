# 117 — Oasis/Ignition on Linux: first live test, X11, real hardware detected, blocked at the NVIDIA direct-mode step (2026-09-07/08)

First hands-on test of Path A from `docs/108` (previously research-only: "we have not installed
or run this"). Short version: it gets much further than expected — the real driver loads and
correctly identifies the actual G2 hardware — and then hits a genuine NVIDIA driver crash at
the last step, on a GPU+headset combination the developer never claimed to support.

## Setup, as actually done on this rig

1. Logged out and picked **GNOME on Xorg** at the GDM greeter — confirmed via
   `loginctl show-session -p Type` (`x11`). Ignition's developer is explicit that Wayland isn't
   supported; this rig's whole production pipeline is Wayland, so this is a deliberate,
   temporary session switch, not a permanent change.
2. Set both Steam apps to their required beta branches from the Steam client UI (Properties →
   Betas): **Oasis Driver for Windows Mixed Reality → `preview`**, **SteamVR → `beta`** — picked
   the dated build matching the 2026-09-06 announcement. Once both finished downloading, the
   Oasis app's own folder gained real Linux-native content it didn't have before:
   `bin/linux64/driver_oasis.so`, `ignition_server.exe`'s Proton bridge config
   (`bin/linux64/ignition.json`: spawns `ignition_server.exe` + `driver_oasis_proton.dll` inside
   a bundled Proton via `launch_serverhelper.sh`), and the driver's own `70-wmr.rules`.
3. Installed that bundled udev rule alongside the existing hand-written one (kept both — the
   bundled one uses the modern `uaccess` tag mechanism and covers Bluetooth-controller vendor
   IDs the existing rule doesn't):
   ```
   sudo cp "<Oasis folder>/70-wmr.rules" /etc/udev/rules.d/70-wmr-ignition.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```
4. Replugged the headset over USB — re-enumerated cleanly (`03f0:0580`, `04b4:6504`,
   `045e:0659`).
5. Launched SteamVR (`steam steam://run/250820`). First launch: Wine prompted to install Mono
   (declined nothing — accepted, standard and safe, contained to the driver's own Wine prefix).

## Three unrelated environmental gotchas found along the way

None of these are Oasis/Ignition bugs — they were pre-existing state on this shared dev
machine that happened to block a clean first test. Documented here because at least one of
them (#1) is a standing operational risk for the native Monado driver too.

**1. SteamVR silently disables a driver that crashed `vrserver`, forever, until manually
re-enabled.** The Mono installer's blocking prompt made Oasis's own `load_drivers` step exceed
SteamVR's watchdog window: `Failed Watchdog timeout in thread Connection load_drivers in oasis
after 20.866440 seconds. Aborting.` — this took the whole `vrserver` process down. The *next*
launch then silently skipped Oasis entirely: `Not loading driver oasis because it was blocked
by a previous safe mode event`, with no prompt pointing at the cause. This isn't in
`steamvr.vrsettings`/`default.vrsettings` under any obvious "safe mode" key — the actual control
is in the SteamVR GUI itself, **Settings → Manage Add-ons**, where the crashed driver shows up
disabled and needs a manual toggle + full SteamVR relaunch. **This applies to Monado too** —
the same panel lists `steamvr-monado`, and any crash that takes `vrserver` down with it would
silently disable it the same way on the next jack-in attempt, with the same non-obvious symptom.
First thing to check if a previously-working external driver silently stops loading.

**2. A leftover `forcedDriver: "vrto3d"` setting in `steamvr.vrsettings`** — from an earlier,
unrelated experiment with a virtual 3D-monitor driver — explicitly rejected Oasis's real device:
`Can't add device oasis.8CC044Z2CM: Does not match user setting "forcedDriver" for the HMD`.
Removed the key entirely (not replaced with `"oasis"` — leaving it unset lets SteamVR
auto-select, which is the normal/correct state).

**3. Even after removing `forcedDriver`, `vrto3d` still won the "active HMD" race by being
faster to initialize** than either real driver (it's a trivial virtual device with no USB
hardware to enumerate): `Active HMD set to vrto3d.VRto3D-1234`, followed by **both** Oasis and
the native Monado driver being rejected — `Can't add device oasis.8CC044Z2CM: Can't add a
second HMD` and `Can't add device monado.HP Reverb Virtual Reality Headset G2: Can't add a
second HMD`. Fixed by disabling `vrto3d` in Manage Add-ons (not deleting it — it's someone's
prior test setup, just don't leave it enabled when testing HMD drivers).

## The real result: driver loads, hardware detected, blocked at NVIDIA's own display-lease step

With all three of the above cleared, `vrserver.txt` shows Oasis genuinely talking to the real
headset for the first time on this rig's Linux install:

```
oasis: Driver version: 1.0.3 (6c0ad872fcc0ced8de31d6e6b70b4c3ffafcbec9)
oasis: Found HMD: HP Reverb Virtual Reality Headset G2
oasis: HMD has Sensors FW: 1.9.53
oasis: Factory calibration IPD: 0.0637
oasis: Panel resolution is: 4320x2160
oasis: Found sensors device: ...vid_045e&pid_0659...
oasis: Found presence device: ...vid_03f0&pid_0580...
oasis: HMD has OEMFW: QA85QAPV1/1.2
oasis: HMD has OEMFW: QA85QBLV1/7.0
oasis: HMD has OEMFW: QA85QDPV1/50.49
```

The firmware strings match byte-for-byte what was decoded from the Windows-side USB capture the
night before (`docs/114`) — same real hardware, same calibration, correctly read through the
Wine/Proton bridge. **The G2's built-in Bluetooth controllers spin in an infinite once-per-second
retry loop** (`oasis: Registering new controller: Built-in Bluetooth Left/Right`, repeating
forever) — expected, not a new bug: there's no Bluetooth adapter on this machine at all (built-in
or USB dongle; `bluetoothctl show` returns "No default controller available"), and the G2's
own built-in-BT-on-Linux gap is already documented as unresolved upstream (`docs/108`). This
session was headset-only, no controllers, by necessity.

The panel briefly showed image — but a flat, wrong blue, not real rendered content. The actual
cause, found in `vrcompositor.txt`:

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

The compositor correctly found the connector and selected the true 90Hz mode via X11 RandR —
then failed to acquire NVIDIA's exclusive "direct mode" display lease, and crashed
(`journalctl` shows NVIDIA driver backtraces in `libnvidia-glcore.so.595.71.05` at the same
moment). This is why SteamVR's own Settings→Video panel never shows a 90Hz option — that UI
queries the live compositor for available modes, and there is no live compositor to query once
it's crashed. It's also why `xrandr` shows the panel's DisplayPort output as "disconnected"
moments later: NVIDIA's direct-mode path only makes that output appear RandR-connected while
something is actively probing it via the Vulkan direct-display extensions requested in the log
(`VK_EXT_acquire_xlib_display`, `VK_EXT_direct_mode_display`); once the compositor died, the
transient state was torn down. No lab script, no presence/standby stack, and no real physical
hotplug were involved — confirmed neither `panel.py` nor the presence/thermal tooling
(Wayland/`jack-in-wayland.sh`-only) were running under this X11 session at all.

## Why this specific failure isn't surprising, and what to do about it

Re-reading the original Steam announcement (already quoted in full in `docs/108`): the
developer's **only** personally-tested configurations are **AMD GPU + HP Reverb G2** and
**NVIDIA GPU + Samsung Odyssey+** (plus SteamOS + Acer AH101). **NVIDIA + Reverb G2 — this
rig's exact combination — was never one of the validated configs.** Hitting a crash
specifically in NVIDIA's proprietary VR-direct-mode acquisition code, on the one GPU+headset
pairing the developer never tried, is closer to "expected, unexplored territory" than "we
misconfigured something."

Checked `BnuuySolutions/Ignition`'s GitHub issues for a known report or fix: **zero issues
open or closed on the repo** — it is two days old as of this test, with no prior art to lean
on either way.

**Not attempting `xorg.conf` surgery (excluding the HMD output from the normal X11 screen so
NVIDIA's direct-mode path can claim it exclusively) tonight.** That's a real, non-trivial
change to this rig's primary X11 desktop configuration with a real chance of breaking the
session if done wrong, aimed at fixing a driver-level crash with no reference implementation
to copy and no confirmation the developer's own driver even works correctly with an NVIDIA
GPU on this specific panel. The responsible next step, if this is revisited, is filing (or
first searching for) an upstream issue on `BnuuySolutions/Ignition` describing this exact
crash signature and GPU+headset combination — genuinely useful input for a brand-new project,
and the safer way to find out whether this is fixable at all before spending a dedicated
session on config surgery with no guarantee of success.

## Bottom line for `docs/108`'s section 4/5 reasoning

This directly answers section 5's watch-item #2 ("does DRM leasing turn out to be the real
explanation, given iashur already does it successfully under Wayland for Monado"): **yes and
no.** X11 doesn't skip the DRM-leasing requirement the way one might hope — it has its own
NVIDIA-specific "direct mode" leasing path, and that path is what's currently broken here,
independent of Wayland's leasing working fine for the same physical connector. Section 4's
conclusion is unchanged and, if anything, reinforced: this lab's own Monado/Wayland pipeline
remains the only one that actually renders real frames to this headset on this hardware today.
