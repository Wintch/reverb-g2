# Desk A/B protocol: timesync clock fix on hare_ware 10a23daab (tunnelled controllers)

Goal: replace the "not a clean A/B" caveat in notify-drafts/03-hare-ware-timesync-report.md with a like-for-like
measurement, and find out why the tracker went quiet ~45 s into run 4 (docs/135).
Rules: iashur only after the user is back from Windows; never sudo; never pkill -f (use PIDs / `pgrep -x`);
no wearer; analysis only after teardown; long run driven by a detached script (setsid nohup + .done marker), never a foreground ssh.

## Arms (the diff between them is exactly 3 files, 28 lines: wmr_camera.c/.h, wmr_source.c)

| Arm | Branch | Tree on iashur | Service |
|---|---|---|---|
| A = fix   | hw-timesync-fix-v2 (10a23daab + 783cf6ae5 + 8 x !2967/!3004) | ~/vr/monado-hw | ~/vr/monado-hw/build/src/xrt/targets/service/monado-service |
| B = nofix | hw-ab-nofix (10a23daab + the same 8 commits)                 | ~/vr/monado-hw-nofix (made by scratchpad/ab/build-on-iashur.sh) | .../monado-hw-nofix/build/.../monado-service |

Both arms contain !2967/!3004 on purpose, so a USB2 storm cannot kill the read thread in either one and the clock fix is the only variable.
Per run `ab-run.sh` verifies `/proc/<service pid>/exe` against the requested path and records the binary sha256 and git head in `.meta`; the two arms' sha256 must differ.
Never run `build-on-iashur.sh` (or any build) while a leg is running or within the same hour as the A/B: CPU load perturbs IMU arrival and the clock fit (T162).

## Kit (all in scratchpad/ab/, copy to iashur: `scp ab-run.sh ab-ts.py ab-analyze.py build-on-iashur.sh iashur:vr/` and `ssh iashur mkdir -p vr/tmp; scp hw-ab.bundle iashur:vr/tmp/`)

| File | Role |
|---|---|
| build-on-iashur.sh | builds both arms (run once, detached: `setsid nohup ~/vr/build-on-iashur.sh > ~/vr/tmp/build-ab.log 2>&1 < /dev/null &`) |
| ab-run.sh `<label> <service path> <duration_s>` | one unattended leg; preflight, launcher copy (only SERVICE=/LOG= differ), debug env, timestamped log, teardown, `.done` marker |
| ab-ts.py | line timestamper used by ab-run.sh (must sit beside it) |
| ab-analyze.py | per-leg summary + comparison table; pass only `ab-<label>-<stamp>.log` files |

ab-run.sh refuses (and touches nothing) if: a monado-service/vrserver/hello_xr is running, a systemd monado.socket is active, not a GNOME Wayland session, headset not 5/5 on USB, a host-Bluetooth G2 controller hidraw exists, the service path is inside `~/vr/monado` (production), disk < 2 GB, or another leg is running.
It waits until 20 s have passed since the previous leg (`AB_SETTLE`). It sets `VR_BT_CTRL_CHECK=0` itself. Its launcher failure marker is the launcher's own (`~/vr/.jack-in-failed`, as with the production launcher): after a failed leg investigate, then `AB_FORCE=1`.
`.done` first line: `status=ok|void|failed|refused|aborted`. `void` = it ran to the end but both tunnelled controllers were not created before the compositor came up (validity rule below). Abort a running leg gracefully with `touch ~/vr/logs/ab-STOP`.

## 0. Pairing gate (do this first, before any Monado)

1. UB500 Plus must be out of the machine (see section "UB500" below). Check: `ls /sys/class/bluetooth` empty and
   `grep -l 'HID_ID=0005:0000045E:0000066A' /sys/class/hidraw/*/device/uevent` prints nothing.
2. Preflight: Debian booted (not a leftover state), no `monado-service`/SteamVR/Steam running, `/run/user/1000/monado_comp_ipc` absent,
   `nvidia-smi --query-compute-apps=pid,process_name --format=csv` empty, `lsusb | grep -cE '03f0|045e|04b4'` >= 5 (same test as the launcher).
3. Wake both controllers (shake), then `~/.../reverb-g2/scripts/controller-pair-check.py 8` on iashur (copy it over if the lab checkout lacks it;
   it only uses the stdlib). PASS = both lines read `paired, online  (VID 0x045e PID 0x066a)`.
   - `paired, offline`: asleep/out of range. Shake again. If it stays offline while the LEDs are lit, the headset still holds a stale bond
     from before 10-03 (the controller re-bonded to the UB500) -> redo the Oasis pairing. This reading is an inference, not tested.
   - `UNPAIRED`: Oasis pairing did not take; redo it on Windows.
   - `no response` for one id: headset reports only controllers it has news of; wake that one and rerun.
4. Do not run the check while Monado is up (harmless but pointless); run it before every launch as the "awake" gate.

## 1. Preconditions for every run

- Room lights ON (dark room is the known runaway/starvation cause; docs/136 static protocol also ran lit).
- Headset on the desk, fixed, not touched between runs, display on (DRM lease as in docs/135). Nobody wearing it.
- Controllers on marked spots (tape / phone photo), <= 50 cm in front of the front cameras, LED rings facing the cameras.
  docs/136: visibility is perfect at 50 cm and zero from 75 cm, so farther than ~50 cm makes every arm look dead.
  Same spots, same orientation for all runs.
- Controllers awake BEFORE the launch command (check with controller-pair-check = ONLINE for both). Reason: the tunnelled controller exists only
  if the headset reports it ONLINE at startup (`hololens_ensure_controller`, wmr_hmd.c:~190-205), and the builder attaches it to the constellation
  tracker only if it already exists when `wmr_create_headset` returns (target_builder_wmr.c:272-280). A late-waking controller is neither exposed nor tracked.
- Launcher: `ab-run.sh` makes a throw-away copy of `~/vr/jack-in-wayland.sh` (diff it against scripts/jack-in-wayland.sh first: the two copies drift) differing only in `SERVICE=`/`LOG=`, and runs it as `up 1 ctrl` with `VR_VERBOSE=1` (= `XRT_LOG`/`WMR_LOG`/`SLAM_LOG=debug`, same as `dev`; NOT `quiet`, which scrubs `CONSTELLATION_TRACKER_LOG`).
  Env, identical for every leg and recorded in `.env`: `WMR_SLAM=0 WMR_HANDTRACKING=0 VR_VERBOSE=1 VR_PACING=0 VR_POSE_CSVS=0 VR_BT_CTRL_CHECK=0 CONSTELLATION_TRACKER_LOG=debug T_LED_SYNC_REFINEMENT_LOG=debug CONSTELLATION_TRACKER_DATA_RECORDER_OUTPUT=~/vr/datasets/constellation/ab-<label>-<stamp>.bin`.
  `WMR_CONSTELLATION_CONTROLLERS`, `WMR_CAMERAS`, `WMR_CONTROLLER_LED_INTENSITY*` are lab-full patches; hare_ware's branch ignores them (grep of src found none), so `ctrl` there just means SLAM off.
  A detached shell has `XDG_SESSION_TYPE=tty`: ab-run.sh recovers the real Wayland env through `gui_env.py` (and the launcher does too); the kit must be started from the iashur GNOME Wayland session's own user (`iam`), after a normal GNOME login.
- No client app (as in run 4). Poses are judged from the service log, not from an app. (The stale-TRACKED freeze of docs/135 needs a client and is out of scope here.)
- Hygiene before each launch is done by ab-run.sh (exact-comm `/proc` scan, never `pkill -f`; `kill -TERM` by PID, SIGKILL only after 20 s and flagged in `.done`; stale socket removed; 4 s USB settle; launcher `down` only to restore the GNOME idle-blank). You still do by hand: check `nvidia-smi --query-compute-apps` is clean (recorded in `.meta` before/after) and, after a SIGKILLed runner (cannot be trapped), `~/vr/jack-in-wayland.sh down`. A leg whose launcher needed attempt 2/3 is flagged `LAUNCHER_RETRY` (only the last attempt is counted) and is better repeated.
- Time budget: from starting ab-run.sh to the HMD thread reading the controller status is roughly 20-30 s (USB-stable check, launcher kill/settle, panel + DP wait), and a tunnelled controller that is not ONLINE then is not created. Wake the joys, pair-check, place on the marks, and start ab-run.sh immediately. The analyzer's `CONTROLLERS_MISSING` flag (and `status=void`) catches a late wake; a void leg is repeated, never averaged in.
- Logs are never overwritten: everything lands in `~/vr/logs/ab-<label>-<stamp>.*` (log, launcher.log, meta, env, usb.log, kernel.log, done). Use unique labels, e.g. `nofix-r1`, `fix-r2`, `fix-r3`, `nofix-r4`.

## 2. Order and timeline

Order: R1 nofix, R2 fix, R3 fix, R4 nofix (R4 optional but recommended: ABBA brackets drift/order effects; do it if R1 or R2 looks surprising or time allows).
~4 min per run including settle. Per run, on iashur, from an ssh session, detached (never a foreground ssh):

```
cd ~/vr && setsid nohup ./ab-run.sh nofix-r1 ~/vr/monado-hw-nofix/build/src/xrt/targets/service/monado-service 120 \
    > ~/vr/logs/ab-launch-nofix-r1.out 2>&1 < /dev/null &
# poll:  cat ~/vr/logs/ab-nofix-r1-*.done   (absent until the leg is over)
```
(fix arm: `~/vr/monado-hw/build/src/xrt/targets/service/monado-service`.)

Clock per run (t=0 = the launcher reported a usable compositor; `ready_epoch` in `.meta`, recorded because the launcher's `MONADO_MARKER: up` line is normally overwritten by the service's own file offset):

| t | Action |
|---|---|
| before | settle >= 20 s (automatic), wake controllers (speaker cue by the agent), `controller-pair-check.py 8` ONLINE x2, place on the marks, start ab-run.sh within ~10 s |
| 0 | ready |
| 0-60 | hands off. Observes the natural behaviour incl. whether/when it goes quiet (run 4: quiet from ~45 s after start) |
| 60 | NUDGE (`AB_NUDGE_AT`, default 60): ab-run.sh speaks "Agita los joys, tres segundos" through espeak-ng on iashur and records `nudge_epoch`. The user picks both controllers up for ~3 s, shakes gently, puts them back on the marks |
| 60-120 | hands off |
| 120 | automatic teardown (SIGTERM by PID, socket removed, USB settle, `down`), `.done` written |

Why ask for the nudge: hidraw offers no way to wake a tunnelled controller from software, and "went quiet = controller idle" cannot be tested otherwise.
docs/136: controllers drop from 200 Hz to a 20 Hz idle mode ~30 s after the last motion (measured on host BT, not tunnelled), and `t_wake` to
tracker start is already ~40 s, which matches run 4's quiet onset. The user only touches controllers at the cue, 4 times, 3 s each; no wearer involved.
If no quiet occurs in a run, the nudge is moot for that run (the analyzer says `NUDGE_NOT_NEEDED`).

## 3. Light analysis after teardown (nice -n 10, one run at a time; never hand raw logs to agents)

`python3 -I ~/vr/ab-analyze.py ~/vr/logs/ab-<label>-<stamp>.log [more logs]` (nice -n 10, one leg at a time; read its text output, never hand raw logs to agents). It prints per-leg
per-10-s bins (Found pose, slow drops, timesync lines), per-hand timesync sanity (negative/wrapped, backward steps, counter breaks, device/wall rate), LED-sync phases, link health
(companion errors/reconnects, read-thread exits, kernel USB events), FLAGS, and a COMPARISON table (`p<60s` = Found pose in the first 60 s after ready = C2; `tsync<0` = wrapped timesync packets = C1; `quiet?` and the `NUDGE_*` flags = C3; `ctrls` = controller ids created).
Strings it matches (hw/nct-10a23daab, all verified against the code's format strings): `Found pose for device %d` (t_constellation_tracker.cpp:869, needs CONSTELLATION_TRACKER_LOG=debug), `Dropping slow|fast sample %llu at ts %lld`
(t_constellation_tracker.cpp:278/1227), `Left|Right controller timesync counter N led_intensity N time <us> offset <us> ramp_width N` (wmr_controller_base.c:161, WMR_LOG=debug; `time` is a uint64 so a negative value prints as 1844...),
`Adding controller device %d` (wmr_hmd.c:192, WMR_LOG=debug), `Entering search phase: %d` (t_led_sync_refinement.c:130), `Error reading from companion ...` (wmr_hmd.c:591), `Exiting reading thread.` (wmr_hmd.c:692).
Sanity: `grep -c -F 'Found pose for device' <log>` on the first log confirms the debug level took effect. Also check `journalctl -k --since <t0>` for `usb 3-1` disconnects only if readable without sudo (ab-run.sh already stores a best-effort `.kernel.log`; else skip, do not escalate).

## 4. Criteria (set before looking at data; thresholds are guesses anchored on run 3 = 0 poses/1923 drops, run 4 = 1779 poses in 45 s)

Validity: both controllers ONLINE at launch and created before the compositor came up (`Adding controller device 0` and `1`; ab-run.sh `status=void` / analyzer `CONTROLLERS_MISSING` otherwise; a controller added later is logged but neither exposed nor tracked), `Using builder wmr` (ab-run.sh enforces it), no companion error/USB storm, no `LAUNCHER_RETRY`, lights on, nobody touched
the setup outside the cue. Otherwise the run is void and is repeated, never averaged in.

- C1 clock (deterministic): nofix has ~100% wrapped timesync times and fix has 0% (sane values, advancing, order of 1e7 us at first). The wrap itself depends on the boot: nofix sends
  `headset_clock - host_monotonic`, negative only while host uptime exceeds the headset clock. So read C1 through the analyzer's "first time + host uptime" line too (ab-run.sh records
  `host_uptime_at_ready_s`): for the nofix arm it must come out as a plausible headset clock (positive, seconds-to-hours, and consistent with the fix arm's `first` time at a comparable moment;
  docs/135 run 3 gave 1658 s), which confirms the double conversion even when the sign did not wrap. If nofix is NOT wrapped AND that sum is not consistent, check that
  device clock and host monotonic did not coincidentally line up after the reboot (error ~ host uptime minus headset uptime); if so the A/B cannot discriminate at this boot
  and the headset USB must be power-cycled to shift the offset. Otherwise 10a23daab changed the path and the draft's first paragraph needs rewriting.
- C2 tracking (`p<60s` column): Found pose in t=0-60: fix >= 500 in both runs and nofix < 50 (and >= 10x apart). Report per hand (which hand locks swaps run to run, docs/136 / docs/126 blob-pool lottery,
  so "either hand" is the pass bar and per-hand is information only). R2 and R3 within 2x of each other, else the A/B is noise-limited and needs more repeats.
- C3 quiet: a >= 10 s bin with zero Found pose and zero Dropping slow sample while timesync lines continue. Record onset and (onset - t_wake).
  After the nudge: poses resume within 15 s = idle hypothesis supported. They do not = not idle; then check whether timesync counter and camera frames still advance
  and rerun once with CONSTELLATION_TRACKER_LOG=trace for ~20 s (`Received blob observation`), as docs/135 already planned.

## 5. What each outcome does to the report draft

| Result | Draft action |
|---|---|
| C1+C2 pass, both fix runs agree | Replace the "Not a clean A/B / not wear-tested" sentence with the real A/B numbers on the new tip (state arms precisely: only the 3-file fix differs, both carry !2967/!3004, desk, controllers on the desk, no wearer). Delete the internal note that run 4's success may not carry over to the new tip. Keep "not wear-tested". Update the quiet sentence per C3. Still needs the user's go to post. |
| nofix also tracks (C2 fails, C1 shows wrap) | The clock bug is real but not the blocker at 10a23daab; drop "no Found pose" causality, post only the clock-domain observation, or hold. |
| both ~0 poses | Fix insufficient at the new tip. Do NOT post "the fix I tried" as a fix. Next suspects: the second clock bug (wmr_controller_base.c:1013 settle gate), camera/LED visibility. Hold the post. |
| fix worse than nofix | Fix is harmful (it publishes nothing until the offset is known; check how long that takes). Hold; investigate. |
| quiet + nudge resumes | Say controllers go idle without motion and resume on motion; remove "for reasons I haven't pinned down". |
| quiet + nudge does not resume | Keep the sentence, add the measured onset and what was ruled out. |

Also correct in the draft's internal notes (unverified by hardware, from reading 10a23daab): the builder calls `wmr_constellation_attach_controller_to_hmd` for BT controllers as well
(target_builder_wmr.c:272-280 -> wmr_controller_base_add_to_constellation_tracker), so "host-BT controllers get no constellation tracking on his branch" is probably too strong;
the `// TODO` comments next to wmr_create_bt_controller look stale. Soften until tested. Re-pairing to the headset is still right here: it keeps the tunnelled path of docs/135 runs 1-4.

## UB500 (controller side of the BlueZ bond)

- Recommendation: physically unplug the adapter (now, before powering the controllers for the Windows pairing); do NOT `bluetoothctl remove` for this test.
  Without an hci device bluetoothd creates no input/hidraw node, and `wmr_find_bt_controller_pair` (wmr_prober.c:206-255) only looks at bus Bluetooth + 045E:066A, so it cannot see anything.
  The bond files stay on disk under the adapter's address, so plugging it back restores the host side untouched; the bond is root-owned so it cannot be backed up without sudo.
- If the UB500 stays plugged: a controller that still holds the old key could reconnect to it, BlueZ would create a hidraw, and `wmr_find_bt_controller_pair` would return it.
  Builder logic is per hand: a BT controller is created only for a hand with no tunnelled controller (`if (left == NULL && ctrls.left != NULL)`, target_builder_wmr.c:~247-270),
  and a BT creation failure (asleep controller, 3 x 250 ms read timeout) is fatal for the whole builder -> Simulated HMD. And the launcher guard would wait 30 s and exit rc=2 while a bond exists.
- `bluetoothctl remove <addr>`: expected to work without sudo (same bluetoothd D-Bus policy as the unprivileged pair/trust/info calls in bt-winorder.py) but not verified; if refused, do not sudo, ask.
  It needs the adapter present. Use it only when restoring, not for this test.
- Unverified: whether `bluetoothctl devices Paired` prints nothing with no adapter (the launcher guard counts on that). Hence ab-run.sh forces `VR_BT_CTRL_CHECK=0`, and instead refuses to start while a host-BT G2 controller hidraw (`0005:045E:066A`) exists (`AB_ALLOW_BT_HIDRAW=1` overrides).
- Restoring host BT later (docs/136 "Pairing recipe"; scripts/bt-controllers/bt-winorder.py with G2_LEFT_BD/G2_RIGHT_BD, addresses are in memory project_g2_controllers_system_bt_test.md, not in the repo):
  1. UB500 directly in a USB 2.0 port (not the extension), plug in. 2. `bluetoothctl remove` both stale entries (controller no longer has that key; a stale bond breaks re-pairing).
  3. `bluetoothctl pairable on`; agent running. 4. Controller: power-cycle, hold the hidden battery-compartment button ~3 s (slow pulse), looped `bluetoothctl --timeout 25 scan on`.
  5. winorder L2CAP connect (PSM 0x11 with BT_SECURITY_MEDIUM, then 0x13). 6. `bluetoothctl trust`, power-cycle, hidraw 0005:045E:066A appears. 7. Controllers awake before Monado starts.
  Pairing to the headset and to the UB500 are mutually exclusive (single-peer bond), and each switch needs a physical re-pair (headset: Oasis on Windows; host: recipe above).
