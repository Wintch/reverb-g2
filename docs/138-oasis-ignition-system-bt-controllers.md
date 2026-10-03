# 138 — Oasis/Ignition with the controllers on the host Bluetooth adapter (2026-10-03)

Follow-up to docs/117, docs/121 and docs/136. docs/117 ended with "the G2's built-in Bluetooth controllers spin in an
infinite once-per-second retry loop … no Bluetooth adapter on this machine", so every Oasis session was headset-only.
This session the controllers were bonded to a TP-Link UB500 Plus on the host (docs/136) and Oasis was launched again.

## Result

- Oasis (Ignition, preview branch, Steam build 25276174, depot 3824492) registers **both** controllers through the host
  Bluetooth stack: `oasis: Registering new controller: \\?\HID#{00001124-0000-1000-8000-00805f9b34fb}_VID&0002045e_PID&066a#…`
  for the right and the left address, then `Driver 'oasis' finished adding tracked device` for serials `A85K641053004DR`
  (right) and `A85K7410630182L` (left). The first attempt on the left timed out once
  (`Cannot register controller with error: 0x800705b4`, ERROR_TIMEOUT) and succeeded on the retry. No retry loop.
- **The controllers deliver full poses.** With the headset still on a desk, `vrcmd --pollposes` (from
  `SteamVR/bin/linux64`, with `LD_LIBRARY_PATH=bin/linux64:bin/linux64/qt/lib`) gave 483 (left) and 531 (right) distinct
  poses out of 718 samples while the joys were waved, and ranges of ~0.35-0.5 m in x and ~0.45 m in z. Still: constant poses
  when held still. Whether that is optical tracking or IMU-driven is **not established** (nothing drawn: see below).
- **LEDs are brighter under Oasis** (user observation): the Windows driver sends its own LED pulse train, the command that
  docs/136 shows Monado now can send over BT too, but only at a flat intensity.
- Log line `oasis: Cannot locate root anchor` repeats continuously; meaning not investigated.

## What did not change: no picture

`vrcompositor.txt`: `Tried to find direct display through Wayland: (nil)` → `Failed to create direct mode surface` →
`VRInitError_Compositor_CannotDRMLeaseDisplay`. Same wall as docs/121 §3 (GNOME Wayland is not a supported SteamVR direct-mode
configuration and the X11 attempt also failed to acquire the display on this NVIDIA+G2 pair). The controllers therefore could
not be seen drawn nor used in a game. The dependency on a separate Bluetooth adapter is solved; the display lease is not.

## Getting there (every step is a trap)

1. **Steam started from ssh has no `/usr/sbin` in PATH**: SteamVR's `vrsetup.sh` dies with "getcap is required" (`getcap` is
   in `/usr/sbin`) and shows a zenity popup. Start Steam with `PATH=$PATH:/usr/sbin:/sbin` plus the GUI env from
   `~/vr/gui_env.py`. Details and a zenity shim idea: docs/137.
2. **The Oasis folder had no `bin/linux64`**: Steam had flagged it `Update Required … (Update delayed for 32709 secs)` and
   the install held only the win64 files, so SteamVR logged `Unable to load driver oasis … VRInitError_Init_FileNotFound`.
   The 291 MB update to the preview build only started after Steam was restarted and the app stopped being "in use"; it was
   then confirmed by hand in the Steam UI. `steam://update/<id>` and `steam://install/<id>` did nothing for 12 minutes.
3. **vrserver exits ~25 s after start** if `vrmonitor` does not connect (here `libQt5Multimedia.so.5` missing because
   `vrmonitor` was started without `bin/linux64/qt/lib` on `LD_LIBRARY_PATH`); it stayed up on the second launch.
4. **A zenity "superuser access" popup** (SteamVR wants `CAP_SYS_NICE` on `vrcompositor-launcher`): the user accepted it by hand;
   afterwards `getcap` on the file still printed nothing, so it is **not** a persistent grant.

## Sudo, to do permanently (user request)

The only privileged step is a single capability on one file:

```
sudo setcap CAP_SYS_NICE=eip ~/.steam/debian-installation/steamapps/common/SteamVR/bin/linux64/vrcompositor-launcher
```

It has to be redone after every SteamVR update (the file is replaced). The rig's agents must not sudo unasked
(lab sudo entries were stripped on 2026-08-21), so the options for making it permanent are: a one-line scoped sudoers entry
for exactly that command, or a post-update hook run by the user. Neither is installed; decide with the user.

## Restored after the test

`openvrpaths.vrpath` (xrizer first again), `steamvr.vrsettings` from the pre-test copies, Steam fully shut down, no SteamVR
or Wine process left, no Monado running, no fail marker.

## Open

The display lease (compositor) under Oasis; a Monado-for-display + Oasis-for-controllers hybrid (docs/117 saw a form of it
with the controllers missing); what `Cannot locate root anchor` means for controller tracking.

## Addendum 2026-10-03 (evening): `scripts/jack-in-oasis-x11.sh`, one measured X11 attempt

Launcher: `scripts/jack-in-oasis-x11.sh up|down|status` (identical copy in `~/vr/`). It finds the X session env from the live
shell processes (the box was a **KDE Plasma X11** login on `:0`, `XAUTHORITY=/tmp/xauth_*`, not GNOME; `gui_env.py` is
Wayland-only and returned a stale Wayland session), finds the G2 output from the EDID (vendor `HPN`; RandR `non-desktop` reads
**0** on this rig, so that property cannot be the selector), waits for the host-BT controllers, backs up and edits
`openvrpaths.vrpath` (SteamVR runtime first) and `steamvr.vrsettings` (`driver_monado.enable=false`), frees the panel
(`kscreen-doctor output.DP-0.disable`, KScreen kded module parked, 8 s wait), starts Steam with `/usr/sbin` in PATH, runs
`steam://run/250820`, watches the logs once and samples `vrcmd --pollposes`. One attempt per `up`; `down` restores both files.

Result of the single attempt (19:31-19:34): Oasis loaded and set the active HMD (`Active HMD set to oasis.8CC044Z2CM`), the
compositor found the output over RandR (`Found candidate direct display as RandR output 0x1d5`, `Selected mode 1`) and then
`Failed to acquire xlib display` -> `VRInitError_Compositor_CannotDRMLeaseDisplay`, 0.3 s later. Same wall as docs/121 s4.
New evidence: Xorgs log shows DP-0 being **re-enabled by the desktop at 19:32:24**, about 3 s before the compositor probed it,

## Addendum 2026-10-03 (evening): `scripts/jack-in-oasis-x11.sh`, one measured X11 attempt

Launcher: `scripts/jack-in-oasis-x11.sh up|down|status` (identical copy in `~/vr/`). It finds the X session env from the live
shell processes (the box was a **KDE Plasma X11** login on `:0`, `XAUTHORITY=/tmp/xauth_*`, not GNOME; `gui_env.py` is
Wayland-only and returned a stale Wayland session), finds the G2 output from the EDID (vendor `HPN`; RandR `non-desktop` reads
**0** on this rig, so that property cannot be the selector), waits for the host-BT controllers, backs up and edits
`openvrpaths.vrpath` (SteamVR runtime first) and `steamvr.vrsettings` (`driver_monado.enable=false`), frees the panel
(`kscreen-doctor output.DP-0.disable`, KScreen kded module parked, 8 s wait), starts Steam with `/usr/sbin` in PATH, runs
`steam://run/250820`, watches the logs once and samples `vrcmd --pollposes`. One attempt per `up`; `down` restores both files.

Result of the single attempt (19:31-19:34): Oasis loaded and set the active HMD (`Active HMD set to oasis.8CC044Z2CM`), the
compositor found the output over RandR (`Found candidate direct display as RandR output 0x1d5`, `Selected mode 1`) and then
`Failed to acquire xlib display` -> `VRInitError_Compositor_CannotDRMLeaseDisplay`, 0.3 s later. Same wall as docs/121 s4.
New evidence: the Xorg log shows DP-0 being **re-enabled by the desktop at 19:32:24**, about 3 s before the compositor probed
it, i.e. right after Oasis woke the panel (an asleep G2 is `disconnected` in RandR; waking it makes the output reappear and the
desktop grabs it again), even with KScreen's kded module unloaded (so it is kwin_x11 and/or the NVIDIA auto-modeset on
hotplug, not KScreen). The panel guard (re-run `xrandr --output DP-0 --off` every 0.3 s while SteamVR starts) was added after
the fact and is **untested**; so is `xrandr --output DP-0 --set non-desktop 1` (the property reports `supported: 0, 1`), the
only user-level persistent-fix candidate (it would have to run at session start, e.g. `~/.config/plasma-workspace/env/`).
Persistent alternatives need root (`xorg.conf` options for the NVIDIA X driver). `down` left Steam/SteamVR/Wine stopped, both
files restored, the panel asleep (`DP-0 disconnected`), desktop on HDMI-0 only.
