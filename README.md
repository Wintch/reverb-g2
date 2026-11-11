# reverb-g2

Running an [HP Reverb G2](https://www.hp.com/gb-en/tech-takes/gaming/review/hp-reverb-g2-review.html)
on Linux — patches, tools, and a procedure manual covering everything from USB topology to
the NVIDIA display driver.

The headset is discontinued and Microsoft removed Windows Mixed Reality in Windows 11 24H2,
so on Windows a G2 now needs either 23H2 or [mbucchia's Oasis
driver](https://github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality). Good optics
going cheap on the used market, with no vendor behind them — which is the whole reason this
repo exists.

Everything documented here was measured on a real rig. Where something does **not** work,
the manual says why and what was tried, including the conclusions that turned out to be
wrong. Several of them did.

**Scope.** The repo is named for the headset, not for an operating system, but effectively
all of the engineering here targets Linux — that is where the headset is not supported and
where the work was needed. Chapters 09, 12, 31 and `windows-kit/` are Windows-side: they exist because
reading what Windows does to the panel is how several Linux questions got answered.

## The one rule that matters

**Verification is physical. Somebody has to put the headset on and look.**

The Vulkan/OpenXR layer reports a successful modeset and a happy 90.0 fps with the panel
completely dark. Every failure documented here is invisible from above the driver. Any
conclusion based on logs, `xrandr`, or a reported framerate is worthless on this hardware —
and this project produced four confidently wrong conclusions that were all reached that way.

## What works today (2026-11)

| Area | State |
|---|---|
| Headset display | ✅ 60 Hz via Monado direct mode, X11 and Wayland |
| 90 Hz | ✅ clean at both native modes (2880×1440 and supersampled 4320×2160), see below |
| Head tracking, 3DoF | ✅ solid (IMU, `WMR_SLAM=0`) |
| Head tracking, 6DoF | ✅ real Basalt SLAM, confirmed across multiple full game sessions (`docs/23`), with occasional divergence on long-uptime sessions (`docs/06`) |
| 360 / VR180 player | ✅ our own, built on `hello_xr`; 8K stereo at 60 fps |
| Headset audio | ✅ works electrically; shares a marginal USB2 contact with the panel, see `docs/22` |
| Controllers, orientation | ✅ 3DoF from the IMUs; buttons and battery fixed by the Monado series. The haptic output name resolves, but vibration over the headset tunnel does not work yet (0078, unapplied) |
| Controllers, position (6DoF) | ⚠️ optical constellation tracking worked on a lab branch (verified in a real game), but only its first steps are in the applied series. The rest, including the ghost-pose defenses, is in `patches/monado/unapplied/` and is **not part of the build** (`docs/03`, `docs/125`) |
| SteamVR (native) | ❌ `driver_monado` loads and sees the G2, but is blocked acquiring the display lease; xrizer is the working path |
| SteamVR titles (via [xrizer](https://github.com/Supreeeme/xrizer)) | ✅ multiple titles confirmed working end to end, bypassing `vrmonitor` entirely, see `docs/23` |
| Cable/connector | ⚠️ known marginal contact (USB2 branch + panel power); reseat procedure in `docs/22` |

## Status

- **90 Hz is solved** (2026-08-06) by `patches/nvidia/0004`. The panel flicker question is closed:
  60 Hz flickers on Windows too, and the flicker seen at 90 Hz had two software causes
  (`docs/112`).
- A full code review of the tooling and patches on 2026-10-12 (`docs/147`) found scripts that
  failed green and several real bugs. The fixes were built and verified on hardware
  (2026-10-13): the Monado camera teardown loop (8/8 clean), the NVIDIA 0002 lease hook
  (6/6 lease cycles, a worn check showed a 90 Hz panel), and the player's seek, frame step,
  recenter, audio hand-back and playlist.
- **Still unverified:** the neck-arm sign flip of Monado 0115 (needs a blind wearer A/B), and
  a game through the patched xrizer build (0014-0017).
- **Controller position tracking** is the main open engineering item. The unapplied Monado
  patches need a rebase onto one base before they can be built (`patches/monado/README.md`).
- **Pairing a new controller to the headset radio** still needs Oasis on Windows. Bonding to a
  host Bluetooth adapter works on Linux (`docs/136`, `docs/03`).
- **Monado pin:** the series stays on `735e29e4e`. Upstream moved, and bumping the pin needs a
  rebase of the whole series. Upstream MR status is in `docs/18`.
- `applies-on-base.txt` shows that every series applies on its pinned base (Monado 76, Basalt
  21, xrizer 17, hello_xr player 25). A from-scratch bootstrap on a clean machine has not
  been re-verified.

## What came out of this: an NVIDIA driver bug

While chasing 90 Hz we root-caused a separate bug in the NVIDIA display driver, filed
upstream as
**[open-gpu-kernel-modules#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275)**
(open as of 2026-08-06; check the PR for its current state):

> `nvDpyGetOutputColorFormatInfo()` treats "the EDID did not declare a color depth" as "the
> sink wants 6 bpc" and drives the DisplayPort link at 18 bpp. The DSI branch of the same
> function already treats that input as 8 bpc. This affects **any** DisplayPort sink that
> leaves EDID Color Bit Depth undefined — on an ordinary monitor it shows up as banding,
> which is easy to misattribute to the panel.

Full write-up in [`docs/13-bug-6bpc.md`](docs/13-bug-6bpc.md), and in the
[NVIDIA forum thread](https://forums.developer.nvidia.com/t/379240).

**It was the fix — confirmed 2026-08-06.** The patch (`patches/nvidia/0004`) stayed
unconfirmed for two extra days for a mundane reason, not a second bug: every retest after
applying it kept reusing the synthetic, injected EDID timings from the earlier
investigation instead of the panel's plain native mode.
[`docs/16-lab-vblank.md`](docs/16-lab-vblank.md) ran a careful factorial across refresh
rate, vertical blanking, and pixel clock on those injected timings and, correctly, found
none of them explained anything — the injected timings were never the actual problem. Once
the plain native EDID mode was retested with the patch applied, both native 90 Hz modes came
up clean. [`docs/13-bug-6bpc.md`](docs/13-bug-6bpc.md) separately closed the USB/HID side of
the investigation from the Windows angle: the headset's own status report is byte-identical
between Linux and Windows, including at the exact moment of a live 60↔90 Hz switch on
Windows (no special command fires). Filed as
[NVIDIA bug 5923212](docs/19-nvidia-bug-5923212-followup.md). Full three-day timeline,
including how the "still open" methodology trap was found, in
[`docs/21-project-retrospective.md`](docs/21-project-retrospective.md).

## Getting started

```bash
./scripts/bootstrap-lab.sh deps      # build dependencies, udev rules
./scripts/bootstrap-lab.sh nvidia    # the pinned NVIDIA driver; reboot afterwards
./scripts/bootstrap-lab.sh sources   # clone upstream at the pinned SHAs, apply patches
./scripts/bootstrap-lab.sh build     # Basalt, Monado, hello_xr, xrizer (xrizer needs Rust from rustup)
./scripts/bootstrap-lab.sh patch-nv  # the NVIDIA patches through DKMS; reboot afterwards
```

`sources` applies each series from its `patches/<series>/applies-on-base.txt`, generated by
`scripts/check-series-apply.sh`. All four series apply in full: Monado (76 patches, 74 clean
and 2 through the 3-way fallback), Basalt (21 files), xrizer (17) and the hello_xr player (25).
The Monado patches that do not apply on the pinned base live in `patches/monado/unapplied/`
and are not read by anything (see `patches/monado/README.md`).

Read [`docs/00-hardware-usb.md`](docs/00-hardware-usb.md) first. If the companion device
`03f0:0580` is missing from `lsusb`, the problem is the USB port, not the software — and
you will waste days debugging Monado if you skip that chapter.

## Daily bring-up (the step-by-step to actually turn it on)

Every session, in this order — this is the procedure, don't improvise it:

```bash
./scripts/preflight.sh               # 5-second READY/NOT READY check, no Monado started yet
```

`preflight.sh` checks, in order: (1) all 5 headset USB devices enumerated, (2) both
controllers paired **and** online (power them on first — there is no hot-add, see
`docs/03`), (3) the HMD's own DP connector actually up after `panel.py activate`. If it
says NOT READY, it also prints the concrete next action — usually a cable reseat, see the
ladder in [`docs/22-cable-connector-diagnosis.md`](docs/22-cable-connector-diagnosis.md).
Don't re-diagnose this in software before reading that chapter; it's exhausted.

Once `preflight.sh` says READY:

```bash
./scripts/jack-in-wayland.sh 1 6dof  # bring up the pipeline: mode 1 (4320x2160@90), real 6DoF SLAM
./scripts/play360.sh <file-or-dir>   # or launch a Steam title through xrizer, see docs/23
```

Use `jack-in-wayland.sh`, not `jack-in.sh` (X11 path, untested at 90 Hz since the bpc
fix). It needs the **"GNOME" entry under Wayland** at the login screen specifically —
not Plasma, not "GNOME" under X11. Nothing above is verified until a human has the
headset on and looks — see the rule right above.

Source trees are not vendored. `bootstrap-lab.sh` clones upstream at the exact SHAs the
patches were generated against and applies them, so this repo stays at a few megabytes and
it is obvious which changes are ours.

## Layout

```
docs/               the manual, one chapter per procedure
patches/nvidia/     open kernel module patches, incl. the 6 bpc fix
patches/monado/     WMR driver, tracking and pacing patches (+ unapplied/)
patches/basalt/     SLAM fixes and instrumentation
patches/xrizer/     OpenVR-on-OpenXR fixes for SteamVR titles
patches/hello_xr-player/   the 360/VR180 viewer
scripts/            tooling: bring-up, EDID surgery, HID capture, diagnostics
experiments/vblank/ an example NVKMS EDID-override config
forum-attachments/  the headset's EDID (serial zeroed) and decode, as posted to NVIDIA
windows-kit/        Windows-side bring-up and capture tools
tools/              ovrplugin-stub: a do-nothing OVRPlugin for native Unity VR games
web/                the credits and licenses page
```

## The manual

Hardware and bring-up

| | |
|---|---|
| [00](docs/00-hardware-usb.md) | USB topology, the SuperSpeed/USB2 split, and why it breaks |
| [01](docs/01-bringup-monado.md) | Building and running Monado + Basalt |
| [22](docs/22-cable-connector-diagnosis.md) | Link anatomy and piece-by-piece diagnosis of cable, connector and power |
| [63](docs/63-hardware-map.md) | Hardware map: every part we can name, and every one we cannot |
| [24](docs/24-safe-system-updates.md) | Keeping the install up to date without losing VR |
| [43](docs/43-autostart-modes.md) | Autostart modes and logging teardown |
| [46](docs/46-battery-management.md) | Battery management and the charge advisor |
| [47](docs/47-calibration-onboarding.md) | Calibration and onboarding: what is per-unit, what to check on a new G2 |

The 90 Hz work and the NVIDIA bug

| | |
|---|---|
| [04](docs/04-lab-90hz.md) | The 90 Hz lab: separate install, patched driver, test protocol |
| [13](docs/13-bug-6bpc.md) | The 6 bpc clamp: root cause and patch |
| [14](docs/14-nvidia-report.md) | The report filed with NVIDIA |
| [16](docs/16-lab-vblank.md) | The vblank factorial: injected timings (its conclusion was wrong) |
| [19](docs/19-nvidia-bug-5923212-followup.md) | Follow-up for the NVIDIA 60 Hz-only bug thread |
| [21](docs/21-project-retrospective.md) | Project retrospective: machines, timeline, fixes, credits |
| [112](docs/112-flicker-resolved-two-causes.md) | Flicker resolved: two causes, neither the panel |
| [51](docs/51-nvidia-display-allowlist-mismatch.md) | NVIDIA direct-mode allowlist mismatch |

Tracking, controllers, protocol

| | |
|---|---|
| [03](docs/03-controllers.md) | Controller state and the 6DoF roadmap |
| [12](docs/12-g2-protocol.md) | The G2's own protocol, from USB captures |
| [09](docs/09-oasis-driver-re.md) | What Windows sends the panel, from the Oasis driver |
| [34](docs/34-tracking-quaternions-slam.md) | 6DoF tracking, visual-inertial SLAM, quaternion math reference |
| [39](docs/39-slam-collapse-root-cause.md), [44](docs/44-clock-domain-skew.md), [40](docs/40-constellation-search-cpu-blowup.md) | SLAM pose-rate collapse, camera clock skew, constellation search CPU blow-up |
| [49](docs/49-controller-input-map.md) | Controller input map and the legacy-API buttons-dead bug |
| [83](docs/83-calibration-knobs.md) | Calibration and tuning knob catalog |
| [124](docs/124-prediction-error-instrument-and-offline-replay.md) | Prediction error instrument and offline replay |
| [125](docs/125-controller-6dof-root-cause-and-plan.md), [126](docs/126-constellation-blob-ownership.md) | Controller 6DoF position: root cause, blob ownership |
| [re-windows](docs/re-windows/README.md) | Reverse-engineering notes on the Windows driver |

Content, games, Windows

| | |
|---|---|
| [02](docs/02-player-360.md) | The 360/VR180 player: projections, pipeline, measurements |
| [23](docs/23-game-compatibility.md) | Game-by-game results via xrizer |
| [140](docs/140-games-and-approach-comparison.md) | Games tested and how our approach differs from Oasis |
| [08](docs/08-passthrough-limits.md) | Passthrough and its limits |
| [31](docs/31-windows-bringup-and-errors.md) | Windows bring-up and what SteamVR errors 108 / 422 mean |
| [60](docs/60-windows-usb-storm-control.md) | The Windows control for the USB2 storm |

Method, diagnostics, upstream

| | |
|---|---|
| [06](docs/06-known-issues.md) | What does not work and why, with evidence |
| [28](docs/28-log-map.md), [29](docs/29-source-map.md) | Where every log lives; every repo and thread this depends on |
| [32](docs/32-measurement-toolkit.md), [42](docs/42-diagnostic-playbook.md) | The measurement toolkit and how the tracking bugs were found |
| [10](docs/10-resources.md) | External resources |
| [17](docs/17-publishing.md) | Preparing this repo for publication |
| [18](docs/18-monado-upstreaming.md) | Upstreaming the Monado patches, MR status |
| [147](docs/147-full-code-review-2026-10-12.md) | Full code review, 2026-10-12 |

More chapters (power, presence, Oasis, Basalt upstream sync, MR test reports) are in
[`docs/`](docs/).

## Reference hardware

Debian 13 (trixie) · kernel 6.12 · RTX 3060 Ti (GA104) · HP Reverb G2 (rev B) ·
Ryzen 5 5600X · NVIDIA 595.71.05 open kernel modules

## Contributing

**The 90 Hz mystery is closed** (2026-08-06) — it was the NVKMS 6bpc clamp
([`patches/nvidia/0004`](patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch)),
confirmed with a clean image on real hardware at both native 90 Hz modes. A non-NVIDIA GPU
is no longer needed to make progress here — that bullet lived in this section for two days
while the root cause was still open; see
[`docs/19-nvidia-bug-5923212-followup.md`](docs/19-nvidia-bug-5923212-followup.md) and
[`docs/21-project-retrospective.md`](docs/21-project-retrospective.md) for the full story.

What would actually move this forward now:

- **A DisplayPort AUX-channel capture** (a logic analyzer on the AUX+/AUX- pins, decoding
  DPCD read/writes during a 60→90 Hz switch) is the one layer nothing in this repo has been
  able to look at yet — mainly useful now to confirm the backlight-duty hypothesis behind
  the (also resolved) flicker, not the core bug anymore.
- **More title reports through [xrizer](https://github.com/Supreeeme/xrizer)**,
  the working SteamVR path. Results go in `docs/23`.
- **Controller position tracking**: rebasing the unapplied Monado patches onto one base
  (`patches/monado/README.md`).

If you have (or can donate) an **HP Omnicept** — same headset, plus Tobii eye-tracking —
that matters too: Monado already treats it as a Reverb G2 at the USB level, so a 90 Hz
result there would show whether this is a G2 problem in general or specific to our unit.
See [`docs/10-resources.md`](docs/10-resources.md#the-omnicept-the-same-headset-inside-with-an-extra-sensor).

Everything in this repo is written in English. Measurements beat opinions: if you assert
something, say how you measured it.
