# 11 - WMR Decompilation Plan (Windows binaries -> Monado driver knowledge)

Status: PLANNING ONLY. No mount, no extraction, no decompilation has happened yet.
This document plans the workflow; `scripts/extract-wmr-dlls.sh` implements the
extraction step and is meant to be run *later*, after the Windows NTFS partition
has been mounted read-only by the user.

## 1. Goal

We want to understand two things that have no public write-up anywhere:

1. The **WMR 6DoF controller tracking path** - how Windows fuses controller
   IMU + camera-based tracking (the "6DoF Kalman"/SLAM-ish loop) into the pose
   pipeline exposed to apps via `Windows.Perception.Spatial`.
2. The **headset <-> controller tunnel protocol** - the USB HID report framing
   that carries controller status/input/tracking data through the headset's
   USB tunnel (Bluetooth-over-USB-HID-like tunnel used by the Reverb G2
   controllers).

Right now, everything we know about (2) lives only in Monado's own
reverse-engineered implementation, principally:

- `/home/brunduk/Documents/linux_vr_base/monado/src/xrt/drivers/wmr/wmr_controller_protocol.c`
  (by Nis Madsen) - message IDs, report parsing, struct layouts inferred from
  USB captures.
- The rest of `src/xrt/drivers/wmr/` (see file listing below) - HMD protocol,
  config blob parsing, camera/tracking glue.

Monado's WMR driver directory, for reference during cross-checking:

```
monado/src/xrt/drivers/wmr/
  wmr_protocol.c / .h              - low-level HMD USB protocol
  wmr_controller_protocol.c / .h   - controller tunnel protocol (KEY FILE)
  wmr_controller.c / .h            - controller driver glue
  wmr_controller_base.c / .h       - shared controller state machine
  wmr_controller_og.c              - "original" (Samsung Odyssey-era) controllers
  wmr_controller_hp.c              - HP Reverb G2 controller variant
  wmr_bt_controller.c / .h         - Bluetooth-paired controller path
  wmr_hmd.c / .h                   - headset driver
  wmr_hmd_controller.c / .h        - headset-mediated (tunneled) controller path
  wmr_camera.c / .h                - HMD camera streaming
  wmr_config.c / .h, wmr_config_key.h - calibration blob parsing
  wmr_common.h, wmr_source.c / .h  - shared types, tracking source glue
  wmr_prober.c                     - USB device enumeration/matching
```

The aim of this RE effort is **not** to replace Monado's protocol
implementation, but to *validate and extend* it: confirm message IDs and
struct fields we're unsure about, and find the parts of the 6DoF fusion math
that are not yet reverse engineered (esp. anything controller-IMU-related that
currently causes tracking drift/jitter in the Linux driver).

## 2. Target binaries

These live on the Windows install once `/dev/nvme0n1p3` is mounted read-only
(by the user, outside this plan - see workflow below). Two groups, clearly
separated by priority.

### 2a. PRIORITY - real device tracking / runtime stack

This is the actual code path that talks to the physical headset and fuses
controller tracking. This is what we care about.

- `Windows.Perception.dll`, `Windows.Perception.Spatial.dll` and related
  `Windows.Perception.*` WinRT projection/implementation DLLs
  (System32, and `WinMetadata\*.winmd` for the API surface).
- Holographic system services - anything named `holographic*` under
  `System32`, e.g. `HolographicRuntime.dll`,
  `Windows.Graphics.Holographic.dll` (naming varies by Windows build).
- The actual WMR device driver / runtime binaries:
  - Under `System32`: files matching `*MixedReality*`, `*Holographic*`,
    `*WMR*`, `*HolographicDevice*`.
  - The WMR "Mixed Reality Portal" install directory (Program Files /
    WindowsApps package for `Microsoft.Windows.HolographicFirstRun` /
    `Microsoft.MixedReality.Portal`), and its driver-support DLLs.
  - `System32\DriverStore\FileRepository\` packages whose `.inf`/folder name
    references WMR / HoloLens Sensors / Spatial (these contain the actual
    kernel-mode + user-mode driver binaries Windows loads for the HMD).
- Any DLL implementing the controller tunnel parser itself, if it's separable
  from the generic holographic stack (naming likely overlaps with the above;
  identify by import table / string search for HID report IDs once loaded in
  Ghidra).

### 2b. SECONDARY - Perception Simulation (synthetic input, NOT the real driver)

This is the **input simulator** used for testing/dev without real hardware.
It is useful only as a secondary cross-reference (it documents pose/input
*data shapes* at the API boundary) - it does NOT contain the real
tracking/fusion code and must not be mistaken for it:

- `PerceptionSimulationManager.Interop.dll`
- `PerceptionSimulationRest.dll`
- `SimulationStream.Interop.dll`
- `PerceptionSimulationInput.exe`

Do not spend serious RE effort here until the priority group has been mined.

## 3. Tooling

### Native code (DLLs, drivers): Ghidra

- Free, NSA-released, scriptable. Chosen over commercial alternatives (no
  budget/license needed) and over radare2/Cutter (better decompiler output
  quality for MSVC-compiled C++ with RTTI, which is what this stack is).
- Headless batch import via `analyzeHeadless` lets us import/analyze the
  whole extracted DLL set unattended, and re-run analysis after re-extracting
  a newer build (e.g. after a Windows Update) to **diff decompiled output
  across versions** - useful since WMR runtime code has changed across
  Windows 10/11 builds and diffing may reveal which parts are stable
  (safe to treat as protocol spec) vs incidental.
- Requires a JDK. Not currently installed on this machine (see status below).

Planned headless workflow (commands to run manually once binaries are
extracted - documented here, not executed by any script yet):

```sh
# One-time project creation + analysis of everything in the extraction dir:
analyzeHeadless /path/to/ghidra_projects WmrRE \
    -import /path/to/extracted/*.dll \
    -recursive \
    -processor "x86:LE:64:default" \
    -analysisTimeoutPerFile 600

# Re-run analysis only (project already populated), useful after adding
# scripts or re-extracting a newer build for diffing:
analyzeHeadless /path/to/ghidra_projects WmrRE \
    -process \
    -analysisTimeoutPerFile 600
```

Then open the project in the Ghidra GUI for interactive decompilation of
target functions (string/constant search for HID report IDs and message
type constants found in `wmr_controller_protocol.c` is the fastest way to
locate the relevant functions inside a huge DLL).

### Managed/.NET assemblies: ILSpy / dnSpy

Some of the Holographic/Perception stack, and definitely the Perception
Simulation tooling, may include .NET or WinRT-projected managed assemblies.
For those:

- `ilspycmd` (CLI decompiler, easiest to script/batch) - not installed.
- ILSpy GUI or dnSpy (interactive, better for stepping through call graphs) -
  not installed, Windows-oriented tools; may need `dotnet` + `ilspycmd` as
  the practical Linux-side option, or running ILSpy under Wine if the GUI is
  needed.
- `monodis` (Mono IL disassembler) - only useful for Mono-compiled IL, not
  relevant here since this is genuine .NET/WinRT, listed only because it was
  checked.

### Ghidra install steps on Debian (documented for later - do NOT run yet)

1. Install a JDK: `sudo apt install openjdk-21-jdk` (candidate
   `21.0.12+8-1~deb13u1` available via `trixie-security`, confirmed present
   in apt cache as of this writing).
2. Download the latest Ghidra release **from the official GitHub releases
   page** (`https://github.com/NationalSecurityAgency/ghidra/releases`) -
   Debian does not currently package `ghidra` (not found via
   `apt-cache policy`/`dpkg -l`).
3. Unzip to e.g. `/opt/ghidra` (not done - `/opt` currently has no Ghidra
   dir).
4. Add `/opt/ghidra` (or its `support/` subdir) to `PATH`, or reference
   `analyzeHeadless`/`ghidraRun` with a full path.
5. First GUI launch (`ghidraRun`) will prompt for a Ghidra project directory
   - point it at a dedicated `ghidra_projects/` dir, not inside this repo.

## 4. Workflow (end to end)

1. **User mounts the Windows NTFS partition read-only** (outside this plan,
   privileged operation):
   ```sh
   sudo mount -o ro /dev/nvme0n1p3 /mnt/win
   ```
2. Run `scripts/extract-wmr-dlls.sh /mnt/win` - copies priority + secondary
   target binaries into a local output dir, with a logged manifest
   (filename, size, sha256) for provenance/reproducibility.
3. Import the extracted binaries into a Ghidra project via `analyzeHeadless`
   (see commands above).
4. Decompile target functions:
   - Start from string/constant search for known WMR protocol constants
     (message type bytes, HID report IDs, GUIDs) that appear in
     `wmr_controller_protocol.c` and `wmr_protocol.h`.
   - Follow call graphs upward/downward from there to find the
     controller-tracking fusion code and the tunnel framing/parsing code.
5. **Cross-reference every finding against Monado's existing structs and
   message-ID enums** in `wmr_controller_protocol.c` / `wmr_controller_protocol.h`
   and `wmr_protocol.h`. The goal is a diff: where does Windows agree with
   Monado's current reverse-engineered model, and where does Monado's model
   fall short (missing fields, wrong offsets, unhandled message types)?
6. Write up confirmed findings as patches/comments against the Monado driver
   source (in the `monado` working tree, not this repo) - never as raw
   Microsoft/NVIDIA decompiled output committed anywhere.

## 5. NDA / IP CAUTION

- Decompiled Microsoft (and any NVIDIA driver-adjacent) binaries are
  **derivative works of copyrighted, proprietary code**. Treat all
  decompiler output as confidential working material.
- Do **not** circulate raw decompiled/disassembled output, Ghidra project
  files, or extracted DLLs outside this machine - not to GitHub, not to the
  Monado GitLab MRs, not to forums, not to Matrix.
- When contributing findings back upstream (Monado MRs, forum posts), only
  ever describe **behavior** (message IDs, struct layouts, algorithms in your
  own words/code) - the same standard used for legitimate clean-room reverse
  engineering. Never paste decompiler-generated C, disassembly listings, or
  Microsoft symbol/string names verbatim into a public issue, MR, or commit.
- Keep the extraction output dir and any Ghidra project files out of git
  entirely (do not add them to this repo; if a `.gitignore` entry is needed
  for a local output path under this repo, add one rather than relying on
  discipline alone).
- This applies to the existing "Session role split" convention too: RE work
  and any resulting *code* changes to the Monado driver belong in the dev
  session/repo, not this comms-focused one - but the plan/tooling docs here
  are fine since they contain no proprietary material.

## 6. Environment status (checked 2026-08-16)

| Tool | Status |
|---|---|
| Ghidra (`ghidra`/`ghidraRun`/`analyzeHeadless`) | NOT installed - no binary on PATH, nothing under `/opt` or `/usr/share`, not in `dpkg -l`, no `apt-cache policy` match (not packaged for Debian) |
| Java (`java -version`) | NOT installed - `java: command not found`. `openjdk-21-jdk` (21.0.12+8-1~deb13u1) is available in apt cache and is the recommended candidate |
| ilspycmd | NOT installed |
| dnSpy | NOT installed |
| monodis | NOT installed |
| `dotnet` CLI | NOT installed |

Nothing needs to be installed to write this plan or the extraction script;
installation is only required before the Ghidra-import step of the workflow
above, and is left for the user to do explicitly (not done as part of this
task, per the no-sudo constraint).
