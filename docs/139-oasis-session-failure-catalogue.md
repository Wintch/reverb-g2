# 139 — Oasis/SteamVR session failure catalogue (2026-10-03, 19:30-22:30)

Every failure met while running Steam VR games through SteamVR + the Oasis/Ignition driver on the HP Reverb G2
(docs/138 is the running log; this file is the post-mortem and the prevention list). Evidence levels:
**proven** (direct log or reproduction), **likely** (fits all evidence, no discriminating test), **guess**.

## Cheat sheet: recognise it fast

| # | Symptom | Grep-able signature | Cause (level) | First action |
|---|---|---|---|---|
| F1 | Headset audio flips, HID/USB devices vanish, game stutters or stops seeing the HMD | `journalctl -k`: `usb 3-1: USB disconnect` immediately followed by `usb 3-1: new high-speed USB device`, no `-71`, no over-current | Headset hub bounces itself; visor-end marginal contact (likely, docs/22) | Stop cycling SteamVR; PC-end USB-C unplug/replug; verify 5/5 |
| F2 | "waiting for VR device", HMD dead for the rest of the session | `oasis: Fatal error: HRESULT failure [80070005] ... Failed to get HID report (HmdDriver.cpp)` thousands per minute, `Cannot locate root anchor` | `driver_oasis` keeps a stale HID handle after a hub bounce (proven for the 22:27 case; likely for the others) | `jack-in-oasis-x11.sh status` -> "HMD driver broken (stale HID)"; one `down` + `up` (or `watchdog --auto`) |
| F3 | `up` TIMEOUT with `active-hmd=0`, new vrserver exits | `Unable to bind server socket errno=98`; `ss -xlpn \| grep @/steamvr` shows a vrserver whose comm is `<pid>: vrstart` | Old vrserver survived `down` (proven) | `down` now asserts no `@/steamvr/*` socket remains |
| F4 | `up` prints TIMEOUT although SteamVR is fine, or `active-hmd` falls from 1 to 0 | log counts jump to 0 mid-run | Controllers asleep (proven); logs rotated by the HID spam (proven) | New verdict names the cause (see F4) |
| F5 | Proton game dies in ~1 s | `OSError: [Errno 22] Invalid argument: '../drive_c'` in the Proton log | New prefix on an NTFS library (proven) | `scripts/steam-prefix-guard.sh check` / `fix --apply` |
| F6 | OpenXR game says runtime unavailable under SteamVR | Player.log `XR_ERROR_RUNTIME_UNAVAILABLE`; Steam console `Failed to connect to monado service process`; `LaunchOptions` has `XR_RUNTIME_JSON=...openxr_monado-dev.json` | 49 titles pin Monado's runtime json (proven) | `up` now swaps that json for the run; `steam-launch-options-audit.py` |
| F7 | DOOM VFR dies 0.5 s after Vulkan init | `FATAL ERROR: vkAcquireNextImageKHR failed with error (VK_ERROR_OUT_OF_DATE_KHR)` then `FORCED CRASH` | Open, ranked hypotheses below | Experiments listed, none run |
| F8 | SteamVR popups, no HMD, no controllers | see the preflight table | setcap lost, safe-mode flag, runtime order, ... (proven individually) | `jack-in-oasis-x11.sh status` shows a preflight table; `up` aborts on blocking ones |
| F9 | Controllers "start badly, settle after seconds", sometimes need waking | `Cannot register controller with error: 0x800705b4`; BT `hid-generic 0005:045E:066A` attaches | Controllers on the host BT adapter, unrelated to hub bounces (likely) | Touch/shake them; no restart |

**Log retention warning.** With F2 active, `vrserver.txt` receives about 2300 lines per second; Steam keeps two ~10 MB files, so the
whole evidence of a run is rotated away within roughly 40 s (tonight's `vrserver*.txt` and `vrstartup-linux*.txt` held nothing older than
the last minutes at 22:20). Anything that needs those logs must run immediately; `status` prints the oldest retained line.

## Recovery procedure after a drop storm

1. **Stop cycling SteamVR.** Every activation cycle is another chance to loosen the contact (docs/22 stop rule: at most 2 recovery cycles per hour).
2. **PC-end USB-C unplug/replug** (the best-evidenced lever, docs/22; visor-end reseat only if that fails).
3. **Verify 5/5 enumeration** with `lsusb`: `3-1 04b4:6506`, `3-1.2 0bda:4c15`, `3-1.3 03f0:0580`, `4-1 04b4:6504`, `4-1.1 045e:0659`.
   `jack-in-oasis-x11.sh status` shows `headset_usb: 5/5` (and `up` refuses to start below 5/5).
4. **One `down` + `up` only** (`up` makes a single launch attempt by design).
5. **Check `status`** for `HMD driver broken (stale HID) since HH:MM:SS`; if present, repeat from 2 once, then stop and reseat the visor end.

## F1 — Headset USB hub drop storms

- **Symptom.** About 70 hub disconnects between 19:30 and 22:14 (71 up to 22:27:39), speaker sink flips in PipeWire, Oasis loses the HMD.
- **Signature.** `usb 3-1: USB disconnect, device number N` (plus `3-1.2`, `3-1.3`), then within the same second `usb 3-1: new high-speed USB device number N+3`
  (the hub re-enumerates itself in under 1 s, a "bounce"). No `error -71` on the hub, no over-current, no xhci error. Two children failed to
  enumerate once each right after a bounce (`3-1.2 device descriptor read/64, error -110` at 21:47:05, `3-1.3 device not accepting address, error -71` at 21:54:39).
- **Data** (`scripts/usb-drop-timeline.py --since "2026-10-03 19:30" --manual "2026-10-03 22:17:05"`; the 22:17:05 disconnect is the user's deliberate PC-end unplug and is classed MANUAL, not a storm event):
  ```
  disconnects: 72  | bounces (storm events): 71  | manual: 1  | unplug-without-reenum: 0
  first/last bounce: 10-03 20:18:57 / 10-03 22:27:39 (2.15 h span, 33.1 per hour inside the span)
  per hour: 10-03 20h=4  10-03 21h=55  10-03 22h=12
  bursts (gap<=120 s): 14, of which >=5 drops: 21:27-21:41 x31; 21:45-21:47 x7; 21:59-22:01 x5; 22:04-22:06 x6
  gap between consecutive bounces: min 2s, median 33s, max 2048s
  ```
- **Same rate without SteamVR/Oasis?** Yes (headset hub enumerated in only five boots; all others had it unplugged or on the other install):

  | boot | hub bounces | what was running |
  |---|---|---|
  | 2026-09-23 13:55-18:34 | 60 (47 in the 17h hour) | Monado (mixtape playlist, docs/131), no SteamVR |
  | 2026-09-23 18:35-09-24 00:20 | 18 | Monado era, no SteamVR |
  | 2026-09-24 00:27-00:58 | 1 | - |
  | 2026-10-01 16:30-10-02 01:16 | 12 (7 + 5 in the 00h-01h hours) | Monado hardware session (`jack-in-wayland-hw`), no SteamVR |
  | 2026-10-03 13:58-22:17 (tonight) | 82 incl. 1 manual; 12 before 19:30 during Monado work | SteamVR/Oasis from 18:55 |

  So SteamVR/Oasis is **not required** for the storms (proven); the peak hourly rate under Monado (47 in the 17h hour on 09-23) is comparable to tonight's peak (55 in the 21h hour).
- **Software trigger test.** Bounces versus Steam app start/exit and vrcompositor client connects, exact binomial tail against the time-share covered by +-N s windows:
  ```
  Steam app start/exit        +-10s:  5 of 71 near an event (chance 10.7%, P=0.888); burst-starts only: 3 of 14 (P=0.182)
  Steam app start/exit        +-20s: 10 of 71 near an event (chance 19.9%, P=0.920); burst-starts only: 6 of 14 (P=0.043)
  vrcompositor client connects +-10s:  2 of 20 (chance 15.9%, P=0.850)
  ```
  The individually striking coincidences (20:53:05 Alyx start +19 s, 21:13:56 Alyx exit +14 s, 22:14:25 Superhot launch, 22:27:39 a Proton `wine-preloader` connecting to the
  compositor in the same second) are not above chance as a set; the Superhot launch at 22:23:12 had no drop. The only marginal figure (burst starts, +-20 s, P=0.043) is one of
  eight tests and is **not** claimed as a finding. `vrserver.txt` around the transitions no longer exists (F2 log warning); `vrcompositor*.txt` show only client connects at those seconds,
  no display-mode or driver event. Whether SteamVR/Oasis does something at transitions is therefore **unknown**.
- **Power management ruled out as the trigger (likely).** `usbcore.autosuspend=2` but `71-usb-no-autosuspend.rules` forces `power/control=on` for `04b4`, `03f0`, `045e`, `0bda`;
  xHCI `0000:07:00.3` runtime PM is `on`/`active`; PCIe ASPM policy is `performance`. (The headset was unplugged when this was read, so the per-device attribute was not re-read.)
- **Root cause.** Marginal visor-end/cable contact (docs/22 "hub resets under load", prior observation 66 reconnects/hour): **likely**, not re-proven tonight. The PC-end replug did bring all 5 devices back
  (22:21:33), and a bounce still followed at 22:27:39.
- **Prevention.** Physical: PC-end replug, visor-end reseat, rev2A cable (docs/22). Software cannot stop it; F2 mitigates the damage.
- **Implemented:** `scripts/usb-drop-timeline.py` (bf19cb8, e90e41f).

## F2 — `driver_oasis` stale HID handle after a bounce

- **Signature.** `oasis: Fatal error: HRESULT failure [80070005] Origin: Failed to get HID report  Source: ...HmdDriver.cpp:4430` (about 2300 lines/s), `oasis: Cannot locate root anchor`; `active-hmd` falls to 0; the next game: "waiting for VR device" (`VR_Init failed with Hmd Not Found (108)`).
- **Cause.** After the hub re-enumerates, the driver keeps the old HID handle and never reopens it; the session stays dead until SteamVR is restarted (proven at 22:27:39: bounce at 22:27:39, error burst after, still running at 22:30; also at 21:50 and 22:14 in the `up` log: `active-hmd=1 tracked-devices=3` then `0/0`).
- **Self-recovery?** Not measurable from the logs (rotated, above). From the `up` log and the play notes: every bounce that coincided with a lost HMD (21:50, 22:14, 22:27) needed a restart; the 20:58:23 and 20:59:32 bounces during Alyx run 2 went by without the wearer noticing (**likely** recovered or never lost the HMD handle). The 19:52:55 controller case recovered on its own after ~10 s (docs/138). Net: self-recovery is the exception for the HMD handle.
- **Implemented** (347cec7): `jack-in-oasis-x11.sh status` prints, from timestamped log lines and the kernel log, `HMD driver broken (stale HID) since HH:MM:SS: headset hub re-enumerated Nx since this SteamVR run started ...`. Tested live at 22:30:
  ```
  HMD driver broken (stale HID) since 22:27:39: headset hub re-enumerated 1x since this SteamVR run started (last 22:27:39); Oasis still holds the old HID handle (85516 errors, root-anchor lines 7)
  ```
  `watchdog` reports (exit 10 stale, 11 headset absent, 12 unexplained); `watchdog --auto` does ONE `down`+`up` only with 5/5 USB present and fewer than 2 recoveries in the last hour (`~/vr/oasis-x11-recoveries`), else it stops and says to reseat; `--dry-run` shows the plan (tested). Never started automatically; invoke it.
  The "since" time is the hub bounce when it precedes the first retained error line (log rotation hides the real onset).
- Limits: the state `HEADSET_ABSENT` (hub missing) and `UNEXPLAINED` (errors without a bounce) are deliberately not auto-recovered.

## F3 — stale `vrserver` survived `down`

- **Signature.** comm renamed to `<pid>: vrstart`, holding `@/steamvr/SteamVR_Namespace`, `VR_ServerPipe_<pid>`; new vrserver: `Unable to bind server socket errno=98` (this line is no longer in the retained logs).
- **Fix 4738456 reviewed, then replaced** (347cec7): the old `vr_pids` also matched any process whose command line merely contained `SteamVR/bin/linux64/` or `ignition` (only `bash/awk/ps/grep/sshd` were excluded: a `tail`, `less`, `python` or `ssh` mentioning the path would be killed). `vr_pids` now matches the comm, the renamed `<pid>: vrstart` comm, or an **argv[0]** under `SteamVR/bin` / the Oasis folder; it uses `/proc` builtins only. Self-test (sourced, harmless `sleep` decoys): `bash -c "sleep 6 # .../SteamVR/bin/linux64/vrserver"` NOT matched; a process started as `.../SteamVR/bin/linux64/vrfake` matched.
- **Assertion.** After the kills `down` waits up to 5 s for no `@/steamvr/*` listener (`ss -xlpn`); if one remains it stops the owner by PID, logs it, and returns 5 if still held. `up` preflight refuses to start while such sockets exist without a VR process; `status` prints `steamvr abstract sockets: ...` and `STALE` when held without a VR process.

## F4 — misleading `up` verdicts; panel guard

- **Bugs (proven).** (a) the counts were `grep -c` over the whole log: when the HID spam rotated the log, `active-hmd` read 0 mid-run (21:50:27, 22:14:54) and a stale vrserver (F3) also read 0, both printed `TIMEOUT`; (b) controllers asleep for 120 s printed `TIMEOUT` with a healthy SteamVR (20:08, 20:11, 21:22).
- **New logic** (347cec7): counts come from log lines timestamped after the launch (`oasis_scan`, both rotation files), flags are sticky, and a hopeless condition ends the watch early. Result and plain-English `cause:` line: `OK`, `STALE_SOCKET`, `SAFE_MODE`, `STALE_HID`, `HMD_MISSING` (hub absent / never selected), `COMPOSITOR_FAILED`, `COMPOSITOR_PENDING`, `CONTROLLERS_MISSING` (exit 4: SteamVR healthy, touch the joys, no restart), `TIMEOUT` (nothing matched). Tested with synthetic logs (scan counts, STALE_HID, future `t0` = NONE); a real `up` was not run (rules).
- **Panel guard.** Evidence: in 14 runs it fired once (19:38:12, the panel's first wake); at every following `up` the output was not on the desktop (`on desktop now: no` in 13 of 14, the exception being the very first run before the guard existed), including after hour-long games with no guard alive. Persistence is therefore **not demonstrated necessary**, and a 0.3 s `xrandr` poll for hours risks interfering with the lease (guess). Implemented: guard PID in the state file, guard ends by itself when the state file is gone, `OASIS_GUARD_PERSIST=1` keeps it until `down` (1 s poll), default unchanged (stops when the watch ends).

## F5 — Proton prefixes on NTFS libraries

- **Signature / cause (proven, docs/70).** `OSError: [Errno 22] Invalid argument: '../drive_c'` creating `dosdevices/c:`: relative symlinks cannot be created on `fuseblk`. Hit by Batman AVR (502820), Superhot VR (617830), The Lab (450390); relocated by hand.
- **Implemented** (510673e): `scripts/steam-prefix-guard.sh check` (read-only; real dir on NTFS, broken link, or link whose target is also NTFS), `fix [--apply]` (dry run by default; refuses a running appid via `STEAM_COMPAT_DATA_PATH`, skips existing destinations, refuses without free space, uses `mv` so a failure leaves the source). Called from `up` preflight as a WARN. Live:
  ```
  PROBLEM  appid 3824490  REAL-DIR-ON-NTFS  (0)  in /mnt/videos/SteamLibrary/steamapps/compatdata
  prefix guard: 1 problem(s) among 34 compatdata entries; store /home/iam/proton-prefixes-external: 9.8G (89% used on /)
  ```
  `compatdata/3824490` (Oasis) is an **empty** directory and nothing runs from it (the Oasis wine process does not use that prefix), so moving it is safe; `fix` was only run as a dry run. Fixture test of `fix --apply` on a scratch tree passed. Root is at 89% (rule: ~80%); `~/proton-prefixes-external` is 9.8 GB.

## F6 — stale launch options

- **Audit** (`scripts/steam-launch-options-audit.py`, read-only, lists all titles; 849e973, e90e41f): 52 titles carry LaunchOptions, 49 of them `XR_RUNTIME_JSON=/home/iam/vr/monado/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 PRESSURE_VESSEL_FILESYSTEMS_RW=/run/user/1000/monado_comp_ipc %command%` (Alyx, Superhot VR, Propagation, ... most uninstalled). SteamVR (250820) itself carries `WMR_*` Monado variables (harmless). DOOM VFR: `PROTON_LOG=1 PROTON_LOG_DIR=/home/iam/vr %command% +r_fullscreen 0`.
- **Effect.** OpenVR titles (Alyx, Propagation, Batman) ignore the variable; OpenXR titles (Superhot VR via the Unity OpenXR plugin; DOOM VFR's `wineopenxr` probe, `xrCreateInstance failed` at 21:58) are sent to Monado and fail (`XR_ERROR_RUNTIME_UNAVAILABLE`, `Failed to connect to monado service process`). Proven by the coordinator's Player.log/console reading.
- **Fix without touching 49 options** (347cec7): `up` saves `openxr_monado-dev.json` to `~/vr/oasis-x11-backup/openxr_monado-dev.json.monado-original` (only when no backup exists; warns when the file differs), writes a SteamVR pointer (`VALVE_runtime_is_steamvr`, `library_path` = SteamVR's `vrclient.so`), records `XR_JSON_SWAPPED` in the state file; `down` restores the original (also idempotent when the state file is gone, if the file is still a SteamVR pointer); `status` prints `Monado OpenXR json (...): STEAMVR|MONADO`. `jack-in-wayland.sh` and `-tracing.sh` warn loudly at launch when the file is still the SteamVR pointer (4bbac2a). `jack-in.sh` (copies already differ) was not touched.
- **To restore later (user action, Steam closed):** DOOM VFR's original launch options are saved in `~/vr/doom650000-launchoptions.original` (the Monado line above) and must be put back after the debugging (the `PROTON_LOG` line is temporary). `localconfig.vdf` was never edited by tooling.

## F7 — DOOM VFR `vkAcquireNextImageKHR` (open)

Facts from `~/vr/steam-650000.log`: `[VR] OpenVR system successfully initialized` at 28807.274, game window class registered, Vulkan device NVIDIA RTX 3060 Ti with `VK_KHR_win32_surface` (a mirror/desktop window of its own), `FATAL ERROR: vkAcquireNextImageKHR failed with error (VK_ERROR_OUT_OF_DATE_KHR)` at 28807.807 (0.53 s later), `FORCED CRASH`. Before that, `wineopenxr` `xrCreateInstance failed` (Monado json, see F6; a separate, now-removed error). It used to run under Monado (no X display grab).

Hypotheses, ranked (all **guess**), with the one experiment that separates each (none run):

1. **Window surface size/state invalid: the game's Win32 window (run with `+r_fullscreen 0`) is created with the HMD resolution (4320x2160) or off the visible X screen, so the first swapchain image acquire is OUT_OF_DATE.** Experiment: launch with a small explicit windowed size (idTech `r_mode`/custom width/height in the game config) or a Proton virtual desktop; if it survives, this is it.
2. **RandR change events during startup** (the compositor's `vkAcquireXlibDisplayEXT` and the guard's `xrandr --off` change the X layout at the same time, so Wine's X11 driver invalidates the swapchain). Experiment: start the game ~60 s after `up` finished (guard dead, compositor settled) and with `OASIS_PANEL_GUARD=0`; compare against launching right after `up`.
3. **Proton Experimental + NVIDIA 595 (open module with local patches) X11 present bug when another client holds an acquired display.** Experiment: same game with GE-Proton (docs/70 A/B) and, separately, a trivial Vulkan windowed program (`vkcube`) started while SteamVR is up: if `vkcube` also fails OUT_OF_DATE, it is the driver/lease combination, not DOOM.
4. **Window created on a desktop without usable output / not mapped by KWin (compositing + the HMD output off).** Experiment: `xwininfo -root -tree` while it starts (is the window mapped, what size?) and `KWIN_COMPOSE=O2`/compositing off for one launch.
5. **Residue of the Monado-era launch environment** (`PRESSURE_VESSEL_FILESYSTEMS_RW`, stale `XR_RUNTIME_JSON`). Experiment: clean launch options, now that the json swap (F6) makes the OpenXR probe harmless. Weakest: the failure is in the Vulkan window path, after OpenVR init succeeded.

## F8 — preflight traps

`jack-in-oasis-x11.sh status` (read-only) and `up` now run one table; `[FAIL]` aborts `up` before anything is changed:

```
  [ OK ] cap_sys_nice: present on vrcompositor-launcher          (WARN with the exact sudo setcap line when lost)
  [ OK ] safe_mode: driver_oasis is not blocked                   (FAIL when blocked_by_safe_mode is true: SteamVR would not load Oasis)
  [ OK ] openvrpaths: runtime[0] is SteamVR                       (INFO otherwise: up reorders it, down restores)
  [INFO] vrsettings: TEST/NORMAL (dashboard on), steamvr.loglevel=4 (verbose: logs rotate fast)   (kiosk = dashboard.arcadeMode)
  [ OK ] monado: no monado-service
  [INFO] sockets: 3 steamvr socket(s) owned by the running session
  [ OK ] libraries: all Steam libraries are present
  [ OK ] disk: / is 89% full                                      (WARN >= 90, FAIL >= 97)
  [ OK ] headset_usb: 5/5 devices enumerated                      (FAIL below 5/5; OASIS_SKIP_USB_CHECK=1 downgrades)
  [WARN] prefixes: 1 Proton prefix problem(s) on NTFS libraries ...
  [ OK ] xr_json: ...
```
Already in `up` before: PATH with `/usr/sbin` (getcap), Oasis `driver_oasis.so` present, Oasis dir in `external_drivers`, no Monado, no leftover VR process, controllers awake (waits and speaks). The `getcap` and openvrpaths items are proven traps from docs/138. `steamvr.loglevel` 4 lives in the test settings; arcade/kiosk originals are in `~/vr/oasis-x11-backup/`.

## F9 — controllers around drops

17 G2 controller HID attach events from the kernel log tonight; 3 within +-10 s of a hub bounce (about 3.4 expected by chance from the bounce coverage), so **no correlation** (likely), as expected for controllers on the host adapter. The rough start ("started badly, settled after seconds") matches the documented `0x800705b4` ERROR_TIMEOUT retries for a controller that was asleep when Oasis tried to register it (docs/138); touching the joys is the fix. BlueZ logged only older refused/timeout lines (14:25-15:25, before the session).

## F10 — shipped Oasis binding does not match the game (I Expect You To Die)

- **Symptom:** the game runs in VR, tracking fine, but ignores every button; the user cannot get past the first screen. Log of the game (`AppData/LocalLow/<studio>/<game>/Player.log` in its prefix) shows `Successfully loaded action manifest into SteamVR` and no errors.
- **Root cause (proven by reading both files):** Oasis ships a binding per game, `resources/input/steam.app.<id>_hpmotioncontroller.json`, listed in the `default_bindings` of `mixedreality_hpcontroller_profile.json` (controller type `hpmotioncontroller`, fallback `oculus_touch`). For app 587430 it targets `/actions/ieytd_default`; the game's `actions.json` now declares `/actions/ieytd1_default` (all 26 actions exist there under the new set). SteamVR cannot apply a binding whose action set does not exist, so no input is mapped.
- **Fix:** `scripts/oasis-binding-fix.py scan|fix [--apply]` compares every installed game's `actions.json` with the shipped binding, repairs a pure action-set rename and backs up the original in `~/vr/oasis-bindings-fixed/original/`. It refuses anything it cannot prove (partial overlap, several sets) and reports it. Checked tonight: 8 shipped bindings for installed games, only 587430 was broken (Alyx matches; OpenVR-legacy titles have no `actions.json` and are skipped). Steam updates of the Oasis driver overwrite the files: re-run after an update.
- **Evidence level:** mismatch proven; that it is the cause of the dead controls is likely, **not yet confirmed in play** (a hub storm broke the session right after the relaunch).

## Commits (local, `~/Documents/reverb-g2`, not pushed)

| commit | what |
|---|---|
| bf19cb8, e90e41f | `scripts/usb-drop-timeline.py` |
| 510673e | `scripts/steam-prefix-guard.sh` |
| 849e973, e90e41f | `scripts/steam-launch-options-audit.py` |
| 347cec7 | `jack-in-oasis-x11.sh`: preflight, watchdog, verdicts, sockets, json swap, guard |
| 4bbac2a | `jack-in-wayland.sh`, `jack-in-wayland-tracing.sh`: warn on a SteamVR-pointing runtime json |
| 4738456 (earlier) | `vr_pids` renamed-comm fix, superseded by 347cec7 |
| 630e52e, 1dc13ec | `up` reported SAFE_MODE after 22 s because an unrelated driver (`prism`) was blocked; now only a block of driver `oasis` counts (and the exec bit lost by that edit was restored) |
| 530fca9 | `steam-prefix-guard.sh preseed`; `up` now runs `fix --apply` + `preseed --apply` (OASIS_PREFIX_AUTOFIX=0 disables). 32 installed apps pre-seeded, I Expect You To Die was the proof that first launches on NTFS die |
| 428ca4a | `scripts/oasis-binding-fix.py` (F10) |

`~/vr/jack-in-oasis-x11.sh`, `~/vr/jack-in-wayland.sh` and `~/vr/jack-in-wayland-tracing.sh` are byte-identical to the tracked copies (replaced by rename so a running instance was not disturbed).

## Addendum 2026-10-03 22:53: stale-HID is not always fatal

After the hub bounce at 22:48:15 `status` / `watchdog` reported the HMD driver as broken (stale HID, 64k errors) while the user kept playing The Lab for about five more minutes with normal tracking and 90 fps (compositor stats: 36509 presents, 1.8 % dropped, 0 reprojected). Earlier bounces (21:50, 22:14, 22:27) did leave the HMD unusable (a game said "waiting for VR device"). So the HID-error signature alone is NOT proof of a dead HMD: it only says the driver's HID handle is stale. Before `watchdog --auto` restarts a session, require a second signal (the compositor stopped presenting, or tracked-devices dropped, or the user reports it). Until the detector is refined, treat its recommendation as advice and do not auto-restart.

## Addendum 2026-10-03 23:15: late-night log

- Hub bounces kept coming: besides the 71 counted by the timeline through 22:27 there were bounces at 22:27, 22:39, 22:43, 22:48 and seven between 22:58 and 23:02 (about one per minute), so the storm was getting denser, not rarer. The 22:17:05 PC-end unplug was done by hand and is excluded.
- Sessions that came up fine and stayed fine: 22:23 (Superhot VR, The Lab); sessions broken by a bounce within minutes: 22:14, 22:27, 22:43, 23:02. Restarting does fix a broken session, but each cycle counts against the contact (docs/22 stop rule), so the recommendation stands: visor-end reseat before more cycles.
- Mistakes of the night worth not repeating: (1) `steam-prefix-guard.sh fix --apply` without naming an appid also relocated `compatdata/3824490` (the Oasis folder, empty; harmless, the session kept running) because the guard only detects games started through `reaper`, not the Ignition server; (2) my first launch-options parse read only one block and said Superhot had no launch options while it carried the Monado ones; the audit script parses the VDF properly; (3) a launch-time `pgrep -f "AppId=..."` matches the shell running it, so a game looked alive when it was not.
- A permission classifier blocked downloading a game from an external link and then reading the downloaded file, even after the user agreed in chat; the user has to download it themselves or add a permission rule.
