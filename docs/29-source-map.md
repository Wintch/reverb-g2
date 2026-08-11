# 29 — Source map: every repo, fork, and forum thread this project depends on

Purpose: one place with every external URL this project actually uses or has checked,
with *why it matters*, so neither machine (nor a future session on either one) re-clones,
re-searches for, or re-litigates something already found. Keep this current when a new
source gets pulled in or an old one turns out to be a dead end -- a wrong or stale entry
here is worse than no entry, so update in place rather than leaving it to rot.

## This project

- **`github.com/Wintch/reverb-g2`** -- this repo. Public since 2026-08-05. Docs, patches,
  scripts. Authoritative status lives in `NEXT-STEP.md` at the repo root, read that first
  in any session, not this file.

## Core upstream repos, actively patched (each has a `patches/<name>/` dir here)

- **Monado** -- `gitlab.freedesktop.org/monado/monado` -- the OpenXR runtime the whole
  stack runs on. Our G2 driver work lives in `patches/monado/`, pinned on `main@735e29e4e`.
  Four series already submitted upstream as MRs (see below); the 6DoF constellation series
  (0012+) is not filed yet, still local.
- **Basalt** -- `gitlab.freedesktop.org/mateosss/basalt` -- the VIO/SLAM library behind
  head tracking (`VIT_SYSTEM_LIBRARY_PATH`). No patches of our own here yet; if head-SLAM
  work resumes, check upstream state before assuming anything's still broken.
- **xrizer** -- `github.com/The-personified-devil/xrizer` -- the repo actually cloned and
  patched here (see `README.md`, `patches/xrizer/`), an OpenVR-compat shim that runs
  SteamVR titles against an OpenXR runtime (i.e. against Monado) without `vrmonitor`.
  **Note**: `github.com/Supreeeme/xrizer` also shows up referenced once, in
  `docs/25-standalone-app-research.md` -- likely the project this one forked from or an
  earlier reference point, relationship between the two not confirmed. If xrizer work
  resumes, verify which one is current before cloning fresh.
- **OpenXR-SDK-Source** -- `github.com/KhronosGroup/OpenXR-SDK-Source` -- upstream source
  for `hello_xr`, the reference OpenXR client this project extended into its own
  360/VR180/8K60 player (`patches/` under the everyday system's own checkout, not yet
  mirrored into this repo's own `patches/` dir as of this note -- check before assuming).

## NVIDIA driver

- **`github.com/Wintch/open-gpu-kernel-modules`** -- our fork, carries the 6bpc-clamp fix
  (`patches/nvidia/0004-nvkms-no-6bpc-clamp.patch`) that resolved the 90Hz bug. `upstream`
  remote points at NVIDIA's own repo below.
- **`github.com/NVIDIA/open-gpu-kernel-modules`** -- upstream. Our PR:
  `github.com/NVIDIA/open-gpu-kernel-modules/pull/1275`.

## Forum threads -- status and root-cause tracking, don't re-derive what's already posted

- **Our own bug, RESOLVED** -- `forums.developer.nvidia.com/t/.../379240` ("clamped to
  6 bpc...", internal bug **5923212**). Confirmed 2026-08-06: the 6bpc clamp was the real
  fix, clean 90Hz confirmed on this Ampere GPU. Answers "does anything run above 60Hz on
  this stack" -- **yes, since 2026-08-06, this headset does**, on this same NVIDIA driver.
  See [[reference-g2-90hz-nvidia-patches]] (session memory) and
  `docs/19-nvidia-bug-5923212-followup.md` / `docs/21-project-retrospective.md` here.
- **Original community report** -- `forums.developer.nvidia.com/t/.../337744` ("Reverb G2
  unable to drive more than 60Hz on NVIDIA") -- where bug 5923212 was first raised by
  someone else; our thread built on this.
- **Related, other headsets, same driver family** --
  `forums.developer.nvidia.com/t/.../341244` (DRM lease acquisition failures across NVIDIA
  drivers/hardware in general, not G2-specific).

## Reference forks, not merged in, worth re-checking if the local approach stalls

- **`gitlab.freedesktop.org/thaytan/monado`, branch `dev-constellation-controller-tracking`**
  -- an existing, working reference implementation of WMR controller 6DoF via constellation
  tracking (used by Envision-XR; wiki updated 2026-07-30 as of the last check). Our own
  0012-0018 series is an independent implementation, not a merge of this fork -- a trial
  merge was done once (8 conflicts, all mechanical CMake/device-list wiring, none touching
  our own patched files) and abandoned, not because it failed, but to avoid rewriting code
  under active upstream review at the time. Worth revisiting if our own controller-tracking
  exposure bug (see `NEXT-STEP.md`'s open problem #2) turns out to need a different
  approach than ours.

## Our own upstream submissions (Monado merge requests)

| MR | branch | what |
|---|---|---|
| `!2967` | `wmr-hid-resilience` | companion-drop tolerance, fw-read retry, bounded status wait |
| `!2968` | `wmr-controller-input-fixes` | squeeze click, haptic name, input timestamps, stick deadzone |
| `!2969` | `wmr-camera-stream-toggle` | `WMR_CAMERAS=0` |
| `!2971` | `steamvr-drv-origin-rpath` | `$ORIGIN` runtime path for pressure-vessel |

All at `gitlab.freedesktop.org/monado/monado/-/merge_requests/<number>`. Reviewer activity
so far: Jan Schmidt / thaytan commented on `!2967` (2026-08-06/2026-08-09) re: authorship
and relation to issue #491 -- see [[project-monado-upstreaming]] (session memory) for the
live back-and-forth, this file only tracks the URLs.

## Community references

- **LVRA wiki (Linux VR Adoption)** -- `wiki.vronlinux.org/docs/hardware/` (source repo:
  `gitlab.com/lvra/lvra.gitlab.io`, file `content/docs/hardware/_index.md`) -- community
  hardware-compat wiki. Has a stale G2-on-NVIDIA entry; a correcting MR is deliberately
  gated on one more independent G2+NVIDIA user confirming our finding first, not pushing
  to be first with an unverified claim. See [[project-lvra-wiki-correction]] (session
  memory).

## Internal surveys already done -- read these before re-researching from scratch

- **`docs/11-linux-hmd-landscape.md`** -- "is this NVIDIA-only, is this G2-only" survey
  across other headsets (Bigscreen Beyond: DSC corruption, bug 4834531; Index/Vive: judder,
  bug 5372097). **Marked RESOLVED/superseded 2026-08-06** once the 6bpc clamp confirmed our
  own root cause -- the survey's own opening note says so. Don't redo this survey; if the
  question comes up again ("does ANYTHING run above 60Hz on NVIDIA+Linux VR"), the answer
  for our own hardware is already yes, and this doc's table is the fuller landscape as of
  that date.
- **`docs/23-game-compatibility.md`** -- every SteamVR title tried against xrizer, with
  Steam AppID + SteamDB link, working/broken/failed/untested status and notes. Check here
  before re-testing a game that might already have a verdict.
- **`docs/25-standalone-app-research.md`** -- non-Steam VR app research (recovered
  delisted titles, DK2-era demos parked as a future idea, etc).
- **`docs/26-diagnostic-toolkit-and-buying-guide.md`** -- hardware fault decision tree +
  tool list, companion to `docs/22`.
- **`docs/27-verbose-logging-survey.md`** / **`docs/28-log-map.md`** -- what verbose
  logging exists across the stack (Steam/Proton/engines/OpenXR loader) and where to find
  it, so a new debugging session doesn't re-survey logging options from scratch.
