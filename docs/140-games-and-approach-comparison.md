# 140 — Games tested and how our approach differs from Oasis (state at 2026-10-04)

Two ways of running the HP Reverb G2 on this Linux rig now have real hands-on data:

- **Ours** — the native Monado WMR driver (`~/vr/monado`, branch `lab-full`) with xrizer for OpenVR titles, DRM-lease Wayland launch, our NVIDIA 90 Hz patches and the operational layer in this repo (presence, telemetry, dashboard, kiosk/booth tooling). Tested August to September 2026.
- **Oasis** — Microsoft's Windows WMR driver running under Wine/Proton through Ignition, loaded by SteamVR on KDE Plasma X11, with the controllers on the host Bluetooth adapter. First end-to-end test on 2026-10-03 (docs/138; failures catalogued in docs/139; the pre-test strategy comparison is docs/108, retests docs/117 and docs/121).

The user's verdict after the Oasis night: **Oasis is the route if you need to play games today; what we built ourselves was valuable too** (and is the only one that is a booth/kiosk system).

## 1. Games tested under Oasis + SteamVR (2026-10-03/04)

| Title (AppID) | VR API | Result | Notes |
|---|---|---|---|
| Propagation VR (1363430) | OpenVR | **works** | tracking, mapping and rumble good; felt below 90 fps at maximum quality (not measured) |
| Half-Life: Alyx (546560) | OpenVR (native Linux) | **works** | first run suffered from shader compilation; later runs good, 1.6-3.5 % dropped frames across three runs, 0 reprojected; waist-in-floor until Room Setup was redone (standing only) |
| Batman: Arkham VR (502820) | OpenVR | **works** | needed a manual controller reassignment; its prefix first had to move off NTFS |
| SUPERHOT VR (617830) | OpenXR (Unity plugin) | **works** | needed the OpenXR runtime JSON pointed at SteamVR (docs/139 F6) |
| The Lab (450390) | OpenVR | **works** | 1.8 % dropped, 0 reprojected over about 7 minutes, including a hub bounce |
| I Expect You To Die (587430) | OpenVR + SteamVR Input | VR ok, **controllers dead** | Oasis ships a binding for a renamed action set; repaired with `scripts/oasis-binding-fix.py`, not yet verified in play |
| DOOM VFR (650000) | OpenVR (Wine) | **fails** | the game itself dies in `vkAcquireNextImageKHR` (`VK_ERROR_OUT_OF_DATE_KHR`) on its desktop window; cause not found |
| Blade Runner 9732 (non-Steam) | OpenVR (Unity 2017) | **starts, no VR verdict** | registers with vrserver (it never did with Monado/xrizer) but SteamVR files it as a 2D desktop game and the Steam client crashes |

Controllers: both G2 controllers on the host Bluetooth adapter, tracked and reconnecting after sleep. Not found under Oasis: SteamVR-side Windows/menu button behaviour (controller side verified), headset audio during the first game (later audio was mostly in the headset, with brief speaker flips caused by headset hub bounces).

## 2. Games tested under our Monado + xrizer stack (August to September)

Full per-title notes are in docs/23; this is the shape of it.

- **Confirmed working** (3DoF controllers or headset 6DoF, some with Xbox pad): International Space Station Tour VR, Aliens Attack VR (second attempt), Cosmic Flow, VRSailing, SUPERHOT VR, VRChat, Propagation VR, Aircar (the reference title of the rig), Google Earth VR, Tank Mechanic Simulator VR, Interkosmos, Emergence, Blast the Past, Audio Factory, VersaillesVR.
- **Image and gameplay reached, with tracking problems or still open:** Dead Herring VR, SafeZoneVR (head drift), Hellblade VR Edition, Wolfenstein: Cyberpilot (promising, tuned later with a seated-6DoF profile), Sniper Elite VR (about 45 fps), Vertical Shift.
- **Runs in 2D, never enters VR:** Dagon, Back to Dinosaur Island, Amoreon NightClub, BlazeRush, and Blade Runner 9732 (non-Steam).
- **Blocked by a named gap in our stack:** fpsVR, Microsoft Maquette, Back to Dinosaur Island 2; DOOM VFR needed OpenComposite (upstream bug).
- **Broken in reproducible xrizer/Monado ways:** Poly Runner VR, Water Bears VR, War Robots VR, IL DIVINO, Meditation VR.
- **Failed for engine/Proton reasons unrelated to the runtime:** NVIDIA VR Funhouse, InCell VR, InMind VR, Surgeon Simulator VR, World of Guns VR, Overkill VR, Welcome to Chornobayivka VR, Dark Room VR.
- **The 2026-08-20/21 sweep with full 6DoF head SLAM plus controller constellation:** of 20 titles re-tested, 17-18 came back broken the same way (30-40 fps, play space misplaced by metres); the cause was the tracking pipeline (CPU-starved SLAM, constellation ambiguity), not the games.

**Titles tested on both stacks:** Propagation VR (works on both), SUPERHOT VR (works on both; Monado had a dead left menu button until a patch, Oasis needed the OpenXR runtime JSON), DOOM VFR (blocked on Monado by OpenComposite, dies in its own Vulkan acquire under Oasis), Blade Runner 9732 (2D only on Monado, registers with SteamVR under Oasis but the Steam client crashes), Batman Arkham VR (needs manual mapping on both).

## 3. How the approaches differ

| Aspect | Ours (Monado WMR + xrizer) | Oasis (Windows driver via Ignition + SteamVR) |
|---|---|---|
| What it is | our own patched open-source driver, fully readable and upstreamable | Microsoft's real Windows driver in a Wine bridge; third-party, closed to us, moves on its authors' schedule |
| Display path | DRM lease on Wayland, 90 Hz via our NVIDIA patches | SteamVR direct mode on **X11 only** (Wayland unsupported by its author); the desktop grabs the headset output, so we need a panel guard that frees it |
| Head tracking | Basalt SLAM in software: CPU hungry, 3DoF fallback needed, drift and stale-pose problems we chased for weeks | Microsoft's tracking: user verdict "tracking perfect of everything" |
| Controller tracking | our constellation code: fragile in ambient light, ghost poses, left controller scarcity | Microsoft's tracking: worked from the first session ("anchored at first, then settled in a few seconds") |
| Controller link | headset-tunnelled Bluetooth, or host Bluetooth with our patches | **host Bluetooth adapter mandatory** (the headset's radio does not work on Linux); controllers sleep after about 5-30 s still and have to be woken |
| LED brightness | dim until our patch 0112 started the LED pulse train for host-BT controllers | bright from the start (Oasis drives the LEDs itself) |
| Haptics | report format reverse-engineered by us (docs/136); works | works under Oasis; its waveform indices not captured |
| OpenVR titles | xrizer translates OpenVR to OpenXR (legacy-input resurrection, oculus_touch profiles); each title can expose a new xrizer bug | real SteamVR: games see a standard runtime, and Alyx, Propagation, The Lab, Batman ran without runtime fixes |
| OpenXR titles | Monado native | works once the Monado runtime JSON that 49 launch options pin points at SteamVR |
| Input mapping | xrizer profiles plus our mapping notes | SteamVR Input with per-game bindings shipped by Oasis; a game update that renames an action set silently kills input (I Expect You To Die) |
| Frame delivery | 6DoF SLAM cost 30-40 fps on heavy sessions; headset-3DoF is smooth | 90 fps target held: 0.4-2.5 % dropped, 0 reprojected in the runs we measured |
| Floor / recenter | our global recenter patch; Monado assumes a flat 1.6 m floor | SteamVR Room Setup (standing only, controller on the real floor) |
| Headset audio | works (ALSA USB audio, routed by hand) | works through the same USB audio; speaker flips whenever the headset hub bounces |
| Presence, thermal telemetry, dashboard, kiosk | all ours and live | none; SteamVR kiosk settings only |
| Fragile points | cable/hub storms kill the HID read thread (!3004), Monado needs a restart | the same hub storms leave the driver with a stale HID handle (a session restart is the fix), SteamVR safe mode blocks drivers after a crash, `setcap` on the compositor launcher after each SteamVR update, desktop-game mode crashes Steam |
| Upstream path | MRs open on Monado | none; issues to Ignition possible |

Both approaches are limited by the same physical fault: the headset's USB hub bounced over 80 times in the Oasis night (docs/139 F1), and the visor-end connector reseat is still outstanding.

## 4. Recommendation

- **Playing games now:** Oasis on X11 (`~/vr/jack-in-oasis-x11.sh up`), controllers on the host adapter. Run `steam-prefix-guard.sh`, the runtime-JSON swap and the binding repair as `up` already does.
- **Booth/kiosk, Wayland, presence and telemetry, anything we must patch or upstream:** the Monado lab stack remains the only choice.
- **A hybrid** (Oasis controllers with Monado display) stays a fallback and was not needed.

## 5. Open items

Hub storms and the visor-end reseat; the DOOM VFR Vulkan acquire; the Blade Runner 9732 desktop-game crash (find the setting that stops the Desktop Game Pointer or start the exe outside Steam); verifying the repaired I Expect You To Die binding; frame rate at maximum quality; SteamVR-side menu/Windows buttons; capturing Oasis' haptic writes.
