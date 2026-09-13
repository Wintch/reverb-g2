# 123 — OpenVR vrpath trap recurrence (#2) + Dalí 250 W scale85-vs-scale100 re-sweep, completed

Date: 2026-09-13

## Context

The GPU swapped back to a 250 W-cap card on 2026-09-10/11 (see `docs/112`/hardware inventory
memory), but the scale85-vs-scale100 re-sweep this was meant to enable never completed that
night — every attempt was blocked by the OpenVR vrpath-priority trap (`docs/120`). Today's
session picked this back up after a machine reboot and an unrelated Oasis/Ignition compositor
survey (`docs/121`/`docs/122`).

## Recurrence #2 of the vrpath trap — and a real process failure caught by the wearer

Attempting the resweep, Monado's own bring-up log looked completely clean: 5/5 USB devices, DRM
lease granted, native `4320x2160@90.00`, "lanzando Dreams of Dali" with no errors. This was
initially reported as a working VR session on that evidence alone — **that was wrong**. The
wearer caught it live ("pero ojo que no arranco en vr, revisa bien"), not any log check.

Investigation:
- `jack-in-wayland.log` had **zero** "Delivered frame" lines; only brief `wineopenxr test
  instance` probe connect/disconnect cycles.
- A targeted screenshot of the actual game window (`xwininfo` + `import -window`) showed Dalí
  rendering flat/2D on the desktop monitor at 454 fps — no VSync/VR pacing at all.
- Dalí's own Unity player log
  (`.../compatdata/591360/pfx/.../Dreams of Dali/output_log.txt`) had:
  `XR: OpenVR Error! OpenVR failed initialization with error code
  VRInitError_Init_InterfaceNotFound: "Interface Not Found (105)"!`
- `~/.config/openvr/openvrpaths.vrpath`'s `"runtime"` array had drifted back to SteamVR-first
  (`["…/SteamVR", "…/xrizer/target/release"]`) — the exact same trap as `docs/120`
  (2026-09-11), recurring.

**Trigger, this time**: plausibly the same day's heavy SteamVR-adjacent activity from the
Oasis/Ignition compositor survey (X11/GNOME/KDE/Sway testing all exercise the SteamVR/OpenVR
stack). This reinforces that any session touching SteamVR heavily — not just a Steam client
"update everything" pass — is a plausible trigger for this to recur.

**Fix**: same one-liner as `docs/120` — `bash scripts/sanity-check.sh soft --fix-vrpath`
(backs up to `.bak-20260913-152149`, reorders `runtime[]` so any xrizer-containing path sorts
first), plus a full Steam client shutdown+relaunch (a foreground game process won't pick up the
reordered file on its own). `/usr/games/steam -shutdown` over plain SSH silently does nothing —
it needs the real GUI session environment (`DISPLAY`/`WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR`/
`DBUS_SESSION_BUS_ADDRESS`), sourced here from `gui_env.py`'s `get()` dict passed as
`subprocess.run(..., env=...)`.

**Confirmed working, end-to-end, this time** (the one gap `docs/120` left open): post-fix,
delivered-frame count climbed steadily rather than staying flat, `app-fps.sh` read a sustained
~89-90 fps across multiple windows, and the wearer directly confirmed "perfecto, jugando."

**General lesson, worth restating**: a clean Monado/USB/DRM-lease bring-up log only proves the
compositor side came up — it is not evidence the actual OpenVR/OpenXR game session rendered.
Always additionally check for real "Delivered frame" line *growth* (not just presence — a brief
probe connect/disconnect can log a couple of lines with zero real rendering), or a physical/
visual check, before reporting a VR session as working.

## Dalí scale85-vs-scale100 re-sweep at the restored 250 W cap

Method: real worn play sessions, `power-log.sh 2 240` (240 s @ 2 s sampling, GPU + CPU-package
draw) + `app-fps.sh` (delivered-frame rate read from Monado's own pacer log,
`U_PACING_APP_LOG=debug`) per arm, with a clean Dalí/wineserver/monado-service teardown between
arms.

| Scale | GPU avg | CPU pkg avg | Total machine-side | Delivered fps |
|---|---|---|---|---|
| **85 %** (shipped default, commit `61d4b34`) | 210.6 W | 71.9 W | **282.5 W** | ~89.8-89.9 |
| **100 %** | 227.1 W | 71.7 W | **298.8 W** | ~89.4-89.8 |

**Conclusion**: at the restored 250 W cap, scale100 no longer gets throttled the way it did on
the 210 W-capped card (`docs/113`'s 2026-09-07 finding: scale100 only held ≥89 fps in 2 of 8
windows there). Here, 227 W stays comfortably under the 250 W cap and both profiles hold ~90 fps
solidly. The remaining difference is purely one of efficiency: scale85 draws ~16 W GPU
(~16 Wh/hour of play) less than scale100 for no measurable fps difference, since both profiles
already sit at the 90 Hz refresh-rate ceiling.

**Decision**: no change to the shipped profile. `TITLE_PROFILES["591360"]`'s scale85 stays the
default, on efficiency grounds (see the hardware-efficiency philosophy memory: tune to the
measured efficient point, not factory-max) — not because scale100 is unusable on this card, but
because there is nothing to buy back by running it hotter.

**Process note**: this is the second time a GPU swap has silently invalidated a prior fps/power
sign-off (the first was `docs/113`'s 210 W finding after the 2026-09-07 swap). Re-run this exact
sweep after any future card change rather than assuming either verdict still holds.

See also: `docs/120` (the vrpath trap's first occurrence), `docs/113` (the 210 W-capped finding
this supersedes for the current card), `docs/112`/hardware inventory (the GPU swap history).
