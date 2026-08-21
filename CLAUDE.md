# Context for the 90Hz lab agent

> ## UPDATE 2026-08-21 ~17:15 (T244) — read NEXT-STEP's START HERE first. Two session-wide bugs
> fixed and verified worn: the **45/30 fps ceiling** (app pacer, 0092 + `U_PACING_APP_USE_MIN_FRAME_PERIOD`
> launcher default → 44 → 90 fps) and the **"flying away"/relocation on every companion drop**
> (0090's blocking proximity read + backlog-poisoned `hw2mono`; 0093/0094 → 66 drops, zero SLAM
> holes). Pairing capture re-mining (docs/03 T244) closed two leads as clean negatives. Every
> T243 fps/flying-away verdict in docs/23 predates these fixes and needs a retest.
>
> ## START HERE (2026-08-20, ~01:45 — the "run it all without Windows" night, T226-T237).
> Read `docs/00` + `docs/03` + `docs/60`-`63` + T226-T237 + NEXT-STEP. Supersedes the block below
> on every point where they disagree. The tracking work (T223-T225) is unchanged and still true;
> this night was about the LINK, the HARDWARE MAP, and cutting the last ties to Windows.
>
> **THE HEADLINE: the G2 now runs end-to-end on Linux from bare hardware — activation, panel,
> tracking, port recovery — with only ONE Windows dependency left (initial controller pairing),
> and that one is now a scoped RE target instead of a wall.** The full USB bring-up ladder is
> PROVEN cold (T234): plug into the CPU-controller socket → 5/5 in 3 s → `panel.py activate` →
> `DP-3` hotplugs from a genuinely absent connector, no Windows at any step. `scripts/usb-port-map.sh`
> is the instrument (`map` needs no headset, `qualify` walks the 4-rung ladder and writes a
> per-board ledger).
>
> **The USB story, fully mapped (T231-T234, T237, `docs/00`)**: this board (ASUS TUF B450M-PLUS
> II) has TWO xHCI controllers — `09:00.3` Matisse (CPU, headset WORKS) and `02:00.0` B450 chipset
> (headset FAILS). ASUS does not publish which rear port is which; the live census does, and that
> gap is why the tool exists. Census signatures and their measured levers: **5/5** = good;
> **2/5 SS-only** = correct plug side, USB2 branch didn't join → **PC-end cold replug, same port
> same side** (T186, but does NOT rescue a never-good seat, T234); **0/5 powered** = wrong plug
> side → **flip the C plug 180° in the adapter** (T184); **4/5 SS-missing** = a black USB2 socket
> (panel works, tracking can't). **Three wrong versions of this table were written and retracted
> in one night** — each generalised a fresh measurement over a better one already in `docs/22`.
> The discriminator is the **plug seat**, not the controller; the kernel's `Cannot enable. Maybe
> the USB cable is bad?` fires on a perfect cable in the wrong seat. **Read the record before
> concluding — that rule was the one being broken.**
>
> **The USB2 storm is the LINK, not our stack (T226, `docs/60`), and the amplifier is FIXED
> (0090, `docs/61`, T227)**: Windows storms at 3.47 drops/min on the same cable/box/headset (OS
> the only variable), USB3 immune on both — so the rev2A cable is BACK on the suspect list and its
> retraction is retracted. A re-enumeration permanently invalidated the companion's hidraw fd
> (the node moves `hidraw6`→`7`→…); 0090 re-finds it by VID/PID and swaps under `hid_lock`, **13/13
> recovered, 3.34 s each**. **Retire `companion_errors`** — past the first re-enum it counts our
> own polling of a corpse (explains T183's errors during 5/5). The rev2A is not a fix but a
> well-posed A/B now: HP recalled every Rev A cable for free, citing power/hub issues on the exact
> USB2 branch that storms.
>
> **THE HARDWARE IS FULLY MAPPED — `docs/63`, every part with a confidence level.** Every
> identifier read off the labels (serials deliberately excluded): headset `TPC-Q077-VH` /
> `VR3000-0XX` (the BASE G2, not Omnicept — a 3-file correction) / FCC `HFS-A85Q` + IC/KC/NCC/
> ANATEL/ICASA/IFT (global-SKU label); controllers **right `TPC-Q077-C1`/`M09967-001`, left
> `-C2`/`-002` — DIFFERENT PARTS** (removes the "same unit" assumption under the T230 LED
> asymmetry); cable **Rev A, SPS `M18238-001`, `TPC-B001C`, by BizLink**, replacement `M52188-001`
> (with switch); **PSU is 18.5 V not 12 V** — HP 65 W `PPP009H`/`PA-1650-02H`, a 33-place
> correction that mattered because `docs/26` told people to replace the brick. Still unknown and
> worth chasing: the **DP repeater chip in the cable's inline box** (no external label; box opens),
> both IMUs, the panel part.
>
> **The LED asymmetry is REAL and OS-DEPENDENT (T229/T230)**: Windows drives the left ring 2.45×
> the blob area of the right; on Linux the two are identical (both at the dim end). We command no
> LED intensity at all — so Windows sends something we don't, a candidate tracking lever upstream
> of every threshold. `scripts/led-ring-photometry.py` measures it (area, not brightness —
> brightness saturates). Decisive test queued: position-swap + battery-swap photos.
>
> **CONTROLLER PAIRING — researched deep, ATTEMPTED, honest negative (T235/T236, `docs/03`)**:
> `WMR_BT_CONTROL_MSG_PAIR=0x05` sits unused in Monado's own header; we built `controller-pair.py`
> and fired it on a genuinely-unpaired controller — **it did NOT pair**. A probe proved the enum
> values past `0x17` are inert (identical `CONTROLLER_STATUS` replies), i.e. unvalidated RE
> guesses. The unpair was the PHYSICAL button (Linux read it live), not a host command. Nobody has
> ever paired a WMR controller from Linux; the scoped next step is **USBPcap of Oasis pairing on
> Windows** to get the real framing. Recovery: one Oasis pass re-pairs (the right controller is
> currently unpaired). Pairing is literal Bluetooth bonding (2402-2480 MHz to the HEADSET radio,
> mutable, per-hand-slot, calibration travels with the controller) — which makes controllers
> **migratable between G2 units**, key for the recycling mission.
>
> **What Oasis actually does, precisely (`docs/31`)**: (1) binds USB to ONE CPU-fed USB3 port —
> relaunch to re-bind, a technically-valid-but-unbound port FAILS (T185 ghost is that refusal);
> (2) controller pairing. Both are the platform's inheritance, not Oasis quirks — the original MS
> driver fought the same on new hardware and "no marcaba bien nada". The diagnostic gap nobody
> ever filled on Windows is exactly what our census/ladder/ledger fills.
>
> **Method meta-lesson of the night, earned four times**: the record outranks the impression, and
> it was violated repeatedly — the socket table (×3), and the pairing "OS-independent" hypothesis.
> The user caught each from memory of his own docs. `poshalim` — we tried the world-first pairing
> and it's an honest negative, which is on file next to the win it wasn't.
>
> ---

> Older superseded session-open headers (2026-08-05 through 2026-08-19) were moved
> to `docs/64-claude-md-session-history-archive.md` on 2026-08-20 to keep this file
> under the context limit. Read that file if older narrative context is needed —
> the block above already states what still applies.


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
  stdin taken away, the player gets it kept alive. **And keeping stdin open is NOT enough
  when launching via `play360.sh`** (found 2026-08-19 T221, root-caused same night —
  CORRECTION: an earlier version of this note blamed a "~300 s timed run inside hello_xr";
  hello_xr never self-limits): `play360.sh` wraps the player in coreutils
  `timeout $SECONDS_TO_RUN` (default **300**, its line ~57), which SIGTERMs on wall clock
  regardless of stdin. Pass `-t <seconds>` for longer instrumented windows. The player also
  now has `HELLO_XR_DURATION_S` (patch 0020: internal graceful quit via the real
  quit-request path — a clean `END_SESSION`, unlike timeout's SIGTERM; 0 = run forever).
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
- **`"found display mode"` in the log does NOT prove the real WMR headset was used**
  (found 2026-08-07, T050). If the `wmr` builder fails to build a head device (e.g. a
  transient `Did not find HoloLens Sensors' companion device`), Monado silently falls back
  to its `legacy` builder's **Simulated HMD** — which still leases the already-hotplugged
  DP connector and still logs `found display mode`, indistinguishable from a real success
  under a naive grep. Always also check for `Using builder wmr` (not `Using builder
  legacy`/`Simulated HMD`) before trusting a session.
- **The right controller can silently lose the startup race and never register — even
  though it's powered on and pairs fine** (found 2026-08-07, T051). Both controllers
  share one HID tunnel through the headset (docs/03) and Monado finalizes its device/role
  list early; if the right controller's config read (`Reading right controller config`)
  finishes after that list is built, it ends up `right: <none>` for the whole session with
  no error logged. Reproduced 9/9 times in a row with both controllers on the entire time —
  this is a left-wins-every-time race, not occasional BT flakiness. Check with
  `grep -E "left:|right:"` in the log; don't trust the physical LED alone. Not fixed yet —
  candidate fix is parallel/round-robin controller reads instead of strictly sequential
  ones in the startup path (`patches/monado`).
- **`jack-in-wayland.sh` now pre-activates the panel and polls sysfs for DP `connected`
  itself before ever starting `monado-service`** (added 2026-08-07, T050), instead of
  relying on Monado's own fixed `WMR_DISPLAY_INIT_SLEEP_SECONDS=2` window — measured
  activate→hotplug latency is NOT fixed (as fast as ~0.5s clean, as slow as ~6s right
  after a prior failed attempt), and 2s wasn't always enough. This is what actually fixed
  the intermittent "Found no connectors available for direct mode" failures that used to
  look like hardware death.
- **The USB Audio sink needs a mute-on-demand plan.** The companion's audio device
  (`0bda:4c15`) becomes the system default output the instant it enumerates, and any
  already-playing stream (e.g. a browser tab) can jump onto it mid-cycle at whatever
  volume it was at — startling right next to your ears. `./scripts/hmd-audio.sh
  {mute|unmute|status|set <pct>}` finds the sink by name via `wpctl` (no ID to
  memorize, survives PipeWire re-numbering the sink on every USB2 re-enumeration) and is
  the fast way to kill it.
- **"No audio" can be the USB2 branch cycling under you, not a real fault — check
  `journalctl -k` for `usb 3-2` disconnects before debugging PipeWire.** (T052-T053,
  corrected: an initial "it was the off-ear speaker position" theory was WRONG and
  retracted — the G2 has no proximity sensor there, only one near the nose bridge for
  wear detection, `WMR_CONTROL_MSG_IPD_VALUE`, unrelated to audio.) Real mechanism,
  caught live: the USB2 branch (hub `04b4:6506` + audio `0bda:4c15` + companion
  `03f0:0580`) can reconnect on its own repeatedly at idle with nothing running — one
  session logged 66 cycles in 60 minutes, including a dense stretch of one every
  ~6-12 seconds with the companion transiently missing from `lsusb`. PipeWire
  creates/destroys the ALSA sink on every cycle, so playback that starts or is already
  running has a real chance of landing in a disconnected window and simply producing
  nothing, with no error anywhere. This is denser than the isolated single-event
  recoveries in T039/T044/T046 — **don't treat the panel.py-activate fix (T048-T050) as
  proof the underlying marginal contact is calm; this storm suggests otherwise, and the
  rev2A cable recommendation should be treated as still-open, not retired.** Not yet
  tested: whether audio glitches mid-playback during a live dropout (vs. just failing to
  start), the mic path, or what makes the storm start/stop.
- **`~/vr/basalt` can look built when it isn't — check for the actual `.so`, not just
  the directory.** Found 2026-08-07 (T060): `cmake --preset library` was silently
  failing on undocumented deps (`libepoxy-dev libyaml-cpp-dev libsqlite3-dev`, on top of
  the already-known `libbz2-dev liblz4-dev libssl-dev`), leaving a `CMakeCache.txt` with
  no `build.ninja` and no `libbasalt.so` — `docs/06`'s Basalt-divergence entry had never
  actually been reproduced in this checkout. Once built clean, SLAM (`WMR_SLAM=1`) works
  well: real 6DoF, no divergence, comparable jitter to 3DoF both at rest and moving
  (T060-T061). **`./scripts/jack-in-wayland.sh [mode] [3dof|6dof]`** now wires this in
  properly (second arg, default `3dof`) instead of hardcoding `WMR_SLAM=0
  WMR_CAMERAS=0` — it checks `~/vr/basalt/build/libbasalt.so` exists before promising
  6dof and sets `VIT_SYSTEM_LIBRARY_PATH` automatically.
- **A game that launches with audio in the headset but a FLAT 2D image is almost certainly
  `openvrpaths.vrpath`'s runtime ORDER, not the headset** (found 2026-08-13, T174).
  OpenVR takes the **first** entry of `"runtime"` in `~/.config/openvr/openvrpaths.vrpath`.
  T170's parked SteamVR-native experiment left `.../steamapps/common/SteamVR` ahead of
  `~/vr/xrizer/target/release`, so every OpenVR title loaded SteamVR's `vrclient`, found no
  session or lease, and silently fell back to flat rendering — `client_connected` stays at
  0 in Monado's log while the game looks alive and even routes audio to the headset.
  Check that file before debugging anything else; xrizer must be first (or alone).
- **Killing the Steam wrapper does NOT stop the game** (found 2026-08-21, T244 close).
  `kill $(pgrep -f "AppId=NNN")` or matching the title in a cmdline only takes down
  `reaper`/`steam-launch-wrapper`/`proton`; the Windows binary keeps running under
  wineserver inside pressure-vessel, keeps its OpenVR session and keeps rendering. Two titles
  ran at once for a whole test this way (151 "Delivered frame"/s = two clients, CPU/GPU numbers
  invalid), and taking Monado down under the orphans produced xrizer `ERROR_INSTANCE_LOST`
  crash dialogs ("compositor + overlay"). Use **`scripts/game-stop.py status|stop <appid>|all`**
  — it finds every process by `STEAM_COMPAT_DATA_PATH=.../compatdata/<appid>`, SIGTERMs the
  main exe, then the rest, and verifies. Before any launch or measurement: `game-stop.py
  status` must say "no Proton game trees running", and Monado's log must show the previous
  `client_disconnected`.
- **`pgrep -f` matches itself** in environments where the shell carries the pattern in its
  cmdline. Use `pgrep -f "monado[-]service"`. A PID that changes on every check is the
  tell. **This bites when killing games too**: `kill $(pgrep -f "Aircar")` from this
  agent's shell killed the shell itself (exit 144, chain aborted) on 2026-08-13 — bracket
  the pattern (`AirCar[-]Win64`) for game processes as well, not just for monado.
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
docs/16-lab-vblank.md       vblank/pixel-clock factorial (conclusion superseded, see its banner)
docs/17-publishing.md       preparing the repo for publication
docs/18-monado-upstreaming.md  upstreaming the Monado WMR patches (4 MRs open)
docs/19-nvidia-bug-5923212-followup.md  >>> THE RESOLUTION <<< how 90Hz actually got fixed
docs/20-desktop-plasma-crash.md  the connected headset vs. the KDE desktop
docs/21-project-retrospective.md  project retrospective
docs/22-cable-connector-diagnosis.md  >>> LINK ANATOMY <<< piece-by-piece diagnosis of cable/connector/power
docs/31-windows-bringup-and-errors.md  >>> WINDOWS MANUAL <<< Oasis on 24H2, and what errors 108/422 mean
forum-attachments/          the thread's attachments, already assembled and ready to upload
windows-kit/                Windows capture package (packaged into windows-kit.7z)
windows-kit/power-on.ps1    Windows bring-up gate: USB census by branch, pairing, Oasis/SteamVR state (see docs/31)
patches/nvidia/             the 3 Project-VR patches for 595-open + OUR 0004 bpc fix (the 90Hz solution)
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
scripts/reseat_audio.py     audible bring-up guide: speaks the census while your hands are on the connector
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
