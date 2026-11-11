# xrizer patches

Patches on top of xrizer `main` @ `6c3e45f4c18b014a7aba87282ee0677306315052` (on
`github.com/Supreeeme/xrizer`, not on the `The-personified-devil` fork). All 17 apply in order
(`applies-on-base.txt`, applied by `bootstrap-lab.sh sources`) and `cargo test --lib` passed on
2026-10-12 (88 tests). Build with `--features static-openxr`. xrizer is the working path for
SteamVR titles on this rig (`docs/23`, `docs/06`).

| # | What |
|---|---|
| 0001 | Global recenter: hold the real menu button for 3 s. Uses a dedicated `system_recenter` action, because `app_menu` on the `oculus/touch_controller` profile is the face buttons |
| 0002 | Alias the OpenVR-legacy `system` path to the `Menu` subpath, so a game that binds MENU to `system` gets a working menu |
| 0003 | Real HMD presence through `XR_EXT_user_presence` (`ShouldApplicationPause`, `IsInputAvailable`, HMD activity level were hardcoded stubs). Pairs with Monado 0075 `WMR_USER_PRESENCE=1`. Without the extension it degrades to the old behaviour |
| 0004 | Legacy input coexists with action manifests (two independent slots); short menu press passes through as `EVRButtonId::System`, a 3 s hold recenters. Fixes recenter being dead in manifest-loading titles |
| 0005 | Honest `GetFrameTiming` values (they were constants), and `GetFrameTimings` implemented (it was `todo!()`) |
| 0006 | Keeps the frame-timing history off the frame path (contention redesign of 0005) |
| 0007 | Optional digital brightness gain through `XR_KHR_composition_layer_color_scale_bias` on the projection layer. The gain is read from a file (`$HOME/vr/logs/xrizer-brightness` or `$XRIZER_BRIGHTNESS_FILE`), clamped `[0,4]`. **Keep it at 1.0**: other values cause dithering flicker (`docs/112`) |
| 0008 | External recenter trigger file (`$HOME/vr/logs/xrizer-recenter`, `$XRIZER_RECENTER_FILE`) for headset-only titles with no button to hold. Both Standing and Seated origins recenter, yaw only |
| 0009 | Opt-in recentre a few seconds after the headset is put on (flag file `$HOME/vr/logs/xrizer-recenter-on-don`), needs `XR_EXT_user_presence`. Titles that re-base their own 3DoF view only move a few degrees |
| 0010 | Recenter diagnostics in the log; `XRIZER_LOG_SERVED_YAW=1` logs the yaw served to the game |
| 0011 | Legacy action sync folded into the game's own `UpdateActionState` |
| 0012 | `is_active` and profile-state diagnostics |
| 0013 | Fixes 0004's binding clobber: the manifest's bindings were replaced by the legacy suggest for the same profile, so every manifest action read `is_active=false`. Legacy bindings are now folded into one suggest per profile (`docs/89`) |
| 0014 | 0013 broke upstream's `load_actions_race` test; the legacy branch now skips the sync while a manifest loads. A repeated `SetActionManifestPath` no longer restarts the session |
| 0015 | Frame-timing ring: a full-history reader never gets the slot being written, reads are re-validated |
| 0016 | The refresh-rate fallback returned seconds (0.011 for 90 Hz); it now returns Hz and assumes 90 until the period is known. A bug in xrizer's base code |
| 0017 | A bad `XRIZER_RECENTER_HOLD_SECS` no longer panics in `WaitGetPoses` |

0014-0017 come from the 2026-10-12 code review (`docs/147`); they are built and unit-tested
but not yet tested in a game.

## Titles with open xrizer problems (root causes found, not patched)

- **War Robots VR** waited on a "put on your VR helmet" prompt because presence was stubbed.
  0003 and Monado 0075 address it; confirm per title.
- **Poly Runner VR** retries an `IVRCompositor_013` request forever. That interface version
  never existed in any published OpenVR header (012 jumps to 014), so there is nothing to shim.
  The cause of the stuck retry loop is unknown.
- **Water Bears VR** recreates its swapchain every frame (`compositor.rs`, "recreating
  swapchain"), so `is_usable_swapchain()` never accepts what the game submits. Probably a
  per-eye bounds mismatch in `swapchain_info_for_texture`. Not root-caused further.
