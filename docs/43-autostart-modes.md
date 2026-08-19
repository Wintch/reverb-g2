# Autostart modes and logging teardown (2026-08-17)

`jack-in.sh` now has an explicit **mode system**. One order-independent argument pass
classifies every argument into three orthogonal choices — the lifecycle **mode**
(`up` / `dev` / `quiet` / `down`), the **tracking** mode (`3dof` / `6dof`), and `--force` —
and each mode carries a decided **logging policy** instead of leaning on Monado's
compiled-in defaults and whatever `*_LOG` happened to be exported. This closes the standing
agenda item from `docs/42` ("Toward unattended diagnostics"): the `*_LOG=trace` /
`VIT_COLLAPSE_LOG` firehoses used all through the 2026-08-17 tracking session are
investigation-only, and an unattended station must run with them **off** and, when idle,
**write nothing extra** — "these things don't ask to be fed."

This documents the X11/60Hz everyday launcher,
`~/Documents/linux_vr_base/jack-in.sh`, where the modes were implemented and tested (a
pristine pre-change backup is at `jack-in.sh.orig`). That launcher has **diverged** from the
repo's `scripts/jack-in.sh` copy (box-specific panel-wake and monitor handling — a known
reconciliation debt), so this doc — not a file sync — is the portable **contract**: apply it
to the repo copy and to the Wayland/90Hz autostart `scripts/jack-in-wayland.sh` (dev's, a
different logging model) per the last section.

## Why this exists

The firehose inventory (`docs/41`, "Env-gated instrumentation & fix toggles") and the
playbook's closing agenda (`docs/42`) both spell out the same requirement: those per-frame
logs add I/O and, worse, **interleave across threads and corrupt naive parsing** (the
`66.40690.001804` trap in `docs/41`). They are opt-in tools for a human at the keyboard,
not something an idle station should emit. So the launcher needed clear modes: enter to
continue dev work (verbose, interactive) or bring the station up self-sufficiently and
silent — and a clean way to take it back **down** that writes nothing.

## The four modes

| Mode | Aliases | Purpose | Logging |
|---|---|---|---|
| **`up`** | `start` | **Default.** Quiet dev launch. | Monado logs pinned `warn`; firehoses left off; **ambient `*_LOG` still honored** (opt-in preserved). |
| **`dev`** | `--verbose`, `-v` | Verbose diagnostic launch. | `WMR`/`XRT`/`SLAM`/compositor logs at `debug`; ambient still wins. |
| **`quiet`** | `unattended` | Self-sufficient station. | Levels **hard-pinned** `warn`; firehoses and the debug GUI **actively scrubbed** (`env -u`); dev usage banner suppressed. |
| **`down`** | `stop` | Clean teardown. | Not a launch: SIGTERM Monado, remove the socket, restore the desktop. Writes nothing to disk. |

### `up` (default)

`./jack-in.sh` with no mode argument is `up`. It is a faithful superset of the old no-args
default: it sets `WMR_LOG=${WMR_LOG:-warn}`, `XRT_LOG=${XRT_LOG:-warn}`,
`SLAM_LOG=${SLAM_LOG:-warn}`, `XRT_COMPOSITOR_LOG=${XRT_COMPOSITOR_LOG:-warn}` — identical
effective noise to before (Monado's compiled default was already `WARN`), now deterministic.
Because every level is `${VAR:-warn}`, an ambient export still wins, so a single firehose
can be opted in without leaving `up` (see "Opting in a single diagnostic var").

### `dev`

Same launch path as `up`, but the four log levels default to `debug`
(`WMR_LOG=${WMR_LOG:-debug}`, etc.). Ambient still overrides, so `dev` is "verbose by
default, tune from there." Use it when you are actively working and want the running
commentary.

### `quiet` / `unattended`

The one deliberately non-inheriting mode. It **hard-pins** `WMR_LOG=warn XRT_LOG=warn
SLAM_LOG=warn XRT_COMPOSITOR_LOG=warn` (no `${VAR:-…}` — ambient does **not** win), pins the
pacing logs (`U_PACING_APP_LOG=warn`, `U_PACING_COMPOSITOR_LOG=warn`,
`U_PACING_LIVE_STATS=false`), and **actively strips** the opt-in firehoses and the debug GUI
via `env -u`:

```
-u VIT_COLLAPSE_LOG  -u CONSTELLATION_TRACKER_LOG  -u HELLO_XR_POSE_STATS
-u SLAM_UI           -u XRT_TRACING                -u XRT_DEBUG_GUI
```

This resolves the apparent tension between "OFF by default" and "opt-in-able": `up`/`dev`
honor ambient (opt-in lives there), and `quiet` is the exception that refuses to inherit —
it is the station you can walk away from. It also suppresses the dev usage banner at the end
(the OpenXR launch snippet), since no human is reading it.

**What `quiet` does NOT silence** (be honest about this — it is in the script comment too):
scrubbing only removes the opt-in / debug variables, which are off by default anyway. It
does **not** stop **default-level fault storms** — the `img_xfer_cb "Invalid frame magic"`
flood on a degraded cable (`docs/22`), or the companion-storm CPU spin — because those log
at `WARN` and above and `WARN` cannot gate them. And `$LOG` is **not** rotated, so an
unattended run sitting under a persistent fault can still grow the log. `quiet` is
deterministic low-noise, not guaranteed silence.

### `down` / `stop`

Teardown, not a launch. It:

- SIGTERMs `monado-service` (all matching PIDs), waits up to 10s, then escalates to
  `kill -9` only if the service ignored TERM. **SIGTERM is on purpose** — Monado's TERM
  handler runs the clean path (screen-off, display lease released). This is the *opposite* of
  the launch path's `kill -9` (which is used only to keep the panel lit mid-bringup); do not
  "fix" the teardown to match the launch path.
- Removes the stale IPC socket (`/run/user/$UID/monado_comp_ipc`) — the process-hygiene step
  from `docs/41` and the Monado-process-hygiene rule.
- Restores the desktop monitor layout (`reassert_monitors`) — but only under X11
  (`XDG_SESSION_TYPE=x11`), so `down` can also clean up from a non-X11 session.
- **Writes nothing to disk**: it does not truncate `$LOG`, and it does **not** touch the
  `FAIL_MARKER` — diagnostic state is preserved, and only a real jack-in that reaches
  "Jacked in" clears the marker.

> **Implemented 2026-08-19 (T228).** Until then everything this document said about
> `FAIL_MARKER` described a design, not code — a grep found the name only in prose, in no
> launcher. It now exists in `jack-in-wayland.sh` (and is synced to `scripts/`), with the
> details this document left unstated:
>
> * **Path**: `$VR/.jack-in-failed`. Contents: timestamp, action, mode, tracking, the reason,
>   and the path of the log to read.
> * **Written by** a `fail()` helper that *every* launch-path exit goes through — missing
>   Basalt, wrong session type, missing service binary, no usable compositor — so "the marker
>   exists" and "the last launch failed" cannot drift apart.
> * **Cleared by** exactly one thing: a launch that reached a usable compositor. Not an
>   attempt, not a teardown, not time passing. `--force` also clears it and launches.
> * **Why it is worth refusing at all**: this project has twice measured that relaunching a
>   sick headset makes it worse — T183 lost ~6 restart cycles to a storm that a single mains
>   power-cycle then cleared, and T074's USB2 branch died after a burst of service restarts and
>   needed every connector reseated. On the unattended tty4 path nothing else stops that loop.
>
> Verified against a real failure (headset powered off): the gate refuses with exit 1 and prints
> the record, `down` works with the marker set and leaves it intact, `--force` clears it.

Two ordering details make `down` robust, via two *different* mechanisms. The FAIL_MARKER
stop-gate sits **above** the teardown dispatch but excludes `down` explicitly — its
condition is `[ "$MODE" != down ]` — so a config-read failure that left a marker cannot
block a shutdown. And the teardown dispatch itself is placed **before** the X11 guard and
the already-running guard: load-bearing precisely *when* the service is running, since the
already-running guard would otherwise print "Already running" and exit without stopping
anything.

## The default and argument order

Defaults: `MODE=up`, `TRACK=6dof`, `FORCE=0`. So `./jack-in.sh` alone is behaviorally
identical to the pre-change default — 6DoF SLAM, `WARN`-level noise, and an ambient
`WMR_LOG=trace` still reaches Monado.

Arguments are parsed in **one order-independent pass** that replaces the three old raw-`$1`
consumers (the `--force` gate, the lone `shift`, and the `3dof` fork). Nothing downstream
reads a positional argument anymore, so the mode token, the tracking token, and `--force`
never contend for `$1` and may appear in any order:

```bash
./jack-in.sh 3dof --force
./jack-in.sh --force quiet 3dof
./jack-in.sh dev
```

Unknown arguments are now a **hard error** (`exit 2` + usage) — this is a small intentional
behavior change. Previously `./jack-in.sh 1` fell through silently to 6DoF; now only the
documented tokens are accepted, which is what makes "clear modes" real. `-h` / `--help`
prints usage and exits 0.

## How the tracking modes interact

Tracking (`3dof` / `6dof`) is **orthogonal** to the lifecycle mode and applies to every
launch mode (`up`, `dev`, `quiet`). It is not consumed by `down`. It sets the same
`MODE_ENV` as before:

| Tracking | Sets | Meaning |
|---|---|---|
| `6dof` (default) | `WMR_SLAM=1` | SLAM/Basalt 6DoF. Real position, currently jittery on this rig. |
| `3dof` | `WMR_SLAM=0 WMR_CAMERAS=0` | IMU-only, rotation only, cameras off entirely. ~2000× more stable at rest; strictly better for orientation-only apps (360 photo/video, skyboxes). |

So the axes combine freely: `./jack-in.sh dev 3dof` is a verbose IMU-only launch,
`./jack-in.sh quiet` is an unattended 6DoF station, and so on. The rationale for the
3DoF/6DoF trade-off (measured ~3° mean / 20–30° max SLAM jitter at rest vs. ~0.0013° for
IMU-only) is unchanged and lives in the script comment.

## Opting in a single diagnostic var

In `up` and `dev`, the log levels are `${VAR:-…}`, so exporting a variable in the ambient
environment overrides that mode's default for that one knob — and the firehoses (which no
launch mode sets) simply pass through. That is how a dev turns on exactly one instrument
without changing modes or editing the script:

```bash
WMR_LOG=trace ./jack-in.sh                 # one firehose, everything else quiet, still 'up'
VIT_COLLAPSE_LOG=1 ./jack-in.sh dev         # SLAM-collapse instrument (docs/39) on top of dev
CONSTELLATION_TRACKER_LOG=trace ./jack-in.sh 3dof
```

Watch the naming traps from `docs/41`: `CONSTELLATION_TRACKER_LOG` (the constellation
pipeline) is **not** `WMR_LOG` (an unrelated USB/IMU firehose), and per-frame lines from
several threads interleave — always match the full anchored line before extracting numbers.

In `quiet` this does **not** work by design: the levels are hard-pinned and the firehoses
are `env -u`-scrubbed, so `WMR_LOG=trace ./jack-in.sh quiet` still produces a `WARN` log and
no debug-GUI window. If you need to instrument, you are not running the unattended station —
use `up` or `dev`.

### The fix toggles are not logging

Two environment toggles in `COMMON_ENV` are **behavior, not logging**, and are therefore
**identical across all launch modes** (`up`, `dev`, `quiet`) — they carry the decided
defaults but stay A/B-overridable via ambient export:

| Toggle | Default | Meaning |
|---|---|---|
| `BASALT_IMU_NONBLOCK_CATCHUP` | `${…:-1}` (ON) | The `processImu` SLAM-collapse fix — non-blocking `try_pop` catch-up. Strict no-op on the healthy path. `docs/39`. Set `=0` to restore the old blocking pop for an A/B. |
| `WMR_CONSTELLATION_SEARCH_BUDGET_US` | `${…:-0}` (off) | Per-model correspondence-search wall-clock deadline in µs. `docs/40`. `0` = unbounded (old behavior, current default — the 3 ms cap cut real matches, see `docs/40` "Controllers-ON A/B"); e.g. `3000` caps each per-model search at 3 ms. |

## Per-mode env matrix

| Variable | `up` (default) | `dev` | `quiet` | `down` |
|---|---|---|---|---|
| `WMR_LOG` | `${WMR_LOG:-warn}` | `${WMR_LOG:-debug}` | `warn` (hard) | — |
| `XRT_LOG` | `${XRT_LOG:-warn}` | `${XRT_LOG:-debug}` | `warn` (hard) | — |
| `SLAM_LOG` | `${SLAM_LOG:-warn}` | `${SLAM_LOG:-debug}` | `warn` (hard) | — |
| `XRT_COMPOSITOR_LOG` | `${…:-warn}` | `${…:-debug}` | `warn` (hard) | — |
| `U_PACING_*_LOG`, `U_PACING_LIVE_STATS` | ambient passthrough | ambient passthrough | `warn` / `false` (hard) | — |
| `VIT_COLLAPSE_LOG`, `CONSTELLATION_TRACKER_LOG`, `HELLO_XR_POSE_STATS`, `SLAM_UI`, `XRT_TRACING` | ambient passthrough (opt-in) | ambient passthrough (opt-in) | **`env -u` scrubbed** | — |
| `XRT_DEBUG_GUI` (real run) | ambient passthrough | ambient passthrough | **`env -u` scrubbed** | — |
| `BASALT_IMU_NONBLOCK_CATCHUP` | `${…:-1}` ON | `${…:-1}` ON | `${…:-1}` ON | — |
| `WMR_CONSTELLATION_SEARCH_BUDGET_US` | `${…:-0}` off | `${…:-0}` off | `${…:-0}` off | — |
| `$LOG` writes | truncate + append (minimal at `warn`) | truncate + append (verbose) | truncate + append (minimal at `warn`) | **none** |
| socket `rm -f` | yes (launch hygiene) | yes | yes | yes (teardown) |
| `FAIL_MARKER` | gated; cleared on "Jacked in" | same | same | **untouched** (skips gate) |
| monitors | free DP-0 + reassert ×2 | same | same | reassert once (restore) |

Note the layering under GNU `env`: `SCRUB_ENV` (`-u`, quiet only, must come first) strips,
then `COMMON_ENV` (fix toggles + the functional `XRT_*`/`WMR_DISPLAY_INIT_SLEEP_SECONDS`),
then `LOG_ENV` (levels), then `MODE_ENV` (`WMR_SLAM`/`WMR_CAMERAS`) — later `NAME=VALUE`
wins, which is the intended precedence. The `wake_panel` probe is pinned low
(`WMR_LOG=warn XRT_LOG=warn XRT_COMPOSITOR_LOG=warn … XRT_DEBUG_GUI=0`) regardless of mode:
it is `kill -9`'d within seconds and its log is truncated before the real run, so it never
needs verbosity (if you must debug the probe itself in `dev`, export the level explicitly).

The tracking-camera health check ("Invalid frame magic", `docs/22`) is **kept in all
modes** — it is a failure signal that goes to stderr, not to disk, so it does not violate
`quiet`'s no-extra-output contract.

## Mirroring this on dev's `jack-in-wayland.sh`

This is a **note for dev**, not implemented in this pass (session-role split: the lab
install is where the Wayland autostart lives). `scripts/jack-in-wayland.sh` is the real
90Hz DRM-lease autostart and has a **different logging model** — master switches
`VR_VERBOSE` (line 354) and `VR_PACING` (line 407), a hardcoded `XRT_COMPOSITOR_LOG=debug`
(line 491), and per-run pose CSVs gated by `VR_POSE_CSVS` (line 376). Port the **same
subcommand contract** (the `up`/`dev`/`quiet`/`down` lifecycle, order-independent parse,
`usage`, `teardown`), then map the modes onto its existing switches rather than rebuilding a
`LOG_ENV`:

- **`dev`** → `VR_VERBOSE=1 VR_PACING=1`.
- **`up`** → `VR_VERBOSE=0 VR_PACING=0`, and change the hardcoded `XRT_COMPOSITOR_LOG=debug`
  at line 491 to `warn` (it is the one knob with no master switch).
- **`quiet`** → as `up`, **plus** `VR_POSE_CSVS=0` (the station writes no per-run CSV dirs)
  and the same `SCRUB_ENV` (`env -u` the six firehoses + the debug GUI).
- **`down`** → an equivalent `teardown`. Its socket path
  (`${XDG_RUNTIME_DIR}/monado_comp_ipc`) and its DRM-lease teardown differ from the X11
  direct-mode path (no DP-0 free / `reassert_monitors`; the compositor owns the lease), so
  adapt the body — but keep the SIGTERM-first / escalate-to-KILL / remove-socket /
  write-nothing shape.

**Naming caveat (important — the wayland twin already uses these names).** On
`jack-in-wayland.sh`, `MODE` is already the **display-mode index** (`0|1|2`, line 23, feeding
`XRT_COMPOSITOR_DESIRED_MODE` at line 490) and `TRACKING` is already a positional second arg
with values `3dof|6dof|ctrl` (line 31). Do **not** reuse `MODE` for the lifecycle subcommand
there — it would clobber the display index. Give the lifecycle its own variable (e.g.
`ACTION` / `LIFECYCLE`) and fold the new tokens into the existing parse without disturbing
the display-index and `ctrl` semantics. Also **preserve the explicit
`WMR_CONSTELLATION_CONTROLLERS` pass** (lines 281-285) — it is not part of the log policy and
must not be folded into it.

## See also

- `docs/38` — the turntable fixture that made these bugs reproducible unattended.
- `docs/39` — SLAM pose-rate collapse root cause + the `BASALT_IMU_NONBLOCK_CATCHUP` fix
  (a fix toggle carried by every launch mode).
- `docs/40` — constellation correspondence-search CPU blow-up + the
  `WMR_CONSTELLATION_SEARCH_BUDGET_US` deadline (default off — its "Controllers-ON A/B"
  section shows the 3 ms cap cut real matches; walk-through in `docs/42` Step 2.6).
- `docs/41` — the diagnostic toolkit: the firehose inventory `quiet` scrubs, the parsing
  trap, and the process-hygiene socket removal `down` performs.
- `docs/42` — the playbook whose closing "Toward unattended diagnostics" agenda ("firehoses
  OFF by default; clear modes; the station writes nothing extra when idle") this implements.
- `docs/22` — the cable/connector fault behind the "Invalid frame magic" health check that
  stays on in every mode.
