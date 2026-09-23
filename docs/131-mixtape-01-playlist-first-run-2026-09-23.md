# 131 — "VR Mixtape 01" playlist: built and run clean end to end

Date: 2026-09-23, desk session on iashur, headset connected, nobody wearing at launch time.

## What was built

A short, named 6-clip playlist for `playlist-runner.py`, picked from the existing
`stereo3d-pack` converted output plus one already-converted music video the user pointed at
directly: `scripts/playlists/mixtape-01.json` (repo) / `~/vr/playlists/mixtape-01.json`
(deployed). One entry per individual file, not per directory, to avoid the mixed-format
single-projection issue `docs/02-player-360.md` documents for directory mode. Each `seconds`
value is the real `ffprobe` duration plus a ~10s buffer, not a guessed round number.

| # | Title | File | seconds |
|---|---|---|---|
| 1 | Steve Miller Band - Abracadabra | `abracadabra_sbs.mp4` | 230 |
| 2 | Terminator - Police Station | `dav2_demo/terminator_police_station_sbs.mp4` | 300 |
| 3 | Tron: Legacy | `dav2_demo/tron_legacy_sbs2048.mp4` | 180 |
| 4 | Eve of Destruction | `dav2_demo/eve_of_destruction_sbs.mp4` | 200 |
| 5 | Blade Runner - Skyline | `dav2_demo/blade_runner_skyline_vr180_4k.mp4` | 230 |
| 6 | Blade Runner - Visuals | `dav2_demo/blade_runner_visuals_vr180_4k.mp4` | 170 |

`gap_seconds: 6`. Committed to the repo (`41358c0`) and pushed to `Wintch/reverb-g2`; synced to
iashur's own tracked clone via `git pull --ff-only`.

Run command (single positional arg, the playlist JSON path — the runner also accepts `-` for
stdin):
```
python3 ~/vr/playlist-runner.py ~/vr/playlists/mixtape-01.json
```
For an unattended/background launch (so it survives the SSH session ending):
```
setsid nohup python3 ~/vr/playlist-runner.py ~/vr/playlists/mixtape-01.json > <logfile> 2>&1 < /dev/null &
disown
```

## Before launching: a leftover session from the same day had to be cleared

`monado-service` was still running from the earlier horizon100 Dalí worn-confirmation test
(`docs/130`), started 16:14, never torn down after the wearer's verdict — confirmed via
`/proc/<pid>/environ` showing `SLAM_PRED_POSITION_HORIZON_MS=100 VR_LAUNCH_APPID=591360`.
Closed with `jack-in-wayland.sh down`, which needed the 10s-grace SIGKILL escalation — same
pattern as [[project_controller_6dof_root_cause]]'s tally, now 6/6 for that class of session.

## The run: clean, 6/6, no wearer needed to confirm technical success

Launched detached at 17:02:28, ended (`state: complete`) at 17:26:54 — 24m26s wall time for
~21m40s of nominal clip runtime, i.e. ~15-20s of jack-in/teardown overhead per transition, which
is consistent and unremarkable. Full log is 592k lines
(`iashur:~/vr/logs/mixtape-01-run-20260923170228.log`); swept for errors:

- No `ERROR`, no `Traceback`, no failed file opens.
- Only warning type across the whole run: 24× `WARN:PERF: ... Vertex attribute ... not consumed
  by vertex shader` (4 per launch × 6 launches) — the same benign per-launch shader warning seen
  in every prior session, not new.
- **None of the 6 internal teardowns between clips needed the SIGKILL escalation** — plain
  graceful `jack-in-wayland.sh down` each time. This is a useful data point for
  [[project_controller_6dof_root_cause]]'s open "why does teardown hang 5-10/10 of the time"
  question: every prior tally coming from a hang was a controller-tracking (constellation
  camera pipeline) session; these 6 were plain 3dof video playback, no controller camera
  pipeline running at all. Consistent with — not proof of — the hang being tied to camera/SLAM
  thread shutdown specifically, not `jack-in-wayland.sh down` in general. Worth keeping in mind
  next time the hang recurs on a controller session: check whether it ever hangs on a
  camera-less 3dof session too.

## What this does and doesn't confirm

Confirmed (from logs): all 6 files exist, decode, and play through their full configured
duration with clean session bring-up/teardown each time, in playlist order, unattended.

**Not confirmed: actual visual quality of any clip** (projection correct, stereo alignment
correct, no artifacts) — nobody was wearing the headset to watch this run; this was launched and
monitored purely over SSH/log-tail per [[feedback_verify_rendered_not_source]]'s general rule,
a log-clean run is not the same claim as "looks right on the visor." That check is still open,
whenever there's a wearer available to spot-check a clip or two.
