# 103 -- Presence auto-standby RESTORE: state-machine cleared, instrumentation added, root cause still needs one more live doff/don (2026-09-05)

Follow-up to `docs/98` (RESTORE confirmed broken, live, twice) and `docs/101` (a different bug in
the same feature area, already fixed). This is a code-level investigation: the rig was mid-session
the whole time (another agent's DP/lease work, `monado-service` PID 191446 actively rendering at
90Hz throughout, `WMR_USER_PRESENCE=1`/`WMR_USER_PRESENCE_SCREENOFF_MS=0` already in its
environment for a docs/101 validation) so no live doff/don repro was attempted here -- static
analysis plus new instrumentation only, per the task's own fallback instruction.

## 1. The driver-side state machine is clean -- hypothesis (b) does not hold in `wmr_hmd.c`

Read `wmr_hmd_update_inputs()` in full (`~/vr/monado` `lab-full`, `src/xrt/drivers/wmr/wmr_hmd.c`).
There is no one-shot latch: `committed` is re-derived from `candidate`/the raw proximity byte on
*every* call, and `screen_off_by_presence` is unconditionally cleared the instant `committed` goes
back to `true` (the very first lines of the `if (wh->presence.committed)` branch). Nothing here
would block a future WORN commit from firing RESTORE, provided the raw proximity byte actually
flips back to nonzero and `wmr_hmd_update_inputs()` keeps getting called.

Traced the caller chain too: `xrt_device_update_inputs()` for `XRT_INPUT_GENERIC_HEAD_DETECT` is
only invoked from two places in `oxr_session.c` -- once at `xrBeginSession` (seeds the initial
value) and once inside `oxr_session_poll()` (called from `xrPollEvent`, `oxr_event.c:434`), which
diffs correctly against `sess->presence` and re-invokes the whole driver chain every call. As long
as the running app calls `xrPollEvent` regularly (standard OpenXR practice, and consistent with
docs/98's "steady ~90Hz pacer log" the whole session), this path was almost certainly running
throughout both historical tests. So "something upstream stopped calling us" is unlikely, though
not directly proven -- see instrumentation below.

## 2. Surviving hypothesis: the raw proximity/IPD channel goes quiet once BLANK fires

`wmr_hmd.c`'s own `wmr_hmd_companion_reconnect()` comments describe the companion HID device (the
same channel carrying screen-enable *and* the `WMR_CONTROL_MSG_IPD_VALUE` proximity/IPD packets)
as the least reliable link in the stack: it re-enumerates 0.9-4.6 times/minute on this cable
(T226), and critically, **post-reconnect proximity re-sync is deliberately OFF by default**
(`WMR_COMPANION_RECONNECT_RESYNC`, default 0, T244) because the device didn't answer a feature-report
poll within the USB timeout when that was tried -- the code's own comment: "presence stays on its
pre-outage value until the sensor next changes." In the live session that's running right now,
reconnects/companion-read-errors are at 0 for ~16 minutes, so a mid-outage coincidence isn't the
dominant explanation on this cable today, but it remains a real contributing mechanism worth
ruling out with real data.

A second, more direct candidate: this driver's WMR_USER_PRESENCE_SCREENOFF_MS design assumes
auto-RESTORE is "the same primitive as blank, reasonably likely to work" (the original driver
commit's own comment, quoted in docs/98) by analogy with Windows Mixed Reality Portal's idle timer
-- but that same comment also flags that this driver's auto-restore is deliberately *not* Windows'
manual-wake-button model. If HP's companion firmware only continues emitting proximity telemetry
while driving an active WMR session and simply stops reporting (or freezes the last value) once it
has accepted a screen-off command -- plausible, since Windows' own recovery path may not depend on
a live proximity feed while blanked -- that would produce exactly this symptom: BLANK's one-shot
command always succeeds (pure host->device write), but no further WORN-carrying packet is ever
pushed afterward, regardless of how correct the Linux-side state machine is.

Both mechanisms funnel into the same observable: the raw `WMR_CONTROL_MSG_IPD_VALUE` packet stream
stops (or stops changing) after BLANK. Distinguishing "channel dead" from "channel alive but stuck
at 0" from "driver-side stopped evaluating" is exactly what was missing, per docs/98's own ask.

## 3. What was built: `WMR_PRESENCE_DIAG` (commit `d51e67c9d`, `lab-full`)

`~/vr/monado`, `src/xrt/drivers/wmr/wmr_hmd.c` + `wmr_hmd.h`, gated behind a new
`WMR_PRESENCE_DIAG=1` debug flag (default off, zero behavior/cost change when unset):

- `control_ipd_value_decode()`: an **unconditional** per-packet log (`PRESENCE-DIAG raw packet
  #N: proximity=.. ipd=..`), distinct from the existing `changed`-gated `WMR_DEBUG` line -- a dead
  channel now shows up as this log simply stopping, rather than being indistinguishable from "the
  sensor calmly reporting the same thing."
- `wmr_hmd_update_inputs()`: a 2-second heartbeat (`PRESENCE-DIAG heartbeat: update_inputs
  calls=.. raw_packets=.. raw_proximity=.. candidate=.. committed=.. screen_off_by_presence=..
  last_packet_age_ms=..`). Comparing the two call counters across a doff/blank/don cycle tells the
  three hypotheses apart directly: if `update_inputs calls` keeps climbing but `raw_packets` stalls
  after BLANK, the companion channel died; if `raw_packets` keeps climbing with a nonzero
  `raw_proximity` on re-don but `committed` never flips, that is a genuine driver-logic bug (not
  found in today's static read, but instrumentation beats a second static read); if both counters
  stall, something upstream (the OpenXR app/state-tracker layer) stopped polling.

Built (`cmake --build . --target monado-service`) to confirm it compiles clean of new warnings --
did **not** restart the live `monado-service` (PID 191446, actively rendering, owned by a
concurrent DP/lease investigation) to avoid disrupting it. Not deployed live yet.

## 4. What a live wearer test still needs to do

`PRESENCE_ENABLE` stays `0` in `~/vr/presence.conf` (unchanged, per docs/98's own policy -- this is
not this doc's decision to make). When the rig is free and a real wearer is available:

```
WMR_USER_PRESENCE=1 WMR_USER_PRESENCE_SCREENOFF_MS=<short, e.g. 15000> WMR_PRESENCE_DIAG=1 \
    ./jack-in-wayland.sh up
```

1. Don, then doff and wait past the threshold. Confirm `panel blanked by auto-standby` still fires
   (baseline, already known-good).
2. Watch `PRESENCE-DIAG raw packet #N` in the log through the doff, the blank, and a real re-don.
   If the counter (or a changing `proximity=` value) stops advancing right at/after the blank and
   never resumes even once physically re-donned -- that confirms hypothesis (a), channel/firmware
   silence, and rules out a Linux-side logic bug definitively.
3. Cross-check the `PRESENCE-DIAG heartbeat` line's `update_inputs calls` counter is still climbing
   at ~90Hz-ish cadence the whole time (rules out the state-tracker/app having simply stopped
   polling).
4. Only after that data is in hand: decide whether the fix is (a) periodic proximity re-poll while
   blanked (there's precedent -- the existing, currently-disabled
   `WMR_COMPANION_RECONNECT_RESYNC` feature-report read path, which could be generalized into a
   periodic poll instead of only firing after a detected reconnect), or (b) something else the log
   reveals. `PRESENCE_ENABLE` goes back to `1` only after RESTORE is proven live, not before.
