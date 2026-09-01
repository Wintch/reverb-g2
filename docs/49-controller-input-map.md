# HP Reverb G2 controller input map, and the legacy-API buttons-dead bug

Sources read for this document: `~/vr/monado` — `src/xrt/drivers/wmr/wmr_controller_hp.c`
(HID packet parser, HP/G2-specific), `wmr_controller_base.c` (shared fusion/pose/binding
plumbing), `src/xrt/include/xrt/xrt_defines.h` (`XRT_INPUT_G2_CONTROLLER_*` enum),
`src/xrt/auxiliary/bindings/bindings.json` (OpenXR profile definitions Monado ships).
`~/vr/xrizer` — `src/input/profiles/oculus_touch.rs`, `src/input/legacy.rs`, `src/input.rs`,
`src/input/action_manifest.rs`, `src/system.rs`. Also `docs/03-controllers.md` (this repo)
and live wearer reports from tonight's session.

No code was changed to produce this document.

## 1. Physical control inventory (G2 controller, HID packet layout)

`wmr_controller_hp_packet_parse()` (`wmr_controller_hp.c:272`) reads a fixed 44-byte
report. Two separate "buttons" bytes carry booleans:

**Buttons byte 1** (offset 0, first byte of the report):
| bit | field | meaning |
|---|---|---|
| 0x01 | `thumbstick.click` | thumbstick pressed down |
| 0x02 | `home` | **Windows-logo button** (the round button — power/wake, see §3) |
| 0x04 | `menu` | hamburger **Menu** button |
| 0x08 | `squeeze_click` | grip reported as "fully squeezed" by the controller's own firmware (not a separate mechanical detent — see comment at `wmr_controller_hp.c:289`) |
| 0x20 | `bt_pairing` | hidden pairing-mode signal — **parsed but never forwarded** to `xrt_inputs` in `wmr_controller_hp_update_inputs()` (`wmr_controller_hp.c:578-610`); dead-ends inside the driver |

**Buttons byte 2** (after trigger/squeeze-value bytes, "on HP it's squeeze value and
A_X/B_Y click", comment at `wmr_controller_hp.c:318`):
| bit | field | meaning |
|---|---|---|
| 0x01 | `y_b` | upper face button (Y on left, B on right) |
| 0x02 | `x_a` | lower face button (X on left, A on right) |

Analog fields: `trigger` (0-255 → 0.0-1.0), `squeeze` (0-255 → 0.0-1.0), `thumbstick.x/y`
(12-bit, centered/clamped, then `wmr_controller_base_apply_stick_autocenter` +
`wmr_controller_base_apply_stick_deadzone`), plus the IMU (accel/gyro/temperature/ticks)
used for orientation, not exposed as a button.

## 2. Full mapping table

`wmr_controller_hp_create()` (`wmr_controller_hp.c:663`) names every input
`XRT_INPUT_G2_CONTROLLER_*` (`xrt_defines.h:1105-1117`) and registers three
`binding_profiles` (`wmr_controller_hp.c:168-190`) that let an OpenXR app request a
*different* interaction profile and have Monado remap it onto the real G2 inputs:
`XRT_DEVICE_TOUCH_CONTROLLER` (oculus/touch_controller), `XRT_DEVICE_SIMPLE_CONTROLLER`
(khr/simple_controller), `XRT_DEVICE_WMR_CONTROLLER` (microsoft/motion_controller, the
"native" one). xrizer requests the **oculus/touch_controller** profile (it self-identifies
controllers as `openvr_controller_type: "oculus_touch"`, `oculus_touch.rs:34`), so the
Touch remap column is what actually matters end-to-end on this project.

| Physical control | HID field | Monado `xrt_input` name | OpenXR path (native `microsoft/motion_controller`) | OpenXR path (`oculus/touch_controller` remap, what xrizer uses) | xrizer modern Input API (action manifest) | xrizer **legacy** `IVRSystem::GetControllerState` |
|---|---|---|---|---|---|---|
| Trigger (analog) | `trigger` | `XRT_INPUT_G2_CONTROLLER_TRIGGER_VALUE` | `/input/trigger/value` | `/input/trigger/value` | any float/bool action bound to trigger | `rAxis[1].x`; also drives `SteamVR_Trigger` bit (`Trigger`→click-thresholded, since `translate_path` in `oculus_touch.rs:62-71` forces a `Click` request on Trigger/Squeeze to read `Value`) |
| Grip/squeeze (analog) | `squeeze` | `XRT_INPUT_G2_CONTROLLER_SQUEEZE_VALUE` | `/input/squeeze/value` (WMR profile has no analog squeeze — see below) | `/input/squeeze/value` | any float/bool action | `rAxis[2].x`; also drives `Grip` **and** `Axis2` bits (both read from the same `squeeze_click` legacy action, `legacy.rs:279-280`) |
| Grip/squeeze (firmware full-squeeze flag) | `squeeze_click` | `XRT_INPUT_G2_CONTROLLER_SQUEEZE_CLICK` | `/input/squeeze/click` | *(no discrete click path on Touch — `translate_path` collapses Click→Value)* | not directly reachable via oculus_touch profile | not read directly; xrizer's `Grip`/`Axis2` legacy bits come from the *Value* action instead (see row above) |
| Thumbstick (analog XY) | `thumbstick.values` | `XRT_INPUT_G2_CONTROLLER_THUMBSTICK` | `/input/thumbstick` (position) | `/input/thumbstick` | any vec2 action | `rAxis[0]` |
| Thumbstick click | `thumbstick.click` | `XRT_INPUT_G2_CONTROLLER_THUMBSTICK_CLICK` | `/input/thumbstick/click` | `/input/thumbstick/click` | any bool action | `Axis0` bit (`legacy.rs:267-271`), touch state also feeds `ulButtonTouched` |
| Face button, lower (X-left / A-right) | `x_a` | `XRT_INPUT_G2_CONTROLLER_X_CLICK` (left) / `..._A_CLICK` (right) | *not exposed* (native WMR profile has no face buttons) | `/input/x/click` (left) / `/input/a/click` (right) | any bool action | `A` bit, from legacy action `a`, bound `Left<X,Click> \| Right<A,Click>` (`oculus_touch.rs:92-96`) |
| Face button, upper (Y-left / B-right) | `y_b` | `XRT_INPUT_G2_CONTROLLER_Y_CLICK` (left) / `..._B_CLICK` (right) | *not exposed* | `/input/y/click` (left) / `/input/b/click` (right) | any bool action | `ApplicationMenu` bit, from legacy action `app_menu`, bound `Left<Y,Click> \| Right<B,Click>` (`oculus_touch.rs:86-90`) |
| Menu (hamburger) | `menu` | `XRT_INPUT_G2_CONTROLLER_MENU_CLICK` | `/input/menu/click` | `/input/menu/click` (left) **or** `/input/system/click` (right) — Monado ORs `MENU_CLICK` and `HOME_CLICK` into both (`wmr_controller_hp.c:109-116`) | reachable if a manifest binds it | **not surfaced to games at all** — xrizer's `system_recenter` action consumes `Left<Menu,Click>` internally for the hold-3s recenter shortcut and is deliberately never read by `get_legacy_controller_state` (`legacy.rs:308-314`) |
| Windows/Home (round logo) | `home` | `XRT_INPUT_G2_CONTROLLER_HOME_CLICK` | *not exposed* (no native WMR path for it) | merged into `/input/menu/click` (left) / `/input/system/click` (right), same OR as above | same as Menu row | same as Menu row — **also consumed internally for recenter, never reaches a game**, on either physical button |
| Pairing button (battery compartment) | `bt_pairing` | *(none — dropped in the driver)* | — | — | — | — |
| Grip pose | IMU fusion + constellation | `XRT_INPUT_G2_CONTROLLER_GRIP_POSE` | `/input/grip/pose` | `/input/grip/pose` | pose action | the `pose` output param of `GetControllerStateWithPose` (only; `GetControllerState` alone has no pose) |
| Aim pose | same, offset | `XRT_INPUT_G2_CONTROLLER_AIM_POSE` | `/input/aim/pose` | `/input/aim/pose` | pose action | **no legacy equivalent** — OpenVR's old API has one pose per device index, not a separate aim/pointer pose; that concept is modern-Input-only |
| Haptic | — | `XRT_OUTPUT_NAME_G2_CONTROLLER_HAPTIC` | `/output/haptic` | `/output/haptic` | `TriggerHapticVibrationAction` | `TriggerHapticPulse` → `Input::legacy_haptic` (`legacy.rs:110`) |
| Battery | `battery` (raw byte, scale unverified) | *(not an `xrt_input`)* | — | — | — | not implemented; `get_battery_status` (`wmr_controller_hp.c:613`) exists but isn't wired to any OpenXR/OpenVR extension yet (docs/pruebas.jsonl, controller-battery thread) |

Notes:
- `EVRButtonId::System` is **never set** by xrizer's legacy state (it isn't in the
  `read_button(...)` call list, `legacy.rs:267-280`) — this matches real SteamVR, which also
  reserves the System button for the dashboard/compositor and never lets a game see it. Not
  a bug.
- The G2's real hardware grip has no separate mechanical click-detent; `squeeze_click` is a
  firmware-derived "fully squeezed" flag on the analog sensor, and even that only reaches
  the *native* WMR OpenXR profile — the Touch remap Monado exposes to xrizer collapses any
  squeeze "click" request straight to the analog value (`oculus_touch.rs:62-71`), so both the
  modern action and the legacy `Grip`/`Axis2` bits are really a thresholded read of the
  analog squeeze channel, not a discrete HID bit.

## 3. User-facing hardware behaviors (reported live, cross-checked against docs/03)

- **Wake / power-on**: hold the **Windows-logo button** (the `home` HID bit above) for
  ~3 seconds. This is also the button used to start Bluetooth-radio pairing mode
  (`docs/03-controllers.md` §"Pairing", confirms "turn on the controller (Windows
  button)"); a *separate*, physically hidden button inside the battery compartment
  (`bt_pairing` bit) is what actually puts the controller into discovery mode, held until
  the LED pulses slowly — the Windows-logo button only wakes/powers it.
- **Auto-sleep**: ~15 minutes motionless → controller powers itself off (LED off), and its
  constellation solves degrade to garbage near-origin poses just before that point (§"Auto-
  sleep / standby", `docs/03-controllers.md:295-319`). Believed to be ordinary
  Bluetooth-controller power management (same pattern as Touch/Vive-wand/PSVR controllers),
  not a defect — but no HID command for the sleep transition itself has ever been captured
  from this project's own data, so that's an informed inference, not a measured protocol
  fact.
- **Re-wake after auto-sleep**: pressing the Windows-logo button re-attaches an
  already-registered controller mid-session with **no Monado/service restart needed**
  (distinct from the unrelated no-hot-add limitation for *unregistered* devices at startup,
  T043).
- **Power-off gesture**: not discoverable anywhere in `docs/03`, `docs/12`
  (protocol reference), or the driver — there is no known explicit "hold X to power off"
  HID command or gesture documented for this project. The only power-down path ever
  observed is the ~15-minute auto-sleep timer.
- **Keepalive prototype**: `WMR_CONTROLLER_KEEPALIVE_S` (`wmr_controller_base.c:611-693`,
  default off, unvalidated) periodically resends the two connect-time enable commands to try
  to postpone the sleep timer via host traffic — explicitly not confirmed to work, since the
  sleep timer may be purely motion/IMU-gated on the controller's own side.

## 4. GOAL 2 — diagnosing "movement works, buttons dead" on a legacy-API OpenVR title

### 4.1 Two mutually-exclusive input paths inside xrizer

xrizer has two independent ways to answer an app's controller-state query, and today's
implementation treats them as **an exclusive switch, not a fallback chain**:

1. **Modern Input API**: the app calls `IVRInput::SetActionManifestPath`
   (`input.rs:1205`). This unconditionally sets
   `session_data.input_data.actions` to `LoadedActions::Manifest(...)`
   (`action_manifest.rs:242-245`) and attaches the manifest's action sets to the OpenXR
   session (`action_manifest.rs:161-170`, `attach_action_sets(&xr_sets)` — note `xr_sets`
   contains only the manifest's own sets, `pose_data.set`, `info_set`, `haptic_set`,
   `skeletal_input.set`; **the legacy action set is never in that list**).
2. **Legacy API**: `IVRSystem::GetControllerState`/`GetControllerStateWithPose`
   (`system.rs:369-406`) call `Input::get_legacy_controller_state` (`legacy.rs:179`), which
   reads from a *separate* `LegacyActionData` action set, lazily created and attached by
   `Input::setup_legacy_actions` (`input.rs:1541`, called from `frame_start_update` the
   first time a game's per-frame update runs with no manifest loaded yet).

OpenXR only allows `xrAttachSessionActionSets` to be called **once** per session. That's why
these two paths can't just coexist today: whichever one attaches first "wins" for that
session generation. `SetActionManifestPath` handles the legacy→manifest transition by
restarting the session (`input.rs:1213-1220`) — but the *reverse* is never handled, and
nothing ever attaches both together.

### 4.2 The exact failure mechanism

`get_legacy_controller_state` (`legacy.rs:200-204`):

```rust
let data = self.openxr.session_data.get();
if data.input_data.get_loaded_actions().is_some() {
    debug!("not returning legacy controller state due to loaded actions");
    return false;
}
```

**If a manifest has ever been loaded in the session, `GetControllerState` returns `false`
unconditionally, for the rest of the session — including 0/false/zeroed output via the
`WriteOnDrop` guard.** This is not a partial degradation; it is a hard, permanent cutoff.

This matches the reported symptom exactly **if Blade Runner 9732 calls
`SetActionManifestPath` at some point** (even if its actual gameplay input loop never calls
`IVRInput::GetDigitalActionData`/`GetAnalogActionData` and instead polls
`GetControllerState` directly for the trigger/grip/buttons it cares about). This is a real,
known-in-the-wild pattern: engines/wrappers built on the legacy SteamVR Unity plugin (v1,
pre-Input-System) or on the classic OpenVR C++ sample (`hellovr_opengl`) commonly register a
default/stub action manifest defensively (some SteamVR versions warn or degrade features
without one) while the actual per-frame button polling still goes through
`OpenVR.System.GetControllerState()`/`vr::VRSystem()->GetControllerState()`. Real SteamVR
tolerates this fine because it keeps legacy binding support live regardless of whether a
manifest is also attached; xrizer's mutual-exclusivity model does not.

### 4.3 Why movement survives while buttons die

Pose/tracking does **not** go through this gate:

- `IVRSystem::GetDeviceToAbsoluteTrackingPose` (`system.rs:852-865`) calls
  `Input::get_poses` directly — no reference to `get_loaded_actions()` or the legacy action
  set at all.
- The compositor's `WaitGetPoses` path (`compositor.rs:880-916`) calls
  `input.frame_start_update()` then `GetLastPoses` every frame, same story.

So a title using the classic "poll `GetDeviceToAbsoluteTrackingPose` once for all devices,
poll `GetControllerState` separately for buttons" pattern (the pattern in Valve's own
`hellovr` sample that many homebrew/fan-recreation OpenVR titles — plausibly including a
from-scratch "Deckard's apartment" project — are built around) gets **exactly** the reported
split: tracking/movement keeps working through a path this bug never touches, buttons go
through the one path that's permanently cut off.

The one title-shape this diagnosis does *not* cover on its own: a game that calls only the
combined `GetControllerStateWithPose` (`system.rs:369-396`) would lose pose too, since that
function literally returns early if the internal `GetControllerState` call fails
(`system.rs:383-395`). Since the report says pose survives, Blade Runner is very likely
calling the two APIs separately, or getting pose via the compositor path.

### 4.4 Commit `5df8023` — related codebase, unrelated bug

`5df8023` ("input: alias legacy 'system' path to the Menu subpath") touches
`profiles/oculus_touch.rs`'s `DynSubpath::from_openvr_str`, which parses **OpenVR-legacy-style
path strings inside a game-supplied action *manifest* binding JSON** (the modern
`SetActionManifestPath` flow) so that a source like
`/user/hand/*/input/system/click` resolves to the real Menu-adjacent action when a game's
own binding file uses that legacy naming convention. It fixed SUPERHOT's manifest-defined
MENU binding never resolving.

It does **not** touch `legacy.rs` or `get_legacy_controller_state` at all, and has no
bearing on the buttons-dead bug: that gate fires whether or not any manifest binding string
ever mentions "system" — it fires purely because a manifest was loaded at all. If Blade
Runner also ships an action manifest with unresolved bindings, `5df8023`-style path
aliasing could matter for *that* manifest's own actions, but it would not restore
`GetControllerState` — that call is dead regardless of what the manifest contains, once
loaded.

### 4.5 How to confirm from a real log before fixing anything

xrizer logs to `~/.local/state/xrizer/xrizer.txt` (`lib.rs:102-149`, `env_logger`, default
level `Info`). Two lines settle this diagnosis directly:

- `info!("loading action manifest from {path:?}")` (`input.rs:1211`) — **visible at default
  log level** — presence proves Blade Runner does call `SetActionManifestPath`.
- `debug!("not returning legacy controller state due to loaded actions")` (`legacy.rs:202`)
  — needs `RUST_LOG=debug` (or `RUST_LOG=xrizer=debug`) set before launch — presence, firing
  every frame the game polls `GetControllerState`, is the direct proof of the cutoff in
  action.

If the manifest-load line is **absent** and buttons are still dead, the mechanism above does
not apply and the real cause is more likely that `setup_legacy_actions` never got its first
call at all (e.g. the game never drives `WaitGetPoses`, so `frame_start_update` never
executes) — a different, not-yet-investigated bug.

## 5. Fix specification (IMPLEMENTED 2026-08-18, commit `48fc243`)

**Status update (2026-08-31, docs/89):** confirmed via `git blame` that xrizer's
`src/input/legacy.rs` already carries this fix — `get_legacy_controller_state` no longer has
the unconditional `get_loaded_actions().is_some() → return false` early exit, the legacy set
is created/attached/synced from both `setup_legacy_actions` and `load_action_manifest`
(see `get_or_create_legacy_actions`'s own doc comment, which narrates the same fix), and a
regression test (`legacy_input_still_works_with_manifest`) pins both halves of it. The
subsections below are kept as the original design record; treat them as history, not a
TODO. This bug is NOT the explanation for Aircar's dead-VR-controller-buttons symptom
(docs/89) — that title's buttons stay dead for a different, still-unresolved reason.

Goal (as originally written, now met): let `GetControllerState`/`GetControllerStateWithPose`
keep working even after a manifest has been loaded, for titles that mix both APIs, without
breaking modern-API-only
titles.

### 5.1 Changes needed

1. **`action_manifest.rs:161-170`** — when building `xr_sets` for
   `session.attach_action_sets(&xr_sets)`, also include the legacy action set (create it via
   `LegacyActionData::new` first if it doesn't exist yet for this session, and call
   `suggest_interaction_profile_bindings` for it before this attach point, same as
   `setup_legacy_actions` already does today). Both the legacy bindings and the manifest's
   bindings must be suggested **before** the single `attach_action_sets` call for the
   session generation that ends up handling both.
2. **`input.rs:1213-1220`** (`SetActionManifestPath`'s legacy→manifest transition) — when a
   manifest arrives after legacy was already attached and a `restart_session()` is forced,
   the *new* session's single attach call (step 1) must carry the legacy set forward instead
   of dropping it, so the post-restart session has both attached together.
3. **`input.rs:1486-1501`** (`frame_start_update`, the `Some(loaded)` branch) — currently
   only conditionally syncs `info_set`. Needs to also unconditionally include the legacy
   action set in its `sync_actions` call every frame, so cached legacy action state (read
   later by `get_legacy_controller_state`) stays current regardless of manifest presence.
4. **`legacy.rs:200-204`** (`get_legacy_controller_state`) — remove the
   `get_loaded_actions().is_some() → return false` early exit entirely. The function's
   existing second check (`get_legacy_actions()` → `None` → "aren't ready") is then the only
   gate needed, and becomes accurate again once (1)-(3) guarantee the legacy set is always
   attached and synced.

No new button plumbing is required — `LegacyActions` (`legacy.rs:390-409`) and
`OculusTouch::legacy_bindings` (`oculus_touch.rs:79-104`) already bind every physical G2
control the legacy API is meant to expose (§2's table is exactly that mapping); the bug is
purely about keeping that action set attached+synced, not about missing bindings.

### 5.2 Legacy bit ↔ action mapping (already correct, unchanged by the fix)

| `VRControllerState_t` field | legacy action | physical source (§2) |
|---|---|---|
| `ulButtonPressed & Axis0` / `ulButtonTouched & Axis0` | `main_xy_click` / `main_xy_touch` | thumbstick click / touch |
| `ulButtonPressed & SteamVR_Trigger` | `trigger_click` | trigger (thresholded from Value) |
| `ulButtonPressed & ApplicationMenu` | `app_menu` | Y (left) / B (right) |
| `ulButtonPressed & A` | `a` | X (left) / A (right) |
| `ulButtonPressed & Grip`, `& Axis2` | `squeeze_click` | grip (thresholded from Value, both bits from the same action) |
| `rAxis[0]` | `main_xy` | thumbstick XY |
| `rAxis[1]` | `trigger` | trigger value |
| `rAxis[2]` | `squeeze` | grip value |
| *(System bit)* | — | intentionally never set — matches real SteamVR reserving it for the dashboard |

### 5.3 Risks

- **`xrAttachSessionActionSets` is call-once per the OpenXR spec.** This fix is a real
  session-lifecycle change, not a one-line patch — it requires restructuring *when* the
  legacy set's bindings get suggested relative to a manifest's, not just relaxing a check.
  Get the ordering wrong and either call throws or silently no-ops on some runtimes.
- **Double-binding the same physical path in two simultaneously-attached action sets is
  spec-legal but doubles the runtime's action bookkeeping** (the legacy `app_menu` action
  and a manifest's own action can both bind `/input/y/click` at once, each with independent
  state) — should be load-tested, not assumed free, especially given this rig's known tight
  per-frame CPU budget under full tracking load (docs/pruebas.jsonl T169).
- **Threshold semantics don't change.** `Grip`/`Axis2`/`SteamVR_Trigger` are already
  emulated from analog Value actions via `translate_path`'s Click→Value collapse
  (`oculus_touch.rs:62-71`) — fixing the attach/sync bug does not turn these into true
  discrete HID clicks; a game that expects a real click-detent grip may still feel a
  threshold, unrelated to this bug.
- **Scope check before implementing**: confirm via §4.5's log lines that Blade Runner
  actually loads a manifest. If it doesn't, this entire fix is a no-op for that title and
  the real bug lies elsewhere (see the closing paragraph of §4.5).
- Minor, likely negligible: modern-API-only titles now carry an always-attached,
  always-synced legacy action set doing nothing visible — one extra `sync_actions` call per
  frame in `frame_start_update`, previously skipped whenever a manifest was loaded.
