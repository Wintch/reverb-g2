# 84 — Per-game graphics tuning method, and the brightness-knob confirmation (2026-08-27)

How to tune a title's graphics for 90 fps on this stack, using Aircar as the worked example: the
measurement protocol, how the two supersampling knobs compound, why a power cap is not the lever, and
what the brightness-knob verdict is.

## 1. Instrument

No in-headset fps counter works on this stack (xrizer does not support overlay applications, so
fpsVR / the Steam overlay cannot run as an in-VR overlay; docs/23). The working instrument is the
**Steam desktop performance overlay**, read by screenshotting the game window (dashboard
`/api/screen.jpg`, or `import -window <window-id>`) and cropping the top ~46 px where the overlay draws
FPS/min/max. GPU% is cross-checked against `nvidia-smi`. Alternatively count `Delivered frame` lines
with `U_PACING_APP_LOG=debug` (docs/83 §4).

## 2. Measurement caveat: fps is heavily scene-dependent

Two captures of the **identical** config (HIGH quality + Pixel Density 1.2), seconds apart, gave
**36 fps / GPU 92%** (dense city, looking down) versus **61 fps / GPU 66%** (open sky). A single grab is
meaningless. Rule for every title sweep: **4+ samples over ~15 s at a representative, stable scene**;
report the typical/worst case, not a lucky frame.

## 3. Worked example: the Aircar sweep

All rows at `XRT_COMPOSITOR_SCALE_PERCENTAGE=100` (Monado side fixed; only in-game knobs varied):

| In-game config | FPS | GPU |
|---|---|---|
| LOW quality | 90 | 24% |
| DEFAULT (Pixel Density 0.9) | 90 | 63% |
| HIGH + Pixel Density 1.0 | 90 | 66% |
| **HIGH + Pixel Density 1.1** | **89-90** | **70%** |
| HIGH + Pixel Density 1.2 | 36-61 | up to 92% |
| HIGH + Pixel Density 2.x | 33 | 91% |

Optimal for this title: **in-game HIGH + Pixel Density 1.1 + Monado `XRT_COMPOSITOR_SCALE_PERCENTAGE=100`**
(holds 90 fps with GPU headroom; Pixel Density 1.0 removes the occasional heavy-scene dip for slightly
less sharpness).

## 4. Quality AND supersampling both cost

A first read of the sweep was "quality knobs are cheap versus supersampling". **Wrong**: at HIGH quality
the GPU maxes out regardless of SS (dropping SS 2.x to 1.2 only moved fps 33 to 36, still pegged). HIGH
quality alone is already expensive before SS is touched.

## 5. Two compounding scale knobs

A game's own "Pixel Density (SS)" / render-scale slider **is the same lever** as Monado's
`XRT_COMPOSITOR_SCALE_PERCENTAGE` (docs/83 §4), and they **compound multiplicatively**: effective render
scale = Monado % x in-game SS. This is the biggest GPU lever because fill rate scales with pixels^2.
Antialiasing and the other quality knobs (post-processing, shadows, textures, effects) are a separate,
moderate-cost axis (edge/detail quality, not raw pixel count). Aircar's in-game quality menu maps its four
presets to UE `sg.*` scalability levels 0-3.

## 6. A power cap is not the lever when the card is already below it

During the sweep `nvidia-smi` showed a 250 W power limit (the card's max) and a peak draw of 244 W: the
fps ceiling at HIGH + high SS is genuine GPU compute saturation, not a cap. "Raise the power cap" is a
no-op there. A configured `GPU_LIMIT_PCT` in `power.conf` is only an intent until applied; check the
live limit (see the power-cap method note at the end of docs/83).

## 7. Brightness (xrizer patch 0007): the knob works, but only at 1.0 is it flicker-free

The dashboard brightness slider works in-headset. An earlier "broken" verdict (a screenshot A/B showing
a flat mean) used the **wrong instrument**: the desktop mirror shows the app's raw submitted texture,
not the compositor's post color-scale/bias output (docs/83 Part 2 traces the whole pipeline: extension
negotiated, struct layout matches, shader applies `color_scale`/`color_bias`). A compositor-layer effect
is invisible to a capture that only sees the pre-compositor frame; the person in the headset is the
instrument.

**Caveat (docs/112 §3):** the gain visibly changes brightness, but at any value other than 1.0 it also
visibly **dithers**: `XR_KHR_composition_layer_color_scale_bias` multiplies the composited RGB into
values between representable 8-bit levels and the driver alternates adjacent levels frame to frame,
which reads as fast flicker in bright areas. Live A/B: 1.0 clean, 1.25 flickers, 4.0 much worse.
**Standing rule: never ship a gain other than 1.0 on this headset.**

Separately, the patch splices the color-scale struct without gating on the extension being enabled: a
robustness improvement (add an enabled-extensions check plus `warn_once`), not a functional fix.

## 8. Per-game config persistence: unsolved, with one corrected conclusion

Goal: make a title launch pre-tuned instead of setting options by hand. For Aircar, pre-writing the
optimal values into the UE `GameUserSettings.ini` and marking it read-only left the file intact on disk,
but **Aircar still started at its default in-game settings**, so the menu does not read that file at
startup (or not a read-only one). The earlier claim that Aircar also never writes menu changes back to
the ini was **wrong**: after changing quality via the in-game menu and closing normally, the ini's mtime
and content changed exactly as a low-quality preset would (`sg.ShadowQuality` 1 to 0, `sg.PostProcessQuality`
3 to 0, `sg.TextureQuality` 3 to 0). The write path works; only the read path (or a read-only-specific
read path) was ever shown to fail, because the original test conflated read-only with pre-written values.
The precise next experiment: pre-write the optimal values into a **writable** ini, launch, and inspect
the file before any menu interaction; if the values survive unchanged the game read them at startup.
Mechanism will need investigating per title/engine; do not assume the ini trick generalises.

## 9. The method, per title

1. Capture the title's own settings screen at full resolution to learn its exact option names.
2. Measure each option's fps/GPU impact, multi-sampled (§2) at a stable scene, both in-game AND
   `XRT_COMPOSITOR_SCALE_PERCENTAGE` swept together (§5).
3. Record the measured-optimal config (a row like §3 per title).
4. Persist it per game; the mechanism is per engine (§8).

Idle policy: while nothing is running, use saver mode and **stop `monado-service`**. The ~60 W figure
that reads as "idle" is Monado's compositor presenting the panel at 90 Hz, not the GPU doing nothing.

## Cross-references

- docs/23: the fps measurement protocol (gameplay not menu, 100% GPU, minimum render resolution via
  `XRT_COMPOSITOR_SCALE_PERCENTAGE`) and Aircar's reference-title history.
- docs/83 §4 and Part 2: the render-scale lever catalog and the brightness-knob pipeline trace.
- `scripts/vr-launcher.py` `TITLE_PROFILES["1073390"]`: Aircar's profile, carrying
  `XRT_COMPOSITOR_SCALE_PERCENTAGE=100`.
