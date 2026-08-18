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
