# 21 — Project retrospective: HP Reverb G2 on Linux (2026-08-04 to 2026-08-06)

A from-scratch account of getting an HP Reverb G2 fully working on Linux against an NVIDIA
GPU: root-causing a driver bug NVIDIA had open since March, fixing four real reliability
bugs in Monado's WMR driver, and upstreaming all of it. Written for anyone landing on this
repo cold — NVIDIA engineers included.

## Machines

One physical box throughout: AMD Ryzen 5 5600X, NVIDIA RTX 3060 Ti (Ampere, GA104), HP
Reverb G2. Two separate Debian 13 installs on separate disks, switched by reboot: an everyday
system with Debian's proprietary, unpatched `nvidia-current` 550.163.01, and a lab system with
`nvidia-open` 595.71.05 plus the patches. Only the lab install gives valid display/driver
measurements. Per-machine details are in `docs/63-hardware-map.md`.

## What this was for

Get a Windows Mixed Reality headset (officially unsupported outside Windows) running on
Linux through Monado (Collabora's open OpenXR runtime): display, head tracking, both
controllers, and 90Hz — then fix what was actually broken instead of working around it, and
send every fix back upstream instead of keeping it as a local patch pile.

## What was found, in order

1. A USB topology bug (root disk sharing the same xHCI controller as the headset) caused full
   hangs; fixed by moving the root disk to SATA.
2. Display and head tracking worked at 60Hz but not 90Hz. The NVIDIA driver investigation ruled
   out DSC, color space and compositor differences (KWin vs. GNOME/mutter), and used custom
   Vulkan instrumentation to bypass the driver's own (misleading) success reporting.
   Cross-checking against an AMD GPU on the same panel showed the 90Hz failure is
   NVIDIA-specific, not a headset fault.
3. NVKMS clamps DisplayPort sinks to 6 bits-per-channel when the EDID leaves color depth
   undeclared, and this headset's EDID does exactly that. A two-line patch (`nvidia/0004`) fixed
   the clamp, but 90Hz still did not light at that point.
4. Re-testing at the plain native EDID timing with no synthetic override loaded showed 90Hz works
   cleanly, both at the native 2880x1440 and the supersampled 4320x2160 modes. The earlier
   vblank/bridge-chip factorial had been retesting synthetic, injected timings, so it was
   chasing a symptom of an outdated test rather than an independent bug.
5. The remaining intermittent 90Hz flicker had two causes: a color-alternating test pattern that
   strobes by construction (not the panel), and a stale backlight-duty state cleared by a reboot
   plus USB replug.
6. The WMR controller thumbstick-seek bug was root-caused (missing binding profile for the native
   `motion_controller` interaction profile) and fixed by `monado/0011`.

## Fixes and where they went

**NVIDIA (`nvidia-open` 595.71.05), 4 patches:**

| Patch | What | Status |
|---|---|---|
| `0001`–`0003` | VESA DisplayID/DSC/VSDB spec fixes, Wayland DRM-lease for VR HMDs, force max DP link config | From Project-VR (`AshishKumar4/Project-VR`), applied; 0002 was later modified here, 0003 is a confirmed no-op (`patches/nvidia/README.md`); prior art, not ours |
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

## Credits

- **Project-VR** (`AshishKumar4`): the three NVIDIA patches that made 90Hz reachable at all
  on this GPU generation; `nvidia/0004` is the fourth patch their series turned out to need
  on Ampere, reported back as a GitHub issue.
- **NVIDIA** (`abchauhan`): triaged and opened internal bug **5923212** in March 2026 from
  the original forum report.
- **Jan Schmidt / Nima01**: original authors of the Monado WMR driver code in which this
  project found and fixed real bugs. Jan's `dev-constellation-controller-tracking` branch is
  also the reference implementation of the WMR controller LED/timesync command that this
  project's early notes wrongly said did not exist (`docs/re-windows/04-led-model.md`). Review status of
  the MRs lives on the MR pages (index in `docs/18-monado-upstreaming.md`).

## Where things stand

For the current state of tracking, controllers and open issues see `docs/06-known-issues.md`
and `docs/63-hardware-map.md`.
