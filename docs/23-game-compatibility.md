# 23 — Game compatibility status

Every VR title tried on this rig (xrizer + Monado, bypassing SteamVR entirely — see
`docs/06-known-issues.md`), with its Steam AppID and a link to SteamDB. Status reflects the
last time each title was actually looked at with the headset on: per this project's core rule
(`CLAUDE.md`, "verification is physical"), a title is not "working" until a human saw it.

**Controllers**: controller **position** tracking (constellation, via the headset's own
cameras) was verified worn on the lab branch (lab-full, 2026-08-12). Rows that describe
controllers "rotating in place at a fixed offset" predate that. The applied series in
`patches/monado/` carries only the first constellation steps, so position tracking is unreliable
from the published build (`patches/monado/README.md`, "Known issues"). It needs
`WMR_CONSTELLATION_CONTROLLERS=1` and cameras running (and `scripts/jack-in-wayland.sh`'s
`ctrl` mode). One controller can flip between two pose hypotheses 0.189 m apart, both good
optical fits (details in `docs/47`). **A title only
validates this if it draws the controllers.** Aircar, this rig's reference title, does not;
use one that renders hands.

**Two global rules from the sweeps below**: (1) the first minute of any Proton title is
shader-compile and asset-streaming noise (Aircar read 3.44% late frames cold, 0.13% warm, with
nothing changed): never judge pacing early. (2) Start the controllers BEFORE `monado-service`;
a controller powered on afterwards gets its config read but stays `<none>` in the role list.

## Working

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| International Space Station Tour VR | [797200](https://steamdb.info/app/797200/) | ✓ | Cleanest signal of the first sweep: zero warnings, `FOCUSED`, real 6DoF head tracking. Under full 6dof+constellation it joined the SLAM-starvation family (anchor age up to 2.7 s, `monado-service` at 519% CPU, 30 fps). A fresh `monado-service` halves the late-frame rate but does not fix it, so session accumulation is a contributing factor, not the root cause. Heaviest content measured (8K decode). |
| Aliens Attack VR | [932190](https://steamdb.info/app/932190/) | ✓ | Works. One `IVRChaperoneSetup_005` unknown-interface warning made one session cycle and exit; a second attempt was clean. Under 6dof+constellation (pre-pacer-fix) it showed the clearest picture of the starvation mechanism: a rotation velocity is captured once and the extrapolator keeps applying it for seconds until a fresh SLAM anchor lands. |
| Cosmic Flow: A Relaxing VR Experience | [1267950](https://steamdb.info/app/1267950/) | ✓ | Works, real 3D. Under 6dof+constellation (pre-pacer-fix): rotations and fps drop to 0, anchor age up to ~5 s. |
| VRSailing by BeTomorrow | [579050](https://steamdb.info/app/579050/) | ✓ | Works. Field-test title for the global recenter patch (`patches/xrizer/0001`): about 4 m off its play-space centre, recentres correctly with height preserved. 30 fps under 6dof+constellation (pre-pacer-fix). |
| SUPERHOT VR | [617830](https://steamdb.info/app/617830/) | ✓ | Trigger, grab and hand tracking work. The menu button was dead; fixed for the **left** controller by `patches/xrizer/0002` (`Menu` is left-only on the `oculus_touch` profile, as on real Touch hardware). |
| VRChat | [438100](https://steamdb.info/app/438100/) | ✓ | Works, reaches `FOCUSED`, real gameplay; EasyAntiCheat loads clean under Proton. A first blank attempt was a DP/panel dropout, not VRChat. Mildest case under 6dof+constellation (30 fps, menu correctly placed, no flying away). |
| Propagation VR | [1363430](https://steamdb.info/app/1363430/) | ✓ | Best signal of the non-original set: works, including exiting from inside via the controllers (no patch needed). Controllers powered on after Monado stayed `<none>` until a full restart. |
| Aircar | [1073390](https://steamdb.info/app/1073390/) | ✓ | **Reference title.** 100% functional with VR sticks or an Xbox pad interchangeably; 89-90 fps at `4320x2160@90` with the default 140% render scale (3024x3024 per eye), 0.13% late frames once warm; audio routes to the headset (PipeWire stream-restore remembers it per application). `WMR_STICK_DEADZONE=0.15` (patch 0008) is required: WMR controllers carry no stick-centre calibration, and the drift was first wrongly blamed on the Xbox pad. See "Aircar findings" below. |
| Google Earth VR | [348250](https://steamdb.info/app/348250/) | ✓ | Works well on 3dof (every input works, confirmed by the in-game controller model). On the old diverging-SLAM stack it was unusable. With the current 6dof stack: "almost usable", left controller positionally tracked, **right controller registered but not positionally tracked** (unexplained asymmetry), occasional "below the map" spawn. Steam's overlay reads a steady 45 fps while compositor-side pacing is clean (0.07-0.15% late): the app is probably rendering at half rate while Monado presents at 90 Hz. About 2 minutes to a usable scene (map-tile streaming, not GPU/tracking bound). |
| Dead Herring VR | [1498490](https://steamdb.info/app/1498490/) | ✓ | Real VR image and gameplay. This title carries the decisive three-way tracking-mode A/B: the 45 fps ceiling survives 6dof+constellation, 6dof alone and 3dof alone, so it is not caused by the tracking stack; "flying away" (anchor age 128→157 ms, zero `det(Q1Jl)==0` divergence events) appears only under the heaviest configuration. After the pacer fix: 80-90 fps, no relocation. Has a 2D debug map mode on the desktop window. |
| Hellblade: Senua's Sacrifice VR Edition | [747350](https://steamdb.info/app/747350/) | ✓ | A real VR edition, not vanilla Hellblade (24.7 GB). First look: promising, steady 45 fps (pre-pacer-fix), good head guidance. Deserves a full pass. |
| Wolfenstein: Cyberpilot | [1056970](https://steamdb.info/app/1056970/) | ✓ | Native Bethesda id Tech VR title: real 6dof head tracking and a working out-of-tracking-volume warning. **Status: testing, not guest-ready.** Details below the table. |
| Sniper Elite VR | [752480](https://steamdb.info/app/752480/) | ✓ | After the pacer fix: 87-89 fps, GPU not limiting. Controllers are tracked by the driver (`constellation sample … matched_blobs=6 reproj_err_px=0.17`) yet the in-game pointer stays immobile and the title waits for a "recalibrate controls" confirmation that never arrives: an xrizer-to-title binding problem, not investigated. Needs `WMR_CONSTELLATION_CONTROLLERS=1` exported explicitly (`6dof` alone does not enable it; only `ctrl` implies it). The world spawns too high (known title trait, hence its calibration step). |
| Vertical Shift | [1807480](https://steamdb.info/app/1807480/) | ✓ | 30 fps and mispositioned before the pacer fix; 66-77 fps afterwards, well positioned, no drift. Controllers never appear in this title in any session: inconclusive, not counted against it. |
| Transmissions: Element 120 | [365300](https://steamdb.info/app/365300/) | ✓ | Mixed. One attempt hit the known companion USB2 drop (continuous `os_hid_read returned -1`, 2/5 census); after a replug and restart two launches exited in 2-3 s with no `client_connected`. Not root-caused. |
| Tank Mechanic Simulator VR | [1463010](https://steamdb.info/app/1463010/) | ✓ | Works, excellent image, 3dof controllers (2026-08-09). Shows a harmless "does not appear to support headset" warning on first launch (click through). Under 6dof+constellation it has a second, distinct problem: 405 `0xc0000005` access violations in one burst (about 30x any other title), which plausibly explains hands not pointing where they should. |
| Aperture Hand Lab | [868020](https://steamdb.info/app/868020/) | ✓ | Valve's free hand-tracking demo (binary `Knux.exe`). A real session was reached, then an in-game "please relocate to center" message and a drop to 2D, traced to the known companion USB2 drop. 30 fps (pre-pacer-fix). |
| SafeZoneVR | [1701090](https://steamdb.info/app/1701090/) | ✓ | Image and gameplay work. Two sessions showed two different position-anchoring symptoms (drift left; spawn about 10 m too high), both with zero `det(Q1Jl)==0` events, so neither is the known divergence bug. Compositor pacing 3.67% late (median one full 11.11 ms slot). The recenter shortcut did not fire in a ~61 s session but fired correctly on VRSailing with the same build: a hold that short never gets 3 s. |
| Interkosmos | [579110](https://steamdb.info/app/579110/) | ✓ | Works, 3dof hands, video perfect. Under 6dof+constellation on a genuinely fresh `monado-service`: anchor age still 921/2341 ms (374% CPU), 30 fps varying to 40 at a fixed spot, which fits variable per-frame SLAM/optflow cost better than a fixed engine cap. |
| Emergence | [1337820](https://steamdb.info/app/1337820/) | ✓ | Works with VR sticks, 0.41% late frames warm. Audio needs routing to the headset by hand. Under 6dof+constellation: rotations, 45 fps, anchor age spikes to 4.9 s. |
| Blast the Past | [943170](https://steamdb.info/app/943170/) | ✓ | Cleanest pacing measured in 3dof (0.00-0.09% late). Under full 6dof+constellation: 4.0-7.2% late at 3024x3024 (better than the 7.2-11.6% 6dof baseline), head 6dof good, some turn delay. 147 W (70%) vs 210 W was indistinguishable: the late frames are CPU/scheduling, not watts. **Title posture matters for hands**: an aim-low title keeps the controllers under the camera FOV cone, so they park at their last solve with IMU-only orientation while hands-up content tracks clean. |
| Audio Factory | [722590](https://steamdb.info/app/722590/) | ✓ | Works. A too-high seat and a 3dof-only controller were not the title's fault (Monado assumes a flat 1.6 m floor below the headset at startup; project-wide). 30 fps under 6dof+constellation (pre-pacer-fix). |
| VersaillesVR \| The Palace is yours | [1098190](https://steamdb.info/app/1098190/) | ✓ | Works, sound in the headset, both sticks registering, 0.37% late frames warm. Started at about 2 fps and settled on its own (the most extreme warm-up case measured). |
| Steam 360 Video Player | [613220](https://steamdb.info/app/613220/) | ✓ | Reaches VR with controllers visible but renders black for lack of test content (structurally fine, verification incomplete). 35 fps under 6dof+constellation, no runaway extrapolation that run. |
| Reelease | [3609930](https://steamdb.info/app/3609930/) | ✓ | Reaches VR with controller input and a laser pointer; broken-family symptoms (flying) under 6dof+constellation. Revisit after the fix. |

**Cyberpilot details.**

- Prefix on the NTFS library: `compatdata/1056970` hit the `dosdevices/c:` `Errno 22` (ntfs-3g refuses the symlink; recipe in `docs/70`); the prefix was relocated via symlink.
- **Unattended runs only ever see a throwaway `BEGIN_SESSION`→`END_SESSION` probe.** The real second `BEGIN_SESSION` follows within ~1 s and opens only once the headset is actually worn (wear sensor), so unattended benchmark windows never see the real session.
- **Window state matters**: fullscreen+focused locked to a hard 30.00 fps (`Fake pacer fell behind` spam), windowed+focused was noisy 60-89 fps, an unfocused/background state ran about 90 fps when idle. A claim that minimizing the window fixes it was retracted after a careful retest (never above a noisy 53-67 fps); the GPU cap may be the real ~60 fps ceiling for this heavy title. Measure windowed versus fullscreen per title.
- **Seated-6dof head recipe** (patch 0097) lives in `scripts/vr-launcher.py`'s `TITLE_PROFILES["1056970"]`: `SLAM_PREDICTION_TYPE=2`, `SLAM_PRED_FREEZE_POSITION=1`, `SLAM_PRED_NECK_ARM_MM=150`, `SLAM_CORRECTION_SPREAD_MS=50`, plus an explicit `WMR_CONSTELLATION_CONTROLLERS=1` (this title needs tracked hands). A launcher bug was fixed on the way: profile selection was a lookup (`TITLE_PROFILES.get(appid, PROFILE_DEFAULT)`), so a partial profile silently dropped positional controller tracking; it is now a merge, `{**PROFILE_DEFAULT, **TITLE_PROFILES.get(appid, {})}`. Reset: hold the right controller's "shift" button ~3 s.
- A/B: constellation off gave hands "anywhere" and drift; recipe + constellation on gave hands roughly right, markedly less drift, playable; residual ~2 m bounded drift on fast head turns.
- **Performance**: in gameplay ~60 fps with 4800-6000 `Fake pacer fell behind` lines per session (the "~90 fps" seen earlier was menu-only). Levers for 90, in order: (1) render resolution via `XRT_COMPOSITOR_SCALE_PERCENTAGE` (default 140% = 3024²/eye; 100 measured 168 W → 90 W), not `XRT_COMPOSITOR_DESIRED_MODE` (cosmetic scanout only) and not the in-game resolution dropdown (inert: xrizer's `IVRSettings` is a stub), while the title's own supersampling toggle does work; (2) the GPU power cap (a sweep is still pending); (3) window visibility. FOV crop is not a lever (no Monado option). Measure only with `U_PACING_APP_LOG=debug`, else `Delivered frame` reads 0 while rendering.
- After the pacer fix, with constellation on: 70-80 fps (a lower bound: a second title was still rendering behind it, see "Killing the Steam wrapper" in `CLAUDE.md`). Residuals are the known ones: controller position jitter (`docs/58`), stick sensitivity (per-title deadzone tuning candidate) and head-pose latency/vertical settle (SLAM anchor age ~150 ms under load). Controllers auto-sleep during the ~100 s load and re-attach on power-on.
- Prewarm A/B (cache-cold, then RAM): RAM mode reached the first real frame at ~22 s versus ~28 s and a cleaner climb to 90 fps; once steady, both converged to the same ~62-66 fps. Prewarm buys only the load transition.

### Aircar findings (apply to every title)

- **6dof costs frames, and it is the SLAM**: 7.2-11.6% late in 6dof versus 2.8% in 3dof (50-70 fps versus 80-90). Basalt runs single-threaded and pins one whole core at 99.4% while the machine sits at 26%. **More threads is worse**, measured: `num-threads=3` gave four monado threads at 94-99% and 10.8-11.6% late. `num-threads=1` stays the default (`SLAM_THREADS`). Constellation is not the cost (off: 3.44% and 7.22% in back-to-back windows, so run-to-run variance exceeds the effect). Use three windows minimum per data point. "The camera snaps back about once a second, only when turning" is dropped frames: a missed slot makes the compositor re-show the previous frame, invisible at rest and obvious mid-turn.
- **Recentering**: the Xbox pad's A button recenters the view in-game. SLAM position drift is 0.37 m/min with the headset static (0.61 m over 100 s), so long sessions otherwise end "outside the ship". The SLAM origin lands wherever the headset sits when the service starts: start the service with the headset worn in the play position.
- **Stick drift resolved** with `WMR_STICK_DEADZONE=0.15` (launcher default), verified with the game's own in-cockpit numeric axis readout; `WMR_STICK_AUTOCENTER` (0070, unapplied in `patches/monado/unapplied/`, not in the published build) remains an optional refinement.
- **Orientation drift is not a SLAM problem**: it reproduces in 3dof. Root cause: `m_imu_3dof` has a gyro-bias estimator that nothing calls (`gyro_biasing()` returns unless a debug-GUI checkbox is set). Resting controllers drifted left 72 °/min, right 20 °/min (same rates in a different resting orientation, so plain gyro bias). Gravity corrects pitch/roll but has no yaw reference, so yaw is what is noticed. `patches/monado/0031` fires the estimator automatically when the device is still (inter-controller drift 18.8 → 8.9 °/min). The remaining resting 20-70 °/min was different: about 30 s after a G2 controller stops moving, its firmware keeps the packet stream alive but **zeroes the IMU fields**, and the calibration pipeline turned those zeros into each device's factory bias vector, a fake constant rotation. Patches 0033-0035 (estimator smoothing, prediction cap, zeroed-packet detection) take a resting controller to +0.00 °/min (`scripts/drift-measure.py`). In-hand drift during play is unmeasured on the new binary.
- **Seated 6dof exam, run #1** (head SLAM, constellation off, Xbox pad, GPU at a 70% cap): render side met (88.9-90.05 fps in four 3×20 s windows, 0 late compositor frames in 6×30 s, 58-82% GPU at 174 W). Head SLAM not met in a dim room: three accelerating runaways in the first 75 s, ~4 m of drift in 12 min seated. Basalt throughput was normal (not CPU starvation): it is the dim room (`docs/56`). Not certified: a normal-light run of 30+ min worn is still needed.

## Runs in 2D but never enters VR — opens an XR session and abandons it

These titles **do** talk to OpenVR: they create a session and drop it inside the same
millisecond while the process stays alive and plays flat on the desktop. Identical signature:

```
OpenXR session state changed: SYNCHRONIZED -> STOPPING -> IDLE -> EXITING
```

That is neither a crash nor a plumbing gap. The likely cause is a missing per-title launch
flag; **`steam -applaunch <id> <args>` does NOT forward arguments** (verified: the game's
cmdline ends at the .exe), so it has to go in the launch options as `%command% -vr` or
whatever the title expects, which needs Steam closed. Untested as a batch.

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| Dagon | [1481400](https://steamdb.info/app/1481400/) | ✓ | Runs perfectly in 2D; no in-game way to switch to VR was found. |
| Back to Dinosaur Island | [412940](https://steamdb.info/app/412940/) | ✓ | Runs fine in 2D, never takes the headset. CryEngine, like its sequel, but this one does not crash. |
| Amoreon NightClub | [701100](https://steamdb.info/app/701100/) | ✓ | 2D only, appears to run fine. |
| BlazeRush | [302710](https://steamdb.info/app/302710/) | ✓ | The **native Linux build exits in under a second** (the install carries a native `blazerush` and a Windows `game.exe`). Its VR support belongs to the Windows build: testing needs forcing Proton from the Steam UI, not yet done. |

## Blocked by a named gap in our own stack

Not compatibility problems: each is a specific missing piece, located with file and line.

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| fpsVR | [908520](https://steamdb.info/app/908520/) | ✓ | **xrizer does not support OpenVR overlay applications at all** (`Unsupported application type: Overlay` from `xrizer::clientcore`). No overlay app can work (fpsVR, OVR Toolkit, none): a missing feature, not a misconfiguration. Its first failure was the launch-options gap (`ERROR_RUNTIME_UNAVAILABLE`), which only revealed this. It is a Windows-only performance overlay, not a VR title. |
| Microsoft Maquette | [967490](https://steamdb.info/app/967490/) | ✓ | Reaches `FOCUSED` with both controllers, then its readiness checklist fails on "controllers on" and "controllers tracking". **The log points at the chaperone, not tracking**: `GetPlayAreaSize` and `GetPlayAreaRect` are unimplemented (`src/chaperone.rs:65` and `:58`). Several right-hand bindings are also rejected (`/y/click`, `/x/click`, `/trigger/value`) because X/Y are left-hand only on `oculus/touch_controller`, the same class as SUPERHOT's Menu button. Reproduces unchanged under 6dof+constellation. |
| Back to Dinosaur Island 2 | [452640](https://steamdb.info/app/452640/) | ✓ | Crashes on launch: CryEngine's "crash handler not found", then "bug submission failed" (the reporter failing after the game died). The XR session opens and exits in the same millisecond. |

## Broken — real, reproducible xrizer/Monado bugs

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| Poly Runner VR | [462910](https://steamdb.info/app/462910/) | ✓ | Reproducible 2/2: stuck permanently at session state `READY`, spamming `app requested unknown interface "IVRCompositor_013"` (~1300 lines/s, ~190% CPU), renders flat 2D, never enters stereo VR. `IVRCompositor_013` never existed in any real SteamVR release (`patches/xrizer/README.md`); the open question is why the client-side retry never gives up. |
| Water Bears VR | [394130](https://steamdb.info/app/394130/) | ✓ | xrizer's compositor recreates the swapchain every frame for both eyes, forever (`recreating swapchain`, `compositor.rs:1247`, ~65 cycles/s); the panel stays dark while the game's 2D mirror and input work. Likely a per-eye texture/bounds mismatch that `is_usable_swapchain()` never accepts. Reproduces unchanged under 6dof+constellation. |
| War Robots VR: The Skirmish | [672640](https://steamdb.info/app/672640/) | ✓ | Calibrates, then drops to backlight-only with an un-skippable "put on your VR helmet" prompt. Two repos are involved: stock xrizer has no HMD presence/worn detection (`ShouldApplicationPause`/`IsInputAvailable` in `src/system.rs` are stubs; `patches/xrizer/0003` adds real presence) and Monado's `wmr_hmd.c` reads the real proximity sensor, which Monado patches 0075/0087/0116 (`WMR_USER_PRESENCE`) wire to `XR_EXT_user_presence`. Retest after Monado 0075/0087/0116 and xrizer 0003. |
| IL DIVINO - Michelangelo's Sistine Ceiling in VR | [1165850](https://steamdb.info/app/1165850/) | ✓ | First run: audio in the headset but no image (backlight only) with `FOCUSED` and both controllers; render path, not investigated. Later run: the no-image bug did not reproduce, but fps degraded within a session (45→30) and turning caused strobing re-centering. May be closer to working than the first verdict suggested. |
| Meditation VR | [1301850](https://steamdb.info/app/1301850/) | ✓ | All black in the headset. Log-clean (`FOCUSED`, `oculus/touch_controller`, one harmless `IVRExtendedDisplay_001` probe): "session healthy, renders nothing visible". One attempt, not investigated. |
| Aircar and Aliens Attack VR, **on the everyday X11/KDE system** | [1073390](https://steamdb.info/app/1073390/) / [932190](https://steamdb.info/app/932190/) | ✓ | Not a contradiction of the working rows above (those are the lab machine: GNOME/Wayland/90 Hz/patched). On a fresh xrizer build on the everyday system (KDE/X11/60 Hz/unpatched) both stay flat 2D with the headset panel powered but blank, after several launch-plumbing fixes. Aircar's `openvr_api.dll` loads and reaches `vrclient_x64.dll` (the OpenVR init handshake is attempted and fails) and cycles load/unload four times before exiting; Aliens Attack never opens an xrizer log at all. Reads as a general everyday-system xrizer regression, not title-specific; if the `PROTON_LOG` trace matches, stop chasing it there and validate on the lab machine. Public NVIDIA + Proton + OpenXR bug reports exist (`ValveSoftware/steam-runtime#782`, `ValveSoftware/Proton#7228`), not symptom-for-symptom identical. |

## Failed — unrelated to xrizer/Monado (Proton/engine-specific)

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| NVIDIA® VR Funhouse | [468700](https://steamdb.info/app/468700/) | ✓ | The first verdict was recorded under launch options **missing `PRESSURE_VESSEL_FILESYSTEMS_RW`** (the game could not see Monado's socket from inside pressure-vessel). With the complete recipe it reaches the runtime and dies at its OWN CUDA gate: the "GPU PhysX must be enabled in the NVIDIA Control Panel" dialog is a string in `UE4Game-Win64-Shipping.exe`, and the real check is FleX's `flexInit` → `GetProcAddress(cuInit)` on `nvcuda.dll`. It fails because Proton Experimental deliberately ships a zero-export stub `nvcuda.dll` (35,867 B, forced via `dlloverrides nvcuda='b'` in its `proton` script). NVAPI is fine (dxvk-nvapi `NvAPI_Initialize: OK`); `winetricks physx` cannot fix it and a user `WINEDLLOVERRIDES=nvcuda=n` cannot beat Proton's appended override. **Lever to try**: GE-Proton11-5's bundled SveSop nvidia-libs CUDA relay: (1) preflight, stock 11-5 aborts prefix setup otherwise: `ln -s ../nvapi '~/.steam/debian-installation/compatibilitytools.d/GE-Proton11-5-x86_64/files/lib/wine/nvidia-libs/nvapi'`; (2) with Steam fully shut down, switch 468700 to GE-Proton11-5 via `CompatToolMapping` in `config.vdf` (procedure in `docs/70`) with a fresh prefix; (3) prepend `PROTON_NVIDIA_NVCUDA=1` to the launch options, **through the Steam UI only**. Acceptance: prefix `system32/nvcuda.dll` becomes an ~830 KB ELF (`nm -D` lists `wine_cuInit`; ignore Wine's hardcoded "builtin" in loaddll lines) and no FleX `cuInit missing` message. This removes only the gate; whether GPU FleX/PhysX then runs under Proton is unknown (no public Linux report of Funhouse past this dialog), and there is no CPU fallback. |
| InCell VR | [396030](https://steamdb.info/app/396030/) | ✓ | A **native Linux Unity build** that calls Oculus's `OVRPlugin` first; `libOVRPlugin.so` has never existed on Linux, so Mono throws `DllNotFoundException` and the process aborts in under a second. Nothing here ever reached VR. `tools/ovrplugin-stub/` (a 78-symbol stub answering "no HMD", installed into `InCell_Data/Plugins/x86_64/`, not `Mono/x86_64/`) moves the failure forward: the stack continues through `SteamVR.CreateInstance` → `OpenVR.Init` → `OpenVRInterop.InitInternal`, where it now dies. Next suspect: the game's own bundled OpenVR 1.0.x `libopenvr_api.so` ABI against xrizer. |
| InMind VR | [343740](https://steamdb.info/app/343740/) | ✓ | Same studio, same native Unity build, same `DllNotFoundException: OVRPlugin`; the earlier "unrelated Mono crash" was the symptom of the missing library. With the stub the exception is gone and the game boots and plays music. Fullscreen it dies in seconds under `XError: BadMatch` (Unity 5.3-era fullscreen vs XWayland); windowed (`-screen-fullscreen 0`) it survives but spams `NullReferenceException` in `OVRManager.Update`, renders black and exits after ~20 s. Unlike InCell this build has **no OpenVR plugin**: its Linux VR path is Oculus-only, so real VR needs the parked LibOVR→OpenVR shim, not another stub tweak. |
| Surgeon Simulator VR: Meet The Medic | [457420](https://steamdb.info/app/457420/) | ✓ | Not a crash loop: the game runs in 2D at 450 fps with a "you need a VR headset" warning. A named xrizer gap: it probes **`IVRSystem_007`** (a real 2014-era interface, unlike `IVRCompositor_013`) four times, xrizer does not implement it, so the game concludes there is no VR. Fixable by implementing the legacy interface: a real project. |
| World of Guns: VR | [1111760](https://steamdb.info/app/1111760/) | ✓ | xrizer initializes and reaches `SYNCHRONIZED`, then the game abandons the session 17 ms later (the Dagon class signature) and keeps running in 2D at 144 fps **showing its VR UI** with a laser pointer that never moves. The binary is already the VR one (`disasm_vr.exe`), so it is not a missing `-vr` flag. |
| Overkill VR | [518720](https://steamdb.info/app/518720/) | ✓ | A throwaway session cycle at launch (READY→EXITING in 18 ms), then silence: no second real session even after the loading window. The desktop mirror is a plain white screen, the headset shows nothing. |
| Welcome to Chornobayivka VR | [2064150](https://steamdb.info/app/2064150/) | ✓ | Reaches `FOCUSED`, real 3D, controllers load on both hands. On the lab 6dof+constellation stack: works, ~50 fps, head tracking good. The game's own camera has a fixed **roll** (world tilted sideways) from launch that recentering does not touch, consistent with its startup "calibrate forward" capturing the player's incidental head tilt as "level": a bug in the game's camera rig. Under later 6dof+constellation (pre-pacer-fix): flying away, 30 fps (=90/3), anchor age 111-176 ms, zero divergence events. Weapon-grab controls are fiddly in the game itself; separate "hard because the game is hard" from "broken here". |
| Dark Room VR | [1394640](https://steamdb.info/app/1394640/) | ✓ | A silent first-run "headset may not be supported" dialog hides behind the main Steam window until clicked through. After that xrizer does its harmless throwaway session cycle and goes quiet; the headset shows nothing and the 2D window shows a black square over the play area. Same shape as Overkill VR. |

## Untested / inconclusive

| Game | AppID | SteamDB | Notes |
|---|---|---|---|
| Arkio | [1053760](https://steamdb.info/app/1053760/) | ✓ | A real session connected (~150 ms, compositor timing clean: gpu 3.3 ms median) and the app crashed on VR init; `monado-service` stayed alive. Reads as app-side. |
| Playable Alpha Demo | [3494600](https://steamdb.info/app/3494600/) | ✓ | Stuck on a ZX Spectrum-style loading screen, identical on a fresh Monado. The game process never registered a named `client_connected`; only Proton's and Steam's OpenXR self-probes did, and the first saw a severe pacer stall (2194 periods in one jump). Retest once the pacer jumps are understood. |

## Not a game

| Item | AppID | SteamDB | Notes |
|---|---|---|---|
| SteamVR | [250820](https://steamdb.info/app/250820/) | ✓ | **Installed, and deliberately not used.** xrizer reimplements OpenVR on top of OpenXR precisely because SteamVR's `vrmonitor` does not work here (`docs/06`). Steam also re-adds it to `openvrpaths.vrpath` on every startup (see the trap below). |
| Windows Mixed Reality for SteamVR | [719950](https://steamdb.info/app/719950/) | ✓ | Microsoft's Windows-only WMR driver plugin for SteamVR; Monado's `drv_wmr` does that job natively. Listed so "did we try it?" has an answer. |
| OpenVR Benchmark | [955610](https://steamdb.info/app/955610/) | ✓ | Standalone GPU stress benchmark (`OpenVRBenchmark.exe`); runs through the stack. **Its score is runtime-capped here, not a GPU measurement**: identical 111.11 avg at both 3024² and 2160² render targets means the frame loop is granted `xrWaitFrame` every exactly 9.00 ms by Monado's app pacer (111 fps rendered, 90 displayed). `XRT_COMPOSITOR_SCALE_PERCENTAGE=100` is the universal-resolution knob (2160×2160 confirmed in its Info panel). **Windows reference** (same G2, same machine, Oasis + SteamVR 2.16.7, 3060 Ti): pass 1 = **26.02 avg / 20.39 (1%) / 19.70 (0.3%)** at 2576×2520@90; pass 2 in the same process = 354.77 FPS, not physical at 6.49 Mpx, so the second run in one process is broken in the benchmark itself (on Linux it wedges instead). **Standing rule: one run per process lifetime, restart between measurements.** It also **mislabels the headset on the Oasis path** ("Oculus Quest2" for a G2), so the per-GPU+headset leaderboard would file results under the wrong hardware. A valid head-to-head is pass 1 versus pass 1 at the same render target (Linux at 2576×2520 via `XRT_COMPOSITOR_SCALE_PERCENTAGE`, first run only). Its supersampling "fix" buttons spawn an Overlay helper, hitting xrizer's no-overlay gap. |

## Trap: Steam launch options edited on disk don't exist

Every VR title here needs the same launch options
(`XR_RUNTIME_JSON=... IPC_IGNORE_VERSION=1 PRESSURE_VESSEL_FILESYSTEMS_RW=... %command%`).
**Editing them into `userdata/<id>/config/localconfig.vdf` while Steam is running does nothing
and is dangerous**: the running client reads that file only at startup, launches the game
*without* the env vars (`ERROR_RUNTIME_UNAVAILABLE`, silent fallback to 2D, "OpenVR failed to
initialize / InterfaceNotFound"), and then **overwrites the file from memory on exit**. The tell:
the game's `/bin/sh -c` line in `ps` has no env-var prefix even though the file shows them.
Set launch options through the Steam UI (Properties → Launch Options).

**Simpler alternative that skips the trap**: export the same three variables
(`XR_RUNTIME_JSON`, `IPC_IGNORE_VERSION`, `PRESSURE_VESSEL_FILESYSTEMS_RW`) in the shell
**before starting the `steam` client itself**. Verified by reading `/proc/<pid>/environ` along the
whole chain for a never-configured title (`reaper` → `pressure-vessel`/`srt-bwrap` →
`pv-adverb` → Proton → the Windows `.exe`): all inherited the three variables and the game
reached a real `FOCUSED` session with both controllers on the first try. pressure-vessel passes
through the ambient environment of the process that launches it, so every future title can skip
the Properties step.

## Trap: Steam silently re-adds SteamVR to openvrpaths.vrpath on every startup

Pointing `~/.config/openvr/openvrpaths.vrpath`'s `runtime` array at xrizer's build directory
(per xrizer's README) works until the Steam client next starts: on every startup it re-adds
`.../steamapps/common/SteamVR` to the front of the array (confirmed by diffing before/after).
A game that runs but shows nothing in the headset is usually this: OpenVR loads SteamVR's real
`vrclient` instead of xrizer's shim, gets `VRInitError_Init_InterfaceNotFound` (visible in the
game's own engine log) and falls back to flat rendering. Run
`scripts/sanity-check.sh soft --fix-vrpath` (it reorders `runtime[]` and backs up the original),
then restart Steam; a running game will not pick up the new order. A second, separate Proton-side
cache compounds it: `steamapps/compatdata/<appid>/pfx/drive_c/vrclient/` and a **per-title** copy
of openvrpaths at `compatdata/<appid>/pfx/drive_c/users/steamuser/AppData/Local/openvr/openvrpaths.vrpath`
regenerate from whatever the Linux-side file said at that title's *last* launch. If a fresh edit
does not take effect for a Proton title, delete both prefix-local paths before the next launch.

## Trap: overlapping VR game launches plus background Steam downloads can hang the desktop

Launching a second title via `steam steam://rungameid/<id>` before the first had released the
compositor (its process was gone, but xrizer/Monado had not finished tearing down the OpenXR
session), while Steam was still downloading multi-GB depots, stacked two or three sessions on top
of each other. `jack-in-wayland.log` showed 10 `client_connected` against 8 `client_disconnected`,
system load hit 20.84, swap was in use, the desktop became unresponsive and `monado-service`
died. **Rule: one VR game launch at a time.** Before the next title: (1) the previous game's
process is completely gone (`scripts/game-stop.py status`), (2) Monado's log shows a matching
`client_disconnected`, (3) `free -h` and `uptime` show no memory/swap pressure, (4)
`~/.steam/steam/logs/content_log.txt` shows no active download. Heavy concurrent load is also a
real confound for any stability test: a USB dropout during such a session cannot be attributed to
the cable.

## Non-Steam titles

Standalone demos that are not Steam apps: no AppID, no Steam Play sandboxing, a Windows binary run
directly under Wine.

| Item | Source | Status | Notes |
|---|---|---|---|
| Blade Runner 9732 (Deckard's apartment tour) | [developer site](https://br9732.quentinlengele.com/) | Not on Steam | Unity 2017.3.1f1, ships its own `openvr_api.dll`. **Runs in 2D, never enters VR** when launched directly via `proton run`: switching to VR (menu or `-vrmode openvr`) leaves the headset on backlight and **no client ever connects to Monado**. The game's `openvr_api.dll` and Proton's `vrclient_x64.so` load, but **`libxrizer.so` is never loaded** (checked in `/proc/<pid>/maps`) although xrizer's layout and `openvrpaths.vrpath` are correct: it is the **launch method**, since every working title goes through Steam (pressure-vessel and the Steam environment the vrclient shim expects). Next: add it as a non-Steam shortcut in the Steam UI with the usual launch-option recipe. It is plain OpenVR, so it is also worth a retest under SteamVR + Oasis. |

## The 20-title sweep with full 6dof+constellation, and what it showed

20 titles were re-tested in one session with full 6dof+constellation and full Proton/Wine logging, to
count how many genuinely DIFFERENT problems sit in the pile of broken-looking titles.

**API surface does not distinguish sub-categories of the tracking bug.** Grepping every saved log
for `IVR[A-Za-z]+_[0-9]+`: titles hit by the SLAM/constellation starvation span
`IVRClientCore_002/003`, `IVRChaperoneSetup_005`, `IVRSystem_012/015/019`, `IVRExtendedDisplay_001`
and `IVRSettings_001` in every combination. The bug lives in the tracking pipeline, below every
OpenVR interface.

**One outlier found by exception counts**: `grep -ic "unhandled exception\|backtrace:"` sits at 9-18 for
every title except **Tank Mechanic Simulator VR (1463010): 405**, almost all `0xc0000005`
in one burst. That is a second, distinct problem on top of the shared tracking issue.

**Problem categories, one exemplar each:**

| Problem | Exemplar | Mechanism | Other titles with the same symptom |
|---|---|---|---|
| SLAM/constellation CPU starvation → fps ceiling + runaway extrapolation | **Dead Herring VR** | Anchor age spikes to seconds under CPU load (`monado-service` 370-520%), also on a fresh restart | ISS Tour VR, SafeZoneVR, Chornobayivka VR, Cosmic Flow, Interkosmos, Emergence, SUPERHOT VR, VRChat, VRSailing, Propagation VR, VersaillesVR, Audio Factory, Blast the Past, Google Earth VR, Aliens Attack VR, Reelease |
| Same tracking bug + a second internal crash storm | **Tank Mechanic Simulator VR** | 405 `0xc0000005` in one burst, ~30x other titles | — |
| xrizer swapchain never stabilizes | **Water Bears VR** | `recreating swapchain` loop, `compositor.rs:1247` | — |
| xrizer has no HMD presence/worn detection | **War Robots VR** | Wiring now exists (Monado 0075/0087/0116, xrizer 0003); the title needs a retest | — |
| xrizer chaperone stub | **Microsoft Maquette** | `GetPlayAreaSize`/`Rect` unimplemented; only title whose readiness check needs the chaperone | — |
| xrizer has no OpenVR overlay support | fpsVR | `overlay.rs` gap, scoped | — |
| GPU/CPU stress baseline | **OpenVR Benchmark** | 18.3 fps at 3024x3024 on the full stack | — |

That is **7 real, distinct problems** behind 20 broken-looking titles.

### The fps ceiling was the app pacer, not the GPU, tracking or engines

Titles settled on different submultiples of 90 (30, 40, 45), which suggested a per-engine ceiling.
Measured with the real instrument (count of `Delivered frame` lines with `U_PACING_APP_LOG=debug`,
`docs/32`), Dead Herring VR, fresh `monado-service` each run:

| Run | Config | app fps | GPU (nvidia-smi) |
|---|---|---|---|
| A | pipelined pacer, render scale 140% | **44** | 168 W / 54% |
| B | `XRT_COMPOSITOR_SCALE_PERCENTAGE=100` (half the pixels) | **45** | 90 W / 39%, **not GPU-bound** |
| C | serial pacer (`VR_PIPELINED=0`) | 63 | — |
| D | pipelined + patch 0092 (promise/gate bookkeeping) | 58 | — |
| E | D + `U_PACING_APP_USE_MIN_FRAME_PERIOD=true` | **89-90** | 161 W / 54% |

Mechanism, two layers: (1) the pacer's `gpu` column is structurally ~1 display period (the
multi-compositor's wait thread only starts waiting on frame N's fence after frame N-1 was consumed,
so `gpu_done` is quantised to the compositor tick). `calc_app_period()` doubles the app period
whenever that column exceeds 11.11 ms and flaps on that edge: 37-42% of frames at `period: 22.22`
→ 58-63 fps. (2) The pipelined model required the next promise to lie past the previous *shifted*
promise and then added the shift again → promises two periods apart by construction → a hard 45 fps
whenever pipelined engaged. A title whose `draw` also tripped the doubling landed on 30 (=90/3):
the per-title 30/40/45 submultiples are the same bug through different stages, not engine age.
**Fix shipped**: patch 0092 plus the launcher default `U_PACING_APP_USE_MIN_FRAME_PERIOD=true`
(`VR_MIN_PERIOD=0` reverts). The companion-drop "flying away" relocation was a separate bug fixed
the same session (`docs/06`, "The wearer gets relocated on every companion drop").

**First retests under the new defaults** (0092-0094, render scale 100%):

| Title | before | after | hands |
|---|---|---|---|
| Vertical Shift (1807480) | 30 fps, "far from the map" | **66-77 fps**, 87 W / 42% GPU, well positioned | never visible in this title: inconclusive |
| Sniper Elite VR (752480) | 45 fps at moments, world very high | **89 fps**; second run with constellation on 87 fps | driver tracks them (`matched_blobs=6`), the title's pointer stays immobile: xrizer-to-title binding |
| Dead Herring VR (1498490) | 44-45 fps + flying away | **80-90 fps**, no relocation, 11 companion drops during the run | left controller usually anchored then jumps to the real position (about 70% wrong / 30% right), right one absent (also in Google Earth VR): `docs/58`'s known residual |
| Wolfenstein: Cyberpilot (1056970) | 30 fps | 70-80 fps (lower bound, a second title was rendering behind it) | see Cyberpilot details |

Launcher fact: `up 1 6dof` does NOT turn controller constellation on (export
`WMR_CONSTELLATION_CONTROLLERS=1` explicitly; `ctrl` implies it).

The panel itself stayed at true 90 Hz all session (`found display mode 4320x2160@90.00` in every
launch log, never a fallback to 60), so the "flicker" feeling on low-fps titles is
compositor frame-repeat/reprojection judder from a low app render rate, not a regression of the
original 60 Hz backlight-strobe fix.
