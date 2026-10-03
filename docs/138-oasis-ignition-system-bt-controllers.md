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
