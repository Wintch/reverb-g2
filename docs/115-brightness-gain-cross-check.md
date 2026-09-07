# 115 — Brightness gain cross-check against Oasis, and a correction to docs/112 (2026-09-07/08)

Corrects one line of `docs/112`'s otherwise-still-valid conclusion. Does **not** reopen the
fix itself: `gain == 1.0` remains the only clean value, and was reconfirmed still pinned (live
file plus both saved profiles) after this session's Windows excursion and reboot back to
Debian.

## What prompted it

During the live Windows session (`docs/114`), the wearer noticed SteamVR's brightness had been
left at **220%** and, even at that value, did not see flicker comparable to Linux's problematic
1.25×. The image looked correct, but highlights lost detail ("no detail in the bright spots") —
the visual signature of clipping/saturation, not of dithering.

## Oasis has the same kind of control

Checked Oasis's own `resources/settings/default.vrsettings`:

```json
{
  "driver_oasis": {
    "gamma_mode": 0,
    "rgb_gain": 1,
    "red_gain": 1,
    "green_gain": 1,
    "blue_gain": 1
  }
}
```

So this is not "Windows doesn't have this problem" — Oasis ships the same conceptual feature
(a post-render multiplicative RGB gain, default 1.0) that xrizer does. The difference is what
happens at the ceiling: Oasis apparently tolerates roughly **2.2×** without a visible flicker
artifact (at the cost of blown highlights), where xrizer's 1.25× already produced clearly
visible temporal flicker. No SteamVR override for `rgb_gain` survived in `steamvr.vrsettings`
after the wearer set it back to 100% — consistent with 100% being Oasis's shipped default
(nothing to persist as an override).

## Correction: xrizer does not do the dithering itself

`docs/112` describes the mechanism as "the xrizer brightness gain ... pushes composited values
between representable 8-bit levels and gets dithered temporally." Re-reading
`current_brightness_gain()` in `src/compositor.rs` (line ~1687) once back on Debian: the
function only reads and clamps the gain scalar from disk (`[0.0, 4.0]`) and attaches it as
`XR_KHR_composition_layer_color_scale_bias`'s `color_scale` on the projection layer. There is no
pixel-level dithering code in xrizer at all. The function's own doc comment says "the driver
dithers them temporally" — the dithering happens **downstream** of xrizer, most likely in
Monado's compositor when it composites the color-scaled layer, or in NVIDIA's proprietary
driver at KMS scanout to the 8bpc DisplayPort link.

Tried to confirm which, this session: no NV-CONTROL access to check the classic Xorg dithering
toggle (`nvidia-settings` can't reach it from a GNOME/Wayland session — Xwayland has no
NV-CONTROL extension), and the DRM connector's own properties (`modetest -c`, looking for a
`dither` property) can't be queried because the leased connector for the headset doesn't exist
until the panel is actually activated (`scripts/panel.py activate` + `hmd-vk` running).
Inconclusive — retract "xrizer's implementation dithers, Oasis's clips" as a design-choice
comparison. It is more likely a Linux/NVIDIA driver-stack behaviour difference from whatever
Windows's D3D/Oasis presentation path does, not a code choice either side made. If this is ever
worth chasing further, the next concrete step is probing the DRM connector's properties with
the panel active — not a code change to xrizer, since there is no xrizer code path that does
this to change.

## Standing status

`~/vr/logs/xrizer-brightness` and both `user-profiles.json` entries (`niko`, `AVGwmn`) read
exactly `1.0`, confirmed after this session's reboot back to Debian. Nothing to fix; the
practical rule from `docs/112` — never ship a gain other than 1.0 on the G2 — stands unchanged.
