# xrizer patches

One patch on top of xrizer `main` @ `6c3e45f` (the SHA `~/vr/xrizer` was cloned at, see
`docs/06-known-issues.md` for the xrizer bring-up). Applies with plain `git am`.

| patch | what |
|---|---|
| 0001 | Global recenter: hold the real menu button 3s to reset the play-space origin, since this reimplementation has no dashboard/vrmonitor to provide SteamVR's usual shortcut. Two real bugs found and fixed via live hardware testing before it worked: (1) the naive version reused the existing `app_menu` action, which on the `oculus/touch_controller` profile our WMR controllers present as is bound to the Y/B face buttons, not the real menu button -- fixed with a dedicated, game-invisible `system_recenter` action; (2) `reset_tracking_space(Standing)` was clobbering height/floor calibration on recenter -- fixed with a `preserve_height` flag, Standing-only. See `docs/pruebas.jsonl` T080 for the full session, including the earlier working commit that data-corrupted in-game input before the `system_recenter` fix. |

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
- **`IVRCompositor_013` warnings from Poly Runner VR are a dead end, not a real gap.**
  Checked every OpenVR SDK header xrizer vendors (`openvr/headers/`, 0.9.12 through 2.15.6,
  the complete published history): Valve's own interface versioning skips straight from
  `IVRCompositor_012` to `IVRCompositor_014` -- version 013 never existed on any real
  SteamVR release either. The dozens of "unknown interface" warnings are near-certainly
  harmless version-probing by the game, not the actual reason its session exits shortly
  after. The real root cause is still unknown -- needs fresh log investigation, not an
  interface shim (there's nothing to shim against). See `docs/pruebas.jsonl` T072 (original,
  now-superseded diagnosis) and the correction this session.
