# 94 — Demo candidate expansion: ranked list for a third/fourth booth slot

Booth today: **Aircar** (1073390, 3dof, Xbox pad) and **Dreams of Dalí** (591360, 6dof,
headset-only gaze-dwell) on an RTX 3060 Ti, 210 W max after the 2026-09-03 GPU swap
(`docs/92`). This is a search for MORE candidates at the same "platinum" bar — a flawless
first-time-guest experience — built from `docs/81`, `docs/23`, `docs/25`,
`docs/76`-`docs/80`, `docs/82`, `docs/96`, `docs/steam-library-vr-map.md`, and a live grep
of everything published since `docs/81`'s original sweep (2026-08-26). Nothing here was
worn-tested by this pass — every "ready to try" item still needs the physical validation
step listed under it, per this project's own cardinal rule (`CLAUDE.md`: a human in the
headset is the only instrument that counts).

## Reading this list: nausea-safety is the top ranking axis

The operator's refined constraint for this pass: for a VR-naive first-time guest, **any
6dof title carrying the tracking micro-adjustment is a nausea risk**, and that risk should
outweigh visual wow when ranking. The project has direct wearer evidence for the
mechanism, not just a theoretical worry — Wolfenstein: Cyberpilot's own 6dof wearer quote:
*"the headset motion still having that constant delay — or rather the vertical
readjustment — is nauseating"* (`docs/23:356`, `docs/67:22`). The measured cause is real:
SLAM anchor age spiking under CPU load lets IMU-only extrapolation run away for up to
several seconds before a fresh solve snaps the view back (`docs/23`'s T243-night sweep,
18+ titles reproduced it the same night).

**Dalí is the existing counter-example, and the reason it's an exception matters for how
this list is built.** Dalí is 6dof, yet it's already worn-approved and measured clean
(89.95/89.90/.../89.95 fps across eight 20 s windows, 0.02 % late-of-period, `docs/76`).
The difference is *what the guest does with the 6dof*: Dalí is gaze-dwell, seated, and the
guest never actively navigates — there's no stick-driven turning or locomotion to
compound the tracking micro-adjustment into vection. So the real first-timer-safety
determinant is not the raw "3dof vs. 6dof" label by itself, it's **whether the guest is
static/passive or actively steering** on top of whichever tracking mode is running. Every
candidate below is tagged accordingly:

- **first-timer safe** — static/seated/passive or 3dof-with-gamepad, no active locomotion
  demanding sustained tracking accuracy, comfort risk approaches zero.
- **experienced-only** — active 6dof navigation, sustained head-turning under SLAM load,
  or unresolved locomotion method; save for a guest who already knows they're VR-tolerant,
  don't default first-timers into it.
- **unknown, pending test** — the deciding factor (locomotion type, session pacing) is not
  yet on file; the validation step below exists specifically to resolve the tag.

GPU load is not a ranking factor for anything on this list — see "GPU headroom" below.

## GPU headroom on the 210 W card (context, not a differentiator)

Measured this session on the post-swap 3060 Ti (`docs/96` §8.1, 2026-09-03): Aircar holds
90 fps at 58 % GPU / ~10 % CPU on a 130 W cap; Dalí holds 90 fps at 72–80 % GPU on a 160 W
cap; both leave real headroom under the 210 W ceiling. The Night Cafe's one unworn grab
(`docs/80`) was 35 % GPU / 54 W. **Every candidate below is comfortably inside the power
budget on content weight alone** — the 210 W drop from the pre-swap 250 W card changes
nothing for this list. The one GPU-heavy title in the recent sweep (Cyberpilot,
unoptimized 140 % render scale) is excluded anyway for needing controllers (see below), so
it isn't a counter-example worth chasing here.

---

## Tier 1 — Ready to try (cheapest validation, best first-timer-safety odds)

### 1. In-house 360/VR180 photo/video reel — no AppID, `~/vr/play360.sh`
- **first-timer safe.**
- **Platinum rationale**: zero controllers, zero locomotion, zero SLAM — the guest sits or
  stands still and looks around a photo or a VR180 video. Visual wow is proven: VR180
  stereo 3D was worn-verified "really good" back on 2026-08-04 (`docs/02`), and the 90 Hz
  panel has been confirmed flicker-free project-wide since `docs/19`. No reading required,
  no game rules to explain, session length is fully operator-controlled (pick a 2-4 minute
  clip). This is the safest possible first-timer experience the project has.
- **3dof vs. 6dof**: neither — it's a native OpenXR client (`hello_xr`), not a Steam
  title, with no tracking dependency of any kind beyond head rotation.
- **GPU-load feasibility**: proven at 8K60 with zero-copy NVDEC→Vulkan (`docs/25`); not a
  concern on this card.
- **What changed since `docs/81`**: at the time of that doc, video playback in this player
  was flatly silent (`docs/81`'s stated "real gap" against the audio-impact requirement).
  **That gap has since been closed in code** — patch `0021` (landed 2026-08-26) implements
  `HELLO_XR_AUDIO=1`: decode → PipeWire → A/V sync, described in `docs/02` as "built and
  linking clean." **But it has never been verified with the headset on** — `docs/02`'s own
  words: "the decode/resample/sync path itself and every in-headset behavior (audible, A/V
  sync over a loop, pause, clean quit) still needs a human with the headset on before it
  counts as verified." No other doc since 2026-08-26 records that worn pass — this is a
  real, currently-open gap, not a solved one.
- **Exact validation step needed**: (1) curate the strongest 2-4 minute VR180/360 clip and
  one striking 360 photo into the demo reel; (2) worn pass with `HELLO_XR_AUDIO=1` set —
  confirm audio is audible, stays in sync across a loop seam, and that pause/quit behave
  cleanly; (3) re-confirm flicker-free 90 Hz and clean stereo depth with the *specific*
  content picked for the booth (the 2026-08-04 verdict used different test media). If the
  audio pass fails or runs out of time before the show, this is still bookable
  video-only/photo-only — it just won't meet the "audio impact matters" bar until fixed.

### 2. The Night Cafe — Van Gogh tribute, appid 482390, free
- **unknown, pending test** (the one open question is exactly the nausea-determining one).
- **Platinum rationale**: thematically the closest thing to "a second Dalí" — a real,
  well-reviewed (95 % positive, 271 reviews) art-walkthrough piece, free, small (449 MB).
- **3dof vs. 6dof**: **the launch-side blocker that made this untestable is now fixed.**
  `docs/81` (2026-08-26) had it as untested; a 2026-08-27 pass found it was dying in the
  OpenXR loader from a missing `XR_RUNTIME_JSON` env var, not an app bug (`docs/82` §6). On
  2026-08-29 that env var was wired into the launcher's `GAME_ENV` and the title reached a
  **real, unworn FOCUSED session**: 89 fps delivered, clean, one harmless
  `IVRSettings_001` probe and nothing else (`docs/80`, "17:04 — The Night Cafe reaches
  Monado"). It has still never been worn. Its store listing says "Tracked Controller
  Support" (grab/point, standing/room-scale) — **not gaze-only like Dalí** — which is the
  open tension `docs/81` already flagged: if it needs real point-and-grab or smooth-stick
  locomotion to move through the gallery, that's both a "no controllers" violation and a
  first-timer nausea risk (vection from stick-driven movement); if it's mostly
  look-and-one-trigger-per-room, it's a strong platinum fit.
- **GPU-load feasibility**: trivial — 35 % GPU / 54 W on the one grab so far (`docs/80`,
  `docs/96`), enormous headroom on this card.
- **Exact validation step needed**: worn 3dof pass exactly as `docs/81` originally
  specified: `VR_LAUNCH_APPID=482390 ~/vr/vr-launcher.py 1 3dof`, now that the launch-env
  fix is in place. Watch for: does progress require point/grab, or is it walk +
  at-most-one-simple-trigger-per-transition; is locomotion teleport/room-scale (comfort-OK)
  or continuous-stick (vection risk); does the wearer report any queasiness at all. Any
  answer that lands on "needs precision grabbing or continuous-stick movement" moves this
  to experienced-only or drops it; "walk + occasional trigger, no stick locomotion" makes
  it a strong #2 slot alongside Dalí.

---

## Tier 2 — Needs work (real gaps, plausible path to platinum)

### 3. I Expect You To Die — appid 587430, installed, never launched on this stack
- **unknown, pending test** — genre argues first-timer safe, but nothing is measured.
- **Platinum rationale**: this is a genuinely different shape than everything else on this
  list — a seated, single-room escape-puzzle (Schell Games), which by design has no
  locomotion at all: the whole experience happens from one fixed seat, manipulating
  objects with the hands. That's about as nausea-proof as an interactive (not passive)
  title gets. Real caveat against the "no reading required" guest-friendliness rule: it's
  a puzzle game — guests may need a beat to read/understand objectives, which cuts against
  the "no reading required" bar more than any other candidate here. Worth a direct check
  of whether the opening puzzle is legible without instructions before trusting it as a
  guest-facing demo.
- **3dof vs. 6dof**: unknown — never tested on this stack at all. Genre (seated,
  hands-in-a-fixed-volume) suggests it may tolerate 3dof-with-controllers reasonably well
  (no positional walking needed), but this is inference, not measurement.
- **GPU-load feasibility**: unmeasured. Nothing about the genre suggests it's heavy.
- **Exact validation step needed**: first-ever launch and worn test, 3dof first per this
  project's own standing strategy for new titles (cheapest, avoids the SLAM
  micro-adjustment entirely). Confirm: (a) it renders and responds to controller input at
  all on this stack (zero prior data), (b) whether hand interactions are simple enough for
  a first-timer with ~30 seconds of instruction, (c) whether the opening minute is legible
  without reading a tutorial, (d) session length for a single puzzle/vignette (the full
  game is long; a booth session needs a curated stopping point).

### 4. International Space Station Tour VR — appid 797200, owned, NOT currently installed
- **first-timer safe if the 3dof-only retest holds** — currently unknown, pending test.
- **Platinum rationale**: this was the single cleanest verdict of the entire original
  sweep — "zero warnings, FOCUSED, real head tracking confirmed live" (`docs/23`,
  T073/T075) — and it's already flagged in `~/vr/vr-launcher.py`'s `NO_HANDS_TITLES` set
  alongside Aircar, Dalí, and the benchmark tool: it does not render hands and its title
  profile turns constellation OFF by design, the exact same "avoid the SLAM/constellation
  starvation bug" strategy behind Aircar's approved config (`docs/81`). Session is a
  guided/gaze tour of the ISS — no reading, no controls to learn, strong visual wow (real
  8K content).
- **3dof vs. 6dof**: this is the key open question, and it cuts the OTHER way from most of
  this doc's worry. Its later T243-night 6dof+constellation retest was genuinely broken —
  the worst instance of the whole "flying away" family that night, `monado-service`
  measured at **519 % CPU** (over 5 of 12 threads), anchor age spiking to 2038-2685 ms
  (`docs/23`). But that failure mode is specifically the SLAM+constellation combination
  fighting the CPU for cycles on top of 8K decode — not something that should exist at all
  in the title's own **3dof-only** profile, which predates 6dof entirely and was clean.
  This is exactly the "prefer 3dof" case the operator's constraint describes: the same
  title has a genuinely good verdict on the config this doc is supposed to favor, and a
  genuinely bad one on the config it's supposed to avoid — and nobody has re-run the good
  config since the 6dof work started.
- **GPU-load feasibility**: 8K decode is proven cheap on this card specifically — the dev
  rig hardware-decodes 8K60 AV1 at ~2x real time (`docs/90`, `docs/92`); the 519 % CPU
  number that broke it was Basalt/constellation contention, not GPU or decode load.
  Expect this to be a non-issue once constellation is off.
- **Exact validation step needed**: reinstall (owned, not currently on disk — heaviest
  content ever measured on this rig, budget real download time), then a **fresh 3dof-only
  worn retest** using its existing `NO_HANDS_TITLES` profile, on the current post-GPU-swap
  card and post-T244-pacer-fix stack (neither of which existed when the clean T073/T075
  verdict was recorded). Confirm the clean verdict survives on current software before
  trusting it for a guest.

---

## Tier 3 — Lower priority / real friction (keep on file, don't chase before the above)

### 5. Cosmic Flow: A Relaxing VR Experience — appid 1267950, owned, NOT installed
- **unknown, pending test.**
- **Platinum rationale**: name and genre fit "light experience" better than almost
  anything else in the catalog (`docs/81`), confirmed working with real 3D and zero late
  frames once warm, historically (T073/T077).
- **3dof vs. 6dof**: untested since 6dof/constellation entered the picture; input method
  (hands-optional or not) was never independently verified even in the original pass —
  lower confidence than #4 above.
- **GPU-load feasibility**: unmeasured, but nothing suggests it's heavy.
- **Exact validation step needed**: reinstall, then a first pass specifically to determine
  whether it needs positional hand tracking or works headset/gamepad-only, before any
  comfort verdict is possible.

### 6. The Scream — appid 1097120, $3.99, not owned/not installed
- **experienced-only until proven otherwise — zero on-rig data.**
- **Platinum rationale**: found in desk research (`docs/77`, 2026-08-26), Munch-themed
  documentary-style piece, three chapters, framed as a passive walkthrough rather than a
  game — plausibly low input load, but that's a store-page inference, never checked.
- **3dof vs. 6dof / GPU feasibility**: completely unknown — never purchased, installed, or
  launched on this stack.
- **Exact validation step needed**: this is a paid title with zero project history; only
  worth the $3.99 + install time if Tier 1/2 candidates don't fill the slot. Not
  recommended to spend booth-prep time on before the free candidates above are resolved.

---

## Not suitable — known-broken or controller-required, excluded from ranking

- **Anne Frank House VR (2877690)** — `docs/81` framed this as merely untested, but a
  2026-08-27 pass found something more specific and worse: it **does** reach a real Monado
  session, then **abandons it after exactly one capability probe and never retries** — a
  named, engine-side Unity XR-plugin give-up matching Valve's own tracked upstream issues
  (`unity-xr-plugin` #97/#111, `docs/82` §6). This supersedes `docs/81`'s more hopeful
  "never launched" framing. **This is a known-broken verdict, not a to-do** — nothing on
  this project's side can fix an upstream engine bug before a show. Also carries the
  independent fit problems `docs/81` already named: ~25-minute narrated length (long for
  short guest sessions) and touch-object controller dependency (not gaze-only).
- **Wolfenstein: Cyberpilot (1056970)** — needs motion controllers by design, and is the
  title that produced this project's clearest first-person nausea quote for the 6dof
  micro-adjustment ("the vertical readjustment is nauseating," `docs/23:356`). Explicitly
  excluded from the current power/lineup plan already (`docs/96`: "Excluded from the
  lineup (needs controllers)"). Not reconsidered here.
- **NVIDIA VR Funhouse (468700)** — even under a clean launch, this is a
  precision-grab minigame collection — the most controller-dependent, precision-sensitive
  genre in the catalog, directly against the no-controllers preference. `docs/23`'s own
  verdict: "poor fit regardless of outcome."
- **Hellblade: Senua's Sacrifice VR Edition (747350)** — explicitly a motion-controller
  title (`docs/76`, `docs/79`), conflicting with the no-controllers preference regardless
  of how well it runs; also still has an open Proton-prefix blocker (`docs/76`, "still not
  done" list) as of the most recent status.
- **DOOM VFR (650000)** — known broken: ~9 second early-exit, possibly the unfixed
  `pop_pose()` segfault (`docs/06`, `docs/82` §3-4). Never delivers a frame.
- **Half-Life: Alyx (546560)** — known broken on this stack: loader panic was fixed, but it
  still delivers zero frames, cause unknown (`docs/82` §4). AAA, controller-driven by
  design regardless.
- **Vertical Shift (1807480)** — flagged only as a footnote, not ranked: it's one of the
  titles that came back genuinely clean under the T244 app-pacer fix (66-77 fps, wearer
  "well positioned, no headset drift," `docs/23`), but it's a climbing/traversal genre
  (active locomotion, height exposure) with controller visibility "never confirmed in any
  session — inconclusive." Both the genre (height/traversal) and the unresolved input
  question argue against spending validation time here before the Tier 1/2 list above is
  resolved.

---

## Summary table

| # | Title | AppID | Tier | First-timer tag | Input | Validation step |
|---|---|---|---|---|---|---|
| 1 | In-house 360/VR180 reel | — | Ready | first-timer safe | none | curate reel + worn audio pass |
| 2 | The Night Cafe | 482390 | Ready | unknown, pending test | controller (type TBD) | worn 3dof test, watch locomotion type |
| 3 | I Expect You To Die | 587430 | Needs work | unknown, pending test | controller, seated | first-ever launch + worn 3dof test |
| 4 | ISS Tour VR | 797200 | Needs work | unknown, pending test | none (NO_HANDS) | reinstall + fresh 3dof-only retest |
| 5 | Cosmic Flow | 1267950 | Lower priority | unknown, pending test | unverified | reinstall + input-method check |
| 6 | The Scream | 1097120 | Lower priority | experienced-only (no data) | controller | purchase + first test, only if 1-4 stall |
| — | Anne Frank House VR | 2877690 | Not suitable | — | — | known-broken, engine-side, not fixable pre-show |
| — | Cyberpilot | 1056970 | Not suitable | experienced-only | controllers | already excluded (`docs/96`) |
| — | NVIDIA VR Funhouse | 468700 | Not suitable | experienced-only | controllers | poor fit regardless of outcome |
| — | Hellblade | 747350 | Not suitable | experienced-only | controllers | prefix broken + controller conflict |
| — | DOOM VFR | 650000 | Not suitable | — | — | known-broken |
| — | Half-Life: Alyx | 546560 | Not suitable | — | — | known-broken |
| — | Vertical Shift | 1807480 | Footnote only | experienced-only (height/traversal) | controller, unclear | not recommended before 1-4 |
