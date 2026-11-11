# 90 — GPU video decode capability for the 360/VR180 player

The question this answers: **can a given GPU feed the 360/VR180 player in real time with a given
file, before anyone puts the headset on?** The player's black-screen failure mode makes an
above-the-driver "it plays" claim worthless, and video decode is one of the few things that can be
measured honestly without a wearer.

## Method (machine-agnostic, no sudo)

Measure decode throughput per file, three ways, using only ffmpeg built with cuda/cuvid (Debian's
stock build has it) and `nvidia-smi`:

- **`hw`**: `ffmpeg -hwaccel cuda -i FILE -f null -`. The NVDEC path **with silent software
  fallback**, so it must be cross-checked against decoder utilisation (below).
- **`cuvid`**: explicit decoder, e.g. `ffmpeg -c:v hevc_cuvid -i FILE -f null -` (or `av1_cuvid`).
  A hard failure on an unsupported codec, so this is the honest hardware number.
- **`sw`**: software decode, all threads (`ffmpeg -i FILE -f null -`). The only meaningful mode on a
  non-NVIDIA box.

For each (file, mode) record frames, wall seconds, fps, **speed_x** (ffmpeg's own `speed=Nx`, the
real-time multiple: anything under 1.0 cannot play in real time on this machine; an 8K60 file needs
>= 1.0 at 60 fps), CPU cores used, and GPU watts / util / **decoder util** / clocks sampled alongside
(`nvidia-smi --query-gpu=power.draw,utilization.gpu,utilization.decoder,clocks.sm --format=csv -lms 500`,
or `nvidia-smi dmon -s u`). **Decoder util is the honest signal that NVDEC really ran**: `util.gpu`
alone can be high on the software path from the frame upload into `-f null`. A `hw` row whose decoder
util stays near zero is a silent software fallback.

Re-run after any card or driver change. For no-wearer VR pacing, `scripts/gpu-pacing-baseline.sh`
brings the rig up 3dof (headset on the desk), sweeps synthetic GPU load (`scripts/gpu-load-sweep.sh`)
at one or more power caps, and records late-frame rate versus load, so two cards or two rigs can be
compared by number, not by feel (detached, unconditional teardown, GUI-env discovery, same contract as
`scripts/light-preflight.sh`).

## Findings that generalise

1. **The VR180/360 test library is AV1-encoded, not HEVC.** `ffprobe` on every file says so (the 8K60
   showcase clip and the newer captures are AV1; only older SDR clips are HEVC). Check the codec of the
   *content* before assuming a card can play it.
2. **An Ampere-class card (RTX 30-series) hardware-decodes everything, including 8K60 AV1, with about
   2x headroom** (the 8K60 AV1 clip ran at ~1.95x real time on NVDEC at ~99% decoder utilisation).
3. **A Pascal-class card (GTX 10-series) has no AV1 hardware decoder.** Both the `hwaccel` and `cuvid`
   AV1 paths return zero frames (`failed` / `unsupported`). It hardware-decodes 8K **HEVC** fine
   (about 2x real time at 8K30), but AV1 falls back to CPU: 8K60 AV1 in software reached only ~1.37x
   in decode-only, which is marginal and gets worse once the GPU is also rendering/warping the stereo
   view.
4. **Both generations handle 8K HEVC in hardware with real headroom**, so an HEVC-transcoded library is
   a universal path; otherwise keep AV1 playback on an Ampere-or-newer card.
5. **The codec of the content matters more than raw GPU class for pure playback**: an older card that
   decodes your codec beats a newer one that does not.
