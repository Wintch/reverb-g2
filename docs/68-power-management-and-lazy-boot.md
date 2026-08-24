# 68 — Power management and lazy boot (T246)

**Status: built and verified live, 2026-08-23. `vr-power-watchdog.service` enabled;
`vr-boot-selector.service` disabled.**

## Why this exists

Two separate things used to run unconditionally, whether or not anyone was actually
about to use VR:

1. **CPU/GPU stayed at whatever `power-profiles-daemon` felt like** between sessions —
   nothing ever pinned them to a deliberate minimum, and nothing pinned them to
   performance for a session either without a human remembering to run
   `vr-power-setup.sh --apply` by hand first.
2. **The headset panel woke up on every single boot.** `vr-boot-selector.service`
   (tty1, `multi-user.target`) ran `power-on.py --pre-login` unattended, whose step
   4/5 sends `panel.py activate` — before anyone had logged in, before anyone had
   decided to use VR that session at all. [docs/22](22-cable-connector-diagnosis.md)
   already documents panel on/off cycling as a real **wear** mechanism, not just a
   watts cost.

Both are the same shape of bug: paying a cost (watts, wear) for hardware nobody asked
to use yet. The fix in both cases: **start light, go full only when something real is
actually running.** This also brings the rig closer to how `pmadminka`'s existing
Windows agent already behaves — it doesn't do a pre-login hardware diagnostic either,
it just boots to desktop and reacts to what gets launched.

## 1. `vr-power-watchdog.py` — automatic saver/performance

`scripts/vr-power-setup.sh` already knew how to pin the machine to full performance
(`--apply`, written 2026-08-12/T163) — it just needed a human to run it, and nothing
ever undid it afterward. It gained a symmetric `--saver` mode (governor `powersave`,
EPP `power` — the lowest of `default performance balance_performance balance_power
power` on this box's `amd-pstate-epp` driver —, boost off, ASPM `powersave`, GPU power
limit floored to its `power.min_limit`, currently 100W of 250W max). Deliberately does
**not** touch GPU persistence mode in either direction — toggling it risks a modeset
on the desktop monitor, which lives on the same GPU as the headset. The one thing
forced identically in both modes: the HMD's USB devices never autosuspend (a
hardware-quirk fix from `docs/22`, unrelated to the power policy).

`scripts/vr-power-watchdog.py` (root, `vr-power-watchdog.service`, `WantedBy=
multi-user.target`) polls every 10s:

- **active** = a `monado-service` process is alive, OR `game-stop.py`'s `scan()`
  finds a live Proton game tree.
- active → `--apply` immediately (more watts is never disruptive).
- not active → `--saver`, but only after 3 consecutive idle ticks (~30s), so a brief
  gap between one game closing and the next opening doesn't flap the CPU/GPU state.
- Forces `saver` once on its own startup — this alone is what makes every boot start
  light, no separate boot-time unit needed.
- Writes the current mode to `/run/vr-power-mode` (world-readable) so unprivileged
  readers can report it without root.

Verified live end to end with a real Aircar launch/close: `saver`→`performance` within
~10s of Monado starting (before the game process even registered), back to `saver`
~20-30s after `game-stop.py stop` + `jack-in-wayland.sh down`.

`vr-cockpit.py`'s power preflight check was updated to match: `powersave` while idle
is now the expected state, not a warning. It only escalates when the watchdog itself
expects `performance` (its own mode file says so, or a session is actually live) and
the governor disagrees — that's a real fault.

## 2. Boot-time headset diagnostic deprecated

Traced end to end before touching anything (worth recording, since it took a few
wrong turns): `vr-boot-selector.service` → `power-on.py --pre-login` (panel activate,
step 4/5) → on a real "LISTO", writes `/run/vr-ready` and rewrites
`/etc/sddm.conf.d/98-vr-autologin.conf` for SDDM autologin → `graphical.target` →
GNOME Wayland session → a GNOME autostart entry was *supposed* to read `/run/vr-ready`
and auto-open the VR picker. **That last stage was already dead**: its target script,
`scripts/vr-launcher-autostart.sh`, was never actually committed to this repo (no git
history at all) — so the panel had been waking at every boot for a payoff that never
fired.

Separately, `power-on.py` called *without* `--pre-login` already does the "diagnose,
then launch" thing on demand: same 5-step diagnostic (USB census → camera speed →
panel activate + DP fingerprint → controllers), and on success it `execv`s straight
into `vr-launcher.py MODE TRACKING`. Its failure paths (`give_up()`/`continue_2d()`)
only touch `systemctl isolate` when `PRE_LOGIN` is set, and `wait_for_reseat()`
already degrades safely with no tty on stdin (60s poll, then gives up) — so it was
already safe to call from a non-interactive context in principle.

**What actually changed:**
- `systemctl set-default graphical.target` (was `multi-user.target`).
- `vr-boot-selector.service` disabled (files kept in the repo — the tty1/getty
  handling and its documented incidents, T129/T130/T172/T182, are worth keeping as
  reference even though the service is inert now).
- The dead `~/.config/autostart/vr-launcher-autostart.desktop` removed.
- `power-on.py`'s own `--pre-login` code path is left in place, unused, in case an
  unattended pre-login console is wanted again later — not deleted.
- SDDM autologin (`iam` → `gnome-wayland.desktop`) left exactly as it was, now a
  static config instead of something rewritten every boot. Deliberate, but flagged:
  this is what lets `pmadminka` rentals and remote sessions work with nobody typing a
  password at the physical console. Revisit if that turns out to be the wrong
  tradeoff.

**Confirmed live after a real reboot**: no tty1 console, straight to a logged-in
GNOME desktop, `DP-1`/`DP-2` both `disconnected` (panel never woke),
`vr-power-watchdog` already in `saver`.

### A dead end worth recording: don't route the dashboard's bare-compositor button through `power-on.py`

Tried wiring `status-dashboard.py`'s "Start compositor" button through
`power-on.py`/`vr-launcher.py` too, on the theory that its extra checks (USB census,
camera speed, controllers) should run before every manual launch, not just fix the
boot case. **Reverted the same day, live:**

- The button's subprocess runs with `stdin=DEVNULL`. `vr-launcher.py`'s game picker
  does `select.select([sys.stdin], ...)` with a 15s timeout meant to fall back to a
  default — but `/dev/null` is always "ready", so the read returns EOF instantly
  instead of waiting, landing on "Opcion invalida" with nothing launched. This is the
  exact trap the script's own `VR_LAUNCH_APPID` code comment already documents; the
  button just wasn't setting it.
- Even fixing that would still be wrong: the button exists to leave a **bare**
  compositor up for the separate "Launch Aircar/Cyberpilot/…" buttons to use
  afterward. `power-on.py` always ends by launching one specific title — a genuine
  semantic mismatch, not just a stdin bug.
- `jack-in-wayland.sh` already does its own `panel.py activate` + DP-connector poll
  (T050, 2026-08-07) right before Monado comes up, lazily, at real launch time — it
  never needed `power-on.py` in front of it. Boot was the only place waking the panel
  early, and disabling `vr-boot-selector.service` alone already fixes that.

Button reverted to calling `jack-in-wayland.sh dev 1 6dof` directly, exactly as
before. `power-on.py` (no `--pre-login`) remains available as a manual, on-demand
diagnostic for a human at a terminal.

## 3. Shared telemetry: `rig_telemetry.py`

`status-dashboard.py` (`:8765`) and `pmadminka-agent.py`'s heartbeat used to compute
the same facts (CPU/GPU/RAM specs, GPU utilization/watts/temp, RAM%, Sunshine active)
with two separate copies of near-identical code — the same sharing gap
`wmr_usb_ids.py`/`gui_env.py` already closed for USB census and GUI env vars. Moved
into `scripts/rig_telemetry.py`: `machine_specs()`, `gpu_telemetry()`, `ram_percent()`,
`sunshine_active()`, `power_mode()` (reads `/run/vr-power-mode`), and a new
`tracking_mode()`.

`tracking_mode()` reads `monado-service`'s own `/proc/<pid>/environ` for `WMR_SLAM`/
`WMR_CAMERAS` — the same env vars `jack-in-wayland.sh` sets per mode (`6dof` →
`WMR_SLAM=1`, `ctrl` → `WMR_SLAM=0 WMR_CAMERAS=1`, `3dof` → neither) — rather than
guessing from anything else. `pmadminka-agent.py`'s heartbeat now sends `tracking`
alongside `power_mode`, both under the same KNOWN GAP as `vr_device`: sent regardless,
dropped hub-side until `deploy/server.py`'s heartbeat whitelist grows those keys.
`status-dashboard.py` mirrors everything the heartbeat sends (CPU/GPU/RAM/Sunshine/
`vr_device`/`power_mode`) plus `tracking`, in the Session and system cards.

**Bug found and fixed while wiring this up**: `sunshine_active()` ran `systemctl
is-active sunshine` with no `--user` flag. Sunshine is a systemd **--user** unit
(`app-dev.lizardbyte.app.Sunshine.service`, aliased to `sunshine.service`,
`WantedBy=graphical-session.target` — it does autostart at login). Querying the
system instance instead of the user one always silently returned `inactive`
regardless of the real state — caught live because the dashboard showed
`sunshine: false` while `systemctl --user status sunshine` showed it running for 8+
minutes. Fixed by adding `--user`; this also silently fixes the same bug in
`pmadminka-agent.py`'s heartbeat, which shared the same code before the move to
`rig_telemetry.py`.

## 4. `/etc/sudoers.d/reverb-g2-power` — measurement scripts without a password prompt

Added while building `scripts/q2rtx-power-sweep.sh` (docs/48): a NOPASSWD grant for
user `iam`, scoped to exactly two things --

- `vr-power-setup.sh` (any args) — the single audited script for CPU governor/EPP/
  boost/ASPM/GPU power/HMD USB autosuspend. Its own internal logic is the safety
  boundary, not sudoers.
- `systemctl start`/`stop` of `vr-power-watchdog.service` by exact unit name only.

Deliberately does **not** grant `nvidia-smi` directly — `q2rtx-power-sweep.sh` computes
a percentage and calls `vr-power-setup.sh --gpu-limit <pct>` instead of a raw
`nvidia-smi -pl <watts>`, so the sudoers surface stays one reviewed script wide, not a
second generic binary. Same convention as the pre-existing `/etc/sudoers.d/
reverb-g2-agent` file (a separate file per feature area, not one growing list).
Verified live: `sudo -n vr-power-setup.sh --gpu-limit 100` and both `systemctl`
verbs run with no prompt; `sudo -n nvidia-smi -pm 1` (something NOT granted) still
asks for a password, confirming the scope actually holds.

## Files

```
scripts/vr-power-setup.sh        gained --saver (mirrors --apply)
scripts/vr-power-watchdog.py     new -- the poll loop
scripts/vr-power-watchdog.service  new -- root, enabled
scripts/rig_telemetry.py         new -- shared CPU/GPU/RAM/Sunshine/power/tracking telemetry
scripts/pmadminka-agent.py       uses rig_telemetry; heartbeat gained power_mode, tracking
scripts/status-dashboard.py      uses rig_telemetry; mirrors the heartbeat fields + tracking
scripts/vr-cockpit.py            power check no longer warns on idle powersave
scripts/power-on.py              header updated: --pre-login deprecated, unused, not deleted
scripts/q2rtx-power-sweep.sh     new -- GPU power/fps sweep (docs/48), uses the sudoers grant above
```

System-level (not in git, recorded here since `docs/22`-style hardware/config state
belongs on paper somewhere): `systemctl set-default graphical.target`, `systemctl
disable vr-boot-selector.service`, `systemctl enable --now vr-power-watchdog.service`,
`~/.config/autostart/vr-launcher-autostart.desktop` removed, `/etc/sudoers.d/
reverb-g2-power` installed.
