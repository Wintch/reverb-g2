# 102 -- The second DP/lease-drop trigger: a zero-settle-time relaunch race

**Status: the race exists at the code level and the mechanism behind it (the driver still holds a
killed process's VRAM for a moment) is directly measured. The failure symptom itself (DP disconnect
plus `vkWaitForFences: VK_TIMEOUT`) was NOT reproduced in four idle-rig attempts, and no code fix
shipped.** This is a different bug from the presence-screenoff bypass
(`docs/101-dali-presence-screenoff-bypass.md`): it fired ~20-30 s after launch, far too soon for any
120 s timer, and `WMR_USER_PRESENCE` was not even set.

## The incident

`vr-launcher.py 1 6dof` with `VR_LAUNCH_APPID=591360`. The launcher's stale-process guard
(`check_no_game_running()`) found an earlier Dali Wine tree still alive 2077 s after its wrapper
died, killed it, and immediately brought Monado up fresh. The DRM lease sequence looked normal
(lease granted, mode taken, "Idle-blank suppressed"). ~20-30 s later all three `card0-DP-*`
connectors read `disconnected`, `monado-service` was alive and still logging `Delivered frame`,
and a warning never seen in any other incident appeared: `WARN [vblank_event_func]
vkWaitForFences: VK_TIMEOUT`. The hardware discriminator of `docs/22` step 0 was negative
(`panel.py activate` succeeded, USB stayed 5/5), so not a cable fault.

Differences from the other lease-loss incidents: `jack-in-wayland.sh down` needed the SIGKILL
escalation ("still running after 10s"), and even after full teardown DP stayed `disconnected` until
a separate `panel.py activate` forced a fresh HID-level reactivation. Other incidents recovered
from a plain compositor kill.

What was checked: no kernel GPU reset or USB error in `journalctl -b 0` for the window (a known
blind spot, NVIDIA does not log context teardown), no coredumps (clean SIGTERM exit). The exact
`vkWaitForFences` log line could not be re-verified later because `jack-in-wayland.sh` keeps only
one `.prev.log`, and two more `up` cycles overwrote the incident's log. Widening the rotation to a
few logs would avoid losing evidence in a same-day multi-relaunch investigation.

## The structural race (confirmed in code)

`scripts/vr-launcher.py`, `main()`:

```python
    # No second client by accident: a previous title's Wine tree must be gone first.
    if not check_no_game_running():
        sys.exit(1)

    if not bring_up_monado():              # the very next executable statement
        ...
```

There is no delay, settle time or condition poll between `check_no_game_running()` declaring the
stale tree gone and `bring_up_monado()` starting the fresh `jack-in-wayland.sh up`.

`check_no_game_running()` calls `game-stop.py stop all`, which SIGTERMs the Windows main exe(s),
then polls `scan()` every 0.5 s for up to 8 s and declares the appid stopped as soon as `scan()` no
longer finds it, before any SIGTERM-all/SIGKILL escalation. `scan()` decides "still alive" by
`read_environ(pid)` (`/proc/<pid>/environ`), which is empty for an exited process, zombie or not
(no address space, so no `STEAM_COMPAT_DATA_PATH`). That is a userspace-existence proxy, not a
"GPU resources reclaimed" proxy. Nothing asks the NVIDIA kernel module, DRM or the Vulkan loader
whether the dead client's VRAM, Vulkan device/queue/fence objects or lease-adjacent handles have
been released; that reclaim is asynchronous to exit.

## Why this is the best-supported hypothesis

Three anomalies, all new to this incident, line up if the killed process's GPU context was still
being torn down when the fresh compositor started rendering:

1. `vkWaitForFences: VK_TIMEOUT` (new to this incident): a fence timeout fits a GPU still busy
   with a lingering client context.
2. `down` needed SIGKILL escalation: a compositor stuck in a low-level GPU/driver call would miss
   the SIGTERM grace window. **Weakened by the reproduction below**: `down` against any live,
   rendering session with a client attached also needed escalation, so this is probably normal.
3. A plain kill plus socket removal was not enough: SIGKILL skips Monado's clean DRM release, and
   only a fresh HID activation (new EDID/hotplug cycle) shook the connector loose.

## Idle-rig reproduction

The rig was idle (no Monado, no Proton trees, load 0.1-0.4, an unrelated Steam app confirmed not
using the GPU via `nvidia-smi --query-compute-apps`). Four back-to-back attempts with the real
launcher path, each with Dali fully loaded first (1.9-2.0 GB GPU memory):

1. Immediate double launch on top of a running session (this also SIGKILLs any running
   `monado-service` as the launcher's own pre-launch hygiene).
2. The same, chained.
3. Orphan variant matching the incident: `jack-in-wayland.sh down` first (Wine tree left alive
   with no compositor), then the launcher finds and kills the orphan and brings Monado up.
4. Repeat of (1) with a 250 ms `nvidia-smi --query-compute-apps` poller across the transition.

**Result: no `vkWaitForFences: VK_TIMEOUT`, DP-2 stayed `connected` throughout** (polled every 8 s
for ~48 s after each attempt), `monado-service` came up clean every time.

**Attempt 4 measured the mechanism.** At one sample the relaunched Dali PID still showed
2085 MiB held with `nvidia-smi` unable to resolve its name (`[No data]`): the process was dead,
`game-stop.py` had already reported "stopped", but the kernel module had not yet released its VRAM.
One 270 ms poll later the entry was gone. The old `monado-service` showed the same pattern. So
there is a real, non-zero window (order of a couple hundred ms, bounded by the poll granularity)
after the "stopped" verdict where GPU memory is still held.

**Why it did not become a failure:** `jack-in-wayland.sh`'s startup (panel activation, DP hotplug
wait, SLAM init, lease negotiation) takes 1-3+ s before the compositor does real Vulkan/DRM work,
longer than the sub-second reclaim lag. The original incident probably needed heavier concurrent
GPU load, or the 2077 s-old orphan reclaimed slowly; neither was recreated.

## No code fix, and what would close it

Sizing a settle poll/sleep would mean guessing the worst-case reclaim lag. Recommended, once a
failing case is available:

- After the appid is confirmed gone, poll until its PIDs are fully absent from `/proc` (not merely
  environ-unreadable) and add a settle margin of ~2-3 s, sized against a real reproduction, in
  `check_no_game_running()` or `game-stop.py stop()`.
- Widen `jack-in-wayland.sh`'s log rotation beyond one `.prev.log`.

To reproduce: run the 250 ms `nvidia-smi` poller during a kill + immediate relaunch under real
concurrent GPU load (something else rendering at the moment of the kill), or catch a live
recurrence and run the poller immediately.

## Related

- `docs/101-dali-presence-screenoff-bypass.md`: the other confirmed trigger for the same outward
  symptom (all three DP disconnected, compositor alive, frames "delivered").
- `docs/103-presence-restore-instrumentation.md` §8: the general stale-lease recovery (kill,
  remove socket, relaunch), which here additionally needed `panel.py activate`.
- `docs/22-cable-connector-diagnosis.md` step 0: the hardware discriminator, negative here.
- Code read: `scripts/vr-launcher.py` (`check_no_game_running()`, `main()`) and
  `scripts/game-stop.py` (`scan()`, `stop()`).
