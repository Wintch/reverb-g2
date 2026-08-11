# 28 — Log map: where every log lives, and what question it answers

Companion to [`27-verbose-logging-survey.md`](27-verbose-logging-survey.md). That one is
about *what to turn on*. This one is about *where it lands and what it is good for*, so a
symptom can be turned into an open file instead of a guess.

The rule this document exists to serve, stated by the user on 2026-08-11:

> Logging is not the problem. **Not having data is the problem.**

The cost of this project's slowest debugging sessions has never been too much log. It has
always been arriving at a question with no data for the run that already happened, and
then having to reproduce it on hardware whose cable connector does not enjoy being handled
(see [`22-cable-connector-diagnosis.md`](22-cable-connector-diagnosis.md)). When in doubt,
write the file.

---

## The ladder: symptom → first file to open

| Symptom | Open this first |
|---|---|
| Session never started, "Found no connectors available for direct mode" | `~/vr/logs/jack-in-launcher.log`, then `~/vr/jack-in-wayland.log` |
| Panel dark / HP logo but no image | `journalctl -k` for `usb 3-2`, then run `./preflight.sh` |
| "The cable is dying again" | **`./preflight.sh` before anything.** Then `journalctl -k \| grep -i "error -71"` |
| Head tracking feels wrong, drifting, frozen | `~/vr/logs/slam-<stamp>/tracking.csv` — measure it, don't eyeball it |
| Controllers not there, or one missing | `grep -E "left:\|right:" ~/vr/jack-in-wayland.log` |
| Controller pose looks wrong / does not move | the player's `POSE` lines — check `trk:` not just the numbers |
| Game launches and dies immediately | `~/vr/logs/steam-<appid>.log` (Proton), then the engine log below |
| Runtime not found by a game | `XR_LOADER_DEBUG=all` output on the game's own stderr |
| Something segfaulted | `coredumpctl list`, then `coredumpctl info <pid>` |
| Unattended boot did not reach VR | `journalctl -b 0 -u vr-boot-selector -u vr-launcher-console`, then `power-on-stats.jsonl` |

---

## Our own stack

### `~/vr/jack-in-wayland.log` — the Monado service, everything it says
Written by `jack-in-wayland.sh` (whole stdout+stderr of `monado-service`). **One generation
is kept**: the previous run is moved to `~/vr/jack-in-wayland.prev.log` before each start,
because a later start once destroyed the only evidence of a mid-session tracking freeze
(T045).

Answers: which builder was selected, whether both controllers registered, which display
mode was taken, whether the DRM lease was granted, what the constellation tracker did.

**Two greps worth memorising**, both from real incidents:

```bash
grep -E "Using builder"        ~/vr/jack-in-wayland.log   # 'wmr', NOT 'legacy'/Simulated HMD (T050)
grep -E "left:|right:"         ~/vr/jack-in-wayland.log   # a controller can silently lose the startup race (T051)
```

Verbosity comes from the `LOG_ENV` block in `jack-in-wayland.sh`: `XRT_LOG`, `WMR_LOG`,
`SLAM_LOG`, `CONSTELLATION_TRACKER_LOG`, all at `debug`. `XRT_LOG` matters more than it
looks — its default is `WARN`, which is why the runtime used to look so quiet. `VR_VERBOSE=0`
turns the whole block off if log volume is ever *measured* to perturb the realtime USB
callback.

### `~/vr/logs/jack-in-launcher.log` — what the launcher script itself said
Added 2026-08-11 (T145). `vr-launcher.py` runs `jack-in-wayland.sh` with
`capture_output=True` and used to only echo it to tty4, where `agetty` overwrote it. That
lost the exact lines that separate *"the panel never came up"* from *"the connector was up
but the compositor had not offered it for lease yet"* — the two look identical from
downstream.

Answers: the pre-flight verdicts — `HMD connector (non-desktop=1) up.`, `Compositor offers
the connector for lease.`, and any `!!` warning.

### `~/vr/logs/slam-<timestamp>/*.csv` — the objective tracking instrument
Written when `SLAM_WRITE_CSVS=1` (on by default now), one directory per run so runs cannot
overwrite each other — upstream's default is a bare `evaluation/` relative to the working
directory, which scatters files wherever the launcher happened to be.

- `tracking.csv` — timestamped pose (position + quaternion). **This is the file that turns
  "it seems to track well" into a number.** Reference measurements taken 2026-08-11:
  2–4 cm of span with the headset resting on a table, versus 4.04 m of coherent path over
  59 s of real movement.
- `timing.csv`, `prediction.csv`, `filtering.csv` — pacing and filter internals.

Worth computing from `tracking.csv`, not just looking at it: total path length, max
displacement, **max step between consecutive samples** (a real divergence shows up as a
discontinuity; fast human motion shows up as consecutive large steps at a normal interval —
these are not the same thing and the difference is the whole diagnosis).

### The player's `POSE` lines
One line per second, **on by default** (`HELLO_XR_POSE_LOG=0` to opt out), head plus both
controllers in app space:

```
POSE head (+0.013 -0.003 -0.010) | left (-0.108 -0.255 -0.586) pos:OK trk:-- | right (...)
```

The flags are not decoration. An untracked controller still reports a completely plausible
position, because Monado pins untracked devices at a fixed offset from the tracking origin
(`u_builder_helpers.c`: `(±0.2, 1.3, -0.5)`), so **a bare XYZ triplet cannot be told apart
from a real one**. `pos:` (VALID) and `trk:` (TRACKED) are what distinguish them. When the
constellation series reaches 0017, `trk:` flips to `OK` and the numbers start moving —
a binary criterion needing no interpretation.

**Known gap:** these lines go to the player's stdout. Run by hand they are on the terminal;
run from the tty4 launcher they go to a VT nobody is reading. Persisting them the way
`jack-in-launcher.log` now persists the launcher's output is an open task.

### `/tmp/vr-launcher-console-debug.log` — the tty4 launcher's stderr
Permanent redirect on `vr-launcher-console.sh`. Exists because `StandardOutput=tty` in the
`.service` hides everything from `journalctl`, which slowed down several fixes on
2026-08-10 before this was added. Note it captures the *launcher's* stderr — output that
`vr-launcher.py` captures internally never reaches it, which is exactly the hole
`jack-in-launcher.log` was added to close.

### `power-on-stats.jsonl` — one line per boot, in the repo
Verdict, step reached, mode, tracking, whether it was pre-login, whether controllers and a
gamepad were present. The cheapest way to answer "how often does this actually work".

### systemd / kernel

```bash
journalctl -b 0 -u vr-boot-selector -u vr-launcher-console -u sddm   # the unattended chain
journalctl -k | grep -iE "usb 3-2|error -71|Cannot enable"           # the USB2 branch, see docs/00 and docs/22
coredumpctl list monado-service                                      # crashes, incl. the known Basalt teardown SIGSEGV
```

---

## The game side — this is where the gaps are

Everything above is ours and is written unconditionally. Everything below has to be asked
for, and most of it is per-title.

| Source | Where it lands | How to enable | Notes |
|---|---|---|---|
| Proton / Wine | `~/vr/logs/steam-<appid>.log` | `PROTON_LOG=1`, `PROTON_LOG_DIR` | Already exported by `vr-launcher.py` before `steam` starts |
| DXVK (D3D9-11) | alongside the Proton log | `DXVK_LOG_LEVEL=info` | Already on |
| VKD3D (D3D12) | alongside the Proton log | `VKD3D_DEBUG=warn` | Already on |
| OpenXR loader | the app's own stderr | `XR_LOADER_DEBUG=all` | Already on. Read by `libopenxr_loader.so` for *any* client, the 360 player included |
| Unity titles | `~/.config/unity3d/<Company>/<Product>/Player.log` | nothing — always written | Free data nobody has to enable. Go read it |
| Unreal titles | `<game>/Saved/Logs/*.log` | `-log -LogCmds="LogInit Verbose, LogHMD Verbose"` | **Must reach the game binary**, so it goes in Steam's per-game Launch Options by hand |
| xrizer | its own stderr, mixed into the Proton log | — | No dedicated log file. A gap |
| Steam client | `~/.steam/debian-installation/logs/` | — | Rarely useful, occasionally decisive for launch-path questions |

**The mechanical rule that keeps biting** (also in `docs/27`): anything that must reach the
Proton/game process has to be exported **before the `steam` client starts**, not set per
game. Editing `localconfig.vdf` on disk while Steam is running is unreliable and has
already been established as dangerous (`docs/23`).

---

## Still not captured — the honest gap list

1. **The player's `POSE` output is not persisted** when launched from the tty4 chain.
2. **xrizer has no log file of its own** — its output only survives if something captures
   the Proton stderr.
3. **Per-title engine logging is manual.** Unreal needs launch options edited by hand for
   every title; nothing enumerates which installed titles are Unreal.
4. **No single collector.** There is no `collect-logs.sh` that snapshots all of the above
   into one timestamped directory after a failed run. Everything here is currently a path
   somebody has to remember, which is precisely what this document is compensating for.
5. **`XRT_WINDOW_PEEK` does not work in this configuration** (tested 2026-08-11): the SDL2
   peek window is created, then `comp_window_peek_blit` fails with
   `VK_ERROR_INITIALIZATION_FAILED` and takes the service down with it. Consistent with the
   compositor being in direct mode with the connector leased. The debug GUI
   (`XRT_DEBUG_GUI=1`) is the mirror that does work. Do not re-try peek without a new idea.

---

## Traps this project has already paid for

- **`StandardOutput=tty` hides everything from `journalctl`.** A tty is not a log.
- **`capture_output=True` swallows a stream before any redirect can see it.** An empty
  debug file is not evidence that nothing was written.
- **A log that is truncated on every start destroys the evidence for the run you care
  about.** Keep one generation (`.prev.log`).
- **`grep "found display mode"` does not prove the real headset was used** — Monado's
  `legacy` builder's Simulated HMD leases the same connector and logs the same line. Check
  `Using builder wmr`.
- **`det(Q1Jl) == 0` from Basalt is not the divergence signature.** It appeared 859 and 630
  times in two runs on 2026-08-11 with zero divergence in either. Check the trajectory for a
  real discontinuity before calling SLAM broken.
