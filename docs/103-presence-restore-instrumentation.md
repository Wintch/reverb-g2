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

## 2026-09-06 ~12:30 -03 -- CORRECTION to the "fix path already exists" claim above: it does NOT

Before implementing the periodic-repoll idea this doc proposed, read the actual code comment
around `wmr_hmd.c`'s reconnect-triggered resync (~line 1029-1040) directly -- it says the exact
opposite of what this doc assumed. **Patch 0090 (T244, 2026-08-21) already tried a feature-report
read of the proximity/IPD value and found it does NOT work**: the device simply does not answer
that query, and the attempt blocks for **1.4-5.0 seconds** (the usbhid control-transfer timeout)
**inside the shared run loop that also reads IMU and camera data** -- every attempt stalled the
IMU/camera streams long enough to relocate the wearer (a real, measured regression, which is why
the read is gated behind `WMR_COMPANION_RECONNECT_RESYNC=1`, off by default, described in the
code itself as "the lesser evil" to leave presence stale rather than pay that cost).

**This means the plan in the 2026-09-06 ~11:52 entry above ("generalize into a periodic poll
gated on screen_off_by_presence") is not viable as written** -- it would reintroduce exactly the
blocking-read regression 0090 already found and disabled, just gated on a different condition.
Not corrected by moving the poll to a less-frequent cadence either: the device not answering at
all means every attempt still pays the full multi-second timeout.

**Open question, not yet resolved**: whether ANY software-side proximity re-sync is possible
given the device appears to ignore on-demand queries entirely, not just rarely. Candidate
directions for next time, neither tried yet: (a) re-confirm this is still true today (T244 is 2+
weeks old) with a single, isolated, wearer-warned manual read rather than trusting old data
blindly; (b) investigate whether `screen_enable_func` (already called on companion reconnect to
restore the panel) has any side effect on getting the companion chip to resume its own
change-driven proximity reporting, which would make screen-reassertion the right trigger instead
of a raw feature-report poll; (c) sidestep the proximity channel's post-blank failure entirely by
using a DIFFERENT signal to gate a RESTORE *attempt* -- e.g. real IMU motion (already read
continuously, unaffected by this bug) as a proxy for "probably being picked up/worn again",
triggering a screen re-assert speculatively rather than waiting on a proximity edge that may
never come.

## 2026-09-06 ~12:25-12:35 -03 — a real, working fix found and A/B-confirmed: screen reassertion "wakes" the companion channel

The two untried candidate directions from the previous correction entry were narrowed down to
(b) first, since it needed zero code changes to test: does re-running `scripts/panel.py activate`
(the existing, independent, HID-level screen-enable command -- NOT the proven-broken
feature-report proximity read) while the panel is auto-standby-blanked have any effect on the
companion channel's willingness to report the next real WORN transition?

**Clean A/B result, 3 cycles total:**

1. `panel.py activate` while NOT WORN, still blanked -> **no new proximity packet by itself**
   (confirmed both times it was tried) -- this alone doesn't fake a WORN reading, it does
   something else.
2. Don immediately after -> **`panel restored from auto-standby` fires** (button-press-timed:
   12:29:47.432 -> 12:30:01.852, don committed cleanly). Doff afterward re-blanks correctly too.
3. **Control cycle, deliberately WITHOUT `panel.py activate`, same session, same blanked
   state**: don/doff (12:33:13.974 -> 12:33:26.002, 12s) -> **zero new packets**, RESTORE fails
   exactly as every prior test this session -- confirms the baseline failure is still live and
   the fix isn't a session-wide fluke.
4. `panel.py activate` again, then don again (12:34:25.144 -> 12:34:36.476) -> **`panel restored
   from auto-standby` fires again**, second clean reproduction.

**Net: 0/1 without the reassert, 2/2 with it, same session, same hardware, same blanked
precondition each time.** This is a real, reproducible, practical fix candidate -- and a
completely different, safer mechanism than the one already ruled out: `panel.py activate` sends
the companion's existing screen-enable command (the same one `wmr_hmd_activate_reverb` and the
reconnect-path already call, per the code read in the previous correction entry), NOT a
feature-report read of the proximity/IPD value -- so it should not carry patch 0090's measured
1.4-5.0s block-the-shared-run-loop cost. Each `panel.py activate` call in this test returned in
well under a second.

**Practical implication for a real fix**: instead of the broken idea (a periodic proximity
feature-read poll), the fix is likely a periodic (or blank-triggered) call to the *existing*
`screen_enable_func` while `screen_off_by_presence` is true -- something Monado's own driver
already has direct access to (it's the same function `wmr_hmd_activate_reverb` and the
reconnect-resync path call, `hmd_desc->screen_enable_func`), not an external script. Not yet
wired into the driver as an automated fix -- this session only proved the *mechanism* works via
the existing standalone `panel.py` tool, calling it manually each time. **Open question before
wiring this in for real**: does calling `screen_enable_func` while genuinely NOT WORN cause any
visible flash/backlight blip a real guest would notice (the wearer reported "HP on, backlight
off" after the first manual activate -- a brief logo flash, not a sustained backlight-on state,
which would be an acceptable tradeoff if confirmed consistent) -- worth a couple more observations
before deciding how often to call it (once right when blank fires vs. a genuine periodic timer).

## 2026-09-06 ~12:45-13:35 -03 — RESOLVED: automated fix implemented, root-caused through 3 layered bugs, live-validated

The previous entry's "practical implication" (wire `screen_enable_func` into the blank/restore
state machine) turned out to be the wrong level of the problem -- it took 5 consecutive failed
live automated attempts, each disproving a specific hypothesis, before the real fix was found.
Documented in full because every failed attempt narrowed the search in a genuinely useful way.

### Attempt 1 -- reassert in the RESTORE branch, gated on `committed`: dead code

First automated wiring called `hmd_desc->screen_enable_func` (later `reassert_func`) inside
`if (wh->presence.committed) { if (screen_off_by_presence) { ... } }` -- mirroring where the
existing (broken) restore logic already lived. **Live result: 0 new raw packets across 500+s of
`update_inputs` calls, including a real don/doff cycle.** Root cause, found by re-reading the
code before blaming the hardware again: `committed` can only ever become `true` from a *fresh*
companion packet -- and the whole bug is that no fresh packet arrives once blanked. The call was
provably unreachable in exactly the state it needed to fix.

### Attempt 2 -- one-shot reassert at the blank transition: decays over time

Moved the call to fire once, right when auto-standby blanks the panel (still NOT WORN). This
matches the manual recipe's shape (activate, then don shortly after) and initially looked
promising. **Live result: a real don ~100s after the one-shot reassert produced zero new
packets** -- same as no reassert at all. The manual successes had a short (single-digit-seconds)
gap between `activate` and donning; a 100s gap was not equivalent. The "wake" effect measurably
decays with time, so a single call can't be relied on to still be in effect whenever the wearer
actually returns.

### Attempt 3 -- periodic re-arm (shared handle, `wh->hid_control_dev`), ~15s interval

Fixed the decay problem by re-arming every `WMR_PRESENCE_REASSERT_INTERVAL_MS` (default 15000)
for as long as the panel stays blanked, confirmed firing repeatedly and on schedule. **Live
result: still 0 new packets** across a real don/doff, even after confirming (via reconstructed
timestamps) the donning gesture happened comfortably outside any reassert's own blocking window.
Ruled out "the wearer happened to don while a reassert was mid-flight and the shared HID
endpoint was too busy to also carry the real proximity report."

Also measured, independent of the above: each shared-handle reassert call blocked the shared
IMU/camera run loop for **~4-5 seconds** (vs. sub-second for the same handshake run standalone
via `scripts/panel.py`) -- almost certainly `wh->hid_lock` contention with that same thread's own
continuous IMU reads. Not the reason RESTORE still failed, but a real, separate cost worth fixing
regardless (a periodic ~30-40% duty-cycle stall on the shared thread, indefinitely, while idle).

### Attempt 4 -- fresh, independent hidraw fd instead of the shared handle

Hypothesis: `panel.py` succeeds as an independent process opening its own fd; maybe *reusing* an
already-open, continuously-read handle (rather than the fd itself) is what differs. Added
`wmr_hmd_reassert_reverb_fresh_fd()`: re-scans for the companion's hidraw path
(`companion_find_hidraw_path`, already used by the reconnect path) and opens a brand-new
`os_hid_device` for the handshake, closing it afterward -- no `wh->hid_lock` taken at all, since
a separate fd needs no serialization with the shared one. **Measured: ~368ms per call, matching
`panel.py`'s own timing almost exactly** -- confirms the ~4-5s cost above really was hid_lock
contention, now gone. **But live result was still 0 new packets** through a real don/doff cycle.
The fresh-fd hypothesis fixed a real performance problem but was not itself the missing
ingredient for RESTORE.

Two cheap non-wearer checks ruled out two more candidate explanations before spending a 6th
physical cycle: (a) enumerated all `hidraw*` nodes matching the companion's VID:PID live -- only
one exists, and both `panel.py`'s naive first-match and the driver's own ":1.0/" interface-
preferring `companion_find_hidraw_path()` resolve to the *same* node, so "wrong USB interface"
was not it; (b) ran `panel.py activate` manually and checked `journalctl -k` for the same window
-- **zero kernel USB events**, so `activate()` does not cause a real re-enumeration either (only
the separate `off` command is documented to do that, per `panel.py`'s own docstring).

### Root cause, found by diffing byte-for-byte against `panel.py`'s own printed output

Added temporary logging of every byte `wmr_hmd_reassert_reverb_fresh_fd()` actually read back
(not just the ioctl return code) and compared directly against `panel.py activate`'s own printed
hex dumps from an earlier manual run. The 0x50 loop responses and the 0x09/0x08/0x06
identification reads **matched byte-for-byte** -- real, correct, changing device data, not
garbage from a "successful-looking" but semantically empty ioctl. So the handshake and reads
were never the problem.

The difference was structural, not electrical: `panel.py activate()` sends the trailing
screen-on command (`HIDIOCSFEATURE({0x04, 0x01})`) on the **same** open file descriptor, right
after the identification reads, before closing it -- one atomic sequence, one connection. Every
automated attempt above closed the fresh/shared fd after the handshake and reads, and left the
screen-on send to the driver's *ordinary* `screen_enable_func`, called separately, on a
*different* handle (`wh->hid_control_dev`), at a *different* time (real RESTORE, which by
definition hadn't happened yet). Five attempts had all silently split one atomic sequence into
two, on two different connections, at two different times -- and never reproduced the effect
because of it.

### The fix

`wmr_hmd_reassert_reverb_fresh_fd()` (`src/xrt/drivers/wmr/wmr_hmd.c`) now replicates
`panel.py activate()` exactly, in order, on one fresh fd: 300ms sleep, 4x (0x50 send + 0x50 get +
10ms sleep), the three identification reads, **then the `{0x04, 0x01}` screen-on send**, then
close. Wired as the Reverb family's `reassert_func` (new optional function pointer on
`wmr_headset_descriptor`, NULL for Odyssey+). `wmr_hmd_update_inputs()` calls it once at the
blank transition and then periodically (`WMR_PRESENCE_REASSERT_INTERVAL_MS`, default 15s) for as
long as the panel stays blanked -- opt out with `WMR_PRESENCE_RESTORE_REASSERT=0`. Committed as
`c44ba4a23` on `lab-full` in the `monado` checkout.

**Known, accepted tradeoff**: every periodic re-arm briefly flashes the HP logo while blanked,
since the screen-on command is genuinely sent to the panel each time (confirmed live, both
manually and automatically, to be a brief flash rather than a sustained lit panel --
`wh->hmd_screen_enable`/`screen_off_by_presence` are untouched by the fresh fd and still say
"off", so nothing keeps compositing frames to it afterward). A guest at a booth idling near a
blanked headset would see this flash roughly every 15s. Not measured or tuned further this
session.

### Live validation

Manual treatment/control pairs (before any automated fix, confirming the underlying effect is
real and not a small-sample fluke): **3/3 success with `panel.py activate` immediately before
donning, 2/2 failure without it**, spread across two separate test sessions on either side of a
`monado-service` restart. Automated fix, after the byte-for-byte root cause was found and
corrected: **3 consecutive fully automatic `blank -> WORN -> restored from auto-standby ->
NOT WORN` cycles, zero manual intervention**, the last one against the final cleaned-up (no
diagnostic byte-dump logging) build. `raw_packets` incremented and `committed` correctly flipped
both directions every time; doffing after a restore re-blanks correctly on schedule too.

**Not done this session, left for later**: no measurement of how long the "wake" from one
reassert call actually lasts (the periodic 15s re-arm sidesteps needing to know this, at the
cost of the recurring logo-flash); no tuning of the flash-vs-freshness tradeoff via a longer or
adaptive interval; SCREENOFF_MS was left at its short 15000ms test value for this whole
investigation, not reset to whatever the real deployed default should be for the demo-day booth.

## 2026-09-06 ~13:40-13:52 -03 — enabled for real, validated through the actual deployed config path, plus an audible operator alert

Everything above was tested with `WMR_USER_PRESENCE`/`WMR_USER_PRESENCE_SCREENOFF_MS` set as
manual ambient env vars, not through `~/vr/presence.conf` the way a real `jack-in-wayland.sh`
launch actually works. Closed that gap:

- `~/vr/presence.conf`'s `PRESENCE_ENABLE` flipped `0` -> `1` (untracked, per-box file, not in
  this repo) now that both directions are live-validated. `PRESENCE_SCREENOFF_MS` left at its
  existing real value, `120000` (2 minutes) -- notably different from this whole investigation's
  15000ms test value, so a real blank takes a lot longer to arrive than every test above.
- New `scripts/presence-sound-alert.sh`: tails `jack-in-wayland.log`, speaks "casco apagado" /
  "casco encendido" (`espeak-ng -v es-419`) on the blank/restore log lines. Read-only, never
  launches or kills anything, survives a `monado-service` restart (`tail -F` re-opens the log
  by name through the truncation `jack-in-wayland.sh`'s own `>` redirect does on each launch).
  Requested so a booth operator gets audible confirmation without watching a screen.
- **Live-tested through the real path**: plain `jack-in-wayland.sh up 1 3dof` (no manual env
  overrides), confirmed via `/proc/<pid>/environ` that it correctly resolved
  `WMR_USER_PRESENCE=1` / `WMR_USER_PRESENCE_SCREENOFF_MS=120000` from `presence.conf`. Blank
  fired at the real 2-minute mark with "casco apagado" confirmed audible live by the wearer;
  donning immediately after produced `restored from auto-standby` with "casco encendido" also
  confirmed audible, button-press-timed via `joy-marker.py` (13:49:45 don -> 13:49:57 doff).

This closes the loop from "fixed and validated with test-only flags" to "the feature a real
booth session actually uses is enabled and makes noise a human can act on." Not done: no long
soak with the real 2-minute interval to see how the recurring HP-logo flash (see the driver
comment in `wmr_hmd_reassert_reverb_fresh_fd`) reads over an extended idle stretch; the sound
alert has no volume/mute control of its own beyond the machine's normal mixer.

## 2026-09-06 ~14:15-14:45 -03 — two more failed live rounds (neither user error), a real operational constraint found, and three new operator-alert states

### Round 1: zero alerts, ~11s don/doff -- root cause was `update_inputs` never running at all

A fresh live test (new `monado-service` launch, `PRESENCE_ENABLE=1` for real this time, not a
manual env override) produced no sound at all. `joy-markers.log` showed a don at 14:19:11.936 and
a doff at 14:19:22.528 -- only 11s apart, nowhere near the real 120000ms `PRESENCE_SCREENOFF_MS`,
so on its own that would just mean "too early to expect anything." But `jack-in-wayland.log`
showed something worse: **zero** `User presence: WORN`/`NOT WORN` commit lines anywhere in the
whole log, across nearly 7 minutes of elapsed real time after the doff.

Root cause, confirmed with `WMR_PRESENCE_DIAG=1` (an existing env var already wired into
`wmr_hmd_update_inputs()`, logging a `PRESENCE-DIAG heartbeat: update_inputs calls=N
raw_packets=N raw_proximity=X candidate=X committed=X screen_off_by_presence=X
last_packet_age_ms=N` line roughly every 2s): with `monado-service` up and no OpenXR client
connected, **that heartbeat never appears at all** -- `update_inputs()`, which contains the
entire presence/auto-standby state machine, is only invoked by the OpenXR runtime while some
client has an active session syncing frames. The moment `hello_xr` (launched via `play360.sh`)
connected, heartbeats started immediately (`calls=1` at `last_packet_age_ms=77019`, climbing at
roughly frame rate).

**This is a real, previously-undocumented operational constraint, not a bug in today's fix**:
auto-standby silently does nothing -- no blank, no restore, no log line, no sound -- for as long
as no VR app is actively running. A booth session always has a game running while a visitor is
between donnings, so this matches real usage, but it is exactly the kind of gap that reads as
"the feature stopped working" to a future debugging session that forgets it. **Flagging clearly:
if presence heartbeats/transitions ever go missing again, check for an active OpenXR client
before suspecting the driver.**

### Round 2: heartbeats started, then stopped -- test client exited before the real threshold

Relaunched with `play360.sh -p flat -t 60 -q <video>` to drive the client loop. Heartbeats
climbed (`calls=1085` -> `calls=5241` across the observed window) but then stopped appearing
entirely, well before 120s of NOT-WORN could accumulate: the 60s `-t` duration meant `hello_xr`
exited at 14:31:25, and while the compositor's own idle loop appears to keep `update_inputs`
ticking for some grace period after a client disconnects, it eventually goes fully idle too and
stops calling it. Fixed by relaunching `play360.sh -p flat -t 600 -q <video>` (10 minutes) to
comfortably outlast the real 2-minute window.

### Round 3: full real cycle, fully automatic, second independent confirmation

With a sustained `hello_xr` session, the cycle completed with zero manual intervention:
`User presence: panel blanked by auto-standby (120000 ms NOT WORN)` fired at the real 2-minute
mark, "casco apagado" was heard live, the user donned (button-press-timed via `joy-marker.py`,
14:39:05.730 -> 14:39:14.610), `User presence: panel restored from auto-standby` fired, and
"casco encendido" was heard live and confirmed. This is a second, independent live confirmation
of the real deployed path (the first is documented in the section above, earlier the same day),
this time specifically proving the fix also survives a fresh `monado-service` relaunch with a
different sustaining client.

### Three new operator-alert states, added to `presence-sound-alert.sh` / `jack-in-wayland.sh`

All three approved live by the user, implemented, `bash -n`-checked, and deployed to both the
git-tracked (`scripts/`) and runtime (`~/vr/`) copies.

1. **`MONADO_MARKER: up` / `MONADO_MARKER: down`** -- `jack-in-wayland.sh` now appends one of
   these two lines to `$LOG`: right after `rm -f "$FAIL_MARKER"` in the `up` success path, and in
   the `down` teardown path guarded by `[ -f "$LOG" ]` (down must never create or truncate the
   log, per its existing "left untouched" contract -- this only appends, and only if a log
   already exists). `presence-sound-alert.sh` speaks "monado arriba" / "monado abajo" on these.
   Directly motivated by Round 1 above: gives the operator a spoken confirmation that the runtime
   is genuinely up, distinct from "nothing happened because nothing is listening."

2. **Controller-missing nudge** -- keyed off the existing `WMR_WARN(wh, "Failed to request
   controller status from HMD")` line in `wmr_hmd.c` (fires once per launch attempt, at HMD
   creation). `presence-sound-alert.sh` speaks "encendé los joysticks y reiniciá monado" on it.
   **Design pivot worth recording**: the original plan (from an earlier design-proposal fork the
   same session) was a PRE-launch controller-presence gate in `jack-in-wayland.sh`, checking via
   `bluetoothctl` before calling `up`. Live investigation found `bluetoothctl devices` hangs
   indefinitely under a non-interactive SSH invocation with no output (`timeout 5`/`timeout 8`
   both had to kill it, repeatedly, even with stdin fully redirected from `/dev/null`) --
   `systemctl is-active bluetooth` reports the system Bluetooth service as `inactive` on this
   rig, and the WMR motion controllers evidently pair through the headset's own onboard radio,
   relayed to the host over USB (matching Monado's own "request controller status from **HMD**"
   wording), not through the host's Bluetooth stack at all. `bluetoothctl` was therefore never
   going to work for this check, hang or no hang. Pivoted to the simpler, already-flagged-as-
   acceptable-fallback shape: a post-launch nudge off Monado's own ground-truth log line, exactly
   matching what the user originally asked for ("asi podes proceder a reiniciar monado para que
   lo tome").

3. **Game-name-on-connect** -- `presence-sound-alert.sh` now parses every
   `application_name: '...'` line Monado logs on client connect
   (`ipc_handle_instance_describe_client`) and speaks a short normalized name instead of a raw
   string. Real values grep-confirmed from historical `~/vr/*.log` files (not all live-tested
   this session): `libmonado` (`jack-in-wayland.sh`'s own post-launch validation probe), `steam`
   and `wineopenxr test instance` (wrapper/handshake noise -- several of these typically precede
   the real app per launch), `HelloXR` (this project's custom hello_xr build, doubling as
   `play360.sh`'s video player and as diagnostic tooling), `SUPERHOTVR`, and
   `AirCar/Binaries/Win64/AirCar-Win64-Shipping` (a raw Unreal binary path). Mapping: `HelloXR` ->
   "player", `SUPERHOTVR` -> "superhot", `AirCar*` -> "aircar", `OpenVRBenchmark` -> "benchmark"
   (grep-confirmed string, not live-tested this session), `libmonado`/`steam`/`wineopenxr test
   instance`/empty -> silent (deliberately not spoken -- these are per-launch noise, not the real
   session), anything else unrecognized -> "testing" fallback rather than reading a raw ugly
   binary path aloud. Extraction is plain bash parameter expansion (`${line#*\'}` /
   `${name%\'*}`), unit-tested in isolation before deploying.
   **Deliberately incomplete**: this mapping does NOT cover the rest of the project's confirmed
   VR library (Dreams of Dali, Night Cafe, I Expect You To Die, Hellblade, etc. from the earlier
   library-audit work) -- only names actually grep-confirmed in a real historical log got an
   entry. Add more only once each title's real `application_name` is confirmed live; don't guess
   ahead of that.

### Decision recorded: two other proposed states, deliberately NOT built

An earlier design-proposal fork the same session considered two more additions and recommended
against both -- recorded here so a future session doesn't re-run the same analysis:
- A distinct **"standby"** cue at the moment doffing is *detected* (before the 120s blank timer
  completes): likely noisy and redundant with "casco apagado" every time someone briefly takes
  the headset off mid-session. Skip unless a concrete use case shows up.
- A generic **OpenXR session on/off** alert keyed on `BEGIN_SESSION`/`END_SESSION`: those fire on
  every app launch/exit, including internal Steam/wrapper transitions -- far noisier than the
  once-per-launch-cycle Monado lifecycle marker above, and not what "estado de monado" actually
  meant (the launcher's lifecycle, not every app's).

## 2026-09-06 ~14:55-15:15 -03 — hardware-wear concern: sequence mapped, IMU idea evaluated and rejected, one more alert added, a dev-vs-booth timing question left open

The user raised a real, different concern from anything above: they own exactly ONE Reverb G2 (their
only test unit), and today's testing kept the panel lit through repeated deliberate doffs while
verifying the new alert states. They asked to map the sequence and reduce needless screen-on time,
and separately reopened an earlier-floated idea (IMU/movement-based detection, "casco en las
manos"/"casco puesto", instant reaction) under this new, concrete justification -- worth an honest
re-check, not a repeat of the earlier "low value" answer given before the hardware-wear stake was on
the table.

### The sequence, with real numbers pulled from `wmr_hmd.c` and today's own log

Constants (`WMR_USER_PRESENCE_DON_MS`/`DOFF_MS`, `DEBUG_GET_ONCE_NUM_OPTION` defaults, lines 142-143;
`~/vr/presence.conf`'s real deployed `PRESENCE_SCREENOFF_MS`):

```
DON_MS      = 250     (ms of continuous "worn" reading before commit)
DOFF_MS     = 1000    (ms of continuous "not worn" reading before commit)
SCREENOFF_MS= 120000  (ms of continuous committed NOT WORN before the panel physically blanks)
REASSERT_MS = 15000   (default re-arm interval while blanked, keeps RESTORE working)
```

Confirmed against real lines from today's `~/vr/jack-in-wayland.log`:
```
User presence: WORN     (raw proximity sensor value 1, held 255 ms)   -- matches DON_MS=250 + slop
User presence: NOT WORN (raw proximity sensor value 0, held 1011 ms)  -- matches DOFF_MS=1000 + slop
```

Timeline from a real doff to the panel physically going dark:
```
t=0        headset removed, raw proximity flips to 0
t=~1.0s    NOT WORN commits (DOFF_MS debounce) -- not_worn_since_ns starts here
t=~121.0s  panel physically blanks (SCREENOFF_MS grace period elapses)
```
And back on:
```
t=0        headset donned again, raw proximity flips to 1
t=~0.25s   WORN commits (DON_MS debounce) -- if blanked, screen_enable_func(true) fires immediately
```

**The number that matters: of the ~121 seconds a doffed, forgotten headset stays lit, ~120 of them
are the SCREENOFF_MS grace period, and ~1 is detection debounce.** Detection latency is roughly
0.8% of the total needless-on-time; the grace period is the other 99.2%.

### Verdict on IMU/movement detection: doesn't move the needle, don't build it

Re-examined against the ACTUAL stated goal (protect the one physical panel from needless on-time),
not just against "is it fast enough" as asked the first time. The proximity sensor already commits a
real doff in ~1 second -- a movement sensor could, at absolute best, shave a fraction of that single
second by reacting to the pick-up gesture instead of waiting for the proximity debounce. It cannot
touch the other 120 seconds at all, because that delay is a deliberate grace period, not a detection
limitation -- there's nothing left to detect faster once NOT WORN has already committed. Building an
IMU classifier (fragile: "moving while worn" and "moving while being carried/set down" look similar
in raw accelerometer variance, needing real tuning against live data to avoid false triggers) to
chase 1 second out of a 121-second problem is solving the wrong stage of the pipeline. **Verdict:
don't build it.** The actual lever is `SCREENOFF_MS` itself, and who gets to use which value when --
see below.

### Dev-vs-booth `SCREENOFF_MS`: a concrete proposal, left for a decision (values NOT changed)

`~/vr/presence.conf`'s real `PRESENCE_SCREENOFF_MS=120000` is production-shaped: a booth visitor
handing the headset to the next person, or briefly setting it down mid-demo, shouldn't force a cold
re-warm every time. But today's OWN testing pattern -- pick up, check something, set down, repeat,
many times in a session -- is exactly the pattern that 2-minute grace period is wrong for: every one
of today's brief checks kept the panel fully lit for up to 2 minutes afterward, on the only unit
there is.

The mechanism to run a different value already exists and needed no new code: `jack-in-wayland.sh`
gives an ambient `WMR_USER_PRESENCE_SCREENOFF_MS` env var precedence over `presence.conf` (this is
exactly how today's whole investigation ran its own tests, e.g. the `WMR_PRESENCE_DIAG=1` launches).
Proposed dev-checking value: **`WMR_USER_PRESENCE_SCREENOFF_MS=5000`** (5s) -- comfortably above the
1s DOFF_MS debounce floor (no risk of the blank fighting the debounce), and a **~95.8% reduction** in
needless lit-panel time versus the real 120000ms value for exactly this kind of repeated brief-check
session. A more conservative **10000ms (10s)** alternative is a **~91.7%** reduction and leaves a
little more margin before a "set it down to adjust something, pick it back up in a few seconds"
mid-test gesture triggers a blank/reassert-flash cycle. Left as an open choice, not applied --
`presence.conf`'s real value is untouched, and this is a call for the user to make (e.g. a habit of
exporting the var before casual `jack-in-wayland.sh up` sessions, or a documented convenience wrapper
later, if wanted).

### New alert added: "casco en la mesa" -- immediate doff feedback, ahead of the 120s countdown

Requested explicitly ("tiene que ser instantaneo... bien detallado con audio"): continuous state
awareness, not just the two endpoint events. Hooked on the SAME `User presence: NOT WORN` line shown
above (already logged today, zero driver changes) -- `presence-sound-alert.sh` now speaks "casco en
la mesa" the instant a doff commits (~1s after a real removal), well before "casco apagado" fires
~120s later. Deliberately NOT mirrored on the `WORN` commit line: that one also logs on every
ordinary redon that never blanked the panel at all (any doff-then-redon inside the SCREENOFF_MS
window), which would (a) double up with "casco encendido" in the one case that matters -- redonning
after a real blank -- while (b) adding noise to the far more common case of a quick check that never
came close to blanking.

Deployed to both `~/vr/presence-sound-alert.sh` and `~/Documents/reverb-g2/scripts/presence-sound-
alert.sh` (kept identical, `bash -n` clean), running process restarted to pick it up.
**Not live-audio-confirmed by a human this round** -- this was implemented and deployed without
physical access to the headset; the log-line hook is the same proven mechanism the other four states
already use, but "casco en la mesa" itself has not yet been heard and confirmed live.

## 2026-09-06 ~15:15-15:22 -03 — "casco en la mesa" live-confirmed; resting-alert delay becomes a per-user dashboard preset

The 30s `PRESENCE_RESTING_ALERT_DELAY_MS` test from the previous section (set via ambient env var)
**was subsequently live-confirmed** by the user: a fresh doff, ~30s wait, "casco en la mesa" heard
and confirmed ("si necesitas mi input por teclado, avisame... Sisi, escuche"). The earlier "not yet
heard" caveat is resolved.

### Per-user preset: `status-dashboard.py`'s user-center is a real per-operator-identity system

Investigated before building anything, per the user's ask ("agregalo al preset por persona"): this
dashboard already has a genuine per-user profile mechanism, not just a single shared config file
wearing a "per-user" label. `USER_PROFILES_FILE` (`~/vr/logs/user-profiles.json`) holds a dict of
named profiles (`height_m`, `dof`, `brightness`, `mapping`, `notes`, `lang`), one `"active"` pointer,
selectable via `/api/user/select` and edited via the user-center card's "Guardar usuario" button
(`/api/user/save`). This is a DIFFERENT mechanism from `presence.conf` (`PRESENCE_ENABLE`/
`PRESENCE_SCREENOFF_MS`), which is genuinely a single machine-wide file with no per-person concept at
all -- both exist side by side today, doing different jobs. The resting-alert delay is a personal
comfort preference (how much warning before "en la mesa"), so it belongs with `lang`/`brightness`/
`height_m` in the per-user profile, not bolted onto `presence.conf`.

**Built**: a new `resting_alert_delay_ms` field alongside the existing per-user fields.
- `DEFAULT_USERS` and the `load_users()` migration both default it to `0` (instant, matching
  today's original/safe behavior) -- existing saved profiles get it via `u.setdefault(...)`, same
  pattern already used for `lang`'s own migration.
- New `set_resting_alert_delay_ms()` (clamped `[0, 600000]` -- 600000ms/10min is the top preset
  offered) writes `~/vr/logs/presence-resting-alert-delay-ms`, a plain-text live file in the same
  spirit as `BRIGHTNESS_FILE`/`set_brightness_gain()`. Called from `/api/user/select` (switching
  active user applies their delay immediately) and from `/api/user/save` when the saved profile IS
  the active one (brightness gets this for free via its own live slider's `oninput`; this field has
  no such slider, so Save has to trigger it directly or it would silently do nothing until the next
  user-switch).
- User-center UI: a new `<select id="uc-resting-delay">` row (labelled via new `cc_resting_delay`
  i18n key, all three languages) offering **0 (instantáneo) / 1 min / 2 min / 3 min / 10 min** --
  the exact preset ladder requested ("puede ser minuto, dos, 3, 10"), plus the 0/instant option to
  keep the safe default reachable from the UI.
- `presence-sound-alert.sh` no longer treats the delay as a value read once at process start:
  `resting_alert_delay_ms()` now reads `RESTING_ALERT_DELAY_FILE` **fresh on every single doff commit**
  (ambient `PRESENCE_RESTING_ALERT_DELAY_MS` still overrides it first, for quick ad-hoc testing the
  way it was used before the dashboard preset existed). This means switching the active user's preset
  takes effect on the very next doff with **no script restart needed** -- notably better than
  `presence.conf`'s own `PRESENCE_ENABLE`/`SCREENOFF_MS`, which explicitly need a `jack-in down`+`up`
  because Monado caches its env var on first read.

**Verified, not just syntax-checked** (per this project's own standing lesson about PAGE-style string
templating -- a source-only check missed a live-breaking backslash-escape bug once already): restarted
`status-dashboard.service` (systemd --user), then `curl localhost:8765/` and confirmed the rendered
page actually contains the new `<select id="uc-resting-delay">`, and `curl localhost:8765/api/users`
confirmed both the `"default"` profile AND the real active profile (`AVGwmn`) carry the migrated
`"resting_alert_delay_ms": 0` field. `python3 -m py_compile` was run too, but treated as necessary, not
sufficient. `bash -n` on the shell script, plus an isolated unit test of the new
`resting_alert_delay_ms()` shell function against no-file / valid-file / corrupt-file / env-override
inputs, all before deploying live.

**Live value preserved across the restart on purpose**: the running `presence-sound-alert.sh` process
had `PRESENCE_RESTING_ALERT_DELAY_MS=30000` set as an ambient env var (today's just-confirmed live
test). Restarting it to pick up the new file-reading code would have silently dropped back to the
file's default (0) had the file been left empty -- instead, the real active user's profile was set to
`resting_alert_delay_ms: 30000` via the actual `/api/user/save` endpoint BEFORE restarting, so the
just-validated 30-second behavior carries over unchanged through the file-based path instead of
regressing. `presence-sound-alert.sh` was killed and relaunched clean; confirmed alive and watching
the log afterward.

Not done: no live doff was performed to prove the FILE path itself (as opposed to the env-var path)
actually drives a real "casco en la mesa" -- the underlying log-line hook is identical to what already
fired successfully minutes earlier, and the shell function was unit-tested in isolation, but a live
confirmation of the file-driven path specifically is still open for whenever the next physical test
happens.

## 2026-09-06 ~17:00-17:20 -03 — root-caused and fixed: presence evaluation was fully dormant with no OpenXR client connected

A live test cycle right after the per-user preset work above surfaced something worse than a missed
alert. The user donned the headset and reported "sin video, solo backlight" -- and directly disputed
an earlier status report of mine that the panel was blanked, from direct physical observation: "ahi
esta! el panel quedo prendido! como sabes que se apago?" That earlier report was wrong -- it was read
from a `PRESENCE-DIAG heartbeat` line that had already stopped updating, not a live re-check. Corrected
that mistake by re-verifying from fresh log state instead of defending the stale answer.

**Root cause, confirmed from the log timeline, not guessed**: `wmr_hmd_update_inputs()` -- which owned
the ENTIRE presence decision (debounce, commit, the `SCREENOFF_MS` countdown, blank, restore, the
periodic reassert) -- is only ever called by the OpenXR runtime while a client has an active
frame-synced session. The log showed a real doff commit, a real 120s-later blank (`panel blanked by
auto-standby`), and then *nothing* -- no further `WORN`/`NOT WORN` commit, no restore, even though the
user physically donned it afterward and `PRESENCE-DIAG raw packet` lines kept arriving (proximity data
was always live). The client (`hello_xr`) had already exited by then, so the whole decision layer went
dormant: a panel lit at that moment just stays lit indefinitely, with zero auto-protection, until a
manual `jack-in-wayland.sh down` (confirmed separately, live, to work correctly -- Monado's own SIGTERM
clean-path handler does screen-off the panel properly; that part was never broken). This defeats
auto-standby for exactly the case it exists to protect: casual dev checking, where a game usually isn't
continuously running.

**Fix**: moved the whole decision (now `wmr_hmd_presence_tick()`) out of `wmr_hmd_update_inputs()` and
into `wmr_run_thread()` -- the driver's own always-on, client-independent background thread that already
calls `control_read_packets()` (the very function that feeds `wh->proximity_sensor` in the first place)
every iteration, and already runs `wmr_hmd_send_controller_keepalives()` client-independently as
precedent for exactly this shape. `wmr_hmd_update_inputs()` now only reads the already-decided
`wh->presence.committed` and reports it to the XRT input system for `XR_EXT_user_presence` -- it
decides nothing anymore. A new `wh->presence_lock` mutex (same pattern as the existing
`controller_status_lock`) protects the fields the tick function owns, since they're now written by the
read thread and read by the OpenXR runtime thread. No debounce window, screenoff delay, or reassert
interval changed -- only *which thread, and whether a client is required* changed.

Full build (`cmake --build .`, all 42 targets, matching this project's own established lesson about
partial builds leaving `libopenxr_monado.so` stale) compiled clean -- two warnings, both pre-existing
and unrelated to this change (one in `control_read_packets`, a sign-compare; one an `int` overflow on
`30 * U_TIME_1S_IN_NS` that was already present verbatim in the code being moved, not introduced by
this patch). Left both alone, out of scope for this fix.

**Live-validated the actual failure mode, with zero OpenXR client connected at any point**:
`jack-in-wayland.sh up` with `WMR_PRESENCE_DIAG=1` and a 15s test `SCREENOFF_MS`, no app launched
afterward. `PRESENCE-DIAG heartbeat` now logs under `[wmr_hmd_presence_tick]` (not
`[wmr_hmd_update_inputs]`) and climbed continuously (`calls=4988 -> 5494 -> 6000` in a few seconds) with
zero clients ever connected (`pgrep hello_xr|play360` empty throughout), and `panel blanked by
auto-standby (15000 ms NOT WORN)` fired for real at the test threshold -- the exact scenario that
produced silence and a stuck-lit panel before this fix. Zero `run loop: ... blocked` warnings appeared
(the read thread's own stall watchdog, unaffected by the new mutex/tick cost). Separately smoke-tested
the still-client-gated path: a brief real `hello_xr` session connected and disconnected cleanly with no
errors, confirming `wmr_hmd_update_inputs()`'s slimmed-down read-only role still works when an app IS
present.

**Not verified** (same residual gap this whole investigation already flagged once today): the actual
physical backlight state was not re-confirmed by a wearer for this specific round -- no physical access
this session. Log/heartbeat state is the strongest evidence available and is now internally consistent
end to end (raw packets -> tick -> commit -> screenoff timer -> blank, all with zero client dependency),
but a live "does the panel actually go dark with nobody touching anything for 2+ minutes" check is the
natural next physical test whenever the user is available for one.

Committed on `~/vr/monado` (branch `lab-full`, NOT pushed -- personal-branch pushes go to the `wintch`
remote only, never `origin`, and this task didn't push at all): `wmr_hmd.h`, `wmr_hmd.c`.

## 2026-09-06 (later) -- multi-language alerts + a more natural TTS voice

User asked for two things: speak in whichever language the active operator has selected (not
hardcoded Spanish), and investigate a less robotic-sounding TTS engine than `espeak-ng`.

**Language**: reused the per-operator `lang` field already living in `status-dashboard.py`'s
`USER_PROFILES_FILE` (`~/vr/logs/user-profiles.json`, `{"active": "<name>", "users": {"<name>":
{..., "lang": "en"|"es"|"ru"}}}`) rather than inventing a second config surface -- `jq -r
'.users[.active].lang // "es"'` reads it fresh on every single alert (same "never cached, no
restart needed" philosophy as the resting-alert-delay file), falling back to `"es"` (this
project's long-standing default) if the file is missing, corrupt, or `jq` fails for any reason.
Unit-tested both failure cases directly. A small `state:lang -> phrase` table (`phrase_for()`)
covers every existing alert state in EN/ES/RU; proper-noun game names (superhot, aircar) are NOT
translated, only the generic labels (player/testing/benchmark) are. Russian phrases were written
carefully (correct grammatical gender/case on the short-form participles -- "шлем выключен" /
"шлем включён" / "шлем на столе", etc.) but have not been confirmed by a native ear or a live
speaker test -- flagging that honestly rather than claiming certainty neither a script author nor
this session's tooling can verify.

**TTS engine**: investigated Piper (rhasspy/piper, local neural TTS, ONNX-based) as the natural-
sounding candidate. Note: Debian's own `piper` apt package is an unrelated gaming-peripheral
config GUI, not this -- installed the real thing via `pip` inside a dedicated venv
(`~/vr/tts-venv`, required by Debian trixie's PEP 668 externally-managed-environment guard, no
`--break-system-packages` used). Pulled one "medium" quality voice model per language from
`huggingface.co/rhasspy/piper-voices` into `~/vr/tts-voices/` (en_US-lessac, es_ES-davefx,
ru_RU-irina; ~63MB each, ~181MB total, +197MB for the venv -- disk went 83% -> 84%, negligible
against 34G free). Measured synthesis latency for a short phrase: Piper ~0.9s wall-clock
(dominated by loading the ONNX model fresh each invocation -- no persistent Piper daemon exists
here, deliberately, to avoid a standing process on a shared lab machine) versus `espeak-ng`'s
~7ms. Verdict: **switched to Piper as the primary engine**, on the judgment that a genuinely more
natural voice is worth ~0.9s of lag for an ambient status narration nothing else is blocked on --
`say_state()` falls back to `espeak-ng` automatically if the venv/model for the needed language is
missing or Piper's own synthesis fails, so the alert system can never go silent outright.
`espeak-ng`'s own voice list has no clean Russian equivalent tested here, so the fallback path
maps `ru` to the existing `es-419` voice rather than guessing at an untested one -- acceptable
since that path only runs if Piper (which DOES have a real Russian voice) is already unavailable.

**Validated**: `phrase_for()`/`active_lang()` unit-tested in isolation (all three languages, plus
missing-file/corrupt-file fallback) by sourcing the script's functions without its tail loop.
Full `say_state()` chain smoke-tested end-to-end (jq lookup -> phrase -> Piper synthesis -> WAV ->
`paplay`) with exit code 0, and the `espeak-ng` fallback path separately exercised by pointing
`TTS_VENV_PIPER` at a nonexistent path. **Not validated**: nobody has actually heard any of this
live -- no physical access to the headset/speakers this round. Whether Piper's voices sound
genuinely better in practice, whether the Russian grammar reads naturally out loud, and whether
~0.9s of lag is noticeable/annoying in real use are all open until a live listen happens.

Committed on `~/Documents/reverb-g2` (branch `main`, NOT pushed): `scripts/presence-sound-alert.sh`.

## 2026-09-06 (later still) -- restore silently failed once after the presence_tick refactor; root-caused to the shared-handle send, fixed by reusing the fresh-fd reassert path

Right after validating the presence_tick threading fix (previous section) with a real player
running, one restore attempt logged `panel restored from auto-standby` -- `HID_SEND` returned
success, no WARN/ERROR anywhere near it -- but the wearer saw no backlight at all. Re-tested the
underlying HID command in isolation with `panel.py off` / `panel.py activate` (identical
`{0x04,0x00}`/`{0x04,0x01}` commands, run manually, no driver involved): `off` genuinely darkened
the panel, but a bare `activate` (full handshake, ending in the same screen-on send) *also*
sometimes failed to bring it back after being off for a stretch -- reproducing the exact shape of
bug this whole investigation started with.

Root cause: the restore branch in `wmr_hmd_presence_tick()` still called
`wh->hmd_desc->screen_enable_func(wh, true)` directly -- sending the screen-on command over the
**shared** `wh->hid_control_dev` handle. This is the exact handle this same investigation already
found unreliable earlier the same day (the ~4-5s `hid_lock`-contention bug, the reason
`wmr_hmd_reassert_reverb_fresh_fd()` exists at all) -- the periodic keep-alive while blanked was
already switched to a fresh fd, but the actual restore-on-don call was never moved off the old
shared-handle path, because until now it had appeared to work reliably across every earlier live
test. It isn't reliable; it had just not failed visibly yet in a small sample.

Fix: the restore branch now calls `wh->hmd_desc->reassert_func(wh)` -- the *same* proven fresh-fd
function already used for the periodic keep-alive -- instead of the bare `screen_enable_func`.
Falls back to `screen_enable_func` only if a family has no `reassert_func` (Odyssey+). No behavior
change for the blank path or for families without the Reverb's companion quirk.

**Live-validated**: full rebuild (same 2 pre-existing unrelated warnings as the presence_tick
commit, nothing new), fresh `jack-in-wayland.sh` launch, a genuine 120s auto-blank (not the
false-positive "panel already on from initial launch activation" case caught and explicitly ruled
out first), then donning: wearer confirmed real video content was already showing, not just a
backlight flash. This is the first fully clean, driver-fixed blank -> restore cycle with zero
manual intervention validated after both fixes landed.

Commit: `c6775c41a` on `~/vr/monado` branch `lab-full` (not pushed).

## 2026-09-06 (later still) -- voice gender selector, shared speak.sh, audio_guide_enabled toggle, and a new unconditional "casco puesto" alert

Four related additions to the presence-sound-alert stack, all live-reported asks in the same
conversation as the language/Piper work above.

**"Leftover Spanish" report, investigated, not reproduced.** The user reported still hearing
Spanish after switching their active profile to "niko" (lang: ru). Traced every path: `jq -r
'.users[.active].lang'` against the real file correctly returned `ru`; every alert state in
`phrase_for()` has a `ru` line; Piper's `ru_RU-irina-medium.onnx` synthesizes real Russian text
cleanly (`piper -m ru_RU-irina-medium.onnx`, exit 0, non-trivial WAV output, verified directly).
No code bug found. Most likely explanation: the report came from before (or right at the boundary
of) the profile switch, when "AVGwmn" (lang: es) was still active and correctly speaking Spanish --
not a bug in the language mechanism. Left as-is; flag if it recurs with a confirmed-post-switch
timestamp.

**Voice gender selector.** The single voice-per-language design (davefx/irina/lessac) meant gender
was accidental and inconsistent across languages -- the user noticed and asked for a selector.
Fetched three additional Piper voice models from `rhasspy/piper-voices` on Hugging Face into
`~/vr/tts-voices/`: `es_ES-sharvard-medium` (a multi-speaker model, M=0/F=1 per its own
`speaker_id_map` in the repo's `voices.json` -- used here only for speaker 1/female, since davefx
already covers male Spanish as its own dedicated model), `ru_RU-denis-medium` (male), and
`en_US-amy-medium` (female). New per-profile field `voice_gender` (male/female, default "male" --
matches what davefx/lessac already were; ru profiles get an explicit `voice_gender` at migration
time so an existing "irina" experience doesn't silently change). Explicit values set per the live
user's request: `niko` -> female, `AVGwmn` and `default` -> male. UI: a new M/F dropdown in the
dashboard's per-user edit panel, same pattern as the existing resting-delay dropdown (saved via
`userSave()`, not live-applied -- these three fields are read fresh from `user-profiles.json`
directly by `speak.sh` on every alert, same as `lang` already was, so no separate live-file/apply
step is needed the way `resting_alert_delay_ms` needed one).

**Shared `speak.sh`.** The live coordinating session had been calling `espeak-ng -v es-419 "..."`
directly over ssh all day for ad-hoc operator narration ("Atención, ponete el casco") --
hardcoded, ignoring whatever profile was actually active. Extracted ALL voice-selection logic
(`active_lang`, `active_voice_gender`, `audio_guide_enabled`, the Piper/espeak-ng fallback chain)
out of `presence-sound-alert.sh` into a new standalone `~/vr/speak.sh` (mirrored, as always, to
`~/Documents/reverb-g2/scripts/speak.sh`). Two calling conventions from the one file: executed
directly for ad-hoc use (`~/vr/speak.sh "phrase text"` -- the live session should use this from now
on instead of raw `espeak-ng` calls) or sourced as a library (`presence-sound-alert.sh` now does
`source "$VR/speak.sh"` and its `say_state()` just resolves `phrase_for(state, lang)` then calls
the shared `speak()`). One source of truth; `presence-sound-alert.sh` no longer duplicates any
TTS/voice logic at all. Note `speak.sh` does not translate -- it only picks which voice speaks; the
caller is responsible for composing the phrase in a language that matches the active profile.

**`audio_guide_enabled` toggle.** New per-profile boolean (default `true`), same migration/UI
pattern as `voice_gender`. `speak()` checks it first and returns immediately -- a genuine no-op,
no synthesis attempt at all -- when false for the active profile, rather than a muted-but-still-
running call. Set explicitly `true` for all three existing profiles per the user's request ("dejalo
activado para ambos") -- this is a toggle that exists for future use, nothing is currently silenced.

**New unconditional "casco puesto" alert.** The user pointed out a live asymmetry: "casco en la
mesa" fires on every doff, but nothing fired on a plain don unless it happened to follow a genuine
auto-standby blank (which speaks "casco encendido" instead). Added a new state, `worn`, fired on
every single `User presence: WORN` log line unconditionally (`en`: "headset on head", `es`: "casco
puesto", `ru`: "шлем надет"), through the same `phrase_for`/`say_state`/language/gender/toggle
machinery as everything else -- not a one-off. "casco encendido" is UNCHANGED and still fires
separately for the specific genuine-restore case; the two now coexist deliberately, answering
different questions ("did I just put it on, period" vs. "did that just wake the panel from a real
standby").

**Verified**: `bash -n` on both scripts, `python3 -m py_compile` on `status-dashboard.py` plus a
live curl of `/api/users` after a real `systemctl --user restart status-dashboard.service` (not
just the source compiling); `voice_model_spec()` resolves all 6 lang×gender combinations to the
right model file (multi-speaker `--speaker 1` included); `phrase_for(worn, *)` returns the right
text in all three languages; a `bash -x` trace of `speak.sh` confirms the full chain (the
`audio_guide_enabled` check, model resolution, the actual `piper` invocation, `paplay`) executes
for niko's now-female/ru profile; the `audio_guide_enabled=false` gate produces zero synthesis
attempts, confirmed by toggling it via the real API and back. **Not validated**: nobody has heard
any of this live yet -- no physical audio access this round, same caveat as the Piper work above.

Committed on `~/Documents/reverb-g2` (branch `main`, NOT pushed): `scripts/presence-sound-alert.sh`,
`scripts/speak.sh` (new), `scripts/status-dashboard.py`.

## 2026-09-06 ~18:15-18:40 -03 -- the "panel keeps relighting itself" report: root-caused to a debounce-design gap (single stray packet, not a HID/DRM problem), fixed, plus a software-only brightness-dim mitigation

Separate task, separate framing from everything above: the user reported the panel "always on,
always with video" despite every log line up to this point saying auto-standby was doing the right
thing. Explicitly code-analysis-only (no live hardware touch, no `monado-service` launch, no live
test) -- this rig is the operator's only physical unit and they asked to protect it while this got
thought through. Root cause and fix below were built and reasoned from `~/vr/jack-in-wayland.log`
(already captured, not reproduced live this round) plus a full read of `wmr_hmd_presence_tick()`.

### Root cause, confirmed independently against the raw log (not taken on faith)

Grepped `jack-in-wayland.log` for `PRESENCE-DIAG raw packet`, `User presence:`, `blanked by
auto-standby`, and `restored from auto-standby` rather than trusting the prior framing of this bug
at face value. Every one of the 4 blank->relight cycles in the captured session shows the identical
shape (line numbers from the log as fetched this session):

```
551: User presence: panel blanked by auto-standby (120000 ms NOT WORN)
569: PRESENCE-DIAG raw packet #2: proximity=0 ipd=750        <- companion still reporting NOT WORN
593: PRESENCE-DIAG raw packet #3: proximity=1 ipd=725        <- ONE packet flips to "worn"
594: User presence: WORN (raw proximity sensor value 1, held 253 ms)
596: User presence: panel restored from auto-standby
603: PRESENCE-DIAG raw packet #4: proximity=0 ipd=688        <- next packet already says NOT WORN again
604: User presence: NOT WORN (raw proximity sensor value 0, held 1001 ms)
```

The headset was resting untouched on the desk the entire time (confirmed by the task framing this
came from, and consistent with every WORN stretch lasting only as long as it takes the NEXT
irregular packet to arrive and flip the byte back). This pattern repeats exactly 4 times across the
whole log (blanks at lines 551, 685, 862, 968 in the fetched copy; each followed by a WORN commit off
a single packet, "held 253 ms" every time -- 253 ms above DON_MS=250 ms is the tick-scheduling slop,
not evidence of anything). In the second cycle (`packet #5` -> WORN -> `packet #6` -> NOT WORN,
lines 614-619), the very next packet after the one that triggered WORN already disagreed with it,
and it STILL arrived only ~1 s later, after WORN had already committed and already fired a real
restore -- i.e. even the "next" packet, when one came at all, was already too late to prevent the
false commit.

**Root cause**: `WMR_USER_PRESENCE_DON_MS`/`WMR_USER_PRESENCE_DOFF_MS` are wall-clock windows
measured against `candidate_since_ns` -- time since the raw candidate value last *changed* -- not a
count of how many times it has been independently *reported*. `wmr_hmd_presence_tick()` runs once
per iteration of the always-on read thread, gated on `WMR_USER_PRESENCE=1` (see `presence_enabled`
in `wmr_hmd.h`) but otherwise independent of any OpenXR client (that part was already fixed in the
"always evaluate" commit, `754beed30`, and is not the bug here). The companion's own
`WMR_CONTROL_MSG_IPD_VALUE` packet -- the only thing that ever writes `wh->proximity_sensor` --
arrives irregularly: 2 s to 100+ s apart in this log, measured directly off the `PRESENCE-DIAG raw
packet #N` sequence numbers and the heartbeat's own `last_packet_age_ms` field (e.g. line 549 shows
`last_packet_age_ms=102439`, 102 s since the previous packet, immediately before the first false
WORN commit). Meanwhile every tick in between two real packets just re-reads the same static,
unconfirmed byte. So a single stray/noisy packet flipping that byte to 1 satisfies the entire
`DON_MS` wall-clock window in a fraction of a second of REAL time, with zero corroborating evidence
that the reading is real -- and, worse for auto-standby specifically, this WORN commit doesn't just
look "invisible" the way the struct's own asymmetry comment assumes (a spurious resume used to only
matter to an OpenXR app's pause state) -- it actively undoes a real, working panel blank.

**Read-thread rate, corrected**: the task that prompted this investigation stated the tick rate as
"~750 Hz observed". Rather than repeat that figure into new code comments unverified, measured it
directly from this exact log: `PRESENCE-DIAG heartbeat` lines carry a `diag_update_inputs_calls`
counter incremented every tick, and fire on a fixed ~2 s interval independent of any packet. The
delta between consecutive heartbeats is essentially constant at ~506-508 calls (312 of 344 deltas in
the whole log are exactly 506), giving **~250 Hz**, not ~750 Hz -- about 3x off. This also lines up
exactly with something already documented elsewhere in this same file: `hololens_sensors_decode_packet()`'s
own comment already says "~250 Hz" for the IMU/sensor packet rate (`wmr_hmd.h` line ~178,
`IMU_FREQUENCY=1000` split into `IMU_SAMPLES_PER_PACKET=4`-sample packets = 250 packets/s), which is
almost certainly the dominant HID report driving the read thread's loop iteration rate. Doesn't
change the fix's validity at all (the mechanism -- one packet is not corroboration -- holds
regardless of whether the tick rate is 250 Hz or 750 Hz), but the code comments now cite the
measured number and how it was derived instead of repeating an unverified one.

**This is not the HID/DRM bug from earlier the same day.** The blank and restore HID commands
themselves work correctly and reliably (that was `c44ba4a23`/`754beed30`/`c6775c41a` and the
screen-off-fresh-fd commit below) -- every "panel blanked by auto-standby" / "panel restored from
auto-standby" pair in this log is a REAL blank followed by a REAL restore. The bug is entirely in
*when* a restore is triggered: a debounce that is time-based against a static last-known value,
never confirmation-based against independent samples.

### Housekeeping found along the way: an already-tested, uncommitted fix, committed as its own commit

Before touching anything, `git status` on `~/vr/monado` showed uncommitted changes to `wmr_hmd.c`/
`wmr_hmd.h` on top of `c6775c41a` (the restore-fresh-fd commit). Diffed it rather than assuming: it
adds `wmr_hmd_screen_off_reverb_fresh_fd()`, a mirror image of the existing
`wmr_hmd_reassert_reverb_fresh_fd()` -- sends the screen-off command over its own brand-new hidraw
fd instead of the shared `wh->hid_control_dev` handle, for the same reason restore was already moved
off that handle (proven unreliable, ~4-5 s `hid_lock` contention, sends that report success without
landing). Confirmed this is exactly the binary that produced the log analyzed above: every `Sent
screen-off (fresh fd)` line in the log (e.g. line 550) comes from this function. Complete,
self-consistent, already live-tested by virtue of having produced this exact log -- just never
committed. Committed it as its own focused commit (`d07872fd9`, "wmr: send auto-standby's screen-off
over a fresh fd too") BEFORE layering the debounce fix on top, so the two unrelated changes don't end
up conflated in one commit, matching this repo's own established one-fix-per-commit granularity (see
the `git log` for `wmr_hmd.c` this same day). Flagging this explicitly since it wasn't part of this
task's own scope -- it was sitting in the working tree, already proven, and leaving it uncommitted
indefinitely felt like the wrong outcome once found and understood.

### The fix: `WMR_USER_PRESENCE_DON_CONFIRM_PACKETS`

Commit `41626b6e2` on `lab-full`. Adds a packet-count confirmation requirement on top of (not
instead of) the existing wall-clock debounce, gated to the WORN direction only:

- Two new fields on the `presence` struct (`wmr_hmd.h`): `candidate_confirm_count` (how many
  independent packets have reported the current candidate value; reset to 1 whenever the raw
  candidate flips -- the flipping packet is confirmation #1) and
  `candidate_last_counted_update_ns` (the `presence.last_update_ns` value already counted, so a tick
  that finds no new packet since the last count does not double-count itself as evidence).
- "Independent" is detected via `presence.last_update_ns`, which `control_ipd_value_decode()`
  already updates on every decoded packet regardless of whether the value changed (its own existing
  comment: "Arrival time, not change time"). A tick only increments `candidate_confirm_count` when
  `last_update_ns` has advanced past what was last counted -- i.e. a genuinely new packet arrived,
  not just another ~250 Hz re-read of the same still-unconfirmed byte.
- The WORN commit condition now requires BOTH `held_ns >= DON_MS` (unchanged) AND
  `candidate_confirm_count >= WMR_USER_PRESENCE_DON_CONFIRM_PACKETS` (new, default 2,
  env-overridable, floored to 1 -- 1 reproduces the exact pre-fix, time-only behavior for anyone who
  wants it back).
- **Deliberately NOT applied to `WMR_USER_PRESENCE_DOFF_MS`** (leaving WORN). Checked the log
  specifically for this before deciding: every NOT WORN commit in the captured session is also a
  single packet (e.g. line 604, `held 1001 ms` off `packet #4` alone) -- but the log never contains a
  genuine WORN stretch at all (the headset was never actually touched in it), so there is no live
  evidence either way of a matching noise-flip-to-0-while-worn failure mode. The struct's own
  long-standing asymmetry reasoning ("entering worn is cheap to get wrong... leaving it is
  expensive") already argues for leaving that direction alone absent proof it needs the same
  treatment -- tighten it too if a live test ever shows a spurious doff mid-session.
- The commit log line now also prints the confirming-packet count, so a future live session can see
  directly how many packets a real don actually produces before commit, without needing a rebuild.

**Open trade-off, flagged for a human, not resolved here**: with `DON_CONFIRM_PACKETS=2` and packets
arriving as irregularly as this log shows (2 s to 100+ s apart), a REAL don could occasionally take
much longer than the old 250 ms to register if the second confirming packet happens to be slow to
arrive -- in the worst case, tens of seconds. This wasn't tunable against real donning-gesture data
this round (no live test), only against a resting-desk session. If a live test later shows real dons
routinely producing multiple packets within a second or two of an actual donning gesture (plausible
-- the sensor may sample faster while something is actually near it -- but not confirmed), 2 is
comfortably cheap; if real dons are just as sparse as this resting session's noise, 2 may need
retuning or a bounded fallback (e.g. "OR held_ns exceeds some much larger ceiling") added later.
Left as an open question rather than guessed at.

### Software-only mitigation: partial brightness dim on every doff/don, independent of the HID path

The user's own framing (translated): "raise it back on presence and lower it a bit as soon as it's
taken off -- the point is not to trigger heavy standby modes or waste cycles, just save what we
reasonably can; if it's not worn, nobody's there." Implemented as a cheap, near-instant,
purely-cosmetic rendering-side gain drop -- explicitly NOT a substitute for the real HID
blank/restore above, which remains the actual power-saving standby after the full `SCREENOFF_MS`
wait; this is a much faster, much cheaper, always-on companion to it.

**Where it hooks in, and why there, not the raw candidate.** Triggered off the SAME two log lines
`presence-sound-alert.sh` already tails for the "casco en la mesa"/"casco puesto" audible alerts:
`User presence: NOT WORN` (the debounced DOFF commit, ~1 s after a real doff) and `User presence:
WORN` (the debounced DON commit, ~250 ms after a real don, now additionally hardened by
`DON_CONFIRM_PACKETS` above). NOT triggered off the raw candidate -- doing that would expose the dim
to the exact same single-packet noise bug this task just fixed for the real standby path, just
relocated to a different symptom (a panel that visibly flickers dim/bright every time a stray packet
passes through, instead of one that silently relights). Reacting to the already-debounced,
already-packet-confirmed `committed` transition means this mitigation inherits the fix above for
free, with no separate hardening needed.

**Where it does NOT hook in: no C driver change.** Considered writing directly from
`wmr_hmd_presence_tick()` (the task's own suggestion pointed at `hololens_sensors_decode_packet()`'s
existing `~/vr/hmd-temperature.json` atomic tmp+rename write as the precedent to follow) but rejected
it after checking what `status-dashboard.py`'s brightness slider actually does: `BRIGHTNESS_FILE`
(`$HOME/vr/logs/xrizer-brightness`, polled ~every 30 frames by `xrizer`'s patched `compositor.rs`,
`patches/xrizer/0007-...`) holds the OPERATOR'S OWN chosen gain (`user-profiles.json`'s per-user
`brightness` field, 0-4x, `set_brightness_gain()` keeps both in sync). A C-driver write would have to
either hardcode a restore value (silently clobbering a custom brightness setting on every doff/don
cycle) or duplicate JSON-profile-reading logic in C for no real benefit -- the driver has no reason to
know about per-operator dashboard preferences. `presence-sound-alert.sh` already has exactly the jq
access needed (`speak.sh`'s `active_lang()`/`active_voice_gender()` are the established pattern) and
is already tailing the log line that should trigger this, live, with no new process. So the fix lives
entirely in `presence-sound-alert.sh`: two new functions, `active_brightness()` (reads
`.users[.active].brightness // 1.0` via jq, same fail-open-to-1.0 pattern as every other per-profile
reader in this script) and `dim_panel()`/`undim_panel()` (write `RESTING_DIM_FACTOR * baseline` /
`baseline` to `BRIGHTNESS_FILE`), called from the existing `NOT WORN`/`WORN` case arms.

**Dim factor**: `RESTING_DIM_FACTOR=0.35` -- a visible-but-not-jarring partial dim, not full black
(full black could read as a crash to anyone watching a spectator feed, and the user's own framing was
"lower it a bit", not "blank it" -- that's what the real HID path is for). Untuned against a live
wearer; revisit if it reads as too subtle or too dark once someone can actually look at it worn.

**Known, accepted gap**: if the operator adjusts the dashboard brightness slider WHILE the panel is
already dimmed (headset genuinely resting), `set_brightness_gain()` writes the newly requested value
at FULL brightness, not the dimmed fraction, until the next real doff -- because the dashboard has no
idea a dim is currently in effect. Harmless in practice (nobody is watching the panel to judge
brightness while it's resting on a desk) and self-corrects on the very next `NOT WORN` commit; not
worth a cross-process "is currently dimmed" flag for a purely cosmetic feature.

### Build

Full rebuild both times (`cd ~/vr/monado/build && cmake --build .`, default target, not a partial
one -- confirmed with a follow-up no-op build showing `ninja: no work to do.` both times): clean
except the same two pre-existing, unrelated warnings the task described in advance (`control_read_packets`
sign-compare, `PRESENCE_STALE_NS` integer-overflow) -- nothing new introduced by either change.

### Not done this round, flagged for a future session with physical/Windows access

The user's own separate idea, explicitly not executed here: a real USB packet capture of genuine
Windows/WMR Portal runtime behavior against the same G2 (dual-boot, or a Windows machine with the
same headset) to see how many confirming samples -- or what actual debounce -- Windows requires
before committing "worn". Would directly answer the open trade-off flagged above (whether 2 confirming
packets is cheap or expensive relative to how a real donning gesture actually behaves) instead of
guessing from a resting-desk session alone. Needs physical hardware access and a Windows boot; not
something this pass could do, and explicitly out of scope for a code-analysis-only task.

### Live-test checklist for a future session (NOT run this round)

1. `WMR_PRESENCE_DIAG=1 WMR_USER_PRESENCE=1 WMR_USER_PRESENCE_SCREENOFF_MS=<short value for
   iteration>` (do not touch `~/vr/presence.conf`'s production value per this task's own
   instruction), then a genuine doff, a long enough wait for a real blank, and specifically leaving
   the headset UNTOUCHED afterward for several minutes -- the exact scenario that produced the false
   relights -- to confirm they no longer happen.
2. A genuine, deliberate don, timed, to see how many real packets and how much wall time it actually
   takes to commit WORN under `DON_CONFIRM_PACKETS=2` -- this is the number needed to resolve the
   open trade-off above.
3. Listen for the two dim/undim transitions alongside the existing "casco en la mesa"/"casco puesto"
   audio, and glance at the panel through a spectator view (or briefly don it) to confirm the partial
   dim is visible but not alarming at `RESTING_DIM_FACTOR=0.35`.

Committed on `~/vr/monado` (branch `lab-full`, remote `wintch` NOT pushed): `d07872fd9` (pre-existing
screen-off-fresh-fd work, found uncommitted and completed) and `41626b6e2` (this section's debounce
fix). Committed on `~/Documents/reverb-g2` (branch `main`, NOT pushed): `scripts/presence-sound-alert.sh`
(brightness dim/undim hooks + updated state-comment header) and this file.

## 2026-09-06 (later still) -- live-caught follow-up: packet confirmation alone left a real don uncommitted for 13+s; fixed with IMU motion corroboration + a bounded timeout (code-analysis-only, not live-tested)

Live wearer test of `41626b6e2` (the packet-confirmation fix from the section above) surfaced
the opposite failure mode almost immediately: the user donned the headset for a real restore
test, `PRESENCE-DIAG` showed `candidate` flip to `1` right away (a genuine proximity=1 packet),
but `committed` stayed `0` for 13+ seconds and counting -- confirmed live via repeated
`PRESENCE-DIAG heartbeat` lines showing `candidate=1 committed=0` unchanged, because the 2nd
confirming packet `WMR_USER_PRESENCE_DON_CONFIRM_PACKETS=2` now requires never arrived in that
window. The wearer was left donned with the panel still blanked and no visible restore, had to
be un-blanked manually out-of-band (`scripts/panel.py activate`, bypassing the driver entirely)
as a stopgap, and the session was torn down (`jack-in-wayland.sh down`) once this was confirmed
-- specifically to stop leaving the wearer in an unpredictable state, not because anything was
left running that needed attention. Per this follow-up task's own explicit instruction, this
whole pass was **code-analysis-only from here**: no live hardware touch, no `monado-service`
launch, no live test, no sudo -- everything below was designed and built against the log this
live test had already produced, then rebuilt and reasoned about, not re-tested live.

### Independently verifying the brief against the actual log, before designing anything

Rather than take the task's framing on faith, re-derived the failure directly from
`~/vr/jack-in-wayland.log` (the exact copy this live test produced) and from `git log`/`git show`
on `~/vr/monado` `lab-full`. Two corrections to the framing worth recording:

**The commit history has 3 commits from tonight, not 2 as loosely remembered going in**:
`d07872fd9` (blank over a fresh fd), `41626b6e2` (the 2-packet confirmation debounce), and a
third, `911ef3c56` ("re-blank the panel after every periodic reassert poke while auto-standby is
active") -- the fix for the *other* live-caught bug tonight (the periodic 15s keep-alive poke
structurally ending in a real screen-ON send, with nothing ever re-blanking afterward, so every
poke permanently relit the real backlight). That one is separately live-validated ("todo negro"
sustained across multiple keep-alive cycles) and untouched by this section -- it is not the same
bug as the one fixed here, and nothing below revisits it.

**The real log data is worse than "13+ seconds and counting" by itself suggests.** Grepped
`control_ipd_value_decode` and `PRESENCE-DIAG heartbeat` across the full captured
`jack-in-wayland.log` rather than trusting the live chat-timed figure alone:

```
717: PRESENCE-DIAG raw packet #2: proximity=0 ipd=765
...(heartbeats climbing, raw_proximity=0, for the next ~74s of last_packet_age_ms)...
783: PRESENCE-DIAG raw packet #3: proximity=1 ipd=763        <- candidate flips to WORN
784: heartbeat: raw_packets=3 raw_proximity=1 candidate=1 committed=0 last_packet_age_ms=1237
...
816: heartbeat: raw_packets=3 raw_proximity=1 candidate=1 committed=0 last_packet_age_ms=43271
                                                                       ^^^^^^^^^^^^^^^^^^^^^^^
                                                       43+ real seconds, committed never flipped
827: PRESENCE-DIAG raw packet #4: proximity=0 ipd=768        <- CONTRADICTS the candidate
828: heartbeat: raw_packets=4 raw_proximity=0 candidate=0 committed=0 ...
```

So this was not "eventually confirmed, just slow": the candidate held for 43+ real seconds with
zero corroboration, and the very next packet to arrive **contradicted** it (proximity flipped
back to 0) rather than confirming it -- per the debounce's own flip logic, this resets the
candidate to NOT WORN and the entire don is discarded, never committed WORN at all. The
non-heartbeat lines in the same window show the real cause was not "the wearer took it off
again" -- `Client 1 disconnected` appears between packet #3 and #4, i.e. the `jack-in-wayland.sh
down` teardown (done specifically to end the stuck-donned state safely) is what produced
packet #4's proximity=0, not a real doff during the test. **The genuine don in this test was
never registered by the driver at all, for the entire time the user wore it.**

Also confirmed directly from `git show 41626b6e2` (not assumed): the fix is exactly as described
in the section above -- `candidate_confirm_count` requires `WMR_USER_PRESENCE_DON_CONFIRM_PACKETS`
(default 2) independent packets to agree, tracked via `presence.last_update_ns` advancing (an
"arrival time, not change time" signal `control_ipd_value_decode()` already sets on every decode
regardless of value change). No surprises there; the fix does exactly what its own commit message
says. The problem is purely that "independent packet" is an expensive, rare event on this
hardware (2 s to 100+ s apart, per the SAME commit's own log-derived comment) -- a correct fix for
a noise-rejection problem, with no latency bound at all for the case that actually matters live.

### Design: IMU motion corroboration (fast, strong) + a bounded timeout (slow, weak, honest)

Read `wmr_hmd_presence_tick()` in full before designing anything, plus its caller
(`wmr_run_thread()`) and `hololens_sensors_decode_packet()` per this task's own hint, to find
what motion data is already available without new plumbing. Found `wh->fusion.last_angular_velocity`
(`wmr_hmd.h`'s `fusion` substruct, "the last angular velocity from the IMU, for prediction") --
already a **calibrated** gyro sample (mix-matrix + bias-offset applied, rotated into the OXR
frame), already updated on **every** IMU packet decode by both `hololens_handle_sensors_avg()` and
`hololens_handle_sensors_all()`, both called from `hololens_sensors_read_packets()` --
which `wmr_run_thread()`'s own loop calls **immediately before** `wmr_hmd_presence_tick()` on
every single iteration. So by the time the tick function runs, this field already holds
same-tick-fresh motion data, protected by the existing `wh->fusion.mutex` (already used elsewhere
in this exact call chain) -- zero new plumbing needed, exactly what the task asked to check for
before inventing any.

This is the key structural advantage over the proximity channel: the IMU updates every tick
(~250 Hz) regardless of whether a proximity packet has arrived, so "is something physically
moving this thing right now" is a continuously-available signal, unlike "did the sparse
companion channel happen to send a 2nd sample yet."

**The fix, in `wmr_hmd.c`/`wmr_hmd.h` (`lab-full`, commit `a01003fb8`):**

1. New `presence.candidate_motion_peak_rad_s` (float): the peak `|wh->fusion.last_angular_velocity|`
   observed since the candidate last flipped. Reset on a flip to *that tick's own* reading (not
   0 -- the flipping tick may already carry real motion), then extended by a running max every
   tick thereafter while the candidate is WORN.
2. `WMR_USER_PRESENCE_DON_MOTION_RAD_S` (default **0.10 rad/s**): if the peak crosses this, that
   alone satisfies confirmation -- in addition to (not instead of) the existing packet-count path.
   Either one is enough once `WMR_USER_PRESENCE_DON_MS` has also elapsed.
3. `WMR_USER_PRESENCE_DON_CONFIRM_TIMEOUT_MS` (default **4000 ms**): a hard ceiling -- if the
   candidate has held continuously this long with neither enough packets nor enough motion,
   commit anyway on the wall-clock alone (the pre-`41626b6e2` behavior). This is the one hard
   requirement the task set: a genuine don must never hang indefinitely.
4. The `WMR_INFO` commit log now always prints the observed motion peak and which of the three
   paths (`packets` / `motion` / `timeout`) actually triggered the commit, so the next live
   session can read real numbers directly instead of re-deriving them from raw packet lines.

**Where the 0.10 rad/s default comes from, and why it is not a blind guess.** Rather than invent
a number with zero grounding, searched the codebase for any existing "is this device at rest"
threshold already established elsewhere in Monado -- and found one: `m_imu_3dof.c`'s own
`gyro_bias_auto()` already defines `STILL_GYRO_RAD_S = 0.10f` as the boundary between "at rest"
(safe to auto-recalibrate gyro bias) and "moving," used generically across any Monado 3dof-fused
device, not invented for this task. Better still, this exact threshold already has **real, live
logged output from this exact physical unit**: `~/vr/jack-in-wayland.prev2.log` (an earlier
session on this same rig) shows `gyro_bias_auto`'s own throttled diagnostic line firing
repeatedly while the headset sat resting, e.g.:

```
gyro_bias_auto[0x55edd304ac98]: gyro=0.0139 rad/s (limit 0.10) accel=9.756 (want 9.81 +-0.5) -> STILL
gyro_bias_auto[0x55edd304ac98]: gyro=0.0130 rad/s (limit 0.10) accel=9.760 (want 9.81 +-0.5) -> STILL
```

Real resting-state gyro magnitude on this unit sits at **0.011-0.016 rad/s**, comfortably (6-9x)
below the 0.10 rad/s threshold -- so reusing that exact number leaves real margin above the
measured noise floor rather than sitting right on top of it. **What this default has explicitly
NOT been validated against, for lack of live access this pass: the actual peak magnitude a real
donning gesture produces on this unit.** The reasoning that it should clear 0.10 rad/s easily
(picking up and placing a headset on a head involves far more rotation than desk-resting
micro-vibration) is sound but untested -- this is reasoning from the sensor's known behavior
elsewhere in this same codebase, not a live measurement of a real don. The commit log's new
`motion peak %.3f rad/s` field exists specifically so the very next live don/doff session settles
this with real data instead of guessing blind twice.

**Being honest about the timeout path's limitation, per this task's own explicit ask not to
oversell it.** The 4000 ms ceiling is NOT a meaningful noise-rejection improvement by itself --
this same log shows a stray packet's candidate can and does sit uncontradicted for well over 4
seconds when packets are this sparse (the very don analyzed above held 43+ seconds before any
2nd packet arrived at all), so a resting-desk noise blip that happens to survive quietly for 4
seconds would still falsely commit via the timeout path, just delayed from the old 250ms to 4000
ms rather than eliminated. The real noise-rejection value in this fix is the motion path: a
genuinely resting, untouched headset should sit at ~0.01 rad/s indefinitely (per the real data
above) and should never cross 0.10 rad/s on its own, so it should never need the timeout to
rescue a false commit. The timeout exists purely to bound wearer-facing latency for a genuine
don in the (expected to be rare, but not proven rare without a live test) case where the motion
path also fails to trip -- not as a second independent defense against noise. Recorded plainly so
a future session does not mistake "bounded" for "noise-proof."

### DOFF direction: re-examined against tonight's data specifically, left untouched

The prior fix (`41626b6e2`) left `WMR_USER_PRESENCE_DOFF_MS` as pure wall-clock, citing no live
evidence of a matching noise-flip-to-0-while-worn failure mode. Re-checked this decision against
tonight's own data rather than carrying it over unquestioned, per this task's explicit ask: the
captured log from tonight's test **still** contains no genuine WORN stretch that also shows a
spurious flip back to NOT WORN mid-session (the don analyzed above never even reached `committed`,
so there was no worn session to spuriously interrupt). No new evidence changes the prior
decision. Separately, applying either the packet-confirm or the new motion-confirm mechanism to
the DOFF direction would actively cut against this driver's own hardware-protection goal (getting
`SCREENOFF_MS`'s countdown started sooner on a real doff, to spare the one physical panel) by
making a genuine doff wait on extra corroboration before the countdown could even begin. Left
alone; revisit only if a live test produces a real spurious mid-worn doff.

### Build

Full rebuild (`cd ~/vr/monado/build && cmake --build .`, default target, confirmed via a
follow-up no-op build showing `ninja: no work to do.`): clean except the same two pre-existing,
unrelated warnings flagged in advance by this task (`control_read_packets` sign-compare,
`PRESENCE_STALE_NS` integer-overflow) -- nothing new introduced.

While in this code, also corrected a stale comment left over from `41626b6e2`: the
`candidate_confirm_count` field comment in `wmr_hmd.h` still said "~750 Hz" for the read thread's
rate, even though the `wmr_hmd.c` comment right next to the debug option itself had already been
corrected to the real, log-measured ~250 Hz in that same commit. Fixed the header to match.

### What is untested -- everything here, plainly

Per this task's own hard constraint (no live hardware, no `monado-service`, no live test, no
sudo), **nothing in this section has been run against real hardware**:

- Whether 0.10 rad/s is actually crossed by a real donning gesture on this unit, and by how much
  (expected to clear it easily, not measured).
- Whether 0.10 rad/s is ever falsely crossed by something OTHER than a real don while the headset
  sits resting -- e.g. desk vibration from a nearby door, someone bumping the table, HVAC/fan
  vibration transmitted through the surface it rests on. The only real data available is the
  `gyro_bias_auto` resting-log excerpt above, which shows calm, low readings, but that log was not
  captured specifically to stress-test ambient vibration.
- Whether 4000 ms actually feels acceptable to a wearer as a worst-case wait, or whether it should
  be shorter (the task's own framing said "a few seconds," and 4000 ms is deliberately at the
  upper end of that to leave the motion path more room to be the one that actually fires first --
  but this trade was made without a live wearer's real reaction to fall back on).
- Whether the three-way `packets` / `motion` / `timeout` split actually resolves tonight's exact
  scenario correctly -- i.e. whether a real repeat of tonight's don would now show `via motion` in
  the commit log within a fraction of a second, as designed, rather than falling through to
  `timeout` at the 4-second mark or (worse) still not committing at all for some reason not caught
  by this pass's code reading.
- Whether the new `os_mutex_lock(&wh->fusion.mutex)` call added inside `wmr_hmd_presence_tick()`
  (already holding `wh->presence_lock`) is free of any lock-ordering surprise under real
  concurrent load -- reasoned through by inspection (no other code path locks `presence_lock`
  while already holding `fusion.mutex`), not exercised under a live thread-sanitizer or stress
  test.

**Live-test checklist for the next session with physical access** (not run this round):

1. `WMR_PRESENCE_DIAG=1 WMR_USER_PRESENCE=1 WMR_USER_PRESENCE_SCREENOFF_MS=<short>` (leave
   `~/vr/presence.conf`'s real value alone), force a real blank, then a genuine, deliberate don --
   watch the `User presence: WORN` commit log line specifically for its new `motion peak %.3f
   rad/s, via %s` fields. `via motion` within roughly `DON_MS` (250 ms) of the don would confirm
   the design works as intended; `via timeout` would mean the motion path did not trip and the
   0.10 rad/s default needs lowering; `via packets` would mean the sparse channel got lucky.
2. Repeat several times to get a real distribution of the motion peak value for a genuine don,
   not just one sample -- use it to tune `WMR_USER_PRESENCE_DON_MOTION_RAD_S` for real if the
   observed peaks run close to 0.10 rather than comfortably above it.
3. Leave the headset resting untouched for several minutes with diagnostics on, watching for any
   `via timeout` commit with a low motion peak -- that would be the residual, honestly-flagged
   risk from the timeout path materializing, and would argue for raising 4000 ms or re-examining
   the motion threshold.
4. If a real spurious mid-worn doff is ever observed, revisit the "DOFF direction left untouched"
   decision above with that evidence in hand.

Committed on `~/vr/monado` (branch `lab-full`, remote `wintch` NOT pushed): `a01003fb8`
("wmr: bound WORN-commit latency with IMU motion corroboration + timeout"), touching
`wmr_hmd.c`/`wmr_hmd.h`.

## 2026-09-06 (later still) -- adversarial review split on `a01003fb8`, the sharper reading kept

Two independent reviewers checked `a01003fb8` (the motion-corroboration + timeout fix above) before
it was treated as done. Both confirmed the worst-case latency bound is real and correctly implemented
(no off-by-one, no overflow, no lock-order issue -- `presence_lock` -> `fusion.mutex` consistently,
matching every other acquisition site in the file) and that it is NOT a regression against the
keep-alive-poke re-blank fix (`911ef3c56`, zero overlap in the diff). They differed only on how to
characterize the timeout path's known tradeoff, already disclosed above as "a weak noise filter":

- Reviewer A called it "not a confirmed bug -- an already-disclosed tradeoff."
- Reviewer B traced the actual consequence through to the hardware and called it a confirmed,
  understated regression risk: `confirm_ok = packets_ok || motion_ok || timeout_ok` means
  `timeout_ok` alone -- zero packet corroboration, zero motion -- is sufficient to commit WORN and
  physically re-light the panel (the `screen_off_by_presence` branch at the restore call site).
  Given tonight's own measured proximity-packet gaps (2 s - 100 s, one case 43 s before a
  *contradicting* packet even arrived), a single noisy byte surviving uncontradicted for the full
  4000 ms default is not a remote edge case on this specific unit -- it is a very plausible,
  possibly common outcome, and when it happens the result is exactly tonight's original symptom
  (the panel re-lighting itself with nobody wearing it), just delayed from ~250 ms to ~4000 ms
  rather than eliminated. The doc's own item 3 in the "how to validate live" list already
  anticipated this exact failure mode as something to watch for -- Reviewer B's point is that it
  should be named as a real, likely-reachable risk going in, not discovered as a surprise later.

**Keeping Reviewer B's framing as the operative one.** Nothing here invalidates the fix -- it is a
genuine, verified ~16x hardening (250 ms -> 4000 ms before an uncorroborated single sample can
commit), and per this investigation's own hard requirement a real don must never hang indefinitely,
which this design satisfies. But "the panel can still relight itself from a single noisy byte with
nobody wearing it" should be read as a live, expected-to-eventually-occur behavior of the current
design, not a hypothetical corner case ruled out by today's work. The honest status is: **the
day's original bug (instant relight from noise) is bounded, not eliminated.**

This is also a direct argument for the parallel finding from tonight's genuine-Windows-standby
packet captures (see the capture-analysis section, if present below/elsewhere in this doc): if
real Windows/SteamVR standby turns out to be a pure compositor-side render-black with no HID
backlight toggle at all, then a false WORN commit under that architecture would just flip a
render gain back and forth -- cosmetically wrong for a moment, but not a real backlight power
cycle. That would make this whole confirm/timeout tradeoff much lower-stakes than it currently is
under Monado's own HID-driven auto-standby, which is worth weighing before spending more effort
tuning `WMR_USER_PRESENCE_DON_MOTION_RAD_S`/`_DON_CONFIRM_TIMEOUT_MS` further.

## 2026-09-06 (later still) -- genuine Windows/Oasis standby, USB-level ground truth from real captures

The user independently ran the real Windows Mixed Reality stack tonight -- Windows 11, SteamVR,
and the "Oasis Driver for Windows Mixed Reality" (mbucchia's SteamVR replacement for Microsoft's
own discontinued WMR portal, running natively on Windows, not the Linux/Wine "Ignition" port) --
with the same physical G2 unit, and captured raw USB traffic with USBPcap/Wireshark across two
tests: SteamVR's motion-based standby ("modo movimiento", `camera_apareo_standby.pcapng`, ~717s /
485k packets / 2.4GB) and its proximity-based standby ("modo proximidad",
`camera_apareo_standby_2_sensor.pcapng`, ~160s / 162k packets / 959MB). This section analyzes
those captures directly (`tshark`) to answer the question raised earlier tonight: does real
Windows standby actually toggle the companion's backlight over HID the way Monado's own
auto-standby does, or is it doing something else -- motivated by the user's live observation that
Steam's standby only blanks the rendered image (backlight visibly stays lit) and the panel only
goes genuinely dark when SteamVR fully exits.

**Method.** USB device addresses get reused across a capture this long as devices enumerate,
disconnect, and re-enumerate (Windows recycles addresses), so filtering by `usb.device_address`
alone across the whole file is unreliable -- confirmed directly: address 5 was the Realtek camera
(`0x0bda:0x4c15`) at t=1s but the HP QHMD companion (`0x03f0:0x0580`) by t=285s. Cross-referenced
every `usb.idVendor`/`usb.idProduct` sighting against its frame's timestamp and device address
before trusting any address-scoped query. Our own driver's screen on/off command
(`wmr_hmd_screen_off_reverb_fresh_fd`/`wmr_hmd_reassert_reverb_fresh_fd` in `wmr_hmd.c`) is sent
as an HID **Feature report** via `os_hid_set_feature()` -- a `SET_REPORT` class control transfer
(`bmRequestType 0x21`, `bRequest 9`) with `wValue` high byte `0x03` (ReportType=Feature). That
exact shape is what was searched for first, since it is the most direct possible confirmation or
refutation of "does Windows use the same command we do."

**Finding 1 -- zero HID Feature-report SET_REPORT commands anywhere, in either capture.**
`tshark -Y "usb.bmRequestType==0x21 && usb.setup.bRequest==9 && usb.setup.wValue>=0x0300 &&
usb.setup.wValue<0x0400"` against the full motion-mode capture (485k packets) and the full
proximity-mode capture (162k packets) both returned **zero matches**. Genuine `SET_REPORT` class
requests do appear throughout both captures (e.g. an Output-type report, `wValue=0x0200`,
`wLength=1`, single data byte `00`, most likely an Xbox controller rumble/LED write given the
device present in this capture) -- so the HID class-request path itself is exercised normally by
other devices, it is specifically the Feature-report shape that never appears. **This directly
refutes the assumption this session's auto-standby work has been built on**: real Windows/Oasis
standby is not sending the equivalent of our `{0x04,0x00}`/`{0x04,0x01}` Feature report at all,
on any device, at any point in either capture.

**Finding 2 -- the motion-mode capture shows the companion undergoing full USB re-enumeration,
three times, not a simple in-band command.** Searching the whole file for `SET CONFIGURATION`
requests (a mid-capture occurrence, after the initial t=0-1s startup enumeration of all 6
devices, means something actually reset/reconnected at the USB level) found three clusters: at
relative t~283-286s, ~317-320s, and ~365-368s. In the first cluster, the HP QHMD companion
(`0x03f0:0x0580`, address 5 at that point) does a complete `GET DESCRIPTOR DEVICE` ->
`GET DESCRIPTOR CONFIGURATION` (x2) -> `SET CONFIGURATION` -> `SET_IDLE` ->
`GET DESCRIPTOR HID Report` sequence -- i.e. exactly what a device does when it is freshly
plugged in or comes back from a real USB-level reset/power-cycle, not what happens when an
already-open handle just receives one more command. About 0.8s later in the same cluster, the
Microsoft HoloLens Sensors interface (`0x045e:0x0659`) does the identical full-enumeration
sequence. The same shape repeats at the other two clusters. This is consistent with (though not
independently proven to be) the multiple deliberate wake/standby attempts the user described
making during this test ("por movimiento arranca igual" -- motion mode woke every time they
tried) -- three clusters for what was likely several manual test cycles is plausible, but this
capture alone does not carry an unambiguous "standby entered here, exactly" marker (the nearest
available reference points, Steam screenshot filenames from the same session, land tens of
seconds after the nearest cluster and don't pin the moment precisely) so which cluster
corresponds to which specific user action is not claimed here with confidence -- only that this
re-enumeration behavior happens, repeatedly, and looks nothing like a single HID command.

**Finding 3 -- the proximity-mode capture shows no mid-capture re-enumeration at all.** The same
`SET CONFIGURATION` search against the full 160s proximity-mode capture found only the initial
t=0-1s startup enumeration of all 6 devices -- no later cluster. Combined with Finding 1 holding
for this file too (zero Feature-report SET_REPORTs), this capture simply does not show *any*
USB-level event that looks like a standby/wake transition, in either the "simple command" or
"device reset" shape. Given the user's own note that proximity mode "arranca... seguro que en la
segunda prueba" (proximity-mode wake was reliable only on the second attempt), it's plausible this
particular 160s window didn't span a full standby-then-wake cycle at all, or that whatever
Windows does for proximity-mode standby leaves no USB-level trace distinguishable from ordinary
sensor traffic -- both are open possibilities, not resolved here.

**What this does and doesn't establish.** It's now directly evidenced, not just user-observed,
that Monado's entire auto-standby architecture (an in-band HID Feature-report toggle over the
companion's control channel, the exact mechanism this whole investigation has been hardening
today -- fresh-fd sends, keep-alive pokes, debounce redesign) has **no counterpart in what real
Windows/Oasis actually does** in this capture. The strongest lead for what real Windows does
instead is the observed USB re-enumeration pattern -- a real port-level reset/power-cycle -- which
would be a categorically different, more invasive mechanism than anything built today, and would
also cleanly explain the user's own observation that only a *full SteamVR exit* reliably darkens
the backlight (a full exit very plausibly does trigger a genuine device power-down/reset, the same
shape seen mid-capture here) while lighter standby mostly just blanks the render (a compositor-
side operation, not a device-level one). This is consistent with, and strengthens, the
already-noted case (see the brightness/render-side mitigation discussion earlier in this file) for
treating a compositor-side render-black as the primary "worn but idle" mechanism rather than
continuing to fight the HID-level toggle for that case -- reserving any real device-level
power-cycle, if one is ever attempted, for genuine session start/end, matching what these captures
suggest Windows itself does. **Not established**: that the re-enumeration clusters found here are
*specifically* standby-triggered (versus some other retry/renegotiation this test's repeated
manual attempts could also explain) -- a future capture bracketing a single, clearly time-marked
standby-then-wake cycle (e.g. the tester speaking a timestamp aloud, or a screenshot taken at the
exact moment of standby) would settle this with more confidence than what these two captures, made
for a different immediate purpose, can support on their own.

Raw extraction files (not committed, local scratch only): device/address timelines and the
Feature-report/SET_CONFIGURATION query outputs used above are in the analyzing session's own
scratchpad, not part of this repo.

## 2026-09-06 (later still) -- a01003fb8's motion corroboration never even ran: motion promoted from candidate-corroborator to independent primary signal (code-analysis-only, not live-tested)

Separate follow-up task, same night, explicitly framed as code/log/design work only -- no live
hardware, no `monado-service` launch, no live test, no `sudo` -- because this rig is the user's only
physical G2 and a human tester is actively using it live tonight. Confirmed live, immediately before
this task started: a wearer donned the headset for over 5 minutes with the panel still
auto-standby-blanked from a prior doff, unable to get a restore, and had to be un-blanked manually
out-of-band (`scripts/panel.py activate`) as a stopgap.

### Independently verifying the brief before designing anything

Per this task's own standing instruction not to take a brief on faith, re-derived the failure
directly from the live `~/vr/jack-in-wayland.log` on `iashur` (this was an ACTIVE, still-growing log
at the time of reading -- `stat` showed the file's mtime within one second of `date`, and a
`monado-service`/`hello_xr` pair was confirmed still running, read-only `pgrep`, nothing touched) and
from `git log`/`git show a01003fb8` on `~/vr/monado` `lab-full`.

**The core claim holds, with one factual correction worth recording.** The task's framing said
`raw_packets` was "stuck at 1." The actual log shows two full, successful `via motion` WORN commits
earlier in the SAME session (motion peaks 0.104 and 0.977 rad/s -- see below), each followed by a
correctly-committed NOT WORN a few seconds later, each off a real, distinct proximity packet
(`raw_packets` climbing 3 -> 4 -> 5 -> 6 through that stretch, not frozen at 1). The actual stuck
point is AFTER packet #6 (the second NOT WORN commit) and the second `panel blanked by auto-standby`
that follows it: from there, `raw_packets` freezes at exactly 6 and `PRESENCE-DIAG heartbeat` shows
`raw_proximity=0 candidate=0 committed=0 screen_off_by_presence=1` completely unchanged for the rest
of the captured window -- 228681 ms (3.8 real minutes) and still climbing at the moment of reading,
confirmed by re-reading the log's tail a second time and seeing it still growing live. So the
precise number in the brief ("stuck at 1") doesn't match the raw counter value, but the underlying
claim -- a long, real, still-ongoing stretch with literally zero new proximity packets while the
panel sits blanked -- is exactly what the log shows, just measured from packet #6 rather than #1.
Recording this correction explicitly rather than silently using the "right" number without flagging
that the brief's specific figure needed adjusting.

**New data point beyond what the brief asked to confirm**: throughout that entire 228+ second stuck
window, the periodic reassert poke (`WMR_PRESENCE_REASSERT_INTERVAL_MS`, firing every 15s per its own
schedule, confirmed via repeated `Sent activation report (fresh fd)` / `presence auto-standby:
reassert took ...` / `Sent screen-off (fresh fd)` triplets in the log) kept firing on schedule the
whole time -- and NOT ONE of those pokes produced a new proximity packet. This directly complicates
the earlier, more optimistic finding from the ~12:30 entry above ("screen reassertion wakes the
companion channel," 2/2 success in a small manual A/B test): whatever effect that test measured, it
is evidently not reliable enough to depend on as a general mechanism for restoring proximity
delivery -- the channel can and does stay completely dark for many minutes even with periodic
reasserts actively running against it the whole time. Not a contradiction of that earlier finding (it
was a real, reproduced effect at the time), but a reminder that a 2/2 sample from one session doesn't
generalize to "this always works," and this driver should not lean on it as a rescue mechanism going
forward -- which is part of the motivation for this section's fix using a completely different
signal instead.

**Confirmed directly from `git show a01003fb8`, not assumed**: the fix is exactly as its own commit
message describes -- `confirm_ok` (packets/motion/timeout) is computed entirely inside
`if (wh->presence.candidate) { ... }`, which itself is inside
`if (wh->presence.candidate != wh->presence.committed) { ... }`. Tracing this literally: if
`wh->proximity_sensor` never changes from 0 (as tonight's confirmed stuck window shows), `raw_worn`
is `false` on every tick, `wh->presence.candidate` never flips away from its already-committed value,
the outer `if` never becomes true, and NOTHING inside it -- not the packet count, not the motion
peak, not even the supposedly-unconditional hard timeout -- ever executes, for as long as the channel
stays silent. This matches the task's own framing precisely: the previous fix could only ever help a
candidate that already existed; it had no way to create one when the sole input that creates a
candidate (the proximity byte) never moves.

### Design: promote motion to an independent primary signal, not a bigger corroborator

Read `wmr_hmd_presence_tick()` in full again, plus the `presence` struct in `wmr_hmd.h`, before
designing anything (per this task's own hint not to invent new plumbing before checking what already
exists). The same `wh->fusion.last_angular_velocity` a01003fb8 already reads (calibrated,
`fusion.mutex`-protected, refreshed every tick regardless of proximity state) is still the only motion
signal used -- no new sensor plumbing needed, same as before.

**The mechanism, in one sentence**: a new `worn_signal` (computed once per tick, before the debounce
block) replaces the raw proximity byte as the value that drives `wh->presence.candidate`, and
`worn_signal` can now become true either because the proximity byte says so (unchanged) or because a
sustained motion run is in progress AND the proximity channel has gone stale/silent long enough to no
longer be trusted on its own.

**Three cases, reasoned through explicitly** (matching the new code comment in `wmr_hmd.c`, restated
here with the reasoning that led to each):

1. **Raw byte says worn.** Always wins, unconditionally, whether the reading is fresh or a stale
   last-known-worn value. This is also what makes the WORN-but-motionless case safe (see below): a
   wearer who dons the headset via case 2, then goes still (watching content, reading), keeps
   `raw_worn` at whatever the byte's last real value was -- if that value was ever `worn`, case 1
   fires on every subsequent tick and case 2's own logic is never reached again for that wearer, so a
   later motion lull cannot undo anything.

2. **Raw byte says NOT worn (or has never reported anything at all) AND the channel has been
   silent for `WMR_USER_PRESENCE_MOTION_RESCUE_STALE_MS` (default 30000ms) or longer.** Hand
   authority to motion. If a sustained run is CURRENTLY in progress, assert worn -- this is the
   actual rescue, and it is the only new way `worn_signal` can become true that raw proximity alone
   would never have allowed. If no run is currently sustained, HOLD the existing `candidate` value
   rather than forcing it false. This holding behavior is the single most important safety property
   of the whole design and deserves its own explanation:

   **Why motion-quiet must NOT independently commit NOT WORN, even though the task explicitly raised
   this as an option to consider.** The DON case and the DOFF case are not mirror images of each
   other, and treating them as if they were would be a mistake. For DON, "sustained real rotation is
   happening" is a strong, low-false-positive signal -- it is genuinely difficult to put a headset on
   a human head with no meaningful head/hand motion at all, so requiring motion to positively appear
   is a safe bar to set. For DOFF, the proposed mirror rule would be "the ABSENCE of motion for a
   while means not-worn" -- but a wearer who is genuinely wearing the headset and sitting still
   (watching a 360 photo, reading in-VR text, a seated cockpit experience) produces exactly that same
   absence of motion, for potentially very long stretches, while very much still wearing it. Building
   a rule that treats stillness-while-worn the same as stillness-while-not-worn would turn ordinary,
   calm VR usage into spurious doffs -- pausing the app and (per the existing brightness-dim
   mitigation, and eventually the real HID blank after `SCREENOFF_MS`) dimming or blanking the panel
   on someone who never took the headset off. This is a real, asymmetric risk that the DON case does
   not share, and it is why case 2 above only ever pushes `worn_signal` toward `true`, never toward
   `false` -- matching, rather than contradicting, this exact struct's own long-standing "fail toward
   worn, never toward absent" philosophy already documented for the DON/DOFF debounce windows.

3. **Raw byte says NOT worn AND the channel is fresh** (it has recently, actively reported the
   opposite of what motion might be suggesting). Trust the live sensor. A channel that is
   demonstrably alive and currently disagreeing with motion always wins -- motion is a fallback for
   when the real sensor has nothing to say, not a competitor to it when it does.

**What this means for the DOFF direction, concretely, re-examined against tonight's data
specifically rather than carried over unquestioned (per this task's own explicit ask)**: DOFF's own
commit path (`WMR_USER_PRESENCE_DOFF_MS`, pure wall-clock, unchanged since `41626b6e2`) is left
completely untouched. The captured log from tonight still contains no genuine spurious mid-worn doff
to point at, and the reasoning above (case 2's asymmetry) argues independently, not just from absence
of evidence, that a motion-driven doff mechanism would be actively harmful to this driver's own goals
rather than merely unproven. The honestly-disclosed cost of this decision: if the proximity channel
goes silent WHILE genuinely worn (as opposed to while genuinely not-worn, tonight's confirmed case),
and the wearer later removes the headset, `raw_worn` stays stuck at its last known `true` value (case
1 above, same as pre-existing behavior, completely unaffected by tonight's change) and the driver has
no way to learn about the real doff until/unless the channel starts talking again. This is not a new
risk introduced tonight -- it already existed before this fix, for the identical reason (a doff
signal is exactly as sparse and exactly as capable of never arriving as a don signal) -- and this fix
does not make it any worse. It is also, per the earlier USBPcap-based finding in this same file
(real Windows/Oasis showing no in-band HID standby command at all, and the case made there for
treating a compositor-side render-black as the primary, lower-stakes "worn but idle" mechanism),
arguably lower-stakes than it looks in isolation: a stuck-committed-WORN panel just means the
render-side dim/HID-blank protections never engage, not that anything dangerous happens -- graceful
degradation on the side that already has the existing brightness-dim mitigation as a backstop, not a
wearer-facing hazard.

### Why a hysteresis-style "motion run" rather than a peak or a leaky integrator

Two more sophisticated alternatives were considered and rejected before settling on the implemented
design (a "run" that starts when magnitude crosses threshold, tolerates gaps up to
`WMR_USER_PRESENCE_MOTION_GAP_MS`, and is "sustained" once it has lasted
`WMR_USER_PRESENCE_MOTION_SUSTAIN_MS`):

- **A bare instantaneous peak, matching a01003fb8's own corroboration check.** Rejected because it
  cannot tell a genuine multi-hundred-millisecond donning gesture apart from one hard knock on the
  desk -- both can produce a single large `|angular velocity|` sample. a01003fb8's peak-based
  corroboration is fine BECAUSE it already has independent evidence (a real proximity=1 packet); this
  new path has no other evidence at all, so it needs a bar that reflects sustained handling, not one
  high sample.
- **A leaky-integrator "motion energy" accumulator** (`energy = energy * decay + magnitude * dt`,
  thresholded on the accumulated value). Considered because it is naturally robust to brief dips
  without an explicit gap-tolerance parameter, and is a common pattern for this class of problem.
  Rejected specifically for THIS task, THIS session: with only two real donning-gesture data points
  available (peak magnitudes 0.104 and 0.977 rad/s, no raw waveform, no duration), there is no way to
  responsibly pick a decay time constant or an energy threshold from real data -- both would be
  pure guesses with an extra layer of nonlinearity between the guess and its observable effect,
  harder to reason about and to explain in review than a simple hold-time. Given this session's own
  standing lesson about fixes that look correct on paper and fail live, the simpler, more legible
  mechanism was preferred even though the leaky integrator is arguably the more "correct" long-run
  design. Revisit once real sustained-motion waveform data exists from a live donning gesture.
- **Reusing the existing `PRESENCE_STALE_NS` (30s) log-notice constant directly as the rescue gate**,
  instead of a new, separate `WMR_USER_PRESENCE_MOTION_RESCUE_STALE_MS` tunable. Rejected to avoid
  coupling a log-cadence constant to a behavior-changing gate -- retuning one for its own purpose
  (e.g. quieting the stale-channel notice on a chattier future unit) should never silently also
  retune when the motion rescue is allowed to engage. Both start at the same 30000ms value for the
  same reason (well above normal packet latency, well below the multi-minute failure actually
  observed), but are independent knobs going forward.

### The fix, concretely (`~/vr/monado` `lab-full`, commit `510a6751c`)

`wmr_hmd.h`: two new fields on `struct wmr_hmd::presence`, `motion_run_started_ns` (0 = no run in
progress, else when the current run began) and `motion_last_above_ns` (the most recent tick's
timestamp where magnitude was at/above threshold, used to detect a gap long enough to end the run).
Both updated unconditionally on every tick, independent of candidate/committed/raw proximity, because
they have to reflect real-world motion regardless of what the proximity channel is or isn't saying --
that is the entire point.

`wmr_hmd.c`: four new `DEBUG_GET_ONCE_*` tunables, each documented in place with its own reasoning
(matching this file's established density) --

- `WMR_USER_PRESENCE_MOTION_PRIMARY_RAD_S` (float, default **0.10**): reuses the exact same
  `STILL_GYRO_RAD_S`-derived, live-log-grounded default a01003fb8 already established (this unit's
  own `gyro_bias_auto` resting log: 0.011-0.016 rad/s, 6-9x below this threshold) -- kept as a
  SEPARATE tunable from `WMR_USER_PRESENCE_DON_MOTION_RAD_S` on purpose, not merged, since the two
  paths have different risk profiles (one already has independent proximity evidence, one doesn't)
  and may need to diverge later.
- `WMR_USER_PRESENCE_MOTION_SUSTAIN_MS` (default **500**): comfortably longer than an expected
  sub-100-200ms bump/knock, comfortably shorter than a real donning gesture's expected
  multi-hundred-ms-to-few-second duration. Reasoning from gesture shape, not from a measured
  duration profile -- flagged as unvalidated below.
- `WMR_USER_PRESENCE_MOTION_GAP_MS` (default **250**): tolerance for a single noisy dip below
  threshold mid-gesture so it doesn't reset the whole sustain clock. A guess at "generous enough to
  bridge a natural pause, short enough not to fuse two genuinely separate events" -- also unvalidated
  against real sample-to-sample data.
- `WMR_USER_PRESENCE_MOTION_RESCUE_STALE_MS` (default **30000**): see the rejected-alternatives
  section above for why this is independent from `PRESENCE_STALE_NS` despite sharing its starting
  value and its reasoning.

All four follow this file's existing "0 or negative disables" convention; setting all four to 0
reproduces `a01003fb8`'s behavior exactly, with zero change.

**Worst-case latency bound, explicitly checked, not just assumed inherited**: once the rescue path
flips `worn_signal` (and therefore `candidate`) to `true`, `candidate_motion_peak_rad_s` is seeded
from that same tick's motion magnitude -- which, by construction, is already at or above
`WMR_USER_PRESENCE_MOTION_PRIMARY_RAD_S`. Since that threshold defaults to the same numeric value as
`WMR_USER_PRESENCE_DON_MOTION_RAD_S`, the existing `motion_ok` corroboration check
(`a01003fb8`, unmodified) will very likely already be satisfied on the very same tick, so the commit
lands `WMR_USER_PRESENCE_DON_MS` (250ms default) after the flip in the common case. In the worse
case where the two thresholds have been tuned apart, the existing hard timeout
(`WMR_USER_PRESENCE_DON_CONFIRM_TIMEOUT_MS`, default 4000ms, unmodified) still applies as an
unconditional backstop regardless of which path caused the flip. No new way to hang was introduced --
the fix re-enters and reuses `a01003fb8`'s own bound rather than duplicating or bypassing it, which
was the explicit hard requirement carried forward from that commit.

**Log line extended**, not replaced: `User presence: WORN (raw proximity sensor value 0 [stale],
held 254 ms, 1 confirming packet(s), motion peak 0.31 rad/s, via motion)` -- the new `[stale]`/
`[fresh]` tag alongside the existing `via packets`/`via motion`/`via timeout` reason lets a future
live session read directly off the log whether a given commit came through the ordinary
channel-healthy path (`[fresh]`, `via packets`) or the new rescue path (`[stale]`, `via motion`,
which is the exact signature tonight's 5+ minute stuck don would have produced had this fix already
been in place).

### Build

Full rebuild (`cd ~/vr/monado/build && cmake --build .`, default target, confirmed via a follow-up
no-op build showing `ninja: no work to do.`): clean except the same two pre-existing, unrelated
warnings this task described in advance (`control_read_packets` sign-compare, `PRESENCE_STALE_NS`
integer-overflow) -- nothing new introduced.

### What remains unverified without live hardware -- stated plainly, per this session's own standing lesson about overclaiming

This session has been burned before tonight by fixes that looked correct on paper and failed live
(`41626b6e2` itself was exactly this: a correct, reasoned fix for one bug that immediately exposed a
worse one the moment a real wearer tried it). Nothing below should be read as more confident than it
is:

- **Whether a real donning gesture on this unit actually produces a "run" that clears
  `WMR_USER_PRESENCE_MOTION_SUSTAIN_MS=500ms` of continuous-enough (within `MOTION_GAP_MS=250ms`
  gaps) motion above `0.10 rad/s`.** The only real data available is two PEAK samples from earlier
  tonight (0.104 and 0.977 rad/s) -- no waveform, no duration, no sample-to-sample gap pattern. The
  0.104 rad/s sample in particular is barely above the 0.10 threshold; if that don's magnitude spent
  much of its time hovering just below 0.10 with only a brief crossing, it is a genuine open question
  whether that SPECIFIC gesture would have cleared a 500ms sustained-run requirement, or would have
  had to fall through to the (still-safe, still-bounded, but slower) timeout path instead. This is
  exactly the kind of thing only a live test with the new `[stale]`/`via motion` log fields can
  answer.
- **Whether `WMR_USER_PRESENCE_MOTION_GAP_MS=250ms` is the right tolerance for real gesture noise.**
  Picked by reasoning about plausible gesture shape, not measured. Too short and a real gesture's
  natural micro-pauses could fragment into multiple short runs that never individually reach
  `MOTION_SUSTAIN_MS`; too long and two genuinely unrelated bumps could fuse into one false run --
  neither failure mode has been observed, because neither has been tested live.
- **Whether `WMR_USER_PRESENCE_MOTION_RESCUE_STALE_MS=30000` engages at the right moment in
  practice.** Reasoned to sit well above normal packet latency and well below the observed
  multi-minute failure, but "normal packet latency" itself was only measured across a handful of
  transitions tonight (sub-second to ~100s+), not a large sample -- it's possible some genuinely
  healthy stretches quietly exceed 30s between packets often enough that the rescue path engages more
  routinely than intended (harmless if it does, since case 3 still lets a fresh, actively-contradicting
  packet win, but worth knowing either way).
- **Whether the ambient-vibration margin this design leans on (0.10 rad/s threshold vs. 0.011-0.016
  rad/s measured resting noise) holds up against something more aggressive than a quiet desk** -- a
  door slam, someone bumping the table hard, a nearby loud fan directly touching the surface the
  headset rests on. Only calm-desk resting data exists; no stress test of this specific claim has
  been run.
- **Whether the new `[stale]`/`[fresh]` log tag and the `via` reason correctly and legibly tell the
  full story on a real repeat of tonight's exact failure** -- i.e. whether a live redo of "leave the
  channel dead for 5+ minutes, then genuinely don" now actually shows `[stale] ... via motion` within
  roughly a second of the real donning gesture, as designed, rather than falling through to `via
  timeout` at the 4-second mark (still correct and bounded, just slower) or, worse, not committing
  correctly for some reason this pass's code reading did not catch.
- **Lock-ordering and concurrency**, reasoned through by inspection only (no new lock was added; the
  new fields are read/written under the same already-held `presence_lock`, and the existing
  `fusion.mutex` acquisition for `motion_mag_rad_s` is unchanged from `a01003fb8`), not exercised
  under a live thread-sanitizer or stress test.

**Live-test checklist for the next session with physical access** (not run this round):

1. Deliberately let the proximity channel go stale (leave the headset undonned long enough, or
   reproduce tonight's blank-then-silence condition) with `WMR_PRESENCE_DIAG=1` on, then perform a
   genuine, deliberate don. Watch for `[stale] ... via motion` in the `User presence: WORN` commit
   line, appearing within roughly a second of the real gesture -- that is the design working exactly
   as intended. `[stale] ... via timeout` means the motion path did not trip in time and
   `MOTION_SUSTAIN_MS`/`MOTION_PRIMARY_RAD_S` likely need loosening.
2. Repeat several times to build a real distribution of how long a genuine "run" lasts and how close
   to `0.10 rad/s` it tends to hover, specifically to settle whether the 0.104 rad/s peak from
   tonight is typical or an outlier -- use this to retune `MOTION_SUSTAIN_MS`/`MOTION_GAP_MS` if
   needed.
3. With the headset genuinely worn and the channel stale (i.e. presence committed via the new rescue
   path), sit still for an extended period (watching static content) and confirm presence stays
   committed WORN throughout -- this is the specific regression case 2's "hold, don't force" design
   exists to prevent, and it deserves a direct live check, not just a code-reading argument.
4. If a live test ever shows a genuine mid-worn doff getting stuck (proximity never reports it,
   headset physically removed but presence stays committed WORN), revisit the DOFF-direction decision
   above with that evidence in hand -- explicitly deferred here, not ruled out forever.

Committed on `~/vr/monado` (branch `lab-full`, remote `wintch` NOT pushed): `510a6751c` ("wmr:
promote IMU motion to an independent primary WORN signal, not just a candidate corroborator"),
touching `wmr_hmd.c`/`wmr_hmd.h`.

## 2026-09-06/07 (later still) -- bisected + root-caused: auto-standby's real screen-off action kills the DRM lease (VK_ERROR_UNKNOWN), fixed with a default-off kill switch

Separate task, same night: a reproducible bug found live during tonight's presence work --
`vk_swapchain_present: VK_ERROR_UNKNOWN` immediately followed by `_lease_finished: Lease has been
closed`, within ~5s of `hello_xr` connecting and `BEGIN_SESSION` logging, on every launch,
surviving a full `jack-in-wayland.sh down`+`up` cycle and even a full OS reboot of `iashur`. Once it
fires, the DRM lease never recovers for the rest of the session -- the companion HID channel keeps
working fine (identification reads succeed, the HP logo LED lights on a manual
`scripts/panel.py activate`), but no real video content ever returns to the panel. Framed explicitly
as headless-reproducible (no wearer needed) and NOT requiring excessive iteration -- confirmed true;
this reproduced 100% of the time, every single test, at every commit from `754beed30` onward,
regardless of which fix was tried.

### Verifying the brief instead of trusting it

`git log --oneline -15 lab-full` confirmed the exact commit list/order the task described. Before
touching anything, found a leftover live session already running (`monado-service` PID 3464, started
22:59:47, `hello_xr` PID 4375) at then-current HEAD `510a6751c` -- its `jack-in-wayland.log` already
showed the exact bug (`BEGIN_SESSION` at line 477, `VK_ERROR_UNKNOWN`/`Lease has been closed` at
lines 484-489), a free, real data point confirming HEAD reproduces before any deliberate test was
even run. Torn down cleanly (`jack-in-wayland.sh down`, confirmed no stray processes) before starting
the actual bisection.

### Bisection: not what the brief expected

The task's brief treated `911ef3c56` as "very likely clean," live-validated earlier tonight by the
human operator ("todo negro" -- full blank/restore cycles, real video before/after, multiple times).
Built and tested it anyway, per the task's own instruction not to assume. **It reproduced the bug**,
identically to HEAD -- `BEGIN_SESSION` at the point the panel was already `screen_off_by_presence=1`
from a pre-connect auto-standby blank, followed within one log burst by `VK_ERROR_UNKNOWN` +
`Lease has been closed`. This directly contradicted the brief's inherited assumption, so the
bisection had to go further back than the three-point plan it suggested.

Walked back to `c44ba4a23` (`wmr: fix presence auto-standby RESTORE never firing`, the commit
immediately before all of tonight's "5 commits" the brief listed) -- full rebuild, full
`down`+`up`+`play360` cycle. **Clean.** The panel blanked mid-session (client already connected,
`BEGIN_SESSION` already fully established, ~36s into the session per the heartbeat), reasserted
periodically (`presence auto-standby: reassert took 370.9 ms`, same duration as every other commit),
and the session kept running with zero `VK_ERROR_UNKNOWN`, zero lease loss, for the rest of the test.

Bisected the middle: checked out `754beed30` (`wmr: run presence decision on the read thread, not
update_inputs` -- the very first of the "5 commits," and the one that moved the entire
debounce/commit/blank/restore/reassert decision off the client-gated `wmr_hmd_update_inputs()` onto
the always-on `wmr_run_thread`). Full rebuild, full test: **reproduced**, same signature as HEAD,
`BEGIN_SESSION` landing on an already-blanked panel, `VK_ERROR_UNKNOWN` + lease-closed within one log
burst. **`754beed30` is the commit that introduced the bug**, confirmed by direct rebuild+test at
both it and its parent, not inferred from the diff alone.

The mechanical reason this specific commit opened the door: before it, the NOT-WORN timer (and
therefore auto-standby's first-ever blank) could only advance from inside `wmr_hmd_update_inputs()`,
which the OpenXR runtime only calls once a client has an active, frame-synced session -- so a blank
could never happen before a client's first real content. After it, the same decision runs
unconditionally on `wmr_run_thread` starting at driver init, so the 15s NOT-WORN countdown can (and,
with `hello_xr` needing ~15-20s to load an 8K test video and connect, reliably does) complete before
any client exists at all.

### Chasing the wrong mechanism, twice, before finding the right one

Read `754beed30`'s diff and the surrounding compositor code before proposing anything, per the task's
own instruction to reason concretely rather than guess.

**First attempt (insufficient): gate the first-ever blank on a client having connected.** Added
`wh->presence.client_update_inputs_seen`, set by `wmr_hmd_update_inputs()` (only ever called from
`oxr_session.c`'s two call sites, both requiring a real OpenXR client), checked before allowing
auto-standby's blank action. Rebuilt, tested: the blank now landed ~1-2s AFTER `BEGIN_SESSION`
instead of before it -- but **still crashed**. Root cause of the miss, found by reading
`oxr_session.c` directly: one of the two `xrt_device_update_inputs()` call sites runs synchronously
*inside* `xrBeginSession()` handling, at the exact moment `compositor_begin_session()` fires -- i.e.
the gate's own trigger IS the vulnerable moment, not something safely earlier than it. Reverted.

**Second attempt (also insufficient): stop the ~370ms blocking HID I/O from holding `presence_lock`
across a cross-thread contention window.** Read `wmr_hmd_presence_tick()` in full: the reassert/
screen-off HID transaction (`wmr_hmd_reassert_reverb_fresh_fd`/`wmr_hmd_screen_off_reverb_fresh_fd`,
each ~370ms -- an initial 300ms sleep plus a 4-iteration handshake loop) ran with `presence_lock`
held for the whole call, and `wmr_hmd_update_inputs()` -- including the `xrBeginSession()` call site
above -- takes the same lock. Narrowed the critical section so `presence_lock` only ever guards the
fast debounce/commit bookkeeping, never the blocking I/O (the actual HID calls moved to run after
`os_mutex_unlock()`, gated by locally-decided `need_restore`/`need_blank`/`need_periodic_poke`
booleans). Rebuilt, tested with the default 15s threshold: **still crashed**, blank landing before
`BEGIN_SESSION` again.

Reasoned further: even unlocked, the HID I/O still ran directly on `wmr_run_thread` -- the same
always-on thread that also does `control_read_packets`/`hololens_sensors_read_packets` every
iteration, i.e. the sole source of the IMU samples the compositor's pose prediction depends on every
frame. Stalling that thread for ~370ms, any time a client is actively presenting, could plausibly
desync frame timing badly enough to explain the symptom. Built a proper fix for this: a new
`wh->presence_action_lock` (trylock-guarded, so at most one action is ever in flight) plus a
short-lived detached thread (`wmr_hmd_presence_dispatch_action()` /
`wmr_hmd_presence_action_thread()`) that performs the actual blocking HID I/O completely off
`wmr_run_thread`, with a proper join-as-barrier in `wmr_hmd_destroy()` (taken right after
`os_thread_helper_destroy(&wh->oth)` stops+joins the read thread, guaranteeing no new dispatch can
race it, then blocking until any last in-flight action thread releases the lock before `wh` is
freed). Rebuilt, tested at the default 15s threshold: **still crashed**, identical signature.

To rule out "maybe it just needs more elapsed time to be safe" as a residual variable, ran the
fully-thread-dispatched build with `WMR_USER_PRESENCE_SCREENOFF_MS=90000` -- letting a real client
render successfully, uninterrupted, for 55+ established seconds before the very first blank ever
fired. **Still crashed**, same signature, the instant the delayed blank landed. This ruled out both
"before vs. after first connect" ordering and "needs a warm-up period" as the operative variable.

**The isolating experiment that found it.** Every prior test's blank action was immediately followed
by a full reassert-then-reblank cascade (the blank transition resets `last_reassert_ns` to 0, making
the periodic keep-alive poke immediately due) -- a confound that hadn't been isolated. Reran with
`WMR_PRESENCE_RESTORE_REASSERT=0` (disabling that cascade) so the tick could do *nothing but* a
single, isolated `wmr_hmd_screen_off_reverb_fresh_fd()` call, with no reassert anywhere near it.
**Still crashed** -- `BEGIN_SESSION` -> `VK_ERROR_UNKNOWN` -> `Lease has been closed`, from that one
lone screen-off, nothing else in flight. This is the direct proof: a real, effective panel screen-off
is sufficient by itself, regardless of threading, locking, or timing relative to session state.

### Reconciling with `c44ba4a23`'s clean mid-session blank

If a real screen-off always kills the lease, why was `c44ba4a23`'s blank clean? Checked what
mechanism it actually used for the BLANK direction specifically (not the RESTORE direction, which
already used fresh-fd reassert even at that commit -- confirmed via
`git log -S'wmr_hmd_reassert_reverb_fresh_fd'`, which shows that function was introduced BY
`c44ba4a23` itself). A second pickaxe search, `git log -S'wmr_hmd_screen_off_reverb_fresh_fd'`, shows
that function -- the fresh-fd screen-OFF path -- was introduced later, by `d07872fd9`. At
`c44ba4a23`, the blank action still called the old `wh->hmd_desc->screen_enable_func(wh, false)` on
the shared `wh->hid_control_dev` handle -- and this driver's own code comments (written earlier the
same day, describing why the fresh-fd paths were built at all) document that exact shared-handle
send as unreliable while a client is actively using the device: *"HID_SEND reported success, but with
a real OpenXR client actively rendering, the panel stayed fully lit with real video still visible."*
The most likely explanation: `c44ba4a23`'s mid-session blank test never actually reached the hardware
at all -- the very unreliability that later commits set out to fix was, until fixed, accidentally
masking this bug. Once `d07872fd9` made screen-off actually work reliably (fresh fd, no shared-handle
contention), it started genuinely reaching the panel -- and that is what newly exposed a pre-existing
hardware/DRM interaction nothing had ever reliably triggered before.

**This also lines up with, and is strengthened by, the USB-capture analysis earlier in this same
file** (the "genuine Windows/Oasis standby, USB-level ground truth from real captures" section
above): real Windows/Oasis standby, captured directly over USBPcap across two full test sessions,
**never sends this HID Feature-report toggle at all** -- zero `SET_REPORT`/Feature-report packets in
either capture. Windows' own standby appears to work through a categorically different, more
invasive mechanism (a full USB re-enumeration/reset), reserved for full application exit, not for
routine idle standby while content keeps running. This driver's `{0x04,0x00}`/`{0x04,0x01}` Feature
report was already flagged, independently, as having no real-Windows counterpart before this bug was
even found -- tonight's crash is a second, concrete way that same design assumption turns out not to
hold on this hardware/compositor combination.

### The disputed live-validation claim

The task's brief cited a live, wearer test at `911ef3c56` as clean ("todo negro," multiple full
blank/restore cycles, real video before and after). Given `911ef3c56` reliably reproduces the bug in
every headless test run here -- and the isolated single-screen-off test rules out timing/threading as
confounds -- this could not be reconciled with confidence. The most plausible account: a worn test
never has an unattended-boot window for the NOT-WORN timer to reach the panel's very first blank
before real content is already flowing, and the blank/restore cycles the operator observed were most
likely doff/don cycles happening well after a session was already established and steadily
presenting -- exactly the scenario this investigation could not get to fail EXCEPT via the accidental
`c44ba4a23`-era shared-handle unreliability. Recording this discrepancy explicitly rather than
silently overriding it or silently deferring to it: this session's own direct, repeated, live
rebuild+test evidence on the same physical rig is trusted here over the secondhand summary, per this
project's own standing practice of re-verifying disputed conclusions against primary sources rather
than defending or assuming either side blind. If the operator has memory of the exact conditions of
that "todo negro" test (was a game/client already rendering before the first blank in that session?),
it would be worth reconciling directly -- not done here, since the rig had to stay headless for this
task.

### The fix

Kept both interim hardening changes -- narrower `presence_lock` scope, and moving the blocking HID
I/O off `wmr_run_thread` onto its own short-lived detached thread -- since neither is the bug's cause
but both are real, independently-justified correctness/latency improvements (removing a genuine
cross-thread lock-contention hazard with `xrBeginSession()`'s handling, and no longer letting a
~370ms HID transaction starve the IMU read loop the compositor depends on every frame).

The actual fix: a new debug option, `WMR_USER_PRESENCE_BLANK_PANEL` (default OFF), gates only the
destructive action -- the real `screen_off_fresh_fd_func`/`screen_enable_func(false)` call and the
`screen_off_by_presence = true` transition that triggers it. Left at its default:

- `not_worn_since_ns` timing, the WORN/NOT-WORN debounce, and all of tonight's motion-corroboration
  work (packet confirmation, IMU motion rescue, the bounded timeout) keep running exactly as designed
  -- `presence.committed` and `XR_EXT_user_presence` stay fully correct and live.
- The panel is simply never told to physically blank, so `screen_off_by_presence` never becomes true,
  which as a direct, correct consequence means RESTORE and the periodic reassert-while-blanked poke
  never have anything to do either -- both are dead code paths only for as long as the kill switch
  stays off, not removed, so re-enabling it later needs no further code changes.
- `jack-in-wayland.sh` and `presence.conf` needed NO changes -- the new option is off by default and
  nothing in either file sets it, so the fix is live purely from the `monado` rebuild.

Recovering the DRM lease automatically after a real screen-off would need the compositor's own
lease/swapchain handling to detect the connector coming back and re-acquire, which lives outside this
driver file and was not attempted here -- flagging it as the real follow-up, not claiming it solved.

### Live validation

Full `jack-in-wayland.sh down` + `rm -f /run/user/1000/monado_comp_ipc` +
`WMR_PRESENCE_DIAG=1 jack-in-wayland.sh up` + `play360.sh -p flat -t 1800 -q .../test2.mp4`, default
settings (`presence.conf`'s `PRESENCE_ENABLE=1`/`PRESENCE_SCREENOFF_MS=15000`, no
`WMR_USER_PRESENCE_BLANK_PANEL` override). Watched past the point every prior build crashed (the
~15-20s mark) and well beyond: 2+ minutes of sustained real playback, `hello_xr`'s own frame loop
actively advancing (`DEBUGGRAB`/`DEBUGTRIGGER` controller-poll lines climbing in its stdout), zero
`VK_ERROR_UNKNOWN`, zero `Lease has been closed`, `screen_off_by_presence=0` throughout (auto-standby
correctly never blanking, as intended with the kill switch at its default). Torn down cleanly
afterward (`jack-in-wayland.sh down`, confirmed no stray `monado-service`/`hello_xr`/`play360`
processes, socket removed).

Committed on `~/vr/monado` (branch `lab-full`, remote `wintch` NOT pushed): `af290d0e3` ("wmr: fix
auto-standby blanking killing the DRM lease (VK_ERROR_UNKNOWN)"), touching `wmr_hmd.c`/`wmr_hmd.h`.

## 2026-09-07 -- CORRECTION to the section above: the reliability shift is thread placement, not fresh-fd

The section above credited `d07872fd9` ("send auto-standby's screen-off over a fresh fd too") with
making the blank action newly reliable, and treated that as why `754beed30` -- the confirmed
bisection point -- started exposing this bug. Checked this claim directly (it hadn't been, when
first written) with `git show 754beed30:src/xrt/drivers/wmr/wmr_hmd.c | grep
screen_off_fresh_fd_func`: **at `754beed30` itself, the blank action still calls the OLD
`wh->hmd_desc->screen_enable_func(wh, false)` on the shared handle** -- `d07872fd9`'s fresh-fd
screen-off function does not exist yet at that commit. Since `754beed30` was independently confirmed
(direct rebuild+test, not inferred) to reproduce the crash, the "fresh-fd made it reliable" story as
stated cannot be the mechanism, because the crash already happens one commit before fresh-fd blank
exists.

The corrected, still evidence-consistent account: the reliability shift is `754beed30`'s move of the
ENTIRE presence decision -- including the call to `screen_enable_func` for blank -- from whatever
thread invokes the client-gated `wmr_hmd_update_inputs()` onto the always-on `wmr_run_thread`. The
already-documented shared-handle unreliability (this driver's own comments: contention with
concurrent HID activity silently swallowing the command) most plausibly depended on which thread was
sending it and what else was contending for `wh->hid_lock` at that moment -- running from
`wmr_run_thread`, likely already the primary/most frequent user of `wh->hid_control_dev` for other
periodic HID traffic (`wmr_hmd_send_controller_keepalives`, `control_read_packets`), plausibly
contends far less than a client-thread-driven call racing an active session's own concurrent HID use.
This was not verified byte-for-byte (would need instrumenting `hid_lock` acquisition/wait times on
both code paths, not done here), so stated as the best-supported account given the evidence in hand,
not a fully proven mechanism -- consistent with this file's own practice of flagging where an
explanation is inferred rather than directly measured.

This does not change the bisection result (`754beed30` is still the confirmed introducing commit,
directly rebuild-tested against its parent), the root cause (a real, effective screen-off during an
active DRM lease kills it, confirmed in isolation regardless of which HID mechanism sends it), or the
fix (the `WMR_USER_PRESENCE_BLANK_PANEL` kill switch gates the action itself, not any particular
delivery mechanism) -- only the specific claim about *why* `d07872fd9` mattered, which it turns out
it does not, for this bug.

## 2026-09-07 -- first real wearer test after the lease fix: both the fix AND the motion-primary
## presence signal validate live, in the same session

Full down/up cycle on `af290d0e3` (blank-panel kill switch, default OFF) + `510a6751c` (motion as
independent primary WORN signal). Launched `jack-in-wayland.sh up 1 3dof`, then
`play360.sh -t 21600 stereo3d-pack/out/dav2_demo` (a multi-clip playlist), real wearer donned and
watched, exited cleanly via a controller button press partway through.

**Lease fix holds under a real wearer, not just headless:** `grep -c "VK_ERROR_UNKNOWN\|Lease has
been closed" jack-in-wayland.log` -> **0**. Sustained playback across multiple clip transitions
(decoder re-inits for each file in the playlist -- exactly the kind of compositor churn that used to
trip the bug), zero crashes.

**The motion-as-primary-signal design (`510a6751c`) fired live for the first time tonight,
correctly, exactly in the scenario it was built for:**
```
User presence: WORN (raw proximity sensor value 0 [stale], held 253 ms, 1 confirming packet(s),
                motion peak 0.867 rad/s, via motion)
User presence: NOT WORN (raw proximity sensor value 0 [fresh], held 1000 ms, ..., via n/a)
User presence: WORN (raw proximity sensor value 1 [fresh], held 251 ms, ..., motion peak 1.106
                rad/s, via motion)
User presence: NOT WORN (raw proximity sensor value 0 [fresh], held 1000 ms, ...)
User presence: WORN (raw proximity sensor value 1 [fresh], held 252 ms, ..., motion peak 0.860
                rad/s, via motion)
```
Two of the three WORN commits happened while the proximity byte was silent/stale -- exactly the
"proximity says nothing for 30s+" gap this design exists to cover -- and motion alone committed
WORN in ~250ms both times, matching the design's `MOTION_SUSTAIN_MS`. No noise-relight, no
multi-second hang. This is the first live evidence this design actually works, not just passes a
headless/isolated check.

**The "seemed like 60Hz" report is not a system bug -- it's the playlist's own source content.**
`dav2_demo` mixes clips at native 23.98/24/25/30/60 fps (trailers and film-sourced footage cut at
different frame rates), while Monado itself is running the panel at a fixed 90Hz the whole time
(confirmed in the same `jack-in-wayland.log`: `found display mode 4320x2160@90.00`, unchanged for
the whole session). Cutting from a 24fps clip to a 60fps clip inside the same VR session is a very
noticeable perceptual jump -- more motion-smooth, less "cinematic judder" -- easy to misread as "the
headset dropped to 60Hz" when it's actually the opposite: the panel is holding 90Hz steady and just
faithfully displaying source material that itself varies. No action needed; worth choosing a
same-framerate curated subset for any future user-facing perceptual comparison, so a framerate
question is never conflated with content variety again.

**Net effect of tonight's whole arc, end to end:** `754beed30` (harmless-looking presence-tick
relocation) silently broke DRM lease recovery -> found via headless bisection, not live testing ->
fixed by making the actually-dangerous action (`WMR_USER_PRESENCE_BLANK_PANEL`) opt-in rather than
trying to make the danger itself safe -> the whole presence-detection stack built earlier tonight
(packet debounce, motion corroboration+timeout, motion-as-primary-signal) got its first real wearer
validation in this same session, clean.
