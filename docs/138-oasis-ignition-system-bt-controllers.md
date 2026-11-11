# 138 — Oasis/Ignition on Linux with the HP Reverb G2: what works, what failed, how to run it (2026-09 to 2026-10)

Oasis (Microsoft's Windows WMR driver, ported to SteamVR by mbucchia) runs on Linux through Ignition (BnuuySolutions' Wine/Proton
bridge for SteamVR Windows drivers). This document consolidates the whole Oasis/Ignition test track on this rig: the first X11 and
Wayland attempts, the compositor survey, and the working setup.

> **Status: it works end to end.** SteamVR + Oasis/Ignition on KDE Plasma **X11**, the Reverb G2 and both controllers on a host
> Bluetooth adapter (TP-Link UB500 Plus, docs/136), no Monado involved. Tracking of the headset and both controllers, rumble and
> per-game mappings work in Propagation VR and several other titles (docs/140). Open: no sound in the headset in the first game, frame
> rate felt below 90 fps at maximum quality (not measured), menu/Windows buttons not mapped as expected on their own.
> Start/stop with `scripts/jack-in-oasis-x11.sh up|down|status`. Failures met along the way and their prevention: docs/139.
> Section 2 is why the other desktops are not used; section 3 is the working setup.

## 1. Requirements and setup

1. Native Steam (not Flatpak). Steam apps on beta branches: **Oasis Driver for Windows Mixed Reality -> `preview`** (build 25276174,
   depot 3824492 at the time of testing), **SteamVR -> `beta`**. Once both download, the Oasis folder gains `bin/linux64/driver_oasis.so`,
   Ignition's Proton bridge config (`bin/linux64/ignition.json`, spawning `ignition_server.exe` + `driver_oasis_proton.dll` inside a
   bundled Proton via `launch_serverhelper.sh`) and a `70-wmr.rules` udev file.
2. Install the bundled udev rule next to the hand-written one (it uses the modern `uaccess` tag and covers the Bluetooth-controller IDs):
   `sudo cp "<Oasis folder>/70-wmr.rules" /etc/udev/rules.d/70-wmr-ignition.rules && sudo udevadm control --reload-rules && sudo udevadm trigger`,
   then replug the headset (`03f0:0580`, `04b4:6504`, `045e:0659` must re-enumerate).
3. **A Bluetooth adapter on the host is mandatory**: the headset's built-in radio does not work with Oasis on Linux. Without one, `oasis:
   Registering new controller: Built-in Bluetooth Left/Right` loops once a second forever. Pairing recipe: docs/136.
4. SteamVR's first launch asks Wine to install Mono; accept it. If that prompt is left open, `load_drivers` blows SteamVR's ~20 s
   watchdog (`Failed Watchdog timeout in thread Connection load_drivers in oasis`) and takes `vrserver` down; pre-seed the prefix interactively once.
5. `setcap CAP_SYS_NICE=eip ~/.steam/debian-installation/steamapps/common/SteamVR/bin/linux64/vrcompositor-launcher` (one sudo command,
   redo after every SteamVR update, because the file is replaced). Without it SteamVR shows a polkit/zenity popup on every launch (docs/137).
   Making it permanent needs a scoped sudoers entry or a post-update hook; neither is installed.

Oasis' author tested only AMD + Reverb G2 and NVIDIA + Odyssey+ (all on X11) and says he had no success with Wayland. NVIDIA + Reverb G2,
this rig's combination, was never a validated configuration.

## 2. First attempts on GNOME (2026-09-07 to 09-13): the driver works, the display lease does not

### Lessons from the first X11 and Wayland runs

1. **SteamVR silently disables a driver that crashed `vrserver`.** The next launch logs `Not loading driver oasis because it was blocked by
   a previous safe mode event`, with no prompt. This applies to Monado's SteamVR driver too. See section 5 for how to clear it.
2. **A leftover `forcedDriver: "vrto3d"` in `steamvr.vrsettings`** rejects Oasis' device (`Does not match user setting "forcedDriver"`).
   Remove the key (leaving it unset lets SteamVR auto-select).
3. **Another virtual HMD driver can win the "active HMD" race** by initialising faster than the real ones, after which both Oasis and
   Monado are rejected with `Can't add a second HMD`. Disable such drivers (vrto3d) in Manage Add-ons while testing HMD drivers.
4. **Do not test two real drivers at once.** With `activateMultipleDrivers: true`, `driver_monado.so` loaded next to Oasis and a
   `vrserver` restart segfaulted inside it (Monado's WMR driver is built for the Wayland/DRM-lease launch path). Set
   `"driver_monado": {"enable": false}`.
5. **Oasis reads the real headset through the Wine bridge**: `vrserver.txt` shows driver 1.0.3, `Found HMD: HP Reverb Virtual Reality
   Headset G2`, sensors FW 1.9.53, IPD 0.0637, panel 4320x2160, and OEM firmware strings identical to the Windows-side USB capture.
6. **NVIDIA direct-mode lease crash on X11 (first run).** The compositor found the connector and selected the real 90 Hz mode
   (`Selected mode 1`, 4320x2160@90.001), then `Failed to acquire xlib display` -> `VRInitError_Compositor_CannotDRMLeaseDisplay`, with a
   `vrcompositor` SIGSEGV inside `libnvidia-glcore.so` (595.71.05) in the first run. `vrserver` aborts 3 s later and the panel's DP output
   goes back to "disconnected" in RandR (NVIDIA's direct-mode path only makes it connected while something probes it through
   `VK_EXT_acquire_xlib_display`/`VK_EXT_direct_mode_display`). The segfault did not recur on the 09-13 retest (same wall, clean error return).
7. **Wayland (GNOME/mutter) is a coin flip.** First run: `Direct mode: enabled`, `Updated HMD Prop_DisplayFrequency_Float to 90`, then camera/Room
   View resource creation failed (`vkGetPhysicalDeviceFormatProperties2 returned zero modifiers for DRM format 0x30313050` ->
   `VRInitError_Compositor_FailedToCreateMailbox`). `"camera": {"enableCamera": false}` in `steamvr.vrsettings` got past it to Room Setup, which
   then died on a generic ~20 s `Failed Watchdog timeout in thread Connection` (not a Monado conflict: reproduced with Monado disabled).
   On the 09-13 retest the compositor never reached direct mode at all: `Tried to find direct display through Wayland: (nil)` ->
   `CannotDRMLeaseDisplay`, 3/3, even right after a Monado launch had leased and released the same connector.
8. **The lease was available when it failed:** `scripts/check-lease.sh` showed the connector `non-desktop=1` with 3 modes and the compositor
   offering `wp_drm_lease_device_v1` for `DP-1`/`HPN`; Monado's own launcher got `Lease granted` in the same session. The fault is in how
   SteamVR's closed-source `vrcompositor` binds and queries the lease global (plausibly an under-roundtripped query, the class of bug tracked
   against Monado as issue #614), not in a missing lease. Valve's own "SteamVR for Linux Support" page says it plainly: GNOME Wayland "is not
   supported as it does not support DRM leasing"; supported are X11, KDE Plasma Wayland and wlroots compositors (Sway, LabWC, Hyprland).

### "Failed to open MR USB Device: 6" is local state, not Oasis

Win32 error 6 is `ERROR_INVALID_HANDLE`: `oasis: Fatal error: Failed to open MR USB Device: 6 Origin: usbStatus == Result_Ok (HmdDriver.cpp)`, about
2.7 s after the driver found the headset. It reproduced 3/3 after a session of heavy USB churn (dongles plugged/unplugged, the headset itself
dropped several times) and was gone after a **full machine reboot** (3/3 clean loads, nothing else changed). Not confirmed at source level
(no logs from inside the Wine-hosted server), but empirically solid: if Oasis throws a `Failed to open ... Device` fatal after heavy USB
churn, reboot before suspecting a code regression.

### Four-way compositor survey (2026-09-13)

| Compositor | DRM lease offered? | Result |
|---|---|---|
| X11 (NVIDIA native direct mode) | n/a (different mechanism) | Blocked on GNOME-on-Xorg: `Failed to acquire xlib display` / `CannotDRMLeaseDisplay`. **Works on KDE Plasma X11 once the panel is kept off the desktop (section 3)** |
| GNOME/mutter (Wayland) | **Yes**: connector 130 DP-1 "HPN" offered cleanly | Valve's `vrcompositor` fails via a Wayland lease-query race (`Tried to find direct display through Wayland: (nil)`) though the lease is available |
| KDE/KWin (Wayland) | No: announces `wp_drm_lease_device_v1` with zero connectors | Known-bad on NVIDIA since 2026-08-04, unrelated to Oasis; public bug NVIDIA/open-gpu-kernel-modules#251 (open since 2022) |
| Sway/wlroots (Wayland, forced `--unsupported-gpu`) | No: same zero-connectors symptom as KWin | Same result |

GNOME/mutter is the only Wayland compositor on this rig that offers the lease for the G2 with the NVIDIA driver (595.71.05-open). The
kernel side is not the problem: the community patch "nvkms/nvidia-drm: enable Wayland DRM-lease of VR HMDs" is applied on the lab machine, which
is why `check-lease.sh` reads `non-desktop=1` under every compositor; the KWin/wlroots gap lives in their own lease-offering code.
Before concluding anything, the survey checked that this is a general Linux-VR-on-NVIDIA pattern and not specific to this rig (KWin + NVIDIA
leasing is a known open bug; wlroots historically does not prioritise NVIDIA; GNOME's NVIDIA leasing works and is the de facto VR desktop there).

A bug report with the X11 crash signature and the Wayland timeout was filed as BnuuySolutions/Ignition issue 3, plus a data point on
NVIDIA/open-gpu-kernel-modules#251 (Sway has the same zero-connector symptom as KWin).

## 3. The working setup: KDE Plasma X11 + host Bluetooth controllers (2026-10-03)

The only configuration that got a picture on this rig. What it took (`scripts/jack-in-oasis-x11.sh up|down|status`, one launch attempt per `up`):

- **Session:** the login must be **KDE Plasma X11** on `:0` (`XAUTHORITY=/tmp/xauth_*`). `gui_env.py` is Wayland-only and returns a stale session,
  so the script reads DISPLAY/XAUTHORITY from the live shell processes. A GNOME-on-Xorg attempt (mouse did not work in that session) was abandoned.
- **Free the panel before SteamVR looks for it.** The G2 output is found from the EDID (vendor `HPN`; RandR `non-desktop` reads 0 on this rig, so
  it cannot be the selector). `kscreen-doctor output.DP-0.disable`, KScreen kded module parked, 8 s wait.
- **The panel guard is the fix.** An asleep G2 is `disconnected` in RandR; when Oasis wakes it, the output reappears and the desktop (kwin_x11
  and/or NVIDIA auto-modeset on hotplug, not KScreen) re-enables it about 3 s before the compositor probes it. Without the guard:
  `Failed to acquire xlib display` -> `CannotDRMLeaseDisplay`. With it (`xrandr --output DP-0 --off` every 0.3 s while SteamVR starts; log line
  `guard: DP-0 came back on the desktop, freeing it again`): `Selected mode 1` (4320x2160@90), `Acquired xlib display!`, `Direct mode surface`,
  `Direct mode: enabled`, `Headset is using direct mode`, `Startup Complete (1.65 s)`. Later runs showed the output was not on the desktop at the
  next `up` anyway, so persistence of the guard is not demonstrated necessary (`OASIS_GUARD_PERSIST=1` keeps it until `down`).
- **Environment:** Steam started over ssh needs `PATH=$PATH:/usr/sbin:/sbin` (docs/137); SteamVR's runtime first in `openvrpaths.vrpath` (backed
  up and restored by `down`); `driver_monado.enable=false`; `setcap CAP_SYS_NICE=eip` on `vrcompositor-launcher`; Oasis on the preview build;
  controllers awake before launch (the script waits for the BlueZ hidraw nodes and speaks a prompt).
- **`down`** kills SteamVR/vrserver/vrcompositor/Ignition by PID (including a `vrserver` whose comm was renamed to `<pid>: vrstart`, which otherwise
  blocks the next start with `errno=98`), restores `openvrpaths.vrpath` and `steamvr.vrsettings` from `~/vr/oasis-x11-backup/<stamp>`, reloads the
  KScreen module, and leaves DP-0 off the desktop on purpose (`RESTORE_DESKTOP_OUTPUT=1` re-enables it). If the panel sticks on a desktop:
  `xrandr --output DP-0 --off`.
- **Verdict logic:** the launcher's verdict reads only log lines written after the launch (the log is appended across runs) and checks
  `Acquired xlib display!` + `Startup Complete`; an early version read an older run's `CannotDRMLeaseDisplay` and reported failure (docs/139 F4).

### Traps on the way to a first launch

1. **Steam started from ssh has no `/usr/sbin` in PATH**: `vrsetup.sh` dies with "getcap is required" and shows a zenity popup (docs/137).
2. **The Oasis folder had no `bin/linux64`**: Steam had flagged the app `Update Required` and the install held only the win64 files, so SteamVR
   logged `Unable to load driver oasis ... VRInitError_Init_FileNotFound`. The 291 MB update to the preview build only started after Steam was
   restarted and the app stopped being "in use"; `steam://update/<id>` did nothing for 12 minutes (docs/137 section 3).
3. **`vrserver` exits ~25 s after start** if `vrmonitor` does not connect (`libQt5Multimedia.so.5` missing because `vrmonitor` was started without
   `bin/linux64/qt/lib` on `LD_LIBRARY_PATH`).
4. **SteamVR error 307** ("key component not working") is `VRInitError_IPC_CompositorInvalidConnectResponse`: `vrmonitor` could not connect to the
   compositor while it was (re)starting. Transient.

## 4. Controllers under Oasis

- Both controllers register through the host Bluetooth stack: `oasis: Registering new controller: \\?\HID#{00001124-0000-1000-8000-00805f9b34fb}_VID&0002045e_PID&066a#...`,
  then `Driver 'oasis' finished adding tracked device`. The first attempt on a controller can time out (`0x800705b4` ERROR_TIMEOUT, sometimes then
  `0x8000ffff`) and succeeds on retry within seconds. No retry loop.
- **Full poses:** with the headset on a desk, `vrcmd --pollposes` (from `SteamVR/bin/linux64`, `LD_LIBRARY_PATH=bin/linux64:bin/linux64/qt/lib`)
  gave head 719/719 distinct poses, left 716/719, right 601/701 while the controllers were waved; constant poses when held still. Whether this is
  optical or IMU-driven is not established.
- **Reconnect:** Oasis resumes a controller that powered off or dropped its link (burst of `Fatal error: HRESULT failure [80070005/80070006] Origin:
  Failed to get HID report`, then `Registering new controller` ~10 s later). Better than Monado, which does not recover a dropped controller (docs/136).
  A controller asleep at launch makes Oasis loop on `Cannot register controller ... 0x800705b4` until it is touched. The launcher's own verdict needs
  the controllers awake within ~120 s, otherwise it reports a controller-specific cause although SteamVR is healthy.
- **LEDs are brighter under Oasis:** the Windows driver sends its own LED pulse train (the command docs/136 shows Monado can now send over BT, at a flat intensity).
- **Buttons.** Raw checks over the BT hidraw showed the right controller sends menu (byte1 bit 0x04) and Windows (0x02); the left sends menu, Windows, X and the
  trigger. Left Y, stick click and grip were not seen (unconfirmed, not broken). So whatever went wrong with menu/Windows in SteamVR happens after the controller:
  - Oasis' `mixedreality_hpcontroller_profile.json` exposes trigger, grip, joystick (+click), emulated trackpad, A/B/X/Y, `application_menu`, pose, haptic; there is no `/input/system`.
  - The profile/legacy bindings come from the original Microsoft driver folder (`.../MixedRealityVRDriver/resources/input/`, still in `external_drivers`).
  - `application_menu` is the application's menu button; the SteamVR dashboard uses the separate system button.
  - **`driver_oasis.use_windows_key`** (`steamvr.vrsettings`; 0 none, 1 controllers only, 2 keyboard only, **3 both, the default**): with 3 the Windows button
    is also sent as the PC keyboard Windows key. Its effect on the in-SteamVR buttons was not isolated. `turn_off_controllers_on_exit` is **true**: Oasis powers the
    controllers off when SteamVR exits. Holding the Windows button ~1 s powers a controller off in hardware; that is not the driver.
- **Per-game bindings:** Oasis ships `resources/input/steam.app.<id>_hpmotioncontroller.json` bindings; a game update that renames its action set silently kills input
  (docs/139 F10, `scripts/oasis-binding-fix.py`).

## 5. SteamVR safe mode: clearing it headless

After an abrupt end of a session SteamVR writes `driver_oasis.blocked_by_safe_mode: true` and the next launch logs `Not loading driver oasis because it was blocked by a
previous safe mode event`, with no HMD and `vrserver` exiting on its own.
- **GUI route (always works):** SteamVR Settings -> Manage SteamVR Add-Ons -> Unblock / Unblock All, then relaunch ("Due to a recent crash, some SteamVR Add-Ons have
  been automatically blocked").
- **Headless route (worked in the later session):** with Steam fully closed and `jack-in-oasis-x11.sh down` run first (it restores the saved `steamvr.vrsettings`, which can
  overwrite the flags), set every `blocked_by_safe_mode` to `false` in `steamvr.vrsettings`. In an earlier session the same edit did not stick (the state was re-derived at
  startup), so verify after the next `up`.
- After any Steam/vrserver crash, the flag is also written for other drivers (gamepad, prism); `up` counts only a block of driver `oasis`.
- Untested idea from the community: `enableSafeMode: false` in the `steamvr` block of `steamvr.vrsettings` to stop SteamVR blocking drivers.

## 6. Headset hub bounces

The headset's USB hub (`usb 3-1`, with audio `3-1.2` and HID `3-1.3`) drops off and re-enumerates repeatedly, with and without SteamVR. Consequences under Oasis: PipeWire
recreates the headset sink (speaker flips), and `driver_oasis` often keeps a stale HID handle (`Failed to get HID report` thousands of times, `Cannot locate root anchor`), so the
next game says "waiting for VR device". Same family as the visor-end contact fault (docs/22). Recovery, evidence and tooling: docs/139 F1-F2. A `down` + `up` is the software recovery.

## 7. Reported upstream

| where | what |
|---|---|
| BnuuySolutions/Ignition issue 3 | Oasis works end to end on KDE Plasma X11 with host-Bluetooth controllers; the panel-guard recipe; stale HID handle after a hub bounce; outdated shipped binding |
| bluez/bluez issue 689 (closed) | pairing recipe for G2 controllers on a host adapter with BlueZ 5.82 (Windows-order L2CAP, `pairable on`, `trust`) |

## Open

- Games tested under both stacks and the Oasis-vs-Monado comparison: docs/140. Failure catalogue: docs/139.
- No sound in the headset in the first Oasis game (audio was mostly in the headset later, with speaker flips on hub bounces).
- Frame rate at maximum quality (felt below 90 fps in Propagation VR): not measured; the room-setup client's compositor stats (`543945 dropped`) are unexplained.
- Menu / Windows buttons inside SteamVR: controller side verified, SteamVR side not; test `use_windows_key = 1` with a short tap in SteamVR Home.
- Left Y, stick click and grip raw confirmation.
- Haptics: capturing the report Oasis writes to the controller (btmon, needs sudo and a real terminal) would give the real waveform indices and resolve docs/136's open questions.
- A persistent no-sudo fix for "the desktop grabs the headset": `xrandr --output DP-0 --set non-desktop 1` is untested; the guard works without it.
- Hybrid (Oasis controllers + Monado display) stays a fallback; not needed so far.
- Verify the repaired I Expect You To Die binding in play (docs/139 F10).
