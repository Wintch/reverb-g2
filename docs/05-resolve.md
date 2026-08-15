# 05 — DaVinci Resolve on the lab rig (makeresolvedeb)

Path the user already validated: [makeresolvedeb](https://www.danieltufvesson.com/makeresolvedeb),
which converts Blackmagic's official installer into a clean .deb for Debian.

## Installation

```bash
# 1. Download the official Resolve .run/.zip (Linux) from blackmagicdesign.com/support
# 2. Download the makeresolvedeb script from danieltufvesson.com/makeresolvedeb
# 3. Generate and install the deb (example with the free version):
unzip DaVinci_Resolve_*_Linux.zip
./makeresolvedeb_*.sh DaVinci_Resolve_*_Linux.run
sudo dpkg -i davinci-resolve_*_amd64.deb
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
