# 109 — Fake pacer phase-jump storm: root cause found and fixed (2026-09-07)

Follow-up to a diagnosis-only session earlier tonight. That phase read the whole
`u_pacing_compositor_fake.c` state machine, instrumented it temporarily, and reproduced only a
mild, connect-time-only version of the bug (125 jumps / ~9084 frames, quiet afterwards) — a real,
unexplained gap against the wearer's report of near-constant spam (10152 jumps) for a whole 100-120s
session. This phase closes that gap: reproduced the full-severity storm headlessly, found the
mechanism, fixed it, and confirmed the fix removes it, with real before/after numbers on this rig.

## 1. Original symptom

Live wearer sessions on `iashur` logged thousands of `WARN [predict_next_frame_present_time] Fake
pacer fell behind: jumped N period(s) forward` lines per session — one wearer session hit 10152 —
and the wearer reported it "felt like 60Hz" despite the display running a genuine 90Hz cadence.

## 2. What the diagnosis phase established

Full call-graph read of `u_pacing_compositor_fake.c` (Monado's fallback pacer, used because
`VK_GOOGLE_display_timing` is unavailable on NVIDIA Linux). One anchor, `last_present_time_ns`, is
written from two places:

- `pc_info()` — fed by `VK_KHR_present_wait` completion times, **guarded**: only accepts a newer
  timestamp than what's already there.
- `pc_update_vblank_from_display_control()` — fed by a background "VBlank Events" thread via
  `VK_EXT_display_control`, **unconditional overwrite**, no guard at all.

`predict_next_frame_present_time()` is stateless per call: `predicted = last_present_time_ns +
period`; if `now + comp_time` has already passed that, it jumps forward however many whole periods
are needed to catch up, and logs the WARN every single time it does. Whether the anchor is fresh or
stale when that runs is the entire story.

Also established: `XRT_COMPOSITOR_USE_PRESENT_WAIT` defaults **off**, and nothing in
`jack-in-wayland.sh` sets it — so `pc_info()`'s better-guarded feedback path is dead code on this
rig even though the driver supports it (`present_wait: 1` in the log). The vblank-thread path is
the only thing keeping the anchor alive in practice.

The diagnosis phase's own headless repro (idle client, ~100s) only produced a connect-time burst
(125 jumps in the first 1-2s, quiet for the remaining ~100s) and could not explain the wearer's
near-constant severity. It correctly declined to guess at a fix without more evidence and
recommended, in order: re-test with a heavier repro, enable present-wait, harden the unconditional
overwrite, throttle the WARN, and only clamp the catch-up logic itself if evidence justified it.

## 3. What actually reproduced the full-severity storm

The diagnosis phase's repro used an idle/synthetic client. This phase used the **real** launch
path instead: `up 1 3dof` + Aircar launched via Steam/Proton through `vr-launcher.py` (the same way
a wearer session starts), headless (no wearer, no controllers). That was enough on its own — no
instrumentation needed:

```
1820 WARN lines / 4641 total phase-jump periods in a ~2m43s session (unmodified code)
```

Critically, this wasn't a connect-time burst. Reading the raw log: once the real game's session
began, **every single `predict_next_frame_present_time()` call logged "jumped 1 period(s) forward"**
— back-to-back, no gaps, continuing unbroken all the way to teardown. That is the mechanism the
existing code comment already names: *"once this catch-up fires, the whole cadence shifts forward
by whole periods and NOTHING ever pulls it back."* Once behind by exactly one period, the pacer
just... stayed exactly one period behind, forever, logging every frame. This is the persistent,
whole-session pattern that matches the wearer's report — the earlier idle repro simply never
generated enough real load (Proton/shader-compile/GPU activity) to trigger it.

That comment, and the fact that `pc_info()` a few lines away already has a monotonic guard while
`pc_update_vblank_from_display_control()` doesn't, pointed straight at the vblank thread as the
likely source of the un-recoverable drift: if a stale or out-of-order vblank timestamp ever
overwrites the anchor *backwards*, the anchor can get stuck re-triggering the catch-up path
indefinitely, with nothing to self-correct it.

## 4. The fix

Both changes are in `src/xrt/auxiliary/util/u_pacing_compositor_fake.c` only (Monado repo,
`lab-full` branch, commit `63b71c926`):

1. **Guard `pc_update_vblank_from_display_control()`** the same way `pc_info()` already guards its
   own write: only accept `last_vblank_ns` if it's newer than the current anchor. One `if`, mirrors
   existing style.
2. **Rate-limit the "Fake pacer fell behind" WARN** to once per second. The existing
   `phase_jump_count` field still tracks the exact per-session total regardless of how often the
   line prints, and the throttled line now also reports how many jumps happened since the last
   print, so no information is lost — just decluttered.

`predict_next_frame_present_time()`'s catch-up math itself is untouched — the diagnosis's
conditional recommendation to clamp it was explicitly gated on wearer-retest evidence this phase
doesn't have, so that idea stays open, not implemented.

`XRT_COMPOSITOR_USE_PRESENT_WAIT=1` (the diagnosis's other lead — an existing, already-merged,
better-guarded anchor source that's simply never turned on here) was deliberately **not** enabled.
It's a rig-wide compositor behavior change affecting every title, not a scoped fix, and the
diagnosis flagged it as needing a live-wearer re-test before adopting — this phase's brief was
headless validation only. Left as the top open follow-up (see §6).

## 5. Before/after validation (headless, iashur)

Same rig, same launch path (`up 1 3dof` then Aircar via `vr-launcher.py`), full teardown between
runs, full `cmake --build build` between runs (`git stash`/`stash pop` to isolate before vs. after
on the exact same binary otherwise). `tests_pacing` (Monado's own unit suite for this file) passes
unchanged both before and after: 1061 assertions, 2 test cases.

| | before (HEAD) | after (this fix) |
|---|---|---|
| session length | ~2m43s | ~6m00s (longer window, same rig) |
| WARN lines logged | **1820** | **6** |
| total phase-jump periods (`phase_jump_count`) | **4641** | 2741 |
| pattern | continuous, every predict() call, unbroken from shortly after connect to teardown | isolated: one real ~13.7s inter-session gap (a short-lived Steam helper client connecting and disconnecting almost immediately — a legitimate catch-up, not a bug), a ~2s connect-churn burst on the real game client (matches the diagnosis's own connect-time finding), then **2 isolated single-period jumps across the remaining ~5m40s of steady-state rendering** |

The number that matters most isn't the line count (that's expected to drop — it's rate-limited by
design now) — it's that the **continuous every-frame storm did not reproduce at all** with the fix
in place. Baseline's last handful of lines before I tore it down were still firing one warning per
frame; the fixed build settled into multi-minute stretches of complete silence.

This headless run cannot rule out every wearer-specific factor (real IMU/USB traffic under an
actual worn session was the diagnosis phase's own flagged gap, and this phase still didn't wear the
headset). But it reproduces the persistent, whole-session degradation pattern that the earlier
idle repro couldn't, at a magnitude (4641 periods / ~150s) much closer to the wearer's 10152/100-120s
report than the original 125/100s finding — and the fix removes that pattern in this reproduction.

## 6. Open items

- **Live-wearer re-test still recommended** before calling this fully closed — this phase closed
  the "can't reproduce the severity" gap but still didn't put the headset on anyone.
- **`XRT_COMPOSITOR_USE_PRESENT_WAIT=1`** remains unenabled by design (see §4) — a good candidate
  for a session that includes a wearer re-test, since it would remove the vblank-thread anchor path
  entirely rather than just hardening it.
- The one real inter-session gap seen in the after-run (~13.7s, a short-lived Steam helper client)
  is expected/correct behavior for a session-boundary catch-up, not a bug — noted here only so a
  future reader doesn't mistake it for a regression.

## 7. Rig state at end

`monado-service` / `AirCar` / `hello_xr` / `play360`: none running. Socket removed
(`/run/user/1000/monado_comp_ipc`). `~/vr/monado` on `lab-full`, working tree clean, fix committed
at `63b71c926`. No pushes made (neither `origin` nor `wintch`). `wmr_hmd.c`/`wmr_hmd.h`
(this session's unrelated presence-detection work) untouched.
