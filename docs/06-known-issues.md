# 06 — Known issues and why we're NOT chasing them (with evidence)

## The unpatched install runs at 60 Hz, and that is CORRECT — don't debug it

There are **two Linux installs, swapped into the same physical machine**. They are not
equivalent, and the difference is entirely in `patches/nvidia/`:

| | patched install | unpatched install |
|---|---|---|
| NVIDIA driver | 595-open **with** `patches/nvidia/0001-0004` | stock binaries, **unpatched** |
| desktop | GNOME on Wayland | KDE |
| display path | Wayland DRM lease (`jack-in-wayland.sh`) | X11 direct-mode (`jack-in.sh`) |
| refresh | **90 Hz** | **60 Hz** |

**The 60 Hz on the unpatched install is the expected, correct result, not a symptom, and nobody
should spend a minute debugging it.** Two of the four patches are load-bearing for exactly this:

- **`0004` (bpc)** is the entire 90 Hz fix. Without it the driver clamps the G2 to 6 bpc and the
  panel stays dark at 90 Hz (`docs/13`, `docs/19`). An unpatched driver *cannot* light 90 Hz.
- **`0002`** publishes `wp_drm_lease_device_v1` for HMDs and marks the connector `non-desktop=1`.
  Without it there is no Wayland lease path at all, and KWin never offers connectors even *with*
  the patch (measured repeatedly, see `check-lease.sh`). X11 direct-mode is the only possible path
  there.

**Corollary, so a red light there is not misread as hardware:** `check-lease.sh`, the
`non-desktop=1` check, step 3 of `preflight.sh` and all of `jack-in-wayland.sh` **cannot** work on
the unpatched install; they fail by construction. Do not diagnose the headset with them there.

The unpatched install is good for everything that does not touch the display path. The 6DoF work
(SLAM head tracking, constellation/LED controller tracking) is cameras over USB plus Monado plus
Basalt, driver-agnostic, so it can be developed there at 60 Hz. Before trusting any result from
that install, check the two things this project has been burned by: that `~/vr/monado` is
built by `bootstrap-lab.sh sources` from `patches/monado/` (the drift trap) and that
`~/vr/basalt/build/libbasalt.so` actually exists.

Applying `patches/nvidia/` there would give it 90 Hz and the lease path, but it is a deliberate
decision, not a default: it replaces the driver with 595-open (`bootstrap-lab.sh` refuses to run
when a different driver is loaded; the stacks are mutually exclusive), and `docs/20` documents that
a connected headset can take the KDE desktop down with it.

## Annoying "USB Audio" popup reconnecting every few seconds: silenced, not fixed

The headset audio (`0bda:4c15`) cycles disconnect/reconnect (~30 s historically, 5-10 s at worst).
The underlying cause of the USB cycling was not investigated; only the popup was silenced, in two
layers:

1. A WirePlumber rule (`scripts/wireplumber/51-disable-reverb-headset-audio.conf`, install to
   `~/.config/wireplumber/wireplumber.conf.d/`, then `systemctl --user restart wireplumber`) marks
   the device (`device.vendor.id`/`device.product.id` = `0bda`/`4c15`) as `device.disabled`, so
   WirePlumber never creates an audio node for it. Verified: `/proc/asound/cards` and `pw-dump` no
   longer list the device after a reconnection cycle.
2. That is not enough: the same device exposes a separate HID interface ("Generic USB Audio
   Consumer Control", media buttons) that **`systemd-logind` re-"watches" on every reconnection**
   (`Watching system buttons on /dev/input/eventN`), which kept triggering the popup.
   `scripts/72-reverb-audio-no-input-watch.rules` (install to `/etc/udev/rules.d/` +
   `udevadm control --reload-rules`) strips the `ID_INPUT_KEY` tag udev's `input_id` puts on that
   interface. Installed but not verified live on a real reconnection cycle.

This may be specific to one unit's condition rather than the G2 model in general.

## Headset audio and the missing USB2 branch: it was the connector, not the audio

> History: this was first filed as an incurable physical cable fault (false), then as a USB-port
> problem (partly), and finally traced to the **VISOR-END CONNECTOR**. The signature
> (`Cannot enable. Maybe the USB cable is bad?` + `error -71`, SuperSpeed OK / USB2 branch dead)
> came back **port-independent** (identical on three USB controllers across two machines), after
> the DP lanes and panel power had already died *with USB still healthy*. A "the cable died, buy a
> rev2A" verdict was issued, and then **reseating the detachable connector where the cable enters
> the visor (behind the magnetic face gasket) fixed every symptom at once**: USB2 branch, panel
> power, DP hotplug, 90 Hz. That single connector carries all four conductor groups, so one
> marginal contact mimics several independent faults; earlier "port or orientation fixed it" results
> most likely worked by mechanically disturbing that same connector. Full anatomy and the
> piece-by-piece ladder: `docs/22-cable-connector-diagnosis.md`. **If these symptoms appear: reseat
> the visor-end connector FIRST, ports second.**

The G2 cable carries a SuperSpeed branch and a USB 2.0 branch through the same port. On a bad seat
the SuperSpeed branch enumerates and **the USB 2.0 branch never trains the link**:

```
usb usb3-port2: Cannot enable. Maybe the USB cable is bad?
usb 3-2: device not accepting address 6, error -71
usb usb3-port2: unable to enumerate USB device
```

Everything on that branch is missing: the companion `03f0:0580` (control HID **and** audio), so
Monado falls back to Simulated HMD and no audio device appears. In WMR terminology this is **error
7-14**, "required USB2 components not found", a documented G2 failure mode (extra-long cable, very
tight signal margins). Moving to another rear USB-A port, or rotating the USB-C plug 180° inside the
C-to-A adapter, often fixes it. **Try the port first, the orientation second.** The outcome depends
on the specific contact, not on which port: the fault moved with the headset when the cable was
moved, and the symptom is progressive (SuperSpeed without USB2, or SuperSpeed + sensors without the
companion). After a machine rearrangement the "seat lottery" got extreme (exactly ONE of the two
branches per seating, across 10 seats, on Linux and two Windows systems); the same ladder was the
fix, and `power-on.py` now walks it interactively per missing branch (`docs/22`, "The seat
lottery"). For the controller-level view of ports see `docs/00`.

### Correct enumeration — all five have to be present

```
3-1    04b4:6506  HP WMR hub (USB2)         480M
3-1.2  0bda:4c15  USB Audio                 480M   <- headset speakers + mic
3-1.3  03f0:0580  QHMD A85V s/n REDACTED   12M   <- companion, control HID
4-1    04b4:6504  HP WMR hub (USB3)        5000M
4-1.1  045e:0659  HoloLens Sensors         5000M
```

Count all five in `lsusb`, never "looks connected". If `03f0:0580` is missing, **don't debug
Monado** — check the port/connector. And **if the companion is missing, the display doesn't appear
either**: the panel does not link until it receives the WMR activation over HID, so `DP-0
disconnected` in xrandr with the headset plugged in does **not** mean a video or DP cable problem.

### The audio, how to find it

It enumerates as ALSA card `USB-Audio - Generic USB Audio` (`0bda:4c15`, Realtek chip), **with no
HP/Reverb/WMR string anywhere**, so checks grepping for `hp|reverb|wmr` report "no headset audio"
even when it is present. Sink `alsa_output.usb-Generic_USB_Audio-00.analog-stereo` + its source (the
microphone). The device misreports its volume range (`Unlikely big volume range (=800)`, PCM at
`-25600`) and PipeWire defers to that broken scale, so **a mid-range percentage can be inaudible:
always test at 100%**. The audio device that "appears, mutes and disappears" on Windows is the same
fault, not an operating-system problem.

## USB2 hub drops under load: it's NOT the PSU

With the panel on, the internal USB 2.0 hub (`04b4:6506`) resets every so often and takes the
companion `03f0:0580` and the audio down with it: clean disconnect and re-enumeration, no
`error -71`. Measured with a load gradient: 0/10 drops without Monado, 6/15 with panel + render.
That looked like a brownout ("replace the DC power supply"), and the conclusion was **withdrawn**:
on **Windows 11 the same headset and power supply ran for hours at 90 Hz** (more draw than our
60 Hz) without a drop, and killing Monado after a drop makes the companion **come back on its own
after ~5 seconds**; an electrical problem is not fixed by killing a process. **Do not buy a power
supply.** The follow-up below traced a large part of the user-visible damage to our own driver's
reconnect path; the drop itself is the marginal connector (`docs/22`).

## The wearer gets relocated on every companion drop (RESOLVED, patches 0093/0094)

The "flying away" / "I appeared far below the map" class (Dead Herring VR, Chornobayivka VR, ISS
Tour VR, Blast the Past, Vertical Shift, Sniper Elite VR...) was neither SLAM CPU starvation nor
the `pop_pose` crash: **every natural USB2 companion re-enumeration stalled the driver's shared
read loop (the IMU/camera reader) for 1.4-5.1 s**, and the backlog then poisoned the clock-offset
filter for another 3.5 s. Each link measured (`scripts/usb-reset-device.py --vid 03f0 --pid 0580`
reproduces it on demand):

1. Companion drops → patch 0090 reconnects (~3.3 s dead, fine). The reconnect path then did
   `os_hid_get_feature(WMR_CONTROL_MSG_IPD_VALUE)` on the fresh node, which never answers (0
   successes / 48 failures across logs) and blocks for the usbhid control-transfer timeout:
   **"proximity feature read took 1375 / 3990 / 5030 ms"**, inside `wmr_run_thread`, which is also
   the sensors reader.
2. The headset keeps sending; the kernel hidraw ring (64 reports) fills; the rest is lost.
3. On resume the ~60 buffered IMU samples arrive in one burst, each with
   `arrival - hw = true_offset + stall`. Through `m_clock_offset_a2b`'s 5%-per-sample filter, 64 of
   them drag `hw2mono` ~96% of the way to +stall: the **first live sample is stamped ~3 s in the
   future**, accepted as `last_imu_ns`, and every real sample for the next ~3.3 s is rejected as
   "from the past" (log signature `dropped 251/501/751/1001 ... 3.49 → 2.48 → 1.48 → 0.47 s`;
   camera bundles dropped the same way via `cam_hw2mono`). `docs/61` had read this as "the
   headset's internal clock is perturbed"; it was ours.
4. SLAM is blind for stall + rejection (~8 s), IMU-only extrapolation runs away → relocation.

**Fixes:** the reconnect's proximity read is off by default (`WMR_COMPANION_RECONNECT_RESYNC=1`
re-enables it); the IMU offset filter is backlog-aware: a sample >50 ms late that arrived faster
than real time keeps the held offset instead of teaching the filter, while late samples at the
normal rate for 25 in a row re-seed it (genuine clock restart). The run loop warns on any step
>50 ms. **Measured after:** one session with **66 natural + 3 forced re-enumerations** (~7/min,
the densest storm on record): 0 "from the past" rejections, 0 dropped frame bundles, 2 IMU bursts
of 54 ms, no reader stall above 60 ms except one 3.0 s `open()` (1 in 75). A worn run reported
that the view no longer flies away; the residual few-cm drift and readjust is `docs/58`'s, not
this.

## `monado-service` segfaults in Basalt's `pop_pose()` at teardown (FIXED, patch 0104)

`coredumpctl list monado-service` showed repeated identical crashes (21+ cores over the period),
which at first masqueraded as "the game crashed in ~8-10 s". Backtrace every time:

```
#0 basalt::vit_implementation::Tracker::pop_pose(vit_pose**) ()  <- SIGSEGV here
   from ~/vr/basalt/build/libbasalt.so
#1 xrt::auxiliary::tracking::slam::flush_poses (t=...)  at t_tracker_slam.cpp:1337
#2 receive_frame (t=..., frame=..., cam_index=3)         at t_tracker_slam.cpp:1952
#3 t_slam_receive_cam3 / xrt_sink_push_frame
#4 img_xfer_cb (xfer=...)  at drivers/wmr/wmr_camera.c:457   (libusb callback)
#5 wmr_cam_usb_thread (...)  at drivers/wmr/wmr_camera.c:281
```

Root cause (lifetime/teardown ordering): `xrt_frame_context_destroy_nodes` calls `break_apart`
newest-node-first, so the SLAM tracker's `tracker_stop` runs *before* the WMR camera source stops
its USB thread, and that thread's last frame lands in `flush_poses` → `pop_pose` on a stopped
tracker. **Patch 0104** puts a `shared_mutex` + `stopped` flag around every runtime call into the VIT
tracker, with `break_apart` taking it exclusive around the stop: 11 teardown cycles (8 bare, 3 with
Dreams of Dalí loaded, `scripts/teardown-stress.sh`) with 0 cores; see `patches/monado/README.md`
(the 0104 row). Patches 0095/0096 additionally join the camera USB thread in `wmr_camera_stop()`
(`wmr_camera_start()` never set `cam->running`, so the join was dead code until 0096).

Related residue: a differently shaped SIGSEGV directly in `receive_frame`
(`t_tracker_slam.cpp:2080`, main thread inside `libnvidia-eglcore`/`ioctl`) pointed at a second
race between EGL/Vulkan teardown and the camera thread, and one `jack-in-wayland.sh down` after a
30-min session **hung** instead of crashing (SIGTERM, "Still running after 10s, escalating to
SIGKILL", log ending after `COMP_DESTROY`). Same teardown-ordering family; if it recurs, capture
`gdb -p` / `thread apply all bt` before the 10 s escalation. Some of the "anchor age spikes to
seconds, controller flies away" findings in `docs/23` may in part have been this crash happening in
the background.

## Basalt SLAM diverges (6DoF head tracking)

An early measurement showed ~3° mean inter-frame error with the headset STATIONARY (spam of
`det(Q1Jl)==0`), with `WMR_SLAM=0` (IMU 3DoF, flawless) used for orientation-only content. **It
was NOT reproduced with a fresh build**: `~/vr/basalt` had in fact never been compiled on that
checkout (CMake configured, but no `libbasalt.so`; the build needs `libbz2-dev liblz4-dev
libssl-dev libepoxy-dev libyaml-cpp-dev libsqlite3-dev`). After a clean build, `WMR_SLAM=1`
(`cam_count=4`, `PositionTracking=True`) showed 20 s stationary-on-table inter-frame rotation mean
0.001-0.006°, max 0.04-0.14°, comparable to the 3DoF jitter floor, zero `det(Q1Jl)==0`. Later
SLAM work is in `docs/34`, `docs/39` and `docs/125`.

## SteamVR won't launch (and it's not our fault); OpenVR titles go through xrizer

The Monado driver for SteamVR loads fine (with patch 0010's RPATH + lib bundle), but Valve's
`vrmonitor` crashes due to a missing `libQt5Multimedia.so.5` **inside Valve's runtime container**.
OpenComposite is unmaintained since 2024; the active path is **xrizer** (OpenVR reimplemented on
top of OpenXR, runs against Monado without launching SteamVR). Traps found setting it up:

- Steam needs `nvidia-driver-libs:i386` for the 595 series (**not**
  `libgl1-nvidia-glvnd-glx:i386`, which only exists at the old 550 version and conflicts); xrizer
  builds with `cargo xbuild --release` and needs `libclang-dev` and `glslc`.
- Nothing registers `libopenxr_loader.so` via `ldconfig`, so xrizer's dynamic loader lookup fails
  silently with `ERROR_RUNTIME_UNAVAILABLE` even while Monado runs fine. Install
  `libopenxr-loader1` system-wide (or set `LD_LIBRARY_PATH` to the loader build dir).
- **Proton titles run inside Valve's Steam Linux Runtime container (pressure-vessel/bwrap), which
  sandboxes the environment: `XR_RUNTIME_JSON` from the launch options never arrives and the
  Monado IPC socket is not exposed.** Add
  `PRESSURE_VESSEL_FILESYSTEMS_RW=/run/user/1000/monado_comp_ipc` to the Steam launch options.
  With that, SUPERHOT VR reached a real session (image, sound, 90 Hz).
- The first batch of VR titles all failed for four **unrelated** reasons (an unrelated Proton/PhysX
  error, an xrizer `VR_InitInternal`/`dlclose` SIGABRT with an old Unity/Mono title, an unrelated
  Mono abort, and the container sandboxing above): fixing one does not fix the others. Check
  `~/.local/state/xrizer/xrizer.txt` timestamps to know whether a launch reached xrizer at all.

Per-title status lives in `docs/23-game-compatibility.md`.

## 90 Hz: resolved, and what NOT to re-investigate

**90 Hz runs clean on Ampere** with the bpc patch (`patches/nvidia/0004`) alone; what had been
missing was re-testing the EDID's native mode without an override after the patch was applied
(`docs/19-nvidia-bug-5923212-followup.md`). Dead ends of that investigation, so nobody repeats them:

- **Ruled out: "Monado is missing an HID command that requests the mode".** Monado's activation
  sequence is the same for 60 and 90 Hz, and disassembling the standalone Oasis driver (which runs
  the G2 at 90 Hz) shows its only panel command is *Display Enable* (HID usage page `0x03`, usage
  `0x21`), exactly the `{0x04, 0x01}` Monado already sends; there is no refresh-rate command. The
  panel adopts the refresh rate of the video signal it receives. Procedure and false positives
  (`HmdDriver_SetFrameRate` belongs to the cameras) in `docs/09-oasis-driver-re.md`.
- **Ruled out: DSC / DP bandwidth.** `2880x1440@90` (10.29 Gbps) requests less than half of the
  working `4320x2160@60` (17.02 Gbps) against 25.92 Gbps usable on 4 lanes HBR3, so it cannot need
  compression, yet it failed identically before the bpc fix.
- **Ruled out: display contention / GPU clock domains** (same failure with a single monitor and
  with the headset as the only display).
- The NVIDIA bug (internal 5923212) was acknowledged and reproduced by NVIDIA, and fails the same
  way on Turing, Ampere and Blackwell across 590.x-610.x; the working fix here is the open-module
  bpc patch (`docs/13-bug-6bpc.md`, `docs/19`).

### CAUTION: Project-VR is NOT a verified positive case

The early lab plan rested on [Project-VR](https://github.com/AshishKumar4/Project-VR) having the G2
at `4320x2160@90` on Linux. That claim does not hold up: 0 stars/forks/issues/PRs, zero external
mentions, **zero images or video across its 177 files**, a single initial-dump commit, validated
only on Ada (never Ampere), and its evidence for "90 Hz working" is a successful Vulkan/OpenXR
session and its logs, which is exactly the kind of evidence this project showed to be **compatible
with a dead panel** (the API reports 90.0 fps with the HP logo on screen). Its patches did not fix
the panel when installed here. Do not invest more time in them as they stand; the only way to
rehabilitate it is a photo or video of the panel lit at 90 Hz. General lesson: without a human
looking at the panel, "it works" is not evidence.

## Controllers: see docs/03 and docs/125

Upstream's WMR driver hardcoded controller position (3DoF only); connection reliability was fixed
in `patches/monado/0001-0004` and constellation 6DoF tracking is documented in `docs/03`,
`docs/125` and `docs/126`.

## System hangs

- **USB root disk sharing an xHCI controller with the headset** (+ autosuspend): a complete hang
  and truncated files. Chapter `docs/00` has the analysis and the procedures.
- **GPU VA-space exhaustion on an 8 GB-VRAM card** after ~20 consecutive Steam/Proton VR launches
  back-to-back at `4320x2160@90`, many torn down with `kill -TERM`: NVIDIA
  `gpu_vaspace.c:4547 _gvaspaceMappingInsert NV_ERR_INVALID_ARGUMENT`, then `Failed to allocate
  NVKMS memory for GEM object`, then a system-wide stall severe enough that `systemd-journald` hit
  its watchdog; only a hard power-cycle recovered it. **Practical rule for marathon sessions: 8 GB
  VRAM is a real ceiling. Do not chain many high-res Proton VR launches for hours without an
  occasional clean `jack-in-wayland.sh down` and a beat for the driver to settle, especially when
  killing titles by signal instead of their own quit path.** Any unattended long-running mode needs
  a periodic clean-restart policy for the same reason.

## The 45 / 30 fps ceiling across 17-20 titles (RESOLVED)

Not GPU (half the pixels, same 45 fps, 90 W), not tracking (survived 3dof), not engine age: the app
pacer. Full table and mechanism in `docs/23`, section "The fps ceiling was the app pacer, not the GPU, tracking or engines"; patch 0092 plus
`U_PACING_APP_USE_MIN_FRAME_PERIOD=true` as the launcher default. 44 → 89-90 fps on Dead Herring VR,
verified in the headset.

## The headset being connected can break the entire KDE desktop

Not the 90 Hz bug (`docs/13`) and more severe: with the headset connected, KDE Plasma X11 can end
up with no panel/icons, or a lock screen missing the password field, because `plasmashell`/`kwin`
lose their graphics context in a loop. Cause confirmed at least once: KDE had `DP-0` (the headset)
saved as a desktop monitor at 90 Hz. Detail, fix, and what remains unexplained in
**`docs/20-desktop-plasma-crash.md`**.

## Four NVIDIA symlinks were silently deleted from disk, invisible to apt/dpkg --audit

Not a headset bug: Plasma X11 would not render (`plasmashell` coredumping) because Xorg could not
load `glxserver_nvidia`. Root cause was a missing symlink dpkg still believed it owned; `dpkg -V`
(not `dpkg --audit`, which stayed clean throughout) found three more of the same class: NVDEC
(`libnvcuvid.so`/`.so.1`), VDPAU (`libvdpau_nvidia.so.1`) and CUDA (`libcuda.so`). Fix:
`apt-get install --reinstall` on the actual owning package (found with `dpkg -S`, not assumed from
the package name), plus the drift check now built into `pre-update-check.sh`. Full detail:
**`docs/73-nvidia-symlink-drift.md`**.

## "The panel flickers at 90 Hz" — check the test pattern before the panel (RESOLVED twice)

`hmd-vk` and `hmd-modeset` both alternate colour on every frame / page-flip by **design**, a
sync/lock-on check that is a ~30 Hz and ~45 Hz strobe respectively at 90 fps. To a wearer that is
indistinguishable from backlight flicker, and it is not the panel. This produced a false
confirmation twice (`docs/19`, `docs/112`), the second time despite the fix existing in the source.
Both tools now paint solid white under `HMD_VK_SOLID=1` / `HMD_MODESET_SOLID=1`, and every wrapper
that asks a human to look (`verify-bpc.sh`, `hmd-test.sh`, `collect-nv.sh`) sets the flag
automatically. **Before trusting any physical flicker verdict, confirm the run went through one of
those wrappers, or pass the flag by hand.**

Two related facts:

- **60 Hz flickers on this panel by design**: factory backlight behaviour at a non-native
  frequency, identical on Windows. 90 Hz is clean on both. Not a bug, do not investigate it.
- **A real content flicker** was the **xrizer brightness gain above 1.0**
  (`XR_KHR_composition_layer_color_scale_bias` → temporal dithering). Never ship that gain at
  anything but 1.0, and fix it in the user profile, not just the live file.
