# 138 — Oasis/Ignition with the controllers on the host Bluetooth adapter (2026-10-03)

Follow-up to docs/117, docs/121 and docs/136. docs/117 ended with "the G2's built-in Bluetooth controllers spin in an
infinite once-per-second retry loop … no Bluetooth adapter on this machine", so every Oasis session was headset-only.
This session the controllers were bonded to a TP-Link UB500 Plus on the host (docs/136) and Oasis was launched again.


> **Status at the end of 2026-10-03: it works end to end.** SteamVR + Oasis/Ignition on KDE Plasma **X11**, the HP Reverb G2 and
> both controllers on a host Bluetooth adapter (TP-Link UB500 Plus), no Monado involved. Wearer verdict after playing Propagation
> VR: *"everything works perfectly: rumble, mapping, everything"*. Open: no sound in the headset, frame rate felt below 90 at
> maximum quality settings (not measured), menu/Windows buttons not mapped as expected on their own. This is the path to use
> to play SteamVR games today; what the project built itself (Monado, docs/136) stays valuable as the Linux-native route.
> Start/stop with `scripts/jack-in-oasis-x11.sh up|down|status`; the traps and fixes are below.

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

## Addendum 2026-10-03 (night): game test, buttons, controls, safe mode

**Propagation VR (Steam 1363430) through SteamVR/Oasis:** launched from Steam with its existing launch options (their
`XR_RUNTIME_JSON` for Monado is ignored by an OpenVR title, nothing had to be changed; SteamVR is first in `openvrpaths.vrpath`
for the run). Wearer: everything worked, **including rumble and the mapping**; at maximum quality it did not feel like 90 fps
(not measured, "the least of it"); **no sound in the headset** (not investigated; Monado's launcher has an `hmd-audio.sh`
for this on the other stack). Propagation loads its own `oculus_touch.json` bindings for the `hpmotioncontroller` profile.

**Controller reconnect:** Oasis resumes a controller that powered off or whose link dropped. Log, 19:52:55: a burst of
`oasis: Fatal error: HRESULT failure [80070005/80070006] Origin: Failed to get HID report`, then at 19:53:05
`Registering new controller` for the left address and normal operation. This is better than Monado, which does not
recover a dropped controller (docs/136). A sleeping controller at launch makes Oasis loop on
`Cannot register controller with error: 0x800705b4` (ERROR_TIMEOUT) until it is touched; once awake it registers
(`finished adding tracked device`). The launcher's own "OK" verdict needs the controllers awake within ~120 s, otherwise it
reports `TIMEOUT` although SteamVR is healthy (it was in the 20:08 and 20:11 runs); touching the joys is enough, no shaking.

**Buttons.** Raw check over the BT hidraw, one control at a time with the right controller and the left one
(`scripts/bt-controllers/bt-menu-probe2.py`, `bt-left-probe.py`): the right controller sends menu (byte1 bit 0x04) and Windows
(0x02); the left sends menu, Windows, X and the trigger. Left Y, left stick click and left grip were not seen but the wearer
pressed X twice instead of Y and did not press the others, so they are **unconfirmed, not broken**. Whatever went wrong with the
menu/Windows buttons in SteamVR therefore happens after the controller, in Oasis/SteamVR:
- Oasis' `mixedreality_hpcontroller_profile.json` exposes trigger, grip, joystick (+click), emulated trackpad, A/B/X/Y,
  `application_menu`, pose and haptic; there is **no `/input/system`** in it.
- The profile/legacy bindings SteamVR loads for the HP controller come from the original Microsoft driver folder
  (`.../MixedRealityVRDriver/resources/input/`), which is still in `external_drivers`.
- `application_menu` is the application's menu button (it does nothing in SteamVR Home without an app that uses it); the system
  button (dashboard) is separate.
- **Oasis setting `driver_oasis.use_windows_key`** (`steamvr.vrsettings`; 0 none, 1 controllers only, 2 keyboard only,
  **3 both, the default**): with 3 the Windows button is also sent as the PC keyboard Windows key. Set to **1** for the
  runs from 20:05 on. Also `turn_off_controllers_on_exit` is **true**: Oasis powers the controllers off when SteamVR exits, which
  is the "they turn off" seen at the end of a session. Holding the Windows button for about a second powers a controller off in
  hardware; that is not the driver.
- The effect of `use_windows_key = 1` on what the Windows/menu buttons do inside SteamVR was not isolated before the game test.

**SteamVR safe mode, headless fix confirmed once:** after the abrupt end of a session SteamVR wrote
`driver_oasis.blocked_by_safe_mode: true` and the next launch logged `Not loading driver oasis because it was blocked by a
previous safe mode event`, with no HMD and `vrserver` exiting on its own. With Steam fully closed, setting that key to `false`
in `steamvr.vrsettings` (and `jack-in-oasis-x11.sh down` first, because `down` restores the saved copy) made Oasis load again on
the next `up`. No GUI needed; one observation, docs/121 §1a saw edits not stick in another situation.

**KDE vs GNOME on X11:** all of today's successful runs were KDE Plasma X11. A switch to GNOME-on-Xorg was attempted at the end
(the mouse did not work in that session) and abandoned; it was not needed.

## Game round under SteamVR/Oasis (2026-10-03, running log; newest last)

Tracking helper: `scripts/bt-controllers/game-round.py` (per-run summary from the SteamVR logs: apps that connected to `vrserver`,
the compositor's cumulative stats per client = presents / dropped / reprojected and fps target, Steam app run windows, crash dumps in
`/tmp/dumps`). A SteamVR session can be restarted by Steam when a game takes it down, so check `vrserver` uptime.

| Title (AppID) | Result | Notes |
|---|---|---|
| Propagation VR (1363430) | **works** | rumble, mapping, tracking; felt < 90 fps at maximum quality (unmeasured) |
| DOOM VFR (650000) | **fails at start** | two launches (20:30:46-20:30:57, 20:32:24-20:32:40); never connected to `vrserver` (no `SetApplicationPid`); a Proton `wine64-preloader` process crashed (`/tmp/dumps/crash_20261003203238_5.dmp`); no Proton log exists, set `PROTON_LOG=1` in its launch options to see why ; **10-04 follow-up:** the Monado `XR_RUNTIME_JSON` launch option was a real blocker (cleared, original kept in `~/vr/doom650000-launchoptions.original`). Next failure, from `PROTON_LOG=1`: the game gets as far as `[VR] Added HMD`, `Initializing Vulkan subsystem`, then **`FATAL ERROR: vkAcquireNextImageKHR failed with error (VK_ERROR_OUT_OF_DATE_KHR)`** (access violation in `DOOMVFRx64.exe`) on its desktop-window swapchain. The `wineopenxr` / `xrCreateInstance failed` lines are Proton's OpenXR probe, not the cause. `+r_fullscreen 0` made no difference (same crash 0.8 s after Vulkan init, then 'FORCED CRASH'). Cause of the OUT_OF_DATE not found (untested guesses: desktop state with the HMD output off, KWin/new-window). Not Proton, prefix or OpenXR. It used to run under Monado. **Open.** DOOM launch options are left at `PROTON_LOG=1 PROTON_LOG_DIR=/home/iam/vr %command% +r_fullscreen 0`; the original is in `~/vr/doom650000-launchoptions.original` (restore when done). |
| Batman: Arkham VR (502820) | **failed at start until the prefix was moved** | Proton died within 1 s: `OSError: [Errno 22] Invalid argument: '../drive_c'` while creating `compatdata/502820/pfx/dosdevices/c:` (`/mnt/videos` is NTFS via fuseblk; relative symlinks fail there). Fix, same as the older prefixes: move `compatdata/502820` to `~/proton-prefixes-external/502820` and symlink it back (21:40). Relaunch connected to `vrserver` (pid 554304). DOOM VFR already has that symlink (since Aug 26), so its failure is something else. |
| Half-Life: Alyx (546560) | **works on the 2nd launch** | first shader compile saturated the CPU for a long time. Run 1 (20:52:46-20:54:54, pid 535051): 10429 presents, 368 dropped (3.5 %), 0 reprojected; user: ran badly. Run 2 (20:56:04-~21:00:49, pid 536553): 24273 presents, 605 dropped (2.5 %), 0 reprojected; user: perfect. Open: waist/body sits inside the floor (same chaperone floor calibration as SteamVR, not Alyx-specific); headset sound mostly OK but briefly flips to the speakers for a few seconds and back (headset audio = Realtek USB Audio 0bda:4c15 sink). **Cause found (10-04 recording, `pactl subscribe` + kernel log):** the whole headset hub (usb 3-1 with the audio 3-1.2 and the HMD HID 3-1.3) drops off USB and re-enumerates; PipeWire removes the sink and recreates it ~4 s later, so output falls back to the speakers in the gap. 8 hub disconnects between 20:18 and 21:14 (20:18:57, 20:53:05, 20:58:23, 20:59:32, 21:02:28, 21:03:38, 21:04:07, 21:04:47) plus 21:13:56 at game exit; the 21:02:17 `Failed to get HID report` burst is the same event. Alyx run 3 (21:05-21:13, pid 539470: 44880 presents, 718 dropped = 1.6 %, 0 reprojected) had no hub disconnect and no speaker jump. Same family as the known visor-end USB contact fault; at 21:02:17 `driver_oasis` logged a burst of `Failed to get HID report` (HmdDriver.cpp:44, HRESULT 80070005) after Alyx had exited |

### Proton prefixes on the NTFS libraries (2026-10-03 night)

Batman (502820), Superhot VR (617830) and The Lab (450390) all died within about a second of launch with `OSError: [Errno 22] Invalid argument: '../drive_c'` while Proton created `dosdevices/c:`: `/mnt/videos` and `/mnt/win5` are NTFS (fuseblk) and cannot hold the prefix symlinks. The fix is the one in docs/70: keep `compatdata/<appid>` on ext4 under `~/proton-prefixes-external/<appid>` and symlink it back. All of them were relocated tonight, plus 1386900, 208200, 1089130, 1481400 and 518720 (each under 50 MB). Left alone on purpose: `compatdata/3824490` (Oasis/Ignition, in use). Any NEW Proton title installed on those libraries will hit it again, so after installing one, run: `mv compatdata/<id> ~/proton-prefixes-external/<id> && ln -s ~/proton-prefixes-external/<id> compatdata/<id>`. Root is at 89 % (limit rule: ~80 %), so watch this directory's growth.

### Headset USB hub drop storms (2026-10-03 night)

About 70 disconnects of the headset hub (`usb 3-1`, with audio `3-1.2` and HID `3-1.3`) between 19:30 and 22:14, in bursts (about 40 in 14 min while Batman was being played, 21:27-21:41). The kernel logs a clean disconnect with no `-71` and no over-current: the headset itself drops off and re-enumerates. Consequences seen: PipeWire removes/recreates the headset sink (speaker flips), and `driver_oasis` often keeps a stale HID handle afterwards (`Failed to get HID report` thousands of times, `Cannot locate root anchor`), so the next game reports "waiting for VR device" (Superhot VR, 22:14:25). This matches the known visor-end marginal-contact fault (docs/22, "hub resets under load"; one prior observation was 66 reconnects/hour). Rules from that doc apply: do not cycle SteamVR repeatedly (each activation is another chance to loosen the contact); PC-end USB-C unplug/replug is the best-evidenced first lever, then a visor-end reseat. A restart of the SteamVR session (`down` + `up`) is the software recovery after a drop. Script fix made along the way: `jack-in-oasis-x11.sh down` now also stops a `vrserver` whose comm was renamed to `<pid>: vrstart` (it survived `down` and blocked the next `vrserver` with `errno=98` on the SteamVR sockets).

## Open

- **Failure catalogue of this night** (hub drop storms, stale HID after a bounce, stale vrserver, verdict bugs, NTFS prefixes, stale launch options, DOOM VFR hypotheses): docs/139.
- **No sound in the headset** under Oasis.
- **Frame rate** at maximum quality (felt below 90 fps in Propagation): not measured; the compositor stats of the room-setup
  client (`543945 dropped`) are also unexplained.
- **Menu / Windows buttons** inside SteamVR: controller side verified, SteamVR side not; test with `use_windows_key = 1`
  in SteamVR Home (short tap) once the next session starts.
- Left **Y, stick click and grip** raw confirmation.
- **Haptics:** rumble works under Oasis. Capturing the report Oasis writes to the controller (btmon, needs sudo and a real
  terminal) would give the real waveform indices and resolve docs/136's open questions (index 3 = continuous buzz, 0 and 4 stall
  the stream).
- A persistent no-sudo fix for "the desktop grabs the headset": `xrandr --output DP-0 --set non-desktop 1` is untested; the
  guard works without it.
- The `setcap CAP_SYS_NICE=eip` on `vrcompositor-launcher` was run by the user; it must be redone after a SteamVR update.
- A hybrid (Oasis controllers + Monado display) stays the fallback; not needed so far.
- Verdict logic of `jack-in-oasis-x11.sh`: wait for the controllers (prompt to touch them) before the 120 s watch starts.
