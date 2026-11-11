# 04 — Lab 90Hz: Debian on separate SSD + patched 595-open driver

> **Outcome:** 90Hz RESOLVED. The 6bpc-clamp patch (`patches/nvidia/0004`, found via this
> lab, ch. 13) is the complete fix: both native modes light clean on the plain EDID, and
> real video through the full player at `4320x2160@90` (mode 1, via `jack-in-wayland.sh` +
> DRM lease on GNOME) is flicker-free. Resolution chain: `docs/19`; retrospective:
> `docs/21`. This chapter keeps the lab install procedure and rollback, plus a summary of
> the early dead ends. The panel-status, firmware-log and bridge facts that came out of
> the lab live in `docs/12`.

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
- **X11 session** was the original lab choice: the Monado pipeline started on NVIDIA
  direct-mode via X11/XRandR. Wayland DRM lease on GNOME is now the verified 90 Hz path
  (`scripts/jack-in-wayland.sh`, with NVIDIA patch 0002); it needs a compositor with
  lease support (Project-VR validated it on patched GNOME/mutter) and is untested on KDE.
- This machine boots **BIOS/legacy → no Secure Boot or MOK**. One less step.

## Step 1 — Base install (spare SSD)

1. Connect the spare SSD (to a chipset-controller port, see ch. 00).
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

Build Monado + Basalt in the lab (ch. 01), run `jack-in.sh`, and confirm that 90Hz
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
PATCH[3]="0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch"
EOF

# Verify they apply in dry-run BEFORE rebuilding:
for p in patches/000*.patch; do sudo patch -p1 --dry-run < "$p" || echo "FAILED: $p"; done

# Rebuild + reinstall the module:
sudo dkms remove nvidia/595.71.05 --all
sudo dkms install nvidia/595.71.05
sudo reboot
```

`PATCH[3]` (0004) is the actual fix (ch. 13): 0001-0003 alone do not light the panel at 90Hz.

Note: `dkms` applies `PATCH[]` to a copy at build time — the source tree stays
clean, and a kernel upgrade re-applies everything automatically. If a future
`apt upgrade` brings 595.91.07, the patches still apply (verified against that tree);
on 610.x you have to drop the two `flatnessDetThresh` hunks from 0001 (NVIDIA already
fixed that there) — the rest is still needed.

## Step 5 — Monado with the 90Hz fix

Apply our patches (`patches/monado/`) to the lab's Monado. The 90 Hz nominal frame
interval on WMR screens (`nominal_frame_interval_ns = 1e9/90` in `wmr_hmd.c`, by Ashish Kumar
Singh of Project-VR) is already carried as `patches/monado/0018`, and
`scripts/bootstrap-lab.sh sources` applies it with the rest of the series. Without it the
SteamVR bridge computes 1/0 and falls back to 60Hz with judder.

## Step 6 — The test

```bash
./jack-in.sh 3dof     # but with XRT_COMPOSITOR_DESIRED_MODE=0  (2880x1440@90 native)
# and if it fails, try =1 (4320x2160@90)
```

**Look at the panel physically.** The API reports success and 90fps even when the panel is
black — the only valid verification is the eye. Expected result with patches: image at 90Hz
and goodbye to the 60Hz backlight-strobe flicker.

Record which mode worked, stability (15+ min), temperature/clocks
(`nvidia-smi -q -d SUPPORTED_CLOCKS` — do NOT copy Project-VR's lock-clocks, those are for Ada),
and re-run the video smoke test from ch. 02 (the NVDEC/cuvid path should work the same on
595; verify it explicitly).

### Baseline result — lab (Debian 13, KDE/X11, 595.71.05-open WITHOUT patches)

Verified **physically**, headset on, with `hello_xr` showing a test equirect:

| `XRT_COMPOSITOR_DESIRED_MODE` | mode reported by the compositor | what's seen inside the headset |
|---|---|---|
| 2 | 4320x2160@60.00 | correct image + the usual 60Hz strobe |
| 0 | 2880x1440@90.00 | **panel off, only the HP logo** |
| 1 | 4320x2160@90.00 | **panel off, only the HP logo** |

595-open by itself does NOT fix 90Hz; the failure is identical to the 550's. Mode numbering
is the same on 550 and 595 (`Found 3 modes`: 0=2880x1440@90, 1=4320x2160@90, 2=4320x2160@60),
but the table is only printed with `XRT_COMPOSITOR_LOG=debug` (`COMP_PRINT_MODE`). In both
90Hz modes every software layer reports success (`BEGIN_SESSION` with no close, 89.999/90.001
Hz frame interval); only the eye tells.

### After installing the patched module

Check the loaded module is the patched build (the version stays 595.71.05 either way),
that all five USB devices are present, then run the test:

```bash
modinfo nvidia-modeset | grep -E "^filename|^version"
ls -l /lib/modules/$(uname -r)/updates/dkms/nvidia-modeset.ko.xz
lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"
cd ~/vr && XRT_COMPOSITOR_LOG=debug XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof
grep -E "found display mode|frame interval" ~/vr/jack-in.log   # confirm it picked up @90
```

`dkms` leaves `/usr/src/nvidia-595.71.05/` itself unpatched and `dkms.conf` carries the
`PATCH[]` lines, so a kernel upgrade re-applies everything. The machine boots BIOS/legacy,
so MOK signing is irrelevant. Content for the headset: `hello_xr --graphics Vulkan2` with
`HELLO_XR_PHOTO360` pointing at a test equirect, fed with a long `sleep` on stdin (the
player exits on EOF).

## Early dead ends (all superseded by ch. 13 and `docs/19`)

Ruled out with measurements while 90Hz still failed on 0001-0003:

- **Display contention / Wayland vs X11:** 90Hz fails the same on X11, on Wayland with a
  DRM lease on GNOME/mutter (KWin refuses the lease).
- **"Nobody tells the headset to go to 90Hz":** Monado sends identical HID traffic at 60 and
  90Hz and HP's driver has no mode command either (`docs/09`, `docs/12` §4).
- **Bandwidth and DSC:** the failing 2880x1440@90 mode needs 10.29 Gbps, less than half of
  the working 4320x2160@60 (17.02 Gbps); the DSC arithmetic does not explain it.
- **Monado, compositor, OpenXR:** `scripts/hmd-vk.c` (Vulkan display, no Monado) reproduces
  60 works / 90 fails. KMS cannot drive this display on NVIDIA (`scripts/hmd-modeset.c` is
  kept because that failure is informative).
- **The headset rejecting the signal:** it measures and reports the exact timing at 90Hz
  (`DEVICE_STATUS`, `docs/12` §5), and its firmware log shows no panel error (`docs/12` §6).
  The signal reaches the headset; the failure was the 6bpc clamp in NVKMS (ch. 13).
- **Control that mattered:** with an AMD GPU the same G2 reaches 90Hz (Monado issue #332),
  which moved the diagnosis from "the headset" to "NVIDIA".

## Optional lab hardening

- Realtime priority for Monado (log warns `Could not raise priority for thread 'VBlank Events'`;
  needs a re-login): `printf '@plugdev - rtprio 99\n@plugdev - nice -20\n@plugdev - memlock unlimited\n' | sudo tee /etc/security/limits.d/99-monado.conf`
- Keep the headset audio device out of the re-enumeration cycle with a udev rule setting
  `ATTR{authorized}="0"` for `0bda:4c15` (it does not fix the hub reset, ch. 06).
- zram as a build safety net (`systemd-zram-generator`, `zram-size = ram / 2`, zstd,
  `swap-priority = 100`). Do not build Monado, Basalt and the rest in parallel: ninja already
  saturates all threads and Basalt's RAM peak can trigger the OOM.
- Basalt needs `libbz2-dev liblz4-dev libssl-dev`.

## Rollback

- Nothing on the main system was touched: BIOS boot menu → old disk → everything as
  before.
- Inside the lab: `sudo dkms remove nvidia/595.71.05 --all`, delete the `PATCH[]` lines
  from dkms.conf, `sudo dkms install nvidia/595.71.05` → stock 595 driver.
