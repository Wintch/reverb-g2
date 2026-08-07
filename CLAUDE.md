# Context for the 90Hz lab agent

> ## RESOLVED (2026-08-06, evening) — 90Hz works clean, no AMD or anything else needed
>
> The bpc patch (`patches/nvidia/0004`) was the complete solution. Nobody had gone back to
> test the native EDID modes without override after installing it — testing it
> clean, `2880x1440@90` and `4320x2160@90` come up perfect. This **supersedes item 2 of
> the "in order of weight" list below** (getting an AMD GPU for the lab) — it's no longer
> needed, don't chase it if this document comes up in a new session. Full detail in
> `docs/19-nvidia-bug-5923212-followup.md` and the entire project summary in
> `docs/21-project-retrospective.md`. **Watch out with the NVIDIA PR:** further down this
> document says "the bpc bug is closed and published" — that's about the investigation, NOT
> about the PR. `github.com/NVIDIA/open-gpu-kernel-modules/pull/1275` is still **`open`,
> unmerged** (verified 2026-08-06 via the GitHub API, after someone on LVRA pointed it out —
> the retrospective had this same error, now fixed). Don't assume "merged" without checking
> the API again before saying so anywhere public.
> `docs/11-linux-hmd-landscape.md` and the 90Hz sections of
> `docs/06-known-issues.md` got a correction note added at the top, but
> keep the old analysis as-is — don't take it as current status without reading the note.

> ## STATUS AS OF 2026-08-06 — new bug, distinct from the 90Hz one: the headset can break the desktop
>
> With the headset connected, **KDE Plasma (X11) can become unstable to the point of losing
> the panel/icons**, or the lock screen shows only the clock with no password field.
> Confirmed cause at least once: KDE saved `DP-0` (the headset) as a desktop monitor
> enabled at 90Hz — the same mode with the unstable DP link that `docs/13` already
> documents — and that takes down the entire compositor with it (`QRhiGles2: Context is
> lost` in `plasmashell`/`kwin`). Fix: `kscreen-doctor output.DP-0.disable`. **But the crash
> recurred later with DP-0 already disabled** (on the lock screen), so there may be a second
> problem unrelated to the headset. **Same-night update: `kscreen-doctor disable` doesn't
> actually turn off DP-0 while hot** (neither raw RandR nor NVIDIA's native MetaMode manage
> it while the headset stays connected — all three methods fail, see the doc) — that's
> probably why it "recurred" with DP-0 supposedly off. The workaround that did work was
> moving the windows trapped on DP-0 with a KWin script (D-Bus), not touching the display.
> Full detail, working snippets, and the "what to pick back up" list in
> `docs/20-desktop-plasma-crash.md`. **Before debugging any desktop weirdness with
> the headset connected, run `kscreen-doctor -o` and check whether DP-0 is `enabled`** —
> and if there are windows that don't show up, suspect they landed there before spending
> time on anything else.

> ## STATUS AS OF 2026-08-05 (night) — read this before anything else
>
> The bpc bug is **closed and published**:
>
> - **PR on NVIDIA:** https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275
> - **Forum thread:** post 379240, revision 6, corrected and with all three attachments
> - With the patch, the headset's 33-byte HID status ends up byte-for-byte identical to
>   Windows'
>
> **The full factorial in `docs/16-lab-vblank.md` has already been run** (7 points, EDIDs
> injected via nvkms override): it ruled out vblank (both in lines and in time), refresh
> itself, and bandwidth. The only pattern that survived was "the only pixel clock that ever
> showed an image is the one from the 60Hz mode that already worked" — there's no second
> hidden variable in the EDID. **Don't go back down that road**: the user decided to pivot to
> reporting instead of continuing to generate EDIDs blindly, and that decision still stands.
>
> **The headset's USB/HID channel is also exhausted**, not only at steady state (this
> document already said so early on 2026-08-05) but during the live TRANSITION: a 60↔90
> refresh change was captured without reconnecting the headset (`windows-kit/`, see
> `docs/13-bug-6bpc.md` section "2026-08-05 (night)") and no special command or HID report
> appears at the moment of the change — only the usual `DEVICE_STATUS` updating
> refresh/htotal/vtotal. The NVIDIA panel and Windows Settings are no use either for
> checking DSC: the Reverb G2 doesn't show up there as a selectable display (it's in
> direct/HMD mode).
>
> **Conclusion: there's nothing left to investigate with user-level tools, on either
> OS.** What follows, in order of weight:
>
> 1. The report to NVIDIA (bug 5923212, body ready in `docs/19-nvidia-bug-5923212-followup.md
docs/20-desktop-plasma-crash.md >>> THE CONNECTED HEADSET BREAKS THE KDE DESKTOP <<<`)
>    — the user uploads it himself.
> 2. An AMD GPU might arrive at the lab to repeat the 90Hz test on `amdgpu` — it's the
>    experiment most likely to move the needle (see `docs/11`), it's not a surprise if it
>    shows up.
> 3. Sniffing the DisplayPort AUX channel with a logic analyzer — noted, not attempted,
>    depends on having the hardware (see the checklist at the end of `docs/13`).
>
> `windows-kit/` ended up consolidated as a general-purpose tool (`run-diagnostics.ps1`, a
> single command) — not as a list of pending 90Hz tasks. If something says "still need to
> run one more Windows capture", be skeptical: that channel has already been fully mined.
>
> ### Publication
>
> The repo is going to be published on GitHub (`Wintch/reverb-g2`). There are two blockers,
> see `docs/17-publishing.md`. The lab's SSH key is already generated at
> `~/.ssh/id_ed25519`. This repo's git identity already points to gmail.


You are on a **brand-new, clean** Debian 13 install, on a dedicated SSD, whose sole
purpose is to test whether the HP Reverb G2 can run at **90 Hz** with the patched NVIDIA
595-open driver. This repo is all the accumulated knowledge of the project. Read it before
proposing anything: several things have already been tried and ruled out with measurement.

## The goal, in one line

**Get the headset panel to stop flickering.** The flicker is the strobe of the G2's
low-persistence backlight at 60 Hz, and it's inherent to 60 Hz mode. The only cure is
reaching 90 Hz. This isn't a performance goal: the user explicitly said video fps are
secondary compared to the flicker.

## Where to start

1. `docs/04-lab-90hz.md` — the full lab plan, step by step. This is your script.
2. `scripts/bootstrap-lab.sh` — automates steps 1 through 4 of that document.
3. `docs/06-known-issues.md` — what NOT to chase again.

Actual order:
```bash
./scripts/bootstrap-lab.sh deps
./scripts/bootstrap-lab.sh nvidia      # and REBOOT
./scripts/bootstrap-lab.sh sources
./scripts/bootstrap-lab.sh build
# baseline WITHOUT patches: confirm 90Hz STILL fails (step 3 of chapter 04)
sudo ./scripts/bootstrap-lab.sh patch-nv    # and REBOOT
# and only then, the 90Hz test
```

**Don't skip the baseline without patches.** It's what separates "the 595 driver alone
changed something" from "the patches fixed it", and it's the only way to know what to
report.

### Where things stand (2026-08-05, 09:15) — report published; needs EDITING

The report was published: [thread 379240](https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240)
(no replies yet). External feedback came in with six items; the full triage, with each
one checked against what's already been measured, is in **`docs/15-feedback-triage.md`**.

**Urgent: the published post has an error and needs editing before more people read it.**
It says *"its DisplayID 2.0 extension carries only a Type VII timing block"*. It's
DisplayID **1.2** and the block is Type I. The conclusion doesn't change and the argument
gets **stronger**: `nvt_edid.c:1101` branches by version (`(pExt[1] & 0xF0) == 0x20`), so
the G2 goes through the DisplayID 1.3 parser, which **never writes `digital.bpc`** —
meaning the clamp to 6 bpc is unavoidable for *any* DP sink with DisplayID 1.x that leaves
depth undeclared.

Full corrected body, ready to paste over the original, in **`docs/14`**. Attachments
already assembled in `forum-attachments/` (raw EDID + 8-bpc repro EDID + annotated decode,
the patch, and the `nvidia-bug-report.log.gz`). There's also text ready to open the issue
on `NVIDIA/open-gpu-kernel-modules`.

**From the feedback, what was already closed** (don't redo it):

- *"Apply the Project-VR patches on top of the bpc one and bisect"* — all three are already
  applied (`PATCH[0..2]` in `dkms.conf`) plus `0004`. The current result **is** the full
  stack on GA104. And there's no verified positive case on Ada to port anything from.
- *"It could be the color space"* — the EDID itself rules it out: CTA-861 byte 3 = `0x00`,
  the headset doesn't advertise YCbCr 4:4:4 or 4:2:2. The link is mandatorily RGB in all
  three modes.
- *"Compare the modeline derived from the EDID against the one nvkms programs"* — done by
  hand (`scripts/edid-tool.py decode`): they match exactly in all three modes. There's no
  second root cause there.

**What's still open, in order:** (2) refresh sweep at 61/72/75/80 Hz — the one that
discriminates most, unblocked by going back to X11 with `Option "CustomEDID"`, which had
been dropped for convenience, not for technical reasons; (3) USBPcap capture on Windows of
the 60→90 transition (the Oasis disassembly only bounds what that binary can send, not what
goes over the bus, and the `driver_oasis.dll` Detours are still unexamined); (4) DPCD via RM
control call, expensive and probably redundant.

#### Previously (2026-08-05, 05:15) — the bpc patch half-works, and the software route is exhausted

**Update (01:50): the firmware route is exhausted too.** `NVreg_EnableGpuFirmwareLogs=1`
enabled and tested — the driver explicitly says it's missing `gsp_log_ga10x.bin` to
log the GSP firmware. Downloaded NVIDIA's full official installer (403 MB) to
look for it: **NVIDIA doesn't distribute it there either** — the installer's
`gsp_ga10x.bin` is byte-for-byte identical (same MD5) to the one we already had. The logic
that decides the 90Hz handshake runs in closed firmware with no public version to speak of.
Full detail in `docs/13-bug-6bpc.md`.

With DSC, color space, and the modeline also ruled out already (see below), **what can be
investigated from Linux without NVIDIA's help is exhausted.** The next step is to report,
not keep digging alone.

#### Previously (2026-08-05, 05:15) — the bpc patch half-works

**The bpc bug was real and the patch works exactly as the code predicted: the headset's
byte 18 went from 06 to 08.** But that did NOT fix the 90Hz. Physical verification:

- `4320x2160@90` and `2880x1440@90` (two bandwidths that differ by 2x): BOTH now
  show **white flicker, no color** — before it was a static logo with no activity. Real
  progress, but not the fix.
- `4320x2160@60` (control, with the same patch): still shows normal colors.
- Since both 90Hz modes fail the same way despite having very different bandwidths, **it's
  not a MIPI bandwidth limit**.

**The most important finding: the state the headset now reports is BYTE-IDENTICAL to
Windows'** (the 33 bytes of `DEVICE_STATUS`, including byte 11 which had been pending — it
got fixed by the bpc change alone). Meaning what this measurement channel can tell us is
exhausted: the headset tells the host the same thing it tells Windows, and the visual
result is different. The missing difference isn't visible from this angle — it has to be
looked for in NVIDIA's logs (silent DSC? RGB vs YCbCr color space? fine timing that
htotal/vtotal don't capture?).

Full detail and the concrete next step (run through `collect-nv.sh` with the patch
applied): **`docs/13-bug-6bpc.md`**.

#### Previously (2026-08-04, 20:45)

**The entire second display path was tested — Wayland + DRM lease on GNOME/mutter — and
90Hz fails identically. Eight failures now. The cause can barely be in NVIDIA.**

The lease **works**: Debian 13's mutter 48.7, unpatched, offers the headset's connector
(`connector 130 DP-1 (HPN)`), Monado leases it and takes `4320x2160@90.00`. That rules out
the NVIDIA forum thread about DRM lease: **the culprit for that block was KWin**, which
advertises the device but offers zero connectors. And yet, with the lease granted and the
90 mode taken, the panel is still dead with the HP logo. The 60Hz control over the **same**
path gave a perfect image. Table and logs in `docs/04-lab-90hz.md`, "GNOME/mutter run".

We swapped X11 Direct-Mode for Wayland DRM lease — two mechanisms that share almost no
driver-side code — and the symptom didn't move. Added to the fact that the patched
595-open failed the same as the unpatched one, there's almost nothing left on the
display-path side.

To check the lease without bringing up Monado: `scripts/check-lease.sh`.

**And the two remaining hypotheses got closed, both by evidence:**

- **There's NO missing mode HID command.** The Oasis driver was disassembled (the one that
  drives the G2 at 90Hz on Windows, talking to the headset directly). Its only panel
  command is *Display Enable* — HID Usage Page `0x03`, Usage `0x21` — which is exactly the
  `{0x04,0x01}` Monado already sends. **There's no refresh-rate command.** Method, false
  positives, and firmware strings in `docs/09-oasis-driver-re.md`. `docs/07` is now
  archived: no need to boot Windows.
- **It's NOT DSC.** From the headset's EDID: `2880x1440@90` needs **10.29 Gbps**, less than
  half of the `4320x2160@60` that works perfectly (17.02), against a 25.92 Gbps link. That
  mode can't need compression and it fails the same. Fourth bandwidth theory ruled out by
  measurement.

**The only thing the two failing modes share is 90 Hz.** It's not bandwidth, it's not
compression, it's not a missing command, it's not the display path, it's not head
contention, it's not the power supply or the cable.

**The cheapest discriminating test that has NOT been run:** `2880x1440@90` (mode 0) via
Wayland DRM lease — `./scripts/jack-in-wayland.sh 0`. It's only been tested on X11.

#### Previously (2026-08-04, 19:10): the 595-open patches do NOT fix 90Hz

Reboot done, patched module confirmed in memory, test run with physical verification
across six cases (full table in `docs/04-lab-90hz.md`, "Step 5 executed"). Both 90Hz modes
still leave the panel off with the HP logo, identical to the unpatched baseline. The 60Hz
control was run *after* the failures and gave a perfect image, so the setup was sound and
the result is clean.

A new hypothesis from the user was also tested and **ruled out**: head contention / GPU
clock domains (he'd already had to turn off 60Hz panels to reach 144Hz on X11). Tested with
a single monitor and with **zero** — the headset as the system's only display — and it's
still off. That's not it. To repeat it without losing your display there's
`scripts/solo-hmd-test.sh`, which restores the desktop via a `trap EXIT`.

~~**The live lead now is different**: maybe the headset is never asked to switch to 90Hz
(`wmr_hmd.c:767` sends the same thing at 60 and at 90). The Windows HID capture is still
needed.~~

> **RULED OUT the same day, twice** (see above and `docs/09-oasis-driver-re.md`). Left
> struck through instead of deleted because this paragraph, after going a few hours without
> an update, caused the hypothesis to be resurrected and cited as "the only one that
> explains the results."
> **When closing a lead, update this section in the same commit.**

Pending items that need sudo (RT priority for Monado, zram, audio, basalt deps) are still
not done; none of them blocked the test.

## The single most important rule of the whole project

**Verifying 90 Hz is PHYSICAL. You have to look inside the headset.**

The Vulkan/OpenXR API reports success and a happy 90.0 fps **with the panel completely
black**. The failure is invisible above the driver. Any conclusion based on logs,
on `xrandr`, or on the reported framerate is invalid. Ask the user to put on the
headset and tell you what they see — it's the only instrument that works.

This applies to the whole project, not just 90 Hz: the 360 photo, the video, VR180
stereo, everything was validated with the user watching. If a human hasn't seen it, it
isn't verified.

## Hardware status and what's already ruled out

**The headset works end-to-end on Linux.** Flawless 3DoF tracking, panel at 60 Hz, audio,
and a custom 360/VR180 player that plays 8K stereo at 60 fps. None of that is the
problem.

Things that **have already been investigated and should be left alone** (detail in `docs/06-known-issues.md`):

- **The cable / the USB port.** It was a bad USB-A port, already fixed. If the
  `03f0:0580` companion is missing, check the port, don't debug Monado.
- **The G2's power supply.** Suspected and **ruled out**: the same headset runs
  90 Hz for hours on Windows 11 without a single drop. It's not electrical.
- **The tracking cameras.** Measured: turning them off changes nothing (`WMR_CAMERAS=0`).
- **DisplayPort bandwidth.** Measured: the working 60 Hz mode has a HIGHER pixel
  clock than the failing native 90 Hz mode. It's not bandwidth: it's the refresh rate.
- **The GPU's DP ports.** Cross-tested with a monitor: both healthy.

**What does remain open** (but AFTER the 90 Hz, not now): with the panel on, the headset's
internal USB2 hub resets every so often and takes the companion and audio down with it. It
comes back on its own ~5 s after killing `monado-service`. Current suspect: how Monado's
WMR driver handles keepalive HID reports compared to Windows. It's an annoyance, not a
blocker.

## Concrete traps that will bite you

- **The player shows BLACK if it can't find its default content.** `LoadPhotoTexture()`
  does a `THROW` when the file won't open, and that kills the XR session: the compositor
  keeps presenting black and the rest of the log says "success". The default points to
  `~/Documents/linux_vr_base/photo360/venice_sunset.jpg`, which only exists on the
  main system. Pass `HELLO_XR_PHOTO360=` pointing to something that exists (the lab has a
  test equirect at `~/vr/media/test-equirect.jpg`). Before blaming video mode, check
  Monado's log for `BEGIN_SESSION` **without** an immediate `END_SESSION`.
- **The player exits on its own if you give it `< /dev/null`.** `hello_xr` v3 reads
  transport keys from stdin and treats `EOF` as "end of timed run": launched with stdin
  closed, it dies in under a second, with **exit 0 and not a single error line**. Monado's
  log shows `client_connected`, swapchains created and destroyed, and `client_disconnected`,
  with no `BEGIN_SESSION` from the app at all — it looks like a compositor failure and it
  isn't. Use `sleep N | hello_xr ...`. Note that **monado-service** needs the opposite
  (`XRT_NO_STDIN=1`, otherwise it dies with `epoll_ctl(stdin) failed`): the service gets
  stdin taken away, the player gets it kept alive.
- **For Wayland you need to pick the right session in SDDM:** there are **two** entries
  both just labeled "GNOME", one Wayland and one X11. Pick "GNOME on Wayland". And KWin
  doesn't work for the lease. `scripts/check-lease.sh` verifies it in two seconds before you
  waste time.
- **`jack-in.sh` no longer hardcodes video outputs** (fixed 2026-08-04): it snapshots the
  actual layout with `xrandr` before touching the CRTCs and restores it afterward, cycling
  the rotation and using `kscreen-doctor` on KDE. It doesn't hardcode paths either: it
  detects `~/Documents/linux_vr_base` or `~/vr`, and accepts `VR_BASE=` and `HMD_OUTPUT=`.
- **`play360.sh` had the same hardcoded path** (fixed 2026-08-04): it pointed to
  `~/Documents/linux_vr_base` and in the lab it would die with "hello_xr not built". It now
  autodetects the same way `jack-in.sh` does. If you touch one, sync `scripts/` with the
  copy in `~/vr/`.
- **`XRT_COMPOSITOR_DESIRED_MODE` from the environment**: until 2026-08-04 `jack-in.sh`
  overrode it with 60Hz, so the chapter 04 90Hz test was silently running at 60 and
  reporting success. It now respects the external value — but **always check the log** for
  which mode it picked: `grep "found display mode" ~/vr/jack-in.log`.
- **The user gets annoyed, rightly, when you break his vertical monitor.** It's happened
  several times. Every time Monado takes `DP-0` in direct-mode, the NVIDIA driver
  reprograms the CRTCs and loses the portrait monitor's rotation — and `xrandr` keeps
  *reporting* "right" while the panel shows landscape. The fix that works is cycling the
  rotation (`none` → `right`), and on KDE it's best done with `kscreen-doctor`, not
  `xrandr`.
- **Monado's startup sequence**: the panel only powers on when Monado sends the WMR
  activation, but Monado can only take the display if X isn't using it. That's why
  `jack-in.sh` starts the service, kills it with `kill -9` (a `SIGTERM` would send the
  screen-off and we'd be back at square one), frees `DP-0`, and only then starts it for
  real. `WMR_DISPLAY_INIT_SLEEP_SECONDS=2` is load-bearing: with the default of 4 s the
  panel has already turned off by the time Monado looks for it, and the service hangs
  forever.
- **Delete `/run/user/1000/monado_comp_ipc` before EVERY startup.** `SIGKILL` doesn't clean
  it up.
- **`pgrep -f` matches itself** in environments where the shell carries the pattern in its
  cmdline. Use `pgrep -f "monado[-]service"`. A PID that changes on every check is the
  tell.
- **`pkill` is blocked** in the Claude Code environment (exit 144, aborts the chain).
  Use `kill` on PIDs from `pgrep`.
- **Project-VR's Monado 90Hz patch** (`nominal_frame_interval_ns = 1e9/90`) **is already
  applied** in the lab tree as of 2026-08-04. It was applied *before* the baseline on
  purpose, so the only change between the unpatched measurement and the later one is the
  NVIDIA driver. `bootstrap-lab.sh` doesn't bring it in: if you redo `sources` from
  scratch, grab it from `patches/consolidated/monado/0001-*.patch` in the Project-VR repo
  (applies clean).

## What's in this repo

```
docs/00-hardware-usb.md     USB topology, the SuperSpeed/USB2 split, procedures
docs/01-bringup-monado.md   runtime build and startup
docs/02-player-360.md       the 360/VR180 player (v3): projections, pipeline, measurement
docs/03-controllers.md      controller status (3DoF, upstream driver limitation)
docs/04-lab-90hz.md         >>> YOUR SCRIPT <<<
docs/05-resolve.md          DaVinci Resolve (another rig goal, unrelated to this)
docs/06-known-issues.md     what's ruled out, with evidence
docs/07-windows-hid-capture.md  ARCHIVED: the mode command doesn't exist (see ch. 09)
docs/08-passthrough-limits.md  passthrough idea + limits by brand (not started)
docs/09-oasis-driver-re.md  what Windows sends to the panel, read from the Oasis driver
docs/10-resources.md         source index: HP driver, FCC, chips, installed base
docs/11-linux-hmd-landscape.md  is it just NVIDIA? other headsets, DK2, and where to publish
docs/12-g2-protocol.md     >>> PROTOCOL REFERENCE <<< everything we know about the headset
docs/13-bug-6bpc.md         >>> THE BUG <<< NVIDIA clamps the G2 to 6 bits per color
docs/14-nvidia-report.md    >>> PUBLISHED REPORT <<< + the corrected body ready to edit in
docs/15-feedback-triage.md  external feedback on the report, item by item, with verdict
forum-attachments/          the thread's attachments, already assembled and ready to upload
windows-kit/                Windows capture package (packaged into windows-kit.7z)
patches/nvidia/             the 3 Project-VR patches for 595-open
patches/monado/             7 of our patches (companion, controllers, WMR_CAMERAS)
patches/hello_xr-player/    3 patches: the full 360/VR180 player
scripts/bootstrap-lab.sh    automated lab install
scripts/jack-in.sh          brings up the VR pipeline (ADJUST the video outputs)
scripts/play360.sh          plays 360/VR180/flat content on the headset
scripts/get360.sh           downloads VR video from YouTube (needs the android_vr client)
scripts/solo-hmd-test.sh    test with the headset as the ONLY display (restores via trap EXIT)
scripts/check-lease.sh      does the Wayland compositor offer the headset's connector? (no Monado)
scripts/xref.py             string xrefs in PE binaries, using only binutils
scripts/edid-tool.py        decodes the headset's EDID and generates variants (bpc, checksum)
scripts/jack-in-wayland.sh  brings up the VR pipeline via DRM lease (Wayland; needs GNOME)
scripts/drmprops.c          reads non-desktop/modes straight from the kernel connector
scripts/capture-hid.sh      captures the companion's HID per mode (usbmon, needs root)
scripts/analyze-hid.py      diffs HID captures: usbmon (Linux) and tshark TSV (Windows)
```

The code trees don't come in the bundle: `bootstrap-lab.sh` clones them from upstream at
the exact SHAs the patches were generated against, and applies the patches. That way the
bundle weighs kilobytes and it's exactly clear what's ours.

## How this user works

- He speaks Spanish. Reply to him in Spanish.
- He's technical and wants the why, not just the what. Measurements matter more to him than
  opinions — if you're going to claim something, measure it.
- **Correct course when the evidence contradicts it.** In this project there have already
  been three conclusions accepted as good that turned out false (the cable, the power
  supply, the "hardware-blocked" audio). Each one cost weeks. If something doesn't add up,
  say so.
- Don't declare anything verified without him having seen it. It's already happened that a
  render was accepted as good that had never actually been looked at.

## If 90 Hz works

Record in `docs/04-lab-90hz.md`: which mode worked (`XRT_COMPOSITOR_DESIRED_MODE`),
stability at 15+ minutes, and re-run the video smoke test from chapter 02 (the
NVDEC/cuvid path should work the same on 595, but it needs to be verified explicitly).

Only then is the final install planned. The cutoff criterion agreed with the
user is **"the headset on par with Windows or better"**.
