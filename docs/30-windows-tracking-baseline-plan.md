# 30 — Windows tracking-cost baseline: capture plan

Written 2026-08-13. Purpose: T166 declared a Windows-side CPU baseline for headset+controller
tracking as the explicit prerequisite before optimizing Basalt/constellation further — the
user's target is "this should run on a toaster", and until a Windows number exists there is
nothing concrete to optimize toward. This is the one-boot session plan to get that number,
plus the pose/calibration tracing options ranked. Designed against this repo's prior Windows
work (docs/07, docs/09, docs/12, windows-kit/) so it reuses tooling that already exists.

## Framing correction (read first)

There is no native WMR runtime path on this rig to trace. docs/19 already established the
Mixed Reality Portal route is dead (sensor driver exists, runtime/video stack does not) and
Oasis is what actually drives the G2 at 90 Hz on Windows here. **The baseline target is
`vrserver.exe` (SteamVR) hosting `driver_oasis.dll` + `HololensSensors.dll` in-process** —
all tracking cost for headset and both controllers lands in that single process, because the
controllers tunnel through the headset's HID stream (docs/12 §1, docs/03). Do not hunt for a
native WMR process, and do not trace host Bluetooth — the controllers structurally never
touch it (this machine does not even have BT hardware, and it never mattered).

`vrcompositor.exe` is rendering, not tracking. Log it separately if curious; never fold it
into the tracking number.

## 1. CPU baseline (the deliverable)

Conditions: SteamVR idle (no game), panel confirmed lit and stable before starting each
window (physical-verification rule applies). Two windows, back to back in one SteamVR
session, ≥2 minutes each: headset at rest, then continuously worn/moving.

```
typeperf "\Process(vrserver)\% Processor Time" "\Process(vrserver)\Thread Count" -si 1 -sc 120 -o vrserver-idle-rest.csv
typeperf "\Process(vrserver)\% Processor Time" "\Process(vrserver)\Thread Count" -si 1 -sc 120 -o vrserver-idle-motion.csv
```

Windows' `% Processor Time` is out of `100 × logical processors`: divide by 100 and report
**core-equivalents** ("N.NN of M cores"), the same unit CLAUDE.md uses for the Linux side
(~4.2 of 6 cores under 6dof+constellation before patch 0037).

Per-thread split (single- vs multi-threaded tracking, the Windows counterpart of the
SLAM_THREADS question): Process Explorer → vrserver.exe → Threads tab during the motion
window, screenshot it.

Per-module hotspots (where the cost actually goes — HololensSensors.dll blob/IMU work vs
driver_oasis.dll glue vs OS HID stack):

```
wpr -start CPU -filemode
:: run the rest+motion protocol
wpr -stop vrserver-cpu.etl
```

Open in WPA (Windows ADK → Windows Performance Toolkit; WPA is Windows-only — bringing the
raw .etl back is fine, note it needs a Windows machine to open), CPU Usage (Sampled),
filter vrserver.exe, group by thread then module/stack.

Pitfalls: disable Xbox Game Bar (it injects into these processes); no SteamVR overlays or
fpsVR during the windows; skip the first seconds after SteamVR launch (calibration read +
enumeration, see §2); confirm vrcompositor.exe stays low and flat during the windows before
trusting the vrserver number as tracking-only.

## 2. Pose/calibration tracing, ranked

a. **ETW providers** (`logman query providers | findstr /i "holographic perception"`) —
   expect silence: Oasis bypasses the native holographic runtime those providers belong to,
   and docs/09's import survey shows no custom ETW registration in the Oasis binaries. Run
   the query once to confirm-and-close, not to build on.

b. **USBPcap of `045e:0659` (HoloLens Sensors)** — the highest-value capture not yet done.
   docs/07 said to avoid this device (IMU firehose drowned the 90Hz investigation); for THIS
   goal the firehose is the signal. Three short captures (10-15 s): plug-in enumeration;
   first seconds of SteamVR/Oasis start (calibration block read — docs/12 §7 already decodes
   the sequence, this confirms Oasis reads the same block); steady-state worn/moving. The
   genuinely new data point: whether Oasis pulls camera frames at a different rate than
   Monado does (throttling/skipping under load). Parse with scripts/parse-usbpcap.py or the
   windows-kit tshark path — both exist.

c. **API Monitor on vrserver.exe (HID/SetupAPI filter)** — gives the tracking loop's actual
   poll rate (`HidD_GetFeature`/`ReadFile` call timing). docs/09's loose end (unexamined
   `.detourc`/`.detourd` Detours sections in driver_oasis.dll) lives at this tier. Only if
   §1's module breakdown raises a question that needs per-call resolution.

d. Thread/algorithm split — answered by the WPA view in §1, no extra capture.

## 3. Not worth doing

- Host Bluetooth tracing (structurally empty — controller tunnel, docs/12 §1).
- Re-disassembling Oasis for the calibration format (docs/12 §7 already has it from the
  Monado side; a capture confirming Oasis reads the same block is far cheaper).
- Resurrecting Mixed Reality Portal (closed in docs/19).
- DPCD/AUX sniffing (belongs to the finished 90Hz/bpc investigation, unrelated to pose).

## 4. One-boot checklist (~30-40 min)

Tools: Wireshark+USBPcap (already a windows-kit prerequisite), Process Explorer (portable —
worth adding to windows-kit/ alongside CRU/HWiNFO64), wpr.exe + typeperf (in-box), WPA (ADK,
install once or defer viewing).

1. Boot Windows, headset detected, SteamVR+Oasis functional, panel lit (physical check).
2. USBPcap #1: capture plug-in + SteamVR start + calibration read. Label `calib-startup`.
3. Fresh SteamVR relaunch; `wpr -start CPU` + typeperf; 2 min rest, 2 min motion; stop both.
4. During motion: Process Explorer Threads-tab screenshot.
5. USBPcap #2 during steady motion. Label `steady-motion`.
6. Optional (§2c): API Monitor, 30 s of motion, HID filter.
7. Copy back: both captures, the .etl, both csv, screenshots, plus one line per run
   (SteamVR + Oasis versions, condition, duration) and a hand-written note of what the
   panel showed at each step. One timestamped folder, windows-kit style.

Version caveat: docs/09's disassembly offsets were against the 2026-08-05/06 Oasis build; if
Steam auto-updated it, note the current version string — the architecture holds, the offsets
may not.
