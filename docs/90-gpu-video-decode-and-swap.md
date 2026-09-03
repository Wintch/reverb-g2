# 90 — GPU video decode capability, and the two-card comparison

Two tools and one measured result set, produced 2026-09-03 after a GPU swap between the two
rigs. The question this answers: **can a given GPU feed the 360/VR180 player in real time
with a given file, before anyone puts the headset on?** The player's black-screen failure
mode makes an above-the-driver "it plays" claim worthless (see the project's core rule), and
video decode is one of the few things that *can* be measured honestly without a wearer.

## The tools (machine-agnostic, no config, no sudo)

- **`scripts/decode-bench.sh`** — decode throughput per file, three ways: `hw` (ffmpeg
  `-hwaccel cuda`, the NVDEC path with silent software fallback, flagged as `sw-fallback`
  when the decoder utilisation says NVDEC did not do the work), `cuvid` (explicit
  `<codec>_cuvid` decoder, a hard failure on an unsupported codec → `unsupported`), and `sw`
  (software, all threads). Per (file, mode) it records frames, wall seconds, fps, **speed_x**
  (ffmpeg's own `speed=Nx`, i.e. the real-time multiple — anything under 1.0 cannot play in
  real time on this machine), CPU cores used, and GPU watts / util / **decoder util** /
  clocks sampled alongside. Writes a `results.csv` plus a per-row ffmpeg log and nvidia-smi
  sample. `decode util` is the honest signal that NVDEC really ran; `util.gpu` alone can be
  high on the software path from the upload into `-f null`.

      ./scripts/decode-bench.sh -o OUTDIR file1.mp4 file2.mp4 ...

- **`scripts/gpu-pacing-baseline.sh`** — detached, no-wearer VR-pacing baseline: brings the
  rig up 3dof (headset on the desk), sweeps synthetic GPU load (`gpu-load-sweep.sh`) at one
  or more power caps, and records late-frame rate vs load. Meant to be re-run once per
  GPU/driver change so two cards (or two rigs) can be compared by number, not by feel. Same
  detached, unconditional-teardown, GUI-env-discovery contract as `light-preflight.sh`.

Both are Debian-checked but distro-neutral in what they call; `decode-bench.sh` needs only
ffmpeg with cuda/cuvid (Debian's stock build has it). On a non-NVIDIA box only `-m sw` is
meaningful.

## The measured result (2026-09-03)

Two cards, same five files, `cuvid` (explicit NVDEC) row quoted as the honest hardware
number. "Ampere" = an RTX 3060 Ti-class card; "Pascal" = a GTX 1070 Ti-class card. speed_x
is the real-time multiple (≥1.0 = plays in real time; the 8K60 file needs ≥1.0 at 60 fps).

| File | Codec | Res / fps | Ampere hw | Pascal hw |
|---|---|---|---|---|
| venice | HEVC | 8192×4096 @30 | 4.19× | 1.99× |
| insta4k | HEVC | 3840×1920 @30 | 14.8× | 7.89× |
| insta8k | HEVC | 7680×3840 @30 | 4.36× | 2.19× |
| insta8k | **AV1** | 7680×3840 @30 | 3.63× | **FAILS (no HW AV1 decoder)** |
| berlin | **AV1** | 7680×4096 **@60** | **1.95×** | **FAILS (no HW AV1 decoder)** |

### What this means

1. **The VR180/360 test library is AV1-encoded, not HEVC.** Earlier notes assumed HEVC; the
   `ffprobe` on every file says otherwise (the 8K60 showcase clip and the newer captures are
   AV1; only the older insta/venice SDR clips are HEVC). This changes the card recommendation.

2. **The Ampere card hardware-decodes everything, including 8K60 AV1, with ~2× headroom.**
   The 8K60 AV1 clip runs at 1.95× real time on the NVDEC path at ~99% decoder utilisation.
   Whatever machine holds the Ampere card is safe for the current library.

3. **The Pascal card has no AV1 hardware decoder at all** — both the `hwaccel` and `cuvid`
   AV1 paths return zero frames (`failed` / `unsupported`). It hardware-decodes 8K **HEVC**
   fine (2.19× at 8K30), but for the AV1 library it must fall back to CPU software decode:
   8K60 AV1 software reached ~1.37× real time here in decode-only, which is marginal and gets
   worse once the GPU is also rendering/warping the stereo view. **Pascal is a dead end for
   the modern AV1 VR library unless the content is transcoded to HEVC**, or AV1 playback is
   kept on an Ampere-or-newer card.

4. **Both cards handle 8K HEVC in hardware with real headroom**, so an HEVC-transcoded
   library is a viable universal path that works on either card.

### Recycling guidance (the point of the exercise)

- A Pascal-class card (GTX 10-series) is fine for an **HEVC** 8K VR library and for lighter
  VR titles, but cannot play the AV1 library in hardware. If a rig with a Pascal card must
  play AV1 content, transcode the library to HEVC 8K (both cards decode it) or move AV1
  playback to the Ampere box.
- The AV1-vs-HEVC codec of the *content* matters more than raw GPU class for this workload:
  an older card that decodes your codec beats a newer one that doesn't, for pure playback.

Raw per-mode CSVs (frames, watts, clocks, decoder util for all three decode paths) are kept
with the run; regenerate with `decode-bench.sh` after any card or driver change, the same way
the pacing baseline is re-run.
