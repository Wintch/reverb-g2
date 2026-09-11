# 120 — the T174 OpenVR vrpath trap recurred via a Steam client update, and cost a whole night

## Summary

Dreams of Dalí (591360) launched, Steam showed "App Running", `DreamsOfDali.exe` ran under
Proton — but nothing appeared in the headset, only a flat 2D window on the desktop monitor.
This is the T174 trap from `CLAUDE.md` (found 2026-08-13): `~/.config/openvr/openvrpaths.vrpath`
had SteamVR's own path ahead of xrizer's in `"runtime"`, so OpenVR loaded SteamVR's `vrclient`
instead of xrizer, found no session, and every OpenVR title silently fell back to flat rendering.
`scripts/sanity-check.sh` already had a check for exactly this — it just wasn't run early enough.

**New information this time**: the trigger wasn't T170's parked SteamVR-native experiment (the
original 2026-08-13 cause). It was a plain **Steam client "update everything" pass**, run the
evening before to clear an unrelated shader-cache-sweep delay. `SteamVR`'s own
`appmanifest_250820.acf` shows `LastUpdated` matching that exact window, and its
`bin/linux64/vrclient.so` was rewritten then too — the update re-registered SteamVR and knocked
it back ahead of xrizer in the vrpath list. **T174 is a recurring class of bug, triggerable by
any Steam update that touches the SteamVR app — not a one-off from a specific 2026-08-13
experiment.**

## Timeline (2026-09-10 22:00 -03 through 2026-09-11 09:00 -03, condensed)

A single session chased this symptom for hours through several genuinely real, but ultimately
unrelated, side issues before reaching the actual cause:

1. Dev's GPU had been swapped back to a non-LHR RTX 3060 Ti (see `reference_hardware_inventory`
   in the assistant's memory system, or ask the user) — confirmed fine, not the cause.
2. Steam's own cold-boot shader-cache sweep across unrelated library titles delayed the first
   `-applaunch` by ~10 minutes — real, but resolved itself once Steam warmed up / the user ran
   a manual update pass. Not the cause of the flat-2D symptom.
3. The G2's USB dropped to 0/5 devices at one point (a `reference_g2_usb_port_fault`
   recurrence, PC-end reconnect fixed it) — real, unrelated.
4. Multiple clean jack-in + Dalí relaunches, each reaching Steam's "App Running" state, each
   still showing flat 2D with 0 "Delivered frame" lines in Monado's log and 0 sustained
   OpenXR/OpenVR client connections (only brief loader probes).
5. Only after reading Dalí's own Unity log did the real error surface:
   `XR: OpenVR Error! OpenVR failed initialization with error code
   VRInitError_Init_InterfaceNotFound: "Interface Not Found (105)"!`
   — found at
   `<compatdata>/591360/pfx/drive_c/users/steamuser/AppData/LocalLow/Half Full Nelson/
   Dreams of Dali/output_log.txt`.
6. That error, plus "App Running but 0 delivered frames, 0 sustained client connections",
   is the T174 signature. `~/.config/openvr/openvrpaths.vrpath`'s `runtime[0]` was SteamVR's
   path, not xrizer's — confirmed by direct inspection.
7. Fixed by reordering `runtime[]` (xrizer's path first), restarting Steam, relaunching Dalí.
   Confirmed fixed: the fatal `VRInitError_Init_InterfaceNotFound` was replaced by a benign
   `VRChaperoneSetup failed initialization with error code (null)` warning (no room boundary
   configured — harmless, doesn't block rendering), and Monado logged new client connections.
   **Not confirmed with a live wearer check** — the session ended (rig powered down) right
   after the log-level confirmation.

## Root-cause chain

```
Steam client "update everything" (2026-09-10 evening)
        │
        ▼
SteamVR app re-updates/re-registers itself (appmanifest_250820.acf LastUpdated,
bin/linux64/vrclient.so rewritten at the same timestamp)
        │
        ▼
~/.config/openvr/openvrpaths.vrpath's "runtime" array gets SteamVR prepended
ahead of xrizer (T174 mechanism, CLAUDE.md)
        │
        ▼
Any OpenVR-API title (Dalí via Oculus Utilities/OVRPlugin, NOT OpenXR-native)
loads SteamVR's real vrclient instead of xrizer's shim
        │
        ▼
VRInitError_Init_InterfaceNotFound (105) inside the game's own Unity/engine log
        │
        ▼
Game falls back to flat 2D rendering, audio may still route to the headset,
Monado's own log stays clean (0 delivered frames, 0 sustained clients) because
Monado was never actually reached
```

## What changed in the repo because of this

- **`scripts/sanity-check.sh`**: the existing "OpenVR runtime routing" check (soft stage) now
  accepts `--fix-vrpath` — when the check fails, it backs up
  `~/.config/openvr/openvrpaths.vrpath`, reorders `runtime[]` so every xrizer path sorts first,
  and reports the new order. Tested end-to-end on dev (2026-09-11): deliberately broke the file,
  ran `./scripts/sanity-check.sh soft --fix-vrpath`, confirmed it healed and reported READY.
  **Restarting Steam is still required afterward** — an already-running game process has already
  read the old order and won't pick up the fix without a relaunch.
- **`CLAUDE.md`**'s T174 entry: updated to note the two confirmed trigger mechanisms (T170's
  parked experiment, and this Steam-update recurrence) and point here.

## The actual lesson (see `feedback_localise_before_theorising` in the assistant's memory)

For a **"game launches (process exists, Steam says App Running) but nothing shows in the
headset, and Monado's own log shows 0 delivered frames and 0 sustained client connections"**
symptom specifically:

1. Check the game/app's own engine log FIRST (Unity: `output_log.txt` under
   `<compatdata>/<appid>/pfx/drive_c/users/steamuser/AppData/LocalLow/<company>/<game>/`) for an
   `XR:` or `OpenVR`/`OpenXR` error line, before chasing Monado/USB/GPU/compositor theories.
2. Run (or grep) `scripts/sanity-check.sh`'s "OpenVR runtime routing" check — it already exists
   and would have named this in seconds. As of this doc it can also fix itself
   (`soft --fix-vrpath`).
3. Only pursue Monado/USB/GPU-side theories once the app's own log confirms it actually
   reached the point of talking to the runtime and failed there — Dalí's log made this
   distinction instantly (`XR: OpenVR Error!` fires before any Monado-side symptom would even
   be relevant).

A rig with this much written history (see `CLAUDE.md`'s traps section) usually already has a
named check for the exact shape of a recurring symptom. Grep it before re-deriving it by hand.
