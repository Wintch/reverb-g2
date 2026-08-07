# 06 — Known issues and why we're NOT chasing them (with evidence)

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

## Basalt SLAM diverges (6DoF head tracking)

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
Monado without launching SteamVR) — not tested yet.

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
