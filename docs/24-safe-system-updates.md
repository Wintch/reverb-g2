# 24 — Keeping this install up to date without losing VR

The goal stated by the user (2026-08-09): stay on the latest packages, not fall behind out
of fear of breaking things — but never lose a working VR stack to an update with no way
back. This chapter is the procedure, plus two scripts (`scripts/pre-update-check.sh`,
`scripts/post-update-verify.sh`) that do the checking so it isn't done by memory each time.

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

## One-time prep: make the rollback kernel actually work (do this now, not during an emergency)

**Found 2026-08-09: the rollback safety net was fake.** Two kernels are installed
(`6.12.100` current, `6.12.94` kept alongside it, Debian's normal behavior), which looks
like a rollback path — but `dkms status` only shows a build for `6.12.100`, and
`linux-headers-6.12.94+deb13-amd64` isn't installed at all. Booting into `6.12.94` today
would leave the machine with **no NVIDIA module for that kernel** — no time to build one
either, since headers aren't there. A "rollback" that requires a from-scratch DKMS build
under time pressure, possibly without network access to fetch headers, isn't a real
rollback.

**Fix, one time, whenever there's a few minutes to spare (not urgent, but do it before
relying on the rollback plan below):**

```bash
sudo apt install linux-headers-6.12.94+deb13-amd64   # match whatever the OLD kernel is,
                                                       # check with: dpkg -l 'linux-image-*'
sudo dkms install nvidia/595.71.05 -k 6.12.94+deb13-amd64
/usr/sbin/dkms status   # should now show BOTH kernels as "installed"
```

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

## What NOT to do

- Don't run `apt upgrade` mid-VR-test-session (confounds any debugging already in
  progress — if something breaks, you won't know if it's the update or whatever you were
  already chasing).
- Don't assume a clean `apt upgrade` exit code means the DKMS rebuild also succeeded
  cleanly — DKMS failures during a kernel postinst don't always fail the whole `apt`
  transaction loudly. Always check the make.log, don't infer it from apt's own output.
- Don't purge old kernels (`apt autoremove --purge` on old `linux-image-*` packages)
  until confident the new one is solid — that's deleting the rollback.
