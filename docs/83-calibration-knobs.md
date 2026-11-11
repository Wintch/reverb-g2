# 83 — Calibration/tuning knob catalog, and the brightness knob root cause

Survey of every runtime knob in the Linux VR stack (Monado + xrizer + the WMR/G2 driver +
our launchers): what each one does, its default, and whether this stack sets it. Part 2 is a
read-only root-cause dig on the brightness knob, which was wired end-to-end but looked like it
had no visible effect. A short generic GPU power-cap method note closes the doc.

Scope: Monado exposes **173** `DEBUG_GET_ONCE_*` env options in total (count on the current checkout)
(`grep -rn DEBUG_GET_ONCE ~/vr/monado/src | grep -cE "_(BOOL|NUM|OPTION|FLOAT|STRING)_OPTION"`).
Most are Android/D3D12/other-headset/other-platform infrastructure with no relevance to a
G2-on-Linux-NVIDIA setup. The tables cover every option in the WMR driver, the SLAM and
constellation trackers, the compositor/pacing layer, and xrizer's own env vars. Pure
build/debug/platform toggles (`XRT_COMPOSITOR_FORCE_XCB`, Android extensions, D3D12 barriers) are
omitted.

## 1. Monado — WMR/G2 driver knobs

Note: the knobs from patches 0066/0067/0076/0077/0084 (`WMR_CONTROLLER_SOLVE_YAW_CORRECT`,
`WMR_CONSTELLATION_YAW_PRIOR_DEG`, the tracker gravity gate, `WMR_CONSTELLATION_SEED_PRIOR`) exist
only on the lab branch (`patches/monado/unapplied/`) and are not in the shipped build.

| Var | File:line | Default | Purpose | Used by this stack? / notes |
|---|---|---|---|---|
| `WMR_SLAM` | wmr_hmd.c:78 | true | 6DoF head tracking on/off | Yes, `jack-in-wayland.sh` sets it per mode argument |
| `WMR_CAMERAS` | wmr_hmd.c:83 | true | Tracking camera stream on/off | Yes, `ctrl` mode uses cameras without SLAM |
| `WMR_DISPLAY_INIT_SLEEP_SECONDS` | wmr_hmd.c:86 | 4 | Wait before Monado looks for the panel after activation | Forced to 2 (load-bearing) |
| `WMR_HANDTRACKING` | wmr_hmd.c:89 | true | Camera-based hand tracking | No; untested on G2 |
| `WMR_CONSTELLATION_CONTROLLERS` | wmr_hmd.c:94, wmr_camera.c:42 | false | Optical (blob) controller tracking | Yes, per title in `TITLE_PROFILES`; real tradeoff (CPU/latency vs. hand accuracy) |
| `WMR_LEFT_DISPLAY_VIEW_Y_OFFSET` / `WMR_RIGHT_DISPLAY_VIEW_Y_OFFSET` | wmr_hmd.c:102-103 | 0 | Per-eye vertical render shift | No; a lever if a panel/lens vertical misalignment is ever found |
| `WMR_HMD_GYRO_MOUNT_FIX` | wmr_hmd.c:111 | false | Corrects a physical gyro-mount rotation error | No; only for a mis-mounted IMU |
| `WMR_USER_PRESENCE` | wmr_hmd.c:120 | false (opt-in) | Emit `XR_EXT_user_presence` from the nose-bridge proximity sensor | Opt-in; see docs/103 for the presence work |
| `WMR_USER_PRESENCE_DON_MS` / `_DOFF_MS` | wmr_hmd.c:126-127 | 250 / 1000 | Debounce for don/doff detection | Only matters with `WMR_USER_PRESENCE` |
| `WMR_MAX_SLAM_CAMS` | wmr_config.c:37 | compile default (2) | Cap cameras fed to SLAM | No |
| `WMR_AUTOEXPOSURE` | wmr_camera.c:36 | true | Camera auto-exposure | No |
| `WMR_UNIFY_EXPGAIN` | wmr_camera.c:39 | false | Force same exposure/gain on all cameras | No |
| `WMR_CONTROLLER_CAM_EXPOSURE_US` / `WMR_CONTROLLER_CAM_GAIN` | wmr_camera.c:97-98 | driver default | Camera exposure/gain specifically for controller-blob tracking | No; candidate if constellation tracking is flaky in bright rooms |
| `WMR_STICK_DEADZONE` | wmr_controller_base.c:113 | 0.0 | Analog stick deadzone | Yes, jack-in default 0.15; a per-game "feel" knob |
| `WMR_STICK_AUTOCENTER` | wmr_controller_base.c:118 | false | Auto-center a drifting stick instead of masking with deadzone | No; the deadzone is a mask, this is the real fix |
| `WMR_CONTROLLER_KEEPALIVE_S` | wmr_controller_base.c:137 | 0 (off) | Periodic controller keepalive interval | No; candidate if BT idle-timeout issues resurface |
| `WMR_CONTROLLER_HAPTICS` | wmr_controller_base.c:176 | false | Enable controller rumble | No |
| `WMR_CONTROLLER_ORIENT_FIX` / `WMR_CONTROLLER_FULL_CAL_LEFT`/`RIGHT` / `WMR_CONTROLLER_RIGHT_ROLL_180` / `WMR_CONTROLLER_LEFT_YAW_MINUS90` | wmr_controller_base.c:50-57,63 | false | Manual controller orientation-calibration overrides | No; reverse-engineering/bring-up only |
| `WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT` / `WMR_CONTROLLER_LEFT_GYRO_FIT` | wmr_controller_hp.c:38,59 | false | HP-controller-specific gyro sign/fit fixes | No |
| `WMR_CONSTELLATION_GRAVITY_GATE_DEG` | wmr_controller_base.c:68 | 14.0 | Reject constellation solves whose implied gravity is off by more than this | No (only the tracker variant is set); accuracy/robustness tradeoff |
| `WMR_CONSTELLATION_TRACKER_GRAVITY_GATE_DEG` | wmr_controller_base.c:80 | driver default | Same gate, tracker-side | Yes, jack-in sets 30 for 6dof-controllers |
| `WMR_CONSTELLATION_MAX_RANGE_M` | wmr_controller_base.c:73 | 1000.0 | Max plausible controller distance for a solve | No |
| `WMR_CONTROLLER_SOLVE_YAW_CORRECT` | wmr_controller_base.c:92 | 0.0 | Nudges IMU heading toward the constellation solve | Yes, jack-in default 0.05 |
| `WMR_CONSTELLATION_YAW_PRIOR_DEG` | wmr_controller_base.c:110 | 0.0 | Second, independent yaw-reject gate | Yes, jack-in default 60 |

## 2. Monado — constellation tracker (`t_constellation_tracker.cpp`)

| Var | Default | Purpose | Used? / notes |
|---|---|---|---|
| `WMR_CONSTELLATION_SEED_PRIOR` | false | Seed blob-assignment from the previous solve | Yes, jack-in sets 1 in 6dof-controllers mode |
| `WMR_CONSTELLATION_SEED_FIRST` | false | Alternate seeding strategy | No; untried alternative to SEED_PRIOR |
| `WMR_CONSTELLATION_MAX_BLOBS` | 0 (unlimited) | Cap blobs considered per frame | No; could cut CPU on heavy titles |
| `WMR_CONSTELLATION_LOST_SEARCH_DIV` | 0 | Divisor for the lost-tracking re-search window | No |
| `WMR_CONSTELLATION_MAX_CAM_RANGE_M` | -1.0 (unlimited) | Per-camera range cap | No |
| `CONSTELLATION_TRACKER_LOG`, `_DATA_RECORDER_OUTPUT`, `_RERUN_ENABLE`, `_RERUN_SPAWN` | warn/off | Dev/debug instrumentation | Ad hoc |

## 3. Monado — SLAM tracker (`t_tracker_slam.cpp`)

| Var | Default | Purpose | Used? / notes |
|---|---|---|---|
| `SLAM_PREDICTION_TYPE` | 4 (dead reckoning; 0 = none, 2 = gyro) | Pose-prediction model; `2` = gyro-orientation | Yes, part of the seated-6dof recipe (patch 0097) |
| `SLAM_PRED_FREEZE_POSITION` | false | Freeze positional prediction | Yes, seated recipe |
| `SLAM_PRED_NECK_ARM_MM` | 0 | Neck-model arc radius for head-only prediction | Yes, 100 in the Aircar profile, 150 in the 1056970 profile (see docs/80, patch 0115) |
| `SLAM_CORRECTION_SPREAD_MS` | 0 | Spreads a late SLAM correction over N ms instead of a snap | Yes, 25 in the Aircar profile, 50 in the 1056970 profile |
| `SLAM_FILTER` | none set (-> one_euro) | Pose-smoothing filter: `one_euro`\|`moving_average`\|`exponential`\|`none` | Yes, jack-in defaults to `one_euro`; only ever A/B'd against `none` |
| `SLAM_FILTER_ROT_MIN_CUTOFF` | pi | one_euro rotation cutoff | Yes, jack-in default 20; the smoothing-vs-latency knob |
| `SLAM_FILTER_POS_MIN_CUTOFF` | pi | one_euro position cutoff | No |
| `SLAM_FILTER_MIN_DCUTOFF` | 1 | one_euro derivative cutoff | No |
| `SLAM_FILTER_BETA` | 0.16 | one_euro speed coefficient | No |
| `SLAM_FILTER_BEFORE_PREDICT` | true | Filter placement in the pipeline | No |
| `SLAM_POS_DEADZONE_M` | 0 | Ignore position jitter below this radius | No; could reduce felt micro-jitter at rest |
| `SLAM_AUTO_RESET` / `SLAM_AUTO_RESET_MAX_SPEED` | true / 10 | Auto-recover from a lost/runaway track | No; safety net, leave alone |
| `SLAM_RESET_OFFSET_CARRY` | true | Carry position offset across a reset | No |
| `SLAM_CAM_COUNT` | 2 | Cameras fed to the SLAM front end | No |
| `SLAM_WRITE_CSVS` / `SLAM_CSV_PATH` | false | Real pose/timing CSV dump, the objective measurement instrument | Yes, in tracing mode |
| `SLAM_THREADS` | 4 (measured default) | Basalt worker thread count | Yes; measured and settled |
| `SLAM_CONFIG_PIPELINE_ONLY` | false | Use `SLAM_CONFIG` for the vision pipeline only, not the full config | Yes, with `SLAM_G2_CONFIG` |
| `SLAM_G2_CONFIG` (launcher-level, selects `basalt-g2-config.json`) | 1 | Denser-detection Basalt pipeline vs. stock defaults | Yes, the default |
| `SLAM_FEATURES_ENABLE` / `SLAM_FEATURES_STAT` / `SLAM_TIMING_STAT` | false/true/true | Extra vision-feature stats | Dev tools |
| `SLAM_SUBMIT_FROM_START`, `SLAM_UI`, `SLAM_OPENVR_GROUNDTRUTH_DEVICE` | off | Dev/debug | Dev tools |

## 4. Monado — compositor/pacing

| Var | File:line | Default | Purpose | Used? / notes |
|---|---|---|---|---|
| `XRT_COMPOSITOR_DESIRED_MODE` | comp_settings.c:32 | -1 (auto) | DP mode index (resolution/refresh), scanout timing ONLY | Yes; cosmetic, proven not to change render cost (docs/23) |
| `XRT_COMPOSITOR_SCALE_PERCENTAGE` | comp_settings.c:34 | **140** | Base supersampling %, sets the actual render-target size (the real fill-rate lever) | Yes, per-title profiles (Aircar sets 100). **The** fps/sharpness lever |
| `OXR_VIEWPORT_SCALE_PERCENTAGE` | oxr_system.c:36 | 100 (max 200) | A **second, independent** scale layered on top of the compositor's recommended size | No; finer per-title dial that leaves the base compositor config alone |
| `XRT_COMPOSITOR_DEFAULT_FRAMERATE` | comp_settings.c:37 | 60 | Fallback framerate when the target can't report one | No |
| `XRT_COMPOSITOR_COMPUTE` | comp_settings.c:38 | platform default | Graphics-pipeline vs. compute-pipeline layer renderer | No; never A/B'd on this NVIDIA rig |
| `XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY` | comp_settings.c:26 | NULL | Vendor-string match to pick the direct-mode target | Yes, hardcoded `"HP Inc."` |
| `XRT_COMPOSITOR_LOG` | n/a | warn | Log verbosity | Yes, `=debug`; **load-bearing for direct mode** per jack-in-wayland.sh, not just verbosity |
| `U_PACING_APP_USE_MIN_FRAME_PERIOD` | u_pacing_app.c:27 | false | The **45/30 fps-ceiling fix**: forces the min frame period the app pacer will honor | Yes, launcher default true; the single most important pacing fix |
| `U_PACING_APP_PIPELINED` | u_pacing_app.c:35 | false | Pipeline app frame submission | Yes |
| `U_PACING_APP_MIN_TIME_MS` / `_MIN_MARGIN_MS` | n/a | 1.0 / 2.0 | Pacer safety margins | No |
| `U_PACING_APP_IMMEDIATE_WAIT_FRAME_RETURN` (+ `_BELOW_REFRESH`) | n/a | false | Return `xrWaitFrame` immediately instead of pacing | No |
| `U_PACING_APP_ALIGN_PREDICTED_DISPLAY_TIME_TO_APP_PERIOD` | n/a | false | Align predicted display time to the app's own period | No |
| `U_PACING_APP_LOG` / `U_PACING_COMPOSITOR_LOG` | n/a | warn | Pacer log level | Yes, `=info`/`=debug` in tracing mode; **required** for "Delivered frame" lines to exist at all (otherwise fps reads 0 while rendering) |
| `U_PACING_LIVE_STATS` | n/a | false | Per-frame pacing stats | Yes, tracing mode |
| `U_PACING_COMP_*` (offset/margin/time-fraction) | n/a | driver defaults | Compositor-side pacing tuning | No; no evidence they matter |

## 5. xrizer knobs

| Var/mechanism | File:line | Default | Purpose | Used? / notes |
|---|---|---|---|---|
| `XRIZER_BRIGHTNESS_FILE` | compositor.rs:1670 | `$HOME/vr/logs/xrizer-brightness` | Path to the polled brightness-gain file | Yes. Works, but **must stay at 1.0: any other value visibly dithers, see docs/112 §3** |
| `XRIZER_RECENTER_HOLD_SECS` | input/legacy.rs:439 | 3.0 s | Hold-menu-button global recenter duration | No; crate default everywhere |
| `XRIZER_TRACKER_SERIALS` | input/devices.rs:422 | none | Semicolon-list of extra generic-tracker serials to expose to the game | No |
| `XRIZER_CUSTOM_BINDINGS_DIR` | input/action_manifest.rs:281 | none | Override the default action-binding search directory | No |
| `static-openxr` (Cargo feature, `Cargo.toml:16`) | build-time | off | Statically link the OpenXR loader into `libxrizer.so` | Yes, for Proton robustness |
| `IVRSettings` (`settings.rs`) | n/a | n/a | OpenVR settings API | **Full stub**, every read returns 0/false: in-game quality dropdowns that go through `IVRSettings` are inert under xrizer (docs/23) |
| Recenter hold (menu button, 3 s) | input/legacy.rs | on | Global play-space recenter | Yes |
| App-fade grid (`app_fade_grid`) | compositor.rs field | off | Overlay fade grid | Internal only |

## 6. Fixed / physical, NOT host-settable

- **IPD**: mechanical slider on the headset. The host only *reads* it (as telemetry, for the
  correct eye separation) via the `WMR_CONTROL_MSG_IPD_VALUE` protocol message
  (`wmr_hmd.c:626,645,861,999`); there is no write path, on Linux or Windows.
- **Panel backlight brightness**: no HID command exists to set it, confirmed even on Windows
  (`compositor.rs:1659`'s own comment, cross-checked against the RE work in `docs/09`/`docs/12`).
  `XRIZER_BRIGHTNESS_FILE` is a **software post-process** (multiplies the rendered pixels before
  scanout), not backlight control.
- **FOV**: Monado exposes no FOV crop (checked across all 173 debug options). Fixed by the panel's
  physical geometry and the baked lens-distortion mesh.
- **Refresh-rate ceiling (90 Hz)**: panel hardware limit; see docs/19.

---

# Part 2 — the brightness knob root cause

Later live work (docs/112 §3) confirmed the knob works as designed but dithers at any gain other than
1.0. The trace below is the static analysis that established the pipeline is wired correctly, plus the
one robustness gap it found.

## Result of the trace

**No wiring defect after a file-by-file trace through xrizer and Monado.** Every hop checked out:

- **Extension request/enable** (`xrizer/src/openxr_data.rs:133-145,163-174`): queries the real runtime
  via `entry.enumerate_extensions()`, sets `exts.khr_composition_layer_color_scale_bias` from the
  answer, passes it to `create_instance`.
- **Monado compiles the extension in**: `CMakeCache.txt` has
  `XRT_FEATURE_OPENXR_LAYER_COLOR_SCALE_BIAS:BOOL=ON`; the generated
  `oxr_extension_support.h` took the branch that defines
  `OXR_HAVE_KHR_composition_layer_color_scale_bias`; `strings` on the binaries shows the extension name
  and `fill_in_color_scale_bias` in `libopenxr_monado.so` and
  `XRT_LAYER_COMPOSITION_COLOR_BIAS_SCALE` in `monado-service`.
- **Struct layout**: `xr::sys::CompositionLayerColorScaleBiasKHR` (openxr-rs) and Monado's
  `XrCompositionLayerColorScaleBiasKHR` have byte-identical field order (`ty, next, colorScale,
  colorBias`), and the `StructureType` value (`1000034000`) matches. The raw-pointer splice in
  `compositor.rs:1619-1633` is the same pattern as the long-proven overlay-alpha code in `overlay.rs`.
- **Monado's consuming path**: `fill_in_color_scale_bias` (`oxr_session_frame_end.c:214-233`) sets
  `XRT_LAYER_COMPOSITION_COLOR_BIAS_SCALE` and copies both colors;
  `can_do_one_projection_layer_fast_path` (`comp_compositor.c:276-304`) excludes the distortion-only
  fast path when that flag is set; both the graphics (`comp_render_gfx.c`) and compute
  (`comp_render_cs.c`) pipelines call `apply_bias_and_scale_from_layer`; the shader
  (`layer_projection.frag`) does `clamp(out_color * color_scale + color_bias, 0, 1)`. The IPC hop copies
  the whole `xrt_layer_data` struct at every stage, so no field is dropped.
- **Build freshness**: every file relevant to the feature predates the library build used.

An earlier "broken" verdict (a screenshot A/B showing a flat mean) used the wrong instrument: the
desktop mirror shows the app's raw submitted texture, not the compositor's post color-scale/bias
output. A compositor-layer effect is invisible to a capture that only sees the pre-compositor frame.

## One real gap: the splice never checks the extension is enabled

`FrameController<G>::end_frame` (`compositor.rs:1606-1637`) splices the struct without checking
whether the extension is enabled on the session, unlike the proven pattern for the same extension in
`overlay.rs` (`SetOverlayAlpha`: `if !self.openxr.enabled_extensions.khr_composition_layer_color_scale_bias
{ warn_once!(...); return ... }`). `FrameController<G>` has no field referencing
`OpenXrData`/`enabled_extensions`. If the extension were ever not granted, Monado's own guard
(`oxr_session_frame_end.c:221`) silently drops the payload with zero log output: "gain changed, zero
visible effect, no error".

Fix: give `FrameController` access to the flag (store `openxr: Arc<OpenXrData<G>>` as `Compositor<C>`
does, or thread the bool in at construction) and gate the splice, with a `warn_once!` when a gain was
requested but the extension is missing:

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

This is a robustness improvement, not a functional fix: the knob works today because the extension is
in fact enabled. To check directly, run with `XRT_COMPOSITOR_LOG=debug` or add a log line at
`oxr_session_frame_end.c:221` for `sess->sys->inst->extensions.KHR_composition_layer_color_scale_bias`.

## Secondary design gap: scale only, no bias

`compositor.rs:1623` sets `color_bias` to zero and only scales RGB by `gain`. A pure multiplicative
scale cannot lift true black (`0 * gain + 0 = 0`), and the shader's clamp clips already-bright pixels
instead of giving them headroom, so on dim content a scale-only gain can look like little change. If
the knob is ever revisited, add a nonzero additive `color_bias` alongside the scale; but see docs/112
§3 for why any gain other than 1.0 dithers on this headset.

---

# Part 3 — GPU power-cap method (generic)

A power cap is a **ceiling**; what a session actually costs is the **measured draw**. To pick a cap
for a VR title or a whole machine:

1. Log real draw over a real session: `scripts/power-log.sh [interval_s] [duration_s]` samples GPU
   power (`nvidia-smi power.draw`) and CPU package power (RAPL energy-counter deltas under
   `/sys/class/powercap`, readable after `scripts/vr-power-setup.sh --apply` with `RAPL_PUBLIC=1`) to a
   CSV and prints session averages in W and Wh/h.
2. Separate GPU load from a title's own CPU cost. `scripts/gpu-load-sweep.sh` sweeps a synthetic GPU
   load (hello_xr's `HELLO_XR_GPU_LOAD=<0-100>` fragment-shader busy loop; no SLAM, no constellation,
   no Proton/DXVK) against real frame pacing on an already-running Monado session, so a pacing change
   across levels can only be the GPU.
3. Sweep the cap (`nvidia-smi -pl <W>`, or `vr-power-setup.sh --gpu-limit`) and record fps (count of
   `Delivered frame` lines, `U_PACING_APP_LOG=debug`), late frames and watts at each step, at least 3
   windows of ~20 s per step on a stable scene (fps is heavily scene-dependent; one grab is
   meaningless).
4. Pick the knee: the lowest cap where fps and late-frame rate stay at the target. For a seated 6dof
   title the late-frame rate was identical at 105, 147 and 210 W, i.e. pacing was CPU-bound across
   that range and the cap was not the limiting factor.
5. A cap is a no-op when the card is already below it. If the fps ceiling holds with draw at the
   card's max, the title is GPU-bound and raising the cap gives nothing.
6. Check the effective limit (`nvidia-smi -q -d POWER`) before trusting a result; a configured value
   such as `GPU_LIMIT_PCT` in `power.conf` is only an intent until applied.
7. Do not change caps mid-session; idle with the compositor stopped (`monado-service` presenting the
   panel at 90 Hz draws ~60 W even with no title running).
