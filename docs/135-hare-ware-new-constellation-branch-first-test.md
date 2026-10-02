# 135 — First live test of hare_ware's `wmr-new-constellation-tracking` (2026-10-02)

First hardware test of `hare_ware/monado` `wmr-new-constellation-tracking` at tip `9e1773326`
(2026-09-30; 45 commits on upstream `main` `9950e2a5f`, post-!2940). See docs/134 for what the
branch is. Worn by the user on the lab (iashur), GNOME Wayland, DRM lease, 4320x2160@90.

## Build

- Separate worktree `~/vr/monado-hw` (detached at `9e1773326`), `RelWithDebInfo`,
  `BUILD_TESTING=OFF`. Production `~/vr/monado` (`lab-full`) untouched.
- **Needs Ceres >= 2.1.** Since !2940, `XRT_MODULE_CONSTELLATION_TRACKING` depends on
  `XRT_HAVE_BIGCERES`. Without it the branch fails to link (`cannot find -lconstellation`):
  the WMR driver links `constellation` unconditionally in `src/xrt/drivers/CMakeLists.txt`, so
  the whole WMR driver becomes unbuildable instead of just losing controller tracking. Worth
  telling hare_ware. Installed `libceres-dev` 2.2.0 (Debian, 28 packages) on iashur.
- **Same consequence for us:** `lab-full` predates !2940 and builds the old tracker without
  Ceres. Any rebase of our controller work onto current `main` now needs Ceres too.
- Launched through a temporary copy of the launcher, `~/vr/jack-in-wayland-hw.sh` (only `SERVICE=`
  changed), mode `ctrl` (`WMR_SLAM=0`), plus `WMR_HANDTRACKING=0`. The copy must live in `~/vr`:
  the launcher resolves `panel.py` relative to its own directory. Clients must use the branch's
  own `build/openxr_monado-dev.json`; `lab-full`'s libmonado clients (status dashboard) get
  `Invalid packet received` against an upstream service, harmless.
- Control build: upstream `main` at the branch's merge-base `9950e2a5f`, worktree
  `~/vr/monado-upbase`, launcher copy `~/vr/jack-in-wayland-upbase.sh`.

## Results

| Run | Build | Head (3DoF) | Controllers | Tracker "Dropping slow sample" |
|---|---|---|---|---|
| 1 | hare_ware `9e1773326` | wearer: "no tracking at all" | never tracked (`pos:-- trk:--` all session) | 2092 |
| control | upstream `9950e2a5f` | wearer: tracks fine | n/a (no WMR constellation upstream) | 0 |
| 2 | hare_ware `9e1773326` (same binary) | wearer: "everything moves fine" | tracked for ~10 s, then frozen | 34 at start, 351 by the end |

Run 2 detail (hello_xr pose log, 1 Hz, app space `Local`): both controllers acquire 6DoF poses
(`pos:OK trk:OK`, positions changing) for roughly ten seconds, then each pose freezes at an
exact constant value — right from 00:35:47, left from 00:36:01 — **while still flagged
`POSITION_TRACKED`**, until the end of the session. Wearer's description: "only the first 10
seconds were fine, now they follow me with head movement".

### Measured with gdb on the live process (no wearer, no sudo, `ptrace_scope=0`)

- No thread blocked on a mutex: not a deadlock. (Suspected from `wmr_controller_base_send_timesync`
  re-locking `data_lock` under `conn_lock`; ruled out.)
- `WMR: USB-HMD` (the HID read thread that carries both the HMD IMU and the tunnelled
  controllers) is healthy, polling in `os_hidraw_read`.
- HMD fusion alive in run 2, with and without a client: `wh->fusion.last_imu_timestamp_ns`
  advances in real time, `i3dof.rot` changes. With the headset still on the desk, yaw drifted
  ~27 deg in ~85 s (worth comparing against the control build before calling it a regression).
- Constellation tracker: four camera fast/slow thread pairs plus the camera USB thread, all
  alive and idle-waiting between frames; drops keep climbing, i.e. frames arrive, nothing matches.

## Reading

1. **Controllers freeze as "tracked".** After losing the constellation lock the controller
   pose comes from `m_relation_history_get` on the last pushed sample with its tracked flags
   intact (`wmr_controller_base_get_constellation_pose`, called from
   `wmr_controller_base_get_tracked_pose` with `use_constellation_poses` forced true and no IMU
   fallback). Two separate problems: (a) re-acquisition fails within seconds, consistent with
   the branch's own "broken, but less broken timesync" and the fast thread never matching;
   (b) a stale history sample is reported as `TRACKED` indefinitely instead of degrading to
   orientation-only / untracked.
2. **Head "no tracking" in run 1 is not reproducible.** Same binary, run 2 tracked fine, and the
   code path (`wmr_hmd_get_3dof_tracked_pose`) is byte-identical to upstream at the tip.
   Run 1 differed in the tracker storm (2092 drops) and a companion `os_hid_read -1`; the
   companion error appeared in both hare_ware runs and not in the control. Unexplained, keep
   an eye on it; not enough evidence to report as the branch's bug.

## Run 3 (debug) — both failures localised

Same binary, `WMR_LOG=debug`, `CONSTELLATION_TRACKER_LOG=debug`,
`CONSTELLATION_TRACKER_DATA_RECORDER_OUTPUT` on. Wearer: "image, no head 6dof, no controllers" —
run 1 reproduced.

### Head death = the G2 USB2 storm + upstream's read thread exiting (not hare_ware's bug)

gdb: the `WMR: USB-HMD` thread no longer exists. Service log:

```
ERROR [control_read_packets] Error reading from companion (HMD control) device. Call to os_hid_read returned -1
DEBUG [wmr_run_thread] Exiting reading thread.
```

Kernel: the whole USB2 branch (`usb 3-1`: hub `04b4:6506`, audio, companion `03f0:0580`)
disconnected and re-enumerated at 00:44:11 (companion `hidraw5` → `hidraw6`). The same event hit
00:22:34 (run 1 start — the "no head tracking" run) and 00:36:32 (end of run 2, after the wearer's
report). Upstream `wmr_run_thread` exits on a companion read error, taking the HMD IMU and the
tunnelled controllers with it. This is the storm of docs/60 and exactly what our **!3004
(companion hot-reconnect)** fixes; the control run simply did not hit a re-enumeration.

### Controller timesync sends a negative device time — hare_ware's bug, root-caused

Every one of the ~2670 timesync packets sent to the controllers in run 3 carried a negative
`slam_time_us` (logged as `uint64`, e.g. `time 18446744045771499111`): from −27938.05 s to
−27886.12 s, advancing in real time. Device clock was ~1658 s, host monotonic ~29596 s:
1658 − 29596 = −27938. The exposure timestamp is double-converted:

- `wmr_camera.c` (`img_xfer_cb`) publishes `T_TIMING_EVENT_TYPE_CAMERA_EXPOSURE_START` with
  `timestamp_ns = frame_start_ts`, read from the camera frame header — the driver's own comment
  says it is "from same clock as video_timestamps on the IMU feed", i.e. **HMD device clock**.
- `wmr_controller_base_timing_event_sink_push` treats it as host time
  (`next_slam_mono_ns = camera_exposure.timestamp_ns + 2 * interval`) and converts it again with
  `wmr_controller_base_host_ts_to_device` → a time ~host-uptime in the past.

With the LED sync scheduled against a nonsensical time the controller LEDs cannot line up with
the camera exposures, which fits the tracker matching almost nothing (1923 slow-thread drops in
~45 s, no `Found pose`) and losing the lock within seconds in run 2. Candidate fix: feed the
device-clock exposure time straight into the timesync (it is already the HMD's SLAM clock the
controllers expect), or convert device→host before publishing the timing event — not both.

Run 2's "frozen but still TRACKED" pose (stale `relation_history` sample, no IMU fallback) is a
separate issue and still stands. Tracker recording kept for offline replay:
`~/vr/datasets/constellation/ct-rec-20261002.bin` (1.7 MB); debug log
`~/vr/logs/jack-in-hw-wmrnct-run3-debug-20261002.log.gz`.

### Next, updated

1. Local experiment: patch the double conversion in `~/vr/monado-hw` and cherry-pick !3004's
   companion hot-reconnect so a USB2 storm can't kill the run; one wear test.
2. Report to hare_ware: the timesync double conversion (with the numbers above), the stale
   TRACKED pose, and the Ceres link failure. Not posted — needs the user's go.

## Next (written before run 3)

- Report (a), (b) and the Ceres link failure to hare_ware as a short factual test report, with
  the pose-log excerpt. Not posted yet — needs the user's go.
- Before that, if wanted: one more run with `WMR_LOG=debug` on the controller to see whether
  `host_ts_to_device` fails after the first seconds (the timesync hypothesis), and the yaw
  drift compared on the control build.
- Logs archived on iashur in `~/vr/logs/*-20261002.*` (service logs for both hare_ware runs
  and the control, the three hello_xr pose logs, the gdb thread dump of run 2).

## Run 4 — clock-domain fix + !2967/!3004, self-verified without a wearer

Branch `hw-timesync-fix` (local monado clone; also applied in `~/vr/monado-hw` on iashur):
`9e1773326` + one fix commit + our !2967/!3004 series (8 commits, cherry-picked clean). The fix
(`patches/hare-ware-test/0001-*.patch`, 3 files, ~27 lines): `wmr_camera` adds `wmr_source`'s
IMU-derived `hw2mono` offset to `frame_start_ts` before publishing the exposure timing event, and
publishes nothing until the offset is known. Built clean on iashur.

Launched with debug logging, controllers lying on the desk in camera view, no client, no wearer:

- Timesync packets now carry sane controller-clock times (`time 36785640`..`37178193` us,
  advancing), instead of −27938 s.
- Tracker: **1779 `Found pose`** (fast path + RANSAC recovery succeeding) in the first ~45 s,
  versus **0** in run 3 with the same binary minus the fix. No companion read error, read thread alive.
- **Open:** in the following 20 s the tracker logged zero new poses AND zero dropped samples,
  i.e. it stopped receiving work, not failing to match. Last poses were static (controllers at
  rest). Not yet explained: candidates are controller idle/sleep with no client, camera stream
  stalling, or the controller exposure frames stopping. The session was cut short (iashur went
  offline at ~01:00 while this was being checked), so no wear test of the fix yet.

Next: relaunch the `hw-timesync-fix` build, check whether controller packets / camera frames keep
flowing after ~45 s (count `timesync counter` and enable `CONSTELLATION_TRACKER_LOG=trace` briefly
for `Received blob observation`), then one wear test.
