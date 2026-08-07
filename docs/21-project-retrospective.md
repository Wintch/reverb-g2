# 21 — Project retrospective: HP Reverb G2 on Linux (2026-08-04 to 2026-08-06)

A from-scratch account of getting an HP Reverb G2 fully working on Linux against an NVIDIA
GPU: root-causing a driver bug NVIDIA had open since March, fixing four real reliability
bugs in Monado's WMR driver, and upstreaming all of it. Written for anyone landing on this
repo cold — NVIDIA engineers included.

## Machines

Same physical box throughout: AMD Ryzen 5 5600X, NVIDIA RTX 3060 Ti (Ampere, GA104), HP
Reverb G2. Two separate Debian 13 installs on separate disks, switched by reboot:

| | everyday system | 90Hz lab |
|---|---|---|
| disk | `/dev/sda1`, plain ext4 | separate SSD, LUKS + LVM |
| NVIDIA driver | Debian's `nvidia-current` 550.163.01, proprietary, unpatched | `nvidia-open` 595.71.05, patched |
| role | day-to-day dev, code, docs, Resolve | the only place display/driver measurements are valid |

The everyday system can read/write the lab's disk without booting into it (LUKS+LVM mounted
read-only or read-write from the other install) — only the physical 90Hz measurements
themselves needed the lab OS booted natively with the patched driver.

## What this was for

Get a Windows Mixed Reality headset (officially unsupported outside Windows) running on
Linux through Monado (Collabora's open OpenXR runtime): display, head tracking, both
controllers, and 90Hz — then fix what was actually broken instead of working around it, and
send every fix back upstream instead of keeping it as a local patch pile.

## Timeline

**2026-08-04 (day 1) — bring-up, then the real investigation starts.** Repo initialized,
Monado + Basalt built locally, first VR180/360 player working. A USB topology bug (root
disk sharing the same xHCI controller as the headset) caused full hangs — fixed by moving
the root disk to SATA. By evening, display and head tracking were confirmed working at
60Hz; 90Hz was not. The rest of the day is the NVIDIA driver investigation: ruled out DSC,
color space, Wayland-vs-X11 compositor differences (KWin vs. GNOME/mutter), and built
custom Vulkan instrumentation to bypass the driver's own (misleading) success reporting.
By 23:05, cross-checking against an AMD GPU on the same panel confirmed the bug was
NVIDIA-specific, not the headset.

**2026-08-05 (day 2) — root cause found, then a real fix, then upstreaming.** 00:54: found
it — NVKMS clamps DisplayPort sinks to 6 bits-per-channel when the EDID leaves color depth
undeclared, and this headset's EDID does exactly that. A two-line patch (`nvidia/0004`)
fixed the clamp, but 90Hz still didn't light — a second, still-open question at the time.
Full write-up prepared and posted to NVIDIA's developer forum (bug thread 337744, plus a
dedicated thread for the bpc bug, 379240). Repo cleaned up for publication (English
filenames/docs, hardware identifiers redacted from published logs, personal AI-assistant
commit trailers stripped from the patches) and made public. In parallel: 10 Monado driver
patches reorganized into 4 upstream-ready branches, and the afternoon/evening went into a
vblank timing factorial trying to explain why 90Hz still failed post-patch — a real,
carefully controlled experiment that, in hindsight (see next day), was chasing a symptom of
an outdated test, not an independent bug.

**2026-08-06 (day 3) — the actual fix confirmed, controllers finished, everything sent
upstream.** Morning: re-ran the panel at its plain native EDID timing with no synthetic
override loaded, for the first time since the bpc patch existed — 90Hz worked cleanly, both
at the native 2880x1440 and the supersampled 4320x2160 modes. The vblank/bridge-chip
investigation from the day before had been retesting synthetic, injected timings the whole
time; nobody had gone back to the plain native mode after the fix landed. An intermittent
90Hz flicker (the one open question left) turned out to be two different things: a
color-alternating test pattern that strobes by construction (not the panel), and a stale
backlight-duty state that a reboot + USB replug cleared. Both NVIDIA forum threads were
edited with the corrected finding. Same day: root-caused and fixed the WMR controller
thumbstick-seek bug (missing binding profile for the native `motion_controller` interaction
profile — patch `monado/0011`), validated both controllers on real hardware, drafted the
GitHub issue reporting the Ampere validation back to Project-VR (whose 3 patches were the
starting point for the NVIDIA side of this work), and opened all 4 Monado MRs against
upstream `monado/monado`.

## Fixes and where they went

**NVIDIA (`nvidia-open` 595.71.05), 4 patches:**

| Patch | What | Status |
|---|---|---|
| `0001`–`0003` | VESA DisplayID/DSC/VSDB spec fixes, Wayland DRM-lease for VR HMDs, force max DP link config | From Project-VR (`AshishKumar4/Project-VR`), applied unmodified — prior art, not ours |
| `0004` | Don't clamp DP sinks to 6bpc when the EDID leaves color depth undeclared | **Ours.** Root cause of the 90Hz failure on this hardware. Filed as [PR #1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275) against `NVIDIA/open-gpu-kernel-modules` — **open, not yet reviewed or merged** as of 2026-08-06 (corrected; an earlier version of this doc wrongly said "accepted") |

**Monado, 11 patches, 4 upstream MRs against `monado/monado`:**

| Patch(es) | What | MR |
|---|---|---|
| `0001`–`0004` | Companion-device drop tolerance, firmware-read retry/validation, bounded controller-status wait, BT controller read resilience | !2967 `wmr-hid-resilience` |
| `0005`–`0008`, `0011` | Squeeze click, haptic name, input timestamps, opt-in stick deadzone, native `motion_controller` binding profile | !2968 `wmr-controller-input-fixes` |
| `0009` | `WMR_CAMERAS=0` to run without tracking-camera streaming | !2969 `wmr-camera-stream-toggle` |
| `0010` | `$ORIGIN` runtime path for SteamVR driver deps under pressure-vessel | !2971 `steamvr-drv-origin-rpath` |

Three of the four MRs fix real bugs in code originally written by **Jan Schmidt**
(`thaytan`) — the unbounded controller-status wait and the fw-command retry/validation gap
both trace back to his commits via `git blame` against upstream `main`. The fourth traces to
**Nima01**, who wrote the original (overly strict) companion-device error handling in 2020.

## Who did what

- **brunduk** (`nikolai.viktorovich@gmail.com`, `@Wintch`) — hardware in hand, every physical
  test/verdict, all decisions on what to pursue and what to drop, GitLab/GitHub accounts,
  every post and PR filed under their name.
- **Claude Code** — pair investigation throughout: instrumentation scripts, patch authorship,
  the vblank factorial design, root-cause write-ups, upstreaming prep. Not credited as
  co-author on the shipped patches (stripped deliberately, see `patches/monado` history) —
  noted here for an accurate account of process, not to relitigate that call.
- **Project-VR** (`AshishKumar4`) — the three NVIDIA patches that made 90Hz reachable at all
  on this GPU generation; this project's `nvidia/0004` is the fourth patch their series
  turned out to need on Ampere, reported back as a GitHub issue.
- **NVIDIA** (`abchauhan`) — triaged and opened internal bug **5923212** in March 2026 from
  the original forum report; no further response since, independent of this investigation.
- **Jan Schmidt / Nima01** — original authors of the Monado WMR driver code this project
  found and fixed real bugs in. Jan notified directly via a comment on !2968 (2026-08-06)
  explaining the three defects traced to his commits; no reply yet as of this writing.
  Nima01 not yet notified.

## State at the end of day 3

Working: display, Direct Mode, head tracking (Basalt SLAM), both controllers, clean 90Hz.
Still open: SteamVR's `vrmonitor` crashes on a missing Qt dependency inside Valve's own
sandboxed runtime (not a Monado bug); Basalt SLAM shows ~3° drift with the headset
stationary; controllers are 3DoF-only (no positional/constellation tracking upstream yet);
headset audio is intermittent, same symptom pattern as it had on Windows. Full detail in
`docs/06-known-issues.md`.
