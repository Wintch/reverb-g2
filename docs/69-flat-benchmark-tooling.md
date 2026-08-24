# 69 — Flat (non-VR) benchmark tooling: cache warming and standalone Proton apps

**Status: two tools used for the first time on this rig, 2026-08-23/T246 follow-up.
Documented here because neither had a home yet — `docs/26` is headset/hardware buying-guide
focused, this is benchmark-methodology focused.**

## `vmtouch` — page-cache warming before a timed run

Installed to rule out a specific false-positive: a low "min fps" in a benchmark result
could be a real engine/API hitch, or it could be the kernel stalling on a cold page-cache
read from SSD/NVMe the first time a file is touched — indistinguishable from the FPS
counter alone. `scripts/vr-prewarm.sh` already solves this for Steam-appid-resolved
titles (`cache` mode: read every byte so the kernel's page cache holds them, no root
needed, works on any storage). `vmtouch` is the same primitive, used directly for
anything `vr-prewarm.sh` can't resolve — chiefly the standalone Proton apps below, which
have no Steam appmanifest for it to find.

Real flags (confirmed via `vmtouch -h` and a live run, not assumed):

```
vmtouch -t <dir>     # touch: read every page into the kernel's cache
vmtouch <dir>         # no flags: report current residency, touches nothing
```

Example, this session's actual Unigine prefix after normal use (no explicit `-t` needed —
install + a few launches had already warmed most of it):

```
$ vmtouch ~/vr/proton-prefixes/unigine
           Files: 812
     Directories: 267
  Resident Pages: 795781/863365  3G/3G  92.2%
```

Like `vr-prewarm.sh`'s `cache` mode, this is only ever a hint to the kernel — under memory
pressure pages can be evicted before the run starts. It is NOT the same guarantee as
`vr-prewarm.sh`'s `ram` mode (rsync to tmpfs + symlink swap); nobody has extended the `ram`
mode to non-Steam installs yet.

## Standalone Proton launches (Unigine Heaven / Superposition Benchmark)

Unigine's Heaven and Superposition benchmarks are free Windows-only downloads (not on
Steam, not on Linux for a real DirectX comparison — the native Linux build only offers
OpenGL/Vulkan, no DirectX at all, since DirectX doesn't exist outside Windows). To get real
DX9/DX11 numbers at all, they have to run under Proton, but with no Steam appid, so a
custom prefix was made instead of a Steam library entry:

```
mkdir -p ~/vr/proton-prefixes/unigine
STEAM_COMPAT_CLIENT_INSTALL_PATH=~/.steam/steam \
STEAM_COMPAT_DATA_PATH=~/vr/proton-prefixes/unigine \
"~/.steam/steam/steamapps/common/Proton - Experimental/proton" run <installer-or-exe>.exe
```

This is the same mechanism Lutris/Bottles use under the hood: any Proton build can run any
Windows binary against any prefix directory, no Steam library entry required. Used first to
run the two installers (`Unigine_Heaven-4.0.exe`, `Unigine_Superposition-1.1.exe`, official
free downloads from `benchmark.unigine.com`) with `xdotool`-driven clicks through the
InnoSetup wizard, then to run the installed exes directly.

**Real gap this creates, not fixed here**: `scripts/game-stop.py`'s `scan()` (and therefore
`vr-power-watchdog.py`'s "is anything active" check) only recognizes processes Steam itself
launched — it matches on the `SteamAppId`/`STEAM_COMPAT_DATA_PATH` environment variables
Steam sets on every child process. A binary launched via a hand-built `proton run` like
above carries neither, so it is invisible to both scripts. Running one of these benchmarks
with the watchdog installed will leave the machine in `saver` (100W GPU cap, `powersave`
governor) even while the benchmark is genuinely GPU-bound — silently changing the result,
not just missing a nice-to-have. **Bracket any standalone-Proton run with
`vr-power-setup.sh --apply`/`--saver` by hand** (same pattern `q2rtx-power-sweep.sh` already
uses for Quake II RTX, a real Steam title, just done there for a controlled experiment
rather than out of necessity).

### Heaven.exe: real CLI syntax, found live, not from Unigine's docs

Clicking "Run" in Heaven's launcher UI (`browser_x86.exe`) starts `heaven.exe` with a
specific command line — read directly off the running process's `/proc/<pid>/cmdline`,
confirmed working:

```
heaven.exe -project_name Heaven -data_path ../ -engine_config ../data/heaven_4.0.cfg \
  -system_script heaven/unigine.cpp -sound_app openal \
  -video_app <direct3d9|direct3d11|opengl> -video_multisample 0 -video_fullscreen 1 \
  -video_mode <N> \
  -extern_define ,RELEASE,LANGUAGE_EN,QUALITY_HIGH,TESSELLATION_DISABLED \
  -extern_plugin ,GPUMonitor
```

`-video_app` is the whole point — this launches Heaven directly into a chosen renderer,
skipping the GUI dropdown (and the `xdotool` coordinate-clicking that was fragile: the
resolution dropdown's list re-anchors around the currently-selected item, so a click
position that picked "1920x1080" once picked "1600x900" the next time the current value
had changed — confirmed live, cost a wrong resolution on the first DX9 run). `-video_mode`
is a numeric index into Heaven's resolution list; only index `5` was confirmed this session
(→ 1600x900, seen via the settings UI before switching to direct CLI launch) — the mapping
for other indices (1920x1080 is very likely 6, immediately after) is inferred from list
order, not independently confirmed yet.

**First real result obtained this session** (DirectX 9, Quality High, Tessellation
Disabled, AA Off, 1600x900 fullscreen — NOT re-run yet at the corrected resolution or with
a warm cache guaranteed beforehand, treat as provisional):

| metric | value |
|---|---|
| FPS | 245.1 |
| Score | 6174 |
| Min FPS | 9.6 |
| Max FPS | 495.8 |

The Min FPS 9.6 dip is unexplained — could be a real single-scene hitch (shader
compile/streaming pause) or a cold-cache artifact from the very first full benchmark pass
on a freshly-installed prefix. Not disentangled yet; re-running with the prefix already
`vmtouch`-warmed (now 92.2% resident) and comparing the min-fps figure across repeats is
the way to tell them apart, not done this session.

### Superposition's CLI/XML automation: license-gated, unconfirmed

`superposition_cli.exe` ships with a fully-documented XML-driven automation format —
`bin/pro_xml_samples/*.xml` includes `multiple_run_low_dx_and_gl.xml`, a ready-made
DirectX-then-OpenGL back-to-back pass with per-pass CSV/TXT logging (`<api>`, `<quality>`,
`<log_csv>`, etc., every field self-documented in the XML's own comments). Ran it against
the free Basic edition installed this session:

```
$ proton run superposition_cli.exe -xml_file pro_xml_samples/single_run_medium.xml
$ echo $?
0
```

Exit 0, but zero output: no stdout, no `result_medium.csv`/`.txt` written anywhere, no new
file under the install directory or under Wine's AppData. The `pro_xml_samples` folder name
strongly suggests this automation path is gated behind the paid Advanced/Pro tier
(`benchmark.unigine.com` lists Advanced/Professional/Enterprise at $19.95–$7500, docs
already fetched this session), but **this is not confirmed** — it could equally be a
missing runtime dependency or an argument-parsing issue specific to running under Proton.
Whoever picks this up next: try `-xml_file` with an absolute Windows-style path (`Z:\...`)
instead of a relative one before concluding it's purely a license wall.

## Files referenced

```
scripts/vr-prewarm.sh          existing -- Steam-appid cache/ram prewarm, not extended here
scripts/q2rtx-power-sweep.sh   pattern to copy for bracketing a standalone-Proton run
~/vr/proton-prefixes/unigine   new -- standalone Proton prefix, Heaven + Superposition installed
```
