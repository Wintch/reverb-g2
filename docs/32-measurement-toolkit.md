# 32 — The measurement toolkit: what exists, what it answers, what's missing

Every tool below was written for a specific question that had already cost time; this file is
the index, so the next session picks the right one instead of writing a fourth variant of it.

Rule of thumb that runs through the whole table: **each tool answers exactly one question
and is blind to the others.** The cautionary tale: `frame-pacing.sh` reported a clean 13x
improvement while the wearer watched a brand-new artefact appear, because it counts missed
slots and cannot see latency. Read the "blind to" column before quoting a number.

## Method (read first)

- **Measure before fixing.** Turn each hypothesis into a number you can read from a log or a
  profiler, then go look. A refuted hypothesis is progress; the step-by-step reasoning path is
  in `docs/42`.
- **Env-gate everything.** Instrumentation and candidate fixes sit behind environment
  variables so they can be A/B'd on the same rig and turned OFF in unattended runs. The
  turntable fixture (`docs/38`) makes "the same rig" repeatable.

## Naming captures

A file name has to be something you can reference later; a screenshot named after the second
it was taken says nothing about what is in it. Convention for captures, logs and exports:

* **lowercase kebab-case, no spaces, no accents.** Spaces break every `for f in $(...)`.
* **The name says WHAT IT SHOWS**, not when it was taken (`a520m-rear-usb3-port-pairs.png`:
  the rear USB3 ports are two separated pairs, not interchangeable).
* **A date only when the capture is a dated measurement** (`nvidia-system-info-2026-08-05`),
  as `YYYY-MM-DD`, never `08-05-2026`.
* **Never a clock time.** Two captures the same day are distinguished by what differs:
  `-linux` / `-windows`, `-run1` / `-run2`, `-before` / `-after`.
* **Strip embedded metadata** before committing an image (`convert x.png -strip x.png`):
  `gnome-screenshot` writes `Software` and `Creation Time` into the PNG, and a phone writes
  far more, GPS included.

And the rule that outranks all of the above: **capture media does not go in the repo at all**
unless it carries information the numbers cannot. The repo is public and a frame of the bench
can carry something personal. `.gitignore` blocks the class; the measurements live in
`docs/pruebas.jsonl`, the reproducible part anyway.

## What we have

| Tool | The question it answers | Blind to |
|---|---|---|
| `scripts/power-on.py` | Is the whole rig ready, and if not, which physical thing do I touch? | Anything after the panel lights |
| `scripts/reseat_audio.py` | Same census, spoken aloud, for when your hands are behind the tower | Same |
| `scripts/frame-pacing.sh` | What share of frames miss their slot, and by how much | **Latency.** A change that trades judder for a stale pose looks like a pure win here |
| `scripts/pose-lag.py` | How many ms of lag each stage of the output pose pipeline adds (tracking → filtering → prediction) | Camera-exposure→SLAM delay and scanout — it measures *between* stages, not photon-to-pose |
| `scripts/pose-measure.py` | Absolute position drift over time (the 6DoF runaway question) | Rotation |
| `scripts/head-jitter.py` | Static head jitter, raw SLAM vs the pose the app receives, rotation AND position, jitter separated from drift (auto-detected static windows) | **Motion & feel** — only static windows; the wearer verdict during movement is separate. Needs a pose querent: with no client connected `filtering.csv` is empty and it reports "missing data" on a healthy tracker (launch `sleep N \| hello_xr`) |
| `scripts/constellation-frame-fit.py` | The constant rotation between two quaternion streams of one rigid body (solve vs IMU fusion), from a capture where the controllers ROTATE — Wahba on paired relative rotations. This is how the Rx180 bridge was identified after static data proved underdetermined | World frames and yaw, **by design** — that is its power. Needs real rotation in the capture; static data gives nothing |
| `timing.csv` col2−col1 (in any `SLAM_WRITE_CSVS` dir) | **VIO frame→pose age**: how old the SLAM pose is when Monado gets it — the dead-reckoning anchor age. This number found the 0.8 s Basalt input-queue backlog (`patches/basalt/0002`) | Where in the pipeline the time is spent |
| `scripts/drift-measure.py` | **CONTROLLER** orientation drift, on a fixed settle/capture protocol with audible phase cues | **The headset.** Asked a headset question it returns zeros with `trk 0%` |
| (no tool yet) | **HEADSET** orientation drift against gravity | Done by hand from `tracking.csv`/`filtering.csv` (quaternion → up-vector tilt, least-squares slope). Headset still, 97 s: **+0.47 °/min raw, +0.51 °/min delivered**, yaw −0.28/−0.24. Raw and delivered agreeing is the finding: the drift is Basalt's, not our output path. Deserves to become a script |
| `scripts/panel.py` | Is the panel powered and does it answer HID? (`activate` / status) | Whether anything is being scanned out |
| `scripts/drmprops.c` | Is the connector really the G2? EDID fingerprint, `non-desktop`, available modes | USB |
| `scripts/check-lease.sh` | Does this compositor offer the headset's connector for lease? | Only meaningful once the panel has been woken this boot |
| `scripts/controller-pair-check.py` | Are the controllers powered and answering? | Their tracking quality |
| `scripts/controller-battery-check.py` | Battery level (needs a live Monado session) | — |
| `scripts/capture-hid.sh` + `scripts/analyze-hid.py` | What does the headset say over HID, per mode; diff two captures | Anything not on the HID channel |
| `scripts/edid-tool.py` | Decode/synthesise EDIDs (the whole 6 bpc investigation) | — |
| `scripts/machine-specs.sh` | What machine is this, exactly | — |
| `scripts/usb-bus-reset.sh` | Software-only re-enumeration attempt | Proven *not* to fix a marginal seat |
| `windows-kit/power-on.ps1` | The Windows twin of `power-on.py`, plus `-Tune` for measurement settings | Not yet run on Windows |
| `windows-kit/run-diagnostics.ps1` | One-shot Windows capture bundle (USBPcap, DxDiag, GPU, EDID) | — |

## Windows captures: what was recorded and mined

Before planning another Windows capture session, check what previous ones already recorded.
These files are gitignored (`windows-kit2/` and local USBPcap captures never appear in
`git status`), so `git log` will not find them; look on disk.

- **`90hz.pcapng`, 317 MB, 45,663 frames, 101 s, ~6.05 GB of payload**, captured with the G2 at
  **90 Hz on Windows**. At ~60 MB/s it carries more than control traffic: the camera/sensor
  streams are in there. It was mined only for the 6 bpc/90 Hz question (the HID control
  channel), so the tracking-side questions (IMU cadence, camera frame pacing, controller
  report rate under the vendor stack) can still be asked of it without booting Windows.
  Alongside it: decoded HID (`hid_full.tsv`), HWiNFO and GPU-Z sensor logs, DxDiag, a USBDeview
  inventory and CRU output.
- Linux-side counterparts: `~/vr/hid-mode{0,1,2}.txt` (usbmon per display mode) and
  `windows-kit/linux-reference.txt`.

| Capture | Size | Mined for | Not yet mined |
|---|---|---|---|
| `flicker.pcapng` | 699 MB, 165k pkts, 267 s | companion `03f0:0580` fully decoded: cold panel bring-up is only report `0x50` SET+GET, `{0x04,0x01}`/`{0x04,0x00}`, `SET_IDLE` | the `0x03` DEBUG firmware log on the HoloLens Sensors interface |
| `aircar_90vs60_switch_windows_confirmed_fine.pcapng` | 1002 MB | companion decoded across a live 90<->60 switch; gave the `DEVICE_STATUS` reference rows in `docs/112` | same |
| `camera_apareo_standby*.pcapng` | 2.5 GB / 959 MB | none | everything |
| `joystick_secuencia_wolf.pcapng` | 3.1 GB | controller work | none |
| `Allinone.pcapng`, `solo1/solo2.pcapng`, `run_60hz_*`, `run_90hz_*` | assorted | the 60/90 comparison in `docs/13` | none |

**Finding the companion in a USBPcap file:** locate it generically with
`tshark -r F -Y "usb.idVendor == 0x03f0" -T fields -e usb.bus_id -e usb.device_address`, then
filter `usb.bus_id == N && usb.device_address == M` and dump with `-x`. `usb.capdata` comes
back empty for USBPcap files, so slice the hex instead; the URB header length is the first
little-endian u16.

## What we are missing, and what each would unlock

| Missing | Unlocks | Cost |
|---|---|---|
| `python3-numpy` | Every CSV analysis in this repo is pure Python today. `pose-lag.py`'s shift scan takes minutes on a 12-minute session; with numpy it is seconds, and proper cross-correlation/FFT becomes practical | apt, ~30 MB |
| `python3-matplotlib` | Plots of drift and pacing as evidence in the docs. Right now every result in this project is a number in prose; a drift curve is far more legible than "0.72 m at 60 s" | apt |
| `linux-perf` | Profile *where* Monado's 2.3 cores go (the total and thread count alone do not name the functions). This is the direct instrument for the CPU-budget question (see "Process-level profiling" below for the perf and gdb recipes) | apt |
| `gnuplot-nox` | Lighter alternative to matplotlib for quick ASCII/PNG plots from the CSVs | apt |
| A high-speed camera (a phone's 240 fps slow-mo is enough) | **Motion-to-photon latency**, the one number that would close the ghosting question directly instead of by inference. Point it at the panel with a moving marker in view and count frames between physical motion and displayed motion | free, needs a phone and a rig |

`docs/45-display-artifact-diagnosis.md` is the display-chain diagnosis protocol (strobe
crosstalk vs. reprojection vs. warm-up ghosting), built around the missing high-speed-camera
instrument above, plus a static full-field color-toggle test mode for the 360/VR180 player.
When filming through the lens, **do not film at an exact multiple of the refresh rate** (e.g.
90 or 180 fps for a 90 Hz panel): the aliasing hides the very frame drops you are trying to
see. Count how many camera frames each displayed frame persists for (irregular persistence =
judder).

Install line for the four apt ones:

```bash
sudo apt install -y python3-numpy python3-matplotlib gnuplot-nox linux-perf
```

## Measured results that belong with the tools

`pose-lag.py`, first run (12-minute Aircar session, `SLAM_FILTER=one_euro`,
pipelined pacing on):

```
tracking -> filtering   +42.5 ms     the one euro filter's own delay
filtering -> prediction -45.0 ms     forward prediction, compensating
tracking -> prediction   -2.5 ms     net: the rendered pose sits 2.5 ms AHEAD of raw SLAM
```

The three are self-consistent (42.5 − 45 = −2.5), and the estimator was validated by
injecting known shifts of 0 / +12 / −20 ms into a real stream and recovering
0 / +12.5 / −20.0 (0.5 ms resolution).

**That reading was WRONG, and the mistake is worth keeping** because it is the kind this
tool invites. From "prediction leads filtering by 45 ms" I concluded that the part of the
pipeline we control was healthy and the ghost had to live somewhere invisible. It doesn't.
Reading the code settled it: the path is `predict_pose() → filter_pose() → app`, so
`prediction.csv` is an **intermediate that never reaches the application** — what the app
gets is `filtering`, the +42.5 ms one. The number was right; the direction I read it in was
backwards. Lesson for the next reader: this tool tells you the lag *between two recorded
streams*, and which of them is the output is a fact about the code, not about the CSVs.

After patch 0044 moved the filter ahead of prediction, the same measurement on the same rig
reads **−5.0 ms** (the delivered pose now leads raw SLAM slightly), residual 0.01%. A swing
of 47.5 ms, matching what the wearer reported independently.

## What each tool is blind to — the running list

This is the column that matters when quoting a number.

| Tool | Blind to | How it bit |
|---|---|---|
| `frame-pacing.sh` | **Latency** | Pipelined pacing read as a clean 13x win while a brand-new ghost appeared in the headset |
| `frame-pacing.sh` | **The app's actual frame rate** | Reported 0.00% late of 2700 expected while the wearer was looking at 30 fps. It counts slots the *compositor* missed; an app delivering 30 fps punctually misses none |
| Monado's `App timing → GPU time` | **Actual GPU work** | It is `gpu_done_ns - delivered_ns`, so it includes queue wait behind the compositor and pins near one frame period. Halving the pixel count moved it by 0.02 ms. Use `nvidia-smi` power draw instead: 180 W → 85 W for the same change |
| Steam's FPS overlay | **The headset** | Reports something other than the delivered VR frame rate; it said 45 while the app delivered 29 and the compositor 90 |
| `drift-measure.py` | **The headset** | It measures CONTROLLER orientation drift — its first line says so. Run against a headset question it returns zeros with `trk 0%` |
| `pose-lag.py` | Absolute photon-to-pose latency | Measures *between* recorded stages only; which stage is the output is a fact about the code, not the CSVs |
| `pose-lag.py` | **Wall-clock delivery delay** | Both CSVs carry frame timestamps (when the pose WAS), not arrival times — a pose delivered 0.85 s late cross-correlates at ~0 lag. The tracker ran 0.8 s behind real time for weeks while this tool read "delivered leads raw by 5 ms", and both numbers are true. `timing.csv` col2−col1 is the instrument for delivery delay |
| Any of them | **Window focus** | Unreal and DXVK throttle when the game window is not focused. Two measurements minutes apart are not comparable unless both state their focus state |

**Root cause of the `GPU time` pin**: `comp_multi_compositor.c`'s wait
thread marks `gpu_done` after `wait_fence()`, but it handles one frame at a time and the previous
iteration ends in `wait_for_scheduled_free()` — so frame N's fence wait only *starts* after frame
N-1 was consumed by the compositor tick, and `gpu_done(N) − delivered(N)` ≈ one period for any app
running a frame ahead. The column is not a measurement of GPU work; and the app pacer feeds it
into `calc_app_period()` (period doubling) and the pipelined engage test, which is how a title
with the GPU at 25-54% got paced to 45 fps. Instrument that caught it: the `Delivered frame`
count below, read against `nvidia-smi` power at two render scales.

**The real app frame rate**, until a script wraps it:

```bash
# with U_PACING_APP_LOG=debug, one line per delivered app frame
a=$(grep -c "Delivered frame" ~/vr/jack-in-wayland.log); sleep 20
b=$(grep -c "Delivered frame" ~/vr/jack-in-wayland.log); echo $(( (b-a)/20 )) fps
```

**Pose CSVs are not tied to `VR_VERBOSE`.** They once lived inside that block, so silencing
the driver's 268 empty-poll log lines per second also silenced the only offline instrument,
and the stale file left behind looked exactly like a CSV writer dying mid-session.
`VR_POSE_CSVS=0` turns them off on their own.

## SLAM pose CSVs — the offline set

`scripts/slam-analysis/` holds nine one-question tools that read the per-session pose CSVs any
`VR_DEMO_RECORD=1` launch already writes to `~/vr/logs/demo-sessions/<run>/slam/`. Full table in
that directory's README; the investigation they were built for is
[113](113-dali-redraw-is-pose-staleness.md).

**What the set is blind to, and it cost most of a day to notice:** position drift and pose
staleness are different failures, and in one A/B they moved in OPPOSITE directions — the arm
that felt much better to the wearer had more drift and identical latency. `count-jumps.py`,
`motion-norm.py`, `anchor-dist.py`, `pinning.py` and `yaxis.py` all measure POSITION and are blind
to latency. A "redraw" complaint is a latency complaint: use `pose-latency.py`
(`received_by_monado - frames_original_timestamp` from `timing.csv`), which is the same quantity
`VIT_COLLAPSE_LOG=1` prints as `age_out_ms` but recorded per session instead of scraped from a log
that most harnesses truncate.

Second blindness, this one about the denominator: resets-per-minute is not comparable between
sessions, because the anchor guard fires on fast motion and a livelier session earns more resets
honestly. `motion-norm.py` exists to divide by path length and by time-above-1-m/s instead. And
before reading any time trend as degradation, check the distance SPREAD — a 22-minute session that
looked like it "degraded after 10 minutes" turned out to be one where the wearer stood still
(~20 cm of spread) for the first ten.

## Process-level profiling: perf, gdb, top -H

Tools used to root-cause the SLAM pose-rate collapse (`docs/39`), the constellation
correspondence-search CPU blow-up (`docs/40`) and the SLAM optical-flow frame drops, written so
the method can be replayed on another HMD.

### perf: sampling profiler (which functions burn CPU)

First reach for this when a process eats CPU and you want to know *where*.

```bash
perf record -F 999 -p <PID> -g -o out.perf -- sleep 8
perf report -i out.perf --stdio | head -40
```

Look at the top self-time symbols and their call chains (`-g`); symbols are real when the
target is built `RelWithDebInfo` (Monado and Basalt are). `kernel.perf_event_paranoid = 3`
blocks kernel-stack sampling (userspace sampling still works, and a "kernel profiling"
warning does not mean it failed); for kernel frames use
`sudo sysctl kernel.perf_event_paranoid=1` or `sudo perf`.

### Poor-man's gdb profiler

"Sampling by hand" when `perf` is unavailable: stop the process briefly, dump every thread's
stack, detach. This is what cracked the constellation CPU blow-up.

```bash
# 1) per-thread CPU, hottest first
top -H -b -d 2 -n 2 -p <PID> | awk '/COMMAND/{h=1;next} h&&NF>10' | sort -k9 -rn | head -6

# 2) classify a hot TID without stopping anything
cat /proc/<PID>/task/<TID>/syscall   # "running" = in userspace, not in a syscall
cat /proc/<PID>/task/<TID>/wchan     # "0" = not sleeping in the kernel
awk '{print $3}' /proc/<PID>/task/<TID>/stat   # R = running, S = sleeping

# 3) dump all thread stacks (brief stop, then detaches)
gdb -p <PID> -batch -nx -ex "set pagination off" -ex "thread apply all bt 12" > bt.txt
# map a hot LWP to its stack:
grep -nE 'LWP <TID>' bt.txt
```

- **Key signature:** `syscall = running` **and** `wchan = 0` **and** state `R` = a userspace
  busy-loop burning a core (not blocked on I/O). That exposed the unbounded constellation
  search: three threads all in `lambdatwist_p3p <- ... <- search_pose_for_model`.
- All Monado threads share the process name `monado-service`, so **map threads by stack, not
  by name**.
- `/proc/<PID>/task/<TID>/stack` needs root and shows only the kernel side; the gdb userspace
  backtrace is what you want.
- `gdb -p` briefly SIGSTOPs the whole process. Safe for a headset nobody is wearing (the DRM
  lease is kernel-side and survives a brief stop); avoid it while someone is in the headset.

### top -H: per-thread CPU

Use the **second** sample (`-n 2`; the first is a cumulative average). `%CPU` is per core: one
thread at ~100% `R` is a busy-loop, a cluster of ~10% threads is a parallel worker pool
(Basalt/TBB). `ps -o %cpu` reports a lifetime average that can differ a lot from the
instantaneous `top` figure; cross-check both.

## Env-gated instrumentation & fix toggles

Read from the environment by Monado/Basalt at launch (via `jack-in.sh`, which propagates
ambient env). They are **firehoses**; in an unattended run they must be OFF (`docs/42`,
`docs/43`).

| Variable | Pipeline | What it logs / does |
|---|---|---|
| `VIT_COLLAPSE_LOG=1` | Basalt SLAM/VIO | Per-frame `vit_collapse IN/OUT` (wall_ms, frame-ts gap, input queue depth, `dropped`), `vit_loop` (`pop_ms` image-wait, `imu_ms` processImu time), `vit_of` (optical-flow `total_ms`, keypoints, patches), `vit_vio` (optimize/marginalize ms, state sizes). The SLAM-collapse instrument (`docs/39`). |
| `CONSTELLATION_TRACKER_LOG=trace` | Controller constellation | Blob observations, pose solves, samples, reproj error, matched_blobs. **Separate from `WMR_LOG`**; `WMR_LOG=trace` is an unrelated USB/IMU firehose. |
| `HELLO_XR_POSE_STATS=1` | OpenXR client | Per-frame pose jitter/quality numbers from the `hello_xr` client. |
| `BASALT_IMU_NONBLOCK_CATCHUP` | Basalt frontend | The processImu collapse fix (`docs/39`). **Default ON**; `=0` restores the old blocking pop for an A/B. |
| `WMR_CONSTELLATION_SEARCH_BUDGET_US` | Constellation search | Per-model correspondence-search wall-clock deadline in microseconds (`docs/40`). **Default `0` = off**; e.g. `3000` caps each per-model search at 3 ms. |
| `WMR_CONSTELLATION_CONTROLLERS=1` | Constellation | Enables the controller constellation path at all (not exported by `jack-in.sh`; set it explicitly or nothing tracks controllers). |

**Parsing trap.** Monado/Basalt log these per-frame lines with `iostream` from several threads
at once, so writes **interleave and concatenate numbers** (two lines collapse into
`66.40690.001804`, or a timestamp bleeds into an `imu_ms` field). A naive
`grep -oE 'imu_ms=[0-9.]+'` then reports impossible values. **Match the full, anchored, clean
line before extracting**:

```bash
grep -oE '^vit_of total_ms=[0-9.]+ recall_ms=[0-9.]+ keypoints=[0-9]+ patches=[0-9]+$' log \
  | sed -E 's/vit_of total_ms=([0-9.]+).*/\1/'
grep -oE '^vit_loop pop_ms=[0-9.eE+-]+ imu_ms=[0-9.eE+-]+$' log | sed -E 's/.*imu_ms=//'
```

**Turntable fixture.** A cheap motorized turntable spinning a controller at a selectable,
roughly constant angular velocity (`docs/38`) made the SLAM collapse reproducible on demand
and is the repeatable stimulus for A/B tests. It keeps the controller awake and loads the
*constellation* pipeline, not head SLAM directly; sweep its speeds to separate rate-dependent
effects.

## Process hygiene between runs

Kill cleanly (`kill -TERM`, escalate to `-KILL` only if needed), verify the PID is gone, and
**remove the stale IPC socket** before relaunching:

```bash
kill -TERM <PID>; sleep 2; kill -0 <PID> 2>/dev/null && kill -KILL <PID>
rm -f /run/user/1000/monado_comp_ipc
```

Confirm which shared library and environment are actually live (Monado dlopens Basalt at
runtime); this catches "I rebuilt but the old `.so`/env is still live" before it wastes a run:

```bash
grep -i basalt /proc/<PID>/maps | awk '{print $6}' | sort -u
tr '\0' '\n' < /proc/<PID>/environ | grep -E 'BUDGET|NONBLOCK|CONSTELLATION|COLLAPSE'
```
