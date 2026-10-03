# 137 — Driving Steam and SteamVR from ssh without clicking popups (2026-10-03)

Goal: launch Steam / SteamVR / Oasis on iashur from an ssh shell with no mouse. Written after the
Oasis retest session of 2026-10-03. Every claim is tagged **[verified]** (observed on this box today),
**[inferred]** (read from scripts/logs, not exercised) or **[failed]**.

## 1. What popped up and why

### 1a. "getcap is required" (zenity error)  [verified]
An ssh shell has `PATH` without `/usr/sbin`. `SteamVR/bin/vrsetup.sh` runs `command -v getcap`
(`/usr/sbin/getcap`), fails, logs `Error: getcap is required to complete the SteamVR setup.` and calls
`steamvr_msg.sh --error`, which opens a zenity window. The same line is in `vrstartup-linux.txt` on
2026-09-13 13:50 and 2026-10-03 18:55: it recurs every time Steam is born from ssh.
Fix: Steam inherits PATH from whoever started it, so extend PATH at launch
(`export PATH=$PATH:/usr/sbin:/sbin`) and restart Steam (`steam -shutdown`, wait for exit, relaunch). A
Steam that is already running keeps its old PATH; `/proc/<pid>/environ` shows what it really has.

### 1b. The second popup behind it: "SteamVR requires superuser access"  [verified]
With PATH fixed, `getcap` exists but `getcap .../SteamVR/bin/linux64/vrcompositor-launcher` prints
nothing, i.e. the binary has no `cap_sys_nice`. vrsetup.sh then calls `steamvr_question.sh` (zenity
`--question`, "Proceed?") and, on yes, `pkexec setcap CAP_SYS_NICE=eip ...`. Over ssh there is no polkit
agent: vrstartup-linux.txt at 18:57:43 shows `Error creating textual authentication agent ... /dev/tty`
and `readback of vrcompositor-launcher shows still lacking cap_sys_nice`, followed by the error popup
again. So the chain is: question popup, failed pkexec, error popup. This happens on EVERY SteamVR launch
until the capability is set.
Real fix (needs a human with sudo once, I did not run it, the dev agent never sudos):
`sudo setcap CAP_SYS_NICE=eip ~/.steam/debian-installation/steamapps/common/SteamVR/bin/linux64/vrcompositor-launcher`
Then vrsetup.sh logs "has cap_sys_nice privileges" and returns before any dialog. [inferred] The cap is
stored as a file xattr, so a SteamVR update that replaces the binary will drop it and the question will
return; re-run the command after a SteamVR update.

### 1c. Popups that are NOT cured by PATH  [from docs, not re-tested today]
- Safe-mode: a driver that crashes vrserver is silently disabled on later launches until toggled in
  Manage Add-ons in the SteamVR GUI (docs/117, docs/121 section 1a). Update 2026-10-03 night: the headless route
  worked once for `driver_oasis`: with Steam fully closed, set `blocked_by_safe_mode` to `false` in
  `steamvr.vrsettings` (the flag SteamVR wrote after an abrupt session end), then launch; Oasis loaded (docs/138).
- Mono installer prompt inside Oasis's Wine prefix blew the 20 s `load_drivers` watchdog (docs/121).
  Pre-seed the prefix once, interactively, before any headless run.

## 2. Suppressing zenity from outside (no mouse, no GUI)

- `xdotool` 3.20160805 is installed; `ydotool`, `wtype`, `dotool` are NOT. Session is GNOME Wayland and
  the zenity here is GTK4/libadwaita (its stderr in vrstartup-linux.txt names Adwaita), i.e. Wayland
  native. [inferred] xdotool only reaches XWayland clients, so it cannot click it. Not exercised (no popup
  was on screen to test against). Clicking is the wrong layer anyway: avoid creating the popup.
- `steam.sh` line 139 does `export SYSTEM_ZENITY="$(which zenity)"` and sets `STEAM_ZENITY` from it, so
  pre-setting `STEAM_ZENITY` in the environment does nothing. But `which zenity` follows PATH, so a shim
  directory placed FIRST in PATH takes over every Steam/SteamVR dialog. Shim used for the test:
  `/tmp/zshim/zenity` = logs its argv to `/tmp/zenity-shim.log`, exits 1 for `--question`, 0 otherwise.
  **[verified at script level]** with `env -u STEAM_ZENITY -u SYSTEM_ZENITY PATH=/tmp/zshim:$PATH`,
  `steamvr_msg.sh --error x` exits 0 and `steamvr_question.sh q` exits 1, no window, argv logged.
  **[not verified end to end]** I did not restart Steam under the shim (a SteamVR session was live).
  Consequence of a shim answering "no": the pkexec step is skipped (so no polkit noise) but the
  compositor still lacks cap_sys_nice, as it does today. The shim hides errors, so read the log file
  (`/tmp/zenity-shim.log`) after every run.
- The shim lives in /tmp and is not committed anywhere; recreate it from the description above.
- No `steamvr.vrsettings` key was found in the shipped `steamvr.vrsettings` that controls these
  dialogs (only unrelated `lastVersionNotice*`); I did not grep SteamVR binaries for hidden keys.

## 3. Applying a pending app update from the command line

State found (Oasis, AppID 3824490, library `/mnt/videos/SteamLibrary`):
`BetaKey preview`, `AutoUpdateBehavior 0` ("only update when launched"), `ScheduledAutoUpdate 0`,
`TargetBuildID 25276174` vs installed manifest of depot 3824491; content_log: `config changed: added
depots 3824492, removed depots 3824491` (the beta swaps the depot, so the old Windows-only files are
replaced by a new depot that carries `bin/linux64`), `Update Required, Fully Installed, (Update delayed
for N secs)`. The countdown number is Steam's background-update delay, not an error; it kept falling
(37057 s at 17:46, 32709 s at 18:58).

What was tried:
| Method | Result |
|---|---|
| `steam steam://update/3824490` and `steam://install/3824490` against the running client | **[failed]** no download for 12 min (observed by caller) |
| Steam scheduler on its own | **[verified]** at 19:07:17 content_log shows `scheduler update : Priority First ... update disabled for 0 seconds`, `Update Queued`, `Update Running`, `Downloading 3793 chunks for depot 3824492`. I do not know what tripped it: the log says only "scheduler". The URL commands may have been queued behind something (e.g. the app being flagged `Component In Use` while SteamVR/Oasis ran at 18:55-18:58, which is visible in content_log) and ran once that cleared. **[inferred]** |
| `steamcmd` | **[not available]** not installed; apt candidate `steamcmd:i386 0~20180105-5`, needs i386 multiarch and sudo to install. Would need a logged-in account (Oasis is not anonymous-downloadable, **[inferred]**) and credentials, so I did not pursue it. If ever used: `steamcmd +force_install_dir <dir> +login <user> +app_update 3824490 -beta preview validate +quit`, and never paste the password into a shared log. |
| Editing `AutoUpdateBehavior` to 2 with Steam closed | **[not tested]** the update started by itself, and the only way to test is killing the live Steam. Plan if needed: `steam -shutdown`, wait for exit, copy the .acf to `/tmp/*.bak`, set `"AutoUpdateBehavior" "2"`, relaunch with PATH extended, look for `Update Queued` in content_log. Steam rewrites the .acf on exit, so edit only after the process is gone. |

Observations about the manifest during the update (verified): `StateFlags` went 6 -> 1030 (1024 =
update started, plus 4 fully installed, plus 2 update required); the new depot downloads to
`<library>/steamapps/downloading/3824490/`, not into `common/`; `bin/` in the install dir keeps showing
only `win64` until staging completes. `StateFlags` returns to 4 when done. At 19:08 the download dir was
42 MB of 291 MB and growing slowly.

Watch it headlessly:
`grep 3824490 ~/.steam/debian-installation/logs/content_log.txt | tail` and
`du -sh /mnt/videos/SteamLibrary/steamapps/downloading/3824490`; done when
`grep StateFlags appmanifest_3824490.acf` shows 4 and `ls "<Oasis dir>/bin"` lists `linux64`.

## 4. Headless launch checklist (SteamVR + Oasis)

1. `export PATH=$PATH:/usr/sbin:/sbin`; get the Wayland env via `gui_env` as `~/vr/jack-in-wayland.sh`
   does (detached shells lack it).
2. Optional: `PATH=/tmp/zshim:$PATH` first (section 2) so no dialog can open; check `/tmp/zenity-shim.log`.
3. `cat /proc/$(pgrep -xo steam)/environ | tr "\0" "\n" | grep ^PATH` — if `/usr/sbin` is missing,
   `steam -shutdown`, wait until `pgrep -x steam` is empty, relaunch with the env above.
4. Check Oasis is actually updated (section 3: `bin/linux64/driver_oasis.so` exists) BEFORE launching,
   else vrserver logs `Unable to load driver oasis ... VRInitError_Init_FileNotFound`.
5. Back up first: `cp ~/.config/openvr/openvrpaths.vrpath` and
   `~/.steam/debian-installation/config/steamvr.vrsettings`. Today's backups: `/tmp/openvrpaths.vrpath.bak-pre-oasis`,
   `/tmp/steamvr.vrsettings.bak-pre-oasis`.
6. Oasis needs Monado out of the way: `driver_monado.enable=false` in steamvr.vrsettings (done).
7. After the test, restore. **State at 19:07 today [verified by diff]:**
   - `steamvr.vrsettings`: `driver_monado.enable` is already false in the backup too (line 50-52 in both
     files, no diff there), so nothing to restore for it; the only diffs are `settings_desktop` window
     geometry and `lastVersionNotice*`, harmless.
   - `openvrpaths.vrpath`: NOT restored. Backup has `runtime[]` = xrizer first, SteamVR second; the live
     file has them swapped (the known vrpath trap, docs/120, docs/123). Restore with Steam closed:
     `cp /tmp/openvrpaths.vrpath.bak-pre-oasis ~/.config/openvr/openvrpaths.vrpath`, then full Steam
     restart. I left it as is because SteamVR was running and may rewrite it; whoever ends the session
     must restore it. (/tmp is lost on reboot: copy the backup into the repo notes if the session runs long.)
8. Kill by PID from `ps | awk`, never `pkill -f` with a pattern that appears in your own ssh command.

## 5. Summary of what needs a human

- Headless today: PATH fix + Steam relaunch, update observation via logs, zenity suppression via a PATH
  shim (script-level only), vrpath/vrsettings backup and restore.
- Still needs the GUI or sudo: `setcap` on vrcompositor-launcher (one sudo command, ssh is fine),
  clearing the SteamVR crash safe-mode (Manage Add-ons), Wine-prefix Mono prompt (first run), and
  forcing a delayed Steam update on demand (no confirmed CLI trigger).
