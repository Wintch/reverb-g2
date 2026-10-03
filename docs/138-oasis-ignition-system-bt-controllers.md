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

## What did not change: no picture (superseded: see the evening addendum, it works on X11)

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

## Addendum 2026-10-03 (evening): it works, Oasis alone on KDE X11 with the controllers on the host Bluetooth adapter

**Verdict (wearer): everything works, tracking of the headset and both controllers "perfect"**, in SteamVR with Oasis/Ignition
and no Monado involved. Only the controllers' start-up was a little rough (the right one needed two registration retries,
`0x800705b4` ERROR_TIMEOUT then `0x8000ffff`, before `finished adding tracked device`) and they settled within seconds.
One thing did not work: the wearer could not bring up the menu (see Open). The SteamVR room setup was completed without problems.

What it took (`scripts/jack-in-oasis-x11.sh up|down|status`, identical copy in `~/vr/`, one launch attempt per `up`):

- **Session:** the login was **KDE Plasma X11** on `:0` (`XAUTHORITY=/tmp/xauth_*`), not GNOME; `gui_env.py` is Wayland-only
  and returned a stale Wayland session, so the script reads DISPLAY/XAUTHORITY from the live shell processes.
- **Free the panel before SteamVR looks for it:** the G2 output is found from the EDID (vendor `HPN`; RandR `non-desktop`
  reads **0** on this rig, so it cannot be the selector). `kscreen-doctor output.DP-0.disable`, KScreen kded module parked, 8 s wait.
- **The panel guard is the fix.** An asleep G2 is `disconnected` in RandR; when Oasis wakes it the output reappears and the
  desktop (kwin_x11 and/or NVIDIA auto-modeset on hotplug, not KScreen) re-enables it about 3 s before the compositor probes
  it. Attempt 1 (no guard, 19:31): `Failed to acquire xlib display` → `VRInitError_Compositor_CannotDRMLeaseDisplay`,
  the same wall as docs/121 §4. Attempt 2/3 (guard on: `xrandr --output DP-0 --off` every 0.3 s while SteamVR starts, log
  line `guard: DP-0 came back on the desktop, freeing it again`): `Selected mode 1` (4320x2160@90), `Acquired xlib display!`,
  `Direct mode surface`, `Direct mode: enabled`, `Headset is using direct mode`, `Startup Complete (1.65 s)`.
- **Environment:** Steam started from ssh needs `PATH=$PATH:/usr/sbin:/sbin`; SteamVR's runtime first in `openvrpaths.vrpath`
  (backed up and restored by `down`), `driver_monado.enable=false`, `setcap CAP_SYS_NICE=eip` on `vrcompositor-launcher`
  (done by the user; `getcap` shows `cap_sys_nice=eip`), Oasis on the preview build (docs/137), controllers awake before launch
  (the script waits for the BlueZ hidraw nodes and speaks a prompt).
- **Script verdict bug found and fixed:** the first run reported `COMPOSITOR_FAILED` at t+28 s, but the log is appended across
  runs, so it was reading an older run's `CannotDRMLeaseDisplay`, and it looked for a success marker that does not exist
  (`Headset is using direct mode` does, `Acquired xlib display!` + `Startup Complete` are what the fixed check uses, counted
  only in lines written after the launch).
- **SteamVR error 307** shown to the wearer ("key component not working") is `VRInitError_IPC_CompositorInvalidConnectResponse`:
  `vrmonitor` could not connect to the compositor while it was (re)starting (`vrclient_vrmonitor.txt`: `Invalid response to
  connect message`, 19:38:25; also at shutdown). Transient; the compositor came up right after.
- Poses (`vrcmd --pollposes`, 8 s, joys moved): head 719/719 distinct, left 716/719, right 601/701.
- Unexplained: the room-setup client's compositor stats read `34479 presents, 543945 dropped, 0 reprojected` with the
  startup phase at 543895 dropped. Nothing visibly wrong for the wearer; not investigated.
- LED brightness under Oasis is visibly higher than ours (the Windows driver drives its own pulse train); docs/136 has the
  Monado-side LED work.

`down` kills SteamVR/vrserver/vrcompositor/Ignition by PID, restores `openvrpaths.vrpath` and `steamvr.vrsettings` from
`~/vr/oasis-x11-backup/<stamp>`, reloads the KScreen module, and leaves DP-0 off the desktop on purpose
(`RESTORE_DESKTOP_OUTPUT=1` re-enables it). If the panel ever sticks on a desktop: `xrandr --output DP-0 --off`.

## Open

- **Menu button:** the wearer could not bring up the menu. A raw probe over the BT hidraw while SteamVR ran was inconclusive
  (the left controller had no hidraw node while Oasis owned the link; the right one reported byte1=0x00 throughout, and it is
  not known whether the buttons were pressed). Whether the Windows/menu buttons reach SteamVR, and how Oasis' bindings
  map them (system button vs app menu), is untested.
- A game through SteamVR/OpenVR with these controllers (the Steam launch options of the library titles force Monado's
  `XR_RUNTIME_JSON`; that has to be removed for a SteamVR run).
- The display lease on Wayland, and GNOME-on-Xorg instead of KDE X11, were not needed in the end.
- A persistent no-sudo fix for "the desktop grabs the headset": `xrandr --output DP-0 --set non-desktop 1` (property reports
  `supported: 0, 1`) is untested; the guard works without it.
- A hybrid (Oasis controllers + Monado display) stays the fallback; not needed so far.
