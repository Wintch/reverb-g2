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

Harnesses: `static-drift.sh` (hello_xr, no game), `static-recorded.sh` (demo-recorder path, the
one that reliably writes CSVs), `don-ab.sh <arm>` (one arm of a worn A/B, emits a
`CLOCK_MONOTONIC` marker for `worn-window.py`).

## The one rule worth repeating

**Drift and "redraw" are different failures and they can move in opposite directions.** Judge a
redraw complaint with `pose-latency.py`, never with position ranges. Most of 2026-09-07 was spent
measuring position to diagnose a latency complaint.

Normalise resets by movement, never by wall time: the guard fires on fast motion, so a livelier
session earns more resets honestly. And check the distance *spread* before reading a time trend —
a session that looks like it "degraded after 10 minutes" may just be one where the wearer stood
still for the first ten.
