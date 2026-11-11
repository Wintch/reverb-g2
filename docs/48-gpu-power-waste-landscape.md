# "Heat without frames": GPU boost waste under CPU-bound load (2026-08-18, measurements 2026-08-23)

Trigger: an RTX 3060 Ti delivered identical VR frame pacing at a 105 W cap and at 210 W
stock (Aircar, three windows per arm, GPU pinned against the cap at 1515 MHz). The GPU
boosts to its power limit for zero delivered frames. Is this recognized industry-wide, or
unexplored?

## Landscape (desk research)

- **The mechanism is universal and vendor-unnamed.** GPU Boost (NVIDIA) / PowerTune (AMD)
  ramp clocks to the power/thermal limit whenever headroom exists, independent of need.
  No vendor documents "stays at max power when frame-capped or CPU-bound" as a behavior.
- **Efficiency curves are a press staple.** RTX 4090 at half TDP loses ~8%; granular
  figures: 80% PL gives 99.1% perf, 70% gives 97.8%, 60% gives 93.9%; peak efficiency
  sits around 75-80% PL.
- **Datacenter/HPC capping is mature** (Slurm power capping, official DGX guides, papers
  reporting ~19-26% energy saved for <4% perf loss via DVFS, arXiv 2402.18593).
- **Vendor mitigations are all opt-in and none is CPU-bound-aware**: AMD Radeon Chill and
  Frame Rate Target Control (off by default), NVIDIA Whisper Mode / Battery Boost
  (laptops) and Max Frame Rate (off by default); nothing found for Intel Arc.
- **The gap:** no desktop/VR tool uses measured frame delivery as the control signal. The
  closest, PULSE/AutoTDP (github.com/keiretrogaming/pulse), is a closed-loop fps-at-
  minimum-power controller for Android handhelds only.

This project's per-box `power.conf` with pacing-measured capping (pacing percentile as the
guard metric, not an fps target) is therefore a reasonable approach; see
`docs/68-power-management-and-lazy-boot.md`.

## The boundary case, measured: capping is NOT free when the GPU is the bottleneck

The "105 W == 210 W" result is specifically a **CPU/pacing-bound** finding: Aircar's frame
rate was gated by something other than GPU clock. As a control, **Quake II RTX**
(`timedemo 1`, demo `q2demo1`, 631 frames, full path-traced renderer) is genuinely
GPU-bound: 95% utilization, GPU clocked to its cap the whole run. Same box, same demo,
only the power limit changed (the power watchdog service was stopped for the duration so
nothing else touched the cap mid-run):

| GPU power limit | frames | time | fps | vs. 175 W |
|---|---|---|---|---|
| 175 W (70% of 250 W max, `power.conf`'s VR-tuned default) | 631 | 9.05 s | 69.73 | - |
| 100 W (40%, the idle-`saver` floor of `vr-power-watchdog.py`) | 631 | 11.94 s | 52.84 | **-24.2%** |

The flat `GPU_LIMIT_PCT` was validated against VR pacing specifically and is not a
universal "40-70% always costs nothing" result: it costs nothing exactly when something
else already caps delivered frames below what the lower wattage can supply, and costs real
fps the moment a title saturates the card.

## The `saver` floor does not reduce idle draw

Measured with `scripts/power-log.sh` (30 s windows, GPU via `nvidia-smi`, CPU package via
RAPL):

| state | GPU | CPU pkg | total |
|---|---|---|---|
| `saver` (100 W cap) | 19.9 W | 25.0 W | **44.9 W** |
| uncapped (250 W) | 19.8 W | 25.1 W | **44.9 W** |

Identical. A first pass measured `saver` at 67.6 W total; it was residual activity from the
preceding benchmark sweep still settling, and a re-measure gave the number above. At idle
the GPU is already at its lowest P-state (P8) regardless of the configured ceiling.

The `saver` floor is insurance against a spike while the machine is supposed to be at rest
(a stray background process using the GPU would otherwise be free to boost to 250 W), not
an idle-power saving. `vr-power-watchdog.py` therefore switches to `--apply` before
anything real runs rather than leaving the machine at the saver floor.

## The actual curve (Quake II RTX, 100/150/175/200 W, 2 reps each)

| watts (% of 250 W max) | rep 1 | rep 2 | mean | vs. 100 W |
|---|---|---|---|---|
| 100 (40%) | 54.01 | 52.88 | **53.45** | - |
| 150 (60%) | 69.37 | 71.62 | **70.50** | +31.9% |
| 175 (70%) | 76.03 | 70.13 | **73.08** | +36.7% |
| 200 (80%) | 75.59 | 73.50 | **74.54** | +39.4% |

**The knee is around 150 W (60%).** 100 to 150 W gains a real +31.9%; every step past that
is diminishing (150 to 175 W: +3.7%, 175 to 200 W: +2.0%), both smaller than the ~5-9%
rep-to-rep spread (175 W's two reps span 70.13 to 76.03). Two reps per level show the
shape but do not justify trusting a single number to better than ~5%. This matches the
generic efficiency curve above, localized to this card and title.

Practical note for any sweep script of this kind: run it as the normal desktop user, not
root. Under root, `steam -applaunch` has no Wayland session to launch into and `$HOME`
silently becomes `/root`, so every rep just times out with no error.

## Opens the door for

A workload-aware cap instead of one number for everything: classify per title (as
`docs/23`'s per-game profiles do for tracking settings) whether it is pacing-bound (VR
titles measured so far) or GPU-bound (this Quake II RTX case, likely most path-traced or
raster-heavy titles) and apply the aggressive cap only in the former case. Not built:
`vr-power-watchdog.py`'s "performance" mode is one flat number (`power.conf`'s
`GPU_LIMIT_PCT`) for every kind of active workload.
