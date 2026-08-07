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
where the work was needed. Chapters 07, 09, 10 and 12 are Windows-side: they exist because
reading what Windows does to the panel is how several Linux questions got answered.

## The one rule that matters

**Verification is physical. Somebody has to put the headset on and look.**

The Vulkan/OpenXR layer reports a successful modeset and a happy 90.0 fps with the panel
completely dark. Every failure documented here is invisible from above the driver. Any
conclusion based on logs, `xrandr`, or a reported framerate is worthless on this hardware —
and this project produced four confidently wrong conclusions that were all reached that way.

## What works today (2026-08)

| Area | State |
|---|---|
| Headset display | ✅ 60 Hz via Monado direct mode, X11 and Wayland |
| 90 Hz | ✅ clean at both native modes (2880×1440 and supersampled 4320×2160) — see below |
| Head tracking, 3DoF | ✅ solid (IMU, `WMR_SLAM=0`) |
| Head tracking, 6DoF | ⚠️ Basalt SLAM diverges (~3° drift while stationary) |
| 360 / VR180 player | ✅ our own, built on `hello_xr`; 8K stereo at 60 fps |
| Headset audio | ✅ works — the long-standing failure was a bad USB port |
| Controllers | ⚠️ 3DoF only (upstream driver limit); connection reliability fixed here |
| SteamVR | ❌ Valve packaging bug (`vrmonitor`/Qt); try [xrizer](https://github.com/The-personified-devil/xrizer) instead of OpenComposite (unmaintained since 2024) |

## What came out of this: an NVIDIA driver bug

While chasing 90 Hz we root-caused a separate bug in the NVIDIA display driver, filed
upstream as
**[open-gpu-kernel-modules#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275)**
(open, not yet reviewed or merged as of 2026-08-06):

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
./scripts/bootstrap-lab.sh deps      # build dependencies
./scripts/bootstrap-lab.sh sources   # clone upstream at the pinned SHAs, apply patches
./scripts/bootstrap-lab.sh build
./scripts/jack-in.sh                 # bring up the whole VR pipeline
```

Read [`docs/00-hardware-usb.md`](docs/00-hardware-usb.md) first. If the companion device
`03f0:0580` is missing from `lsusb`, the problem is the USB port, not the software — and
you will waste days debugging Monado if you skip that chapter.

Source trees are not vendored. `bootstrap-lab.sh` clones upstream at the exact SHAs the
patches were generated against and applies them, so this repo stays at a few megabytes and
it is obvious which changes are ours.

## Layout

```
docs/          the manual, one chapter per procedure
patches/nvidia/            open kernel module patches, incl. the 6 bpc fix
patches/monado/            WMR driver and SteamVR bridge fixes
patches/hello_xr-player/   the 360/VR180 viewer
scripts/       tooling: bring-up, EDID surgery, HID capture, diagnostics
experiments/   the headset's own EDID plus prepared variants for the 90 Hz work
```

## The manual

| | |
|---|---|
| [00](docs/00-hardware-usb.md) | USB topology, the SuperSpeed/USB2 split, and why it breaks |
| [01](docs/01-bringup-monado.md) | Building and running Monado + Basalt |
| [02](docs/02-player-360.md) | The 360/VR180 player: projections, pipeline, measurements |
| [03](docs/03-controllers.md) | Controller state and the 6DoF roadmap |
| [04](docs/04-lab-90hz.md) | The 90 Hz lab: separate install, patched driver, test protocol |
| [05](docs/05-resolve.md) | DaVinci Resolve (a separate goal for the same rig) |
| [06](docs/06-known-issues.md) | What does not work and why, with evidence |
| [07](docs/07-windows-hid-capture.md) | Capturing the Windows HID traffic (archived — see 09) |
| [08](docs/08-passthrough-limits.md) | Passthrough and its limits |
| [09](docs/09-oasis-driver-re.md) | Reverse-engineering the Oasis driver (what Windows sends the panel) |
| [10](docs/10-resources.md) | External resources |
| [11](docs/11-linux-hmd-landscape.md) | The state of HMDs on Linux |
| [12](docs/12-g2-protocol.md) | The G2's own protocol, from USB captures |
| [13](docs/13-bug-6bpc.md) | The 6 bpc clamp: root cause and patch |
| [14](docs/14-nvidia-report.md) | The report filed with NVIDIA |
| [15](docs/15-feedback-triage.md) | Triage of the feedback on that report |
| [16](docs/16-lab-vblank.md) | The vblank factorial: refresh rate vs. timing shape, run to completion |
| [17](docs/17-publishing.md) | Preparing this repo for publication |
| [18](docs/18-monado-upstreaming.md) | Upstreaming the Monado WMR patches |
| [19](docs/19-nvidia-bug-5923212-followup.md) | Follow-up for the NVIDIA 60Hz-only bug thread |
| [20](docs/20-desktop-plasma-crash.md) | A Plasma desktop crash hit during the lab work |
| [21](docs/21-project-retrospective.md) | Project retrospective: machines, timeline, fixes, credits |

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
  the (also resolved) flicker, not the core bug anymore. See the open item at the end of
  [`docs/13-bug-6bpc.md`](docs/13-bug-6bpc.md).
- **Testing the SteamVR path via [xrizer](https://github.com/The-personified-devil/xrizer)**
  instead of chasing the `vrmonitor`/Qt bug in Valve's own sandboxed runtime — not yet tried.

If you have (or can donate) an **HP Omnicept** — same headset, plus Tobii eye-tracking —
that matters too: Monado already treats it as a Reverb G2 at the USB level, so a 90 Hz
result there would show whether this is a G2 problem in general or specific to our unit.
See [`docs/10-resources.md`](docs/10-resources.md#the-omnicept-the-same-headset-inside-with-an-extra-sensor).

Everything in this repo is written in English. Measurements beat opinions: if you assert
something, say how you measured it.
