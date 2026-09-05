# 97 -- Dashboard Vitals + driver sensor-data wiring (2026-09-05)

Two local commits, one in each repo, done as a paired round: the driver side dumps
three new JSON snapshot files that were previously either not computed at all
(`perf-metrics.json`) or computed-and-discarded (`camera-calibration.json`,
`hmd-status.json`); the dashboard side hides the Audio UI, promotes the Tracking
cameras card to the untabbed glance-grid, and adds a new Vitals section of
hand-rolled live charts plus wiring for all four of these driver-side files
(including the pre-existing `camera-expgain.json`).

Neither side was live-verified against a running Monado session -- see
"What is NOT yet live-verified" below before treating any of this as confirmed
working end-to-end.

## 1. What was added and why

**Problem being solved:** a technician standing at the booth during a live session
has no glance-able trend view of session health (FPS, HMD temperature, camera
dropped-frame rate) -- only a static status snapshot refreshed every few seconds.
Separately, `~/vr/monado` was already *decoding* several pieces of HMD/controller/
camera data (calibration numbers, the raw HMD `DEVICE_STATUS` packet, controller
firmware serial + idle flag) but only ever exposing them through monado-gui's ImGui
widgets -- useless for an unattended kiosk dashboard, since that requires a live
debug-GUI session, not just a running compositor.

This round closes that gap in both directions:

- **Driver side** (`~/vr/monado`, branch `lab-full`): three new atomic JSON snapshot
  writers, following the exact tmp-file + rename idiom already used by the existing
  `hmd-temperature.json` and `camera-expgain.json` writers -- no new JSON library, no
  new timing/scheduling/tracking behavior anywhere.
- **Dashboard side** (`~/Documents/reverb-g2`, `scripts/status-dashboard.py` +
  `scripts/rig_telemetry.py`): defensive readers for all four snapshot files (three
  new + the pre-existing `camera-expgain.json`), a new **Vitals** section with three
  live sparkline charts (FPS, HMD temperature, camera dropped-frame rate), the
  Tracking-cameras/Headset-preview layout promotion, and the Audio-UI hide.

## 2. New file schemas (exact, read from the driver commit diff)

### `~/vr/perf-metrics.json`

Written from `comp_compositor.c`'s `compositor_layer_commit()`, wall-clock-throttled
to roughly once per second (`COMP_PERF_METRICS_SNAPSHOT_INTERVAL_NS`, a new
`perf_metrics_snapshot_last_ns` field on `struct comp_compositor`, not a frame-count
modulo -- display refresh rate isn't assumed to be a fixed constant).

```json
{"fps": 89.732, "frame_time_ms": {"min": 10.821, "avg": 11.145, "max": 12.903}, "ts": 1788581333}
```

- `fps` -- the same running average already backing monado-gui's "FPS (Compositor)"
  debug field (`compositor_frame_times.fps`).
- `frame_time_ms.{min,avg,max}` -- computed directly from
  `compositor_frame_times.timings_ms[]`, the same 50-sample ring buffer already
  backing the "Frame Times (Compositor)" debug graph. Full min/avg/max is reported
  (not just an instantaneous value) since iterating that buffer outside the ImGui
  path turned out cheap.
- All fields are always present; no field is ever null in this file (it is only
  written when the compositor is actually running a frame loop).

### `~/vr/camera-calibration.json`

Written **once**, from `wmr_hmd.c`'s `wmr_hmd_write_cam_calib_snapshot()`, called
from the existing `wmr_hmd_fill_slam_cams_calibration()`'s one call site (same place
that already logs this data via `wmr_hmd_log_cam_calib()`). Never polled or rewritten
after that -- this data cannot change at runtime, it's parsed once from the factory
config block at startup.

```json
{
  "cam0": {
    "image_size": {"w": 640, "h": 480},
    "fx": 286.421000, "fy": 286.512000, "cx": 320.114000, "cy": 239.887000,
    "k1": -0.012345, "k2": 0.003210, "k3": 0.000012, "k4": 0.000000, "k5": 0.000000, "k6": 0.000000,
    "p1": 0.000045, "p2": -0.000032,
    "pose": {
      "position": {"x": 0.0, "y": 0.0, "z": 0.0},
      "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    }
  },
  "cam1": { "...": "same shape" }
}
```

- One top-level key per camera, `cam0`..`cam<N-1>` for `N = wh->config.tcam_count`.
- `image_size` (`w`/`h` in pixels) is a deliberate addition beyond the originally
  requested field list -- `cx`/`cy` are only meaningful paired with the image
  dimensions they're relative to, and the values were already computed and available.
- `fx`/`fy`/`cx`/`cy` come from `cc->intrinsics[0][0]`/`[1][1]`/`[0][2]`/`[1][2]`;
  `k1`-`k6`/`p1`/`p2` come straight off `cc->wmr.k1..k6/p1/p2`; `pose` is
  `wh->config.tcams[i]->pose` (position + quaternion orientation).

### `~/vr/hmd-status.json`

Written from `wmr_hmd.c`'s `hololens_sensors_decode_packet()`, reusing the same
`temperature_log_count % 250` throttle already governing the existing
`hmd-temperature.json` write (~1/s at the sensor packet's own rate).

```json
{
  "device_status_raw": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "controllers": {
    "left":  {"fw_serial": "ABCD1234", "imu_zeroed": false},
    "right": {"fw_serial": "EFGH5678", "imu_zeroed": true}
  },
  "ts": 1788581333
}
```

- `device_status_raw` -- the last HMD `DEVICE_STATUS` (0x05) message's raw bytes,
  verbatim, length matching `sizeof(wh->device_status_raw)` (11 bytes in the current
  struct). No interpretation is added -- the meaning of these bytes is still an open
  TODO in the existing parse switch. Because `DEVICE_STATUS` is itself a rare,
  event-driven message (not sent every packet), this array can lag behind the file's
  own ~1/s write cadence -- it always reflects the last message actually *seen*,
  never a fabricated/interpolated one.
- `controllers` -- keyed `"left"`/`"right"`. **A side is omitted entirely** (not
  present as a key at all, never `null`) when that controller connection doesn't
  exist yet or has no device attached. Each present side has:
  - `fw_serial` -- the controller's real firmware serial (a `wmr_controller_base`
    field that already existed from a prior commit; distinct from the hardcoded
    `"Left/Right Controller"` `base.serial` literal, which this change does not touch).
  - `imu_zeroed` -- a **new** generic `bool` field added to `wmr_controller_base`
    (`wmr_controller_base.h`), mirroring `wmr_controller_hp.c`'s existing
    `last_inputs.imu.zeroed` computation with a one-line copy right after it's
    computed. `wmr_hmd.c` only knows the generic base struct, not any
    controller-variant-specific input struct, so this generic mirror field was the
    plumbing needed to reach it from there. Only ever set by the HP variant; stays
    `false` (the correct "unknown"/never-idle default) for variants that don't
    compute it (e.g. Odyssey).

### `~/vr/camera-expgain.json` (pre-existing, unchanged this round -- included for completeness since it's now wired into the same dashboard code paths)

Confirmed live shape, read directly off the box:

```json
{
  "cam0": {"exposure_us": 9000, "gain": 255},
  "cam1": {"exposure_us": 9000, "gain": 255},
  "cam2": {"exposure_us": 9000, "gain": 255},
  "cam3": {"exposure_us": 9000, "gain": 255},
  "dropped_frames": 0,
  "ts": 1788581333
}
```

The dashboard's reader also tolerates an optional `controller_tracking` key (not
present in any real sample seen so far) -- carried through as-is if present, never
invented.

## 3. Dashboard layout change

- **Tracking-cameras card** moved out of the tabbed `#panel-headset` (inside the
  Headset/GPU/CPU instrument-bank tabs) into the untabbed `.glance-grid`, stacked
  directly under the **Headset-preview** card in the same left-hand `.stack` column.
  Both cards are now a "live monitoring" pair visible regardless of which of the
  Headset/GPU/CPU tabs is selected -- confirmed live via CDP: with the CPU tab
  selected, `#camera-card` still reports `hidden:false, offsetParent:true,
  height:160px`.
- **Presence card** stayed inside the Headset tab, unchanged.
- **Audio card / dot / buttons / guide bullet hidden, not deleted:**
  - `#audio-card` (the "Audio outputs" card) and `#dot-audio` (the status-strip dot)
    both got a plain `hidden` attribute.
  - The 3 audio-route action buttons (`audio-headset`/`audio-external`/`audio-both`,
    tracked as `AUDIO_ACTION_IDS`) were already excluded from rendering by a
    pre-existing `AUDIO_ACTION_IDS` filter in `loadActions()` -- nothing needed
    changing there, only a clarifying comment was added.
  - Of the two audio-related guide bullets, only `guide_1` (pure audio troubleshooting)
    was hidden. `guide_2` (window focus) mentions audio only incidentally alongside
    essential, still-relevant gamepad-focus guidance, so it was left visible.
  - Everything underneath stays live: `audio_status()`, the `/api/audio-outputs`
    endpoint, and `hmd-audio.sh` integration are all untouched -- `tick()` still
    writes into `#audio-devices` every cycle, which is harmless against a hidden
    card and simpler than scattering conditionals through `tick()`.
  - One CSS fix needed along the way: `.status-dot`'s own `display:inline-flex` rule
    would otherwise beat the bare `hidden` attribute on specificity/origin grounds
    (an author rule always wins over the browser's UA `[hidden]{display:none}`), so
    a `.status-dot[hidden] { display:none; }` rule was added, mirroring the existing
    `.fault-dot[hidden]` pattern already in this file.

## 4. Why hand-rolled canvas charts instead of a CDN library

The Vitals section (three sparklines: FPS, HMD temperature, camera dropped-frame
rate) is plain `<canvas>` + vanilla JS -- no Chart.js/D3/etc. This is the same
reasoning this project already applies to its zero-web-fonts policy: **this kiosk
dashboard has no guaranteed internet connection**, and anything pulled from a CDN at
runtime is a single point of failure for a booth display that has to come up clean
on its own. Three scalar time series is little enough code (a ~60-sample ring buffer
per metric, redrawn each tick against a `<canvas>` 2D context) that a dependency
would add a network dependency and buys essentially nothing in return. The charts
use one steel-blue `--accent` line and dim gridlines, consistent with every other
numeric readout already on the page, and are explicitly framed as a **trend view**,
not a log/table -- the operating instruction behind this was "not like a log, but
like a clean flow" (a technician's at-a-glance session-health read, not raw data
dumped to scroll through).

The dropped-frame *rate* (as opposed to the raw cumulative counter already in
`camera-expgain.json`) is computed **client-side**, diffing consecutive samples
(frames / elapsed seconds) -- the same idea `rig_telemetry.py`'s own `cpu_telemetry()`
already uses server-side, diffing two `/proc/stat` reads. A negative delta (counter
reset, e.g. Monado restarted) or the very first sample report "no rate yet" rather
than a nonsense number.

## 5. Commits, CPU cost, and what is NOT yet live-verified

**Driver-side commit:** `1f45fc6b6354a846a3ae103e489da39c0ad58279`, branch `lab-full`,
repo `~/vr/monado` -- local only, not pushed.
Files: `src/xrt/drivers/wmr/wmr_hmd.c` (+137), `src/xrt/drivers/wmr/wmr_controller_base.h`
(+10), `src/xrt/drivers/wmr/wmr_controller_hp.c` (+5),
`src/xrt/compositor/main/comp_compositor.c` (+83),
`src/xrt/compositor/main/comp_compositor.h` (+6).

**Dashboard-side commit:** `56c52867be2ff83db25665ac49078c33a8f736d3`, branch `main`,
repo `~/Documents/reverb-g2` -- local only, not pushed.
Files: `scripts/rig_telemetry.py` (+164), `scripts/status-dashboard.py` (+281/-17).

### CPU cost (measured, dashboard side)

No new HTTP endpoint was added -- the 4 new fields ride the existing `/api/status`
response, cached behind the existing `MIN_REFRESH_INTERVAL_S=4.0`. Measured two ways:

- **The 4 new `rig_telemetry.py` functions in isolation** (2000 calls each,
  `resource.getrusage`): **~100µs combined per call** (`camera_expgain` ~44.6µs; the
  other three ~15µs each, since their backing files don't exist on the box yet and
  they hit the "no data yet" path) -- roughly 10-30x below the ~1ms/request concern
  threshold that prompted the measurement.
- **Whole `/api/status` rebuild** (including all pre-existing `nvidia-smi`/`lsusb`/
  `sensors`/`coredumpctl`/`git` subprocess calls), measured via `/proc/<pid>/stat`
  jiffies spaced beyond the cache TTL: **~3.3ms/rebuild**. The 4 new functions are
  roughly 3% of that total. Conclusion: negligible; no slower poll interval needed.

### What is NOT yet live-verified

Neither side of this round has been exercised against a real running Monado session
-- say this plainly rather than implying otherwise:

- **Driver side:** verified by a clean incremental rebuild only (`ninja -t clean`
  itself failed on an unrelated pre-existing `steamvr-monado` resource-directory
  issue, not caused by this change; verified instead by touching the 5 changed files
  and running a full incremental `ninja -j$(nproc)`). All 658 targets build; the 3
  touched translation units show zero new warnings (only the same 2 known
  pre-existing `wmr_hmd.c` warnings: sign-compare, integer-overflow);
  `monado-service`/`monado-gui`/`monado-cli`/the SteamVR driver all relink cleanly.
  **No live Monado session was started** (the project's own house rule requires
  confirming controller state with the operator before any live VR test, which
  wasn't possible during this build). None of the three new files have actually been
  observed appearing under `~/vr/` at runtime; the `hmd-status.json` controller
  fields in particular are code-reviewed only, never exercised against a real
  connected controller.
- **Dashboard side:** the page itself, its layout changes, and the Audio-hide were
  verified live (systemd service restarted, headless-Chrome CDP clicks/keyboard nav
  at 1400px and 420px, zero console errors) -- and `camera_expgain` was verified
  against a real file on disk, since that file already existed. But `perf-metrics.json`,
  `camera-calibration.json`, and `hmd-status.json` **did not exist on the box** at the
  time the dashboard side was built (the driver-side commit landed separately) --
  so the FPS chart, the camera-calibration readout, the HMD-status hex display, and
  the controller `fw_serial`/`imu_zeroed` extension were all only exercised through
  their "no data yet" / defensive-parsing fallback path, never against real,
  changing values from an actual driver.

Net: the code on both sides is written and internally consistent (the dashboard's
field names and null-handling match the driver's actual JSON output, confirmed by
reading both diffs directly), but the full pipeline -- driver writing real numbers,
dashboard reading and charting them, across an actual live session -- has never run
end-to-end. That is the next thing to check once a live session is possible.

## 6. monado-gui gap-analysis: what this round closes, what it leaves open

A separate, read-only research pass (repo `~/vr/monado`, branch `lab-full`, HEAD
`c36d680e0` at the time of the audit) mapped everything monado-gui's debug UI
already exposes for a G2 session against what a technician actually needs, and
ranked five gaps. Summary of what monado-gui already has:

- **FPS is real, not synthetic**: `compositor_layer_commit()` pushes a genuine
  wall-clock inter-frame sample every composited frame; "FPS (Compositor)" is a
  rolling average of that, and "Frame Times (Compositor)" is the live 50-sample
  history behind it. (This is exactly what `perf-metrics.json` now also dumps to
  disk.)
- **No true motion-to-photon latency exists anywhere in the tree.**
  `predicted_display_time_ns` is only a scheduling target, not a measurement. Two
  real proxies exist but neither is surfaced live: SLAM anchor-pose age (log-line
  only, gated off by default) and GPU render time + present-margin (reaches only an
  offline `XRT_METRICS_FILE` dump, off by default).
- **Camera/tracking-health confidence signals** exist (SLAM per-camera feature
  count, controller optical-constellation reprojection error) but are gated off by
  default and/or reach only CSV/log output, never a live technician view. The
  "Tracker status" text is static, set once at startup -- not a live health signal.

**Ranked gaps (most valuable first):** (1) SLAM per-camera feature count, (2) SLAM
anchor-pose age (best available latency proxy), (3) real GPU render time +
present-margin, (4) controller constellation quality-gate rejection counters, (5)
dropped-frame counter lacking a rate/recency dimension.

**What this round closes:** gap **(5)** is now half-closed -- the dashboard's Vitals
section computes a live dropped-frame *rate* client-side from the existing
cumulative `dropped_frames` counter in `camera-expgain.json` (a technician can now
tell "3 drops just now" from "3 drops 10 minutes ago", the exact complaint the gap
raised), though a *server-side* last-drop-timestamp field (the gap analysis's own
suggested addition) was not added -- the rate is reconstructed purely from polling,
not from a new driver field.

**What this round leaves entirely open:** gaps (1)-(4) are untouched. No SLAM
feature-count data, no anchor-pose-age numbers, no GPU render-time/present-margin
data, and no constellation quality-gate counters were added to any snapshot file or
to the dashboard this round -- all four remain exactly where the gap analysis found
them (gated off by default and/or log/CSV/offline-dump only, never live). This
round's driver-side work was scoped only to perf/calibration/HMD-status/controller
fields already requested, not to closing the gap analysis's list -- those remain a
separate, later piece of work.
