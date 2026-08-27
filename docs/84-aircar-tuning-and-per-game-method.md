# 84 — Aircar graphics tuning and the per-game tuning method (2026-08-27)

Aircar's own in-game graphics menu was swept for the first time against a real fps/GPU
instrument, on top of the `XRT_COMPOSITOR_SCALE_PERCENTAGE=100` Monado-side fix already in
`TITLE_PROFILES` (`scripts/vr-launcher.py:155-167`, docs/83 §4). Result: a measured optimal
config, a corrected model of where the GPU cost actually comes from, a confirmed (not
broken) brightness knob, and an open problem — Aircar does not persist its own settings.

## 1. Instrument

No in-headset fps counter works on this stack: xrizer's app-type whitelist blocks
fpsVR/Steam-overlay as an in-VR overlay (session memory `idea_fpsvr_data_extraction`). The
only working instrument this session was the **Steam desktop performance overlay**, read by
screenshotting the game window (dashboard `/api/screen.jpg`, or `import -window
<Aircar-window-id>`) and cropping the top ~46px where the overlay draws FPS/min/max. GPU%
cross-checked against `nvidia-smi`.

## 2. Measurement caveat: fps is heavily scene-dependent

Two captures of the **identical** config (HIGH quality + Pixel Density 1.2), seconds apart,
gave **36 fps / GPU 92%** (dense city, looking down) vs. **61 fps / GPU 66%** (open sky). A
single grab is meaningless. Rule for this and every future title sweep: **4+ samples over
~15s at a representative/stable scene**, report the typical/worst case, not a lucky frame.

## 3. The sweep

All rows at `XRT_COMPOSITOR_SCALE_PERCENTAGE=100` (Monado side fixed; only the in-game
knobs varied):

| In-game config | FPS | GPU | Note |
|---|---|---|---|
| LOW quality | 90 | 24% | "horrible visuals, very fluid" |
| DEFAULT (Pixel Density 0.9) | 90 | 63% | |
| HIGH + Pixel Density 1.0 | 90 | 66% | steady, 4 samples |
| **HIGH + Pixel Density 1.1** | **89-90** | **70%** | steady, 4 samples — **optimal** |
| HIGH + Pixel Density 1.2 | 36-61 | up to 92% | tanks, scene-dependent (§2) |
| HIGH + Pixel Density 2.x | 33 | 91% | tanks; SS 2.x ≈ 4x native pixels |

## 4. Optimal config

**In-game HIGH (all quality settings) + Pixel Density (SS) 1.1 + Monado
`XRT_COMPOSITOR_SCALE_PERCENTAGE=100`.** Holds 90 fps, sharp, GPU headroom (70%). Wearer:
*"muy lindo anda, apenas un tirón mínimo"* — the tiny tug is the occasional heavy-scene dip
from §2; dropping to Pixel Density 1.0 removes it for a hair less sharpness, a legitimate
fallback if the 1.1 dip ever bothers a guest.

## 5. Corrected insight: quality AND supersampling both cost

The lead's first read of the sweep was **"quality knobs are cheap vs. supersampling."
Wrong** — the record contradicts it: at HIGH quality the GPU maxes out regardless of SS
(dropping SS 2.x → 1.2 only moved fps 33 → 36, i.e. it's still pegged). Both axes matter;
HIGH quality alone is already expensive before SS is touched at all.

## 6. The key relationship: two compounding scale knobs

A game's own "Pixel Density (SS)" / render-scale slider **is the same lever** as Monado's
`XRT_COMPOSITOR_SCALE_PERCENTAGE` (docs/83 §4), and they **compound multiplicatively**:
effective render scale = Monado % × in-game SS. This is the single biggest GPU lever
because fill-rate scales with pixels². Antialiasing and the other quality knobs
(post-processing/shadows/textures/effects) are a separate, moderate-cost axis (edge/detail
quality, not raw pixel count). Aircar's in-game quality menu maps its four presets to UE's
`sg.*` scalability levels 0-3.

## 7. GPU power is not capped

Measured this session: `nvidia-smi` power limit = 250W (the card's max), draw peaked at
244W. `power.conf`'s `GPU_LIMIT_PCT=70` is **not applied** in this session. So the fps
ceiling at HIGH+high-SS is genuine GPU compute saturation, not a power cap —
"raise the power cap" is a no-op here; there's nothing to lift.

## 8. Brightness (xrizer patch 0007) — corrected verdict: it works

Wearer confirmed the dashboard brightness slider works in-headset: *"el slider de brillo me
anduvo bien."* The earlier "broken" verdict (an objective screenshot A/B that showed a flat
mean) used the **wrong instrument**: the desktop mirror shows the app's raw submitted
texture, not the compositor's post color-scale/bias output (docs/83 Part 2 traces the whole
pipeline — extension negotiated, struct layout matches, shader applies
`color_scale`/`color_bias` — nothing wrong was found there either). A compositor-layer
effect is invisible to a capture that only sees the pre-compositor frame. Per this project's
cardinal rule (CLAUDE.md), the human in the headset is the instrument, and the human says it
works.

Separate, non-blocking note from the docs/83 calibration pass: the patch splices the
color-scale struct without gating on the extension actually being enabled. That's a
robustness improvement (add an enabled-extensions check + `warn_once`), not a functional
fix — the knob works today because the extension is in fact enabled.

## 9. Per-game config persistence — unsolved

Goal: make Aircar launch pre-tuned to §4's config instead of the wearer setting it by hand.
Tried: pre-write the optimal values into Aircar's UE `GameUserSettings.ini` and mark it
read-only. Result: the read-only file survived intact on disk (verified after launch), but
**Aircar still started at its default in-game settings**. Conclusion: Aircar's graphics menu
does not read `GameUserSettings.ini` — its settings live somewhere else (a custom save file,
or runtime CVars set via `-execcmds`/`r.ScreenPercentage`-style launch args). Separately
confirmed: Aircar also does **not** write menu changes back to the ini on exit, which is why
settings "reset" between sessions today. Per-game config persistence is an open problem,
mechanism unknown, and will need its own investigation per title/engine — do not assume the
ini trick generalizes even within Aircar.

## 10. The method, per title, and the north star

For each demo title:
1. Capture its own settings screen at full resolution to learn its exact option names.
2. Measure each option's fps/GPU impact — multi-sampled (§2), at a stable/representative
   scene, both in-game AND `XRT_COMPOSITOR_SCALE_PERCENTAGE` swept together (§6).
3. Record the measured-optimal config (a row like §3/§4 for every guest-facing title).
4. Persist it per-game — mechanism to be found per engine (§9 shows the obvious one doesn't
   work for Aircar).

North star ("hagamos que ya venga tunado"): every guest-facing title in the demo lineup
launches already at its measured-optimal config, no manual menu step. Once persistence is
solved per-title, expose these as per-game settings in the web command centre (docs/83 §8's
shortlist already earmarks `XRT_COMPOSITOR_SCALE_PERCENTAGE` as a live per-title slider).

## 11. Power policy

While nothing demo-relevant is running: apply full power saving — saver mode **and stop
`monado-service`** for genuine idle. The ~60W figure previously read as "idle" is Monado's
compositor presenting the panel at 90Hz, not the GPU actually doing nothing (session memory
`project_benchmarks_and_power_policy`). Never cap power mid-demo (§7 — there's currently no
active cap to begin with, but the rule stands regardless).

## Cross-references

- docs/82 §1.4, §9 — the fps measurement protocol (gameplay not menu, 100% GPU, minimum
  render resolution via `XRT_COMPOSITOR_SCALE_PERCENTAGE`) this session's Aircar sweep
  follows.
- docs/83 §4, §8 — the `XRT_COMPOSITOR_SCALE_PERCENTAGE`/render-scale lever catalog and the
  brightness-knob pipeline trace this session's findings build on and confirm.
- `scripts/vr-launcher.py` `TITLE_PROFILES["1073390"]` — Aircar's profile, already carrying
  `XRT_COMPOSITOR_SCALE_PERCENTAGE=100` from the same 2026-08-27 work.
- docs/23's Aircar rows — the existing reference-title history (stick deadzone, recentering,
  SLAM cost); this doc adds the graphics-quality axis, doesn't replace any of it.
