# 143 — Desk A/B of the constellation clock fix on hare_ware `10a23daab` (2026-10-10)

Follow-up to docs/135. Question: does our clock-domain fix (`783cf6ae5`, camera exposure timing
events published in monotonic time) make hare_ware's controller timesync sane, and does that
change tracking? Lab: dev (iashur), Debian 13, GNOME Wayland, DRM lease, 4320x2160@90, headset on
the desk, lights on, no wearer, no client. Controllers on the **host UB500 Plus** (docs/136), not
the headset radio.

## Arms

Both are hare_ware `10a23daab` + our !2967/!3004 series (8 commits) + the one-line BT descriptor
fix below (applied identically to both, uncommitted in the iashur worktrees). The only difference
is `783cf6ae5` (3 files, +28/−2); `git diff hw-ab-nofix hw-timesync-fix-v2` equals that commit.

| Arm | Branch | Worktree on iashur |
|---|---|---|
| fix | `hw-timesync-fix-v2` (`5e1c7d3c0`) | `~/vr/monado-hw` |
| nofix | `hw-ab-nofix` (`9e841c5c3`) | `~/vr/monado-hw-nofix` |

Kit: `scripts/hare-ware-ab/` (`ab-run.sh` one detached leg with `AB_TRANSPORT=bt|tunnel`,
`ab-ts.py` line timestamper, `ab-analyze.py`, `build-on-iashur.sh`, `PROTOCOL.md`). Each leg: 120 s
from compositor-ready, spoken nudge at 60 s ("move the controllers"), logs in `~/vr/logs/ab-*`.

## Upstream regression found on the way: host-BT WMR controllers break the whole WMR builder

The first leg never started: `ERROR [wmr_create_bt_controller] Failed to get WMR Bluetooth
controller string descriptor`, then `XRT_ERROR_DEVICE_CREATION_FAILED` — no headset at all.

Cause: upstream `b0b1d8b1b` ("drivers: fix dead stores", Simon Zeni, MR !2985) added to
`wmr_prober.c` `wmr_create_bt_controller()`:

```c
if (ret != 0) {
	U_LOG_IFL_E(log_level, "Failed to get WMR Bluetooth controller string descriptor");
	return XRT_ERROR_DEVICE_CREATION_FAILED;
}
```

but for a Bluetooth device `p_get_string_descriptor()` returns the `snprintf` length of the product
string (`p_prober.c:1438` at `13b5c134b`), i.e. > 0 on success. Every host-paired WMR controller
therefore fails, and because a BT creation failure is fatal to the builder, the headset goes with
it. The same file already checks the same call correctly at line 64 (`if (result <= 0)`).
Fix: `if (ret <= 0)`. Applied locally, the BT controllers were created and the legs ran. Present
on upstream `main` since !2985; our lab is pinned at `735e29e4e` (before it), so lab-full is not
affected. Not reported upstream yet.

## Results

| Leg | Arm | Timesync packets (L / R) | Found pose | Last pose | Notes |
|---|---|---|---|---|---|
| R1b | nofix | 2555/2596, 2617/2658 **negative**; device clock runs at **−27.9x** wall | 1389, one controller | +28.5 s | USB2 storm at +40 s, companion reconnected (!3004) |
| R2 | fix | **0 negative**, advances at **1.0007x / 1.0003x** wall | 992 (991 + 1) | +56.3 s | LED sync MAINTAIN, then resync after ~525 frames unseen, repeatedly |
| R3 | fix | 0 negative, 1.0008x | **0** | — | LED sync never leaves FIND_INITIAL_OFFSET; no blob ever matched |
| R4 | nofix | 2677/2739 negative, −27.8x | **0** | — | same as R3 |
| R5 ×3 | fix | — | — | — | after a controller power-cycle: left controller `fw read timed out` (281-345 ms) at BT controller creation, builder fails, 3/3 attempts, also with the controllers held and buttons pressed |

The nudge at 60 s never brought poses back in any leg (the user did move the controllers; LEDs on).

### Reading

1. **The clock fix is confirmed on hardware, in a clean A/B.** Without it, every timesync packet
   carries device-clock-minus-host time (negative, running backwards at ~28x); with it, the times
   are positive and advance at wall rate. This is the docs/135 double conversion, now measured on
   both arms of the same build.
2. **Tracking is not decided by the clock fix on this bench.** Poses decayed with time across
   legs in both arms (1389 → 992 → 0 → 0) with the controllers awake and LEDs on. In R3/R4 the
   tracker matched no blob at all. A controller-side state carried between sessions is the leading
   guess (untested: the power-cycle control could not run because of point 3).
3. **Host-BT controller creation is fragile after a power-cycle** on this branch: the left
   controller's firmware command times out and the builder aborts. Not investigated further.
4. **Shutdown crash in hare_ware's code**, 3 of 4 completed legs, both arms: SIGSEGV after SIGTERM.
   gdb on the core: the BT controller read thread is in `wmr_controller_base_handle_imu_sample` →
   `xrt_sink_push_imu(wcb->tracking.constellation_imu_sink)` (`wmr_controller_base.c:1113`) while
   the main thread is in `os_thread_helper_destroy` — the constellation tracker's IMU sink is gone
   before the controller thread stops (use-after-free in teardown order). Probably BT-specific in
   practice (tunnelled controllers stop with the HMD thread).

Caveat: this is the host-BT path (20 Hz idle / 200 Hz active reports), not the tunnelled path
hare_ware uses. Both arms shared it, so the clock comparison is clean; the tracking numbers do not
transfer to a tunnelled setup.

## Next

- Report to hare_ware (draft `notify-drafts/03`, outside the repo): add the hardware A/B for the
  clock (point 1) and the teardown crash (point 4); keep tracking claims out.
- Upstream: a one-line MR/issue for the `b0b1d8b1b` BT descriptor regression (needs the user's go;
  MR creation needs the web form, issues work over the API).
- If tracking is to be judged: tunnelled controllers (headset radio pairing from Linux is being
  prepared, `scripts/controller-pair-v2.py`) and a power-cycle before every leg.
