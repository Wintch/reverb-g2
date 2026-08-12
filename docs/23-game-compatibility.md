# 23 — Game compatibility status

Every VR title tried on this rig (xrizer + Monado, bypassing SteamVR entirely — see
`docs/06-known-issues.md`), with its Steam AppID and a link to SteamDB. Status reflects the
last time each title was actually looked at with the headset on — per this project's core
rule (`CLAUDE.md`, "the single most important rule"), a title isn't "working" until a human
saw it, and several early sweep results below are marked accordingly as log-only, not
physically verified.

**Shared limitation across every WORKING title below**: controller **position** tracking
(constellation, camera-based) is paused pending upstream Monado reviewer feedback
(`docs/03-controllers.md`). All 6DoF sessions are head-only — controllers rotate correctly
but stay positionally offset from wherever they started. This is expected, not a per-game
bug, and isn't repeated in every row.

## Working

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| International Space Station Tour VR | [797200](https://steamdb.info/app/797200/) | ✓ | Cleanest signal of the whole sweep (T073, T075) — zero warnings, FOCUSED, real 6DoF head tracking confirmed live. |
| Aliens Attack VR | [932190](https://steamdb.info/app/932190/) | ✓ | One `IVRChaperoneSetup_005` unknown-interface warning caused one session to cycle and exit, but recovered clean on a second attempt (T073, T076). |
| Cosmic Flow: A Relaxing VR Experience | [1267950](https://steamdb.info/app/1267950/) | ✓ | Confirmed working, real 3D (T073, T077). |
| VRSailing by BeTomorrow | [579050](https://steamdb.info/app/579050/) | ✓ | Confirmed working (T073, T079); also the title used to field-test the global recenter patch (`patches/xrizer/0001`) — was ~4m off its play-space center, recenters correctly with height preserved after the fix (T080). |
| SUPERHOT VR | [617830](https://steamdb.info/app/617830/) | ✓ | Trigger, grab, and hand tracking all confirmed working (T082). Menu button was dead on arrival (T067) — root-caused and fixed for the **left** controller via `patches/xrizer/0002` (T083-T084); right hand not expected to work, `Menu` is Left-only on the `oculus_touch` profile, matching real Oculus Touch hardware. |
| VRChat | [438100](https://steamdb.info/app/438100/) | ✓ | Confirmed working, reached `FOCUSED`, real gameplay, EasyAntiCheat loads clean under Proton (T082-session, same day). First attempt showed nothing — traced to an unrelated DP/panel dropout from heavy session churn that session, not a VRChat bug; a clean retest worked immediately. |
| Propagation VR | [1363430](https://steamdb.info/app/1363430/) | ✓ | Best signal of the whole non-original sweep — "works just perfect", including exiting the game from inside via the controllers (menu/quit works out of the box, no patch needed unlike SUPERHOT). First launch had controllers powered off (Monado has no controller hot-add — confirmed `<none>`/`<none>` in the log), retested clean after a full jack-in-wayland.sh restart with controllers on beforehand. |
| Aircar | [1073390](https://steamdb.info/app/1073390/) | ✓ | **RECOMMENDED — the reference title for this rig (re-verified 2026-08-12, T161).** User verdict: "100% funcional con sticks VR o Xbox 360 por igual, buen performance, sonido en casco". Works with either input device, interchangeably. Measured in the same session: **89-90 fps** at `4320x2160@90` with the default 140% render scale (3024x3024 per eye), and **0.13% late frames** (0.12/s) once warmed up. **Warm-up caveat that applies to every Proton title, not just this one**: the first measurement of the same session read 3.44% late frames (3.10/s) with the render scale *unchanged* -- that window caught DXVK shader compilation and asset streaming, not steady state. Its `DXVK_state_cache` directory is empty, so first-run compilation is heavy. **Do not judge a Proton title's pacing in its first minute.** Audio routes to the headset and PipeWire's stream-restore remembers it per-application across Monado restarts. VR-controller stick drift needs `WMR_STICK_DEADZONE=0.15` (patch 0008) -- WMR controllers carry no stick centre calibration at all; without it the drift is plainly felt and was initially, wrongly, blamed on the Xbox pad. Earlier verdict: "first game I'd call 99%" — real VR, full controller input, excellent GPU utilization. First launch fell to 2D-only via the localconfig launch-options trap (see the note below this table). Two session-level issues observed, neither the game's fault: a pronounced CCW **roll drift** on the long-uptime 6DoF/SLAM session (horizon re-tilts right after every recenter — recenter is yaw-only by design), and on the fresh-SLAM session a wrong start position ("outside the vehicle") from the origin anchoring where the headset sat. See T106 for the SLAM-divergence follow-up. |
| Google Earth VR | [348250](https://steamdb.info/app/348250/) | ✓ | **Works perfectly on a 3dof session** — user: "funciona perfecto… todos sus controles andan perfecto, eso se ve en el modelo 3d adentro" (the in-game controller model confirms every input works). On the same night's *diverging* 6DoF/SLAM session it was unusable (head jitter + view flying away — Basalt numerical divergence, `det(Q1Jl)==0` cascades in the log; light on didn't help, recenter didn't either). Controller *position* missing is the known project-wide 3DoF-controllers limitation, not a game issue. First launch attempt also hit the localconfig trap ("OpenVR failed to initialize / InterfaceNotFound" was the visible symptom). |
| Dead Herring VR | [1498490](https://steamdb.info/app/1498490/) | ✓ | Real VR image and gameplay reached; user was mispositioned (same diverging-SLAM session as Google Earth — needs a clean-session retest for a final verdict, but the game itself renders and runs). Curiosity: has a 2D debug mode showing a map on the desktop window in 3D. |
| Tank Mechanic Simulator VR | [1463010](https://steamdb.info/app/1463010/) | ✓ | Confirmed working, 2026-08-09 — user: "perfecto! 3dof en los joy. Imagen excelente." Shows a generic "does not appear to support headset" warning on first launch (same harmless whitelist-check pattern as Dark Room VR) — click through it, doesn't block anything real. |
| SafeZoneVR | [1701090](https://steamdb.info/app/1701090/) | ✓ | Image/gameplay confirmed working (2026-08-09), but head-tracking drifted left during both attempts, including a fresh-SLAM restart — **not the usual `det(Q1Jl)==0` numerical-divergence signature** (zero such warnings in the log either time, unlike Aircar/Google Earth VR), so likely plain SLAM/VIO drift rather than the known divergence bug. The global recenter shortcut (hold menu 3s) never fired during either SafeZoneVR attempt (`xrizer.txt` shows zero "menu button held" lines that session, which itself exited on its own after only ~61s, clean `STOPPING→IDLE→EXITING`, not a crash). **Confirmed NOT a general recenter regression**: immediately re-tested on VRSailing (same session, same xrizer build) and it fired twice, ~3.0s hold each time, exactly as designed. So the SafeZoneVR case is either that the ~61s session never gave a full 3s of continuous hold a real chance, or something specific to that game/session — not root-caused further this session, redo with a longer SafeZoneVR run if it recurs. |
| Interkosmos | [579110](https://steamdb.info/app/579110/) | ✓ | Confirmed working 2026-08-12 (T161) — 3DoF hands, video perfect. Sound not verified (none reached the user in the opening section; may appear further in). |
| Emergence | [1337820](https://steamdb.info/app/1337820/) | ✓ | Confirmed working 2026-08-12 (T161) — plays well with the VR sticks. **0.41% late frames** once warm. Audio needed routing to the headset by hand (see the audio note below the tables). |
| Blast the Past | [943170](https://steamdb.info/app/943170/) | ✓ | Confirmed working 2026-08-12 (T161) — hands in 3DoF and responding. **The cleanest pacing result measured so far: ZERO late frames in 30 s** (0.00–0.09%). |
| Audio Factory | [722590](https://steamdb.info/app/722590/) | ✓ | Confirmed working 2026-08-12 (T161). Two observations that are **not this title's fault**: the user sat too high (Monado assumes a flat 1.6 m floor below the headset at startup, T146, project-wide) and one controller was 3DoF-only (the paused controller position tracking, `docs/03`). |
| VersaillesVR \| The Palace is yours | [1098190](https://steamdb.info/app/1098190/) | ✓ | Confirmed working 2026-08-12 (T161) — sound in the headset, both sticks visible and registering movement. **0.37% late frames** once warm. Started at ~2 fps and settled on its own: the most extreme warm-up case measured (see the warm-up note below). |
| Steam 360 Video Player | [613220](https://steamdb.info/app/613220/) | ✓ | Reaches VR with controllers visible, but renders black **for lack of content** — the project's own test media is down to a single equirect JPG. Structurally fine; verification incomplete rather than failed (2026-08-12, T161). |

> **Correction to a conclusion in `CLAUDE.md` (2026-08-12, T161).** That file records Funhouse,
> InCell VR and InMind VR as "each fail for their own unrelated reason … **not a shared bug**".
> That does not hold. InCell and InMind share one cause exactly (the missing Oculus
> `OVRPlugin`), and Funhouse was separately unable to reach the runtime at all because its
> launch options were incomplete. Three different crash signatures, two shared causes, and
> none of the three was ever observed under a working configuration.

## Runs in 2D but never enters VR — opens an XR session and abandons it

A distinct failure class, named 2026-08-12 (T161), previously lumped in with "doesn't work".
These titles **do** talk to OpenVR: they create a session and then drop it inside the same
millisecond, while the process stays alive and plays perfectly flat on the desktop. Identical
signature in all three:

```
OpenXR session state changed: SYNCHRONIZED -> STOPPING -> IDLE -> EXITING
```

That is neither a crash nor a plumbing gap. The likely cause is a missing per-title launch
flag; **`steam -applaunch <id> <args>` does NOT forward arguments** (verified — the game's
cmdline ends at the .exe), so it has to go in the launch options as `%command% -vr` or
whatever the title expects, which needs Steam closed. Untested as a batch.

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| Dagon | [1481400](https://steamdb.info/app/1481400/) | ✓ | Runs perfectly in 2D; the user recalls having played it in VR before and could find no in-game way to switch. |
| Back to Dinosaur Island | [412940](https://steamdb.info/app/412940/) | ✓ | Runs fine in 2D, never takes the headset. CryEngine, like its sequel — but this one does not crash. |
| Amoreon NightClub | [701100](https://steamdb.info/app/701100/) | ✓ | 2D only, appears to run fine. |

## Blocked by a named gap in our own stack

Not compatibility problems — each is a specific missing piece, located with file and line.

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| fpsVR | [908520](https://steamdb.info/app/908520/) | ✓ | **xrizer does not support OpenVR overlay applications at all**: `Unsupported application type: Overlay` from `xrizer::clientcore`. No overlay app can work — not fpsVR, not OVR Toolkit, none. A missing feature, not a misconfiguration. Its first failure was the launch-options gap (`ERROR_RUNTIME_UNAVAILABLE`); fixing that only revealed the real blocker (2026-08-12, T161). |
| Microsoft Maquette | [967490](https://steamdb.info/app/967490/) | ✓ | Reaches `FOCUSED` with both controllers, then its readiness checklist fails on "controllers on" and "controllers tracking". **The log points at the chaperone, not at tracking**: `GetPlayAreaSize` and `GetPlayAreaRect` unimplemented at `src/chaperone.rs:65` and `:58`. Separately, several right-hand bindings are rejected — `/user/hand/right/input/x/click`, `/y/click`, `/trigger/value` — because X/Y are **left-hand only** on the `oculus/touch_controller` profile (the right hand has A/B), the same class as SUPERHOT's Menu button (2026-08-12, T161). |
| Back to Dinosaur Island 2 | [452640](https://steamdb.info/app/452640/) | ✓ | Crashes outright on launch: the user saw CryEngine's "crash handler not found" followed by "bug submission failed" — the reporter failing after the game had already died. The XR session opens and exits in the same millisecond (2026-08-12, T161). |

## Broken — real, reproducible xrizer/Monado bugs

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| Poly Runner VR | [462910](https://steamdb.info/app/462910/) | ✓ | Reproducible 2/2: gets stuck permanently at OpenXR session state `READY`, spamming `app requested unknown interface "IVRCompositor_013"` in an infinite tight loop (~1300 lines/sec, ~190% CPU), never advancing or exiting on its own — killed by hand both times. Renders normally in flat 2D the whole time (confirmed physically), just never enters stereo VR. `IVRCompositor_013` itself is a confirmed dead end (never existed in any real SteamVR release, see `patches/xrizer/README.md`) — the real bug is why the client-side retry never gives up, still open. |
| Water Bears VR | [394130](https://steamdb.info/app/394130/) | ✓ | xrizer's compositor recreates the swapchain every single frame, for both eyes, forever (`recreating swapchain` spamming in `compositor.rs:1247`, ~65 cycles/sec) — never stabilizes a presentable frame, panel stays dark. Game itself is healthy: input works (trigger gives audible feedback) and it renders fine to its own flat 2D mirror the whole time. Real cause not fully isolated — likely a per-eye texture/bounds mismatch that `is_usable_swapchain()` never accepts, worth a closer look. |
| War Robots VR: The Skirmish | [672640](https://steamdb.info/app/672640/) | ✓ | Calibrates fine, then drops to backlight-only with an un-skippable "put on your VR helmet" prompt. Root cause spans two repos: xrizer never implements HMD presence/worn detection (`ShouldApplicationPause`/`IsInputAvailable` in `src/system.rs` are hardcoded stubs), and Monado's `wmr_hmd.c` already reads the real proximity sensor but never wires it into Monado's own working `XR_EXT_user_presence` support. Scoped, not started — see `patches/xrizer/README.md`. |
| IL DIVINO - Michelangelo's Sistine Ceiling in VR | [1165850](https://steamdb.info/app/1165850/) | ✓ | Menu renders 2D-only on the desktop; entering the experience gives audio in the headset but **no image** (backlight only). Session reached `FOCUSED` with both controllers registered, launch options confirmed applied — the failure is in the render path, cause not investigated (2026-08-09, one attempt). |
| Meditation VR | [1301850](https://steamdb.info/app/1301850/) | ✓ | All-black in the headset, nothing ever shows. Log-clean: `FOCUSED`, controllers on `oculus/touch_controller`, one harmless `IVRExtendedDisplay_001` unknown-interface probe (same benign category as the `IVRCompositor_013` lesson). Same "session healthy, renders nothing visible" shape as the player's own LoadPhotoTexture trap — not investigated further (2026-08-09, one attempt). |
| Aircar, **on the everyday system specifically** | [1073390](https://steamdb.info/app/1073390/) | ✓ | **Not a contradiction of the ✓ working row above** — that verdict is from the lab machine (GNOME/Wayland/90Hz/patched); this is a fresh xrizer build on the everyday system (KDE/X11/60Hz/unpatched, see `docs/pruebas.jsonl` T152 for the environment note), never tested there before 2026-08-11. Stays in flat 2D through several launch-plumbing fixes (canonical launch options, Steam-wide env export, `-vr` flag) — `PROTON_LOG=1` proved the game's own `openvr_api.dll` DOES load and DOES reach `vrclient_x64.dll` (xrizer's real bridge), cycling load/unload 4 times before the process exits on its own after ~9s. So the OpenVR init handshake is being attempted and failing, not skipped — genuinely different symptom from anything else in this table. Not root-caused; needs narrower `WINEDEBUG` channels or a second already-lab-verified Proton title (SUPERHOT, Propagation VR) tried here to check if this is Aircar-specific (older OpenVR SDK 1.0.16) or a general regression on this machine's xrizer build. |
| Aliens Attack VR, **on the everyday system specifically** | [932190](https://steamdb.info/app/932190/) | ✓ | **Second title reproducing Aircar's exact non-connection signature on this machine** (2026-08-11, `docs/pruebas.jsonl` T154-T155) — installed fresh, canonical launch options set via the Steam UI, game runs fine in flat 2D on the desktop monitor, headset panel powered but blank. Zero new `client_connected` in Monado's log, and `~/.local/state/xrizer/xrizer.txt` doesn't exist anywhere on disk — xrizer never even opens its own log. Confirmed this isn't a plumbing gap specific to this title: the Proton-side bridge (`compatdata/932190/pfx/drive_c/vrclient/bin/vrclient_x64.dll`) and prefix-local `openvrpaths.vrpath` are already correctly wired, reusing the same setup validated for Aircar. A `PROTON_LOG=1` relaunch to compare traces against Aircar's is queued, not yet captured. Two already-lab-verified titles both failing identically here is a real update to the working theory in the Aircar row above: this reads increasingly like a general everyday-system/KDE xrizer regression, not something specific to Aircar's older OpenVR SDK version. External research (not project-specific) found three open, unresolved public bug reports for NVIDIA + Proton + OpenXR (`ValveSoftware/steam-runtime#782`, `ValveSoftware/Proton#7228`, an NVIDIA Developer Forums thread on driver 550.76) — none symptom-for-symptom identical to ours, but real precedent that this stack is independently fragile on NVIDIA. **Standing plan**: if the pending PROTON_LOG trace matches Aircar's pattern, stop chasing this here and resume validation on the dev/lab machine, where the full sweep already works. |

## Failed — unrelated to xrizer/Monado (Proton/engine-specific)

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| NVIDIA® VR Funhouse | [468700](https://steamdb.info/app/468700/) | ✓ | **Verdict suspect, needs a retest (2026-08-12, T161).** This title's launch options were **missing `PRESSURE_VESSEL_FILESYSTEMS_RW`**, so it could not see Monado's socket from inside pressure-vessel and could not have reached VR regardless of PhysX. The recipe is now complete; the Proton/PhysX/CUDA verdict above was recorded under the broken configuration and should not be trusted until it is run again. |
| InCell VR | [396030](https://steamdb.info/app/396030/) | ✓ | **Root cause corrected 2026-08-12 (T161).** The game is a **native Linux Unity build** that calls Oculus's `OVRPlugin` before anything else (`OVRSwitcher.GetVRActiveDevice`). `libOVRPlugin.so` has never existed on Linux — Oculus dropped the platform in 2015 — so Mono throws `DllNotFoundException` and the process aborts in under a second. **Nothing here ever reached VR**, so the earlier `VR_InitInternal` verdict described a stage the game could not get to. `tools/ovrplugin-stub/` fixes that: a 78-symbol stub answering "no HMD" (install into `InCell_Data/Plugins/x86_64/` — **not** `Mono/x86_64/`, which is only the fallback path the log advertises). With it the stub's trace shows `ovrp_GetStatus` being called and the stack continuing through `SteamVR.CreateInstance` → `OpenVR.Init` → `OpenVRInterop.InitInternal`, where it now dies — so the old verdict was right about WHERE, one stage later than anyone could previously observe. **Next suspect**: the game bundles its own OpenVR 1.0.x-era `libopenvr_api.so` in `Plugins/x86_64/`; an ABI mismatch against xrizer would explain a crash this early (xrizer never opens its log). Not investigated. |
| InMind VR | [343740](https://steamdb.info/app/343740/) | ✓ | **Same root cause as InCell VR, corrected 2026-08-12 (T161)** — same studio (Nival VR), same native Linux Unity build, same `DllNotFoundException: OVRPlugin` (`OVRManager.Update` → `OVRPlugin.get_hasVrFocus`). The "unrelated Mono crash" recorded earlier is the *symptom* of a missing native library, not a cause. The stub in `tools/ovrplugin-stub/` applies here too but **has not been tried on this title yet**. Context that pointed the way: the user recalls both titles running on a DK2, which makes a genuine performance or complexity failure implausible. |
| Surgeon Simulator VR: Meet The Medic | [457420](https://steamdb.info/app/457420/) | ✓ | Crash-loop: 4 rapid connect/disconnect cycles from `SurgeonVR.exe` before giving up (T073, log-only, never looked at physically). |
| World of Guns: VR | [1111760](https://steamdb.info/app/1111760/) | ✓ | Never gets past the initial steam/wineopenxr probe stage at all — fails earlier than every other title tried (T073, log-only). |
| Overkill VR | [518720](https://steamdb.info/app/518720/) | ✓ | Confirmed physically (was log-only "inconclusive" in T073): xrizer shows a throwaway session cycle at launch (READY→EXITING in 18ms, same shape as VRChat/Overkill's own harmless probe) then goes silent — no second real session ever opens, even after waiting well past the process's own high-CPU "loading" window. Desktop mirror shows a plain white screen, headset shows nothing. Not the slow-Unity-boot theory T073 floated — it just never gets further. |
| Welcome to Chornobayivka VR | [2064150](https://steamdb.info/app/2064150/) | ✓ | Confirmed physically (was log-only "ambiguous" in T073): reaches `FOCUSED`, real 3D, controllers load fine (`oculus/touch_controller` on both hands) — but the game's own camera has a fixed **roll** (world tilted sideways), always the same initial angle, present from launch and unaffected by recentering. Our recenter patch doesn't touch it either way, by design (it only ever resets yaw + position, same as real SteamVR) — consistent with the game doing its own one-time "calibrate forward" at startup that captures the player's full incidental head tilt as its reference "level" instead of extracting gravity-aligned yaw only, baking the error in permanently. Also dropped the user somewhere with no visible menu, "lugar raro" (odd spawn location). Normal head pitch/yaw tracking is otherwise correct — this reads as a bug in the game's own camera rig, not an xrizer/Monado issue. |
| Dark Room VR | [1394640](https://steamdb.info/app/1394640/) | ✓ | Was blocked by a silent first-run dialog exactly as suspected (a hidden "headset may not be supported" warning behind the main Steam window) — cleared once the user clicked through it. After that, reproduced identically twice: xrizer does its usual harmless throwaway session cycle, then goes quiet — headset shows nothing at all, game only ever renders to its 2D desktop window (no VR menu/options visible there either). Inside the game's own 2D window a plain black square covers the play area the whole time (its own failed VR-view placeholder, never an actual crash) — everything else in the window keeps running and responding normally, and it exits cleanly. Same failure shape as Overkill VR: reaches xrizer briefly, never opens a real VR session. |

## Untested / inconclusive

Nothing left here as of this sweep — every T073 backlog title has now been either confirmed
working, confirmed failed, or blocked on something outside this agent's reach (Dark Room
VR's dialog, since resolved).

## Not a game

| Item | AppID | SteamDB | Notes |
|---|---|---|---|
| fpsVR | [908520](https://steamdb.info/app/908520/) | ✓ | A SteamVR performance-overlay tool, not a VR title. First real attempt 2026-08-09: blocked by the launch-options trap below ("VR HMD not found" dialog, `ERROR_RUNTIME_UNAVAILABLE` in xrizer). Worth retrying with UI-set options: xrizer's `overlay.rs` implements `IVROverlay` seriously (1600+ lines, up to `IVROverlay028`), so the prognosis isn't hopeless — still pending. |

## Trap: Steam launch options edited on disk don't exist (2026-08-09)

Every VR title here needs the same launch options
(`XR_RUNTIME_JSON=... IPC_IGNORE_VERSION=1 PRESSURE_VESSEL_FILESYSTEMS_RW=... %command%`).
**Editing them into `userdata/<id>/config/localconfig.vdf` while Steam is running does
nothing and is actively dangerous**: the running client only reads that file at startup,
launches the game *without* the env vars (`ERROR_RUNTIME_UNAVAILABLE`, game falls back to
2D — how both Aircar's and fpsVR's first attempts failed, and Google Earth VR's "OpenVR
failed to initialize / InterfaceNotFound"), and then **overwrites the file from memory on
exit**, silently destroying the hand edit. The tell in a live diagnosis: the game's
`/bin/sh -c` line in `ps` has no env-var prefix even though the file on disk shows them.
Always set launch options through the Steam UI (Properties → Launch Options) — applies
immediately and survives.

**Update (2026-08-09, later the same day): there's a simpler alternative that skips this
trap entirely.** Exporting the same 3 variables (`XR_RUNTIME_JSON`, `IPC_IGNORE_VERSION`,
`PRESSURE_VESSEL_FILESYSTEMS_RW`) in the shell **before starting the `steam` client
itself**, instead of per-game Launch Options, works: verified live by reading
`/proc/<pid>/environ` on every process in the chain for a freshly-launched, never-before-
configured title (VersaillesVR) — `reaper` → `pressure-vessel`/`srt-bwrap` → `pv-adverb` →
Proton → the actual Windows `.exe` under Wine all inherited the 3 vars with zero manual
Steam UI steps, and the game reached a real `FOCUSED` OpenXR session with both controllers
on the first try. `pressure-vessel`'s sandbox evidently passes through the ambient
environment of the process that launches it (Steam), not just what's baked into a specific
game's Launch Options. This means every *future* title can skip the manual
Properties-dialog step from now on, as long as Steam itself is started with these three
vars already exported — no per-game setup needed at all.

## Trap: Steam silently re-adds SteamVR to openvrpaths.vrpath on every startup (2026-08-11)

Found setting up xrizer fresh on the everyday system (see `docs/pruebas.jsonl` T152).
Pointing `~/.config/openvr/openvrpaths.vrpath`'s `runtime` array at xrizer's build
directory (per xrizer's own README) works — until the next time the Steam client itself
starts. On every Steam startup, it silently re-adds `.../steamapps/common/SteamVR` to
the front of the `runtime` array (confirmed by diffing the file before/after a restart),
without removing the xrizer entry, but present as a second item — a real risk if OpenVR's
loader logic ever prefers the first listed runtime, or if a game specifically probes for a
`SteamVR` string in the path. **Fix: only edit `openvrpaths.vrpath` after Steam is already
running and stable, never edit it and then restart Steam** — restarting undoes exactly the
part of the edit Steam considers its own. This compounds with a second, separate
Proton-side cache: `steamapps/compatdata/<appid>/pfx/drive_c/vrclient/` (a directory
Proton creates containing `vrclient.dll`/`vrclient_x64.dll`) and a **per-title** copy of
openvrpaths at
`compatdata/<appid>/pfx/drive_c/users/steamuser/AppData/Local/openvr/openvrpaths.vrpath`
— both regenerate from whatever the Linux-side file said at the moment of that specific
game's *last* launch, not necessarily the current file content, so a stale prefix-side
cache can silently keep pointing at an old runtime even after the Linux-side file and
Steam's own env are both correct. If a fresh openvrpaths edit doesn't seem to take effect
for a Proton title specifically, delete both of those prefix-local paths before the next
launch to force a clean regeneration.

## Trap: overlapping VR game launches + background Steam downloads can hang the whole
## desktop (2026-08-09)

Launched a second title (`Emergence`) via `steam steam://rungameid/<id>` before confirming
the first one (`Back to Dinosaur Island`) had actually released the compositor — `pgrep`
showed its process gone, but that doesn't guarantee xrizer/Monado had finished tearing down
its OpenXR session cleanly. At the same time, Steam was still downloading several other
titles in the background (including the multi-GB `SteamVR` + `steamvr_environments`
depots). Net effect, live-observed by the user in the headset: **two/three sessions
visibly stacked/layered on top of each other**, not a clean single game view. Checking
`jack-in-wayland.log` afterward showed 10 `client_connected` vs. only 8
`client_disconnected` — real unclosed sessions, not just a visual glitch. System load hit
**20.84** (normally single digits), swap was in active use, and **the desktop became
unresponsive enough that the user had to force-close Steam by hand**. `monado-service`
itself was found dead afterward (crashed or OOM-killed under the load, not investigated
further) and had to be relaunched from scratch.

**Rule going forward: one VR game launch at a time, full stop.** Before launching the next
title: (1) confirm the previous game's process is completely gone (`pgrep`), (2) confirm
Monado's log shows a matching `client_disconnected` for its `client_connected`, (3) check
`free -h` and `uptime` aren't showing memory/swap pressure or an inflated load average, and
(4) check `~/.steam/steam/logs/content_log.txt` for the client still actively downloading
something — pause/let it finish first. None of this touches the cable/USB physically, but
heavy concurrent load is a real confound for any zero-touch stability test: a USB dropout
seen during a session like this can't cleanly be attributed to the cable degrading at rest,
since system-level resource starvation is a live alternative explanation.
immediately and survives.

## Non-Steam titles

Standalone DK2/DK1-era demos and tech demos that aren't Steam apps at all — no AppID, no
Steam Play sandboxing, just a Windows binary run directly under Wine. Table shape kept
consistent with the sections above (Runtime/Requirements/Status) minus the Steam-specific
columns.

| Item | Source | Status | Notes |
|---|---|---|---|
| Blade Runner 9732 (Deckard's apartment tour) | [developer site](https://br9732.quentinlengele.com/) | Not available | Was briefly on Steam (AppID [770990](https://steamdb.info/app/770990/)) but delisted January 2018 after a DMCA claim over the Blade Runner IP. User never owned it before delisting, so there's no copy to test — Steam won't offer a re-download for an app never in the library, and the dev site's public download predates confirmation it's still live. Requires HTC Vive per its listed system requirements (Windows-only, GTX 970+) — untested whether it'd even accept a WMR/xrizer OpenVR session if a copy turns up later. |

If other old standalone binaries turn up (the user recalls having several from the DK2 era),
add them here the same way — they don't need a SteamDB link, just where the binary came from.

## Reference

Full session-by-session detail for every entry above is in `docs/pruebas.jsonl` — search by
game name or by the T-numbers cited per row (T063-T086 cover this sweep as of
2026-08-08).
