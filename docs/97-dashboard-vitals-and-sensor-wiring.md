# 97 -- Driver-side JSON snapshots: perf metrics, camera calibration, HMD status

> **Scope note.** The writers described here (changes in `comp_compositor.c`, `wmr_hmd.c`,
> `wmr_controller_base.h`) exist only on the lab branch and are not part of the shipped patch series
> in `patches/monado/`. The readers in `scripts/` degrade to "no data" without them.

The Monado driver decodes several pieces of HMD/controller/camera data (calibration numbers, the raw
HMD `DEVICE_STATUS` packet, controller firmware serial and idle flag) but historically exposed them only
through monado-gui's ImGui widgets, which is useless for an unattended dashboard because it needs a live
debug-GUI session. Three atomic JSON snapshot files under `~/vr/` close that gap
(`perf-metrics.json`, `camera-calibration.json`, `hmd-status.json`), next to the two pre-existing ones
(`hmd-temperature.json`, `camera-expgain.json`). `scripts/rig_telemetry.py` and
`scripts/status-dashboard.py` read all of them defensively (a missing file or key reads as "no data
yet", never an invented value). All writers use the tmp-file + rename idiom of the existing
`hmd-temperature.json` / `camera-expgain.json` writers: no new JSON library, no new timing, scheduling or
tracking behaviour.

## 1. File schemas (exact, read from the driver diff)

### `~/vr/perf-metrics.json`

Written from `comp_compositor.c`'s `compositor_layer_commit()`, wall-clock-throttled
to roughly once per second (`COMP_PERF_METRICS_SNAPSHOT_INTERVAL_NS`, a
`perf_metrics_snapshot_last_ns` field on `struct comp_compositor`; not a frame-count modulo, because the
display refresh rate is not assumed constant).

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

### `~/vr/camera-expgain.json` (pre-existing)

Live shape:

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

Readers should tolerate an optional `controller_tracking` key (never present in a real sample so far).

## 2. Measured cost of the readers

No new HTTP endpoint: the four new fields ride the existing `/api/status` response, cached behind the
existing `MIN_REFRESH_INTERVAL_S=4.0`. The four `rig_telemetry.py` reader functions cost about 100 us
combined per call (2000-call `resource.getrusage` measurement); a whole `/api/status` rebuild, including
all the `nvidia-smi` / `lsusb` / `sensors` / `coredumpctl` / `git` subprocess calls, is about 3.3 ms, of
which the new readers are roughly 3%. Negligible; no slower poll interval needed.

The dashboard computes the dropped-frame *rate* client-side by diffing consecutive samples of the
cumulative `dropped_frames` counter (frames / elapsed seconds); a negative delta (counter reset, e.g.
Monado restarted) or the first sample reports "no rate yet" instead of a nonsense number.

## 3. monado-gui gap analysis (what a technician cannot see live)

A read-only audit of everything monado-gui's debug UI exposes for a G2 session:

- **FPS is real, not synthetic**: `compositor_layer_commit()` pushes a genuine wall-clock inter-frame
  sample every composited frame; "FPS (Compositor)" is a rolling average of that and "Frame Times
  (Compositor)" is the 50-sample history behind it (exactly what `perf-metrics.json` dumps).
- **No true motion-to-photon latency exists anywhere in the tree.** `predicted_display_time_ns` is only a
  scheduling target. Two real proxies exist but neither is surfaced live: SLAM anchor-pose age (log line
  only, gated off by default) and GPU render time + present margin (only an offline `XRT_METRICS_FILE`
  dump, off by default).
- **Tracking-health confidence signals** (SLAM per-camera feature count, controller
  optical-constellation reprojection error) exist but are gated off by default and/or reach only
  CSV/log output. The "Tracker status" text is set once at startup, not a live health signal.

Ranked gaps, most valuable first: (1) SLAM per-camera feature count, (2) SLAM anchor-pose age (best
available latency proxy), (3) GPU render time + present margin, (4) controller constellation
quality-gate rejection counters, (5) dropped-frame counter lacking a rate/recency dimension. Only (5) is
partly closed (the client-side rate above; a driver-side last-drop timestamp was not added). Gaps (1)-(4)
remain open: none of that data is in any snapshot file.
