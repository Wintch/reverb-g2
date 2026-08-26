# 73 — Four NVIDIA symlinks were silently deleted from disk; dpkg never knew

**Found 2026-08-25**, while diagnosing why Plasma X11 wouldn't come up cleanly (needed for
`resolve-linux` testing — see that repo, this project doesn't own DaVinci Resolve setup).
Not a VR-specific bug, but it broke a display path (`jack-in.sh`'s X11 direct-mode) this
project also depends on, and the detection method belongs in `docs/24`'s update discipline,
so it's recorded here.

## The symptom

Plasma X11 session started (Xorg, sddm, plasmashell all running, process-table-visible),
but the desktop never rendered correctly and `plasmashell` coredumped
(`systemd-coredump: Process 4493 (plasmashell) dumped core`). `Xorg.0.log` had the real
error, easy to miss if you only check exit codes or `systemctl status`:

```
(WW) Warning, couldn't open module glxserver_nvidia
(EE) NVIDIA: Failed to load module "glxserver_nvidia" (module does not exist, 0)
(EE) NVIDIA(0): Failed to initialize the GLX module
```

Xorg fell back to software GLX (`mesa`/`llvmpipe`), and whatever tried to use hardware GL
in that state (plasmashell's scenegraph) crashed.

## Root cause

`/usr/lib/xorg/modules/extensions/` had the versioned driver file
(`libglxserver_nvidia.so.595.71.05`) but **not** the unversioned symlink
(`libglxserver_nvidia.so`) that Xorg's module loader actually looks for. `dpkg -L
xserver-xorg-video-nvidia` says that package owns exactly that symlink path — so per dpkg's
own bookkeeping it should exist. It didn't. The file was deleted from disk by something
outside dpkg (most likely a side effect of one of the driver rebuild/reinstall cycles during
90Hz work — never pinned down exactly which one), and dpkg had no way to notice because
`apt`/`dpkg -l` only report package *install* state, not on-disk file presence.

`dpkg --audit` (which only flags packages stuck mid-install) was clean the whole time — it
does **not** catch this class of drift. The tool that does is `dpkg -V` (verifies every
file dpkg thinks it owns against disk, checksums where available, existence always).
Running it system-wide took a few seconds and turned up the complete picture in one shot —
**three more silently-broken symlinks**, all NVIDIA, none related to the GLX bug directly:

| missing path | owning package | breaks |
|---|---|---|
| `.../modules/extensions/libglxserver_nvidia.so` | `xserver-xorg-video-nvidia` | Xorg server-side GLX (this bug) |
| `.../x86_64-linux-gnu/libnvcuvid.so` **and** `libnvcuvid.so.1` | `libnvcuvid1` | NVDEC hardware video decode (ffmpeg, Resolve, this project's video player) |
| `.../x86_64-linux-gnu/libcuda.so` | `libcuda1` | link-time CUDA (the SONAME `libcuda.so.1` was intact — runtime CUDA was NOT broken) |
| `.../x86_64-linux-gnu/vdpau/libvdpau_nvidia.so.1` | `nvidia-vdpau-driver` | VDPAU hardware video decode |

Note `libnvcuvid.so.1` is the real SONAME, not a dev-only symlink — NVDEC was fully dead,
not just missing a build-time convenience link. This directly matters for the open item in
the main `CLAUDE.md` ("the NVDEC/cuvid path should work the same on 595, but it needs to be
verified explicitly") — it would **not** have worked; the check had never actually been run.

Everything else `dpkg -V` reported was noise: conffiles edited on purpose (`nvidia.conf`,
`/usr/src/nvidia-595.71.05/dkms.conf` — that's this project's own `PATCH[]` lines,
`zabbix_agent2.conf`) or paths with no recorded checksum at all (`sudoers`,
`fwupd.conf`, ...), which is normal and not a signal.

> **DO NOT `apt-get install --reinstall nvidia-kernel-open-dkms` to "fix" the
> `dkms.conf` line.** It came up again mid-session (2026-08-25, right after the three real
> fixes below) and almost got treated the same way. It is not the same class of problem:
> the three symlinks were deleted *outside* dpkg by accident; `dkms.conf`'s checksum differs
> because `bootstrap-lab.sh patch-nv` *deliberately* wrote the four `PATCH[0..3]` lines into
> it — that's the entire 90Hz fix (`0004` is the bpc-clamp patch). Reinstalling that package
> restores Debian's stock `dkms.conf` with no `PATCH[]` lines and turns 90Hz back off.
> Confirmed still correct after this scare:
> `grep 'PATCH\[' /usr/src/nvidia-595.71.05/dkms.conf` must show all four
> `0001`-`0004` lines. If it ever doesn't, that's `docs/04-lab-90hz.md`/`patch-nv` territory,
> not this doc.

## Fix

Reinstall each owning package — this re-extracts the package's files from the already-cached
`.deb`, no download needed, no version change:

```
sudo apt-get install --reinstall -y xserver-xorg-video-nvidia
sudo apt-get install --reinstall -y libnvcuvid1 libcuda1 nvidia-vdpau-driver
```

**`glx-alternative-nvidia` looked like the obvious first target and was a dead end** — in
this Debian 595 packaging, that package doesn't even own the broken symlink (`dpkg-divert
--list` shows no active diversions through `/usr/lib/nvidia/`, which is where that
package's postinst expects to find its source files; that directory is essentially empty
here). Reinstalling it changed nothing. Always confirm the actual owner with `dpkg -S
<path>` or `dpkg -L <package> | grep <name>` before reinstalling — don't guess from the
package name alone.

Xorg itself only loads GLX submodules once, at server startup — restarting the display
manager session on top of an already-running X server does **not** re-trigger the load. If
this happens again, `sddm` itself needs restarting (which tears down every session it
manages, including ones on other VTs/seats — warn before doing it), not just
`loginctl terminate-session`.

## Verification

```
dpkg -V 2>&1 | grep -v '^..5?????? c ' | grep -v '^????????? c '
```
should be empty (only conffile/no-checksum lines filtered out). Confirmed clean after the
reinstalls above. `Xorg.0.log` after the restart:

```
(II) Loading /usr/lib/xorg/modules/extensions/libglxserver_nvidia.so
(II) Module glxserver_nvidia: vendor="NVIDIA Corporation"
(II) NVIDIA GLX Module  595.71.05  Fri Apr 24 06:26:53 UTC 2026
```

No further `plasmashell` coredumps after relogin.

## Prevention

`scripts/pre-update-check.sh` now runs the same `dpkg -V` filter as a standard section,
before every future `apt upgrade`. It would not have prevented this particular drift (its
cause predates any tracked update), but it means the next occurrence gets caught before it
costs a debugging session instead of by accident while chasing something else.

**One-shot fix script:** `scripts/fix-nvidia-symlink-drift.sh` (reinstalls the 4 known
owning packages, re-verifies, warns about the `dkms.conf` false positive, tells you to
restart `sddm` if a stale X11 session is still up).

**Layered sanity check:** this incident is now `stage_os` in `scripts/sanity-check.sh`
(2026-08-25), a 3-stage check — OS+drivers, general software/Steam, VR stack — run
separately so a failure in one layer isn't mistaken for another (e.g. this driver-packaging
bug looks nothing like, and must not be diagnosed as, the T174 OpenVR-routing trap or a
headset/USB problem, even though all three can present as "nothing works"). Run
`./scripts/sanity-check.sh os` any time X11/NVIDIA feels off, independent of whether the
headset is even connected.
