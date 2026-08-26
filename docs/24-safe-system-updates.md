# 24 — Keeping this install up to date without losing VR

The goal stated by the user (2026-08-09): stay on the latest packages, not fall behind out
of fear of breaking things — but never lose a working VR stack to an update with no way
back. This chapter is the procedure, plus two scripts (`scripts/pre-update-check.sh`,
`scripts/post-update-verify.sh`) that do the checking so it isn't done by memory each time.

**Debian 13 (trixie) specific.** Every path, package name, and mechanism here (DKMS,
`/etc/kernel/postinst.d/dkms`, the exact `dkms.conf` PATCH[] convention, GRUB's "Advanced
options" submenu) was checked against this exact install. Never tried on another
distro/release — don't assume it transfers as-is.

**This procedure did not originally check for silent on-disk drift** — files dpkg still
believes it owns but that no longer exist, invisible to `apt`/`dkms status`/`dpkg --audit`
alike. `docs/73-nvidia-symlink-drift.md` found four such missing NVIDIA symlinks (GLX,
NVDEC, VDPAU, CUDA) with zero warning from any of those. `pre-update-check.sh` now runs
`dpkg -V` as a standard section to catch this before it's mistaken for update fallout.

## Why this needs its own procedure at all

Almost everything on this machine is safe to update anytime — desktop apps, codecs,
`jq`, `udisks2`, browsers. None of it touches the GPU/display/USB stack this project
depends on.

**Two categories are not "just update them" territory:**

1. **The kernel** (`linux-image-amd64`, `linux-headers-amd64`, `linux-libc-dev`). A kernel
   bump triggers a DKMS rebuild of the patched NVIDIA module — the same rebuild mechanism
   already confirmed present and working (`/etc/kernel/postinst.d/dkms` hook, standard
   Debian DKMS integration). This is **not inherently risky** — the `PATCH[]` lines in
   `/usr/src/nvidia-595.71.05/dkms.conf` (all 4: the DisplayID/VESA fix, the Wayland DRM
   lease enable, the forced max link config, and the load-bearing 6bpc-clamp fix that makes
   90Hz possible at all) get reapplied automatically on every rebuild. The risk is
   **trusting it blindly** — this project has already lost a session once to exactly that
   (`patches/monado/README.md`'s postmortem on a *different* drifted-build incident is the
   same class of mistake: assuming a rebuild did what the tracked patches say, without
   checking the actual build log).
2. **NVIDIA/EGL/Wayland userspace packages** (anything starting `nvidia-`, `libnvidia-`,
   `libegl-nvidia`). These need to move in lockstep with the kernel module version, and one
   of them (`libnvidia-egl-wayland*`) is directly in the path GNOME/mutter uses to publish
   the `wp_drm_lease_device_v1` global this entire project's Wayland pipeline depends on
   (see `docs/pruebas.jsonl`, 2026-08-09 session — this exact package came up mid-diagnosis
   of a DRM lease issue that night, for unrelated reasons, and turned out fine, but it's a
   real dependency to be aware of, not a coincidence).

## Keep the rollback kernel actually working

**Checked 2026-08-09 with `pre-update-check.sh`: on this machine, right now, the rollback
is real** — `dkms status` shows the nvidia module installed for both `6.12.100` (current)
and `6.12.94` (kept alongside it, Debian's normal behavior), and
`linux-headers-6.12.94+deb13-amd64` is present. (An earlier pass that same night, done by
hand instead of with the script, wrongly concluded this was missing — a manual `dpkg -l`
check gave a false negative for reasons not fully tracked down. Lesson kept on purpose:
**trust `pre-update-check.sh`'s own output over a one-off manual command**, and re-run it
if something here ever looks stale.)

**This isn't self-maintaining, though** — a DKMS build only exists for a kernel that had
headers installed *at the time* something triggered the build. If a future update ever
removes the second-newest kernel's headers, or the second-newest kernel itself gets
purged, the rollback quietly stops being real again until fixed:

```bash
sudo apt install linux-headers-<OLD_KERNEL_VERSION>   # check with: dpkg -l 'linux-image-*'
sudo dkms install nvidia/595.71.05 -k <OLD_KERNEL_VERSION>
/usr/sbin/dkms status   # should show BOTH kernels as "installed"
```

`pre-update-check.sh`'s "rollback kernel readiness" section checks exactly this — trust
its verdict, don't re-derive it by hand.

**Whenever a new kernel becomes "current" after an update (see procedure below), the kernel
that was current a moment ago becomes the new fallback — repeat this for whichever
kernel is now second-newest**, so there's always exactly one proven-working fallback with
a real DKMS build sitting ready, not just an installed-but-untested kernel image.

## The procedure

### 1. Before running `apt upgrade`

```bash
./scripts/pre-update-check.sh
```

Records the current known-good state (kernel, driver version, confirms all 4 patches are
applied cleanly in the *current* build log) and flags loudly if the pending upgrade queue
touches the kernel or anything NVIDIA/EGL-related — that's the signal to actually read the
rest of this chapter instead of just running `apt upgrade` on autopilot.

### 2. Run the upgrade

```bash
sudo apt update && sudo apt upgrade
```

Ordinary desktop-package-only upgrades: nothing else needed, go about your day.

**If the kernel or an nvidia-/libnvidia-/libegl-nvidia- package was in the list:**

### 3. Reboot

The DKMS postinst hook builds the new module automatically at this point — no manual
`dkms install` needed, it's already wired up (`/etc/kernel/postinst.d/dkms`).

### 4. After rebooting, before trusting VR again

```bash
./scripts/post-update-verify.sh
```

Checks, in order, refusing to say "OK" if any of them fails:

1. The running kernel actually matches the newest installed one (i.e., the reboot really
   picked it up — a stale GRUB default has bitten this project before, see `docs/06`).
2. `dkms status` shows the nvidia module **installed for the currently running kernel**,
   not just installed for some kernel.
3. The freshest DKMS `make.log` shows **all 4 patches** applied with no `FAILED`/reject —
   the exact same check `docs/pruebas.jsonl` T096 did by hand, now scripted.
4. `scripts/verify-bpc.sh` — the bpc-specific check (this is the one load-bearing patch
   for 90Hz existing at all; the other three matter but this one is the whole ballgame).
5. `scripts/preflight.sh` — USB/controllers/HMD connector, the same check used before
   every test session.

**Then — this doesn't get automated, per this project's core rule** — put the headset on
and run a real `jack-in-wayland.sh 1 6dof` session, confirm 90Hz with real content, before
considering the update fully trusted. Logs passing is necessary, not sufficient.

### 5. If step 4 fails anything

**Rollback**: reboot, pick "Advanced options for Debian" at the GRUB menu, boot the
previous kernel entry (the one made a real fallback in the one-time prep above). VR should
work immediately on that kernel — no rebuild needed under pressure, because the DKMS build
for it was already proven working beforehand. Debug the new kernel/driver combination at
leisure from there, not from a broken VR stack with the clock running.

## First real end-to-end run of this procedure (2026-08-09, kernel 6.12.101)

`post-update-verify.sh` caught a real bug in itself: step 3's `reject|FAILED` grep on the
fresh `make.log` false-positived on mangled C++ symbol names (`messageFailed`,
`RejectedByHW`, ...) inside harmless `objtool` "naked return" warnings — nothing to do with
whether the patches applied or the build succeeded (all 4 patches applied clean, `# exit
code: 0`). Same false-positive class as the DP check fixed the commit before this one.
Fixed by checking for real patch-reject markers and the build's own `# exit code: 0` line
instead of a bare keyword grep. Synced to `~/vr/`.

Everything else passed straight through: kernel/DKMS/patches clean, `verify-bpc.sh`,
`preflight.sh` (once the controllers were powered on — they were off from the previous
session). Full physical verification: `jack-in-wayland.sh 1 6dof` + `play360.sh` on the
real 3-video playlist — real `wmr` builder, both controllers registered, real
`wayland-direct` lease, `4320x2160@90` taken. One side note, not a regression: NVDEC
rejected the 4320px width (`Video width 4320 not within range from 48 to 4096`) and fell
back to software decode — still hit ~55-60 fps, no visible impact. User, headset on:
"sí, todo perfecto". Full detail: `docs/pruebas.jsonl` T108-T109.

## What NOT to do

- Don't run `apt upgrade` mid-VR-test-session (confounds any debugging already in
  progress — if something breaks, you won't know if it's the update or whatever you were
  already chasing).
- Don't assume a clean `apt upgrade` exit code means the DKMS rebuild also succeeded
  cleanly — DKMS failures during a kernel postinst don't always fail the whole `apt`
  transaction loudly. Always check the make.log, don't infer it from apt's own output.
- Don't purge old kernels (`apt autoremove --purge` on old `linux-image-*` packages)
  until confident the new one is solid — that's deleting the rollback.
