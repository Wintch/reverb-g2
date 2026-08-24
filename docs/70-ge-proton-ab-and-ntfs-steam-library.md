# 70 — GE-Proton vs Experimental A/B, and two real Steam/NTFS gotchas found getting there

**Status: measured, 2026-08-24. Two config fixes applied and confirmed working
(secondary NTFS library registered, Proton prefix relocated off NTFS). Results are
single-run per cell — repeat 2-3x per this project's own variance discipline before
treating the FSR gap below as settled.**

## Why this exists

Following up on `docs/48`/`docs/69`'s GPU-bound benchmarking thread with the other
half of the "what actually varies performance" question this session opened: not just
GPU power and render API, but **which Proton build** runs the game. GE-Proton
(the community fork) advertises OptiScaler/FSR4/DLSS-scaling patches vanilla Proton
doesn't have — a plausible, measurable performance lever, unlike chasing every vanilla
Proton point release (mostly per-game compatibility fixes, not general performance
changes).

## Two real gotchas, found live, before any benchmark could even run

### 1. A second Steam library (NTFS, shared with Windows) wasn't registered

The rig has a second Steam library at `/mnt/videos/SteamLibrary` — three NTFS
partitions (`nvme0n1p3/4/5`, mounted via `fuseblk`/ntfs-3g), genuinely shared with a
Windows install (the library's own `libraryfolder.vdf` marker file has `"launcher"
"C:\\Program Files (x86)\\Steam\\steam.exe"` baked in — proof it was created by Windows
Steam, not this Linux one). **Cyberpunk 2077 (66GB) already lived there, fully
installed** — but this Linux Steam client had never had that library folder added
(`~/.steam/debian-installation/steamapps/libraryfolders.vdf` only listed the primary
local library). Launching the game therefore offered to **install it fresh** — not
because anything was broken, purely because Steam didn't know the second library
existed.

**Fix**: with Steam shut down, add an entry to `libraryfolders.vdf` for the path, using
the `contentid` already present in that library's own `libraryfolder.vdf` marker
(leave `"apps": {}` empty — Steam scans and populates it itself on next start):

```
"1"
{
	"path"		"/mnt/videos/SteamLibrary"
	"label"		""
	"contentid"		"6686477392085450162"   // from that library's own libraryfolder.vdf
	"totalsize"		"0"
	"update_clean_bytes_tally"		"0"
	"time_last_update_verified"		"0"
	"apps"
	{
	}
}
```

Confirmed live: Steam's next start scanned the whole library and populated every
appid's exact installed size (Cyberpunk showed up as `66366228927` bytes, matching
what was already on disk) — no download, no re-verify, just recognition.

### 2. Proton's own prefix can't be created on NTFS at all

Even with the library recognized, the first real launch attempt crashed in ~2 seconds:

```
OSError: [Errno 22] Invalid argument: '../drive_c' -> '.../compatdata/1091500/pfx//dosdevices/c:'
```

This is `ntfs-3g` refusing the symlink Proton creates inside every prefix
(`dosdevices/c:` → `../drive_c`) — NTFS's symlink/reparse-point emulation doesn't
support whatever Proton's prefix-init code needs here. **The actual game files were
never touched** — this only affects the small Linux-only `compatdata/<appid>` metadata
folder, which Windows Steam doesn't read or care about either way.

**Fix**: don't put the prefix on NTFS. Relocate just `compatdata/<appid>` to the local
ext4 disk (real symlink support) via a plain symlink, leaving the actual game on NTFS
untouched:

```bash
rm -rf /mnt/videos/SteamLibrary/steamapps/compatdata/1091500   # was a broken partial prefix, not game data
mkdir -p ~/proton-prefixes-external/1091500
ln -s ~/proton-prefixes-external/1091500 /mnt/videos/SteamLibrary/steamapps/compatdata/1091500
```

Confirmed live: after this, the prefix builds and the game launches normally under
either Proton build tested. **General lesson for this rig, not just Cyberpunk**: any
title installed on the NTFS library will hit this exact crash on first Proton launch;
apply the same symlink relocation before assuming a title is broken.

Also confirmed empirically, worth remembering: switching a title's assigned Proton
build (via `CompatToolMapping` in `config.vdf`) while **reusing the same prefix**
across two different Proton major builds is asking for trouble (different Wine
versions sharing one prefix is a known source of subtle breakage) — this session used
a **separate prefix directory per Proton build** (`1091500-ge-proton11-5` vs.
`1091500-experimental`, both under `~/proton-prefixes-external/`, swapped via the same
symlink) specifically to keep the two arms of the A/B clean of each other.

## Installing GE-Proton

Not on Steam's own tool list — fetch straight from the project's GitHub releases and
drop it in the compatibility-tools directory Steam already scans:

```bash
mkdir -p ~/.steam/debian-installation/compatibilitytools.d
curl -L -o /tmp/GE-Proton.tar.gz \
  "$(curl -s https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest \
     | grep -o 'https://[^"]*x86_64\.tar\.gz')"
tar -xzf /tmp/GE-Proton.tar.gz -C ~/.steam/debian-installation/compatibilitytools.d/
```

Steam needs a full restart (`steam.sh -shutdown`, wait, relaunch) to notice a newly
added tool — confirmed live by watching Steam's own startup hardware probe
(`d3ddriverquery64.exe`) run through the new tool automatically right after restart,
with zero manual selection.

To force a specific title onto it (or back to vanilla), edit `config.vdf`'s
`CompatToolMapping` with Steam shut down (same "edit config while the client is
down, never while it's live" discipline as the `libraryfolders.vdf` fix above):

```
"CompatToolMapping"
{
	"<appid>"
	{
		"name"		"GE-Proton11-5-x86_64"    // or "proton_experimental" for vanilla
		"config"		""
		"priority"		"250"
	}
}
```

The internal tool name comes from the tool's own `compatibilitytool.vdf`
(`"GE-Proton11-5-x86_64"` for this release) — don't guess it from the folder name,
read the manifest.

## Measuring: MangoHud, since Cyberpunk keeps no useful logs of its own

Checked first, to avoid extra tooling if unnecessary: Cyberpunk 2077 retail writes no
fps/perf log by default (no `r6/logs` or per-run engine log found under its `AppData`
prefix path — only `UserSettings.json`). No CLI benchmark flag either, unlike
Heaven/Quake II RTX (see `docs/69`) — the only benchmark entry point is the in-game
**Settings → Graphics → Run Benchmark** button, a fixed camera fly-through reporting
avg/min/max fps and frame count at the end, same reviewer-standard shape as Heaven's.

[MangoHud](https://github.com/flightlessmango/MangoHud) (`apt install mangohud`) fills
the gap — a Vulkan/OpenGL overlay + CSV logger, config'd per-executable at
`~/.config/MangoHud/<exe_name>.conf`:

```
output_folder=/home/iam/vr/logs/mangohud
autostart_log=1
log_duration=90
fps_metrics=avg,0.1,0.01
no_display
```

Enabled via the title's Steam launch options (same shutdown-Steam-first discipline to
edit `localconfig.vdf`'s per-app `LaunchOptions`): `MANGOHUD=1 %command%`.

## Results (single run per cell — see Status banner)

Same demo (Cyberpunk's built-in benchmark), same 1920x1080 Windowed Borderless, same
64.2-64.3s duration each run. Two settings profiles, two Proton builds, screenshotted
directly off the in-game results screen (MangoHud overlay visible in the same shot for
cross-check):

| Config | Proton | Avg FPS | Min FPS | Max FPS | Frames |
|---|---|---|---|---|---|
| Ray Tracing: Low, DLSS Quality (Transformer) | GE-Proton11-5 | 78.06 | 55.59 | 101.84 | 5015 |
| Ray Tracing: Low, DLSS Quality (Transformer) | Proton Experimental | 77.11 | 56.13 | 101.19 | 4954 |
| Medium preset, FSR 2.1 Auto + Sharpening 0.5 | GE-Proton11-5 | **112.67** | **80.92** | **149.15** | 7239 |
| Medium preset, FSR 2.1 Auto + Sharpening 0.5 | Proton Experimental | 109.03 | 75.60 | 146.26 | 7006 |

**With DLSS: no real difference** (≤1.2% either direction, inside normal run-to-run
noise). **With FSR: GE-Proton is ahead on every metric**, most notably the **min fps,
+7.0%** (80.92 vs 75.60) — the metric this project's own priority (lows over average,
see `docs/48`) actually cares about. Matches the hypothesis cleanly: GE's
FSR-side patches (OptiScaler / bundled VKD3D-Proton improvements ahead of upstream)
help specifically on the FSR path, and DLSS goes through NVIDIA's own path either way,
largely unaffected by which Proton build is running it.

**Not yet done**: repeating each cell 2-3x to confirm this isn't a lucky/unlucky single
run (this rig's own measured per-window variance elsewhere has been as high as
5-9%, `vr-power-setup.sh`'s header) — the DLSS "no difference" read is fairly safe
already (both numbers land within that noise band of each other), but the FSR min-fps
gap, while bigger than the DLSS gap, is not yet clearly bigger than this rig's own
noise floor either. Re-run before quoting the +7.0% number as settled.

## Files / paths touched

```
~/.steam/debian-installation/compatibilitytools.d/GE-Proton11-5-x86_64/   new
~/.steam/debian-installation/steamapps/libraryfolders.vdf                 edited (2nd library registered)
~/.steam/debian-installation/config/config.vdf                            edited (CompatToolMapping)
~/.steam/debian-installation/userdata/*/config/localconfig.vdf            edited (MangoHud launch option)
~/proton-prefixes-external/1091500-ge-proton11-5/                         new -- GE's prefix
~/proton-prefixes-external/1091500-experimental/                          new -- Experimental's prefix
/mnt/videos/SteamLibrary/steamapps/compatdata/1091500                     now a symlink, not a real dir
~/.config/MangoHud/Cyberpunk2077.exe.conf                                 new
~/vr/logs/mangohud/                                                       new -- MangoHud CSV output
```

Every `.vdf` edit was preceded by a timestamped backup next to the original
(`<file>.bak-<timestamp>`) and done with Steam fully shut down first — never edit these
live, per this project's own established caution around Steam's config files.
