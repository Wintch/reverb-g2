# 139 — Oasis/SteamVR session failure catalogue (2026-10-03)

Every failure met while running Steam VR games through SteamVR + the Oasis/Ignition driver on the HP Reverb G2 in one long session
(docs/138 is the setup and result document; this file is the post-mortem and the prevention list). Evidence levels:
**proven** (direct log or reproduction), **likely** (fits all evidence, no discriminating test), **guess**.

## Cheat sheet: recognise it fast

| # | Symptom | Grep-able signature | Cause (level) | First action |
|---|---|---|---|---|
| F1 | Headset audio flips, HID/USB devices vanish, game stutters or stops seeing the HMD | `journalctl -k`: `usb 3-1: USB disconnect` immediately followed by `usb 3-1: new high-speed USB device`, no `-71`, no over-current | Headset hub bounces itself; visor-end marginal contact (likely, docs/22) | Stop cycling SteamVR; PC-end USB-C unplug/replug; verify 5/5 |
| F2 | "waiting for VR device", HMD dead for the rest of the session | `oasis: Fatal error: HRESULT failure [80070005] ... Failed to get HID report (HmdDriver.cpp)` thousands per minute, `Cannot locate root anchor` | `driver_oasis` keeps a stale HID handle after a hub bounce (proven for one case; likely for the others) | `jack-in-oasis-x11.sh status` -> "HMD driver broken (stale HID)"; one `down` + `up` (or `watchdog --auto`) |
| F3 | `up` TIMEOUT with `active-hmd=0`, new vrserver exits | `Unable to bind server socket errno=98`; `ss -xlpn \| grep @/steamvr` shows a vrserver whose comm is `<pid>: vrstart` | Old vrserver survived `down` (proven) | `down` now asserts no `@/steamvr/*` socket remains |
| F4 | `up` prints TIMEOUT although SteamVR is fine, or `active-hmd` falls from 1 to 0 | log counts jump to 0 mid-run | Controllers asleep (proven); logs rotated by the HID spam (proven) | The verdict now names the cause (see F4) |
| F5 | Proton game dies in ~1 s | `OSError: [Errno 22] Invalid argument: '../drive_c'` in the Proton log | New prefix on an NTFS library (proven) | Keep `compatdata/<appid>` on ext4 and symlink it (docs/70) |
| F6 | OpenXR game says runtime unavailable under SteamVR | Player.log `XR_ERROR_RUNTIME_UNAVAILABLE`; Steam console `Failed to connect to monado service process`; `LaunchOptions` has `XR_RUNTIME_JSON=...openxr_monado-dev.json` | Many titles pin Monado's runtime json in their launch options (proven) | `up` swaps that json for the run, `down` restores it |
| F7 | DOOM VFR dies 0.5 s after Vulkan init | `FATAL ERROR: vkAcquireNextImageKHR failed with error (VK_ERROR_OUT_OF_DATE_KHR)` then `FORCED CRASH` | Open, ranked hypotheses below | Experiments listed, none run |
| F8 | SteamVR popups, no HMD, no controllers | see the preflight table | setcap lost, safe-mode flag, runtime order, ... (proven individually) | `jack-in-oasis-x11.sh status` shows a preflight table; `up` aborts on blocking ones |
| F9 | Controllers "start badly, settle after seconds", sometimes need waking | `Cannot register controller with error: 0x800705b4`; BT `hid-generic 0005:045E:066A` attaches | Controllers on the host BT adapter, unrelated to hub bounces (likely) | Touch/shake them; no restart |
| F10 | Game runs in VR but ignores every button | `Successfully loaded action manifest into SteamVR` and no errors | Oasis' shipped binding targets a renamed action set (proven) | `scripts/oasis-binding-fix.py` |

**Log retention warning.** With F2 active, `vrserver.txt` receives about 2300 lines per second; Steam keeps two ~10 MB files, so the whole evidence of a run is rotated
away within roughly 40 s. Anything that needs those logs must run immediately; `status` prints the oldest retained line.

## Recovery procedure after a drop storm

1. **Stop cycling SteamVR.** Every activation cycle is another chance to loosen the contact (docs/22 stop rule: at most 2 recovery cycles per hour).
2. **PC-end USB-C unplug/replug** (the best-evidenced lever, docs/22; visor-end reseat only if that fails).
3. **Verify 5/5 enumeration** with `lsusb`: `3-1 04b4:6506`, `3-1.2 0bda:4c15`, `3-1.3 03f0:0580`, `4-1 04b4:6504`, `4-1.1 045e:0659`.
   `jack-in-oasis-x11.sh status` shows `headset_usb: 5/5` (and `up` refuses to start below 5/5).
4. **One `down` + `up` only** (`up` makes a single launch attempt by design).
5. **Check `status`** for `HMD driver broken (stale HID) since HH:MM:SS`; if present, repeat from 2 once, then stop and reseat the visor end.

## F1 — Headset USB hub drop storms

- **Symptom.** About 70 hub disconnects in under 3 hours of SteamVR/Oasis use, speaker sink flips in PipeWire, Oasis loses the HMD.
- **Signature.** `usb 3-1: USB disconnect, device number N` (plus `3-1.2`, `3-1.3`), then within the same second `usb 3-1: new high-speed USB device number N+3` (the hub
  re-enumerates itself in under 1 s, a "bounce"). No `error -71` on the hub, no over-current, no xhci error. Two children failed to enumerate once each right after a bounce
  (`device descriptor read/64, error -110`; `device not accepting address, error -71`).
- **Data** (`scripts/usb-drop-timeline.py --since "<time>" --manual "<time of a deliberate unplug>"`; a deliberate PC-end unplug is classed MANUAL, not a storm event):
  ```
  disconnects: 72  | bounces (storm events): 71  | manual: 1  | unplug-without-reenum: 0
  first/last bounce: 20:18:57 / 22:27:39 (2.15 h span, 33.1 per hour inside the span)
  per hour: 20h=4  21h=55  22h=12
  bursts (gap<=120 s): 14, of which >=5 drops: x31, x7, x5, x6
  gap between consecutive bounces: min 2s, median 33s, max 2048s
  ```
  The storm kept getting denser later in the run (about one bounce per minute for a while), so restarting fixes a broken session but each cycle counts against the contact.
- **Same rate without SteamVR/Oasis?** Yes. In four other boots with the hub enumerated, Monado-only sessions logged 60 bounces in one afternoon (47 in the peak hour), 18, 1 and 12; the
  Oasis night peaked at 55 in an hour. So SteamVR/Oasis is **not required** for the storms (proven).
- **Software trigger test.** Bounces versus Steam app start/exit and vrcompositor client connects, exact binomial tail against the time-share covered by +-N s windows: 5 of 71 bounces within
  +-10 s of an app start/exit (chance 10.7 %, P=0.888); 10 of 71 within +-20 s (chance 19.9 %, P=0.920); 2 of 20 within +-10 s of a compositor client connect (P=0.850). The individually striking
  coincidences are not above chance as a set; the one marginal figure (burst starts, +-20 s, P=0.043) is one of eight tests and is **not** claimed as a finding. `vrserver.txt` around the transitions
  no longer exists (log retention). Whether SteamVR/Oasis does something at transitions is **unknown**.
- **Power management ruled out as the trigger (likely).** `71-usb-no-autosuspend.rules` forces `power/control=on` for `04b4`, `03f0`, `045e`, `0bda`; xHCI runtime PM is `on`/`active`; PCIe ASPM policy is `performance`.
- **Root cause.** Marginal visor-end/cable contact (docs/22 "hub resets under load"): **likely**, not re-proven. A PC-end replug brought all 5 devices back, and a bounce still followed minutes later.
- **Prevention.** Physical: PC-end replug, visor-end reseat, rev2A cable (docs/22). Software cannot stop it; F2 mitigates the damage.

## F2 — `driver_oasis` stale HID handle after a bounce

- **Signature.** `oasis: Fatal error: HRESULT failure [80070005] Origin: Failed to get HID report  Source: ...HmdDriver.cpp:4430` (about 2300 lines/s), `oasis: Cannot locate root anchor`; `active-hmd`
  falls to 0; the next game: "waiting for VR device" (`VR_Init failed with Hmd Not Found (108)`).
- **Cause.** After the hub re-enumerates, the driver keeps the old HID handle and never reopens it; the session stays dead until SteamVR is restarted (proven for one bounce, seen at two others).
- **Self-recovery?** Rare for the HMD handle: every bounce that coincided with a lost HMD needed a restart; two bounces during a game went unnoticed by the player (likely recovered or never lost). A controller HID drop recovered on its own after ~10 s (docs/138).
- **Tooling:** `jack-in-oasis-x11.sh status` prints, from timestamped log lines and the kernel log, `HMD driver broken (stale HID) since HH:MM:SS: headset hub re-enumerated Nx since this SteamVR run started ...`.
  `watchdog` reports (exit 10 stale, 11 headset absent, 12 unexplained); `watchdog --auto` does ONE `down`+`up` only with 5/5 USB present and fewer than 2 recoveries in the last hour
  (`~/vr/oasis-x11-recoveries`), else it stops and says to reseat; `--dry-run` shows the plan. Never started automatically. `HEADSET_ABSENT` and `UNEXPLAINED` are deliberately not auto-recovered.
- **Stale HID is not always fatal.** After one bounce `status` reported the driver as broken (64k errors) while the player kept playing The Lab for five more minutes with normal tracking and 90 fps (1.8 % dropped, 0 reprojected).
  Earlier bounces did leave the HMD unusable. The HID-error signature alone only says the handle is stale: before `watchdog --auto` restarts a session, require a second signal (the compositor stopped presenting, tracked-devices dropped,
  or the player reports it). Treat the detector's recommendation as advice until it is refined.

## F3 — stale `vrserver` survived `down`

- **Signature.** comm renamed to `<pid>: vrstart`, holding `@/steamvr/SteamVR_Namespace`, `VR_ServerPipe_<pid>`; the new vrserver logs `Unable to bind server socket errno=98`.
- **Fix.** `vr_pids` matches the comm, the renamed `<pid>: vrstart` comm, or an **argv[0]** under `SteamVR/bin` / the Oasis folder, using `/proc` builtins only. An earlier version matched any process whose command line merely contained
  `SteamVR/bin/linux64/` or `ignition`, which would kill a `tail`, `less`, `python` or `ssh` mentioning the path. After the kills `down` waits up to 5 s for no `@/steamvr/*` listener (`ss -xlpn`); if one remains it stops the owner by PID and
  returns 5 if still held. `up` preflight refuses to start while such sockets exist without a VR process; `status` prints `steamvr abstract sockets: ...` and `STALE` in that case.

## F4 — misleading `up` verdicts; panel guard

- **Bugs (proven).** (a) the counts were `grep -c` over the whole log: when the HID spam rotated the log, `active-hmd` read 0 mid-run and a stale vrserver (F3) also read 0, both printed `TIMEOUT`; (b) controllers asleep for 120 s printed `TIMEOUT` with a healthy SteamVR.
- **Current logic.** Counts come from log lines timestamped after the launch (`oasis_scan`, both rotation files), flags are sticky, and a hopeless condition ends the watch early. Result plus a plain-English `cause:` line: `OK`, `STALE_SOCKET`, `SAFE_MODE`,
  `STALE_HID`, `HMD_MISSING` (hub absent / never selected), `COMPOSITOR_FAILED`, `COMPOSITOR_PENDING`, `CONTROLLERS_MISSING` (exit 4: SteamVR healthy, touch the joys, no restart), `TIMEOUT` (nothing matched). `up` reports `SAFE_MODE` only for a block of driver `oasis`
  (an unrelated blocked driver such as `prism` used to trigger it).
- **Panel guard.** In 14 runs it fired once (the panel's first wake); at every following `up` the output was not on the desktop, including after hour-long games with no guard alive. Persistence is therefore **not demonstrated necessary**, and a 0.3 s `xrandr` poll for hours risks
  interfering with the lease (guess). The guard PID is in the state file, it ends by itself when the state file is gone, and `OASIS_GUARD_PERSIST=1` keeps it until `down` (1 s poll).

## F5 — Proton prefixes on NTFS libraries

Proven (docs/70): `OSError: [Errno 22] Invalid argument: '../drive_c'` while Proton creates `dosdevices/c:`, because relative symlinks cannot be created on `fuseblk` (NTFS). Hit by several VR titles whose libraries live on NTFS. Fix: keep `compatdata/<appid>` on ext4 and symlink it back:
`mv compatdata/<id> ~/proton-prefixes-external/<id> && ln -s ~/proton-prefixes-external/<id> compatdata/<id>`. Do it for every new Proton title installed on an NTFS library. Do not relocate `compatdata/3824490` (Oasis' own folder, empty, not used by the Ignition wine process) with a blanket fix:
a guard that detects only games started through `reaper` does not see the Ignition server.

## F6 — stale launch options

- **Audit.** 52 titles carried LaunchOptions, 49 of them `XR_RUNTIME_JSON=~/vr/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 PRESSURE_VESSEL_FILESYSTEMS_RW=/run/user/1000/monado_comp_ipc %command%`. SteamVR (250820) itself carries `WMR_*` Monado variables (harmless).
  Parse `localconfig.vdf` properly (an ad-hoc parse of one block missed a title's options).
- **Effect.** OpenVR titles (Alyx, Propagation, Batman) ignore the variable; OpenXR titles (SUPERHOT VR via the Unity OpenXR plugin; DOOM VFR's `wineopenxr` probe) are sent to Monado and fail (`XR_ERROR_RUNTIME_UNAVAILABLE`, `Failed to connect to monado service process`).
- **Fix without touching the options.** `up` saves `openxr_monado-dev.json` to `~/vr/oasis-x11-backup/openxr_monado-dev.json.monado-original` (only when no backup exists; warns when the file differs), writes a SteamVR pointer (`VALVE_runtime_is_steamvr`,
  `library_path` = SteamVR's `vrclient.so`) and records `XR_JSON_SWAPPED` in the state file; `down` restores the original (idempotent when the state file is gone, if the file is still a SteamVR pointer); `status` prints `Monado OpenXR json (...): STEAMVR|MONADO`.
  `jack-in-wayland.sh` and `-tracing.sh` warn loudly at launch when the file is still the SteamVR pointer.
- **DOOM VFR** needed a temporary `PROTON_LOG=1 PROTON_LOG_DIR=~/vr %command% +r_fullscreen 0`; put the Monado recipe back after debugging (Steam closed).

## F7 — DOOM VFR `vkAcquireNextImageKHR` (open)

Facts from the Proton log: `[VR] OpenVR system successfully initialized`, game window class registered, Vulkan device NVIDIA RTX 3060 Ti with `VK_KHR_win32_surface` (a mirror/desktop window of its own), `FATAL ERROR: vkAcquireNextImageKHR failed with error (VK_ERROR_OUT_OF_DATE_KHR)`
0.53 s later, `FORCED CRASH`. Before that, `wineopenxr` `xrCreateInstance failed` (Monado json, F6; a separate error that went away). `+r_fullscreen 0` made no difference. It used to run under Monado.

Hypotheses, ranked (all **guess**), with the one experiment that separates each (none run):

1. **Window surface size/state invalid:** the game's Win32 window is created with the HMD resolution (4320x2160) or off the visible X screen, so the first acquire is OUT_OF_DATE. Experiment: launch with a small explicit windowed size or a Proton virtual desktop.
2. **RandR change events during startup** (the compositor's `vkAcquireXlibDisplayEXT` and the guard's `xrandr --off` change the X layout while Wine's X11 driver sets up its swapchain). Experiment: start the game ~60 s after `up` finished and with `OASIS_PANEL_GUARD=0`.
3. **Proton Experimental + NVIDIA 595 (open module with local patches) X11 present bug when another client holds an acquired display.** Experiment: same game with GE-Proton (docs/70), and separately `vkcube` while SteamVR is up; if `vkcube` also fails OUT_OF_DATE it is the driver/lease combination.
4. **Window created on a desktop without usable output / not mapped by KWin (compositing + the HMD output off).** Experiment: `xwininfo -root -tree` while it starts, and `KWIN_COMPOSE=O2` / compositing off for one launch.
5. **Residue of the Monado-era launch environment** (`PRESSURE_VESSEL_FILESYSTEMS_RW`, stale `XR_RUNTIME_JSON`). Weakest: the failure is in the Vulkan window path, after OpenVR init succeeded.

## F8 — preflight traps

`jack-in-oasis-x11.sh status` (read-only) and `up` run one table; `[FAIL]` aborts `up` before anything is changed:

```
  [ OK ] cap_sys_nice: present on vrcompositor-launcher          (WARN with the exact sudo setcap line when lost)
  [ OK ] safe_mode: driver_oasis is not blocked                   (FAIL when blocked_by_safe_mode is true: SteamVR would not load Oasis)
  [ OK ] openvrpaths: runtime[0] is SteamVR                       (INFO otherwise: up reorders it, down restores)
  [INFO] vrsettings: TEST/NORMAL (dashboard on), steamvr.loglevel=4 (verbose: logs rotate fast)
  [ OK ] monado: no monado-service
  [INFO] sockets: 3 steamvr socket(s) owned by the running session
  [ OK ] libraries: all Steam libraries are present
  [ OK ] disk: / is 89% full                                      (WARN >= 90, FAIL >= 97)
  [ OK ] headset_usb: 5/5 devices enumerated                      (FAIL below 5/5; OASIS_SKIP_USB_CHECK=1 downgrades)
  [WARN] prefixes: Proton prefix problem(s) on NTFS libraries ...
  [ OK ] xr_json: ...
```
Already in `up` before: PATH with `/usr/sbin` (getcap), Oasis `driver_oasis.so` present, Oasis dir in `external_drivers`, no Monado, no leftover VR process, controllers awake (waits and speaks). The `getcap` and openvrpaths items are proven traps (docs/138).

## F9 — controllers around drops

17 G2 controller HID attach events in the kernel log during the session; 3 within +-10 s of a hub bounce (about 3.4 expected by chance), so **no correlation** (likely), as expected for controllers on the host adapter. The rough start ("started badly, settled after seconds") matches
the `0x800705b4` ERROR_TIMEOUT retries for a controller that was asleep when Oasis tried to register it (docs/138); touching the joys is the fix.

## F10 — shipped Oasis binding does not match the game (I Expect You To Die)

- **Symptom:** the game runs in VR, tracking fine, but ignores every button. The game's `Player.log` (in its prefix, `AppData/LocalLow/<studio>/<game>/`) shows `Successfully loaded action manifest into SteamVR` and no errors.
- **Root cause (proven by reading both files):** Oasis ships a binding per game, `resources/input/steam.app.<id>_hpmotioncontroller.json`, listed in the `default_bindings` of `mixedreality_hpcontroller_profile.json` (controller type `hpmotioncontroller`, fallback `oculus_touch`).
  For app 587430 it targets `/actions/ieytd_default`; the game's `actions.json` now declares `/actions/ieytd1_default` (all 26 actions exist there). SteamVR cannot apply a binding whose action set does not exist, so no input is mapped.
- **Fix:** `scripts/oasis-binding-fix.py scan|fix [--apply]` compares every installed game's `actions.json` with the shipped binding, repairs a pure action-set rename and backs up the original in `~/vr/oasis-bindings-fixed/original/`. It refuses anything it cannot prove (partial overlap, several sets).
  Of 8 shipped bindings for installed games only this one was broken (Alyx matches; OpenVR-legacy titles have no `actions.json`). Steam updates of the Oasis driver overwrite the files: re-run after an update.
- **Evidence level:** mismatch proven; that it is the cause of the dead controls is likely, **not yet confirmed in play**.

## Other traps from the same session

- A 2D/not-yet-VR app connecting to SteamVR makes it build the "Desktop Game Pointer" overlay (`valve.steam.desktopgame.*`); on this machine that is followed within seconds by an abort of the Steam client (`src/common/pipes.cpp: fatal stalled cross-thread pipe`, `crash_*.dmp`), which kills vrserver.
  Same family as the known "SteamVR desktop view crashes Steam" trap. Open: find the SteamVR setting that suppresses the pointer, or start such games outside the Steam client.
- After any Steam/vrserver crash SteamVR writes `blocked_by_safe_mode: true` for the drivers it was loading. `down` restores the backup taken at `up` time, which can overwrite flags you just cleared: clear them AFTER `down`.
- Proton logs of a non-Steam shortcut are named by its gameid, not by appid.
- Tooling mistakes worth not repeating: a launch-time `pgrep -f "AppId=..."` matches the shell running it, so a game looked alive when it was not.
