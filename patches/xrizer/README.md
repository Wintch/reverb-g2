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

## 0003 — real HMD presence via XR_EXT_user_presence (2026-08-18, T213 era)

`ShouldApplicationPause`, `IsInputAvailable` and the HMD branch of
`GetTrackedDeviceActivityLevel` were hardcoded stubs — any title gating on worn
state (War Robots VR's un-skippable "put on your VR helmet", docs/03) was stuck
forever. Now: `ext_user_presence` requested opportunistically, the central event
pump catches `UserPresenceChangedEXT` into a cached `AtomicBool`, and all three
surfaces consult it. A runtime without the extension degrades to exactly the old
hardcoded behavior. **Pairs with monado 0075 (`WMR_USER_PRESENCE=1`)** — the G2's
nose-bridge proximity sensor feeds Monado's generic presence machinery. The
`proximity != 0` threshold is provisional; the first live don/doff with logging
calibrates it. Showcase value: doff-to-pause/attract-mode. cargo clean, 83/83 tests.

## 0004 — legacy input coexists with manifests + menu pass-through (2026-08-18, docs/49)

The Blade Runner 9732 diagnosis implemented. **Fix 1**: `InputSessionData` held a
single `OnceLock<LoadedActions>` (Legacy XOR Manifest) — structurally nowhere to
serve legacy button state once a title loaded a manifest, and
`get_legacy_controller_state` hard-returned `false` forever after. Now two
independent slots; the legacy set attaches IN THE SAME `attach_action_sets` call
as the manifest's (OpenXR attach-once), synced every frame. **Bonus discovery**:
the hold-3s recenter (0001) was only reachable from the legacy-only branch — it
was silently DEAD in every manifest-loading title (explains SafeZoneVR's
never-firing recenter); now runs always. **Fix 2**: short menu presses pass
through to games via `EVRButtonId::System` (advertised in every profile's mask,
never populated); a 3s hold fires recenter and force-clears the exposed value the
same frame. 84+1 tests pass (2 added, 2 rewritten that pinned the old buggy
model). Known cost: one extra `sync_actions` per frame for manifest titles.
Commit `48fc243`. **Hardware validation pending**: Blade Runner 9732 buttons +
SUPERHOT menu + a recenter check in any manifest title.

## 0005 — real frame timing (2026-08-18, T217-T219) — REVERTED ON TOP, returns with a lock redesign

`GetFrameTiming` filled `Compositor_FrameTiming` with hardcoded constants
(`TotalRenderGpu=9.0` → OpenVR Benchmark's eternal fictional 111.11 = 1000/9.0,
identical at every resolution and load — T217/T218). 0005 implements honest values
(real WaitGetPoses interval, real blocked wait, real Submit copy time, real
xrEndFrame time; honest zeros for the unmeasurable; 128-entry ring buffer;
`GetFrameTimings` implemented — was a `todo!()` that PANICKED callers; `frames_ago`
honored; `m_nNumDroppedFrames` finally written — games read stack garbage before).
**Proved measurement works**: first real varying scores in stack history (4.66
warm-up → 19.25 avg / 9.80 low). **Reverted on top** (`782e72b`) pending a
contention-free redesign: the metrics mutex sits in the frame path while benchmarks
hammer `GetFrameTiming` every frame — a real contention shape, though T219 proved it
was NOT that night's freeze (the second-run wedge reproduces on the stub build too;
that bug is the XR-session-re-cycle suspect, separate). Bring 0005 back with
atomics/seqlock or out-of-frame-path ring writes. Commits `d467454` + revert `782e72b`.

## 0007 — digital brightness gain (2026-08-27)

The G2 panel backlight cannot be set from any host — no HID command exists, Windows
included (re-verified three ways: Monado's WMR command set, the Oasis driver disassembly,
the headset calibration blob — see the repo's brightness investigation and `docs/09`/`docs/12`).
Instead, multiply the game's own composited RGB via Monado's
`XR_KHR_composition_layer_color_scale_bias`, attached to the **projection** layer (Monado
implements it there — `oxr_session_frame_end.c` — and xrizer already negotiates the
extension; it just only used it for overlay alpha before). Same raw-pointer next-chain
splice as `overlay.rs::set_alpha`. Applied after the game renders, before scanout, so it
works for any closed-source Steam title. Gain is read from a dashboard-controlled file
(`$HOME/vr/logs/xrizer-brightness`, or `$XRIZER_BRIGHTNESS_FILE`), re-read every ~30 frames
to stay off the per-frame hot path, clamped `[0,4]`; `1.0` disables the layer entirely. The
status dashboard's per-user command centre writes that file (brightness slider). Build with
the same `--features static-openxr` as the rest of the lab tree. Commit `05afead`.

## 0008 — external recenter trigger file (2026-08-29)

Headset-only titles (Dreams of Dalí, the booth's 6dof title) have no button to hold for the
0001 shortcut, and a booth guest sits 1–2 m from wherever Basalt happened to start the session
(docs/80 "the anchor test"). Same mechanism as 0007's brightness file: the status dashboard's
**🎯 Recentrar** button touches `$HOME/vr/logs/xrizer-recenter` (override `$XRIZER_RECENTER_FILE`);
`OpenXrData::poll_recenter_trigger`, called from `Compositor::WaitGetPoses` every frame for every
title (NOT from `Input::frame_start_update`, which only exists once a game asks for IVRInput — the
first draft lived there and was moved after review), checks every ~30th call, removes the file and
recenters **both** Standing (floor height kept) and Seated (head height) origins on the current
head pose, yaw only — stronger than SteamVR, which never moves Standing, because the STAGE origin
here is arbitrary and the title's universe is unknown. Guards: triggers older than 10 s are
discarded (a touch with no title running cannot recenter the next launch — verified: "25.3 s old
-- stale, discarded"); a non-FOCUSED session leaves the file in place (Dalí tears its bootstrap
session down ~30 ms after the first frame); with `XR_EXT_user_presence` enabled a doffed headset
ignores it; and `reset_tracking_space` now refuses a head pose without POSITION/ORIENTATION_VALID
(covers 0001 and `ResetSeatedZeroPose` too). Worn-validated 2026-08-29 15:50–15:59 on Dalí via the
booth button: wearer turned 90° left, operator pressed, the scene came round to the front, 0.2–0.3 s
from POST to the xrizer log line. Build with `--features static-openxr`. Commit `4090f8e`.
