# 137 — Driving Steam and SteamVR from ssh without clicking popups (2026-10-03)

Goal: launch Steam / SteamVR / Oasis on the lab machine from an ssh shell with no mouse. Every claim is tagged **[verified]** (observed),
**[inferred]** (read from scripts/logs, not exercised) or **[failed]**.

## 1. What pops up and why

### 1a. "getcap is required" (zenity error)  [verified]
An ssh shell has `PATH` without `/usr/sbin`. `SteamVR/bin/vrsetup.sh` runs `command -v getcap` (`/usr/sbin/getcap`), fails, logs
`Error: getcap is required to complete the SteamVR setup.` and calls `steamvr_msg.sh --error`, which opens a zenity window. The same line
appears in `vrstartup-linux.txt` every time Steam is born from ssh.
Fix: Steam inherits PATH from whoever started it, so extend PATH at launch (`export PATH=$PATH:/usr/sbin:/sbin`) and restart Steam
(`steam -shutdown`, wait for exit, relaunch). A running Steam keeps its old PATH; `/proc/<pid>/environ` shows what it really has.

### 1b. The second popup behind it: "SteamVR requires superuser access"  [verified]
With PATH fixed, `getcap` exists but `getcap .../SteamVR/bin/linux64/vrcompositor-launcher` prints nothing, i.e. the binary has no `cap_sys_nice`.
`vrsetup.sh` then calls `steamvr_question.sh` (zenity `--question`, "Proceed?") and, on yes, `pkexec setcap CAP_SYS_NICE=eip ...`. Over ssh there is no
polkit agent: `vrstartup-linux.txt` shows `Error creating textual authentication agent ... /dev/tty` and `readback of vrcompositor-launcher shows still lacking
cap_sys_nice`, followed by the error popup again. The chain (question popup, failed pkexec, error popup) happens on EVERY SteamVR launch until the capability is set.
Real fix (needs a human with sudo once):
`sudo setcap CAP_SYS_NICE=eip ~/.steam/debian-installation/steamapps/common/SteamVR/bin/linux64/vrcompositor-launcher`
Afterwards `vrsetup.sh` logs "has cap_sys_nice privileges" and returns before any dialog. [inferred] The cap is a file xattr, so a SteamVR update that replaces
the binary drops it; re-run the command after a SteamVR update.

### 1c. Popups that are NOT cured by PATH
- Safe mode: a driver that crashes vrserver is silently disabled on later launches until unblocked (docs/138 section 5: GUI toggle in Manage Add-ons, or, with Steam
  fully closed, setting `blocked_by_safe_mode` to `false` in `steamvr.vrsettings`, which worked in one session).
- The Mono installer prompt inside Oasis' Wine prefix blows the 20 s `load_drivers` watchdog (docs/138 section 1). Pre-seed the prefix once, interactively, before any headless run.

## 2. Suppressing zenity from outside (no mouse, no GUI)

- `xdotool` is installed; `ydotool`, `wtype`, `dotool` are not. On GNOME Wayland the zenity here is GTK4/libadwaita (Wayland native), so [inferred] xdotool (XWayland only)
  cannot click it. Clicking is the wrong layer anyway: avoid creating the popup.
- `steam.sh` does `export SYSTEM_ZENITY="$(which zenity)"` and sets `STEAM_ZENITY` from it, so pre-setting `STEAM_ZENITY` does nothing. But `which zenity` follows PATH, so a shim
  directory placed FIRST in PATH takes over every Steam/SteamVR dialog. Shim: a `zenity` script that logs its argv to `/tmp/zenity-shim.log`, exits 1 for `--question`, 0 otherwise.
  **[verified at script level]** with `env -u STEAM_ZENITY -u SYSTEM_ZENITY PATH=/tmp/zshim:$PATH`, `steamvr_msg.sh --error x` exits 0 and `steamvr_question.sh q` exits 1, no window,
  argv logged. **[not verified end to end]** Steam was not restarted under the shim.
  Consequence of a shim answering "no": the pkexec step is skipped (no polkit noise) but the compositor still lacks cap_sys_nice. The shim hides errors, so read the log file after every run.
- The shim is not committed; recreate it from the description above.
- No `steamvr.vrsettings` key was found that controls these dialogs.

## 3. Applying a pending app update from the command line

An app on a beta branch can sit at `Update Required, Fully Installed, (Update delayed for N secs)` with `AutoUpdateBehavior 0` ("only update when launched"); the countdown is Steam's
background-update delay, not an error. A beta that swaps depots replaces the old files with a new depot (the Oasis `preview` branch is what adds `bin/linux64`).

| Method | Result |
|---|---|
| `steam steam://update/<id>` and `steam://install/<id>` against the running client | **[failed]** no download for 12 min |
| Steam scheduler on its own | **[verified]** `content_log.txt` later showed `scheduler update : Priority First ... update disabled for 0 seconds`, `Update Queued`, `Update Running`. The URL commands may have been queued behind the app being flagged `Component In Use` while SteamVR/Oasis ran. [inferred] |
| `steamcmd` | **[not available]** not installed (needs i386 multiarch and sudo) and needs a logged-in account. If ever used: `steamcmd +force_install_dir <dir> +login <user> +app_update <id> -beta preview validate +quit`; never paste the password into a shared log |
| Editing `AutoUpdateBehavior` to 2 with Steam closed | **[not tested]** Steam rewrites the .acf on exit, so edit only after the process is gone |

During an update `StateFlags` goes 6 -> 1030 (1024 = update started, 4 fully installed, 2 update required) and back to 4 when done; the new depot downloads to
`<library>/steamapps/downloading/<id>/`, not into `common/`, and `bin/` keeps showing only `win64` until staging completes.
Watch it headlessly: `grep <id> ~/.steam/debian-installation/logs/content_log.txt | tail`, `du -sh <library>/steamapps/downloading/<id>`; done when `StateFlags` is 4 in the
`appmanifest_<id>.acf` and `ls "<Oasis dir>/bin"` lists `linux64`.

## 4. Headless launch checklist (SteamVR + Oasis)

1. `export PATH=$PATH:/usr/sbin:/sbin`; get the GUI env via `gui_env` as `jack-in-wayland.sh` does (detached shells lack it).
2. Optional: `PATH=/tmp/zshim:$PATH` first (section 2) so no dialog can open; check `/tmp/zenity-shim.log`.
3. `cat /proc/$(pgrep -xo steam)/environ | tr "\0" "\n" | grep ^PATH`: if `/usr/sbin` is missing, `steam -shutdown`, wait until `pgrep -x steam` is empty, relaunch with the env above.
4. Check Oasis is actually updated (`bin/linux64/driver_oasis.so` exists) BEFORE launching, else vrserver logs `Unable to load driver oasis ... VRInitError_Init_FileNotFound`.
5. Back up `~/.config/openvr/openvrpaths.vrpath` and `~/.steam/debian-installation/config/steamvr.vrsettings` first (`scripts/jack-in-oasis-x11.sh` does this itself).
6. Oasis needs Monado out of the way: `driver_monado.enable=false` in `steamvr.vrsettings`.
7. After the test, restore both files with Steam closed, then do a full Steam restart. Do not leave SteamVR's runtime ahead of xrizer in `openvrpaths.vrpath` (see the trap below).
8. Kill by PID from `ps | awk`, never `pkill -f` with a pattern that appears in your own ssh command.

## 5. What needs a human

- Headless: PATH fix + Steam relaunch, update observation via logs, zenity suppression via a PATH shim (script level only), vrpath/vrsettings backup and restore.
- Still needs the GUI or sudo: `setcap` on `vrcompositor-launcher` (one sudo command), clearing the SteamVR crash safe mode when the headless edit does not stick, the Wine-prefix Mono prompt (first run),
  and forcing a delayed Steam update on demand (no confirmed CLI trigger).

## OpenVR vrpath priority trap

**Symptom.** An OpenVR game launches (Steam shows "App Running", the process exists under Proton) but nothing appears in the headset, only a flat 2D window or nothing, possibly with audio still in the headset.
Monado's own log stays clean: 0 `Delivered frame` lines and no sustained client connections, only brief loader probes. A clean Monado log is **not** proof the runtime path is right: Monado was never reached.

**Cause.** OpenVR takes the **first** entry of `"runtime"` in `~/.config/openvr/openvrpaths.vrpath`. SteamVR activity re-registers its own runtime and moves
`.../steamapps/common/SteamVR` ahead of xrizer (`~/vr/xrizer/target/release`). The game then loads SteamVR's real `vrclient` instead of xrizer's shim and gets
`VRInitError_Init_InterfaceNotFound (105)`, so it falls back to flat rendering. Known triggers: a parked SteamVR-native experiment, a Steam client "update everything" pass (SteamVR's `appmanifest_250820.acf`
`LastUpdated` and `bin/linux64/vrclient.so` were rewritten at the same moment), and any SteamVR/Oasis session (docs/138 backs the file up and restores it). It is a recurring class of bug, not a one-off.

**Check (do this before any Monado/USB/GPU theory).**
1. Read the game's own engine log first. For Unity titles under Proton: `<compatdata>/<appid>/pfx/drive_c/users/steamuser/AppData/LocalLow/<company>/<game>/output_log.txt` (or `Player.log`), and look for
   `XR: OpenVR Error! OpenVR failed initialization with error code VRInitError_Init_InterfaceNotFound: "Interface Not Found (105)"`.
2. `scripts/sanity-check.sh soft` has an "OpenVR runtime routing" check that names the problem in seconds.

**Fix.** `scripts/sanity-check.sh soft --fix-vrpath` backs up `openvrpaths.vrpath`, reorders `runtime[]` so every xrizer path sorts first and reports the new order (tested by deliberately breaking the file;
no root needed). Doing the same by hand is equivalent. Then **restart Steam fully**: an already-running game or Steam process has already read the old order and will not pick up the fix. After the fix the fatal
`VRInitError_Init_InterfaceNotFound` is replaced by a benign `VRChaperoneSetup failed initialization with error code (null)` warning (no room boundary configured) and Monado logs new client connections.
