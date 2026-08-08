# xrizer patches

Two patches on top of xrizer `main` @ `6c3e45f` (the SHA `~/vr/xrizer` was cloned at, see
`docs/06-known-issues.md` for the xrizer bring-up). Apply with plain `git am`, in order.

| patch | what |
|---|---|
| 0001 | Global recenter: hold the real menu button 3s to reset the play-space origin, since this reimplementation has no dashboard/vrmonitor to provide SteamVR's usual shortcut. Two real bugs found and fixed via live hardware testing before it worked: (1) the naive version reused the existing `app_menu` action, which on the `oculus/touch_controller` profile our WMR controllers present as is bound to the Y/B face buttons, not the real menu button -- fixed with a dedicated, game-invisible `system_recenter` action; (2) `reset_tracking_space(Standing)` was clobbering height/floor calibration on recenter -- fixed with a `preserve_height` flag, Standing-only. See `docs/pruebas.jsonl` T080 for the full session, including the earlier working commit that data-corrupted in-game input before the `system_recenter` fix. |
| 0002 | Alias the OpenVR-legacy `system` path to the already-legal `Menu` subpath in `DynSubpath::from_openvr_str`, one line, same precedent as the existing `application_menu` alias right above it. Root-caused why SUPERHOT's menu never opened despite raw input registering fine at the Monado level (confirmed live via `XRT_DEBUG_GUI=1`): its default `bindings_oculus_touch.json` offers only two sources for its MENU action -- a `long` press on X (input mode not implemented anywhere in xrizer, silently dropped by serde) and a click on `system` (never a recognized subpath string at all) -- so the action was permanently unbound, hundreds of `No active binding for SetupOpenAction (/actions/default/in/MENU)` lines per session in the game's own log. This patch fixes the `system` half only; `long` press detection is a separate, more invasive gap, not fixed. Confirmed live: rebuilt, the "no active binding" spam dropped to one transient line at startup, and the left controller's physical menu button now opens SUPERHOT's pause menu. Right hand untested/expected to still fail -- `Menu` is Left-only on this profile, matching real Oculus Touch hardware. See `docs/pruebas.jsonl` T082-T084. |

Found and root-caused, NOT yet patched here (real xrizer/Monado work, bigger than tonight's
session):

- **War Robots VR: The Skirmish hangs on a "put on your VR helmet" prompt post-calibration.**
  xrizer never implements HMD presence/worn detection at all (`ShouldApplicationPause` and
  `IsInputAvailable` in `src/system.rs` are hardcoded stubs). Monado's WMR driver
  (`wmr_hmd.c`) already reads the headset's real proximity sensor but never wires it into
  Monado's generic `XR_EXT_user_presence` support (present and working for other drivers,
  see `oxr_session.c`/`oxr_system.c`/`oxr_event.c`) -- `wmr_hmd.c` never sets
  `xdev->supported.presence = true`. A real fix needs both repos: Monado to surface the
  sensor, xrizer to consume it. See `docs/pruebas.jsonl` T078.
- **`IVRCompositor_013` warnings from Poly Runner VR are a dead end, not a real gap --
  and the actual failure mode is an infinite retry loop, not a clean exit.** Checked
  every OpenVR SDK header xrizer vendors (`openvr/headers/`, 0.9.12 through 2.15.6, the
  complete published history): Valve's own interface versioning skips straight from
  `IVRCompositor_012` to `IVRCompositor_014` -- version 013 never existed on any real
  SteamVR release either, so there's nothing to shim against. T072's original
  characterization ("dozens of warnings, then a clean self-exit") does not reproduce:
  retested twice in a row this session, both times the game gets stuck permanently at
  OpenXR session state `READY`, spamming the same "unknown interface" request in a tight
  loop (~1300 lines/sec, ~190% CPU, never advancing or exiting on its own -- had to be
  killed both times). The game itself keeps rendering normally in flat 2D the whole time
  (confirmed physically with the headset on), it just never enters stereo VR. Real root
  cause of the stuck retry loop is still unknown -- needs fresh investigation into why the
  client-side interface-negotiation retry never gives up. See `docs/pruebas.jsonl` T072
  (original, now-superseded diagnosis) and T085-T086 (this session's retest).
- **Water Bears VR recreates the swapchain every single frame, forever, and never
  stabilizes a presentable image.** `compositor.rs:1247` logs `recreating swapchain` for
  both eyes continuously (~65 cycles/sec, confirmed via line-count deltas over time),
  meaning `submit_impl`'s `is_usable_swapchain()` check never accepts what the game submits
  the frame after creating it. The game itself is healthy the whole time -- confirmed
  physically that its trigger gives audible feedback (input reaches it fine) and it renders
  normally to its own flat 2D mirror -- so this is purely a compositor-side bug, not input
  or session negotiation. Not root-caused further -- likely candidate is a per-eye
  texture/bounds mismatch (the game may submit one wide texture with different UV bounds
  per eye, and something about how `swapchain_info_for_texture` derives the effective
  per-eye size from those bounds may never converge). See `docs/pruebas.jsonl` T087.
