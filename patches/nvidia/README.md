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
- **0003** — `forceMaxLinkConfig` workaround-database entry for the G2's EDID (HPN 0x220E),
  so the DP link trains HBR3 x4 instead of 2 lanes.

Our contribution here is the **Debian delivery mechanism** (see `dkms/` and
`docs/04-lab-90hz.md`): applying these via the `PATCH[]` hook of the
`nvidia-kernel-open-dkms` 595.71.05 package from NVIDIA's debian13 repo, so they survive
kernel upgrades automatically — instead of Project-VR's Ubuntu-specific manual `.ko`
install. Project-VR was validated on an RTX 4080 (Ada); this repo tests Ampere (GA104).
