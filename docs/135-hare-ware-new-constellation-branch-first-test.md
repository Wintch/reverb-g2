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

## Next

- Report (a), (b) and the Ceres link failure to hare_ware as a short factual test report, with
  the pose-log excerpt. Not posted yet — needs the user's go.
- Before that, if wanted: one more run with `WMR_LOG=debug` on the controller to see whether
  `host_ts_to_device` fails after the first seconds (the timesync hypothesis), and the yaw
  drift compared on the control build.
- Logs archived on iashur in `~/vr/logs/*-20261002.*` (service logs for both hare_ware runs
  and the control, the three hello_xr pose logs, the gdb thread dump of run 2).
