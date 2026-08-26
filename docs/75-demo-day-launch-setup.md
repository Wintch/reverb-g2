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

### Aircar (1073390) — the reference title, most-worked, still not fully certified

```
VR_LAUNCH_APPID=1073390 ./scripts/vr-launcher.py 1 6dof
```

- `TITLE_PROFILES` already sets `WMR_CONSTELLATION_CONTROLLERS=0` for this appid — no manual
  env needed, and it's in `NO_HANDS_TITLES` so the controller-registration check stays
  informational (an Xbox pad is what it actually needs, not motion controllers).
- **Known gotcha**: expect possible VIO runaways / relocation in the first ~75 seconds seated,
  worse in dim light — recentre with the pad's A button. `jack-in-wayland.sh down` after a long
  session can hang >10s before SIGKILL (`docs/06`) — that's an already-known non-fatal teardown
  hang, not a new crash, don't panic-restart on top of it.
- **Not fully certified per `docs/67 §2`'s own acceptance table**: run #1 (T245, 2026-08-23)
  met sustained 88-90fps, clean pacing, and companion-drop recovery, but **failed** the
  no-relocation criterion (3 VIO runaways in 75s) and never reached the required 30-minute worn
  duration (only 13.5 min). Run #2 (normal light, ≥30 min soak) is `docs/67`'s own stated next
  step and has not happened yet as of the most recent `NEXT-STEP.md` entries.

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

- **Aircar**: relocation/recentre criterion unmet, 30-min soak test never run. Currently the
  most-measured of the three, but its own exam is not passed per the project's own bar.
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
