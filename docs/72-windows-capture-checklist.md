# 72 — Windows capture session: standalone checklist (2026-08-25)

Written because the user is about to reboot into Windows and lose this Linux session — this
doc has to be followable alone, without the agent available mid-session. Manual capture only
(the PowerShell automation in `windows-kit/` and `windows-kit2/` never worked reliably for the
user) — plain Wireshark + USBPcap, driven by hand, with a manual timestamped log to correlate
offline afterward. One boot, bundles everything currently pending on the Windows side.

## 0. Why this session exists, in one line each

- **NEW (2026-08-25, the reason this doc exists today):** does Windows' camera driver
  (`HololensSensors.dll`) split its ~30 fps camera stream between SLAM and controller
  tracking the same way Linux's does (confirmed on Linux: `wmr_camera.c` tags every frame
  `WMR_FRAMETYPE_SLAM`/`WMR_FRAMETYPE_CONTROLLER` off its own header and routes each frame to
  exactly one consumer — 29-39% diverted to controllers whenever constellation runs, capping
  SLAM pose rate at ~21-24 Hz instead of 30). A static decompile of `HololensSensors.dll` hit
  a real wall today: its camera log strings live in `.rsrc` as WPP/ETW message-table
  resources, not directly-referenced string literals, so there is no code pointer to trace
  backward from — a **live capture is the only way left to answer this.**
- **Already pending (`docs/67` §3, "A-win"):** controller pulse-train command over the
  `0x06`/`0x0E` HID tunnel (`docs/re-windows/04`), magnetometer bytes (`docs/54` — Linux-side
  capture found the 12 "mag" bytes flat/dead, needs a Windows reference to compare
  byte-for-byte), a Windows CPU/tracking-cost baseline (`docs/30`), battery calibration
  (T227), and an OpenVR Benchmark pass-1 number (the project's "better than Windows"
  cutoff needs this).

## 1. Before rebooting into Windows

- [ ] Confirm Wireshark + USBPcap installed (component checkbox during Wireshark install),
      machine rebooted since installing it if this is the first time.
- [ ] Confirm both WMR controllers are charged and OFF (need them off, then on, during the
      capture — see step 3).
- [ ] Have a plain text file or notepad open to log timestamps by hand as you go — this
      replaces the script's automatic step-logging. Write `HH:MM:SS  <what just happened>`
      for every step below marked **[LOG]**.

## 2. Start the capture (do this FIRST, before touching the headset)

The headset's USB device spans **more than one USBPcap interface** ("two branches" per the
old script's own comment) — don't guess which one, capture all of them:

1. Open Wireshark → Capture → you'll see multiple entries named `USBPcap1`, `USBPcap2`, etc.
2. Start a capture on **every** `USBPcapN` interface shown (one Wireshark window per
   interface, or use `dumpcap` from a terminal per interface if that's easier — whatever's
   comfortable). Don't filter yet — filtering happens in analysis, not capture; a filtered
   live capture can silently drop the camera video traffic if the filter is HID-only.
3. **[LOG]** note the exact start time of each interface's capture.

## 3. The capture sequence (this is the part the timestamp log correlates against)

Run through this in order, logging **[LOG]** at each numbered step:

1. **[LOG]** Plug in the headset if not already connected (or power-cycle it if it was
   already on, so the capture sees the full enumeration).
2. **[LOG]** Wait for Windows to recognize `045e:0659` (Device Manager, or just wait ~10s).
   **Do NOT launch Oasis/SteamVR yet** — this is the "before tracking activates" window
   the pulse-train/frametype questions need a clean baseline for.
3. **[LOG]** Launch Oasis / SteamVR, wait for the panel to light and head tracking to start.
   **Controllers still OFF at this point.**
4. **[LOG]** Power ON the right controller. Note whether/when it shows as tracked in
   SteamVR's status window.
5. **[LOG]** Power ON the left controller. Same note.
6. **[LOG]** Hold still for ~30s (a clean "both controllers registered, head+controllers
   both tracking, nobody moving" window — this is the closest Windows-side equivalent to
   today's Linux `timing.csv` sessions, and the one to check for a frametype-style split).
7. **[LOG]** Wave BOTH controllers around deliberately for ~90s (rotate through multiple
   axes, tilt, roll) — same protocol `constellation-frame-fit.py`/docs/54 already use on
   Linux, needed for the magnetometer byte-for-byte comparison and useful for the
   frame-type question too (does diversion % change with active controller motion?).
8. **[LOG]** Play normally for ~2 minutes (real content, not just holding still) — the
   "2 min of play" A-win already asked for, and gives real camera-frame timing to compare
   against Linux's `timing.csv` inter-frame deltas.
9. **[LOG]** Power OFF one controller only, wait 10s, note in the log — useful reference
   point for the pulse-train/keepalive question (does Windows send anything different).
10. **[LOG]** Stop Oasis/SteamVR cleanly.
11. **[LOG]** Stop every USBPcap capture, save each as
    `windows-kit2/results/frametype-capture-<interface>-20260825.pcapng` (or wherever's
    convenient — just keep the interface number and date in the filename).

## 4. Separately, same boot: the other three A-win items

These don't need to be interleaved with the capture above — do them before or after, Oasis
already running is fine for all three:

- **CPU/tracking-cost baseline (docs/30 §1)**: `typeperf` commands are in that doc verbatim
  — run them for a 2-min idle-rest window and a 2-min motion window. **If `wpr`/WPA CPU
  trace also gets captured** (docs/30's per-module-hotspot section), that ETL, if it
  resolves symbols even partially, could ALSO answer today's frame-type question by showing
  which `HololensSensors.dll` functions are actually hot during tracking — worth doing even
  just for that, independent of the CPU-cost number itself.
- **Battery calibration (T227 `using_1v2_batteries`)**: see that note in `NEXT-STEP.md`'s
  history (search `T227`) for the exact protocol if not already memorized.
- **OpenVR Benchmark pass-1**: run it once at whatever resolution/settings the Linux-side
  pass-1 used (check `docs/67` §2's acceptance table, "Better than Windows" row) — this is
  half of the project's one honest head-to-head number, the Linux half is already done.

## 5. After rebooting back to Linux

Bring the `.pcapng` files and the manual timestamp log back (USB drive, network share,
whatever's easiest) and hand them to the next session — the analysis (tshark filtering,
correlating the frame-type/diversion question, comparing magnetometer bytes byte-for-byte,
reading the CPU baseline) all happens on the Linux side afterward, same as every prior
Windows capture in this project.
