# "Heat without frames": GPU boost waste under CPU-bound load — landscape (2026-08-18)

Trigger: T209 measured this box's RTX 3060 Ti delivering IDENTICAL VR frame pacing
at a 105W cap vs 210W stock (Aircar, three windows per arm, GPU pinned against the
cap at 1515MHz) — the GPU boosts to its power limit for zero delivered frames.
The user's question: is this recognized industry-wide, and per-vendor, or unexplored?

## Established (with sources)

- **The mechanism is universal and press-documented, vendor-unnamed**: GPU
  Boost (NVIDIA) / PowerTune (AMD) ramp clocks to the power/thermal limit whenever
  headroom exists, independent of need. No vendor whitepaper names
  "stays at max power when frame-capped/CPU-bound" as a behavior.
  https://skatterbencher.com/nvidia-gpu-boost-performance-limiters/
  https://www.xda-developers.com/gpu-boost-behavior-creates-more-problems-than-it-solves/
- **Efficiency curves are a press staple**: RTX 4090 at half TDP loses ~8%
  (videocardz/tomshardware); granular: 80% PL → 99.1% perf, 70% → 97.8%,
  60% → 93.9%. Peak efficiency ~75-80% PL (der8auer-style consensus).
  Matches this project's 70%-cap direction and the user's own observation.
- **Datacenter/HPC: mature, tooled, production practice**: NERSC runs power
  capping via Slurm (https://docs.nersc.gov/jobs/power-capping/), NVIDIA ships
  official DGX capping guides, papers report ~19-26% energy saved for <4% perf
  loss via DVFS (https://arxiv.org/pdf/2402.18593).

## Vendor mitigations — ALL opt-in, none CPU-bound-aware

| what | scope | default |
|---|---|---|
| AMD Radeon Chill (motion-based fps/clock scaling) | desktop | OFF |
| AMD Frame Rate Target Control | desktop | OFF |
| NVIDIA Whisper Mode / Battery Boost | laptops only | opt-in |
| NVIDIA Max Frame Rate cap | desktop | OFF |
| Intel Arc | nothing found; undervolting unsupported | — |

None auto-detect "CPU-bound, GPU boosted-for-nothing" and act.

## The genuine gap (our niche)

**No desktop/VR tool closes the loop with measured frame delivery as the control
signal.** Closest existing: PULSE/AutoTDP (https://github.com/keiretrogaming/pulse)
— a real closed-loop fps-at-minimum-power controller, but Android handhelds only.
GPUPowerAdjuster switches per-process caps by process NAME, not telemetry. VR
energy literature focuses on standalone-headset rendering (YORO, MobiSys'25),
not tethered-PC boost waste.

**Verdict**: the mechanism is well-known; the automated, measured, VR-specific
closing of the loop is not. This project's per-box `power.conf` + pacing-measured
capping (pacing percentile as the guard metric, not an fps target) is a credible
differentiator — worth writing up once the harness automates the sweep
(NEXT-STEP WS4 tooling queue).

## The boundary case, measured: capping is NOT free when the GPU is actually the bottleneck

T209's "105W==210W, free" result is specifically a **CPU/pacing-bound** finding —
Aircar's frame rate was gated by something other than GPU clock, so the GPU boosting
to its power limit was pure waste (the "heat without frames" this doc is named for).
2026-08-23 (T246 follow-up) measured the opposite case on purpose, as a control:
**Quake II RTX** (`timedemo 1`, demo `q2demo1`, 631 frames, full path-traced renderer)
is genuinely GPU-bound — 95% utilization, GPU clocked to its cap the whole run, no
CPU/pacing ceiling in the way. Same box, same demo, only the power limit changed
(watchdog held still via `systemctl stop vr-power-watchdog.service` for the duration,
so nothing else touched the cap mid-run):

| GPU power limit | frames | time | fps | vs. 175W |
|---|---|---|---|---|
| 175W (70% of 250W max — `power.conf`'s VR-tuned default) | 631 | 9.05 s | 69.73 | — |
| 100W (40% — the idle-`saver` floor, `vr-power-watchdog.py`) | 631 | 11.94 s | 52.84 | **-24.2%** |

This is exactly the shape the der8auer-style efficiency curve above predicts once
you're actually GPU-bound (own citation above: 80%→99.1%, 70%→97.8%, 60%→93.9% —
extrapolated further down to 40%, a real double-digit hit is expected, not
surprising). The point of measuring it here isn't the number itself, it's
**confirming the boundary of the "free" claim**: `power.conf`'s single flat
`GPU_LIMIT_PCT` was validated against VR pacing specifically (T204/T209) and is not
a universal "40-70% always costs nothing" result — it costs nothing exactly when
something else already caps delivered frames below what the lower wattage can still
supply, and costs real fps the moment a title actually saturates the card. The idle
`saver` floor (100W) is deliberately NOT "free" by this same logic — it's chosen for
minimum watts at rest, not for being consequence-free under load, which is why
`vr-power-watchdog.py` always switches to `--apply` before anything real runs rather
than leaving the machine at the saver floor.

**Opens the door for**: a workload-aware cap instead of one number for everything —
detect (or classify per-title, the way `docs/23`'s per-game profiles already do for
tracking/constellation settings) whether a title is pacing-bound (VR titles measured
so far) or GPU-bound (this Quake II RTX case, likely most flat/rasterized-heavy or
path-traced titles), and only apply the aggressive cap in the former case. Not built —
today `vr-power-watchdog.py`'s "performance" mode is one flat number
(`power.conf`'s `GPU_LIMIT_PCT`) for every kind of active workload, VR or flat.
