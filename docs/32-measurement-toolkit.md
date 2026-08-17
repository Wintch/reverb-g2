# 32 — The measurement toolkit: what exists, what it answers, what's missing

**Born 2026-08-13 (T176), at the user's request: "frená si hay buenas herramientas que aún
no tenemos y documentalas, así se puede repetir sin reinventar la rueda."** Every tool
below was written for a specific question that had already cost time; this file is the
index so the next session picks the right one instead of writing a fourth variant of it.

Rule of thumb that runs through the whole table: **each tool answers exactly one question
and is blind to the others.** The 2026-08-13 pacing episode is the cautionary tale —
`frame-pacing.sh` reported a clean 13x improvement while the wearer watched a brand-new
artefact appear, because it counts missed slots and cannot see latency. Read the "blind
to" column before quoting a number.

## What we have

| Tool | The question it answers | Blind to |
|---|---|---|
| `scripts/power-on.py` | Is the whole rig ready, and if not, which physical thing do I touch? | Anything after the panel lights |
| `scripts/reseat_audio.py` | Same census, spoken aloud, for when your hands are behind the tower | Same |
| `scripts/frame-pacing.sh` | What share of frames miss their slot, and by how much | **Latency.** A change that trades judder for a stale pose looks like a pure win here |
| `scripts/pose-lag.py` | How many ms of lag each stage of the output pose pipeline adds (tracking → filtering → prediction) | Camera-exposure→SLAM delay and scanout — it measures *between* stages, not photon-to-pose |
| `scripts/pose-measure.py` | Absolute position drift over time (the 6DoF runaway question) | Rotation |
| `scripts/head-jitter.py` | Static head jitter, raw SLAM vs the pose the app receives, rotation AND position, jitter separated from drift (auto-detected static windows) | **Motion & feel** — only static windows; the wearer verdict during movement is separate. Needs a pose querent: with no client connected `filtering.csv` is empty and it reports "missing data" on a healthy tracker (launch `sleep N \| hello_xr`) |
| `scripts/constellation-frame-fit.py` | The constant rotation between two quaternion streams of one rigid body (solve vs IMU fusion), from a capture where the controllers ROTATE — Wahba on paired relative rotations. This is how the Rx180 bridge was identified (T181) after static data proved underdetermined | World frames and yaw, **by design** — that is its power. Needs real rotation in the capture; static data gives nothing |
| `scripts/constellation-gate-validate.py` | What the published constellation stream looks like per hand: position scatter, consecutive steps, rx180 gravity mismatch, gate-drop counters | Hand attribution rides on adjacent-line log pairing (~% mispairs); reads only the 1-in-15 telemetry, not every solve. A yaw-ghost has a CLEAN gravity number here — scatter is the column that exposes it |
| `timing.csv` col2−col1 (in any `SLAM_WRITE_CSVS` dir) | **VIO frame→pose age**: how old the SLAM pose is when Monado gets it — the dead-reckoning anchor age. This number found the 0.8 s Basalt input-queue backlog (T180, `patches/basalt/0002`) | Where in the pipeline the time is spent |
| `scripts/drift-measure.py` | **CONTROLLER** orientation drift, on a fixed settle/capture protocol with audible phase cues | **The headset.** Asked a headset question it returns zeros with `trk 0%` — corrected here 2026-08-13 after this very table said otherwise and cost a measurement |
| (no tool yet) | **HEADSET** orientation drift against gravity | Done by hand from `tracking.csv`/`filtering.csv` (quaternion → up-vector tilt, least-squares slope). 2026-08-13, headset still, 97 s: **+0.47 °/min raw, +0.51 °/min delivered**, yaw −0.28/−0.24. Raw and delivered agreeing is the finding: the drift is Basalt's, not our output path. Deserves to become a script |
| `scripts/panel.py` | Is the panel powered and does it answer HID? (`activate` / status) | Whether anything is being scanned out |
| `scripts/drmprops.c` | Is the connector really the G2? EDID fingerprint, `non-desktop`, available modes | USB |
| `scripts/check-lease.sh` | Does this compositor offer the headset's connector for lease? | Only meaningful once the panel has been woken this boot |
| `scripts/controller-pair-check.py` | Are the controllers powered and answering? | Their tracking quality |
| `scripts/controller-battery-check.py` | Battery level (needs a live Monado session) | — |
| `scripts/capture-hid.sh` + `scripts/analyze-hid.py` | What does the headset say over HID, per mode; diff two captures | Anything not on the HID channel |
| `scripts/edid-tool.py` | Decode/synthesise EDIDs (the whole 6 bpc investigation) | — |
| `scripts/machine-specs.sh` | What machine is this, exactly | — |
| `scripts/usb-bus-reset.sh` | Software-only re-enumeration attempt | Proven *not* to fix a marginal seat (T171) |
| `scripts/triage-sweep.sh` | Launch many titles and collect logs — good for "which are worth a human's time" | **Verification.** A timed sweep is not a human seeing it (T073) |
| `windows-kit/power-on.ps1` | The Windows twin of `power-on.py`, plus `-Tune` for measurement settings | Written 2026-08-13, not yet run on Windows |
| `windows-kit/run-diagnostics.ps1` | One-shot Windows capture bundle (USBPcap, DxDiag, GPU, EDID) | — |

## Datasets we already own and have NOT fully mined

**This section exists because of a good catch by the user on 2026-08-13**: before planning
another Windows capture session, check what previous ones already recorded.

- **`windows-kit2/results/90hz.pcapng` — 317 MB, 45,663 frames, 101 s, ~6.05 GB of payload**,
  captured 2026-08-05 with the G2 running at **90 Hz on Windows**. At ~60 MB/s it is not
  just control traffic: the camera/sensor streams are in there. It was captured for the
  6 bpc/90 Hz question and mined only for that — the HID control channel. **The tracking-side
  questions in `docs/30` (what does sensor traffic look like when the vendor stack drives
  this headset: IMU cadence, camera frame pacing, controller report rate) have never been
  asked of this file**, and they can be, without booting Windows.
- Alongside it, from the same session: `hid_full.tsv` (10 MB, decoded HID), HWiNFO sensor
  log, GPU-Z sensor log, DxDiag, USBDeview inventory, CRU output, and screenshots of
  SteamVR running at 90 Hz.
- **Why it fell off the radar**: `windows-kit2/` is in `.gitignore` (line 3), so it never
  appears in `git status` and no commit ever mentions it. If you are looking for prior
  data, `git log` will not find it — look on disk.
- Linux-side counterparts already captured: `~/vr/hid-mode{0,1,2}.txt` (usbmon per display
  mode) and `windows-kit/linux-reference.txt`.

## What we are missing, and what each would unlock

| Missing | Unlocks | Cost |
|---|---|---|
| `python3-numpy` | Every CSV analysis in this repo is pure Python today. `pose-lag.py`'s shift scan takes minutes on a 12-minute session; with numpy it is seconds, and proper cross-correlation/FFT becomes practical | apt, ~30 MB |
| `python3-matplotlib` | Plots of drift and pacing as evidence in the docs. Right now every result in this project is a number in prose; a drift curve is far more legible than "0.72 m at 60 s" | apt |
| `linux-perf` | Profile *where* Monado's 2.3 cores go. Today we know the total and the thread count, not the functions. This is the direct instrument for the CPU-budget question that `docs/30` is trying to answer from the outside | apt |
| `gnuplot-nox` | Lighter alternative to matplotlib for quick ASCII/PNG plots from the CSVs | apt |
| A high-speed camera (a phone's 240 fps slow-mo is enough) | **Motion-to-photon latency**, the one number that would close the ghosting question directly instead of by inference. Point it at the panel with a moving marker in view and count frames between physical motion and displayed motion | free, needs a phone and a rig |

**This gap got a name and a protocol on 2026-08-17 (T206)**: the wearer named a subtle
late "color fill-in" artifact at the resolution limit of feel-testing —
`docs/45-display-artifact-diagnosis.md` is the display-chain diagnosis protocol (strobe
crosstalk vs. reprojection vs. warm-up ghosting), built exactly around the missing
high-speed-camera instrument above, plus a static full-field color-toggle test mode for the
360/VR180 player.

Install line for the four apt ones:

```bash
sudo apt install -y python3-numpy python3-matplotlib gnuplot-nox linux-perf
```

## Measured results that belong with the tools

`pose-lag.py`, first run (2026-08-13, 12-minute Aircar session, `SLAM_FILTER=one_euro`,
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

Added 2026-08-13 (T178) after the same instrument misled twice in one session. This is the
column that matters when quoting a number.

| Tool | Blind to | How it bit |
|---|---|---|
| `frame-pacing.sh` | **Latency** | Pipelined pacing read as a clean 13x win while a brand-new ghost appeared in the headset (T175) |
| `frame-pacing.sh` | **The app's actual frame rate** | Reported 0.00% late of 2700 expected while the wearer was looking at 30 fps. It counts slots the *compositor* missed; an app delivering 30 fps punctually misses none |
| Monado's `App timing → GPU time` | **Actual GPU work** | It is `gpu_done_ns - delivered_ns`, so it includes queue wait behind the compositor and pins near one frame period. Halving the pixel count moved it by 0.02 ms. Use `nvidia-smi` power draw instead: 180 W → 85 W for the same change |
| Steam's FPS overlay | **The headset** | Reports something other than the delivered VR frame rate; it said 45 while the app delivered 29 and the compositor 90 |
| `drift-measure.py` | **The headset** | It measures CONTROLLER orientation drift — its first line says so. Run against a headset question it returns zeros with `trk 0%` |
| `pose-lag.py` | Absolute photon-to-pose latency | Measures *between* recorded stages only; which stage is the output is a fact about the code, not the CSVs |
| `pose-lag.py` | **Wall-clock delivery delay** | Both CSVs carry frame timestamps (when the pose WAS), not arrival times — a pose delivered 0.85 s late cross-correlates at ~0 lag. T180: the tracker ran 0.8 s behind real time for weeks while this tool read "delivered leads raw by 5 ms", and both numbers are true. `timing.csv` col2−col1 is the instrument for delivery delay |
| Any of them | **Window focus** | Unreal and DXVK throttle when the game window is not focused. Two measurements minutes apart are not comparable unless both state their focus state |

**The real app frame rate**, until a script wraps it:

```bash
# with U_PACING_APP_LOG=debug, one line per delivered app frame
a=$(grep -c "Delivered frame" ~/vr/jack-in-wayland.log); sleep 20
b=$(grep -c "Delivered frame" ~/vr/jack-in-wayland.log); echo $(( (b-a)/20 )) fps
```

**Pose CSVs are no longer tied to `VR_VERBOSE`** (T178). They used to live inside that
block, so silencing the driver's 268 empty-poll log lines per second also silenced the only
offline instrument in the project — and the stale file left behind looked exactly like a
CSV writer dying mid-session, which was investigated as a regression before the environment
was checked. `VR_POSE_CSVS=0` turns them off on their own now.
