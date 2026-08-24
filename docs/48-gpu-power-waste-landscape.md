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

## The saver floor doesn't reduce idle draw at all -- measured

Obvious-in-hindsight question, asked directly: how much does the machine actually draw
at idle, and is the `saver` 100W cap buying anything there? Measured with
`power-log.sh` (30s windows, GPU via `nvidia-smi`, CPU package via RAPL):

| state | GPU | CPU pkg | total |
|---|---|---|---|
| `saver` (100W cap) | 19.9 W | 25.0 W | **44.9 W** |
| uncapped (250W) | 19.8 W | 25.1 W | **44.9 W** |

**Identical.** A first pass measured `saver` at 67.6W total and looked like the cap was
somehow making idle WORSE -- re-measured immediately rather than reported, and it was
residual activity from the benchmark sweep still settling (the whole reason this
project's rule is remeasure when a number doesn't make physical sense, not rationalize
it). The real number matches the physics: at idle the GPU is already at its lowest
P-state (P8, minimal clocks) regardless of the configured ceiling, so a 100W vs. 250W
cap changes nothing when nothing is asking for more than a few watts anyway.

**So what is the `saver` floor actually for?** Not reducing idle watts -- it's
insurance against a SPIKE while the machine is supposed to be at rest (a stray
background process that starts using the GPU without a real session/game running would
otherwise be free to boost all the way to 250W). `vr-power-watchdog.py` still applies
it unconditionally at rest for that reason, just not because it saves power sitting
idle -- it doesn't.

## The actual curve, not just one point (`scripts/q2rtx-power-sweep.sh`)

Built a small reusable sweep script (same discipline as `scripts/gpu-load-sweep.sh`'s VR
side: multiple reps per level, CSV output) and ran 100/150/175/200 W × 2 reps on the same
`q2demo1` timedemo, watchdog held stopped for the duration:

| watts (% of 250W max) | rep 1 | rep 2 | mean | vs. 100W |
|---|---|---|---|---|
| 100 (40%) | 54.01 | 52.88 | **53.45** | — |
| 150 (60%) | 69.37 | 71.62 | **70.50** | +31.9% |
| 175 (70%) | 76.03 | 70.13 | **73.08** | +36.7% |
| 200 (80%) | 75.59 | 73.50 | **74.54** | +39.4% |

Raw data: `~/vr/logs/q2rtx-power-sweep-20260823-2258.csv`.

**The knee is around 150W (60%), not down at the saver floor.** The gain from 100→150W
is a real +31.9%; every step past that is diminishing returns (150→175W: +3.7%,
175→200W: +2.0%, both smaller than the ~5-9% rep-to-rep spread already visible in the
table — e.g. 175W's two reps alone span 70.13 to 76.03). That spread matches this
project's own documented per-window variance on this rig (3.44%/7.22%, `vr-power-
setup.sh`'s header) — two reps per level is enough to see the shape, not enough to trust
any single number to better than ~5%. This is the concrete version of the der8auer-style
efficiency curve cited above (peak efficiency well below 100% PL), just localized to
this exact card/title instead of a generic press number.

**Caught live while running this**: the sweep script must run as the normal desktop
user, not root/`sudo -i` — under root, `steam -applaunch` has no Wayland session to
launch into and `$HOME` silently becomes `/root`, so every rep just times out waiting
for a result that can never arrive (no error printed). `q2rtx-power-sweep.sh` now
refuses to start as root with a clear message instead of burning 8×60s finding out.

**Opens the door for**: a workload-aware cap instead of one number for everything —
detect (or classify per-title, the way `docs/23`'s per-game profiles already do for
tracking/constellation settings) whether a title is pacing-bound (VR titles measured
so far) or GPU-bound (this Quake II RTX case, likely most flat/rasterized-heavy or
path-traced titles), and only apply the aggressive cap in the former case. Not built —
today `vr-power-watchdog.py`'s "performance" mode is one flat number
(`power.conf`'s `GPU_LIMIT_PCT`) for every kind of active workload, VR or flat.
