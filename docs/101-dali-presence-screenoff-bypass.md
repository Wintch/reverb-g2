# 101 -- Dali dark-panel incident: presence.conf's "disabled" was bypassed, not a hardware fault

**Status: root cause confirmed from the logs; fix applied to `jack-in-wayland.sh` and validated
live.** Background on the presence feature itself: `docs/103-presence-restore-instrumentation.md`.

## The incident

During a Dreams of Dali (appid 591360) 6dof session launched with `VR_LAUNCH_APPID=591360
WMR_USER_PRESENCE=1`, the headset panel went dark mid-session while `monado-service` kept running
and delivering frames on schedule (no crash, steady ~11 ms pacer log).
`/sys/class/drm/card0-DP-{1,2,3}/status` all read `disconnected`, `scripts/hmd-connector.sh` came
back empty, and `scripts/panel.py activate` reported full HID-level success without DP coming
back. USB stayed a healthy 5/5 throughout. `presence.conf` had `PRESENCE_ENABLE=0`, which was
believed to fully disable the presence/auto-standby feature. It did not.

## Classification against `docs/22`

Not a genuine hardware DP-dead fault (`docs/22` step 4):

- `panel.py activate` succeeded and showed "full activation + screen on" (step 4 needs no logo at
  all after a clean activation).
- USB stayed 5/5: no `error -71`, no `reqCmd 23`, no HID read failures, no device-number churn.
- `monado-service` never failed to construct the HMD; a real DP-dead fault fails at compositor/
  Vulkan init, not mid-session after frames were flowing.

It is the stale-DRM-lease signature (`docs/22` step 4 point 4, and §8 of `docs/103`): HID
activation succeeds while Monado's lease on the connector is dead. Recovery: kill `monado-service`,
`rm -f /run/user/1000/monado_comp_ipc`, relaunch. No cable check is warranted.

## Root cause

### 1. The trigger: presence-driven auto-standby fired

`jack-in-wayland.prev.log` (the pre-relaunch log):

```
  8: INFO [wmr_hmd_create] User presence enabled (WMR_USER_PRESENCE=1): surfacing the companion
     proximity sensor as XR_EXT_user_presence. Threshold is provisional, see wmr_hmd_update_inputs().
...
58101: INFO [wmr_hmd_update_inputs] User presence: panel blanked by auto-standby (120000 ms NOT WORN)
```

No `WORN`/`NOT WORN` transition appears before line 58101, so the sensor read "not worn" from
the start (the struct's zero default) and 120 s later auto-standby blanked the panel as designed.
No `panel restored` line ever follows (the RESTORE bug of `docs/103` §2).

### 2. The HID power-down dropped DP and the lease died

About 2000 lines later, right after three `vk_swapchain_present: VK_ERROR_UNKNOWN` errors:

```
DEBUG [_lease_finished] Lease has been closed
```

That is mutter's `wp_drm_lease_v1.finished`: commanding the panel/bridge off over HID
(`screen_enable_func(wh, false)`) drops HPD without touching USB. `dmesg`/`journalctl -k` show
nothing because NVIDIA's proprietary DRM driver does not log connector-status transitions, and
mutter does not log revoking a lease at default verbosity.

`comp_window_direct_wayland.c`'s `_lease_finished` only sets `lease->finished = true` and closes
the fd (literal comment: `/* TODO handle graceful shutdown if lease is currently used */`);
nothing re-requests a lease and nothing tears the render loop down. The fake-vblank pacing thread
(`COMP_TARGET_FORCE_FAKE_DISPLAY_TIMING`) keeps ticking, which is why "Delivered frame" lines
continue at ~11 ms with a dark panel. This is the only DRM-lease code in Monado; the lease is
acquired once in `comp_window_direct_wayland_init` and never revisited.

### 3. Why `PRESENCE_ENABLE=0` did not stop it: a script bug

Old `jack-in-wayland.sh` logic:

```bash
PRESENCE_ENABLE_VAL="${WMR_USER_PRESENCE:-${PRESENCE_ENABLE:-0}}"
PRESENCE_SCREENOFF_VAL="${WMR_USER_PRESENCE_SCREENOFF_MS:-${PRESENCE_SCREENOFF_MS:-0}}"
```

`PRESENCE_SCREENOFF_VAL` was computed independently of `PRESENCE_ENABLE_VAL`. With
`WMR_USER_PRESENCE=1` exported in the ambient environment (a reasonable request for telemetry),
the ambient export won for `PRESENCE_ENABLE_VAL` by design, but the conf file's
`PRESENCE_SCREENOFF_MS=120000` was applied regardless of `PRESENCE_ENABLE`. `PRESENCE_ENABLE=0`
had never actually gated the screen-off; it only looked like an off switch because nobody had
exported `WMR_USER_PRESENCE=1` while it was `0`.

## Fix

Around the `PRESENCE_SCREENOFF_VAL` computation in `scripts/jack-in-wayland.sh`:

```bash
PRESENCE_ENABLE_VAL="${WMR_USER_PRESENCE:-${PRESENCE_ENABLE:-0}}"
if [ -n "${WMR_USER_PRESENCE_SCREENOFF_MS+set}" ]; then
    PRESENCE_SCREENOFF_VAL="$WMR_USER_PRESENCE_SCREENOFF_MS"
elif [ "${PRESENCE_ENABLE:-0}" = "1" ]; then
    PRESENCE_SCREENOFF_VAL="${PRESENCE_SCREENOFF_MS:-0}"
else
    PRESENCE_SCREENOFF_VAL=0
fi
```

| Scenario | ambient `WMR_USER_PRESENCE` | ambient `..._SCREENOFF_MS` | conf `PRESENCE_ENABLE` | conf `PRESENCE_SCREENOFF_MS` | Result |
|---|---|---|---|---|---|
| The bug | `1` | unset | `0` | `120000` | `0`, auto-standby suppressed |
| Opted in via the conf file | unset | unset | `1` | `120000` | `120000` |
| Explicit ambient override | (any) | `5000` | `0` | `120000` | `5000`, ambient wins |

`WMR_USER_PRESENCE` itself (surfacing `XR_EXT_user_presence`) is untouched: telemetry can be
requested without re-arming the screen-off side effect. A change to the script or conf only takes
effect on the next `jack-in down` + `up`.

## Validation

Relaunched Dali with `WMR_USER_PRESENCE=1` and `PRESENCE_ENABLE=0`, left the headset untouched
for 2:30 (past the 120000 ms conf threshold): `card0-DP-2` stayed `connected` and no `panel
blanked by auto-standby` line appeared. Before the fix that combination reliably blanked the
panel and lost the lease.

To check a running service: `tr '\0' '\n' < /proc/<pid>/environ | grep SCREENOFF` should show `0`.

## Not fixed here

- The RESTORE problem and the underlying fact that a real screen-off kills the lease are covered
  in `docs/103`. This doc only closes the configuration bypass.
- A second, unrelated trigger for the same lease-loss symptom (fired ~20 s after launch, far too
  early for the 120 s timer) is in `docs/102-dali-relaunch-race-second-lease-trigger.md`.
