# Windows vs. Monado clock model — cross-reference (2026-08-17)

Follow-up to `01-ghidra-firstpass.md` ("HUP↔QPC" section). That pass
identified the shape of Windows' HUP↔QPC conversion; this pass pins the exact
constants/formulas and cross-references against Monado's `wmr_source.c` to
explain the position "pops" (Vector D, see `project_g2_controller_6dof`).

Source: `MRSensorFusion.dll` decompiled (`HatchetHupConvertTime*` family,
`~/Documents/wmr-ghidra/decompiled/MRSensorFusion.dll.all.c`, out-of-git/NDA).
Only behavior, formulas and named constants are recorded here — no raw
decompiled code blocks beyond a couple of one-line snippets already safe to
quote.

## 1. Windows clock model — pinned

### The CFG-guarded indirect call resolves to `QueryPerformanceFrequency`

`a CFG-guarded indirect call` is a generic Control-Flow-Guard
dispatch thunk used for ~150 different indirect calls throughout the DLL, so
it can't be resolved by itself. But in `MRSensorFusion.dll.all.c`:

- `an internal helper` (line 836) stores `QueryPerformanceFrequency`'s import
  thunk into the delay-load slot `a cached internal global`.
- `an internal helper` (line 849) stores `QueryPerformanceCounter`'s import thunk
  into `a cached internal global`.
- All four `HatchetHupConvertTime*` conversion functions call the same icall
  pattern *once*, lazily, cache the result in a function-local static, and
  compare it against a sentinel (`a cached internal global`) to decide whether to
  recompute. The call signature (`icall(&out_int64)`) matches
  `QueryPerformanceFrequency(LARGE_INTEGER*)` exactly, and two of the four
  functions (`SocQpcToHupNs`, `SocQpcToHupTicks`) call the *direct*,
  unambiguous `QueryPerformanceCounter()` right next to it in the same
  function body — confirming these functions are all in the
  `QueryPerformance*` family and the icall is the frequency counterpart.

So: **the icall is `QueryPerformanceFrequency`**, called exactly once ever
(cached forever after), never `QueryPerformanceCounter` (that one is a direct
import call).

### The constants

Ghidra's headless decompile doesn't surface the raw bit patterns for
`a cached internal global` / `a cached internal global` / `a cached internal global` (no memory dump was
exported), but their **role** is unambiguous from how each is used:

| Symbol | Role | Evidence |
|---|---|---|
| `a cached internal global` | **HUP tick frequency** (device ticks/sec) | `HupTicksToSocQpc`: `scale = qpc_freq / an internal global`. `SocQpcToHupTicks`: `scale = an internal global / qpc_freq`. Symmetric denominator/numerator role in both tick-domain conversions — it is *the* device tick rate. |
| `a cached internal global` | **Nanoseconds-per-second, i.e. `1e9`** | `HupNsToSocQpc`: `scale = qpc_freq / an internal global`, applied to a value already in `ns`. `SocQpcToHupNs` computes `qpc_freq / an internal global` too (see caveat below). Only a value of `1e9` makes both the Ns-domain formulas dimensionally consistent with the Ticks-domain formulas that use `a cached internal global`. |
| `a cached internal global` | **`2^63` cast-safety guard, not a live re-sync threshold** | Used *only* inside `SocQpcToHupNs`, applied to the `double` result right before the `(longlong)` cast: `if (threshold <= x && x - threshold < threshold) x_int += INT64_MIN`. This is the standard idiom for casting a `double` that may be `>= 2^63` to `int64_t` without hitting float→int UB — it fires on the *magnitude* of the converted value, not on elapsed time or a periodic epoch. It is unrelated to WMR's "clock re-sync" concept. |

One genuine decompiler artifact worth flagging honestly: in
`SocQpcToHupNs` (line 15622-15626), the cached-scale branch reads
```
an internal global = an internal global / 0.0;
```
with the QueryPerformanceFrequency icall called *without* an output-pointer
argument in the decompiled text — unlike the sibling three functions, which
all pass `&local_resN`. This is almost certainly a Ghidra register-tracking
miss (the `double` return value in `xmm0`/similar got lost, defaulting the
literal to `0.0`), not an actual division-by-zero in the shipped binary — by
symmetry with the other three cached-scale computations, the real formula is
`an internal global = an internal global / qpc_freq` (i.e. `1e9 / qpc_freq`), which is
exactly what the resulting formula table below assumes and what makes the
Ticks/Ns directions consistent with each other.

### The six `Hatchet*` time functions — exact formulas

```
HupTicksToSocQpc(hup_ticks):      qpc      = hup_ticks * (qpc_freq / hup_tick_freq)
HupNsToSocQpc(hup_ns):            qpc      = hup_ns    * (qpc_freq / 1e9)
                                   (delegates to HupTicksToSocQpc when the ns arg is NULL)
SocQpcToHupNs(qpc):               hup_ns   = qpc * (1e9 / qpc_freq), with the 2^63 cast guard
                                   (uses current QueryPerformanceCounter() if qpc arg is NULL)
SocQpcToHupTicks(qpc):            hup_ticks = qpc * (hup_tick_freq / qpc_freq)
                                   (uses current QueryPerformanceCounter() if qpc arg is NULL)
HatchetHupGetConvertTimeValidityPeriod(): returns (0xFFFFFFFF, 0xFFFFFFFF) — infinite validity
HatchetHupDeviceHandshake():       SetLastError(0); return 1;  — a no-op stub
```

Every scale factor is a `double` computed **once**, cached in a function-static,
and reused forever (gated by `if (cached == sentinel) recompute`). There is
**no additive offset term anywhere** in this family, and **no periodic
re-sync**: validity is reported as infinite, and the "handshake" that would
plausibly trigger one does nothing.

**Interpretation**: Windows treats HUP-device-ticks and host QPC as **the
same timebase**, differing by a pure, constant frequency ratio established
once at driver init and never revisited. There is no concept of "arrival
jitter correction" in this layer at all — that whole problem class doesn't
exist in the Windows model because HUP and QPC share the same physical clock
source (same SoC), so the ratio is exact and stable for the life of the
process.

## 2. Monado's clock model — as implemented today

File: `src/xrt/drivers/wmr/wmr_source.c`.

### `m_clock_offset_a2b` — pure offset, exponential smoothing, no skew term

`src/xrt/auxiliary/math/m_clock_tracking.h:39-58`:

```c
const time_duration_ns alpha = 1000 * (1.0 - 12.5 / freq);
time_duration_ns got_a2b = b - a;                       // THIS sample's raw, noisy offset
new_a2b = old_a2b == 0 ? got_a2b
                       : ((old_a2b - got_a2b) * alpha) / 1000 + got_a2b;
```

This is a single-pole IIR / EMA on the *offset* between clock A and clock B.
For `IMU_FREQ = 250` (`wmr_source.c:177`), `alpha = 1000*(1 - 12.5/250) =
950`, i.e. `new_a2b = 0.95*old_a2b + 0.05*got_a2b`. **Every single IMU
sample (250/sec, ~4 ms apart) nudges the offset 5% toward that sample's raw,
individually-measured `(now_mono - now_hw)` delta.** There is no frequency-
ratio/skew term at all — pure additive offset, re-estimated from every
sample's arrival time.

### `wmr_source.c:170-183` — where it's fed, and from what

```c
timepoint_ns now_hw   = s->timestamp_ns;               // device clock
timepoint_ns now_mono = (timepoint_ns)os_monotonic_get_ns(); // captured AT ARRIVAL
timepoint_ns ts = m_clock_offset_a2b(IMU_FREQ, now_hw, now_mono, &ws->hw2mono);
```

`now_mono` is stamped when the sample is *processed by Monado*, i.e. after
USB transfer time and OS scheduling delay — both of which jitter sample to
sample. That jitter goes directly into `got_a2b` and, at 5%/sample, directly
perturbs `ws->hw2mono`.

The file's own in-tree measurements (comments at `wmr_source.c:48-52` and
`198-220`, dated 2026-08-12) quantify this precisely: **281 backwards-time
events per session, p50 3.3 ms, p99 14.7 ms, max 17.3 ms** of jitter in the
converted timeline — large enough, at a 4 ms IMU sample period, to
occasionally invert sample order, which is why `IMU_JITTER_MAX_NS` /
`IMU_MIN_STEP_NS` flooring logic (`wmr_source.c:52,56,237-247`) had to be
added downstream just to keep the timeline monotonic.

`cam_hw2mono` (`wmr_source.c:115,129`) is a per-bundle *cache* of `hw2mono`
taken at camera-0 arrival and reused for cameras 1-3 and, per the
2026-08-11 fix (`wmr_source.c:101-106,153-168`), for the constellation
controller-tracking path too. It inherits all of `hw2mono`'s jitter — it
doesn't add any of its own.

**A documented, reverted attempt to fix this** (`wmr_source.c:182-193`):
swapping `m_clock_offset_a2b` for `m_clock_windowed_skew_tracker` (already
used successfully by the Rift driver, `rift_driver.c:1038` with a
2048-sample window, `rift_radio.c:383` with 64). Result: backwards-time
events dropped to zero, but static 60 s drift went from 0.7-1.0 m to 243 m
and 1002 m on two consecutive runs — reverted, "do not re-apply without
measuring drift, not just the drop counters."

Reading `m_clock_tracking.c:24-182` for what that tracker actually does
(despite the "skew" name, it does **not** fit a rate/slope — no frequency
term either): it tracks a ring-buffer window of raw `local-remote` offset
observations, takes the *minimum* observed value as the least-jittered
estimate, and damps it into `current_skew` via
`current_skew = (min + current_skew*(w-1)) / w`. One concrete, testable gap
found while reading it: on a >100 ms jump (`CLOCK_RESET_THRESHOLD`,
`m_clock_tracking.c:15,107-116`) the window is cleared and a 30 ms hold-off
begins (`CLOCK_RESET_HOLDOFF`), but `current_skew`/`have_skew_estimate` are
**not** reset or reseeded — `to_local()` keeps returning the *stale
pre-jump* offset through the hold-off. That's a plausible contributor to the
regression (a real 8.23 s device-clock restart was measured on this same
hardware, `wmr_source.c:200-201`), but it's a lead, not a confirmed
root-cause of the 243 m/1002 m numbers — flagging honestly rather than
asserting.

## 3. The cross-reference — why this produces position "pops"

**Decisive difference:** Windows uses a fixed frequency-ratio *scale* only,
computed once, infinite validity, zero additive-offset re-estimation.
Monado's `hw2mono` is a *pure additive offset*, re-estimated from a fresh,
individually-noisy arrival-time sample every ~4 ms, with no skew term.

These are not solving the same problem in different ways — Monado's model is
solving a strictly harder problem than Windows' is, because **on Linux the
premise is different and the harder problem is real**: `CLOCK_MONOTONIC` on
the host CPU and the WMR headset's internal oscillator are genuinely two
separate physical clocks (host SoC vs. sensor-hub MCU across USB), unlike
Windows' HUP/QPC pair which shares one SoC clock source. Some offset — and
in principle some skew, since two independent crystals drift relative to
each other over time — is unavoidable on Linux; "just copy Windows and stop
tracking an offset" is not a valid fix, because the shared-clock assumption
that makes that valid on Windows does not hold here.

The bug is not "Monado estimates an offset it shouldn't." It's **how**
it estimates it:

1. **Update rate mismatch by ~4 orders of magnitude.** Windows never updates
   after init (effectively update rate → 0). Monado updates at 250 Hz, once
   per IMU sample, directly off that sample's own arrival jitter.
2. **The forcing signal is jitter, not a real offset change.** `got_a2b = b
   - a` conflates "true offset between the two clocks" with "USB transfer +
   scheduler latency for this one packet." The true offset changes on the
   order of clock-drift ppm over seconds; USB/scheduling latency changes by
   milliseconds sample to sample. At `alpha=0.95`, 5% of that latency noise
   leaks into `hw2mono` every single sample, so `hw2mono` itself becomes a
   noisy signal with the *sample-period-scale* variance measured (3-17 ms,
   comparable to the 4 ms IMU period itself).
3. **That noisy offset lands directly in position tracking.** `ts =
   m_clock_offset_a2b(...)` becomes `s->timestamp_ns` (`wmr_source.c:269`)
   and `xf->timestamp += ws->cam_hw2mono` for every camera and controller
   frame (`wmr_source.c:131,166`). Any consumer that differentiates
   timestamps (velocity/angular-rate integration, or SLAM's inter-frame
   `dt`) sees that noise as if it were real motion — a few ms of timestamp
   jitter at IMU rates translates into a non-trivial fraction of the true
   `dt`, which is exactly the kind of input that produces visible position
   "pops" downstream, distinct from and worse than ordinary sensor noise
   because it's *correlated* with USB/scheduler load rather than random.

So: the fix target is **stability of the fit**, not its existence. Windows'
lesson to take is "trust the estimate and stop re-deriving it from every
noisy sample," not "there is no offset."

## 4. Concrete, minimal fix recommendation

**Target**: `src/xrt/drivers/wmr/wmr_source.c:180`

```c
timepoint_ns ts = m_clock_offset_a2b(IMU_FREQ, now_hw, now_mono, &ws->hw2mono);
```

Recommended change, in order of surgical-ness:

1. **Decouple the offset update rate from the IMU sample rate.** Keep
   `m_clock_offset_a2b`'s proven EMA structure (it isn't the bug — the input
   cadence is), but stop feeding it every sample's raw, individually-noisy
   `(now_hw, now_mono)` pair. Instead, pre-filter over a short window (e.g.
   64 samples ≈ 256 ms at 250 Hz, matching the scale the Rift controller
   radio already uses for its own windowed tracker at `rift_radio.c:383`):
   track `min(now_mono - now_hw)` over the window (the least-latency sample
   is the best single-sample offset estimate, same principle the reverted
   `m_clock_windowed_skew_tracker` used), and call
   `m_clock_offset_a2b(freq_eff, a_min, b_min, &ws->hw2mono)` only once per
   window, with `freq_eff` scaled down accordingly (e.g. `IMU_FREQ/64`) so
   the EMA's effective time-constant stays sane. This directly attacks the
   measured problem (5%-per-4ms leakage of USB/scheduling jitter) while
   keeping the exact code path that is already known-good, instead of
   re-adopting the windowed skew tracker that regressed drift.

2. **If re-attempting `m_clock_windowed_skew_tracker` instead**, fix the
   stale-offset-during-holdoff gap identified above first
   (`m_clock_tracking.c:107-124`: on a `CLOCK_RESET_THRESHOLD` jump,
   reseed `current_skew`/`current_local_anchor` from the triggering
   observation immediately rather than leaving the pre-jump value live for
   the 30 ms `CLOCK_RESET_HOLDOFF`), and size the window for a 250 Hz IMU
   stream comparably to the Rift HMD's use (`rift_driver.c:1038`, 2048
   samples ≈ 8 s at its IMU rate) rather than the controller-radio's 64
   samples — a window that's too short relative to the true clock-drift
   timescale would let a handful of favorably-timed-but-atypical minima
   dominate the fit, which matches the "wrong slope"-shaped regression this
   driver's own comment already hypothesized (even though, per §2 above,
   this tracker doesn't literally fit a slope — a too-short window has the
   same net effect: it commits early to a minimum that isn't representative).

3. **Either way, keep `IMU_JITTER_MAX_NS`/`IMU_MIN_STEP_NS` flooring**
   (`wmr_source.c:52,56,237-247`) as a downstream safety net — it's cheap
   insurance against the residual jitter any offset estimator will still
   have, and it already correctly distinguishes ordinary jitter (≤17.3 ms
   measured) from genuine device-clock discontinuities (8.23 s measured).
   It should shrink to near-zero triggers once the offset feeding it is
   stable, which is a good regression check for whichever fix above is tried.

No change is recommended to the Windows-inspired "drop the offset entirely,
use a fixed ratio" direction from `01-ghidra-firstpass.md`'s original hypothesis — that
hypothesis was written before this pass distinguished HUP/QPC's *shared*
clock source from CLOCK_MONOTONIC/device-oscillator's *separate* one. It
does not transfer here as stated; the fix is about update stability, not
model removal.
