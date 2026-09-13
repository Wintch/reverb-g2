# slam-analysis — offline tools for the per-session SLAM pose CSVs

Written 2026-09-07 during the Dalí redraw investigation ([docs/113](../../docs/113-dali-redraw-is-pose-staleness.md)).

## Where the input comes from

Any demo-button launch with `VR_DEMO_RECORD=1` writes per-session CSVs:

```
~/vr/logs/demo-sessions/<run>/slam/{tracking,filtering,prediction,timing}.csv
/mnt/vrtmp/slam-<ts>/                     # the same files, live, during the run
```

So **every worn run through a demo button is measurable afterwards**, with no special
instrumentation and without depending on `~/vr/jack-in-wayland.log` surviving (several harnesses
truncate it).

Two traps that have already cost real results:

- **The recorder persists its session directory asynchronously.** `ls -dt ... | head -1` right
  after a run returns the *previous* session. Match by `slam_config_final` in `summary.json`.
- **`SLAM_WRITE_CSVS` flushes when the tracker is destroyed.** A hard `jack-in-wayland.sh down`
  kills the service first and leaves the directory empty.

## Which file answers what

- `tracking.csv` — raw pose out of Basalt
- `filtering.csv` — after the one_euro filter; **this is what the wearer sees**
- `prediction.csv` — after prediction
- `timing.csv` — absolute stamps for every frontend/backend stage

## The tools

Each answers exactly one question and is blind to the others — see
[docs/32](../../docs/32-measurement-toolkit.md) for why that framing matters here.

| tool | question |
|---|---|
| `count-jumps.py <csv> [thr]` | how many pose discontinuities, and how big |
| `motion-norm.py <csv>` | resets normalised by path length and fast-motion time |
| `cluster.py <csv>` | isolated events, or one episode re-firing every ~2 s |
| `anchor-dist.py <csv>` | distance-from-anchor distribution, and where resets sat in it |
| `yaxis.py <csv>` | sustained level shifts (a viewpoint that drops and *stays* dropped) |
| `pinning.py <csv> <radius>` | is the output pinned at the guard radius after the first trip |
| `recall-trend.py <timing.csv>` | does any frontend stage grow over the session |
| `worn-window.py <csv> <mark_ns> [s]` | restrict the above to the worn segment only |
| `pose-latency.py <timing.csv> <mark_ns> [s] [label]` | end-to-end pose latency |
| `predict-error.py <session_dir>` | how far the PREDICTED pose lands from where the head really was, binned by yaw/pitch rate |
| `heading-bias.py <csv>` | CONTROLLERS, not the head: is their heading error a stale gyro bias or noise? Reads lab patch 0107's WMR_CONTROLLER_HEADING_CSV. See docs/125 |

Harnesses: `static-drift.sh` (hello_xr, no game), `static-recorded.sh` (demo-recorder path, the
one that reliably writes CSVs), `don-ab.sh <arm>` (one arm of a worn A/B, emits a
`CLOCK_MONOTONIC` marker for `worn-window.py`).

## Comparing configs without a wearer (2026-09-13)

A worn A/B cannot hold the input constant: two donnings never repeat the same head motion, so the
4-arm `SLAM_PRED_NECK_ARM_MM` sweep had to be binned by angular rate before its arms could even be
put side by side. Record the motion **once** instead, then replay it through as many configs as
you like:

```
record-euroc.sh [name]                       # ~3.5 min worn, spoken routine, writes a EuRoC dataset
replay-euroc.sh <dataset> <label> [K=V ...]  # one config, headless, reports via predict-error.py
```

`record-euroc.sh` waits for `/tmp/record-euroc.go` before starting the routine, so the wearer is
never rushed by a timer (the first take was lost to exactly that). Wear it for the recording if at
all possible — the neck-arm model is about rotation around a real neck pivot, which hand-held
motion does not reproduce.

`replay-euroc.sh` needs no headset, wearer, compositor or OpenXR client: it drives
`monado-cli slambatch`, which streams the dataset through the real tracker and the real prediction
code. It depends on lab patches 0105/0106 and on `~/vr/logs/calib-g2-2cam.json`; the reasons for
each are in `patches/monado/README.md` under 0105–0106, and they are not obvious — read that
before changing anything in the harness.

**The trap that makes a replay lie**: with a G2 plugged in, the prober picks the `wmr` builder and
the service tracks the *real cameras* while looking completely healthy. The first replay reading
here was a headset lying on a desk, not the dataset. Check the log for
`Selected wmr because it was certain it could create a head` before believing any replay result
from the service path.

### Run replays ONE AT A TIME

A replay uses ~3 of 12 cores, so three or four fit and a 40-minute sweep looks like it should
collapse to twelve. Don't. Pipeline latency **is** the prediction horizon, and the prediction
horizon is the quantity under test — so anything that inflates latency changes the measurement.
CPU contention does exactly that: the same Basalt frontend at the same 30/2 density measures
**14.5 ms isolated and 24.1 ms** in [docs/113](../../docs/113-dali-redraw-is-pose-staleness.md),
where a game ran alongside. Parallel runs would each measure a different machine, varying with how
they happened to overlap.

For the same reason the playback speed is fixed at 1x (`EUROC_MAX_SPEED=0`,
`EUROC_USE_SOURCE_TS=0`). Those are load-bearing, not defaults to tidy up. The compute ceiling if
you ever *did* drop the pacing — valid for tracking comparisons, never for prediction — is about
2.3x real time, set by that 14.5 ms frontend.

And when quoting results: a replay measures a *less loaded* machine than a real game session. It is
sound for comparing configs against each other, which is the point, but its absolute numbers are
not in-game truth.

## The one rule worth repeating

**Drift and "redraw" are different failures and they can move in opposite directions.** Judge a
redraw complaint with `pose-latency.py`, never with position ranges. Most of 2026-09-07 was spent
measuring position to diagnose a latency complaint.

And a third failure, separate from both: **prediction error** — the pose is fresh and the tracker
is healthy, but the extrapolation to display time lands in the wrong place. That is what
`predict-error.py` measures, and until 2026-09-13 nothing here could see it, so the artifacts the
`SLAM_PRED_*` knobs introduce could only be judged by a wearer. Judge an "it carries me further
than I turned" / "pitching drops me" complaint with `predict-error.py`, not with the other two.

Normalise resets by movement, never by wall time: the guard fires on fast motion, so a livelier
session earns more resets honestly. And check the distance *spread* before reading a time trend —
a session that looks like it "degraded after 10 minutes" may just be one where the wearer stood
still for the first ten.
