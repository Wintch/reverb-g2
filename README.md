# reverb-g2-linux

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
| 90 Hz | ❌ panel stays dark — root cause still open, see below |
| Head tracking, 3DoF | ✅ solid (IMU, `WMR_SLAM=0`) |
| Head tracking, 6DoF | ⚠️ Basalt SLAM diverges (~3° drift while stationary) |
| 360 / VR180 player | ✅ our own, built on `hello_xr`; 8K stereo at 60 fps |
| Headset audio | ✅ works — the long-standing failure was a bad USB port |
| Controllers | ⚠️ 3DoF only (upstream driver limit); connection reliability fixed here |
| SteamVR | ❌ Valve packaging bug (`vrmonitor`/Qt); OpenComposite is the way |

## What came out of this: an NVIDIA driver bug

While chasing 90 Hz we root-caused a separate bug in the NVIDIA display driver, filed
upstream as
**[open-gpu-kernel-modules#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275)**:

> `nvDpyGetOutputColorFormatInfo()` treats "the EDID did not declare a color depth" as "the
> sink wants 6 bpc" and drives the DisplayPort link at 18 bpp. The DSI branch of the same
> function already treats that input as 8 bpc. This affects **any** DisplayPort sink that
> leaves EDID Color Bit Depth undefined — on an ordinary monitor it shows up as banding,
> which is easy to misattribute to the panel.

Full write-up in [`docs/13-bug-6bpc.md`](docs/13-bug-6bpc.md), and in the
[NVIDIA forum thread](https://forums.developer.nvidia.com/t/379240).

**It did not fix 90 Hz.** That remains open. As far as we can tell there is not a single
confirmed human sighting of a Reverb G2 running 90 Hz on Linux, on any GPU — the claims we
could find all rest on API-level evidence, which this project has shown nine times is
compatible with a dead panel. The current lead is in
[`docs/16-lab-vblank.md`](docs/16-lab-vblank.md): across the three modes this headset
advertises, "90 Hz" and "short vertical blanking" are perfectly confounded, and the
experiment that separates them is prepared and unrun.

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
| [07](docs/07-captura-hid-windows.md) | Capturing the Windows HID traffic (archived — see 09) |
| [08](docs/08-passthrough-y-limites.md) | Passthrough and its limits |
| [09](docs/09-oasis-driver-re.md) | Reverse-engineering HP's Oasis driver |
| [10](docs/10-recursos.md) | External resources |
| [11](docs/11-panorama-hmd-linux.md) | The state of HMDs on Linux |
| [12](docs/12-protocolo-g2.md) | The G2's own protocol, from USB captures |
| [13](docs/13-bug-6bpc.md) | The 6 bpc clamp: root cause and patch |
| [14](docs/14-nvidia-report.md) | The report filed with NVIDIA |
| [15](docs/15-feedback-triage.md) | Triage of the feedback on that report |
| [16](docs/16-lab-vblank.md) | The open experiment: refresh rate, or timing shape? |
| [17](docs/17-publicacion.md) | Preparing this repo for publication |

## Reference hardware

Debian 13 (trixie) · kernel 6.12 · RTX 3060 Ti (GA104) · HP Reverb G2 (rev B) ·
Ryzen 5 5600X · NVIDIA 595.71.05 open kernel modules

## Contributing

If you have a G2 and Linux, the most useful thing you can do is run
[`docs/16-lab-vblank.md`](docs/16-lab-vblank.md) and report what the panel actually does.
The EDIDs are prepared; the experiment needs eyes.

Everything in this repo is written in English. Measurements beat opinions: if you assert
something, say how you measured it.
