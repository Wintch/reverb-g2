# 68 — Power management: saver/performance watchdog, shared telemetry, scoped sudoers

**Status: built and verified live. `vr-power-watchdog.service` enabled.**

Scope note: the filename mentions lazy boot, which was scoped out of this doc and is not covered here.

## Why this exists

Between sessions nothing pinned the CPU/GPU to a deliberate minimum, and nothing pinned them to
performance for a session either without someone running `vr-power-setup.sh --apply` by hand.
The principle: **start light, go full only when something real is actually running.** (Panel
on/off cycling is also a real wear mechanism, see [docs/22](22-cable-connector-diagnosis.md), so
the headset panel should not wake before a launch is actually requested; `jack-in-wayland.sh`
already does its own `panel.py activate` + DP-connector poll right before Monado comes up.)

## 1. `vr-power-watchdog.py` — automatic saver/performance

`scripts/vr-power-setup.sh` pins the machine to full performance (`--apply`). It also has a
symmetric `--saver` mode: governor `powersave`, EPP `power` (the lowest of `default performance
balance_performance balance_power power` on an `amd-pstate-epp` driver), boost off, ASPM
`powersave`, GPU power limit floored to its `power.min_limit`. It deliberately does **not** touch
GPU persistence mode in either direction, because toggling it risks a modeset on the desktop
monitor, which lives on the same GPU as the headset. The one thing forced identically in both
modes: the HMD's USB devices never autosuspend (hardware-quirk fix from `docs/22`, unrelated to
the power policy).

`scripts/vr-power-watchdog.py` (root, `vr-power-watchdog.service`, `WantedBy=
multi-user.target`) polls every 10 s:

- **active** = a `monado-service` process is alive, OR `game-stop.py`'s `scan()` finds a live
  Proton game tree.
- active -> `--apply` immediately (more watts is never disruptive).
- not active -> `--saver`, but only after 3 consecutive idle ticks (~30 s), so a brief gap
  between one game closing and the next opening does not flap the CPU/GPU state.
- Forces `saver` once on its own startup, which is what makes every boot start light with no
  separate boot-time unit.
- Writes the current mode to `/run/vr-power-mode` (world-readable) so unprivileged readers can
  report it without root.

Verified live with a real launch/close: `saver` -> `performance` within ~10 s of Monado starting
(before the game process even registered), back to `saver` ~20-30 s after the game stopped and
the compositor was brought down.

## 2. Shared telemetry: `rig_telemetry.py`

The status dashboard and other agents need the same facts (CPU/GPU/RAM specs, GPU
utilization/watts/temp, RAM%, Sunshine active), so they live in `scripts/rig_telemetry.py`:
`machine_specs()`, `gpu_telemetry()`, `ram_percent()`, `sunshine_active()`, `power_mode()` (reads
`/run/vr-power-mode`), and `tracking_mode()`.

`tracking_mode()` reads `monado-service`'s own `/proc/<pid>/environ` for `WMR_SLAM`/
`WMR_CAMERAS` — the same env vars `jack-in-wayland.sh` sets per mode (`6dof` -> `WMR_SLAM=1`,
`ctrl` -> `WMR_SLAM=0 WMR_CAMERAS=1`, `3dof` -> neither) — rather than guessing from anything
else.

**Trap: `sunshine_active()` must use `systemctl --user`.** Sunshine is a systemd **--user** unit
(`app-dev.lizardbyte.app.Sunshine.service`, aliased to `sunshine.service`,
`WantedBy=graphical-session.target`). `systemctl is-active sunshine` without `--user` queries
the system instance and always silently returns `inactive` regardless of the real state.

## 3. `/etc/sudoers.d/reverb-g2-power` — measurement scripts without a password prompt

A NOPASSWD grant for the lab user, scoped to exactly two things:

- `vr-power-setup.sh` (any args) — the single audited script for CPU governor/EPP/boost/ASPM/GPU
  power/HMD USB autosuspend. Its own internal logic is the safety boundary, not sudoers.
- `systemctl start`/`stop` of `vr-power-watchdog.service` by exact unit name only (so a
  benchmark can hold the machine in one power state; see `scripts/gpu-pacing-baseline.sh`).

It deliberately does **not** grant `nvidia-smi` directly: measurement scripts compute a
percentage and call `vr-power-setup.sh --gpu-limit <pct>` instead of a raw `nvidia-smi -pl
<watts>`, so the sudoers surface stays one reviewed script wide, not a second generic binary. A
separate file per feature area, not one growing list. Verified: `sudo -n vr-power-setup.sh
--gpu-limit 100` and both `systemctl` verbs run with no prompt; `sudo -n nvidia-smi -pm 1`
(not granted) still asks for a password, confirming the scope holds.

## Files

```
scripts/vr-power-setup.sh          --apply / --saver / --gpu-limit
scripts/vr-power-watchdog.py       the poll loop
scripts/vr-power-watchdog.service  root, enabled
scripts/rig_telemetry.py           shared CPU/GPU/RAM/Sunshine/power/tracking telemetry
scripts/status-dashboard.py        uses rig_telemetry
```

System-level (not in git): `systemctl enable --now vr-power-watchdog.service` and
`/etc/sudoers.d/reverb-g2-power` installed.
