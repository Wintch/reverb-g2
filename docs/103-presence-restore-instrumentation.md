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

## 2026-09-06 ~11:17-11:27 -03 — live wearer test: hypothesis (a) CONFIRMED, companion channel dead

Deployed exactly per this doc's §4 recipe (`WMR_USER_PRESENCE=1 WMR_USER_PRESENCE_SCREENOFF_MS=15000
WMR_PRESENCE_DIAG=1 ./jack-in-wayland.sh up`), plus `hello_xr` kept alive throughout
(`HELLO_XR_PHOTO360=` pointed at an arbitrary existing PNG since the default 360-photo path
doesn't exist on this box and the loader throws fatally without one) -- needed because
`update_inputs()` is only invoked from the IPC/oxr_session action-sync path, so without an active
OpenXR client the heartbeat this doc added never fires at all (a real gap in the recipe above,
worth noting for next time: always pair `WMR_PRESENCE_DIAG=1` with a live client).

**One raw packet arrived passively at launch** (`PRESENCE-DIAG raw packet #1: proximity=0 ipd=743`).
**Zero more arrived after that, ever, for the rest of the session** -- confirmed across two
separate observation windows (an initial ~1 minute, then a second, user-confirmed real
don-then-doff-then-re-don cycle performed inside a precisely bounded ~60s window). Through the
whole thing, `update_inputs calls` climbed steadily at ~90/s (4098 -> 9156 in 56s, later 15477 ->
20897 in another 60s) -- direct proof the polling/logging path itself works perfectly and would
have shown a new `raw_packets` count immediately if the device had sent anything. `raw_proximity`
stayed frozen at its single startup value (`0`) the entire time; `screen_off_by_presence` flipped
1 partway through purely from the elapsed-time SCREENOFF timer, independent of any real sensor
reading (expected -- that timer doesn't need proximity data to fire).

**Refinement, checked directly in `wmr_hmd.c` before over-claiming**: this proximity/IPD message
is explicitly **change-driven by design** (`wmr_hmd.c:1046`'s own comment: "This message is
CHANGE-driven"), not a continuous stream -- so "stuck at 1 packet" is not automatically anomalous
on its own; a device that never changes state would legitimately never resend it. What makes this
a real, confirmed failure is that the test spanned a **genuine, deliberate don -> doff -> re-don**
(at minimum 2 real proximity transitions, not-worn->worn and worn->not-worn, inside the monitored
window) and **none of them produced a new packet**. That rules out (a)'s softer reading ("it's
just quiet because nothing changed") and confirms the harder one: **the channel is failing to
deliver change notifications on real transitions**, not a Linux-side logic bug or a stopped-
polling app (both directly ruled out by the climbing `update_inputs` counter, ~90/s throughout).

**This matches, and sharpens with real data, an existing suspicion already on record**
([[project_aircar_yaw_drift_investigation]]'s "sensor hole" note: "1 don in 11 gave no PRESENT
edge") -- today's test got 0-for-(at least 2) transitions in one deliberate trial, consistent
with (not proof of a worse rate than, n=1) that same known-flaky edge-detection, reproduced
cleanly with proper instrumentation this time instead of anecdotally.

**A fix path already exists in the codebase, just not generalized**: `wmr_hmd.c` around line
1046-1063 already has a **feature-read-based re-sync** for the proximity/IPD value, currently
wired to fire only after a detected companion-device *reconnect*
(`WMR_COMPANION_RECONNECT_RESYNC`). Since the passive change-driven push is now confirmed
unreliable across a real transition (not just theoretically fragile), generalizing that existing
feature-read into a small periodic poll (e.g. every few seconds, or specifically while
`screen_off_by_presence` is held) is the right next step, not just one of several options --
exactly what this doc's own §4 already proposed as fix (a). Confirmed via source read, not yet
implemented or tested this session.

**Re-tested on a completely fresh `down`+`up` restart, same result**: a brand-new session (no
wearer action this time, purely passive) again got exactly one startup packet
(`proximity=0 ipd=743`, `raw_packets` frozen at 1) and zero more over the next ~20s of continuous
`update_inputs` polling. Consistent across two independent session starts -- this looks like a
standing condition on this unit right now (the passive startup read still works every time; it's
specifically the *change-driven update* that never fires), not a one-off fluke of the first test.

**`PRESENCE_ENABLE` stays `0` in `~/vr/presence.conf`**, unchanged -- this finding does not
change that decision, if anything it reinforces it: the channel needs to reliably deliver
packets before RESTORE can ever work, regardless of any software fix on the Linux side.

**Hardware validated healthy, same session, right after**: `./scripts/panel.py activate` (no sudo needed) reported "full activation + screen on" with real HID reads (device IDs 0x09/0x08/0x06), and the wearer directly confirmed the HP boot logo actually lit up on the headset. This rules out a connection/USB-fault explanation for not having seen anything during the don/doff test above -- consistent instead with what the log already showed independently: `panel blanked by auto-standby (15000 ms NOT WORN)` fired before the physical test began, and no `panel restored` line ever appeared. Not seeing the panel light up on re-don is therefore the bug itself (RESTORE not firing), not a hardware symptom -- the headset genuinely works, confirmed live.

**Final confirmation, same session**: relaunched a plain session (no diagnostics, just `up`, 3dof) after the panel.py logo check, and the wearer directly confirmed the backlight/panel shows real image while worn. Hardware and DRM/video path are both genuinely healthy right now -- this closes out any doubt about the earlier don/doff test's validity raised mid-session; the companion-channel finding above stands as a real, hardware-independent, software/protocol-level bug.

## 2026-09-06 ~11:40-11:52 -03 — third, cleanest confirmation, with precise button-press timestamps

Built a fast feedback loop for this: `~/vr/joy-marker.py` logs a wall-clock timestamp to
`~/vr/joy-markers.log` on every Xbox 360 pad button press (`/dev/input/js0`), read via the raw
`js_event` struct (no extra dependencies -- `python3-evdev` isn't installed on this box). Protocol:
press a button right before donning, press again right before doffing -- gives exact,
low-friction timestamps to correlate against `jack-in-wayland.log` instead of relying on
imprecise chat-message timing.

**First two attempts this round were invalidated by test-harness bugs, not new hardware
findings** (both caught and corrected before drawing conclusions):
1. The first `hello_xr` keepalive (`sleep 180 |`) expired mid-conversation before the wearer
   actually did the marked don/doff -- `update_inputs` had already stopped being called
   entirely by the time the real test happened, so nothing could have been logged either way.
   Fixed by using `sleep 1800` (30 min) keepalives going forward.
2. `hello_xr` then hung 3 times in a row at the exact same point (right after `vkCreateDevice`,
   before ever reaching a synced session) against the same long-lived `monado-service` instance
   (alive ~17 min, survived several prior `hello_xr` connects and `pkill -9` disconnects).
   Resolved by a full `jack-in-wayland.sh down` + fresh `up` -- the stale, long-lived
   `monado-service` process, not a wearer/hardware issue, was the cause. Worth remembering:
   don't keep reusing one `monado-service` instance across many hello_xr connect/kill cycles in a
   single session; restart it if a fresh client ever hangs at device-creation.

**The actual test, once the harness was solid**: fresh `monado-service` + fresh `hello_xr`,
confirmed both alive and `update_inputs` heartbeat climbing steadily. Session had already
auto-blanked (`screen_off_by_presence=1`, `raw_packets` frozen at 1 since launch, nobody had
touched it) by the time the wearer was ready. Button-marked cycle: **A pressed 11:52:31.080 ->
[donned] -> A pressed 11:52:42.712 -> [doffed]**, an 11.6s real wear cycle. **Zero new raw
packets across the entire window** (`raw_packets` still exactly 1, `heartbeat calls` climbed
from ~7875 to ~8236 in the meantime -- update_inputs was unquestionably running the whole time).

**This is the third independent reproduction of the same result** (the first don/doff test
~11:24-11:27, the fresh-restart passive check right after, and now this precisely-timestamped
one) -- consistent, not a fluke. Combined with the earlier finding that the *same* channel
correctly reported 5 consecutive real transitions in a row when tested right after a fresh
launch (before any blank had occurred, see the 2026-09-06 ~11:33-11:39 entry above), the
characterization is now solid: **the proximity/IPD companion message works normally for ordinary
transitions, but specifically fails to fire a fresh "worn" report once the session has already
auto-blanked (`screen_off_by_presence=1`) and stayed in that state.** This is precisely the
condition RESTORE needs to work, and precisely the condition where the channel goes silent --
directly explaining why RESTORE has never once been observed firing, across every prior attempt
in `docs/98`/`docs/101` and this one.

**Hardware ruled out as the cause, twice over**: `panel.py activate` (no sudo needed) reported
real HID reads and the wearer confirmed the HP logo actually lit; a plain, non-diagnostic
Monado session afterward showed real backlight/image while worn. Both confirm this is a
software/firmware-protocol bug in the change-driven proximity path specifically, not a marginal
USB/cable connection (which would show up in USB enumeration or `panel.py`'s HID reads, and
didn't).

**Practical next step, per the fix already scoped above**: generalize the existing
reconnect-triggered feature-read resync (`wmr_hmd.c` ~1046-1063) into a periodic poll, gated
specifically on `screen_off_by_presence` being true (exactly the state where the passive
push channel is now confirmed dead) -- rather than a blind fixed-interval poll everywhere,
which would cost more without addressing a state where the passive channel still works fine.
Not implemented this session; `PRESENCE_ENABLE` stays `0`.
