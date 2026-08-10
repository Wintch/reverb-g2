# 27 — Verbose logging survey: Steam, Proton, game engines, OpenXR loader

Research pass (2026-08-10), triggered by a real gap: every startup bug found this same
session (missing `XDG_SESSION_TYPE`, `runuser` killing children on session teardown,
missing `plugdev` supplementary group, a stale Monado DRM lease after a cable reseat)
was diagnosed entirely on the **native Linux side** (`jack-in-wayland.sh`, `monado-service`,
systemd). Nothing has ever looked inside a Proton-sandboxed game's own view of its
environment, or the OpenXR loader's own resolution steps, when something goes wrong
there instead. This doc surveys what's available, without enabling anything by default
-- per the user's own instruction, only disable/keep a source once it's actually been
checked for signal, don't pre-judge.

**Already in use, not new** (context, so the list below doesn't duplicate it):
`jack-in-wayland.sh` already sets `XRT_COMPOSITOR_LOG=debug` on every launch. Past
sessions used `WMR_LOG=debug` (T045, T055) and this project's own `HELLO_XR_POSE_STATS=1`
(`patches/hello_xr-player/0001`) to catch a dead tracking thread and a proximity-sensor
HID read failure. `~/.local/state/xrizer/xrizer.txt` is xrizer's own log (Rust
`env_logger`, default level `Info`, `RUST_LOG` overrides it) -- already informally cited
in `docs/23` and confirmed still healthy (reaches `FOCUSED` cleanly) as of tonight.

## Ranked for startup/env/permission-class bugs (tonight's class)

1. **`XR_LOADER_DEBUG={none,error,warn,info,all}`** -- read by `libopenxr_loader.so`,
   which every title here (UE, Unity, xrizer) calls through. Logs runtime-manifest
   discovery, `dlopen` of the runtime library, and the initial `xrCreateInstance`
   handshake. This is the exact point where `ERROR_RUNTIME_UNAVAILABLE`-class failures
   (`docs/23`'s launch-options trap, `docs/06`'s pressure-vessel note) actually
   originate -- currently diagnosed indirectly (`/proc/<pid>/environ`, absence of
   activity in `xrizer.txt`). Highest signal-to-noise of everything surveyed, zero
   engine-specific setup needed. **No help for 6DoF** -- instance-creation-time only.

2. **`PROTON_LOG=1`** (+ optional `PROTON_LOG_DIR=<path>`, defaults to `$HOME`) --
   writes `steam-<AppID>.log` and **automatically** also sets
   `WINEDEBUG=+timestamp,+pid,+tid,+seh,+unwind,+debugstr,+loaddll,+mscoree`,
   `DXVK_LOG_LEVEL=info`, `VKD3D_DEBUG=warn`. Extends diagnosis into the half of the
   stack nothing has looked at yet (Wine/Proton's own env and file view). Worth adding
   manually on top: `+env` (does `XR_RUNTIME_JSON`/`PRESSURE_VESSEL_FILESYSTEMS_RW`
   actually reach the Windows-side process?), `+file` (permission/EACCES-class failures
   from inside Wine). `+relay` (every cross-DLL call) is too noisy for default-on --
   only useful narrowed to one DLL. **No help for 6DoF** -- below the engine, no pose
   awareness.

3. **Unity's `Player.log`** -- default path `~/.config/unity3d/<Company>/<Product>/
   Player.log`, or explicit `-logFile <path>` (`-logFile -` for stdout). No flag needed
   to see `XR SDK`/OpenXR loader init failures at normal verbosity -- **already being
   produced on every run and thrown away**. Likely Unity titles among the 12 confirmed
   working (not per-title confirmed, worth a quick `*_Data` folder check if this matters
   later): Cosmic Flow, VRSailing, SUPERHOT, Propagation VR, Google Earth VR, Dead
   Herring VR, Tank Mechanic Simulator, SafeZoneVR. No per-frame pose data without the
   game's own script logging.

4. **Unreal Engine** (Aircar, confirmed UE-based) -- `-log` (live console + log-to-file),
   `-stdout`/`-FullStdOutLogOutput` (route to stdout, fits the existing `setsid stdbuf`
   capture pattern this project already uses for Monado), `-LogCmds="LogInit Verbose,
   LogHMD Verbose"` (raise verbosity per-category without touching `Engine.ini`).
   `LogInit` shows exactly where in UE's own startup a missing-env-var or permission
   failure manifests; `LogHMD` shows OpenXR session-state/tracking-origin events (not
   raw poses). Complements #2, doesn't duplicate it -- Wine-level shows what the OS gave
   the process, UE-level shows what UE itself saw.

5. **Steam's own client logs** (`~/.steam/steam/logs/{content_log,bootstrap_log,
   connection_log}.txt`) -- already the mechanism behind `docs/23`'s "one launch at a
   time" rule (checking for background downloads). Nothing new to add; keep using
   `content_log.txt` as-is.

## Situational only, not default-on

- **`DXVK_LOG_LEVEL={none,error,warn,info,debug}`** / **`VKD3D_DEBUG={none,err,fixme,
  warn,trace}`** / **`DXVK_HUD=compiler`** -- the D3D-on-Vulkan translation layer.
  Catches genuine graphics-API failures (bad device selection, OOM, shader compile
  stalls that look like a startup hang) but has zero visibility into env vars,
  permissions, DRM leases, or poses. Matches this project's own precedent
  (`HELLO_XR_FIXED_POSE`, `WMR_LOG=debug` used only when needed): enable as a
  second-pass check when a title reaches `FOCUSED` in Monado/xrizer's own log but shows
  nothing renderable, not as a default-on diagnostic.

## For the 6DoF/SLAM divergence investigation specifically

**None of the above are a real substitute for what's already in use.** Steam, Proton,
DXVK/VKD3D, and the OpenXR loader never see pose data -- that lives entirely inside
Monado/Basalt, already surfaced via `WMR_LOG=debug` and the `det(Q1Jl)==0` cascade greps
used in the T106 divergence follow-up. UE's `LogHMD` and Unity's default log only show
session-level *events* (lost/recovered/recentered), not the numeric divergence itself.
If finer-grained pose data is ever needed from a **Steam title specifically** (as
opposed to the custom `hello_xr` player, which already has `HELLO_XR_POSE_STATS=1`),
the realistic options are Monado-side only -- `XRT_LOG=debug` (project-wide) or a
targeted per-driver var -- not anything from the Steam/Proton/engine side.

## One mechanical rule that applies to every var above

Per `docs/23`'s already-proven trap: anything that needs to reach the actual game
process under Proton (`XR_LOADER_DEBUG`, `PROTON_LOG`, `WINEDEBUG`, `DXVK_LOG_LEVEL`)
must be exported in the shell **before** starting the `steam` client itself, not set via
per-game Launch Options -- the same mechanism already verified working for
`XR_RUNTIME_JSON`/`PRESSURE_VESSEL_FILESYSTEMS_RW`.

## Sources

[ValveSoftware/Proton](https://github.com/ValveSoftware/Proton) ·
[WineHQ Debug Channels](https://www.linuxsecrets.com/wine-wiki/Debug_Channels.html) ·
[UE 4.27 Command-Line Arguments](https://docs.unrealengine.com/4.27/en-US/ProductionPipelines/CommandLineArguments) ·
[Unity Manual: Log files reference](https://docs.unity3d.com/6000.5/Documentation/Manual/log-files.html) ·
[dxvk/README.md](https://github.com/doitsujin/dxvk/blob/master/README.md) ·
[vkd3d-proton environment variables](https://deepwiki.com/HansKristian-Work/vkd3d-proton/8.4-environment-variables) ·
[OpenXR Loader — Design and Operation](https://registry.khronos.org/OpenXR/specs/1.0/loader.html)
