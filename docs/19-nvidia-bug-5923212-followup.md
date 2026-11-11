# 19 — Follow-up for the 5923212 bug thread (60Hz-only on NVIDIA)

Thread: https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744
(NVIDIA `abchauhan` confirmed the reproduction and opened internal bug **5923212** on
2026-03-20; the bpc root cause and patch are in the separate thread
[379240](https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240),
PR [#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275)).

## The patch DOES work (2026-08-06): exact cause of the earlier "90 Hz is impossible" conclusion

`docs/16-lab-vblank.md` (a vblank/pixel-clock factorial run with injected timings) concluded
that 90 Hz was ruled out on this link, and that a "~709 MHz only" pixel-clock pattern pointed
at the bridge chip. **That conclusion was wrong.** Nobody had retested the **EDID-native
modes, with no override loaded**, with the bpc patch active. The chain:

1. The first test of the native `2880x1440@90` mode with `hmd-vk` (DRM lease) failed ("HP logo
   on, screen off") on 2026-08-04, **before the bpc bug was found** (2026-08-05), i.e.
   before the patch existed.
2. That failure turned into a working assumption ("2880x1440 never showed anything at any
   refresh rate") that was quoted from memory in later notes.
3. The extensive factorial that did run with the patch active (595.71.05, patch 0004 present,
   `Notify Attach Begin` at 24 bpp) never used the native modes as the EDID declares them: all
   cells used synthetic timings injected through `nvidia_modeset.config_file` (for example
   `vblank=240` instead of the real 116), to isolate vblank as a variable.
4. In one of those sessions `hmd-vk list` even showed `[0] 2880x1440@89.999` as available; it
   was skipped as "already known to FAIL", citing the pre-patch result.
5. The real native mode was finally run with no override at all (confirmed with no
   `nvidia_modeset.config_file` loaded) and it lit up. Same for the native supersampled mode
   (`hmd-vk native 1`, descriptor #1 unmodified, real vblank 116).

Wayland-vs-X11, DRM lease vs Direct Mode, or a driver reinstall are not the explanation. The
sufficient explanation: the patch fixes the bug, and the old "native 90Hz fails" result was
never remeasured after the patch existed. The ANX7530 datasheet line "4K x 2K x 60Hz" that the
bridge-chip hypothesis leaned on does not hold up as a ceiling either.

Lesson kept for future investigations: a negative result recorded before a fix must be
re-run after the fix, and a test with injected timings does not replace the plain native mode.

## The residual 90Hz flicker: resolved

After the patch the panel still looked like it flickered at ~60 Hz although HID, compositor
timing (11.111 ms) and the API all confirmed 90 Hz. Result with a static solid white pattern
(`HMD_VK_SOLID=1` in `hmd-vk`) and a physical verdict:

| Mode | Verdict |
|---|---|
| 2880x1440@90 native | clean |
| 4320x2160@90 | clean (also straight after a 60Hz session: order-independent) |
| 4320x2160@60 | flickers |

Linux then behaves exactly like Windows (on Windows 60Hz flickers and 90Hz does not): the 60Hz
flicker is factory backlight behavior at a non-native panel frequency, not a driver problem.
Two methodology corrections:

- `hmd-vk`'s color test alternates color **every frame**, which at 90 fps is a ~30Hz strobe by
  construction: those observations were the test flickering, not the panel. Only real video
  through Monado is a valid check.
- The one earlier flicker seen with real video did not reproduce after a full reboot and
  several USB unplug/reconnect cycles of the headset, with the driver side unchanged. Most
  plausible (hypothesis, unprovable without AUX access): backlight state stuck on an old
  timing config and cleared by the power cycle; the firmware manages backlight duty from the
  detected timing (Windows driver strings `left duty %d, right duty %d, frame timing %d`,
  see `docs/09-oasis-driver-re.md`). For anything flicker-related read
  `docs/112-flicker-resolved-two-causes.md`.

The public forum posts were edited with this correction, so the public record reads: 90Hz
works and is clean with the bpc patch; the one driver issue left standing is the bpc default
when the EDID leaves color depth undeclared.

## What Windows does (measured, no special sauce)

With CRU on a Windows machine driving the same headset, the active 90Hz timing is
`2880x1440 @ 89.999 Hz (428.58 MHz)`, `htotal=2980 vtotal=1598`: exactly the unmodified EDID
base-block DTD. Windows drives both the 60Hz mode (709.15 MHz, DisplayID descriptor #2) and
the 90Hz mode "as-is" from the EDID. A USB capture (Wireshark + USBPcap) of a live 60->90 and
90->60 switch shows **no additional HID command**, only the usual 33-byte `DEVICE_STATUS`
report updating refresh/htotal/vtotal. HWiNFO64, GPU-Z and NVIDIA's control panel show no DSC
and the G2 is not even a selectable display in direct/HMD mode.

Ruled out (no need to repeat):

- Stereo/3D bits in the EDID: base-block DTD byte 17 and the two DisplayID Type I descriptors'
  byte 3 declare no stereo; the only bit that differs between the working and failing native
  descriptors is `preferred`.
- Inspecting DPCD/AUX from software: `/sys/kernel/debug/dri/*/DP-1/` has only `edid_override`
  (ignored by NVIDIA, see `docs/16`), `force`, `output_bpc` and `vrr_range`; there is no `dpcd`
  file. USB capture can never see AUX/DPCD (it runs over the DP cable). Only a DisplayPort
  protocol analyzer would.
- Microsoft's original WMR driver packages: the candidates found are the sensor/IMU driver,
  not the video path. `driver_oasis.dll` does not touch video timing at all (it speaks HID/USB
  and sends `Display Enable`, see `docs/09`), so mode negotiation lives entirely in the
  standard NVIDIA driver. Black-screen-at-90Hz reports also exist for Microsoft's own Mixed
  Reality Portal on AMD and NVIDIA, so the G2's 90Hz is somewhat fragile on every platform.

## Driver landscape check (2026-08-18, source level)

PR #1275 still OPEN with zero maintainer engagement since 2026-08-06 (CLA bot only). New
releases 595.91.07 (stable) and 610.57.04 (feature, Blackwell) touch nothing we depend on, and
`nvkms-dpy.c` at the 610.57.04 tag still carries the pre-patch bpc clamp byte-for-byte
(grepped directly). Patches 0001/0003/0004 apply clean against 610 source; 0002 (DRM lease,
10 files) needs a real `git am --check` before any upgrade.

**Operational hazard, keep loud**: the NVIDIA CUDA apt repo for Debian 13 offers 610.57.04, so
an unpinned `apt full-upgrade` would silently replace the patched driver and BREAK 90Hz. The
apt pin to 595.71.05-1 (priority 1000) is the guard; never remove it casually.

**Verdict: stay on 595.71.05 + patches.** Revisit triggers: (a) PR #1275 gets maintainer
movement; (b) a changelog mentions DP EDID color-depth/bpc, DRM lease, or VR; (c) a Debian
kernel bump breaks the 595 dkms build; (d) new GPU hardware.

## Live thread/RT audit (2026-08-18, running 6dof session, Ryzen 5 3600)

37 threads in monado-service. Exactly THREE run SCHED_FIFO:99 (absolute max): `WMR: USB-HMD`
(the USB read thread), `VBlank Events`, and one unnamed thread (almost certainly the
compositor renderer). Everything else, including all Basalt VIO workers, is SCHED_OTHER and
floats freely across all 12 CPUs. Two findings for per-title profile work:

1. RT assignment is coarse: three threads at the absolute ceiling, everything else
   unprioritized, nothing in between. Whether SLAM's optical-flow/backend threads deserve a mid
   RT band (SCHED_RR 10-50?) has never been tested.
2. Observability gap: Basalt worker threads carry no pthread names (`comm` =
   "monado-service"), making per-thread profiling/affinity assignment blind. A cheap patch
   naming them (`pthread_setname_np`) unlocks a per-core-ownership design.
