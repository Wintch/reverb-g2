# 06 — Known issues and why we're NOT chasing them (with evidence)

## The second environment runs at 60 Hz, and that is CORRECT — don't debug it (2026-08-11)

There are now **two Linux installs on two SSDs, swapped into the same physical machine**.
They are not equivalent, and the difference is entirely in `patches/nvidia/`:

| | this lab SSD | the other SSD |
|---|---|---|
| NVIDIA driver | 595-open **with** `patches/nvidia/0001-0004` | stock binaries, **unpatched** |
| desktop | GNOME on Wayland | KDE |
| display path | Wayland DRM lease (`jack-in-wayland.sh`) | X11 direct-mode (`jack-in.sh`) |
| refresh | **90 Hz** | **60 Hz** |

**The 60 Hz over there is the expected, correct result, not a symptom, and nobody should
spend a minute debugging it.** Two of the four patches are load-bearing for exactly this:

- **`0004` (bpc)** is the entire 90 Hz fix. Without it the driver clamps the G2 to 6 bpc
  and the panel stays dark at 90 Hz — that is the whole saga in `docs/13` and `docs/19`.
  An unpatched driver *cannot* light 90 Hz. 60 Hz is the only mode that will ever work
  there.
- **`0002`** is what publishes `wp_drm_lease_device_v1` for HMDs and marks the connector
  `non-desktop=1`. Without it there is no Wayland lease path at all — and KWin never
  offers connectors even *with* the patch (measured repeatedly, see `check-lease.sh`).
  X11 direct-mode is the only possible path on that SSD, which is exactly what is used.

**Corollary, so a red light there is not misread as hardware:** `check-lease.sh`,
`drmprops`' `non-desktop=1` check, step 3 of `preflight.sh` and all of
`jack-in-wayland.sh` **cannot** work on the unpatched SSD. They will report failure by
construction. Do not diagnose the headset with them there.

What the second environment *is* good for: everything that does not touch the display
path. The 6DoF work (SLAM head tracking, and the constellation/LED controller tracking in
`patches/monado/0012`+) is cameras over USB plus Monado plus Basalt — driver-agnostic — so
it can be developed and exercised there at 60 Hz without disturbing the one install where
90 Hz is validated. Before trusting any result from that machine, check the two things
this project has already been burned by: that `~/vr/monado` is built from a clean `git am`
of `patches/monado/` (the drift trap, `docs/pruebas.jsonl` T068) and that
`~/vr/basalt/build/libbasalt.so` actually exists (T060).

Applying `patches/nvidia/` over there would give it 90 Hz and the lease path too, but it
is a deliberate decision, not a default: it means replacing the driver with 595-open
(`bootstrap-lab.sh` refuses to run when a different driver is loaded — the stacks are
mutually exclusive), and `docs/20` documents that a connected headset can take the KDE
desktop down with it.

## Annoying "USB Audio" popup reconnecting every ~30s: silenced, not fixed (2026-08-06)

The headset audio (see below, next section) is still cycling disconnect/reconnect roughly
every ~30s — that hasn't changed. What was added is a WirePlumber rule
(`scripts/wireplumber/51-disable-reverb-headset-audio.conf`, install to
`~/.config/wireplumber/wireplumber.conf.d/`, restart with
`systemctl --user restart wireplumber`) that marks that specific device
(`device.vendor.id`/`device.product.id` = `0bda`/`4c15`) as `device.disabled`, so that
WirePlumber never creates an audio node for it — with no node, there's no "device
connected/disconnected" event and the KDE popup no longer appears. The USB cycling at the
kernel level keeps happening exactly the same (visible in `journalctl -k`), it's just now
invisible to the user. Verified: `/proc/asound/cards` and `pw-dump` no longer list the
device after a reconnection cycle with the rule active.

**Note:** this isn't necessarily a defect of the G2 model in general — it could be specific
to this particular unit's condition (the same physical impact that caused the light leak
noted in `NEXT-STEP.md` of `linuxlab-kit` could plausibly explain this too). The underlying
cause of the USB cycling itself was not investigated, only the annoying symptom was
silenced.

**Second round (2026-08-06, later): the popup kept appearing despite the rule above.**
Cause: the WirePlumber rule only covers PipeWire's audio node — the `0bda:4c15` device also
exposes a separate HID interface ("Generic USB Audio Consumer Control", media buttons) that
**`systemd-logind` re-"watches" on every reconnection cycle** (`Watching system buttons on
/dev/input/eventN`), and that's what kept triggering the noise. This time the cycle measured
much faster than the historical ~30s — every 5-10s. Fix:
`scripts/72-reverb-audio-no-input-watch.rules`, install to `/etc/udev/rules.d/` +
`udevadm control --reload-rules`. It strips the `ID_INPUT_KEY` tag that udev's builtin
`input_id` puts on that interface, so logind stops treating it as a button device.
**Installed but not verified live yet** — the headset powered off right after installing the
rule; confirm on the next real reconnection cycle.

## Headset audio: RESOLVED — it was the USB port (2026-08-04)

> This section used to say the audio was an incurable physical cable fault. **That was
> false.** The error is left documented because it cost months of misdiagnosis.
>
> **Correction of the correction (2026-08-07, final): it was neither the port nor a dying
> cable — it's the VISOR-END CONNECTOR.** The same kernel signature documented below
> (`Cannot enable. Maybe the USB cable is bad?` + `error -71`, SuperSpeed OK / USB2 branch
> dead) came back overnight, this time **port-independent** (identical on three USB
> controllers across two physical machines, T039-T040), after the DP lanes and panel power
> had already died hours earlier *with USB still healthy* — so the corollary below
> ("companion missing → display missing, check USB first") did **not** explain that first
> phase. A "the cable died, buy a rev2A" verdict was issued... and then **reseating the
> detachable connector where the cable enters the visor (behind the magnetic face gasket)
> fixed every symptom at once** — USB2 branch, panel power, DP hotplug, 90Hz, everything
> (T041). That single connector carries all four conductor groups, which is why one
> marginal contact can mimic several independent faults, including this section's whole
> 2026-08-04 saga: the port/orientation changes that day most likely "worked" by
> mechanically disturbing the same connector, and "the cable's signal margins are so
> tight that the outcome depends on the specific contact" was literally true — the
> contact in question just wasn't at the PC end. Full measured anatomy and the
> piece-by-piece diagnostic ladder: `docs/22-cable-connector-diagnosis.md`. If these
> symptoms appear: reseat the visor-end connector FIRST, ports second.

The G2 cable carries a SuperSpeed branch and a USB 2.0 branch through the same physical
port. On the USB-A port we were using, the SuperSpeed branch enumerated fine and **the USB
2.0 branch never trained the link**:

```
usb usb3-port2: Cannot enable. Maybe the USB cable is bad?
usb 3-2: device not accepting address 6, error -71
usb usb3-port2: unable to enumerate USB device
```

Everything living on that branch was missing: the companion `03f0:0580` (control HID **and**
audio). That's why Monado fell back to Simulated HMD and why no audio device appeared. In
WMR terminology this is **error 7-14**, "required USB2 components not found", a documented
G2 failure mode: the cable is extra long and leaves USB signal margins very tight.

**Moving the headset to a different rear USB-A port fixed it completely.** Zero `error -71`
since then. Rotating the USB-C connector 180° inside the C-to-A adapter also helped on its
own (it brought up the HoloLens sensors). Try the port first, the orientation second.

> **Revalidated 2026-08-13 (T171), and generalized**: after a machine rearrangement the
> seat lottery got extreme — exactly ONE of the two USB branches per seating, across 10
> seats, on Linux and both Windows systems. The port-then-orientation ladder above was
> again the exact fix, and `power-on.py` now walks it interactively, per missing branch.
> Full pattern table and evidence: `docs/22`, "The seat lottery (T171)".

### Correct enumeration — all five have to be present

```
3-1    04b4:6506  HP WMR hub (USB2)         480M
3-1.2  0bda:4c15  USB Audio                 480M   <- headset speakers + mic
3-1.3  03f0:0580  QHMD A85V s/n REDACTED   12M   <- companion, control HID
4-1    04b4:6504  HP WMR hub (USB3)        5000M
4-1.1  045e:0659  HoloLens Sensors         5000M
```

If `03f0:0580` is missing, **don't debug Monado** — check the port.

### Important nuance, measured in the lab (2026-08-04, afternoon)

"Changing ports" turned out to be an incomplete description of the fix. Reproduced
methodically in the lab:

1. Initial state: only the SuperSpeed hub (`04b4:6504`) enumerated, nothing behind it.
   `usb3-port2: Cannot enable` + `error -71` on the USB2 branch.
2. The cable was moved to a different rear USB-A port. **The fault moved with the
   headset**: it shifted to `usb3-port3`, same `error -71`. That **rules out the port as
   the cause** — what did change is that the `045e:0659 HoloLens Sensors` appeared.
3. Only when reseating the whole assembly (cable + USB-C orientation in the C-to-A adapter)
   did all five enumerate at once.

In other words: this cable's signal margins are so tight that the outcome depends on the
specific contact, not on which port it is. **The symptom is progressive, not binary** — you
can have SuperSpeed without USB2, or SuperSpeed + sensors without the companion. Cutoff
criterion: count all five in `lsusb`, never "looks connected".

Corollary for diagnosis: **if the companion is missing, the display doesn't appear either**.
With `03f0:0580` absent, `DP-0` shows `disconnected` in xrandr and the kernel sees no new
DisplayPort sink, because the panel doesn't link until it receives the WMR activation over
HID. Seeing `DP-0 disconnected` with the headset plugged in **doesn't** mean a video or DP
cable problem: check the USB first.

### The audio, how to find it

It enumerates as ALSA card `USB-Audio - Generic USB Audio` (`0bda:4c15`, Realtek chip),
**with no HP/Reverb/WMR string anywhere**. That's why checks grepping for `hp|reverb|wmr`
reported "no headset audio" even when it was present. Confirmed audible 2026-08-04, and
stable: 30 seconds of continuous playback without a single dropout.

Sink `alsa_output.usb-Generic_USB_Audio-00.analog-stereo` + its source (the microphone). The
device misreports its volume range (`Unlikely big volume range (=800)`, PCM at `-25600`) and
PipeWire defers to that broken scale, so **a mid-range percentage can be inaudible: always
test at 100%**.

This also explains the symptom the user had been suffering on Windows all along (audio
device that appears, mutes, and disappears). It was never an operating-system problem.

## USB2 hub drops under load: it's NOT the PSU (2026-08-04, afternoon)

With the panel on, the internal USB 2.0 hub (`04b4:6506`) resets every so often and takes
the companion `03f0:0580` and the audio down with it. Clean disconnect + clean
re-enumeration, no `error -71`. Measured in the morning with a load gradient: 0/10 drops
without Monado → 6/15 with panel + render. That looked like a brownout, and the morning's
conclusion was "replace the DC power supply".

**That conclusion is withdrawn.** Evidence from the user: on **Windows 11 the same headset,
same power supply, same everything, ran for HOURS at 90Hz** (which draws more than our
60Hz) without a single drop. If current were insufficient, Windows would drop too — the
hardware doesn't know which OS is running. The only fragile thing on Windows was always the
audio (device that appears, mutes, disappears), meaning the audio branch is problematic on
both OSes on its own.

Also reproduced twice today: companion drops during hours of use → `kill` Monado →
**comes back on its own after ~5 seconds**. An electrical problem doesn't get fixed by
killing a process.

**Current hypothesis:** Monado's WMR driver handles HID reports (keepalive/state)
differently than the Windows stack, and something about that traffic — or its absence —
makes the headset firmware recycle the hub. It correlates with load because Monado under
load changes its HID timing. Pending: instrument `wmr_hmd.c` (logging every report +
timestamps) the next time it drops. **Do not buy a power supply.**

## `monado-service` segfaults in Basalt's `pop_pose()` — real crash, not the CPU-load story (2026-08-21, T243-night)

**This is a different, sharper bug than the anchor-age/CPU-contention narrative built up over
most of `docs/23`'s T243-night sweep.** Caught live while debugging why DOOM VFR kept
"crashing" in ~8-10s: the *game* was fine — `monado-service` itself was segfaulting, taking
the whole session down with it. `coredumpctl list monado-service` shows **five identical
crashes the same night**, starting well before DOOM VFR was ever touched:

| Time | PID |
|---|---|
| 22:45:51 | 18998 |
| 22:55:45 | 25380 |
| 23:16:31 | 33635 |
| 23:35:04 | 45741 |
| 01:18:27 | 10549 |

Same backtrace every time (`coredumpctl gdb monado-service -q` on the saved core, `bt`):

```
#0 basalt::vit_implementation::Tracker::pop_pose(vit_pose**) ()  <- SIGSEGV here
   from /home/iam/vr/basalt/build/libbasalt.so
#1 xrt::auxiliary::tracking::slam::flush_poses (t=...)
   at /home/iam/vr/monado/src/xrt/auxiliary/tracking/t_tracker_slam.cpp:1337
#2 receive_frame (t=..., frame=..., cam_index=3)
   at .../t_tracker_slam.cpp:1952
#3 t_slam_receive_cam3 (sink=..., frame=...)
   at .../t_tracker_slam.cpp:2096
#4 xrt_sink_push_frame (...)  at .../include/xrt/xrt_frame.h:75
#5 img_xfer_cb (xfer=...)  at .../drivers/wmr/wmr_camera.c:457
#6-9 libusb-1.0.so.0 internals
#10-11 libusb_handle_events_{timeout_}completed
#12 wmr_cam_usb_thread (...)  at .../drivers/wmr/wmr_camera.c:281
```

**Reads as a real race, not a config issue**: the crash fires inside `Tracker::pop_pose()`,
called from `flush_poses` on the camera-frame-receive path, itself invoked from a libusb
callback running on the dedicated `wmr_cam_usb_thread` — i.e. Basalt's pose queue is being
popped from a background USB delivery thread, and something about that access pattern
(use-after-free, unguarded concurrent access, queue underflow) crashes it. Reproduced 5/5
times the same way across a night that ran SLAM continuously for hours under heavy,
variable load — consistent with a race that needs sustained real-world triggering, not a
one-line config mistake.

**Reframes a lot of the same night's `docs/23` findings**: the "anchor age spikes to
seconds, controller flies away" pattern documented across Dead Herring VR, Chornobayivka VR,
ISS Tour VR, Emergence, and Aliens Attack VR may in several cases be **this crash happening
silently in the background** (the compositor and game can keep running briefly on stale
poses right up until the whole service dies) rather than purely "SLAM/constellation is too
CPU-expensive for this box" as read at the time. The two explanations aren't mutually
exclusive — heavy CPU load plausibly makes the race easier to hit — but this is a real,
locatable bug in `t_tracker_slam.cpp`/`libbasalt.so`'s queue handling, not just a resource
ceiling. **Not yet fixed or minimally repro'd** — next step is reading `pop_pose()`'s actual
implementation and `flush_poses()`'s call site for the missing lock/lifetime, then trying to
trigger it on demand (rapid session start/stop under camera load looks like the likeliest
lever, going by the crash's own call stack).

## Basalt SLAM diverges (6DoF head tracking)

> **Update 2026-08-07 (T060): NOT reproduced with a fresh build, don't treat this entry
> as current status without retesting.** Discovered while investigating that
> `~/vr/basalt` had in fact never been compiled on this machine/checkout (CMake was
> configured but `build.ninja`/`libbasalt.so` never existed -- three dependency groups
> were missing: `libbz2-dev liblz4-dev libssl-dev` then `libepoxy-dev libyaml-cpp-dev
> libsqlite3-dev`, none fully documented together before). After building clean and
> running `WMR_SLAM=1` (`cam_count=4`, `PositionTracking=True`), 20s stationary-on-table
> showed inter-frame rotation mean 0.001-0.006°, max 0.04-0.14° -- comparable to the
> 3DoF jitter floor, zero `det(Q1Jl)==0` spam. Whether this is a newer upstream Basalt
> commit behaving differently, or the original ~3° measurement came from a different
> environment/calibration, is unknown -- no verified SLAM data existed in this exact
> repo/machine before today. Not yet tested: worn/moving tracking quality, longer
> sessions, or interaction with the marginal USB2 contact (docs/22) since the tracking
> cameras are on the separate USB3 branch. Full detail in `docs/pruebas.jsonl` T060.

~3° mean error between frames with the headset STATIONARY (spam of `det(Q1Jl)==0`).
`WMR_SLAM=0` (IMU 3DoF, flawless) is used for everything orientation-only. Investigation
pending: calibration? environment visual texture? exposure? With 90Hz closed (2026-08-06)
this is now the top technical unlock; note the related-but-distinct constellation route
for controller 6DoF already has a trial merge paused awaiting Monado MR feedback
(`docs/03`, "Positional tracking").

## SteamVR won't launch (and it's not our fault)

The Monado driver for SteamVR loads fine (with patch 0002's RPATH + lib bundle), but
Valve's `vrmonitor` crashes due to a missing `libQt5Multimedia.so.5` **inside Valve's
runtime container**. Recommended path: ~~OpenComposite~~ — unmaintained since 2024. The
active replacement is **xrizer** (OpenVR reimplemented on top of OpenXR, runs against
Monado without launching SteamVR).

> **Update 2026-08-07 (T063): xrizer tested, builds and partially works, not usable yet.**
> Full setup done from scratch: Steam installed (needs `nvidia-driver-libs:i386` for the
> 595 driver series — **not** `libgl1-nvidia-glvnd-glx:i386`, that package only exists at
> the old 550 version and conflicts), Rust via rustup, xrizer built with `cargo xbuild
> --release` (needs `libclang-dev` and `glslc` beyond what's documented anywhere else in
> this repo), `openvrpaths.vrpath` pointed at the build. Real trap found: nothing on this
> system registers `libopenxr_loader.so` via `ldconfig` — xrizer's dynamic loader lookup
> silently fails with `ERROR_RUNTIME_UNAVAILABLE` unless launched with `LD_LIBRARY_PATH`
> including `~/vr/OpenXR-SDK-Source/build/src/loader`, even though Monado itself is
> running fine (confirmed live with `hello_xr` against the same service at the same
> moment). With that fixed, tried two OpenVR titles: **NVIDIA VR Funhouse** never reached
> VR init at all (blocked earlier by an unrelated GPU PhysX/CUDA error under Proton, not
> investigated). **InCell VR** (native Linux, Unity/Mono) reproducibly `SIGABRT`s inside
> xrizer's own `VR_InitInternal` → `dlclose` (confirmed 3x via `coredumpctl`), crashing
> before xrizer's own log (`~/.local/state/xrizer/xrizer.txt`) even records the attempt —
> looks like a real xrizer/old-Mono interop bug, not a config issue here. **Verdict: not
> usable yet on this rig, on either available title** — but the setup is fully in place
> (source at `~/vr/xrizer`, `openvrpaths.vrpath` configured, the `LD_LIBRARY_PATH` fix
> known) for whoever picks this up next. Full detail in `docs/pruebas.jsonl` T063.
>
> **Same-day follow-up (T064-T065): batch-tested every VR title downloaded, all fail, for
> FOUR unrelated reasons — this is not one bug.** `libopenxr-loader1` was installed
> system-wide via `apt` (superseding the `LD_LIBRARY_PATH` workaround above for native
> processes). InMind VR: user-confirmed physically (grey blank 2D window, headset
> backlight-only) that it crashes before ever touching xrizer — a Mono runtime abort
> unrelated to VR. **SUPERHOT VR (Proton)**: reveals a new, different blocker —
> `XR_RUNTIME_JSON` set via Steam launch options never reaches the process at all, because
> Proton titles run inside Valve's Steam Linux Runtime container (pressure-vessel/bwrap),
> which sandboxes the environment. Neither the `LD_LIBRARY_PATH` fix nor the system-wide
> loader package changed the result — confirmed via `xrizer.txt` timestamps that fresh
> attempts still fail identically. No system-wide `/etc/xdg/openxr/1/active_runtime.json`
> exists as a fallback either. **Net result: Funhouse, InCell, InMind, and SUPERHOT each
> fail for a DIFFERENT root cause** (unrelated Proton/PhysX error; xrizer's own
> `VR_InitInternal` crash; an unrelated Mono crash; container env sandboxing) — fixing one
> would not fix the others. Full detail in `docs/pruebas.jsonl` T064-T065.
>
> **Update, same night (T066-T067): SUPERHOT's container-sandboxing blocker cracked — xrizer
> WORKS.** The missing piece for SUPERHOT (Proton): the Steam Linux Runtime container
> doesn't expose the Monado IPC socket by default, even with `XR_RUNTIME_JSON` correctly
> set — add `PRESSURE_VESSEL_FILESYSTEMS_RW=/run/user/1000/monado_comp_ipc` to the Steam
> launch options. With that, SUPERHOT VR reached a real session: image, sound, `90Hz`,
> confirmed by the user. Along the way, fixing the right-controller registration bug
> (T051) properly at the source (`patches/monado/0012`, an `&&`/`||` bug in the bounded
> status wait in `wmr_hmd.c`) got both controllers showing up in Monado for the first time
> all project. **Still open**: SUPERHOT's own buttons (grab, menu/quit) don't respond
> in-game even with both controllers correctly registered and `hello_xr` confirming clean
> `oculus/touch_controller` bindings — not yet isolated to Monado vs. xrizer, planned next
> step is `XRT_DEBUG_GUI=1`'s live controller panel. First real, working, non-trivial
> xrizer session this project has had.

## RESOLVED (2026-08-06, afternoon) — everything below in this section has been superseded

**90Hz runs clean on this very GPU (Ampere, no AMD or any other new hardware).** The bpc
patch (`patches/nvidia/0004`) was the complete solution — what was missing wasn't another
cause, it was re-testing the EDID's native mode without an override after the patch was
applied, which nobody had done until that day. Full detail:
`docs/19-nvidia-bug-5923212-followup.md`. The analysis below (including the "corollary"
that no confirmed human case exists with any GPU) is kept as-is for the investigation's
record — don't take it as current status.

## 90Hz — the 595-open patches do NOT fix it (2026-08-04, 18:55)

Belief at the time: NVIDIA driver bug (5923212), not hardware or Monado; no upstream fix
through 610.x inclusive; the lab with a patched 595-open was the active plan.

**Measured: not enough.** With Project-VR's three patches installed via DKMS and the
patched module confirmed loaded in memory, both 90Hz modes still leave the panel stuck on
the HP logo — identical to the unpatched baseline. Physical verification, six cases, full
table in chapter 04. The 60Hz control run afterward gave a perfect image, so the setup was
healthy.

### RULED OUT: "missing an HID command that requests the mode from the headset" (2026-08-04, 21:00)

Belief at the time, written up as a live hypothesis in chapter 04 and in `CLAUDE.md`:
Monado's WMR driver sends the same activation HID sequence for both 60 and 90Hz
(`wmr_hmd.c:767`), and the "90Hz patch" only sets `nominal_frame_interval_ns` for pacing
(`wmr_hmd.c:1992`) — it doesn't touch the panel. That's what led to all of `docs/07`
(capturing Windows' HID traffic).

**It's false, and there are two independent pieces of evidence:**

1. **By argument (19:30):** Project-VR reaches `4320x2160@90` with patches to the video
   driver and no proprietary command whatsoever.
2. **By reading the binary (21:00):** the Windows disk's NTFS partitions were mounted
   read-only and the **Oasis Driver** was disassembled — the standalone driver that runs
   the G2 at 90Hz and talks to the headset directly, bypassing the OS's WMR runtime. Its
   **only** panel command is *Display Enable* (HID Usage Page `0x03` VR Controls, Usage
   `0x21`), which is exactly the `{0x04, 0x01}` that Monado already sends. There is no
   refresh-rate command. Procedure and false positives in **`docs/09-oasis-driver-re.md`**.

The two false positives not to chase again: `HmdDriver_SetFrameRate` belongs to the cameras
(`IspFrameRate`/`SensorFrameRate`, same as `OV7251SetFrameRate`), and `Detected change of
refresh rate` is SteamVR's internal bookkeeping around `Prop_DisplayFrequency_Float`.

**Conclusion: Monado's HID sequence is correct and sufficient. The panel adopts the refresh
rate of the video signal it receives.** `docs/07-windows-hid-capture.md` is now archived —
no need to boot Windows.

Process note: this hypothesis died twice because between the first and second time,
`CLAUDE.md` was left out of date still treating it as live, and it got cited again as "the
only one that explains the results". When closing out a line of investigation, update
`CLAUDE.md` **in the same commit**.

### CAUTION: Project-VR is NOT a verified positive case (2026-08-04, 23:00)

The entire lab plan rested on [Project-VR](https://github.com/AshishKumar4/Project-VR)
having the G2 running at `4320x2160@90` on Linux. **That claim doesn't hold up.**

- 0 stars, 0 forks, 0 issues, 0 PRs. Zero external mentions anywhere on the web.
- **Zero images or video across its 177 files.** A single initial-dump commit (2026-07-03).
- Validated on Ada (RTX 4080), never on Ampere.
- And the decisive point: its evidence for "90Hz working" is **a successful Vulkan/OpenXR
  session and its logs** — exactly the kind of evidence this project already demonstrated
  nine times over is **compatible with a dead panel**. The API happily reports 90.0 fps
  with the HP logo on screen.

It would be the fourth false positive in the same family as the cable, the power supply,
and the audio: a conclusion accepted as good without a human ever looking.

**Do not invest more time in its patches as they stand.** The only way to rehabilitate it
is to ask the author for a photo or video of the panel lit up at 90Hz.

Uncomfortable corollary: **there is NOT A SINGLE confirmed human case of a G2 at 90Hz on
Linux, on any GPU** — not even AMD. We'd been asking ourselves why it wasn't working for us
when it worked for others; maybe it never worked for anyone.

### The NVIDIA bug is cross-cutting and still open (2026-08-04)

From the forum thread (internal bug **5923212**): NVIDIA **acknowledged and reproduced**
the bug on 2026-03-20, and it's still unresolved as of 2026-07-19. It fails the same way on
**Turing, Ampere, and Blackwell** (2070 SUPER, 3090, A5000, 5070 Ti) and across the 590.x to
610.x series.

This explains why Project-VR's 3 patches changed nothing: if the bug lives in the GSP
firmware or the closed userspace blob, no patch to the *open kernel modules* can reach it.
And it shifts the goal: from "find the right patch" to "confirm which layer it lives in and
contribute evidence to the bug report".

### RULED OUT: DSC as the cause (2026-08-04, 21:30) — the fourth bandwidth theory to fall

With the HID theory dead, the suspect was DSC: Project-VR's patch 0001 claims to fix the
*"90 Hz handshake"* for DSC 1.1. But the headset's EDID numbers don't support it:

| mode | pixel clock | 24 bpp | works? |
|---|---|---|---|
| 2880x1440@90 | 428.6 MHz | **10.29 Gbps** | NO |
| 4320x2160@60 | 709.1 MHz | 17.02 Gbps | YES |
| 4320x2160@90 | 905.4 MHz | 21.73 Gbps | NO |

Link: 4 lanes HBR3 = **25.92 Gbps** usable. The `2880x1440@90` mode requests less than half
of the working `4320x2160@60`: **it can't need compression**, and it fails just the same.
DSC could at most explain the 4320@90 mode at 30 bpp, not the other one. Full table and the
test still to run, in chapter 04.

### Ruled out: display contention / GPU clock domains

Different from the DP cable bandwidth (above): this was about the display engine with
multiple active heads. Tested with a single monitor and with **zero** — the headset as the
system's only display — and the panel is still off. Also, the failing 90Hz mode uses less
pixel clock (428 MHz) than the working 60Hz mode (709 MHz). This isn't it.

## Controllers: 3DoF only

Code limitation in the upstream WMR driver (hardcoded position). Constellation roadmap in
chapter 03. We already fixed connection reliability (patches/monado/0001-0004).

## Full system hang 2026-08-04 (resolved by design)

USB root disk sharing an xHCI controller with the headset + autosuspend. Chapter 00 has the
analysis and the procedures. That morning's truncated .mp4 files (marsa*, missing moov
atom) are not recoverable — re-download them.

## Full system hang after a long Steam/Proton VR marathon (2026-08-21, T243-night)

Different from the 2026-08-04 hang above (that one was USB/xHCI). ~20 consecutive Steam VR
titles launched back-to-back over several hours (`docs/23`'s T243-night sweep), many torn
down with `kill -TERM` rather than a clean in-game exit, on an **8GB-VRAM** card at
`4320x2160@90`. `journalctl -b -1` shows NVIDIA driver GPU virtual-address-space errors
starting ~20 min before the freeze (`gpu_vaspace.c:4547`, `_gvaspaceMappingInsert`
`NV_ERR_INVALID_ARGUMENT`), then `Failed to allocate NVKMS memory for GEM object`, then a
cascading system-wide stall severe enough that `systemd-journald` itself hit its 3-minute
watchdog timeout — required a hard power-cycle, no clean shutdown possible. No single
culprit title identified; reads as cumulative GPU VA-space exhaustion from rapid repeated
Proton/DXVK launches, not a bug in any one title. **Practical rule for marathon sessions**:
this machine's 8GB VRAM is a real ceiling — don't chain many high-res Proton VR launches for
hours without an occasional clean `jack-in-wayland.sh down` + a beat to let the driver settle,
especially when killing titles by signal instead of their own quit path. Feeds
`idea_arcade_mode_headless_vr` (agent memory) — any unattended long-running mode needs a
periodic clean-restart policy for exactly this reason, not just crash recovery.

## The headset being connected can break the entire KDE desktop (2026-08-06)

This isn't the 90Hz bug (`docs/13`) — it's different and more severe: with the headset
connected, KDE Plasma X11 can end up with no panel/icons, or with a lock screen missing the
password field, because `plasmashell`/`kwin` lose their graphics context in a loop. Cause
confirmed at least once: KDE had `DP-0` (the headset) saved as a desktop monitor at 90Hz.
Detail, fix, and what remains unexplained in **`docs/20-desktop-plasma-crash.md`**.

## Known broken hardware

- 16GB RAM (upgrade to 32 planned); zram configured at 100% with zstd.
- 1.8TB NVMe entirely NTFS (Windows) — the ideal future setup should give Linux a native
  partition for Resolve media/scratch.
