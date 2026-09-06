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
