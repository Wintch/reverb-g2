# 100 — Dreams of Dalí 6dof "redraw": does the Aircar recipe transfer, and is the new GPU a separate bottleneck

> **Answered 2026-09-07 — see [113](113-dali-redraw-is-pose-staleness.md).** The redraw described here is pose staleness, not rendering: Basalt's optical flow was 200/200 frames over the 33 ms budget and `age_out_ms` compounded to a p50 of 100.8 ms. Detection density 30/3 → 30/2 brings it to 36.7 ms, and render scale 100 → 85 restores the fps lost to the 210 W cap. Both shipped in the booth profile.

Trigger (2026-09-05): right after today's DP/lease bug got fixed and Dalí rendered correctly
again, the wearer's verdict (translated) was *"Dalí's perfect. Of course, you can tell it doesn't
render as smoothly as 3dof — the already-known redraw thing — investigate if we can make progress
there too."* He is naming the same symptom class `docs/80` built around Aircar and asking whether
it now applies to Dalí. **Also new since he said that**: a second, live worn sample from the same
session showed a sustained ~75 fps read and an average ~4.9 ms lateness against the 11.11 ms/90 Hz
period over the last 50 `Delivered frame` lines — not occasional spikes, a systematic slip. This
doc reasons through both possible causes side by side rather than assuming it is the prediction
recipe, per the task's own instruction, and lands on two independent, cheap, unvalidated test
buttons instead of a profile change.

## 1. What `docs/80`'s recipe actually is, and why its numbers were chosen for Aircar

The winning Aircar/Cyberpilot combination (`TITLE_PROFILES["1073390"]` /
`TITLE_PROFILES["1056970"]` in `vr-launcher.py`) is:

```
SLAM_PREDICTION_TYPE=2            # gyro-orientation prediction (responsive turns, no NONE-style lag)
SLAM_PRED_FREEZE_POSITION=1       # holds position at the last SLAM anchor instead of extrapolating
                                   # linear_velocity across the ~90-190ms anchor age
SLAM_PRED_NECK_ARM_MM=<value>     # swings the frozen eye along the neck-pivot arc as orientation
                                   # predicts forward -- fixes the orientation/position timestamp split
SLAM_CORRECTION_SPREAD_MS=<value> # spreads each per-anchor position correction over N ms so the
                                   # periodic re-anchor snap ("se acomoda") doesn't feel like a jump
```

Every numeric value was reached by a **live wearer A/B on Aircar specifically**, not derived from
theory:

- **Neck-arm 150→100mm** (`docs/80` "the 10-minute wearer slot", 2026-08-29 06:14-06:37): swept
  0/100/150/200mm live. Order: `0 ≈ 100 < 150 < 200` for felt drift on fast yaw; 100 chosen over 0
  only because 0 showed near-field cockpit jitter looking at the dashboard up close — a
  *seated-cockpit-specific* tie-breaker, not something that generalizes.
- **Spread 50→25ms, Aircar only** (`docs/80`, 2026-08-27 evening, "Variant F"): confirmed in-headset
  as "bastante solido" and explicitly noted as **Aircar-only** — Cyberpilot's own profile still
  carries `SLAM_CORRECTION_SPREAD_MS=50`, with the comment "Aircar's 25 was only validated worn on
  Aircar, not on this title." This is direct, in-repo evidence that even the two titles that
  *already* share this recipe don't share every value — it is tuned per title, not copy-pasted.
- Aircar additionally now carries a Basalt-backend variant (`SLAM_CONFIG=P2.toml`, recall on +
  marg-lost off + tighter triangulation/keyframes + `SLAM_CORRECTION_AVG_N=3` +
  `WMR_CAM_TS_MID_EXPOSURE=1` + `VIT_QUEUE_DEPTH=1`) layered on top of the four knobs above. This is
  a *separate, deeper* axis (Basalt's own landmark/recall behavior) from the four Monado-side
  prediction knobs and matters below.

## 2. Would the same numeric values transfer to Dalí? Reasoning, not assumption

Dalí is standing, gaze-dwell, headset-only (no controllers, no gamepad-driven cockpit yaw) —
100% of its head motion is real physical rotation, unlike Aircar where some apparent "turning" can
come from stick input while the head stays still. Point by point:

- **`SLAM_PREDICTION_TYPE=2` / `FREEZE_POSITION=1`**: these are general VIO-anchor-age mitigations
  (gyro is fast and cheap; freezing position avoids extrapolating noisy accel-integrated velocity
  across the SLAM latency gap). Nothing about the mechanism is seated-cockpit-specific — if
  anything, a standing gaze-dwell title with *only* real head rotation should see the *same or
  more* benefit from responsive orientation prediction than Aircar, since Aircar's recipe was
  partly masking a mixed input signal.
- **`SLAM_PRED_NECK_ARM_MM`**: this models the physical lever arm from the neck pivot to the
  visor's IMU/eye position. That anatomical distance does not change between sitting and standing
  — a starting value of 100mm (Aircar's tuned number) is a reasonable initial guess, not a
  seated-only artifact. It is still a per-wearer, per-title guess until swept live on Dalí, exactly
  as Aircar's own 0/100/150/200 sweep was necessary before landing on 100.
- **`SLAM_CORRECTION_SPREAD_MS`**: this is the one value the project's own data says is genuinely
  title-sensitive — the Aircar/Cyberpilot split above is direct proof. **Do not import Aircar's 25ms.**
  Cyberpilot's untested-but-plausible 50ms is the safer starting point for a title that has never
  run any of these knobs before.

**Conclusion of this section**: the *mechanism* (SLAM anchor-age dead-reckoning snap, no
gravity-anchored yaw correction) applies to Dalí exactly as much as to Aircar — arguably more,
since Dalí's head motion is 100% real rotation. The specific *numbers* need their own sweep, but a
starting point of `TYPE=2 + FREEZE=1 + NECK_ARM=100mm + SPREAD=50ms` is a defensible, conservative
first guess, not a blind copy.

## 3. The P2 gate test on Dalí already ran — but it tested a DIFFERENT thing, and failed for a different reason

`docs/80` already has a Dalí + "P2" worn gate (2026-08-29, both a dark-room run that was invalidated
and a later lit-room run that failed): *"saltos de 6.6 m a los 30 s y 38.6 m a los 107 s ->
compuerta NO pasada, P2 queda solo en Aircar, Dali sigue en base."* It would be easy to read this as
"the recipe was already tried on Dalí and rejected" — **that reading is wrong.** "P2" there means
`SLAM_CONFIG=~/vr/basalt-variants/P2.toml`, the Basalt-backend landmark/recall variant (section 1
above) — it does **not** set any of `SLAM_PREDICTION_TYPE` / `SLAM_PRED_FREEZE_POSITION` /
`SLAM_PRED_NECK_ARM_MM` / `SLAM_CORRECTION_SPREAD_MS`. Dalí's profile at gate time (and today)
carries **none** of those four knobs — `docs/80`'s own words: *"Dalí is the only approved title
whose profile carries no head-prediction knob."* The P2 gate failure is real and is about Basalt's
landmark/recall backend starving on a standing wearer (the same doc's own numbers: landmarks
collapse under fast yaw, worse than a seated cockpit) — a legitimate reason to leave the *backend*
config alone for Dalí, but it says nothing about whether the four Monado-side prediction knobs
would help. **That combination has never been tried on Dalí.**

## 4. The GPU-power-headroom angle — likely the dominant factor RIGHT NOW

Two independent facts point the same direction, and one of them is worn/live data collected after
this doc's trigger message, so it should be weighted more heavily than the older approval numbers:

- **The 2026-09-03 GPU swap dropped the card's max draw 250W → 210W** (`docs/92`; confirmed via
  `nvidia-smi -q -d POWER`). Dalí's existing "approved" sign-off (`DEMO_LAUNCHES` note,
  2026-08-29 15:15, on the OLD 250W card) explicitly needed the **full** 250W to hold 89-90fps in
  6/8 twenty-second windows, with dips to 79/85fps in the other 2/8 specifically when the GPU hit
  the 250W cap at 91-96% utilization — i.e. it was already at the edge of the old card's headroom
  before the swap.
- **A quick unworn sample today** (menu/idle content, ~1 min, before the wearer test) already
  showed ~200W of the new 210W cap (95%), 78% GPU util, ~1% of frames >11ms late (a full dropped
  frame at 90Hz) and ~4% >5ms late — worse than the old card's own baseline dip rate, on IDLE
  content.
- **A live worn sample from the actual wearer session today** (collected after this investigation
  started) is stronger evidence than either of the above: the wearer reported seeing ~75fps
  in-headset, and the last 50 `Delivered frame` lines in `jack-in-wayland.log` averaged ~4.9ms late
  against the 11.11ms (90Hz) period — a **sustained**, not occasional, slip. This is a bigger,
  more consistent gap than the old card's worst historical dip rate (2/8 windows at 79/85fps) ever
  showed, under real worn load rather than idle content.

**This is very likely the dominant contributor to today's "doesn't render as smoothly" complaint**,
separate from and probably larger than any SLAM-prediction-knob gap — a sustained ~44% of the frame
budget being eaten late is a compositor-side pacing problem, not a subtle tracking-latency "redraw"
of the kind `docs/80` characterizes (which shows up as occasional catch-up snaps on fast turns, not
a continuous fps deficit).

### The separate, already-known, GPU-independent ~60fps app-cap (do not confuse with the above)

`docs/96` §13 (measured 2026-09-03, same day as the GPU swap) already documents that **Dalí's own
game engine renders at ~60fps**, and Monado's compositor cleanly reprojects that to a locked 90Hz
panel refresh (0 late frames of 2700 in that specific measurement, ~79% GPU/203W — real headroom
*in that sample*). Pushing render-scale supersampling above 100% on Dalí was explicitly measured to
buy nothing (you can't exceed the app's own 60fps submission rate), and even tipped an earlier
"Dalí shows 60" alarm when supersampling was left at Monado's 140% default. **This app-side 60fps
cap + reprojection is a real, permanent, GPU-independent characteristic and is likely part of why
Dalí "doesn't feel as smooth as 3dof" even when the compositor itself is clean** — but it is a
*different* phenomenon from today's live sustained-lateness reading, which is a compositor-side
pacing problem the 09-03 measurement did not show. Both can be true at once and need to be told
apart before spending effort on either.

### What this means for render scale

`docs/96` only ever tested scale **above** 100% for Dalí (and only for Aircar's "adamantium" tier).
Nobody has tried **below** 100% for Dalí. Given the new, lower power ceiling and today's live
sustained-lateness reading, testing 85% is cheap, reversible, zero-code, and directly answers
whether compositor-side cost (not the app's own 60fps cap, which no scale change touches) is what's
eating the frame budget under real worn load.

## 5. Recommendation

Two independent, low-risk things to try, **in this order**, each isolated from the other so a worn
A/B can tell them apart — don't combine them in one test:

1. **First: `test-591360-scale85`** (new dashboard button, `XRT_COMPOSITOR_SCALE_PERCENTAGE=85`,
   nothing else changed from the approved profile). This targets the newly-surfaced,
   worn-confirmed sustained lateness under the lower 210W ceiling — likely the bigger and more
   recent problem. Measure with `frame-pacing.sh` under actual worn load (not idle/menu), compare
   late-frame % against the approved scale-100 button.
2. **Then, separately: `test-591360-predict`** (new dashboard button,
   `SLAM_PREDICTION_TYPE=2` + `SLAM_PRED_FREEZE_POSITION=1` + `SLAM_PRED_NECK_ARM_MM=100` +
   `SLAM_CORRECTION_SPREAD_MS=50`, layered as env overrides on Dalí's already-approved anchor +
   quat-check base). This targets the SLAM-anchor-age "redraw" mechanism itself, which has never
   actually been tested on Dalí (see §3 — the earlier P2 gate tested something else). Expect this
   to help the occasional fast-turn snap, not the sustained fps deficit from item 1 — don't expect
   it to fix a systemic ~75fps read by itself.

Both are staged as new `ACTIONS` entries in `scripts/status-dashboard.py` (labelled 🧪, status
`"testing"`, explicitly marked unvalidated) — the approved `demo-`/`DEMO_LAUNCHES` button for Dalí
and `TITLE_PROFILES["591360"]` in `vr-launcher.py` were **not** touched, so the booth's known-good
configuration is unaffected until a real wearer signs off on either test.

### Concrete next-worn-test steps (model: `docs/80`'s Aircar A/B)

1. Confirm light (`light-preflight.sh`) — Dalí's raw/no-anchor-fallback history is entangled with
   dark-room VIO problems that are NOT this investigation; don't let a dark room contaminate the
   read.
2. Run the **approved** Dalí button first as today's baseline-with-the-new-GPU (it hasn't been
   re-measured worn since the swap) — note fps read and, if possible, grep
   `jack-in-wayland.log` for `Delivered frame` lateness the same way today's live sample was read.
3. Run `test-591360-scale85`, same wearer, same routine (look around, lean in, slow and fast
   turns). Ask: does the fps read change? Does the log's average lateness drop? Does anything look
   visibly softer (acceptable, since the app is engine-capped at 60fps anyway — sharpness above
   that is not being spent regardless of scale)?
4. If (3) doesn't move the lateness number, scale is not the lever — the 210W ceiling is being hit
   for a reason resolution doesn't fix (thermal/clock), and that's a separate, bigger investigation
   (not in scope here).
5. Separately, run `test-591360-predict` against the same baseline. Ask the wearer specifically
   about the fast-turn "redraw"/"se acomoda" feeling (not just "does it feel smooth overall" —
   `docs/80`'s Aircar sessions show wearers conflate general fps softness with the anchor-snap
   feeling unless asked pointedly). If it helps, sweep `SLAM_PRED_NECK_ARM_MM` the same way Aircar's
   was swept (0/100/150/200) before promoting anything into `TITLE_PROFILES["591360"]`.
6. Only promote either test into the approved profile after its own dedicated worn sign-off,
   following this project's own rule (`CLAUDE.md`: a human in the headset is the only instrument
   that counts) — do not combine both changes into one promotion, since that would make a future
   regression impossible to attribute.

## 2026-09-05 live worn session, same day — honest re-measurement + window-focus question

Ran the two staged tests live, worn, right after this doc's agent-work landed.

**Honest `app-fps.sh` comparison (the correct instrument, not the rough avg-lateness estimate used
earlier today)** — 5×20s windows each, same idle/menu content, same session:

- **Scale 100% (approved baseline, re-run for a fair same-day comparison)**: 53.95 (still settling
  from load), then 89.00 / 88.65 / 88.85 / 89.20 — steady-state **~89 fps**, matching this doc's
  earlier concern-raising sample far less than expected.
- **Scale 85% (`test-591360-scale85`)**: 89.30 / 88.75 / 89.00 / 89.20 / 89.15 — steady-state **~89
  fps**, statistically indistinguishable from 100%.

**Conclusion: render scale is NOT the lever here.** The earlier same-day alarm ("~200W/95%,
sustained ~75fps") came from a rough live estimate (average `Delivered frame` lateness across a
short sample), not from `app-fps.sh` — once measured with the project's own validated instrument,
both scales hold ~89fps steady. This directly confirms `docs/96` §8.1's own prior finding: Dalí's
fps counter can read clean while the wearer still feels roughness, because the real limit is **SLAM
prediction latency**, not GPU power/render cost. Do not trust a rough lateness-average number over
`app-fps.sh` again — this cost real back-and-forth today. The 210W-vs-250W GPU swap concern from
`docs/92` is not disproven in general, but it is NOT what's causing Dalí's felt redraw.

**`test-591360-predict` (SLAM_PREDICTION_TYPE=2 + FREEZE_POSITION=1 + NECK_ARM_MM=100 +
CORRECTION_SPREAD_MS=50), first worn run**: wearer's verdict, translated: *"feels pretty good, I
think better, but hard to confirm."* Consistent with the mechanism (a felt latency artifact, not a
counted fps drop) being genuinely subtle — `docs/80`'s own Aircar A/B needed a pointed, repeated
protocol (0 vs 100 vs 150 vs 200mm neck-arm, asked specifically about the fast-turn feeling each
time) before the wearer could commit to a verdict; one pass here is not enough to promote this.
**Next**: repeat with the same pointed-question protocol, and/or sweep neck-arm (0/100/150/200) the
same way, before promoting into `TITLE_PROFILES["591360"]`.

**Recurring DP/lease drop, second distinct instance today**: mid-comparison, a relaunch hit the same
symptom as `docs/101` (all 3 `card0-DP-*` disconnected, `monado-service` alive and still logging
`Delivered frame`) — but this time only ~20s after launch, far short of the 120000ms
`PRESENCE_SCREENOFF_MS` threshold `docs/101`'s fix already gates behind `PRESENCE_ENABLE`. So this
was **not** a recurrence of that specific bug (too soon for the timer even unpatched) — a second,
so-far-uncorrelated trigger for the same symptom class. Discriminated against the genuine hardware
DP-dead fault the same way as before (`docs/22` step 0): `hmd-connector.sh` empty, but
`panel.py activate` succeeded (valid EDID-like reads, "full activation + screen on", not "no logo
at all") and USB stayed enumerated throughout — so hardware-fault is still not indicated. Notably,
this time a plain `jack-in-wayland.sh down` (which kills `monado-service` and removes the IPC
socket) did **not** bring the connector back on its own — it took a subsequent `panel.py activate` +
a couple seconds before `DP-2` read `connected` again. Worth flagging to whoever picks up
`docs/101`'s open thread: the fix there addresses ONE known trigger (the presence-screenoff bypass);
this session shows there is at least one more, different trigger for the same lease-loss symptom,
not yet identified. Treat `docs/101`'s fix as a partial fix, not a full root cause, until this
second trigger is separately explained.

**Window-focus question (asked live, `docs/23`/`docs/75`/`status-dashboard.py`'s `guide_2` already
answer this in general)**: the wearer noticed Dalí's desktop companion window was not focused during
today's tests and asked whether that needs forcing. Per this project's own already-established,
general rule: **losing desktop window focus does NOT affect VR head-tracking/render performance**
(the HMD path renders via Monado's direct DRM lease, independent of desktop window-manager focus) —
what it does affect is **Wine's gamepad input and audio routing**, which drop when the companion
window is unfocused while head tracking keeps working fine (`status-dashboard.py`'s guide_2: "the
game's desktop window must be focused or Wine drops gamepad + audio (only head tracking keeps
working)"). Dalí has no gamepad/controller input (`WMR_CONSTELLATION_CONTROLLERS=0`, headset-only
gaze-dwell), so the gamepad half is moot for this title; if Dalí has any ambient audio, that (only)
could be at risk while unfocused. **Net: no need to force focus for today's performance
measurements** — none of today's fps numbers are invalidated by the window being unfocused. Do
force focus only if a guest ever reports missing audio on this title, per the existing guide_2
convention. (Caveat: an earlier, separate investigation for Wolfenstein: Cyberpilot floated then
**retracted** a claim that window visibility/minimizing changes fps for THAT title — see
`docs/23`'s Cyberpilot entry, "RETRACTED ~40 min later" — so this "focus only gates audio/gamepad,
not fps" rule is Dalí/general-case, already validated project-wide; it does not reopen that
retracted, title-specific claim.)

**Follow-up, same session, a bit later — CORRECTION**: this doc previously (wrongly) attributed a
"works solid, I played it a bit there" verdict here to `test-591360-predict`. Checked
`/proc/<pid>/environ` on the actually-running `monado-service` at that moment and confirmed NO
`SLAM_PREDICTION_TYPE`/`SLAM_PRED_*`/`SLAM_CORRECTION_SPREAD_MS` were set — the session running at
that point was the plain APPROVED baseline profile (`WMR_USER_PRESENCE=1` for an unrelated
presence-screenoff test, `docs/101`), not the prediction-recipe test. So that verdict is a data
point about the BASELINE profile, not `test-591360-predict` — see the next section below (the
191-reset anchor-guard finding) for what that baseline session actually looked like under the
hood. `test-591360-predict` itself still has only the one earlier, hedged verdict ("feels pretty
good, I think better, but hard to confirm") and still needs the pointed Aircar-style protocol
before promotion.
