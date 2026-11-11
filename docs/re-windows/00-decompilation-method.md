# WMR decompilation method (Windows binaries -> Monado driver knowledge)

How the findings in this directory were obtained, and how to reproduce them. Raw decompiler output
is never committed (see the IP caution in section 5); only behavior-level write-ups are.

## 1. Goal

Understand two things that have no public write-up:

1. The **WMR 6DoF controller tracking path**: how Windows fuses controller IMU and camera-based
   tracking into the pose pipeline exposed through `Windows.Perception.Spatial`.
2. The **headset <-> controller tunnel protocol**: the USB HID report framing that carries
   controller status, input and tracking data through the headset's USB tunnel.

Until now everything known about (2) lived in Monado's own reverse-engineered implementation,
mainly `src/xrt/drivers/wmr/wmr_controller_protocol.c` (message IDs, report parsing, struct layouts
inferred from USB captures) and the rest of `src/xrt/drivers/wmr/` (HMD protocol, config blob,
camera/tracking glue). The aim is not to replace that implementation but to validate and extend
it: confirm message IDs and struct fields, and find the parts of the 6DoF fusion math that are
not yet reverse engineered.

## 2. Target binaries

Taken from an installed Windows with the Mixed Reality stack.

**Priority: the real device tracking / runtime stack.**

- `Windows.Perception.dll`, `Windows.Perception.Spatial.dll` and related `Windows.Perception.*`
  WinRT DLLs (System32; `WinMetadata\*.winmd` for the API surface).
- Holographic system services: anything named `holographic*` under System32
  (e.g. `HolographicRuntime.dll`, `Windows.Graphics.Holographic.dll`; naming varies by build).
- The WMR device driver/runtime binaries: System32 files matching `*MixedReality*`,
  `*Holographic*`, `*WMR*`; the Mixed Reality Portal package directory; and the
  `DriverStore\FileRepository\` packages whose `.inf` references WMR / HoloLens Sensors / Spatial
  (`hololenssensors.inf` holds the kernel- and user-mode HMD drivers).
- Any DLL implementing the controller tunnel parser itself; identify it by import table and by
  string search for HID report IDs once loaded in Ghidra.

**Secondary: Perception Simulation** (`PerceptionSimulationManager.Interop.dll`,
`PerceptionSimulationRest.dll`, `SimulationStream.Interop.dll`, `PerceptionSimulationInput.exe`).
This is the synthetic-input simulator. It documents pose/input data shapes at the API boundary but
contains none of the real tracking or fusion code. Mine it only after the priority group.

## 3. Tooling

**Native code (DLLs, drivers): Ghidra.** Free and scriptable, with better decompiler output than
radare2/Cutter for MSVC-compiled C++ with RTTI, which is what this stack is. Headless batch import
(`analyzeHeadless`) imports and analyzes the whole extracted set unattended and can be re-run on a
newer Windows build to diff decompiled output across versions (stable parts are safe to treat as
protocol spec; changed parts may be incidental). Requires a JDK (`openjdk-21-jdk` on Debian 13);
Debian does not package Ghidra, so download it from the official GitHub releases page and unzip it
somewhere like `/opt/ghidra`. The work here used Ghidra 12.1.2.

```sh
# One-time project creation + analysis of everything in the extraction dir:
analyzeHeadless /path/to/ghidra_projects WmrRE \
    -import /path/to/extracted/*.dll \
    -recursive \
    -processor "x86:LE:64:default" \
    -analysisTimeoutPerFile 600

# Re-run analysis only (project already populated), e.g. after adding scripts
# or re-extracting a newer build for diffing:
analyzeHeadless /path/to/ghidra_projects WmrRE \
    -process \
    -analysisTimeoutPerFile 600
```

Then open the project in the Ghidra GUI for interactive decompilation. Searching for the string and
constant values already known from `wmr_controller_protocol.c` / `wmr_protocol.h` (message type
bytes, HID report IDs, GUIDs) is the fastest way to locate the relevant functions inside a huge DLL.
Keep the Ghidra project directory outside this repo.

**Managed/.NET assemblies: ILSpy.** Parts of the Holographic/Perception stack and the Perception
Simulation tooling are managed or WinRT-projected. `ilspycmd` (needs `dotnet`) is the practical
Linux option and is easy to batch; the ILSpy/dnSpy GUIs are Windows-oriented. `monodis` is no use
(genuine .NET/WinRT, not Mono IL).

## 4. Workflow

1. Mount the Windows partition read-only (privileged; done by the operator, never by a script).
2. `scripts/extract-wmr-dlls.sh <mount-point> [output-dir]` copies the priority and secondary
   targets into a local output directory and writes `manifest.tsv` (relative path, destination,
   size, sha256) for provenance. It never mounts or uses sudo, shows what it found before copying
   (unless `-y`), and refuses a mount point that is not actually a mount. Re-running it after a
   Windows Update gives a diffable manifest.
3. Import the extracted binaries into a Ghidra project with `analyzeHeadless` (above).
4. Decompile target functions: start from known WMR protocol constants, then follow call graphs up
   and down to the controller-tracking fusion code and the tunnel framing/parsing code.
5. Cross-reference every finding against Monado's existing structs and message-ID enums in
   `wmr_controller_protocol.c/.h` and `wmr_protocol.h`. The deliverable is a diff: where Windows
   agrees with Monado's model, and where Monado's falls short (missing fields, wrong offsets,
   unhandled message types).
6. Write confirmed findings up as behavior-level notes (this directory) and as patches or comments
   against the Monado driver source, never as raw decompiled output.

## 5. IP caution

- Decompiled Microsoft (and any NVIDIA driver-adjacent) binaries are derivative works of
  proprietary code. Treat all decompiler output as confidential working material.
- Do not circulate decompiled or disassembled output, Ghidra project files or extracted DLLs
  anywhere public: not git, not upstream MRs, not forums, not chat.
- When contributing findings upstream, describe behavior only (message IDs, struct layouts,
  algorithms in your own words and code), the same standard as clean-room reverse engineering.
  Never paste decompiler-generated C, disassembly listings or Microsoft symbol/string names
  verbatim into a public issue, MR or commit.
- Keep the extraction output directory and Ghidra projects out of git entirely.
