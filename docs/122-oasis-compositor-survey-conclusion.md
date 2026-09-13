# 122 — Oasis/Wayland compositor survey: conclusive, but not a "nobody can do this" verdict

Date: 2026-09-13

## Summary

This session completed a full compositor survey for getting Oasis (via Ignition) working on
this rig's Wayland pipeline, after `docs/121` left one lever untested. The survey is now
conclusive for *this specific combination* (Oasis/Ignition + this exact rig), but external
research shows the underlying compositor-level failures are well-known, general Linux-VR-on-NVIDIA
issues, not evidence that VR-on-Linux-with-NVIDIA is broadly impossible.

## The four-way compositor test, final results

| Compositor | DRM lease offered? | Result |
|---|---|---|
| X11 (NVIDIA native direct-mode) | n/a (different mechanism) | Blocked: `Failed to acquire xlib display` / `VRInitError_Compositor_CannotDRMLeaseDisplay` (same as `docs/119`) |
| GNOME/mutter (Wayland) | **Yes** — connector 130 DP-1 "HPN" offered cleanly | Oasis's own `vrcompositor` fails via a Wayland-roundtrip race (`Tried to find direct display through Wayland: (nil)`), even though the lease is genuinely available |
| KDE/KWin (Wayland) | No — announces `wp_drm_lease_device_v1`, zero connectors | Already known-bad since 2026-08-04 (this rig's own `docs`/git history), unrelated to Oasis |
| Sway/wlroots (Wayland, forced `--unsupported-gpu`) | No — same zero-connectors symptom as KWin | Newly tested today, same result |

GNOME/mutter is the only compositor on this rig that correctly offers the DRM lease for the G2
at all with the NVIDIA driver in use (595.71.05-open).

## Correcting course mid-session: KDE was never "the untried lever"

`docs/121` listed KDE Plasma as one of two untried, Valve-documented-supported alternatives.
That was wrong — `git log --follow -- scripts/check-lease.sh` surfaces a comment, and commit
`e72b5a4` (2026-08-04), showing KWin's zero-connector NVIDIA bug was already discovered months
ago, in a completely different investigation (the 90Hz panel-blank saga) — it's the reason this
rig runs GNOME/mutter for its whole production VR pipeline in the first place, not something
left over to try for Oasis. Lesson: check a diagnostic script's own git history before calling
a path "untried."

## Is this an NVIDIA-Wayland dead end for everyone? No — checked externally before concluding that

The user pushed back on an early framing of this ("me parece raro, todos usan nvidia") — right
call, worth checking against outside evidence before writing anything as a hard conclusion:

- **KWin + NVIDIA DRM leasing is a known, public, still-open community bug**, independent of
  this rig or of Oasis: [`NVIDIA/open-gpu-kernel-modules#251`](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/251)
  (opened 2022-05-24, still open): *"neither driver works over Xwayland, Kwin added DRM leasing
  support, which works fine with AMD cards, but not Nvidia ones."* Matches our result exactly.
- **wlroots (Sway/Hyprland/LabWC) has a long, explicit history of not prioritizing NVIDIA
  support** — Sway's `--unsupported-gpu` launch flag used to be named literally
  `--my-next-gpu-wont-be-nvidia` in older releases. Its DRM-lease implementation failing on
  NVIDIA specifically is consistent with that stance, not a fluke of this rig.
- **GNOME/mutter's NVIDIA DRM leasing genuinely works**, and this isn't unique to us — it's
  precisely why GNOME is the de facto standard desktop for Linux VR users on NVIDIA (Monado,
  ALVR, etc. all commonly run there). Our own Monado stack already runs successfully on it in
  production.
- **The one piece that is genuinely unresolved, and specific to Oasis/Ignition, not to
  Linux+NVIDIA in general**: `BnuuySolutions/Ignition`'s GitHub issue tracker has exactly 2
  issues total, neither about Wayland — meaning nobody has publicly reported success *or*
  failure on the specific "Oasis + GNOME/Wayland + NVIDIA" combination before us. This is a
  brand-new, low-adoption project; the SteamVR-side Wayland-roundtrip race we're hitting
  (`docs/121`) is unreported territory, not a confirmed dead end. It is very plausibly a real,
  fixable bug in `vrcompositor`'s own client-side lease-acquisition code (the same class of bug
  already fixed/tracked upstream in Monado, see [[project_monado_upstreaming]] issue #614) —
  worth filing (`docs/119`, still in draft) precisely because nobody else seems to have hit or
  reported it yet, not despite that.

## Bottom line

- Our own Monado-based solution remains the one that actually runs on this rig today — that
  hasn't changed. But it isn't "the only thing that exists in the world for NVIDIA+Wayland VR"
  — it's one instance of a broader, viable, widely-used pattern (native OpenXR driver + GNOME).
- What's actually stuck is narrower than "Oasis on Linux is impossible": it's specifically
  "Ignition's SteamVR-side Wayland client code has an unreported bug that nobody else has hit
  yet, on the one compositor (GNOME) where the lease itself is available." That's a real,
  reportable, plausibly-fixable gap — not a wall.
- No further compositor-hopping is warranted; the remaining lever is filing/tracking the
  upstream report.

See also: `docs/108` (strategy), `docs/117`/`docs/119` (bug drafts), `docs/121` (this session's
earlier compositor tests, corrected by this doc regarding KDE).
