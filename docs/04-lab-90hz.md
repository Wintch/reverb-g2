# 04 — Lab 90Hz: Debian on separate SSD + patched 595-open driver

> **OUTCOME (2026-08-06/07), since this file's running log stops before the ending:**
> 90Hz RESOLVED — the 6bpc-clamp patch (`patches/nvidia/0004`, found via this lab, ch. 13)
> was the complete fix; both native modes light clean on the plain EDID, and real video
> through the full player at `4320x2160@90` (mode 1, via `jack-in-wayland.sh` + DRM lease
> on GNOME) was verified flicker-free (T041). Resolution chain: `docs/19`; retrospective:
> `docs/21`; the per-mode/vblank dead ends below are all superseded by those. The ch. 02
> video smoke test at 90Hz implicitly passed with T041 (NVDEC falls back to software above
> 4096 px width; 60 fps sustained, 0 starves).

## Why this way

The G2 doesn't go above 60Hz on NVIDIA/Linux due to driver bugs (NVIDIA bug 5923212: DisplayID
parser that drops the native mode, DSC 1.1 tables out of spec — the compression handshake
for the 90Hz mode fails — and Microsoft VSDB parsing). Measured here: it's NOT
bandwidth (the 60Hz mode that works has a HIGHER pixel clock than the native 90Hz that fails).
NVIDIA hasn't fixed it in any version up through 610.x (Jul 2026).
[Project-VR](https://github.com/AshishKumar4/Project-VR) fixes it by patching the **open
kernel modules**; tested by its author only on an RTX 4080. Our analysis: the patches are
generic (the Ampere `nvkms-evo3.c` path is covered) and the 3060 Ti (GA104) is
supported by the open modules — it should work, but that's exactly what the lab tests.

**Why a separate system:** it replaces the entire graphics stack. If it goes wrong, the
main system doesn't even know — rollback = pick the other disk in the boot menu.

**Decisions made:**
- **Debian 13 stable (trixie)** in the lab too. NVIDIA publishes an apt repo for
  debian13 with **exactly 595.71.05**, the version Project-VR patches — zero rebase.
  (The Debian-packaged 550-open doesn't even compile on kernel 6.12.100; ruled out.)
  Testing/sid would break the DKMS rebuild on every new kernel — not for an experiment.
- **X11 session**, not Wayland: our entire Monado pipeline uses NVIDIA direct-mode via
  X11/XRandR. The Wayland path needs the full 0002 patch + Monado patch 0008 +
  a compositor with support (Project-VR validated it on patched GNOME/mutter; untested
  on KDE). Wayland remains a future path.
- This machine boots **BIOS/legacy → no Secure Boot or MOK**. One less step.

## Step 1 — Base install (spare SSD)

1. Connect the spare SSD (to a chipset-controller port, see cap. 00).
2. Debian 13 netinst → install on that disk, **KDE or XFCE**, ideally with the main disk
   DISCONNECTED (this keeps the installer from touching the good system's GRUB).
   Otherwise, carefully choose the bootloader target = the lab SSD.
3. First boot, basics:

```bash
sudo apt install -y build-essential dkms linux-headers-amd64 git curl \
    cmake ninja-build meson pkg-config glslang-tools \
    libvulkan-dev vulkan-tools vulkan-validationlayers \
    libeigen3-dev libusb-1.0-0-dev libudev-dev libhidapi-dev \
    libgl-dev libglx-dev libglvnd-dev libxcb-randr0-dev libx11-xcb-dev \
    libavcodec-dev libavformat-dev libavutil-dev libswscale-dev ffmpeg
# Headset udev:
sudo cp scripts/70-wmr-reverb.rules scripts/71-usb-no-autosuspend.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo usermod -aG plugdev,adm,systemd-journal $USER
```

## Step 2 — NVIDIA 595.71.05 driver (official debian13 repo)

**Do NOT install Debian's nvidia-driver in the lab.** The stacks are mutually exclusive.

```bash
# NVIDIA keyring + repo for Debian 13:
curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb -o /tmp/cuda-keyring.deb
sudo dpkg -i /tmp/cuda-keyring.deb
sudo apt update

# Pin to the exact version Project-VR patches, and install the open stack:
sudo apt install -y nvidia-driver-pinning-595.71.05
sudo apt install -y nvidia-open
# (NVIDIA's DKMS package is called nvidia-kernel-open-dkms — WATCH OUT, Debian has another
#  near-homonym, nvidia-open-kernel-dkms 550: don't mix them up)
sudo reboot
```

## Step 3 — Baseline WITHOUT patches (experiment control)

Build Monado + Basalt in the lab (cap. 01), run `jack-in.sh`, and confirm that 90Hz
**still fails the same way** (modes 0 and 1 = black panel with the logo, mode 2 = 60Hz works).
This separates "the 595 driver changed something" from "the patches fixed it".

## Step 4 — Apply the patches via DKMS

The patches hook into the DKMS tree the package leaves at `/usr/src/nvidia-595.71.05/`,
using dkms.conf's `PATCH[]` mechanism — this way they re-apply automatically with every kernel:

```bash
cd /usr/src/nvidia-595.71.05
sudo mkdir -p patches
sudo cp ~/reverb-g2/patches/nvidia/000*.patch patches/

# Register the patches in dkms.conf (append at the end):
sudo tee -a dkms.conf >/dev/null <<'EOF'
PATCH[0]="0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch"
PATCH[1]="0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch"
PATCH[2]="0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch"
EOF

# Verify they apply in dry-run BEFORE rebuilding:
for p in patches/000*.patch; do sudo patch -p1 --dry-run < "$p" || echo "FAILED: $p"; done

# Rebuild + reinstall the module:
sudo dkms remove nvidia/595.71.05 --all
sudo dkms install nvidia/595.71.05
sudo reboot
```

Note: `dkms` applies `PATCH[]` to a copy at build time — the source tree stays
clean, and a kernel upgrade re-applies everything automatically. If a future
`apt upgrade` brings 595.91.07, the patches still apply (verified against that tree);
on 610.x you have to drop the two `flatnessDetThresh` hunks from 0001 (NVIDIA already
fixed that there) — the rest is still needed.

## Step 5 — Monado with the 90Hz fix

Apply our patches (`patches/monado/`) to the lab's Monado **plus** Project-VR's 0001
(`nominal_frame_interval_ns = 1e9/90` in `wmr_hmd.c` — without this the SteamVR bridge
computes 1/0 and falls back to 60Hz with judder; applies cleanly on top of main):

```bash
curl -fsSL https://raw.githubusercontent.com/AshishKumar4/Project-VR/main/patches/consolidated/monado/0001-drivers-wmr-Set-90-Hz-nominal-frame-interval-on-WMR-.patch | git -C monado am
```

(The exact filename may vary — list `patches/consolidated/monado/` in the repo.)

## Step 6 — The test

```bash
./jack-in.sh 3dof     # but with XRT_COMPOSITOR_DESIRED_MODE=0  (2880x1440@90 native)
# and if it fails, try =1 (4320x2160@90)
```

**Look at the panel physically.** The API reports success and 90fps even when the panel is
black — the only valid verification is the eye. Expected result with patches: image at 90Hz
and goodbye to the 60Hz backlight-strobe flicker.

Record in this chapter: which mode worked, stability (15+ min), temperature/clocks
(`nvidia-smi -q -d SUPPORTED_CLOCKS` — do NOT copy Project-VR's lock-clocks, those are for Ada),
and re-run the video smoke test from cap. 02 (the NVDEC/cuvid path should work the same on
595; verify it explicitly).

### Baseline result — 2026-08-04, lab (Debian 13, KDE/X11, 595.71.05-open WITHOUT patches)

Verified **physically**, headset on, with `hello_xr` showing a test equirect
(`ffmpeg -f lavfi -i testsrc2=size=4096x2048`, at `~/vr/media/test-equirect.jpg`):

| `XRT_COMPOSITOR_DESIRED_MODE` | mode reported by the compositor | what's seen inside the headset |
|---|---|---|
| 2 | 4320x2160@60.00 | correct image + the usual 60Hz strobe |
| 0 | 2880x1440@90.00 | **panel off, only the HP logo** |
| 1 | 4320x2160@90.00 | **panel off, only the HP logo** |

**Conclusion: 595-open by itself does NOT fix 90Hz.** The failure is identical to the 550's
on the main system, so anything that works after step 4 is attributable to the patches and
not to the driver version. Experiment control satisfied.

Details worth keeping handy:

- Mode numbering **did not change** between 550 and 595 (this was suspected and ruled out):
  the log with `XRT_COMPOSITOR_LOG=debug` confirms `Found 3 modes` and the mapping 0=2880x1440@90,
  1=4320x2160@90, 2=4320x2160@60.
- In both 90Hz modes the API reports complete success: `BEGIN_SESSION` with no close,
  frame interval of 89.999/90.001 Hz, both processes with memory on the GPU. Nothing above the
  driver gives away the failure. This is the project's rule in its purest form.
- Reading the mode table requires `XRT_COMPOSITOR_LOG=debug`: `print_modes()` uses
  `COMP_PRINT_MODE`, which doesn't print at the default log level.

### Step 4 executed — 2026-08-04 18:26

`bootstrap-lab.sh patch-nv` ran clean: all three patches passed the dry-run, dkms
applied them to its copy, compiled, signed, and installed the five modules. Verified afterward:

- `dkms.conf` has the three `PATCH[0..2]` lines → a kernel upgrade re-applies them on its own.
- `/usr/src/nvidia-595.71.05/` remains **unpatched** (dkms works on a copy).
- New modules in `/lib/modules/6.12.100+deb13-amd64/updates/dkms/`.
- MOK signing is irrelevant here: the machine boots BIOS/legacy, no Secure Boot.

**Pending: reboot.** Until the reboot, the old unpatched module keeps running.

### How to resume after the reboot

```bash
# 1. Confirm the loaded module is the patched one (build date, not version:
#    the version stays 595.71.05 in both cases)
modinfo nvidia-modeset | grep -E "^filename|^version"
ls -l /lib/modules/$(uname -r)/updates/dkms/nvidia-modeset.ko.xz

# 2. Headset plugged in: all FIVE have to be present (see cap. 00)
lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"

# 3. The test. MODE=0 first (2880x1440@90 native)
cd ~/vr && XRT_COMPOSITOR_LOG=debug XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof
grep -E "found display mode|frame interval" ~/vr/jack-in.log   # confirm it picked up @90

# 4. Content to see something with (the player's default points at the main system):
sleep 600 | XR_RUNTIME_JSON=$HOME/vr/monado/build/openxr_monado-dev.json \
  IPC_IGNORE_VERSION=1 VK_LOADER_LAYERS_DISABLE='*' \
  HELLO_XR_PHOTO360=$HOME/vr/media/test-equirect.jpg \
  ./OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr --graphics Vulkan2

# 5. LOOK INSIDE THE HEADSET. If mode 0 fails, try MODE=1.
```

If it works: leave it running 15+ min, then the video smoke test from cap. 02 (NVDEC/cuvid on 595),
and only then plan the final installation.

### Step 5 executed — the test WITH patches: FAILS (2026-08-04, 18:38–18:55)

Reboot done, patched module confirmed loaded (`.ko` from the 18:26 build, dkms
`installed`), all five USB devices present. **Physical** verification in all six cases, the
user looking inside the headset:

| Mode | Resolution@Hz | Active desktop displays | Result |
|---|---|---|---|
| 2 | 4320x2160@60 | 3 | **correct image** (control) |
| 0 | 2880x1440@90 | 3 | panel off, HP logo |
| 1 | 4320x2160@90 | 3 | panel off, HP logo |
| 0 | 2880x1440@90 | 1 (DP-3 only) | panel off, HP logo |
| 0 | 2880x1440@90 | **0 (headset sole display)** | panel off, HP logo |

**Conclusion: Project-VR's three patches for 595-open do NOT fix 90Hz here.**
The behavior is identical to the unpatched baseline and to the 550 on the main system.

The 60Hz control was run *after* the failures, with the patches in place, and gave a
perfect image: the setup is sound and the result is clean. It's not "black across the board".

### Ruled out in the same test: display contention (user's hypothesis)

Reasonable hypothesis, never tested before: in X11 the user had already had to turn off his
60Hz panels to get his monitor to 144Hz, and `jack-in.sh` leaves the three monitors on when
Monado takes `DP-0`. With the headset that's 4 heads on a 3060 Ti — right at the limit.
**This is a different theory from the DP cable bandwidth one** (already ruled out in
cap. 06): this one is about the GPU's display engine, not the link.

Tested and **ruled out**, in two steps: with a single monitor and with **zero**. With the
headset as the system's sole display, the panel is still off. It's neither head contention
nor clock-domain contention.

The measured pixel clocks, which also kill the "aggregate bandwidth budget" variant:

| Display | Mode | Pixel clock |
|---|---|---|
| Headset mode 2 (**works**) | 4320x2160@60 | 709.150 MHz |
| Headset mode 0 (fails) | 2880x1440@90 | **428.580 MHz** |
| Headset mode 1 (fails) | 4320x2160@90 | 905.400 MHz |

Mode 0 fails while consuming **less** clock than the mode 2 that works, with the same
heads on. If it were a bandwidth budget issue, mode 0 would have to work.

To repeat the test without losing all displays: `scripts/solo-hmd-test.sh` turns off the
whole desktop, runs the test, and **restores the layout from a `trap EXIT`** (including the
rotation cycle of `DP-3` with `kscreen-doctor`). It survives the script failing.

### Live hypothesis: nobody is telling the headset to go to 90Hz

Code finding, not a measurement yet. In `src/xrt/drivers/wmr/wmr_hmd.c`:

- `wmr_hmd_activate_reverb()` (line ~767) **always sends the same HID sequence** —
  `0x50`×4, `0x09`, `0x08`, `0x06`, and `wmr_hmd_screen_enable_reverb()`. There isn't a single
  branch that depends on the refresh rate. 60Hz activation and 90Hz activation are identical.
- The "Monado 90Hz patch" (line ~1992) only does
  `nominal_frame_interval_ns = 1e9/90.0`. Its own comment explains it: it exists so that
  the SteamVR bridge doesn't compute `1/0` and fall back to 60. It's a value **reported
  upward** for pacing. **It doesn't touch the panel.**

In other words: the DisplayPort connector is asked for a 90Hz mode, but the G2's panel
never receives a command to reconfigure itself. That's consistent with the six results
above — including why the NVIDIA patches didn't move anything: **the problem may not be
in NVIDIA.**

Still to confirm: whether the G2 actually requires a proprietary command for 90Hz instead
of negotiating it via modeset. Natural path: capture the headset's HID traffic on Windows 11
(where 90Hz runs for hours) and diff it against what Monado sends.

### Measured: Monado sends the same thing at 60 and 90 Hz (2026-08-04, 19:10)

No longer just code reading. `usbmon` capture of the companion during Monado's startup,
one file per mode (`scripts/capture-hid.sh`), analyzed with
`scripts/analyze-hid.py`. The entire class-HID conversation with the headset, in full:

| Transfer | mode 2 — 60Hz (**panel turns on**) | mode 1 — 90Hz (**panel off**) |
|---|---|---|
| `SET_REPORT` Feature `0x50` = `5001` | ×4 | ×4 |
| `GET_REPORT` Feature `0x50` | ×4 | ×4 |
| `GET_REPORT` Feature `0x09` | ×1 | ×1 |
| `GET_REPORT` Feature `0x08` | ×1 | ×1 |
| `GET_REPORT` Feature `0x06` | ×1 | ×1 |
| `SET_REPORT` Feature `0x04` = `0401` (screen ON) | ×2 | ×2 |

13 transfers in each case. The diff comes out to **zero** differences. The headset is sent
exactly the same thing whether the panel turns on or not. This is the baseline to compare
against Windows (cap. 07).

Two things to avoid tripping over when repeating this:

- **The mode 0 capture was no good** and has to be redone: the companion re-enumerated in
  the middle of startup (it appeared only as device 085) and Monado never completed the
  sequence with it — the file doesn't have a single `SET_REPORT 0x50`. It's the USB2 hub
  reset from cap. 06. This doesn't invalidate anything: mode 1 is also 90Hz and came out
  clean. **Valid-capture criterion: there has to be a `SET_REPORT` Feature `0x50`.**
- **The companion's device address changes on every run** (79, 91, 85...). Hardcoding it
  doesn't work; `analyze-hid.py` detects it by the `f0038005` descriptor (`03f0:0580` in
  little endian) and, if there are several, keeps the one that actually received commands.

And a trap that cost two runs: **bus 3 is full of traffic that looks like HID and isn't**
— UTF-16 string descriptors that read as reports with plausible payloads. You have to filter
for class control transfers (`bmRequestType` 0x21/0xa1 with `bRequest` 0x09/0x01) or the
analysis produces pure noise that looks like signal.

### TURN: 90Hz on NVIDIA DOES work — Project-VR has it running (2026-08-04, 19:30)

Source research, after closing up the lab. Changes the entire plan.

[Project-VR](https://github.com/AshishKumar4/Project-VR) — the repo our three patches came
from — **reports the G2 running at `4320x2160 @ 90 Hz` on an RTX 4080 with the same
`nvidia-driver-595-open` and the same patches.** This isn't an open problem: it's a solved
problem that didn't work for us.

And now it's known **why** 60 works and 90 doesn't: **the 90Hz mode uses DSC (Display
Stream Compression)**. Patch 0001 fixes the DSC 1.1 rate-control tables and DisplayID 2.0
parsing — literally, *"needed for the 90 Hz handshake to succeed"*.

That explains at once why **all** the bandwidth-based reasoning failed: ours about the
display engine, the user's about the panels, and the 2-lane theory circulating in the
[NVIDIA thread](https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744).
With DSC the raw pixel clock isn't the limiting factor — what matters is whether the
compression handshake completes. Note it down: this was the third bandwidth theory ruled
out.

Upstream bug status: NVIDIA confirms **5923212**, reproduces it, it's still under
investigation, and the thread's latest report (**July 19, 2026**) says it persists in
**610.43.02**. Waiting on upstream isn't a plan.

**The HID-command hypothesis from the previous section dies**: Project-VR reaches 90Hz with
patches to the video driver, no proprietary command at all. The identical HID sequence we
measured is correct and sufficient. `docs/07` (Windows capture) is filed away as archived
material — **no need to boot Windows.**

#### The two differences from the setup that works

1. **Ampere vs Ada.** They validated on an RTX 4080 (AD103); here there's a 3060 Ti (GA104).
   `patches/nvidia/`'s README claims the Ampere `nvkms-evo3.c` path is covered, but that's a
   code-reading claim and the empirical result says otherwise.
2. **X11 direct-mode vs Wayland DRM lease.** Our log says `Selected NVIDIA Direct-Mode
   backend!` with `VK_EXT_acquire_xlib_display`. Project-VR runs **Wayland with DRM lease**,
   and patch 0002 is literally named `enable-Wayland-DRM-lease-of-VR-HMDs`. The README
   claims that machinery is dead code on X11 — another unverified claim.

The second one is free to test and is the only setup variable that can be changed without
buying hardware. It goes first.

### Test Wayland + DRM lease

```bash
# 1. Log out and choose "Plasma" (NOT "Plasma (X11)") in SDDM.
# 2. Resume the agent if needed:  claude --continue
# 3. The HMD must NOT appear in Settings > Displays. If it appears, KWin picked it
#    up as a monitor and patch 0002 (marking it non-desktop) isn't taking effect.
cd ~/vr && ./jack-in-wayland.sh 1     # 1 = 4320x2160@90, Project-VR's mode
```

`jack-in-wayland.sh` is much simpler than `jack-in.sh`: with DRM lease there's no fight
with X over the display, so **it doesn't touch a single desktop monitor** — no releasing
`DP-0`, no CRTC cycling, no portrait-rotation problem.

**What to look for in the output** (the script prints it on its own): the chosen backend.
If it still says `Selected NVIDIA Direct-Mode backend!`, the DRM lease wasn't used and the
test doesn't count. The Wayland/lease path has to show up.

And then, as always: **look inside the headset.** The API is going to happily report
90.0 fps with the panel black.

### Wayland executed: blocked in KWin, but with three measured rule-outs (2026-08-04, 20:05)

There ended up being no 90Hz test: the DRM lease path couldn't be brought up. But the
journey left verified findings worth more than the attempt itself.

**1. Patch 0002 WORKS. Measured, not deduced.** The headset's connector is marked
`non-desktop=1` and KWin leaves it out of the desktop (lists only the 3 monitors). Read from
the kernel with `scripts/drmprops.c`:

```
connector 130  type=10  CONNECTED  modes=3
    non-desktop  = 1
    mode: 4320x2160@90
    mode: 2880x1440@90
    mode: 4320x2160@60
```

With that: **the NVIDIA driver side is doing its part.** All three modes are exposed, the
HMD is marked as leasable. What's missing is further up the stack.

**2. Monado was built WITHOUT Wayland, and nothing gave it away.** The runtime symptom was
`Could not find target factory with identifier 'direct_wayland'`. Root cause: missing
**`libdrm-dev`**, and Monado's CMake logic is

```cmake
option_with_deps(XRT_HAVE_WAYLAND ... DEPENDS WAYLAND_FOUND WAYLAND_SCANNER_FOUND
                 WAYLAND_PROTOCOLS_FOUND LIBDRM_FOUND)
```

meaning without libdrm Wayland falls **entirely**, and with it `XRT_HAVE_WAYLAND_DIRECT`.
CMake doesn't warn: it just leaves the options OFF and builds anyway. `bootstrap-lab.sh`
brought in `libwayland-dev` and `wayland-protocols` but not `libdrm-dev` — already fixed,
with a comment explaining why. Reconfigured and rebuilt: `WAYLAND: ON`, `WAYLAND_DIRECT: ON`.

**3. With all that resolved, KWin doesn't offer the connector.** Monado sees the device but
zero connectors:

```
INFO [_drm_lease_device_drm_fd] Available DRM lease device: /dev/dri/card0
INFO [comp_window_direct_wayland_init] Found no connectors available for direct mode
```

That exact symptom is reported on the [NVIDIA forum](https://forums.developer.nvidia.com/t/nvidia-proprietary-non-open-modules-completely-unable-to-acquire-a-drm-lease-on-any-display-server-all-known-nvidia-drivers-any-hardware/341244)
as a DRM lease failure with NVIDIA drivers, unresolved as of Nov 16, 2025. The thread is about
the closed modules, but there's one report with **open** modules on an RTX 4080. Plasma 6.3.6
still doesn't have the "VR Mode / Display Leasing" toggle (it's in a draft KWin MR).

**Trap for whoever picks this up next:** `XRT_COMPOSITOR_FORCE_VK_DISPLAY` **is not an
innocent alternative.** It enumerates all system displays and with index `0` grabbed the
user's LG monitor, not the headset (`Will use display: LG Electronics LG ULTRAGEAR (HDMI-0)`),
and segfaulted. If tried, the HMD's index needs to be identified first.

#### What Project-VR actually needs (and raises the cost of replicating it)

Rereading their README with a focus on the runtime: **it's not just "GNOME instead of
KDE".** They use GNOME 50 / mutter 50.1 **with their own Mutter patches**, SteamVR as the
runtime, their WMR fork loaded inside `vrserver`, and their own orchestrator (`g2-studio` /
`infra/g2ctl`).

The nuance that leaves the door open: their Mutter patches are so *"the desktop doesn't
hang during/after VR"* (lease lifecycle, input/render freezes) — **not** to make the lease
work in the first place. So *unpatched* Mutter should still offer the connector, and that's
what discriminates whether the problem is KWin or NVIDIA.

**Next test, in order of cost:** install GNOME and try a GNOME Wayland session with
`jack-in-wayland.sh`. If Mutter offers the connector, the problem was KWin and that's the
path forward. If it doesn't offer it either, the problem is NVIDIA + DRM lease, matching the
forum thread, and a call has to be made on whether it's worth replicating Project-VR's whole
stack or staying at 60Hz.

### GNOME/mutter executed: the lease works, 90Hz still fails (2026-08-04, 20:45)

The discriminating test from the previous block has been run, and it answers the two
pending questions — one in favor and one against.

**1. The culprit for the lease was KWin, not NVIDIA.** With Debian 13's GNOME 48.7 /
mutter 48.7, **with no patches at all**, the headset's connector shows up offered for lease.
Read with `wayland-info` (`scripts/check-lease.sh`):

```
interface: 'wp_drm_lease_device_v1', version: 1, name: 35
	path: /dev/dri/card0
	connector:
		id: 130
		name: DP-1
		description: HPN
```

| | KWin 6.3.6 | mutter 48.7 |
|---|---|---|
| advertises `wp_drm_lease_device_v1` | yes | yes |
| offers connectors | **zero** | **connector 130 `DP-1 (HPN)`** |
| lease granted | no | **yes** |

And Monado takes it without a fight:

```
INFO  [_lease_connector_done] [/dev/dri/card0] connector DP-1 (HPN) id: 130
DEBUG [_lease_fd] Lease granted
DEBUG [compositor_try_window] Target backend wayland-direct initialized!
DEBUG [get_primary_display_mode] found display mode 4320x2160@90.00
```

This **rules out the NVIDIA forum thread** for our case: 595.71.05-open grants leases
perfectly fine. The bug was in the compositor. Project-VR's mutter patches aren't needed to
bring up the lease, just as predicted.

**2. And yet 90Hz fails exactly the same way.** Physical verification, the user with the
headset on:

| mode | via | lease | mode taken | what's seen inside |
|---|---|---|---|---|
| 1 | Wayland DRM lease | granted | `4320x2160@90.00` | **HP logo, dead panel** |
| 2 | Wayland DRM lease | granted | `4320x2160@60.00` | **perfect image** |

The 60Hz control was run *after* the failure, via the same path and with the same lease, so
the path is sound and the result is clean. This brings the 90Hz failures to **eight**.

**What this closes off.** We changed the entire video path — X11 NVIDIA Direct-Mode →
Wayland DRM lease, two mechanisms that barely share any driver-side code — and the failure
didn't budge: exact same symptom, same HP logo. Combined with the patched 595-open failing
the same as the unpatched one, there's almost no surface left on the NVIDIA side where the
cause could be hiding.

**What does NOT follow from this.** While writing this section it was said that the
HID-command hypothesis remained "the only one that explains the eight results", and the
Windows HID capture was proposed as the next step. **That was a mistake**: the earlier block
(`TURN`, 19:30) had already ruled it out, and `CLAUDE.md` had gone stale, still treating it
as alive. Worse: a few hours later HP's driver was read and it was confirmed that **the mode
command doesn't exist** (`docs/09-oasis-driver-re.md`). The mistake is left written down
because it's exactly the kind of relapse this project has already paid for three times.

**The real next step is in the section below**, and it doesn't need booting Windows.

#### Trap that cost a debug cycle: the player exits on EOF on stdin

`hello_xr` v3 reads transport keys from stdin, and **`EOF` is how it terminates**
(`case EOF: // the pipe on stdin closed - this is how a timed run ends`). Launching it with
`< /dev/null` kills it in under a second, with **exit 0 and not a single error line**: the
Monado log shows `client_connected`, swapchains created and destroyed, and
`client_disconnected`, with no `BEGIN_SESSION` from the app at all. It looks like a
compositor failure and it isn't. The correct way is the documented one: `sleep N | hello_xr ...`.

Watch out, this clashes with `XRT_NO_STDIN=1`, which IS needed for **monado-service**
(without it, it dies with `epoll_ctl(stdin) failed`). They're two different processes: the
service needs stdin taken away, the player needs it given to it alive.

### The DSC theory doesn't survive the arithmetic (2026-08-04, 21:30)

With the HID hypothesis dead for the second time (see `docs/09-oasis-driver-re.md`), the
suspect left standing was DSC: if the panel only obeys the video timing, 90 Hz fails because
the timing it receives isn't decodable, and Project-VR's patch 0001 claims to address exactly
the DSC 1.1 *"90 Hz handshake"*.

Before chasing it, the real numbers were pulled from the headset's EDID, read from the
kernel (`/sys/class/drm/card0-DP-1/edid`, 3 blocks: base + CEA + DisplayID 2.0):

| mode | pixel clock | totals | 24 bpp | 30 bpp | works? |
|---|---|---|---|---|---|
| 2880x1440@90 | 428.6 MHz | 2980x1598 | **10.29 Gbps** | 12.86 Gbps | **NO** |
| 4320x2160@60 | 709.1 MHz | 4420x2674 | 17.02 Gbps | 21.27 Gbps | **YES** |
| 4320x2160@90 | 905.4 MHz | 4420x2276 | 21.73 Gbps | 27.16 Gbps | **NO** |

Link capacity, 4 lanes HBR3 (8.1 Gbps/lane, 8b/10b → 80% usable): **25.92 Gbps**.

**The `2880x1440@90` mode asks for 10.29 Gbps — less than HALF of the `4320x2160@60` that
works perfectly.** There's no way that mode needs compression: it fits three times over in
the link. And it fails just the same as the other one.

Only `4320x2160@90` at 30 bpp exceeds the link and would genuinely need DSC. So **DSC could
at most explain one of the two failing modes, and doesn't explain the other.**

The only thing the two failing modes have in common is **90 Hz**. It's the same pattern
that has already shown up three times in this project: every bandwidth theory collapses once
measured. That makes four.

Watch out for the nuance in the old `CLAUDE.md` note ("the 60 mode that works has a higher
pixel clock than the 90 mode that fails"): it's true, but it was comparing `4320x2160@60`
(709 MHz) against `2880x1440@90` (428 MHz). It doesn't hold against `4320x2160@90` (905 MHz).
The correct statement is the one in the table.

**The cheapest discriminating test, and it hasn't been run:** `2880x1440@90` (mode 0) via
the **Wayland DRM lease** path. It's only been tried on X11 direct-mode. If it also fails via
lease, DSC is ruled out as the cause for that mode and the suspect becomes the refresh rate
itself — something about the handshake or the panel bring-up at 90 Hz, not bandwidth or
compression.

```bash
./scripts/jack-in-wayland.sh 0     # 2880x1440@90
# and PHYSICAL verification, as always
```

### Our own instrument does NOT work on NVIDIA: KMS doesn't drive this display (2026-08-04, 22:30)

An attempt was made to build an independent instrument (`scripts/hmd-modeset.c`) that would
modeset the headset's connector via DRM lease, without Monado or Vulkan, to sweep refresh
rates. **It doesn't work, and the reason why is a finding in itself.**

The mandatory control was requesting the NATIVE mode `4320x2160@60` — the one Monado drives
with a perfect image. Result, with physical verification:

| step | result |
|---|---|
| mutter lease | granted, with CRTC and 2 planes |
| `AddFB2` XRGB8888 on dumb buffer | accepted |
| `drmModeSetCrtc` legacy | **accepted** |
| `drmModeAtomicCommit` with ALLOW_MODESET | **accepted** |
| `drmModeGetCrtc` readback | `mode_valid=1  4320x2160  fb=144` |
| page flip (legacy AND atomic) | **EINVAL**, 0.00 flips/s |
| **what's seen in the headset** | **HP logo — no signal** |

In other words: **every KMS ioctl says yes, and nothing goes out over the cable.**

The cause: running `strings` on `monado-service` shows it uses
`VK_EXT_acquire_drm_display`, `VK_KHR_display`, and `VK_EXT_direct_mode_display`. **Monado
doesn't program the display via KMS: it programs it via Vulkan.** In the NVIDIA driver,
DRM/KMS is a partial layer for direct-mode/leased displays — it accepts the commits and
reports `mode_valid=1`, but what actually programs the hardware is `nvidia-modeset` via the
Vulkan path. This also explains why Project-VR drags in all of SteamVR instead of doing
modeset by hand.

**Practical consequence:** any experiment with custom modes has to go through
`vkCreateDisplayModeKHR` (VK_KHR_display allows requesting arbitrary `visibleRegion` +
`refreshRate`), not KMS. The refresh sweep is still the right experiment, but the vehicle is
Vulkan.

#### And the HP logo means less than we thought

The HP logo was reproduced **at 60 Hz**, with a mode known to be good. So the logo is
simply the state "panel powered, no signal lock" — **it's not a signature of the 90 Hz
failure**. All previous readings remain valid (the panel doesn't lock), but the logo by
itself doesn't distinguish "the 90 mode is bad" from "there's no signal at all".

#### Two other data points measured along the way

- **The screen-enable `{0x04,0x01}` alone is NOT enough to power the panel.** Without the
  full `wmr_hmd_activate_reverb()` sequence (the `{0x50,0x01}` loop x4 and the gets
  0x09/0x08/0x06) the headset stays completely off, not even the logo appears. Replicated in
  `scripts/panel.py activate`, which also returns real data from the headset (the 0x09 get
  brings back what looks like the serial number, `REDACTED`).
- **Screen-off can make the companion RE-ENUMERATE** and change its hidraw node (seen
  `hidraw8` -> `hidraw7`). This is direct evidence bearing on the open USB2 hub reset
  problem: they're not random under load, they're triggered by the power-off command.

#### nvidia-modeset parameters that turned up while looking into this

`/sys/module/nvidia_modeset/parameters/` exposes, among others: `config_file`,
`output_rounding_fix`, `opportunistic_display_sync`, `debug`, `debug_force_color_space`,
`conceal_vrr_caps`, `disable_vrr_memclk_switch`, `hdmi_deepcolor`, `enable_overlay_layers`.
None investigated yet. `config_file` and `output_rounding_fix` smell the most relevant to
timings.

### OWN INSTRUMENT WORKING: 60 yes, 90 no, measured without Monado (2026-08-04, 23:30)

`scripts/hmd-vk.c` drives the panel via the same path as Monado — Vulkan display, not KMS —
taking the connector via DRM lease and passing that fd to `vkGetDrmDisplayEXT` /
`vkAcquireDrmDisplayEXT`. **It works.** It's the project's first instrument independent of
Monado, the compositor, and OpenXR.

New protocol, prompted by a real problem: runs had a fixed duration and a test could "time
out" while the user was still looking, and afterward it wasn't clear which run each response
corresponded to. Now runs hold **indefinitely** until killed, and each test is logged with an
ID and the user's textual verdict in `docs/pruebas.jsonl` (`scripts/testlog.py`).

| test | mode | bandwidth | fps presented | **what the user sees** |
|---|---|---|---|---|
| T001 | `4320x2160@60.000` | 17.02 Gbps | 59.99 | **"everything flashing"** — alternating colors |
| T002 | `2880x1440@89.999` | **10.29 Gbps** | 89.98 | **"hp lit up, screen off"** |

Both runs share the binary, the Vulkan path, the HID activation sequence, and the color
pattern. **The only thing that differs is the refresh** — and the mode that fails asks for
less than half the bandwidth of the one that works.

With this, measured with our own instrument and physical verification, the following are
independently ruled out: bandwidth, DSC, Monado, the compositor, and the entire OpenXR
stack.

#### The refresh sweep is blocked by the driver, at BOTH layers

You can't request a refresh that isn't in the EDID:

```
KMS   : drmModeSetCrtc with synthetic modeline      -> EINVAL
Vulkan: vkCreateDisplayModeKHR 2880x1440 @ 61/62/65/70/75/80/85 Hz
                                                   -> VK_ERROR_INITIALIZATION_FAILED (-3)
```

And **Vulkan reports exactly the same 3 modes as the EDID** (89.999 / 90.001 / 60.000 Hz),
not one more. So sweeping requires **injecting a modified EDID**; the most likely route is
the NVIDIA driver's `CustomEDID` option on X11 (DRM core's EDID override doesn't work: nvidia
doesn't use the `drm_edid_*` helpers).

#### Correction: the display bridge is an ANX7530, not the CrossLink

In the previous commit, the Lattice CrossLink `LIF-MD6000` was flagged as the primary
suspect. **That was wrong.** Lattice's datasheet doesn't mention DisplayPort, and its VR use
cases are MIPI DSI 1:2 bridging and camera aggregation. The firmware version string clears it
up:

```
STM:%02X.%02X.%02X;DFU:%02X.%02X.%02X;ANX7688:%02X.%02X.%02X;ANX7530:%02X.%02X.%02X;
```

The real DP->MIPI DSI bridge is an **Analogix ANX7530** (specced for VR up to 120 Hz), plus
an ANX7688. The CrossLink is the camera aggregator. There's also an **STM32** and a **DFU**
route: `bridge_fw_check_update`, `bridge_fw_switch_bank`, `QCI_FEATURE_ERASE_FLASH`,
`QCI_FEATURE_DFU_NEW`, `SMARTBRIDGE_UNINITIALISED`. So the bridge firmware is updatable — but
those routes are for *updating*, not per-session init, so they don't support the idea that
the bridge needs to be initialized from the host on every boot.

### THE HEADSET TELLS US IT'S AT 90 (2026-08-04, 23:00) — sink-side instrumentation

The lead came from a Monado comment in `control_read_packets()` (`wmr_hmd.c`): the
companion sends a `DEVICE_STATUS` (0x05) message when the screen state changes. Captured
with `scripts/panel-status.py` while `hmd-vk` requests each mode:

| mode requested | companion message | byte 5 |
|---|---|---|
| `4320x2160@60` (works) | `05 00 01 01 00 3c 00 00 00 05 2c 1e 02 ...` | **0x3c = 60** |
| `2880x1440@90` (fails) | `05 00 01 01 00 5a 00 00 00 0c 1a 14 02 ...` | **0x5a = 90** |
| `4320x2160@90` (fails) | `05 00 01 01 00 5a 00 00 00 09 38 14 04 ...` | **0x5a = 90** |

**Byte 5 is the refresh rate in decimal.** It tracks the refresh, not the resolution: the
two 90 modes, with different resolutions, both report `0x5a`. Byte 11 goes along with it:
`0x1e` (30) at 60 Hz and `0x14` (20) on both 90 ones.

**Consequence, and it reorders the entire diagnosis:** the headset RECEIVES the 90 Hz
signal, measures it, and reports it as 90 — with the panel showing the HP logo. It doesn't
reject it or fall back to 60. And since **there is no HID command that tells it the mode**
(cap. 09), that number can only come from measuring the incoming timing.

In other words: the DisplayPort signal arrives fine, with the correct timing, and the
bridge locks onto it enough to count the 90 Hz. **The failure is after that point**, in how
the ANX7530 or the panels bring up 90.

That rules out the whole "the link doesn't train" / "the timing is invalid" family, which
is exactly where we were about to aim the report to NVIDIA. And it explains why the driver
log reports success with not a single error: **the attach genuinely succeeds.**

Watch out for a nuance: Monado's comment describes, for the Reverb **G1**, a second message
`05 01 01 01 01 ...` that arrives when the backlight *visibly* turns on. On our G2, bytes 1
and 4 are `00` in ALL cases, **including the working 60Hz one** — so those bytes aren't the
"backlight on" flag on the G2, or that message isn't emitted. Don't use them as a signal.

Bonus: this is the project's first sink-side instrumentation, and it lets you read what
refresh the headset thinks it's at **without anyone putting it on**.

### DECODED the headset's DEVICE_STATUS, and the A/B that changes everything (2026-08-04, 23:45)

#### Confirmed: the headset measures and reports the exact timing

Matrix of 7 trials alternating modes in both directions (`scripts/decode-status.sh`), with
the full 33 bytes of the `0x05` message:

| offset | meaning | evidence |
|---|---|---|
| byte 5 | **refresh in decimal** | `0x3c`=60, `0x5a`=90 in two different resolutions |
| bytes 19-20 | **htotal**, little-endian | `44 11`=4420, `a4 0b`=2980 |
| bytes 21-22 | **vtotal**, little-endian | `72 0a`=2674, `3e 06`=1598, `e4 08`=2276 |
| byte 2 | screen enabled (0→1 with screen-enable) | seen by isolating the HID activation |

The three values match **exactly** with our EDID's modes, in all three cases:

```
60Hz  4320x2160  ->  refresh 60  htotal 4420  vtotal 2674
90Hz  2880x1440  ->  refresh 90  htotal 2980  vtotal 1598
90Hz  4320x2160  ->  refresh 90  htotal 4420  vtotal 2276
```

**Firm conclusion: the signal coming out of the GPU reaches the headset with the correct
timing, at 90Hz too.** The headset measures it and reports it correctly. With the HID
activation but WITHOUT video, those fields come back zero — meaning the headset fills them in
by measuring, not by echoing back what it was told.

#### What did NOT work: the automatic detector

It seemed an automatic verdict had been found: `byte 1 = 1` showed up in 3 of 3 messages
from the mode that works and in 0 of 8 from those that fail, and it matched Monado's comment
for the G1 (*"once the HMD screen backlight visibly powers on"*).

**It didn't survive validation.** Tested twice against the known-good 60 mode: one gave
"FAIL" and the other emitted no message at all. `byte 1 = 1` shows up **only sometimes**,
even when the panel actually turns on. It's useful as a hint (it never appeared at 90Hz), but
**not as an instrument**. Verification remains PHYSICAL.

`scripts/hmd-test.sh` stays in the repo with that warning written into it.

#### The missing A/B: with AMD the G2 DOES reach 90Hz

From the protocol sweep: in Monado issue #332, user `dimitriscr` ran the A/B we couldn't run
— **same G2, same cable, swapped an RTX 3060 for an RX 7800 XT, and 90Hz works with AMD.**

That **corrects** the conclusion this document was carrying a few hours earlier ("the
failure is on the headset side"). The headset measuring and reporting 90 didn't mean the
signal was usable; it meant it measured the frequency. **It's NVIDIA.**

Reinforcements from the same sweep:
- Bug 5923212 is confirmed by NVIDIA staff and **reproduced by 8 users**, from Ampere to
  Blackwell, drivers 535 to 610, **proprietary and open-kernel alike**. It explains why the
  595-open patches didn't move anything.
- **thaytan**, author of Monado's WMR driver, states that after the *enable display*
  command nothing over USB influences the mode: the negotiation is entirely DP at the GPU
  driver level. Independent confirmation of what we got from disassembling HP's driver.
- The **ANX7530 has no DSC** on its MIPI output, and it's configured over I2C from the
  headset's STM32. If something needed reprogramming for 90Hz, it would be a firmware write
  at boot.
- The **HTC Vive Pro uses the same ANX7530** (teardown). **Project North Star** uses an
  ANX7530 with open firmware: it's the reference if the chip ever needs to be talked to
  directly.
- Another user (`Kukeltje`) reported seeing `DMA CMT ERR` on the HID channel `0x03 DEBUG`
  during the 90Hz attempt. **Pending**: hunt for it on our rig (`scripts/hunt-debug.py`).

### The headset's firmware log, read in plain text (2026-08-05, 00:30)

**The G2 emits its own firmware log over HID**, in ASCII, on the `0x03 DEBUG` channel of
the HoloLens Sensors interface. 509-byte packets with several entries concatenated:

```
magic "Dlo+" | 4 bytes timestamp | 2 bytes sequence | 1 byte level | ASCII text
```

Real captures: `RequestImuDisable forSpi=0`, `ImuDisable Req=0 Spi=0`,
`RequestImuEnable forSpi=0`, `ICMStart`, `ICM start status=0`,
`ERROR: CommandSet st 0, cmd 0, reqCmd 23`.

**The channel is SILENT until someone runs the headset's configuration sequence.** Our
`hmd-vk` doesn't run it and nothing came out; `monado-service` does run it and the channel
starts talking. Tool: `scripts/fwlog.py`.

#### And the control rules it out as a lead

In Monado issue #332 another user reported `DMA CMT ERR` on this channel during the 90Hz
attempt. **It doesn't show up here.** What does show up is a repeating error every 5 s:

| | 90Hz (fails) | 60Hz (works) |
|---|---|---|
| `ERROR: CommandSet st 0, cmd 0, reqCmd 23` | every 5 s | **every 5 s** |

It's present in BOTH: it doesn't discriminate. It's noise from the controllers subsystem
(`reqCmd 23` = `0x17 CONTROLLER_STATUS`).

**What matters is what's NOT there: the firmware doesn't log a single panel error at
90Hz.** It measures the correct timing (see the DEVICE_STATUS block) and doesn't complain
about anything. And the panel still doesn't turn on.

### BOM: the ANX7530 has just enough margin, and its datasheet says "up to 4K x 2K @ 60Hz"

- **`ANX7530` bridge** (Analogix): DP 1.4 input and **two independent MIPI-DSI
  transmitters, one per panel, 8 lanes at 1.5 Gbps/lane = 12 Gbps per output**. Per panel at
  90Hz: 2160x2160 x 90 x 24bpp = **10.08 Gbps**. It fits, with little margin. Its product
  brief is titled **"up to 4K x 2K @ 60Hz"**.
- **Panels**: a user's teardown gives the part `AA029M48000 REV.02`, labeled "JDP".
  Commercial candidate **Sharp LS029B3SX06/06A**: 2.9", 2160x2160, CG-Silicon LTPS, MIPI-DSI
  with 2 channels x 4 lanes, **no integrated backlight**. No confirmation from Sharp naming
  the G2.
- **`ANX7688`**: its datasheet places it on the host side (HDMI2.0+USB3.1 -> USB-C). **No
  source explains what it does inside the headset.**
- **Backlight driver**: no public data.

#### FCC filings located (grantee Quanta, code HFS)

| FCC ID | date | product |
|---|---|---|
| HFS-A85P | 2019-03-21 | Reverb G1 |
| **HFS-A85Q** | 2020-06-05 | **hypothesis: base G2** |
| HFS-A85R | 2020-09-30 | G2 Omnicept (its own SKU, e.g. `3A7X9AA`; **not** `VR3000-0XX`, which is the base G2 — corrected T232, see docs/63) |
| HFS-A85KL / -A85KR | 2020-08 | left/right controllers |

The **internal PCB photos** for A85Q and A85R have been located
(`fccid.io/HFS-A85Q/Internal-Photos/...`) but **not read**: they're scanned PDFs with no text
layer and no proxy could OCR them. **It's the cheapest gap to close: someone with a browser
opens them and looks.**

#### Installed base: no sales figure exists

**No official sales figure exists** for the G2 or for WMR — not from HP, not from
Microsoft, not in IDC/Counterpoint. The only real series is the Steam Hardware Survey, which
aggregates all WMR:

| date | WMR among Steam VR users |
|---|---|
| jun-2018 | 6.25% |
| 2019 | peak ~10% |
| sep-2022 and dec-2023 | ~5% |
| **jul-2026** | **1.99%** |

It's still at 1.99% **after** Windows 11 24H2 (Oct 2024) dropped native support. There's no
public estimate of how many are still in use.

### Pending items that need sudo (don't block the 90Hz test)

1. **RT priority for Monado.** The log throws `Could not raise priority for thread
   'VBlank Events'` and `'Multi Client Module'`. It was tolerable at 60Hz; at 90Hz vblank
   pacing is the last thing you want competing for CPU. Needs a re-login:
   `printf '@plugdev - rtprio 99\n@plugdev - nice -20\n@plugdev - memlock unlimited\n' | sudo tee /etc/security/limits.d/99-monado.conf`
2. **Headset audio out of the picture** for as long as the lab lasts: udev rule
   `72-wmr-audio-off.rules` with `ATTR{authorized}="0"` for `0bda:4c15`. It doesn't fix the
   hub reset (cap. 06), it just takes the audio out of the re-enumeration cycle.
3. **zram** (16 GB RAM, 12 threads): `systemd-zram-generator`, `zram-size = ram / 2`, zstd,
   `swap-priority = 100`, `vm.swappiness=180`. Safety net for builds, not an accelerator.
   Don't build the three projects in parallel: ninja already saturates all 12 threads with
   just one, and basalt's RAM peak is what can trigger the OOM.
4. **Deps basalt is missing**: `libbz2-dev liblz4-dev libssl-dev` (ROS drags in more).
   Doesn't block anything as long as `3dof` is used, which is the mode for all the 360/video
   work.

## Rollback

- Nothing on the main system was touched: BIOS boot menu → old disk → everything as
  before.
- Inside the lab: `sudo dkms remove nvidia/595.71.05 --all`, delete the `PATCH[]` lines
  from dkms.conf, `sudo dkms install nvidia/595.71.05` → stock 595 driver.

## If 90Hz runs stable

Only then does the "ideal setup" get planned (decision already made with the user): Debian,
two dedicated users — `vr` (X11 session, jack-in at login) and `edit` (Resolve, cap. 05) —
in a final installation. Not before: the cutoff criterion is "the headset on par with
Windows or better".
