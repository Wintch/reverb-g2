# 83 — Calibration/tuning knob catalog, and the brightness knob root cause

Full survey of every runtime knob in the Linux VR stack (Monado + xrizer + the WMR/G2
driver + our launchers/dashboard), done for the demo booth's "command centre" work: which
knobs are worth exposing as dashboard dials ("perillas"), which are already wired, and
which exist and would help but sit unused. Part 2 is a read-only root-cause dig on the
brightness knob, which is currently wired end-to-end but produces zero visible effect.

Scope note on completeness: Monado exposes **224** `DEBUG_GET_ONCE_*` env options total
(`grep -rn DEBUG_GET_ONCE ~/vr/monado/src | grep -cE "_(BOOL|NUM|OPTION|FLOAT|STRING)_OPTION"`).
Most are Android/D3D12/other-headset/other-platform infrastructure with zero relevance to a
G2-on-Linux-NVIDIA booth. The tables below cover every option in the WMR driver, the SLAM
and constellation trackers, the compositor/pacing layer, and xrizer's own env vars — i.e.
everything a G2 demo could plausibly want to tune. Pure build/debug/platform toggles
(`XRT_COMPOSITOR_FORCE_XCB`, Android extensions, D3D12 barriers, etc.) are omitted as noise.

## 1. Monado — WMR/G2 driver knobs

| Var | File:line | Default | Purpose | Used by us? | Dashboard? | Perilla? |
|---|---|---|---|---|---|---|
| `WMR_SLAM` | wmr_hmd.c:78 | true | 6DoF head tracking on/off | Yes — `jack-in-wayland.sh` sets per mode arg | Yes (DoF selector) | Already a perilla |
| `WMR_CAMERAS` | wmr_hmd.c:83 | true | Tracking camera stream on/off | Yes — `ctrl`-mode uses cameras w/o SLAM | Yes (via DoF) | Already a perilla |
| `WMR_DISPLAY_INIT_SLEEP_SECONDS` | wmr_hmd.c:86 | 4 | Wait before Monado looks for the panel after activation | Yes, forced to 2 (load-bearing, CLAUDE.md) | No | No — infra, not user-facing |
| `WMR_HANDTRACKING` | wmr_hmd.c:89 | true | Camera-based hand tracking | No | No | Maybe — untested on G2, no title needs it yet |
| `WMR_CONSTELLATION_CONTROLLERS` | wmr_hmd.c:94, wmr_camera.c:42 | false | Optical (blob) controller tracking | Yes — per-title in `TITLE_PROFILES` | No (title-implicit) | Yes — real per-title tradeoff (CPU/latency vs. hand accuracy) |
| `WMR_LEFT_DISPLAY_VIEW_Y_OFFSET` / `WMR_RIGHT_DISPLAY_VIEW_Y_OFFSET` | wmr_hmd.c:102-103 | 0 | Per-eye vertical render shift | **No** | No | **Have, don't use** — a real lever if a panel/lens vertical misalignment is ever found |
| `WMR_HMD_GYRO_MOUNT_FIX` | wmr_hmd.c:111 | false | Corrects a physical gyro-mount rotation error | No | No | No — only relevant if a specific unit's IMU is mis-mounted |
| `WMR_USER_PRESENCE` | wmr_hmd.c:120 | false (opt-in) | Emit `XR_EXT_user_presence` from the nose-bridge proximity sensor | **No** | No | **Have, don't use** — see §5, real automation opportunity |
| `WMR_USER_PRESENCE_DON_MS` / `_DOFF_MS` | wmr_hmd.c:126-127 | 250 / 1000 | Debounce for don/doff detection | No | No | Only matters if `WMR_USER_PRESENCE` gets adopted |
| `WMR_MAX_SLAM_CAMS` | wmr_config.c:37 | compile default (2) | Cap cameras fed to SLAM | No | No | No |
| `WMR_AUTOEXPOSURE` | wmr_camera.c:36 | true | Camera auto-exposure | No | No | No — low-light tracking already has its own warning (session memory) |
| `WMR_UNIFY_EXPGAIN` | wmr_camera.c:39 | false | Force same exposure/gain on all cameras | No | No | No |
| `WMR_CONTROLLER_CAM_EXPOSURE_US` / `WMR_CONTROLLER_CAM_GAIN` | wmr_camera.c:97-98 | driver default | Camera exposure/gain specifically for controller-blob tracking | No | No | Maybe, if constellation tracking is ever flaky in bright rooms |
| `WMR_STICK_DEADZONE` | wmr_controller_base.c:113 | 0.0 | Analog stick deadzone | Yes — jack-in default 0.15 | No | Yes — genuinely a "feel" knob per game |
| `WMR_STICK_AUTOCENTER` | wmr_controller_base.c:118 | false | Auto-center a drifting stick instead of masking with deadzone | **No** | No | **Have, don't use** — jack-in-wayland.sh's own comment calls the deadzone workaround a mask, not "the real fix" |
| `WMR_CONTROLLER_KEEPALIVE_S` | wmr_controller_base.c:137 | 0 (off) | Periodic controller keepalive interval | No | No | No — candidate if BT idle-timeout issues resurface |
| `WMR_CONTROLLER_HAPTICS` | wmr_controller_base.c:176 | false | Enable controller rumble | **No** | No | **Have, don't use** — no demo currently gets haptic feedback |
| `WMR_CONTROLLER_ORIENT_FIX` / `WMR_CONTROLLER_FULL_CAL_LEFT`/`RIGHT` / `WMR_CONTROLLER_RIGHT_ROLL_180` / `WMR_CONTROLLER_LEFT_YAW_MINUS90` | wmr_controller_base.c:50-57,63 | false | Manual controller orientation-calibration overrides | No | No | No — only for RE/bring-up, not steady-state tuning |
| `WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT` / `WMR_CONTROLLER_LEFT_GYRO_FIT` | wmr_controller_hp.c:38,59 | false | HP-controller-specific gyro sign/fit fixes | No | No | No |
| `WMR_CONSTELLATION_GRAVITY_GATE_DEG` | wmr_controller_base.c:68 | 14.0 | Reject constellation solves whose implied gravity is off by more than this | No (only the *tracker* variant is set) | No | Yes — a real accuracy/robustness tradeoff |
| `WMR_CONSTELLATION_TRACKER_GRAVITY_GATE_DEG` | wmr_controller_base.c:80 | driver default | Same gate, tracker-side | Yes — jack-in sets 30 for 6dof-controllers | No | Already tuned once; worth a proper A/B |
| `WMR_CONSTELLATION_MAX_RANGE_M` | wmr_controller_base.c:73 | 1000.0 | Max plausible controller distance for a solve | No | No | No |
| `WMR_CONTROLLER_SOLVE_YAW_CORRECT` | wmr_controller_base.c:92 | 0.0 | Nudges IMU heading toward the constellation solve | Yes — jack-in default 0.05 | No | Yes — T206/T207 lever, deserves its own perilla |
| `WMR_CONSTELLATION_YAW_PRIOR_DEG` | wmr_controller_base.c:110 | 0.0 | Second, independent yaw-reject gate | Yes — jack-in default 60 | No | Same family as above |

## 2. Monado — constellation tracker (`t_constellation_tracker.cpp`)

| Var | Default | Purpose | Used? | Perilla? |
|---|---|---|---|---|
| `WMR_CONSTELLATION_SEED_PRIOR` | false | Seed blob-assignment from the previous solve (T215) | Yes — jack-in sets 1 in 6dof-controllers mode | Already tuned |
| `WMR_CONSTELLATION_SEED_FIRST` | false | Alternate seeding strategy | **No** | **Have, don't use** — untried alternative to SEED_PRIOR |
| `WMR_CONSTELLATION_MAX_BLOBS` | 0 (unlimited) | Cap blobs considered per frame | **No** | **Have, don't use** — could cut CPU on ISS Tour VR-class heavy titles |
| `WMR_CONSTELLATION_LOST_SEARCH_DIV` | 0 | Divisor for the lost-tracking re-search window | **No** | **Have, don't use** |
| `WMR_CONSTELLATION_MAX_CAM_RANGE_M` | -1.0 (unlimited) | Per-camera range cap | **No** | **Have, don't use** |
| `CONSTELLATION_TRACKER_LOG`, `_DATA_RECORDER_OUTPUT`, `_RERUN_ENABLE`, `_RERUN_SPAWN` | warn/off | Dev/debug instrumentation | Ad hoc | No — dev tools, not demo knobs |

## 3. Monado — SLAM tracker (`t_tracker_slam.cpp`)

| Var | Default | Purpose | Used? | Perilla? |
|---|---|---|---|---|
| `SLAM_PREDICTION_TYPE` | dead-reckoning (0) | Pose-prediction model; `2` = gyro-orientation | Yes — the Aircar/Cyberpilot seated-6dof recipe (patch 0097) | Already tuned per-title |
| `SLAM_PRED_FREEZE_POSITION` | false | Freeze positional prediction (seated recipe) | Yes | Already tuned |
| `SLAM_PRED_NECK_ARM_MM` | 0 | Neck-model arc radius for head-only prediction | Yes — 150 in the recipe | Already tuned |
| `SLAM_CORRECTION_SPREAD_MS` | 0 | Spreads a late SLAM correction over N ms instead of a snap | Yes — 50 in the recipe | Already tuned |
| `SLAM_FILTER` | none set (→ one_euro) | Pose-smoothing filter: `one_euro`\|`moving_average`\|`exponential`\|`none` | Yes — jack-in defaults to `one_euro` | **Only ever A/B'd against `none` once (T-something ghost test)** — moving_average/exponential are **have, don't use** |
| `SLAM_FILTER_ROT_MIN_CUTOFF` | π | one_euro rotation cutoff | Yes — jack-in default 20 | Real "smoothing vs. latency" perilla, one knob of four |
| `SLAM_FILTER_POS_MIN_CUTOFF` | π | one_euro position cutoff | **No** | **Have, don't use** — sibling of the rot cutoff above, never touched |
| `SLAM_FILTER_MIN_DCUTOFF` | 1 | one_euro derivative cutoff | **No** | **Have, don't use** |
| `SLAM_FILTER_BETA` | 0.16 | one_euro speed coefficient | **No** | **Have, don't use** |
| `SLAM_FILTER_BEFORE_PREDICT` | true | Filter placement in the pipeline | No | No |
| `SLAM_POS_DEADZONE_M` | 0 | Ignore position jitter below this radius | **No** | **Have, don't use** — could reduce felt micro-jitter at rest |
| `SLAM_AUTO_RESET` / `SLAM_AUTO_RESET_MAX_SPEED` | true / 10 | Auto-recover from a lost/runaway track | No | No — safety net, leave alone |
| `SLAM_RESET_OFFSET_CARRY` | true | Carry position offset across a reset | No | No |
| `SLAM_CAM_COUNT` | 2 | Cameras fed to the SLAM front end | No | No |
| `SLAM_WRITE_CSVS` / `SLAM_CSV_PATH` | false | Real pose/timing CSV dump — the objective measurement instrument | Yes, in tracing mode | No | Not a "feel" knob, a measurement tool |
| `SLAM_THREADS` | 4 (measured default) | Basalt worker thread count | Yes | No | Already measured/settled (docs history) |
| `SLAM_CONFIG_PIPELINE_ONLY` | false | Use `SLAM_CONFIG` for the vision pipeline only, not full config | Yes, with `SLAM_G2_CONFIG` | No | Infra |
| `SLAM_G2_CONFIG` (launcher-level, selects `basalt-g2-config.json`) | 1 | Denser-detection Basalt pipeline vs. stock defaults | Yes | No | Already the default; worth exposing as an A/B toggle |
| `SLAM_FEATURES_ENABLE` / `SLAM_FEATURES_STAT` / `SLAM_TIMING_STAT` | false/true/true | Extra vision-feature stats | No | No | Dev tools |
| `SLAM_SUBMIT_FROM_START`, `SLAM_UI`, `SLAM_OPENVR_GROUNDTRUTH_DEVICE` | off | Dev/debug | Ad hoc | No | Dev tools |

## 4. Monado — compositor/pacing

| Var | File:line | Default | Purpose | Used? | Perilla? |
|---|---|---|---|---|---|
| `XRT_COMPOSITOR_DESIRED_MODE` | comp_settings.c:32 | -1 (auto) | DP mode index (resolution/refresh) — scanout timing ONLY | Yes | Yes, but **cosmetic**: proven (docs/82 §1.4) not to change render cost |
| `XRT_COMPOSITOR_SCALE_PERCENTAGE` | comp_settings.c:34 | **140** | Base supersampling %, sets actual render-target size (the real fill-rate lever) | Yes — Aircar profile sets 100 | Yes — **the** perilla for the fps/sharpness tradeoff |
| `OXR_VIEWPORT_SCALE_PERCENTAGE` | oxr_system.c:36 | 100 (max 200) | A **second, independent** scale layered on top of the compositor's own recommended size | **No** | **Have, don't use** — a finer per-title dial that doesn't touch the base compositor config; worth an A/B against `XRT_COMPOSITOR_SCALE_PERCENTAGE` |
| `XRT_COMPOSITOR_DEFAULT_FRAMERATE` | comp_settings.c:37 | 60 | Fallback framerate when the target can't report one | No | No |
| `XRT_COMPOSITOR_COMPUTE` | comp_settings.c:38 | platform default | Graphics-pipeline vs. compute-pipeline layer renderer | **No** | **Have, don't use** — never A/B'd on this NVIDIA rig |
| `XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY` | comp_settings.c:26 | NULL | Vendor-string match to pick the direct-mode target | Yes, hardcoded `"HP Inc."` | No | Infra, not a calibration knob |
| `XRT_COMPOSITOR_LOG` | — | warn | Log verbosity | Yes, `=debug` | No | **Load-bearing for direct mode** per jack-in-wayland.sh, not just verbosity — don't touch casually |
| `U_PACING_APP_USE_MIN_FRAME_PERIOD` | u_pacing_app.c:27 | false | The **45/30fps-ceiling fix** — forces the min frame period the app pacer will honor | Yes, launcher default true | No | Already the single most important fix in the project's history (CLAUDE.md T244) |
| `U_PACING_APP_PIPELINED` | u_pacing_app.c:35 | false | Pipeline app frame submission | Yes | No | Settled |
| `U_PACING_APP_MIN_TIME_MS` / `_MIN_MARGIN_MS` | 1.0 / 2.0 | Pacer safety margins | No | No | Have, don't use |
| `U_PACING_APP_IMMEDIATE_WAIT_FRAME_RETURN` (+ `_BELOW_REFRESH`) | false | Return `xrWaitFrame` immediately instead of pacing | No | No | No |
| `U_PACING_APP_ALIGN_PREDICTED_DISPLAY_TIME_TO_APP_PERIOD` | false | Align predicted display time to the app's own period | No | No | No |
| `U_PACING_APP_LOG` / `U_PACING_COMPOSITOR_LOG` | warn | Pacer log level | Yes, `=info`/`=debug` in tracing mode | No | **Required** for "Delivered frame" lines to exist at all (docs/82 §5's dead-grep trap) |
| `U_PACING_LIVE_STATS` | false | Per-frame pacing stats | Yes, tracing mode | No | Measurement tool |
| `U_PACING_COMP_*` (offset/margin/time-fraction) | driver defaults | Compositor-side pacing tuning | No | No | Have, don't use — no evidence they matter yet |

## 5. xrizer knobs

| Var/mechanism | File:line | Default | Purpose | Used? | Dashboard? |
|---|---|---|---|---|---|
| `XRIZER_BRIGHTNESS_FILE` | compositor.rs:1670 | `$HOME/vr/logs/xrizer-brightness` | Path to the polled brightness-gain file | Yes | **Yes — but broken, see Part 2** |
| `XRIZER_RECENTER_HOLD_SECS` | input/legacy.rs:439 | 3.0s | Hold-menu-button global recenter duration | **No** | No | **Have, don't use** — hardcoded to the crate default everywhere |
| `XRIZER_TRACKER_SERIALS` | input/devices.rs:422 | none | Semicolon-list of extra generic-tracker serials to expose to the game | **No** | No | Not relevant — no extra trackers in the booth |
| `XRIZER_CUSTOM_BINDINGS_DIR` | input/action_manifest.rs:281 | none | Override the default action-binding search directory | **No** | No | Have, don't use |
| `static-openxr` (Cargo feature, `Cargo.toml:16`) | build-time | off | Statically link the OpenXR loader into `libxrizer.so` | Yes, adopted 2026-08-26 for Proton robustness (docs/82 §2) | N/A | Build-time, not a runtime perilla |
| `IVRSettings` (`settings.rs`) | — | — | OpenVR settings API | **Full stub** — every read returns 0/false | N/A | **Fixed, not adjustable**: in-game quality dropdowns that go through `IVRSettings` are inert under xrizer (docs/82 §1.4) |
| System recenter hold (menu button, 3s) | input/legacy.rs | on | Global play-space recenter | Yes | No | Real per-user comfort knob, currently one-size-fits-all |
| App-fade grid (`app_fade_grid`) | compositor.rs field | off | Dashboard overlay fade grid | Internal only | No | Not exposed as a toggle |

## 6. Already wired to the dashboard (`status-dashboard.py`)

- **DoF** (3dof/6dof) — per-user preference, drives `WMR_SLAM`/`WMR_CAMERAS` via the launcher.
- **Brightness** (`XRIZER_BRIGHTNESS_FILE` gain, 0-4x) — per-user, `/api/brightness` — **broken, see Part 2**.
- **Audio** (`hmd-audio.sh mute/unmute/set <0-150>%`) — sink-name lookup via `wpctl`, survives PipeWire re-numbering.
- **Playlist** (`playlist-runner.py`) — ordered demo-round sequencing, not a per-frame calibration but a booth-operation control.

## 7. Fixed / physical — NOT host-settable

- **IPD** — mechanical slider on the headset itself. The host only ever *reads* it (as
  telemetry, for rendering the correct eye separation), via the `WMR_CONTROL_MSG_IPD_VALUE`
  protocol message (`wmr_hmd.c:626,645,861,999`) — there is no write path, on Linux or
  Windows.
- **Panel backlight brightness** — no HID command exists to set it, confirmed even on
  Windows (`compositor.rs:1659`'s own comment, cross-checked against the RE work in
  `docs/09`/`docs/12`). `XRIZER_BRIGHTNESS_FILE` is a **software post-process** (multiplies
  the rendered pixels before scanout) — a real workaround, not backlight control.
- **FOV** — Monado exposes no FOV crop; checked across all 240 debug options during the
  Cyberpilot 90fps investigation (docs/82 T158). Fixed by the panel's physical geometry and
  the baked lens-distortion mesh.
- **Refresh-rate ceiling (90Hz)** — panel hardware limit; not a knob, it's the whole reason
  this repo exists (docs/19).

## 8. Wire these to the command centre next (shortlist)

Ranked by "would actually help a guest-facing booth" combined with "verified real,
currently unused":

1. **`WMR_USER_PRESENCE`** (+ DON/DOFF ms) — the proximity sensor already exists and is
   wired in Monado, off by default. This is the missing link for auto-pausing/advancing the
   playlist when a guest takes the headset off — directly useful for the
   `idea_arcade_mode_headless_vr` / playlist-sequencer line of work, and it's a single env
   var away, not a new feature.
2. **`XRT_COMPOSITOR_SCALE_PERCENTAGE` as a live per-title slider**, not just a
   `TITLE_PROFILES` constant — it's already proven to be the real fps/sharpness lever
   (Aircar 6dof: 140%→100% took the fps floor from 41 to 79). Exposing it as a dashboard
   dial (with `OXR_VIEWPORT_SCALE_PERCENTAGE` as a secondary fine-trim) turns a one-off
   patch-and-relaunch tuning session into a live control.
3. **`SLAM_FILTER` + its four one_euro parameters** as a "tracking feel" perilla
   (smooth ↔ responsive), instead of the single hardcoded default — this is a legitimate,
   cheap axis that's never been A/B'd beyond the one `none` comparison.
4. **`WMR_STICK_AUTOCENTER`** — the codebase's own comment already names the current
   deadzone setting as a mask, not the real fix; worth a real A/B before the next controller
   demo.
5. **`XRIZER_RECENTER_HOLD_SECS`** — trivial to expose, meaningfully different per guest
   height/seating.

---

# Part 2 — the brightness knob root cause

## Summary

**No wiring defect found after an exhaustive, file-by-file trace through both xrizer and
Monado.** Every hop checked out structurally correct:

- Extension request/enable (`xrizer/src/openxr_data.rs:133-145,163-174`): queries the real
  runtime via `entry.enumerate_extensions()`, sets
  `exts.khr_composition_layer_color_scale_bias` from the answer, passes it to
  `create_instance`.
- Monado actually compiles the extension in for **this exact build**: confirmed three ways
  — `CMakeCache.txt:1171` has `XRT_FEATURE_OPENXR_LAYER_COLOR_SCALE_BIAS:BOOL=ON`; the
  **generated** header in the build tree
  (`build/src/xrt/state_trackers/oxr/extension_support/oxr_extension_support.h:63-66`) took
  the `#if` branch that defines `OXR_HAVE_KHR_composition_layer_color_scale_bias` (not the
  empty `#else`); and `strings` on the actual `.so`/binary on disk shows the extension name
  and `fill_in_color_scale_bias` symbol present in `libopenxr_monado.so`, and
  `XRT_LAYER_COMPOSITION_COLOR_BIAS_SCALE` present in `monado-service`.
- Struct layout: `xr::sys::CompositionLayerColorScaleBiasKHR` (openxr-rs `generated.rs:8366`)
  and `XrCompositionLayerColorScaleBiasKHR` (Monado's `openxr.h:2199`) have byte-identical
  field order (`ty, next, colorScale, colorBias`); same for `CompositionLayerProjection`.
  The `StructureType` enum value (`1000034000`) matches on both sides. The raw-pointer splice
  in `compositor.rs:1619-1633` is the same pattern as the long-proven `overlay.rs:358-372`
  alpha implementation (same struct, same extension, in production since commit `fe8dad0`,
  2025-04-02).
- Monado's consuming path: `fill_in_color_scale_bias` (`oxr_session_frame_end.c:214-233`)
  sets `XRT_LAYER_COMPOSITION_COLOR_BIAS_SCALE` and copies both colors when the chained
  struct is found; `can_do_one_projection_layer_fast_path`
  (`comp_compositor.c:276-304`) correctly **excludes** the zero-cost distortion-only fast
  path whenever that flag is set, forcing the full layer renderer; both the graphics
  (`comp_render_gfx.c:422`) and compute (`comp_render_cs.c:731-732`) pipelines call
  `apply_bias_and_scale_from_layer` for the projection layer; the shader
  (`shaders/layer_projection.frag`) does `out_color = clamp(out_color * ubo.color_scale +
  ubo.color_bias, 0, 1)`. The IPC hop between the client-side OXR tracker and
  `monado-service` copies the **whole** `xrt_layer_data` struct at every stage
  (`ipc_client_compositor.c:600`, `ipc_server_handler.c`'s `_update_projection_layer`,
  `comp_layer_accum.c:72`) — no field-by-field reconstruction anywhere that could drop the
  new fields.
- Build freshness: `libopenxr_monado.so` (Aug 19) predates `monado-service` (Aug 26), but
  every file relevant to this feature (`oxr_session_frame_end.c`, `xrt_compositor.h`,
  `comp_compositor.c`'s fast-path exclusion, `CMakeLists.txt`'s feature default) was last
  touched between Dec 2023 and Feb 2026 — all well before Aug 19. Not a staleness bug for
  this feature (though the gap is still worth closing before the next rebuild, on general
  hygiene grounds).

## The one real, concrete gap found

`compositor.rs`'s new brightness code (in `FrameController<G>::end_frame`, line
1606-1637) **never checks whether the extension is actually enabled on the session**
before splicing the struct. Compare directly against the codebase's own, already-proven
pattern for the identical extension, `overlay.rs:704-710` (`SetOverlayAlpha`):

```rust
// overlay.rs — the proven pattern
if !self.openxr.enabled_extensions.khr_composition_layer_color_scale_bias {
    crate::warn_once!("Cannot SetOverlayAlpha on {:?}: Runtime does not support \
        KHR_composition_layer_color_scale_bias", overlay.name);
    return vr::EVROverlayError::None;
}
```

`FrameController<G>` (`compositor.rs:1280-1292`, where the brightness splice lives) **has
no field referencing `OpenXrData`/`enabled_extensions` at all** — unlike `Compositor<C>`
(`compositor.rs:36`, `openxr: Arc<OpenXrData<Self>>`), which is what `overlay.rs`'s check
runs against. Structurally, the code that does the splice cannot see whether the extension
was actually granted for this instance. If it isn't — for any reason: a different
per-session extension-negotiation order, a title that creates more than one instance, a
future Monado build where the runtime declines it — Monado's own guard
(`oxr_session_frame_end.c:221`, `if (!...extensions.KHR_composition_layer_color_scale_bias)
{ return; }`) silently drops the whole payload with **zero** log output and **zero** visible
error anywhere, exactly matching "gain=2.5, zero change, no error." xrizer has no
instrumentation to catch this for the brightness path, unlike its own sibling feature.

**Exact fix** (`compositor.rs`, `FrameController<G>::end_frame`, around line 1606-1637):
give `FrameController` access to the enabled-extensions flag (either store
`openxr: Arc<OpenXrData<G>>` in the struct, mirroring `Compositor<C>` at line 36, or thread
the bool in at construction time from `Compositor::new` where `self.openxr` already exists),
then gate the splice:

```rust
let gain = current_brightness_gain();
if gain != 1.0 && self.openxr.enabled_extensions.khr_composition_layer_color_scale_bias {
    // existing splice
} else {
    if gain != 1.0 {
        crate::warn_once!("brightness gain requested but runtime does not support \
            KHR_composition_layer_color_scale_bias");
    }
    proj_layer = Some(layer);
}
```

This is the concrete, minimal patch a rebuild should carry. It does two things regardless
of the underlying cause: (1) if the extension genuinely isn't enabled for this session, the
log now says so instead of silently no-op'ing — turning an unfalsifiable "zero change" into
a diagnosable one-line answer; (2) it brings the new code in line with the codebase's own
established safety pattern for this exact extension.

## One secondary, independently real issue

`compositor.rs:1623` sets `color_bias: Default::default()` (zero) and only scales RGB by
`gain`. A pure multiplicative scale cannot lift true-black pixels (`0 × gain + 0 = 0`), and
the shader's `clamp(..., 0, 1)` means already-bright pixels clip instead of gaining
headroom. On any content whose average exposure sits low (a dim scene — exactly the
situation this knob exists to help with), a scale-only gain can look like little-to-no
change even if the extension is applying correctly. This alone is unlikely to produce a
**literal zero** on typical mixed-tone game footage, but it's a real design gap worth
closing in the same patch: add a nonzero `color_bias` (additive lift) alongside the scale,
not scale alone.

## Recommended next step (still read-only, no rebuild)

Before touching code further: add one `debug!`/`warn_once!` line at
`oxr_session_frame_end.c:221` (or trace it via `XRT_COMPOSITOR_LOG=debug`, already the
project's standard verbose flag) logging whether
`sess->sys->inst->extensions.KHR_composition_layer_color_scale_bias` is true the next time
a game session starts. That one log line discriminates between "the extension genuinely
isn't enabled for this session" (matches the gap found above) and "it's enabled and
something else entirely is wrong" — the only thing static reading alone could not settle.
