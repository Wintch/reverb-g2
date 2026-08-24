# 05 — DaVinci Resolve on the lab rig (makeresolvedeb)

Path the user already validated: [makeresolvedeb](https://www.danieltufvesson.com/makeresolvedeb),
which converts Blackmagic's official installer into a clean .deb for Debian.

## Current state (2026-08-24)

Checked on the lab rig (`iashur`):

- **`davinci-resolve` is NOT installed** (`dpkg -l | grep -i resolve` — nothing). No
  Resolve `.run`/`.zip` found anywhere on disk (`~/Downloads`, full filesystem search).
- **`makeresolvedeb` fetched and staged**: `~/resolve-install/makeresolvedeb_1.10.0_multi.sh`
  (v1.10.0, from `danieltufvesson.com/download/?file=makeresolvedeb/...`, no login needed —
  only Blackmagic's own installer is behind a login wall). Confirmed it's a plain bash
  script, not a binary blob. It auto-detects Resolve vs. Resolve Studio in the archive and
  builds the matching package, so no special flag is needed for Studio.
- **Prerequisites for the conversion**: `fakeroot` already installed (1.37.1.1-1).
  `xorriso` is only needed for Resolve 15.x — not installed, not needed for current
  releases (20.x).
- **NVIDIA CUDA driver: confirmed live and matches the VR project's stack.**
  `nvidia-smi` reports driver `595.71.05`, CUDA 13.2, RTX 3060 Ti, 0% util at idle.
  `dpkg -l` confirms `nvidia-open` + `nvidia-driver-cuda` + `nvidia-kernel-open-dkms`
  all at `595.71.05` — this is the same 595-open branch the 90Hz project runs on (not
  independently re-verified here whether the local 0004 bpc patch is baked into this
  exact build; irrelevant to Resolve, which only needs CUDA/NVENC/NVDEC, not the DP/EDID
  path). No extra driver install needed — the doc's `sudo apt install nvidia-driver-cuda`
  step is already satisfied.
- **~52G free on `/`** (207G total, 74% used). Conversion needs ~4x the downloaded
  archive size in scratch space; Resolve installs (Free or Studio) are commonly in the
  5-10GB installed range, so headroom should be fine for a single install but is worth
  watching if the Studio `.run` turns out to be large.

**IMPORTANT — Studio, not Free**: the user has a Resolve Studio USB activation dongle.
**Use DaVinci Resolve STUDIO for this validation, not the Free version**, and benchmark
Studio specifically. This matters for two reasons: (1) it's the version that will
actually be used, so it's the one whose stability under this driver is worth knowing;
(2) **Studio decodes H.264/HEVC/AAC natively** — the whole DNxHR-transcode workaround
below is a Free-version-only limitation and likely does not apply to Studio. Don't
assume that until it's checked directly with real camera footage, but don't reflexively
apply the Free-version workaround either. The dongle was NOT seen on `lsusb` during this
check (not currently plugged in) — plug it in before first launch of Studio.

**Blocked on a human step, can't be scripted around**: no Resolve installer of either
edition is present locally, and Blackmagic gates the Linux download behind a free-account
login on their site — this agent can't create/log into that account. **Manual step
needed**: go to
[blackmagicdesign.com/support/family/davinci-resolve-and-fusion](https://www.blackmagicdesign.com/support/family/davinci-resolve-and-fusion),
log in with the account tied to the Studio dongle, and download **DaVinci Resolve Studio
for Linux** (the `.zip` containing the `.run`). Save it anywhere (e.g. `~/Downloads`) and
say so — the conversion (`makeresolvedeb`, already staged) and `dpkg -i` install can then
be run directly, no further blockers expected before "does the process launch and stay
up," which is as far as this can be verified without a human looking at the actual
editing/playback quality (project rule: visual verification needs the user's eyes).

## Installation

```bash
# 1. Download the official Resolve STUDIO .run/.zip (Linux) from blackmagicdesign.com/support
#    (see "Current state" above — this is the step blocked on a human/login right now)
# 2. makeresolvedeb is already staged at ~/resolve-install/makeresolvedeb_1.10.0_multi.sh
#    (fetched 2026-08-24; re-fetch from danieltufvesson.com/makeresolvedeb if starting fresh)
# 3. Generate and install the deb (script auto-detects Free vs. Studio in the archive):
unzip DaVinci_Resolve_Studio_*_Linux.zip
~/resolve-install/makeresolvedeb_1.10.0_multi.sh DaVinci_Resolve_Studio_*_Linux.run
sudo dpkg -i davinci-resolve-studio_*_amd64.deb
```

GPU requirement: with the lab's NVIDIA stack (debian13 repo, `nvidia-open` +
`nvidia-driver-cuda`) Resolve finds CUDA with no extra steps. If missing,
`sudo apt install nvidia-driver-cuda`.

## The limitation you need to know about (free version on Linux)

**Resolve free on Linux does NOT decode H.264/HEVC or AAC** (Studio does). Typical
camera/phone footage comes in silent or doesn't come in at all. Standard workflow:
transcode to DNxHR before editing — and for that we already have NVDEC/NVENC on this
machine:

```bash
# H.264/HEVC -> DNxHR HQ + PCM (fast: NVDEC decode, ~no CPU)
ffmpeg -hwaccel cuda -i input.mp4 \
       -c:v dnxhd -profile:v dnxhr_hq -pix_fmt yuv422p \
       -c:a pcm_s16le output.mov
```

DNxHR HQ 4K ≈ 700 GB/hour — think about the destination (the NTFS NVMe is visible from
Linux for reading; for serious work a native partition is preferable, to be decided in
the ideal setup).

## Context note

Resolve was already validated running on the main system (August 2026 research session).
The lab re-validates it on the patched 595 driver — if Resolve shows artifacts or
instability there, that's important data BEFORE migrating the main system to the new
driver. In the ideal setup, Resolve lives under the `edit` user, with no VR running
alongside it.
