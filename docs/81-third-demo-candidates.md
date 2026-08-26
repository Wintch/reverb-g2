# 81 — Third demo candidates (2026-08-26)

Approved so far: **Aircar** (1073390, 3dof, Xbox pad) and **Dreams of Dalí** (591360, 6dof,
headset-only gaze-dwell) — both worn, measured, signed off tonight (`docs/75`, `docs/76`).
This is the search for a THIRD.

**Operator's constraints, as given:** short sessions, many first-timers, seated, "light"
experiences; only what is PERFECT gets shown ("más vale descartar que sumar algo como
perfecto y no lo es"); motion controllers do NOT need to be showcased — gamepad or
headset-only strongly preferred, because controller 6DoF is still not demo-grade (positional
presence target ≥90%, measured today 50-60%, `docs/58`, `docs/67:75`); audio impact matters
(this shortlist was built around binaural sound); bar is "like on Windows or better."

Every title below that "reportedly needs controller point/grab" is flagged as a real
tension with the no-controllers preference, not glossed over — per the operator's own rule,
that alone is grounds to discard unless a session tonight proves it's light-touch in practice.

## Ranked shortlist (installed, ready to test)

### 1. The Night Cafe — Van Gogh tribute (482390, free, 449 MB, /mnt/win5)
- **Input**: SteamVR "Tracked Controller Support" — grab/point, standing/room-scale per its
  store page (`docs/77`). NOT gaze-only like Dalí. Unclear how much is required just to walk
  through vs. optional — untested on this stack.
- **Session length**: unknown, likely short (art-walkthrough scale, comparable to Dalí).
- **Audio**: unverified on this rig; genre fits the shortlist's spirit even if not confirmed
  binaural.
- **Verified vs assumed**: nothing verified — never launched on this headset. What IS
  verified: it's installed, in `vr-launcher.py`'s `GAMES` catalog, and its Proton prefix is
  **already relocated off NTFS** to ext4 (docs/70 fix pre-applied 2026-08-26 for this title
  and Anne Frank — `scripts/vr-launcher.py:122-124`). So the blocker that hit
  Dalí/Cyberpilot/Hellblade is already cleared here.
- **Risks**: needs controller point/grab per its listing — may simply fail the
  no-controllers preference outright; not in `NO_HANDS_TITLES`, so the launcher treats it as
  a hands title (constellation on) by default; zero wear-test data.
- **Minimal test tonight**:
  ```
  VR_LAUNCH_APPID=482390 ~/vr/vr-launcher.py 1 3dof
  ```
  Try 3dof first (cheapest, Aircar's proven avoid-the-SLAM-bug strategy) — if the game needs
  positional hand tracking to move at all, it'll be obvious immediately (can't reach/grab
  anything). If unplayable, retry `6dof` with both controllers on **before** the service
  starts. **Watch for**: does progress need point/grab, or is it mostly walk + one trigger
  press? **Pass**: wearer laps the main room with at most one simple trigger action per
  transition, no precision grabbing, no jitter/jumping complaints, can describe what they
  saw. Anything more input-heavy = discard.

### 2. In-house 360/VR180 player reel (`~/vr/play360.sh`, no AppID)
- **Input**: none. No controllers, no gamepad required at all (`docs/02`).
- **Session length**: fully operator-controlled — pick a 2-4 minute clip/photo set per guest.
- **Audio**: **real gap, stated plainly** — video playback in this player is currently
  **silent** (`docs/02:587`, "Video audio (silent today)"). Still images have no audio
  expectation either way. This cuts against "audio impact matters"; it doesn't disqualify
  the visual experience, but this option can't deliver what Aircar/Dalí deliver on sound.
- **Verified vs assumed**: the most *technically* verified item on this list — 90Hz panel
  confirmed unblocked project-wide (`docs/19`), VR180 stereo 3D worn-verified "really good"
  (`docs/02`, 2026-08-04), zero Proton/Steam/NTFS/controller-pairing risk (native OpenXR
  client via `hello_xr`, not a Steam title at all). **Not yet on file**: a worn pass with the
  specific media selected as tonight's demo reel.
- **Risks**: audio-silent for video; needs someone to curate 2-4 minutes of the strongest
  clips/photos in `~/vr/media/`; needs a human manually starting/stopping content, not a
  self-contained game loop.
- **Minimal test tonight**:
  ```
  ~/vr/play360.sh   # or jack-in-wayland.sh + play360.sh per docs/02's own runbook
  ```
  Pick the best VR180 3D clip and one striking 360 photo. **Watch for**: flicker-free 90Hz,
  clean stereo depth, no black seams. **Pass**: wearer confirms sharp, flicker-free,
  genuinely 3D image, no controllers in hand — same bar as the 2026-08-04 verdict, just
  re-confirmed with the exact content that would run at the booth.

### 3. Anne Frank House VR (2877690, free, 1.4 GB, /mnt/win5)
- **Input**: same family as Night Cafe — point-and-click floor markers to move, touch
  doorknobs/objects with a virtual hand (`docs/77`). Not gaze-only.
- **Session length**: **~25 minutes narrated** — long for "many short sessions" unless
  truncated to a chapter; a real fit concern independent of the input question.
- **Audio**: narrated in 7 languages — likely the strongest *narrative* audio here, though
  narration ≠ the binaural/spatial quality the other three titles were picked for.
- **Verified vs assumed**: same as Night Cafe — never launched here, but Proton prefix
  already relocated off NTFS, installed and in the launcher catalog.
- **Risks**: controller-dependent per its listing (same tension as #1, likely worse — it
  names "touch objects," not just locomotion); length mismatch with "short sessions for
  many guests"; subject matter is heavy, which may or may not fit "light" depending on
  whether that means technical lightness or tone — worth a direct check with the operator.
- **Minimal test tonight**: same recipe as #1 —
  ```
  VR_LAUNCH_APPID=2877690 ~/vr/vr-launcher.py 1 3dof
  ```
  **Watch for**: can the narration be followed by looking around only, or is progress gated
  behind touching objects? **Pass**: same as Night Cafe, plus check whether a 3-5 minute
  excerpt reads as a complete moment — if not, this needs a curated shorter path.

## Also installed, lower priority

### 4. NVIDIA VR Funhouse (468700, 3.1 GB, /mnt/win5)
Launch-options recipe is complete (`PRESSURE_VESSEL_FILESYSTEMS_RW` fix landed, `docs/23:141`)
but never retested under it — the old FAIL verdict predates the fix and is explicitly
"suspect." Genre is precision-grab minigames (balls, guns, carnival games) — likely the
*most* controller-dependent, precision-sensitive title here, cutting hard against the
no-controllers preference and the "only perfect" bar. PhysX/CUDA-heavy, unknown performance
profile on this stack. Ranked below #1-3: even a clean launch likely still needs the exact
motion-controller precision the operator wants to avoid showcasing.

### 5. Hellblade: Senua's Sacrifice VR Edition (747350, 23.6 GB, /mnt/win5)
Best raw material for "audio impact" (binaural-shortlist title, `docs/78`) and the most
positive wearer quote in the T243-night sweep ("very promising, steady 45fps, good head
guidance," `docs/23:54`) — but that **predates the T244 app-pacer fix** that resolved the
project-wide 45/30fps ceiling; nobody has looked since. Two hard blockers tonight: **(a)**
its Proton prefix is currently broken by the same docs/70 NTFS symlink bug that hit
Dalí/Cyberpilot — needs the `compatdata/747350` → ext4 relocation before it can even launch;
**(b)** it's explicitly a motion-controller title (`docs/76:10`, `docs/79:14`,
"treated as hands-title"), conflicting directly with the operator's stated preference no
matter how well it runs. Kept on the list as the most-invested prior candidate, but it needs
real engineering work (the prefix fix) before it's even testable, and even a perfect result
would need the operator to explicitly waive the no-controllers preference for it.

## Owned but NOT installed — worth a reinstall if time allows

- **International Space Station Tour VR (797200)** — strongest structural fit of anything
  uninstalled: already flagged `NO_HANDS_TITLES` in `scripts/vr-launcher.py` (does not
  render hands, `docs/23`) with its own profile turning constellation OFF — the same
  "avoid the SLAM/constellation starvation bug" strategy behind Aircar's approved 3dof
  config. Original clean verdict ("cleanest signal of the whole sweep," T073/T075)
  predates 6dof/constellation entirely; a 3dof retest is the honest way to check it holds.
  Caveat: also the heaviest content ever measured here (8K, `monado-service` at 519% CPU
  under 6dof) — worth confirming 3dof alone stays light.
- **Cosmic Flow: A Relaxing VR Experience (1267950)** — name/genre fit "light experience"
  better than almost anything in the catalog; confirmed working, real 3D, zero late frames
  once warm (T073/T077). Input method not independently verified as hands-optional.
- **VRSailing by BeTomorrow (579050)** — confirmed working, good pacing history, but genre
  (sailing controls) suggests real reliance on sticks/hands — lower confidence than the two
  above; a fallback only.

## Not considered further (per the operator's constraints or lack of data)

- **Wolfenstein: Cyberpilot (1056970)** — known-playable, but explicitly needs controllers
  and runs 46-67 fps under load, not clean 90 (`docs/23`, `docs/67 §8`) — excluded by the
  operator's own stated preference, not a new finding.
- **Batman: Arkham VR, DOOM VFR, Half-Life: Alyx, Alien: Rogue Incursion VR** — zero verdict
  rows in `docs/23`, never launched on this stack. All four are controller-driven AAA
  titles by design. Given "only perfect gets shown," these carry the highest
  risk-to-unknown ratio here and aren't realistic to validate before the show.
- **Crysis 2 (108800)** — a flat stereo-3D experiment (`docs/71`), not a VR piece.
- **Steam 360 Video Player (613220)** — reaches VR fine but has no real content installed
  (`docs/23:76`); the in-house player already does this job with a proven pipeline
  (`docs/02`). Redundant, not a distinct option.

## Recommendation

**Test The Night Cafe first tonight** (`VR_LAUNCH_APPID=482390 ~/vr/vr-launcher.py 1 3dof`)
— it is the cheapest possible test (already installed, prefix already fixed, thematically
the closest thing to a "second Dalí"), and it is the one test whose result actually resolves
an open question already on file (`docs/77`) rather than just re-confirming something
already known. If it fails the no-controllers bar, the in-house 360/VR180 reel is the
zero-risk fallback that is already known to work — the only open item there is picking the
content and accepting the audio gap.
