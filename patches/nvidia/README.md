# NVIDIA open-gpu-kernel-modules patches (90Hz for the HP Reverb G2)

The three `.patch` files are **unmodified** from
[AshishKumar4/Project-VR](https://github.com/AshishKumar4/Project-VR)
(`patches/consolidated/nvidia/`, branch `g2-patches-on-595.71.05`) — full credit to
Ashish Kumar Singh for root-causing and fixing NVIDIA bug 5923212. See that repo for the
long-form analysis.

What each does:

- **0001** — spec-correctness fixes: DisplayID 2.0 Type-VII descriptor stride, VESA DSC 1.1
  RC tables (the 90Hz DSC handshake), `flatnessDetThresh`, MSFT VR VSDB version gate.
  All architecture-generic (`src/common/` + both the Turing/Ampere and Ada/Blackwell
  nvkms paths — our RTX 3060 Ti uses the `nvkms-evo3.c` path, which is covered).
- **0002** — VR HMD DRM-lease enablement. The Wayland lease machinery is dead code on X11,
  **but do not skip this patch**: its `nvkms-modepool.c` hunk marks the HMD's native mode
  as RandR-preferred, which the X11/SteamVR path needs.
  **Updated 2026-10-12 (code review, docs/147 §9 step 7):** the CREATE_LEASE hook leaked one
  `drm_master` reference per lease, and it held `idr_mutex` across the modeset locks, the
  reverse of the REVOKE_LEASE path. It now snapshots the leased CRTCs, drops both, then
  locks. It builds against 595.71.05 on kernel 6.12, but the module has **not been loaded on
  the rig yet**: test a lease (`jack-in-wayland.sh up`) before the next DKMS install.
  NVIDIA PR #1275 (the 615 port) still has the old hook. Still open: a lessee that exits
  without REVOKE_LEASE leaves its head's `lesseeFlipPermissive` set (N01-3/9). Clearing it
  on exit needs the `master_drop` path, which this change does not touch.
> **2026-10-10, probably a no-op — verify before relying on 0003**: DPLib's `getManufId()`
> (`dp_edid.h:129-135`) reads EDID bytes 8-9 little-endian (Apple's `06 10` is `case 0x1006` in the
> same database), so the G2's `22 0e` reads **`0x0E22`**, not `0x220E`. Faulto's 0003 uses `0x0E22`
> plus product `0x36C1`. 90 Hz never depended on this entry as far as we know (docs/144 §5).

- **0003** — `forceMaxLinkConfig` workaround-database entry for the G2's EDID (HPN 0x220E),
  so the DP link trains HBR3 x4 instead of 2 lanes.

Our contribution here is the **Debian delivery mechanism** (see `dkms/` and
`docs/04-lab-90hz.md`): applying these via the `PATCH[]` hook of the
`nvidia-kernel-open-dkms` 595.71.05 package from NVIDIA's debian13 repo, so they survive
kernel upgrades automatically — instead of Project-VR's Ubuntu-specific manual `.ko`
install. Project-VR was validated on an RTX 4080 (Ada); this repo tests Ampere (GA104).
