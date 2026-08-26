# 75 — Demo-day launch setup: Aircar, Dreams of Dalí, Hellblade

**Scope**: a concrete pre-show and per-title runbook for the three titles currently shortlisted
for the commercial-showcase presentation (2026-08-26 planning session) — chosen for their
audio impact: **Aircar** (1073390), **Dreams of Dalí** (591360), **Hellblade: Senua's Sacrifice
VR Edition** (747350). This is a launch-mechanics doc, not a new compatibility finding — it
assembles what's already on file in `CLAUDE.md`, `docs/67`, `docs/23`, and the current scripts
into one operational sequence, and states plainly what is genuinely unverified for these three
specifically. **Per this project's own rule: nothing below is "verified" just because it's
written down — only what a human has worn/heard counts.**

**Why Wayland, specifically (2026-08-26 clarification)**: all three launches below go through
`jack-in-wayland.sh`/GNOME-on-Wayland, and the reason is concrete, not a convention —
**Wayland is this lab SSD's verified flicker-free 90 Hz path** (`docs/01`'s own note: "the
verified 90Hz launcher is `jack-in-wayland.sh`"). 60 Hz visibly flickers and is genuinely hard
on the eyes worn for any length of time; that alone rules out X11 for a real audience-facing
demo regardless of anything else. See `docs/06`'s new 2026-08-26 entry for a same-night X11
panel-link failure on this exact SSD, still open as of this writing — not the deciding factor
for using Wayland here, but worth knowing X11 is currently unverified on this session too.

**Hellblade reinstalled (2026-08-26)**: the 24.7GB re-download flagged as a blocker earlier
this session is done — `StateFlags: 4`, `SizeOnDisk: 24747009205`, `downloading/` empty,
installed to `/mnt/win5/SteamLibrary`. No longer a blocker for the retest.

## 1. Pre-show checklist (once, before doors open)

1. **Power**: `vr-power-watchdog.service` is installed and running (confirmed active
   2026-08-26) — it auto-applies full performance the moment a session/game is live and drops
   to saver at rest, so no manual `vr-power-setup.sh --apply` step is needed *if the watchdog is
   up*. Check with `systemctl status vr-power-watchdog`; if it's down, run
   `sudo ./scripts/vr-power-setup.sh --apply` by hand before the first title.
2. **No stale game trees**: `./scripts/vr-launcher.py status` (wraps `game-stop.py status`)
   must say clean. A Steam wrapper kill does NOT stop the real process (CLAUDE.md, T244) — a
   second live client silently doubles `Delivered frame` counts and invalidates everything.
3. **No stale Monado**: confirm `monado-service` isn't already running
   (`pgrep -f "monado[-]service"` — bracket the pattern, `pgrep -f` matches its own invocation
   otherwise) and delete `/run/user/1000/monado_comp_ipc` (SIGKILL doesn't clean it up).
4. **Audio**: `./scripts/hmd-audio.sh status` — confirm the USB Audio sink is present, unmuted,
   at a sane level. This lineup was picked specifically for audio impact, so check this every
   time, not just once: the sink gets torn down and recreated on every USB2-branch
   re-enumeration and can silently land muted/wrong-volume, or briefly disappear entirely.
5. **Controllers**: if a title needs hands (see per-title notes below), power both controllers
   on **before** `monado-service` starts — a controller powered on after startup reads its
   battery but is stuck at `<none>` for the whole session (right-hand startup race,
   `CLAUDE.md`). `vr-launcher.py` reports this after launch but does not fix it; fixing it means
   `jack-in-wayland.sh down`, power-cycle the controller, back `up` **once**, not in a loop
   (chained `monado-service` restarts trigger USB2 faults).
6. **Battery**: **correction (2026-08-26) — a real check does exist, this doc had it wrong.**
   `docs/03:113` documents `XRT_DEBUG_GUI=1` on `monado-service`, which opens a live debug GUI
   with a per-controller panel showing sticks, IMU, **and battery**. `docs/67` C6's "cliff byte
   never observed directly" is about a different thing (a specific low-battery signal byte in
   the wire protocol, for headless/scripted detection) — it does NOT mean there's no way to see
   battery at all. For a demo booth: run one `XRT_DEBUG_GUI=1` session before doors open, glance
   at both controller panels, close it, then launch normally (the debug GUI is not meant to stay
   open during a real session). Charge fully beforehand regardless — this only tells you the
   starting state, not a live mid-show number without the GUI open.
7. **Low-light tracking warning: not automated. Say it out loud manually.** The startup
   low-light warning was approved 2026-08-17 but **never built** (`docs/56:82`,
   confirmed still true as of `docs/67`). Aircar's own run #1 (T245) saw 3 VIO runaways in the
   first 75 seconds specifically attributed to a dim room (`docs/67 §7`) — venue lighting is a
   real, measured variable, not theoretical. Whoever runs the booth should check the room isn't
   dim before handing over the headset, every time, since nothing in software will say so.
8. **Vertical monitor**: if a desktop monitor is in portrait mode nearby, expect the NVIDIA
   driver to flatten its rotation the moment Monado takes a connector in direct-mode — fix by
   cycling the rotation via `kscreen-doctor`, not `xrandr` (`CLAUDE.md`).

## 2. Per-title launch

All three go through `scripts/vr-launcher.py`, not `bench-launcher.py` — the latter is built
for unattended automated runs and has already been shown to miss the real session entirely on
at least one title (Cyberpilot: every unattended `bench-launcher.py` pass saw only a harmless
capability-probe session, because the real OpenXR session only opens once the headset's own
wear sensor fires — `docs/67 §8`). A human needs to actually put the headset on for any of
these three to produce a real session.

### Aircar (1073390) — APPROVED for the demo (2026-08-26), gamepad + 3dof only

**Live-tested and approved by the user 2026-08-26 with a human wearing the headset, in this
EXACT configuration — do not substitute `6dof` for this booth, see below for why.**

```
VR_LAUNCH_APPID=1073390 ./vr-launcher.py 1 3dof
```

- `TITLE_PROFILES` already sets `WMR_CONSTELLATION_CONTROLLERS=0` for this appid (Xbox pad
  input, no hands) — `3dof` on top of that means WMR_SLAM=0 and WMR_CAMERAS=0 too: head
  rotation only, off the IMU, no cameras/SLAM in the loop at all.
- **Measured 2026-08-26**: clean **90.00 fps** both measurement windows (`app-fps.sh`), GPU
  93% util / 249 W / 75°C, **zero USB disconnects** over the test. Audio confirmed stable
  through the headset the whole time (see the audio section above — route it to `headset`
  and set volume via `hmd-audio.sh headset`, which now defaults to 120%, before handing over
  the headset).
- **Why 3dof, not 6dof, for this booth**: `docs/67 §2`'s own 6dof run (T245, 2026-08-23) hit 3
  VIO runaways/relocations in the first 75 seconds and never reached its 30-minute soak
  target. The user's own verdict after comparing both live: *"prefiero que ande así para la
  demo que con 6dof del casco pero a medias"* (prefer it running like this over 6dof
  half-working) — 3dof trades positional head tracking for zero relocation risk and a
  guests-per-hour-friendly, nothing-ever-stutters experience. This is the approved config;
  6dof stays a research track (`docs/67`), not a demo option, until it clears its own bar.
- **Known gotcha, only relevant if 6dof is ever revisited**: VIO runaways/relocation in the
  first ~75 seconds seated, worse in dim light — irrelevant in 3dof (no SLAM running at all).
  `jack-in-wayland.sh down` after a long session can hang >10s before SIGKILL (`docs/06`) —
  that's an already-known non-fatal teardown hang, not a new crash, don't panic-restart on
  top of it.

**6dof retest, same night, later — good light was the variable, but not yet "perfect":**
re-ran the exact `docs/67 §2` retest that had never happened (`VR_LAUNCH_APPID=1073390
./vr-launcher.py 1 6dof`, well-lit room this time). Result: **zero VIO runaways past the
critical first 75s** (max frame-to-frame pose jump over 375s/6.25 min worn: 0.17 m, vs. the
previous run's raw pose parked at 41 m), clean 90.00 fps, zero USB disconnects during the
live session. Confirms light was the real variable behind T245's failure. **Did not run the
full 30-minute soak** — stopped at ~6 minutes worn. User's own verdict, direct quote:
*"no es platinum, pero es gold, suma mucho a la experiencia y anda muy bien"* (not platinum,
but gold — adds a lot, works very well) and *"apenas se nota que no es 100% como el 3dof"*
(you can barely tell it's not 100% like 3dof). **Still NOT promoted to the approved demo
config** — this project's own bar is "approved only when it's perfect, discard rather than
oversell to guests" — 6dof is a strong, promising result, not yet a pass. Before it can
replace 3dof as the approved config: complete the 30-minute soak, and get a specific answer
to what keeps it from "platinum" (the user was asked but the session moved on before an
answer landed — worth asking again next time 6dof comes up).

**The specific answer landed later the same session: YAW is the weak axis.** User's own
finding, live: fast head rotation around yaw drifts him out of his seated position far more
than the same speed of rotation on the other axes — his own estimate, **~20x worse**.
Recoverable instantly with the pad's A button (the existing recentre binding), but it *will*
happen with first-time guests turning their head quickly, which a demo booth guarantees.
**This is a different mechanism from `docs/55`'s yaw-ghost-layer work** — that's about
controller constellation pose solving, not head SLAM — parallel finding, not the same fix.
Root cause not chased tonight (a plausible generic reason: fast yaw sweeps visual features
across the camera frame fastest of the three rotation axes, both because the WMR camera
layout is optimized for the *forward* view and any yaw pushes it off-axis, so cheaper to
re-litigate a separate day). **Standing instruction for the demo operator, not yet built into
the onboarding script**: watch for a guest turning their head quickly side-to-side, and be
ready to say "press the A button" — don't wait for them to visibly disorient first. Also hit
during this same test: audio and gamepad input both silently stopped (only head tracking kept
working) because the Aircar companion window had lost desktop focus with nothing re-focusing
it — window focus governs more than fps here, it gates Wine's raw input/audio routing too.
Fixed live by re-focusing the window (`xdotool windowactivate`); **not yet built as an
automated alert**, flagged as a real gap for the operator script (see `docs/79`).

### Dreams of Dalí (591360) — confirmed working today, headset-only input, still no metrics

```
VR_LAUNCH_APPID=591360 ./scripts/vr-launcher.py 1 6dof
```

- **Now in `vr-launcher.py`'s `GAMES` catalog and `TITLE_PROFILES`/`NO_HANDS_TITLES`** (added
  2026-08-26). `WMR_CONSTELLATION_CONTROLLERS=0` — correct because the input model has none.
- **Input method, worn-confirmed by the user (2026-08-26): headset-only, gaze-dwell.** You look
  at an on-screen marker and stay on it; the experience advances on its own. No gamepad, no
  motion controllers at all. (An earlier version of this doc guessed "gamepad-class" from static
  binary evidence in the install — `openvr_api.dll` + `OVRGamepad.dll` — that guess was wrong;
  worn evidence overrides it per this project's own rule.)
- Run with **6dof** head tracking per the user's own direction — this is a real room/head-motion
  piece, not a seated-gaze-only one, so basalt/SLAM should be live.
- **Audio confirmed very good** by the user directly — consistent with why this title made the
  binaural shortlist in the first place.
- **Status**: worn, working, genuinely positive (2026-08-26) — but still **zero recorded
  metrics**: no fps/pacing numbers, no duration, no note of how long it ran. Before relying on it
  for a live audience, worth one measured pass with `app-fps.sh`/`frame-pacing.sh` running,
  matching the rigor already applied to Aircar and Cyberpilot — the subjective result is good,
  the numbers just aren't on file yet.

### Hellblade: Senua's Sacrifice VR Edition (747350) — one good look, pre-fix, reinstalled

**Was missing entirely, now fixed (2026-08-26).** Found gone from all four Steam library
folders earlier tonight — the 24.7GB downloaded live during T243-night (2026-08-21) had been
uninstalled at some point since. Re-downloaded same session: confirmed complete
(`StateFlags: 4`, `SizeOnDisk: 24747009205`, `downloading/` empty), installed to
`/mnt/win5/SteamLibrary`. Ready to launch; still needs the actual retest below.

```
VR_LAUNCH_APPID=747350 ./scripts/vr-launcher.py 1 6dof
```

- Already in `GAMES`. **No `TITLE_PROFILES` entry** — runs with the default
  (constellation ON, treated as a hands title). Not in `NO_HANDS_TITLES`, so a missing
  controller registration will print loudly, which is probably correct behavior for this title
  but has not been confirmed against how the game is actually played.
- **Status, per `docs/23:54`**: tested exactly once, 2026-08-21 (T243-night), **before** the
  T244 app-pacer fix that resolved the project-wide 45/30fps ceiling bug. Wearer's own read was
  the most positive of that entire broken-family night: *"very promising, steady 45fps, good
  head guidance."* It hit the same ceiling bug as everything else that night — a bug that no
  longer exists. **`docs/67 §4`'s own B5 track explicitly names this: "Hellblade deserves a full
  pass"** — i.e. the project's own plan already flags this exact gap, it just hasn't been
  picked up yet. Real chance this title now runs meaningfully better than its one data point
  suggests, but that is a prediction, not a measurement, until it's retested.

## 3. Between-title teardown

Before starting the next title:

1. `./scripts/vr-launcher.py stop all` (wraps `game-stop.py stop all` — kills the real process
   tree via its Proton `compatdata` path, not just the Steam wrapper).
2. `./scripts/vr-launcher.py status` must report clean.
3. Check Monado's log (`~/vr/jack-in-wayland.log`) shows `client_disconnected` for the title
   that just ended before bringing the next one up. Two clients alive at once has already
   happened for real (Dead Herring VR rendering silently behind a live Cyberpilot session,
   151 combined `Delivered frame`/s, every CPU/GPU number invalidated for that whole test).
4. Don't chain `monado-service` restarts rapidly across titles — each `vr-launcher.py` launch
   already does a full down/up cycle; that's fine. Looping restarts quickly is a known USB2
   trigger, not the normal per-title cadence.

## 4. What's explicitly NOT ready yet

- **Aircar (6dof)**: relocation/recentre criterion unmet, 30-min soak test never run — still a
  research track, not a demo option. **Aircar in `3dof` (gamepad-only) IS approved for the
  demo (2026-08-26)**: clean 90fps, zero USB drops, live-tested and signed off by the user in
  this exact config (see section 2 above) — use `3dof`, not `6dof`, at the booth.
- **Dreams of Dalí**: input method and tracking mode now confirmed (headset-only gaze-dwell,
  6dof, wired into the launcher) and audio confirmed very good — but still zero recorded
  fps/pacing/duration numbers behind the good subjective result.
- **Hellblade**: reinstalled (2026-08-26, was missing entirely earlier tonight) — ready to
  launch, but still not retested against the T244 fix that's the whole reason a retest looked
  promising in the first place.
- **No automated low-light warning** exists anywhere in the stack — it's an approved, unbuilt
  idea. Venue lighting is a real, measured risk factor for Aircar specifically.
- **Battery**: correction above — `XRT_DEBUG_GUI=1` gives a real live per-controller reading,
  this is no longer a blind spot, just an extra manual step before doors open.
- **Long unattended marathon sessions** (many titles back to back over hours) have a known,
  not-root-caused full-system hang risk tied to 8GB VRAM (`docs/06`, T243-night) — mitigation on
  file is "don't chain many high-res launches for hours without a clean restart," not a fix.

## 5. Open questions for the user

1. ~~Add Dalí to the launcher~~ — done 2026-08-26. ~~What input method does Dalí use~~ — answered
   2026-08-26 by the user directly (headset-only gaze-dwell, no controllers, 6dof).
2. ~~Battery check~~ — answered: `XRT_DEBUG_GUI=1` before doors open.
3. **Hellblade re-download**: worth doing now while there's time before the show, or drop it
   from the shortlist if the re-download + retest can't fit the remaining schedule?
4. Given the low-light warning isn't built, should the demo operator have a fixed spoken line
   ("make sure the room isn't dim") as a standing part of the handover script, or is a lighting
   fix at the venue itself (make sure the booth is never dim) enough to skip needing this per
   session?
5. **Dalí needs a measured pass** (fps/pacing/duration) to match the rigor already on file for
   Aircar/Cyberpilot — worth scheduling before it's treated as demo-ready, even though the
   subjective result today was good.

## 6. Session recording (the demo IS the soak test — docs/80)

The demo is how Aircar 6dof (and any new config) gets its real soak: many wearers of different
heights cycling through one running title beats a solo 30-min soak. `scripts/demo-recorder.py`
captures each run so it's on file. Design (agreed 2026-08-26): records to RAM (`/mnt/vrtmp`,
same tmpfs as the SLAM CSVs — no disk jitter mid-demo) while the session is live, then copies
everything to `~/vr/logs/demo-sessions/<date>/` with a `summary.json` (date, eye-height,
wearer-session count, operator notes, the exact SLAM config in effect) when `monado-service`
ends. Nothing is lost to a reboot — it's persisted at session close.

- **Auto-start**: the dashboard demo buttons (`:8765`) set `VR_DEMO_RECORD=1`, so a demo launch
  records automatically. From the CLI: `VR_DEMO_RECORD=1 VR_DEMO_COMMENT="run 1, tall guests"
  ./vr-launcher.py 1 6dof`. Dev/tuning launches without that env do NOT record.
- **Per-run eye-height**: each `start` is one run; do several at several eye-heights (taller /
  shorter guests). The run's `summary.json` records the eye-height it ran at (from
  jack-in-wayland.sh's own "Eye height:" line), so the runs are comparable.
- **Operator notes, live**: `~/vr/demo-recorder.py note "person 3, ~1.9m, slight drift on fast
  turns"` appends a timestamped comment to the active run — capture wearer reactions as they
  happen; they land in `summary.json`'s `operator_notes`.
- **Check / stop**: `demo-recorder.py status` (recording? wearers? eye-height?);
  `demo-recorder.py stop` finalizes now (otherwise it finalizes on its own when the session
  ends). Each run writes one `~/vr/logs/demo-sessions/<date>/` folder: `metrics.jsonl` (fps /
  pacing / power / config time series), `slam/` (the run's pose CSVs), `summary.json`.
