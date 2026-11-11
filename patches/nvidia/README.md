# NVIDIA open-gpu-kernel-modules patches (90 Hz for the HP Reverb G2)

Four patches for the `nvidia-kernel-open-dkms` 595.71.05 package.

| Patch | Origin | What |
|---|---|---|
| 0001 | Project-VR, unmodified | Spec-correctness fixes: DisplayID 2.0 Type-VII descriptor stride, VESA DSC 1.1 RC tables, `flatnessDetThresh`, MSFT VR VSDB version gate. Architecture-generic: it covers the Turing/Ampere (`nvkms-evo3.c`) and the Ada/Blackwell paths. |
| 0002 | Project-VR, modified here | VR HMD DRM-lease enablement. The Wayland lease machinery is dead code on X11, but do not skip this patch: its `nvkms-modepool.c` hunk marks the HMD's native mode as RandR-preferred, which the X11/SteamVR path needs. |
| 0003 | Project-VR, unmodified | `forceMaxLinkConfig` workaround-database entry for the G2's EDID. **Confirmed a no-op** (2026-10-14): the entry matches manufacturer id `0x220E`, but DPLib's `getManufId()` reads EDID bytes 8-9 little-endian, so the G2's `22 0e` is `0x0E22` and the case is dead code. 90 Hz never depended on it. The file is kept so the series stays identical to Project-VR's, and the scripts that name it keep working. |
| 0004 | This repo | **The 90 Hz fix.** `nvDpyGetOutputColorFormatInfo()` treated "EDID declares no color depth" as 6 bpc and drove the DP link at 18 bpp. 0004 clamps to 6 bpc only when the sink actually declares a depth below 8, otherwise the existing 8 bpc default applies. Root cause and evidence: `docs/13-bug-6bpc.md`. Filed upstream as [NVIDIA/open-gpu-kernel-modules#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275). |

0001-0003 come from [AshishKumar4/Project-VR](https://github.com/AshishKumar4/Project-VR)
(`patches/consolidated/nvidia/`, branch `g2-patches-on-595.71.05`). Full credit to Ashish
Kumar Singh for the spec-correctness fixes (0001), the lease enablement (0002) and the
original G2 work in Project-VR. The bpc root cause and the 90 Hz fix are 0004 from this
repo (`docs/13-bug-6bpc.md`). Project-VR was validated on an
RTX 4080 (Ada); this repo tests Ampere (GA104, RTX 3060 Ti).

## 0002 changes made here

The original CREATE_LEASE hook leaked one `drm_master` reference per lease and held
`idr_mutex` across the modeset locks, the reverse of the REVOKE_LEASE path (code review,
`docs/147`). It now snapshots the leased CRTCs, drops both, then locks. Status: built against
595.71.05 on kernel 6.12, installed on the rig on 2026-10-13, 6/6 lease cycles passed and a
worn check showed a 90 Hz panel. PR #1275 (the 615 port) still carries the old hook. The 0004 bpc fix was also ported to 615.71.09: that driver moved the DP 6-bpc clamp into `nvDpyGetOutputColorFormatInfo()` and added `GetMaxOutputColorBpc()`, which returns 8 for an undefined EDID depth; the fix is the same guard in the new place (`if (info->input.u.digital.bpc != 0 && info->input.u.digital.bpc < 8)`). The 615 port is compile-tested only; the runtime proof is the 595.71.05 test in `docs/19`. Still
open: a lessee that exits without REVOKE_LEASE leaves its head's `lesseeFlipPermissive` set;
clearing it needs the `master_drop` path, which this change does not touch.

## Delivery

`scripts/bootstrap-lab.sh patch-nv` copies the four files into `/usr/src/nvidia-595.71.05/patches/`,
dry-runs each one, adds `PATCH[0..3]` to `dkms.conf`, then builds and installs through DKMS. The
patches are applied to a copy on every build, so they survive kernel upgrades. Project-VR's own
route is a manual `.ko` install on Ubuntu. Plan and test protocol: `docs/04-lab-90hz.md`. On
610.x drivers the `flatnessDetThresh` hunks of 0001 have to be dropped.

`scripts/pre-update-check.sh`, `scripts/post-update-verify.sh` and `scripts/sanity-check.sh`
check that all four patch files are still wired in after a driver update (`docs/24`).
