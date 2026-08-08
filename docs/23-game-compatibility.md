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

## Broken — real, reproducible xrizer/Monado bugs

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| Poly Runner VR | [462910](https://steamdb.info/app/462910/) | ✓ | Reproducible 2/2: gets stuck permanently at OpenXR session state `READY`, spamming `app requested unknown interface "IVRCompositor_013"` in an infinite tight loop (~1300 lines/sec, ~190% CPU), never advancing or exiting on its own — killed by hand both times. Renders normally in flat 2D the whole time (confirmed physically), just never enters stereo VR. `IVRCompositor_013` itself is a confirmed dead end (never existed in any real SteamVR release, see `patches/xrizer/README.md`) — the real bug is why the client-side retry never gives up, still open. |
| Water Bears VR | [394130](https://steamdb.info/app/394130/) | ✓ | xrizer's compositor recreates the swapchain every single frame, for both eyes, forever (`recreating swapchain` spamming in `compositor.rs:1247`, ~65 cycles/sec) — never stabilizes a presentable frame, panel stays dark. Game itself is healthy: input works (trigger gives audible feedback) and it renders fine to its own flat 2D mirror the whole time. Real cause not fully isolated — likely a per-eye texture/bounds mismatch that `is_usable_swapchain()` never accepts, worth a closer look. |
| War Robots VR: The Skirmish | [672640](https://steamdb.info/app/672640/) | ✓ | Calibrates fine, then drops to backlight-only with an un-skippable "put on your VR helmet" prompt. Root cause spans two repos: xrizer never implements HMD presence/worn detection (`ShouldApplicationPause`/`IsInputAvailable` in `src/system.rs` are hardcoded stubs), and Monado's `wmr_hmd.c` already reads the real proximity sensor but never wires it into Monado's own working `XR_EXT_user_presence` support. Scoped, not started — see `patches/xrizer/README.md`. |

## Failed — unrelated to xrizer/Monado (Proton/engine-specific)

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| NVIDIA® VR Funhouse | [468700](https://steamdb.info/app/468700/) | ✓ | Fails before VR even initializes — a Proton/PhysX/CUDA error. |
| InCell VR | [396030](https://steamdb.info/app/396030/) | ✓ | Reproducible xrizer `VR_InitInternal`/`dlclose` crash, but on a native (non-Proton) process — a build/packaging issue on the game's own native Linux port, not the WMR/xrizer input or compositor path. |
| InMind VR | [343740](https://steamdb.info/app/343740/) | ✓ | Unrelated Mono runtime crash before ever touching VR. |
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
| fpsVR | [908520](https://steamdb.info/app/908520/) | ✓ | A SteamVR performance-overlay tool, not a VR title — installed but out of scope for this compatibility sweep. |

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
