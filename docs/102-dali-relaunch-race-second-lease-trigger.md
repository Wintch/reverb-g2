# 102 -- The second DP/lease-drop trigger (2026-09-05): a zero-settle-time race after killing a stale Wine tree, not the presence bug

**Status: structural cause CONFIRMED at the code level (a real race exists, not hypothetical);
the specific failure mechanism (stale GPU/Vulkan resources delaying the fresh compositor) is the
best-supported hypothesis given the evidence, but NOT independently confirmed by reproduction --
the rig was mid-use (a live Dali session) for this entire investigation, so no live test was run.
This is the "second, distinct trigger" `docs/100` (lines 220-235) and `docs/101`'s closing note
both flagged as still open. It is a DIFFERENT bug from `docs/101`'s presence-screenoff bypass:
that fix is correct and unrelated -- this trigger fired ~20-30s after launch, far too soon for any
120s timer, and `WMR_USER_PRESENCE` was not even set on the affected launch.**

## The incident, recap (full detail in the investigation prompt, not repeated here)

`~/vr/vr-launcher.py 1 6dof` with `VR_LAUNCH_APPID=591360` at 13:25:08 -03. The launcher's own
stale-process guard (`check_no_game_running()`) found an earlier Dali (591360) Wine tree still
alive 2077s after its wrapper had died, killed it, and immediately proceeded to bring Monado up
fresh. The DRM lease sequence in the log looked completely normal (lease granted, mode taken,
"Idle-blank suppressed"). ~20-30s later, all three `card0-DP-*` connectors read `disconnected`,
`monado-service` was still alive and still logging `Delivered frame` lines, and a new warning
never seen in any other incident that day appeared: `WARN [vblank_event_func] vkWaitForFences:
VK_TIMEOUT`. `docs/22` step 0's hardware-fault discriminator came back negative (`panel.py
activate` succeeded, USB stayed 5/5) -- same as `docs/101`'s incident, not a cable fault.

The one new detail vs. every other incident that day: `jack-in-wayland.sh down` needed the
SIGKILL escalation ("still running after 10s") to actually kill `monado-service`, and even after
that full teardown (no `monado-service` process alive, socket removed), DP stayed `disconnected`
until a *separate* `panel.py activate` forced a fresh HID-level reactivation ~2s later. Every
prior incident that day recovered from a plain compositor kill alone.

## What was checked here, and what it rules out

- **Journalctl (`-b 0`, 13:24:30-13:27:00 -03)**: no kernel-level GPU reset/timeout message, no
  USB error, no crash signature. Consistent with `docs/101`'s already-established finding that
  NVIDIA's proprietary driver does not log connector-status or GPU-context-teardown transitions to
  the kernel ring buffer -- an absence of kernel evidence here does not rule the hypothesis below
  in or out, it is simply a known blind spot for this stack.
- **`coredumpctl list --since "2026-09-05 13:00:00"`**: no coredumps at all. The killed Dali
  process exited (or was reaped) without crashing -- this was a clean SIGTERM exit, not a fault.
- **The exact `vkWaitForFences: VK_TIMEOUT` log line could not be independently re-verified.**
  `jack-in-wayland.sh` keeps exactly ONE rotation deep (`cp -f "$LOG" "${LOG%.log}.prev.log"` on
  every `up`, no `.prev2.log` for a same-day rotation). Between the incident (13:25:08) and now,
  there were at least two more `up` cycles (the clean recheck relaunch at ~13:27, and the
  currently-running session started 13:42:43) -- each one pushed the previous log one slot further
  and the incident's own log has fallen out of the single-slot rotation window. This is a real gap:
  worth widening `jack-in-wayland.sh`'s rotation depth (keep N previous logs, not 1) so a
  same-day, multi-relaunch investigation like this one doesn't lose its own smoking gun. Not fixed
  in this doc (touches a script relied on by a currently-live session -- see below).

## The structural race: confirmed, with line numbers

`~/vr/vr-launcher.py`, `main()`:

```python
    # No second client by accident: a previous title's Wine tree must be gone first.
    if not check_no_game_running():        # line 691
        sys.exit(1)

    if not bring_up_monado():              # line 694 -- the very next executable line
        print("No lanzo nada -- Monado no quedo listo.")
        sys.exit(1)
```

There is **zero delay, zero settle time, no poll for any external condition** between
`check_no_game_running()` declaring the stale tree gone and `bring_up_monado()` starting the fresh
`jack-in-wayland.sh up`. This is not a guess -- it is the literal next line of code.

`check_no_game_running()` calls `game-stop.py stop all` (`~/Documents/reverb-g2/scripts/
game-stop.py`), which SIGTERMs the Windows main exe(s), then polls `scan()` every 0.5s for up to
8s, and declares the appid "stopped" the moment `scan()` no longer finds it -- **before** falling
back to the SIGTERM-all/SIGKILL escalation branch (which only triggers if that first 8s poll times
out). Critically, `scan()`'s "is this appid still alive" check is `read_environ(pid)` --
`/proc/<pid>/environ`. For an already-exited process, whether still an unreaped zombie or fully
gone, this file is empty (a zombie has no address space, so no `STEAM_COMPAT_DATA_PATH` can be
read from it) -- `scan()` correctly stops counting it, and `game-stop.py` correctly reports
"stopped." **But this is a userspace-process-existence proxy, not a GPU-resource-reclaimed proxy.**
Nothing in this codepath asks the NVIDIA kernel module, DRM, or the Vulkan loader whether the just-
terminated process's client state (VRAM allocations, Vulkan device/queue/fence objects, any DRM
lease-adjacent handles) has actually been released -- that reclaim happens on the kernel driver's
own schedule, asynchronously to the SIGTERM/exit, and this codebase has no way to observe it.

## Why this is the best-supported hypothesis for the specific symptom (not just a coincidence)

Three independent details line up if (and only if) the just-killed Dali process's GPU/Vulkan
context was still being torn down by the driver when the fresh `monado-service` started rendering:

1. **`vkWaitForFences: VK_TIMEOUT`, new only to this incident.** A fence timeout is exactly the
   symptom of a GPU that is contended/busy with something else at the driver level when the new
   compositor submits work and waits on it -- consistent with a lingering client context still
   being reclaimed, not consistent with a cleanly-idle GPU (every other incident that day, launched
   without a stale tree to kill first, never produced this warning).
2. **`jack-in-wayland.sh down` needed the SIGKILL escalation this time.** `jack-in-wayland.sh`'s
   own comment (around its `down` handler) says SIGTERM is sent deliberately first because it
   "runs Monado's clean-path handler (screen-off, DRM lease released)" -- i.e. a healthy
   `monado-service` is expected to exit within the 10s SIGTERM grace window on every previous
   incident that day. This time it didn't, and had to be force-killed. A compositor whose render
   thread is itself blocked in a stuck low-level GPU/driver call (e.g. still inside the same fence
   wait that produced the timeout warning, or a subsequent one) is a coherent explanation for why
   its signal handler could not complete its normal shutdown path in time -- it lines up with #1,
   it isn't a second unrelated anomaly.
3. **A plain kill + socket removal was NOT enough to restore the connector this time**, unlike
   every earlier incident that day. Because SIGKILL (the escalation path) skips Monado's own clean
   DRM-release code entirely, the connector was left in whatever state the GPU/bridge was in at the
   moment of the kill -- consistent with the lease/panel state being genuinely wedged rather than
   cleanly released-but-not-yet-re-leased, and consistent with why only a fresh HID-level
   `panel.py activate` (forcing a new EDID/hotplug cycle, independent of anything Monado's
   compositor code does) was able to shake it loose.

None of these three are independently proven at the driver level (no kernel log, no coredump, as
noted above) -- but they are three separate observed anomalies, all novel to this one incident,
and all point the same direction. That is stronger than the "two data points, same day" pattern-
match this investigation started from, even though it stops short of a instrumented, reproduced
confirmation.

## What was NOT done, and why

**No reproduction was attempted.** At the time of this investigation, `pgrep -af monado-service`
showed a live `monado-service` (PID 191446, started 13:42:43, ~10 minutes old at the time of
checking) and `game-stop.py status` showed an ACTIVE Dali (591360) Wine tree already running
(oldest 782s at the time of checking) under that session -- `loginctl`'s `IdleHint=no`, and load
average 8.95. This is a live, in-use session, not an idle rig. Per this investigation's own
constraints, no kill/relaunch cycle was run against it. **Reproducing this deliberately (kill a
long-lived same-title Wine tree, immediately relaunch, watch for `vkWaitForFences` and the DP
status) is the single most valuable next step to fully close this out**, but it needs a genuinely
idle rig first.

**No code fix was implemented.** The confirmed race (zero settle time, proxy-only "stopped" check)
is real and a fix is easy to describe in the abstract -- poll for the killed appid's PIDs to be
fully absent from `/proc` (not merely environ-unreadable, which a zombie already satisfies) with
an added settle margin, or a conservative fixed sleep, between `check_no_game_running()` returning
and `bring_up_monado()` starting. But `vr-launcher.py` and `game-stop.py` are exactly the scripts
the currently-live session depends on, this is a demo-day-critical rig, and the right settle margin
should be sized against an actual reproduction rather than picked blind. Landing an unvalidated
timing change into a live-relied-upon launcher the same day is not worth the risk. **Recommended,
not yet implemented**:

- In `vr-launcher.py`'s `check_no_game_running()` (or inside `game-stop.py stop()` itself): after
  the appid is confirmed gone by the existing proxy, add a short additional poll/sleep before
  returning control to the caller -- long enough to give the NVIDIA kernel module a chance to
  finish reclaiming the exited client's GPU resources. Size this empirically (start with something
  like 2-3s and tighten or loosen based on a real reproduction) rather than guessing a number now.
- Widen `jack-in-wayland.sh`'s log rotation from one `.prev.log` slot to a few, so a same-day
  multi-relaunch investigation doesn't lose its own key evidence to overwrite, as happened here.

## Cross-references

- `docs/100-dali-6dof-redraw-and-gpu-headroom.md`, lines 220-235: first flagged this as a second,
  uncorrelated trigger the same day, distinct from `docs/101`'s presence-screenoff bug.
- `docs/101-dali-presence-screenoff-bypass.md`: the OTHER confirmed-and-fixed trigger for the same
  outward symptom (all 3 DP disconnected, compositor alive, frames still "delivered"). Its closing
  note already pointed here.
- `docs/98-presence-restore-broken-and-stale-drm-lease.md` section 2: the general "stale DRM
  lease, HID activation succeeds but Monado's lease stays dead" recovery signature and fix
  (kill + socket removal) that this incident matches for steps 1-4, but which uniquely did NOT
  fully work here without the extra `panel.py activate` step (section above explains why).
- `docs/22-cable-connector-diagnosis.md` step 0: the hardware-fault discriminator run here, came
  back negative (not a cable/connector hardware fault).
- `~/Documents/reverb-g2/scripts/game-stop.py`, `~/Documents/reverb-g2/scripts/vr-launcher.py`
  (mirrored at `~/vr/vr-launcher.py`): the code read for this investigation, `check_no_game_running()`
  around line 470 and its call site at lines 691/694, `game-stop.py`'s `scan()`/`stop()`.

## 2026-09-05 (later the same day): idle-rig reproduction attempted -- mechanism partially confirmed, failure symptom NOT reproduced, no code fix shipped

**Status: the rig was genuinely idle this time** (`pgrep -af monado-service` empty, no Proton
trees, `loginctl` `IdleHint=no` but load average 0.1-0.4, only an unrelated non-VR Steam
app (482390) sitting in the background, confirmed not touching the GPU via
`nvidia-smi --query-compute-apps`). This is the reproduction this doc's own "What was NOT
done" section asked for.

### What was run

Four back-to-back attempts, all using the real launcher path (`VR_LAUNCH_APPID=591360
python3 ~/vr/vr-launcher.py 1 6dof`), each time letting Dreams of Dali reach a real
established running state first (dreamsofdali.exe as the main exe, stable process count,
1.9-2.0 GB of GPU memory allocated per `nvidia-smi`, well past the loading screen) before
triggering the second launch:

1. **Immediate double-launch** (~14:41-14:44): launch A up for ~172s, then launch B
   immediately on top of it. `check_no_game_running()` SIGTERM'd the main exe, reported
   "stopped" after the plain 8s poll (no escalation), `bring_up_monado()` ran straight after
   -- this also SIGKILLs any already-running `monado-service` as its own pre-launch hygiene
   (`jack-in-wayland.sh` line ~283), so this attempt tore down BOTH the game and the old
   compositor together and brought a fresh one up with zero settle time, same as the
   structural race this doc describes.
2. **Repeat of (1), chained** (~14:46): same pattern immediately on launch B's own tree.
3. **Orphan variant, closer to the actual incident's shape** (~14:49-14:50): let Dali run
   ~180s, then ran `jack-in-wayland.sh down` on its own (clean SIGTERM path) to kill
   *only* `monado-service`, leaving the Dali Wine tree alive with no compositor at all --
   matching this doc's own read of the incident ("bring Monado up fresh", i.e. no live
   monado-service existed right before the stale-tree kill). Then ran vr-launcher.py fresh,
   which found the orphaned tree, killed it, and brought Monado up for the first time in
   that window (no second monado-service to also kill).
4. **Repeat of (1), instrumented**: same immediate double-launch, but with a 250ms-interval
   `nvidia-smi --query-compute-apps` poller running in the background across the whole
   transition, to see the actual GPU-memory reclaim timing directly instead of inferring it.

In all four, watched: `~/vr/jack-in-wayland.log` for `vkWaitForFences: VK_TIMEOUT`,
`/sys/class/drm/card0-DP-*/status` for `disconnected` (polled every 8s for ~48s after each
attempt, since the original incident's disconnect showed up 20-30s late), and whether
`jack-in-wayland.sh down` needed the SIGKILL escalation.

### Result: the specific failure symptom did NOT reproduce

None of the four attempts produced `vkWaitForFences: VK_TIMEOUT`, and DP-2 (this rig's
active connector, now on a fresh port after the 2026-09-03 GPU swap) stayed `connected`
throughout every attempt and every poll window. `monado-service` came up clean every time.

### But attempt 4 measured the hypothesized mechanism directly, and it is real

The 250ms poller caught the exact transition. At one sample, the about-to-be-relaunched
Dali PID (316771) still showed **2085 MiB held, with `nvidia-smi` unable to resolve its
process name (`[No data]`)** -- i.e. the process was already dead (SIGTERM had landed,
`game-stop.py` had already reported "stopped" to the caller) but the NVIDIA kernel module
had not yet released its VRAM allocation. One 270ms poll cycle later, that PID's entry was
gone entirely -- the reclaim had completed by then. The old `monado-service` PID
(316060, killed by the launcher's own pre-launch hygiene in this same window) showed the
same pattern: present with shrinking memory for one sample, gone the next.

So the doc's central claim is now **directly measured, not just inferred from code
reading**: there is a real, non-zero window (on this rig, on the order of a couple hundred
ms, bounded above by our poll granularity) after `game-stop.py stop`'s "stopped" verdict
during which the just-killed process's GPU memory is still held by the driver. The
zero-settle-time race described in this doc is real.

**Why it didn't turn into a visible failure here:** `jack-in-wayland.sh`'s own startup path
(panel activation, DP hotplug wait, SLAM thread/pipeline init, DRM lease negotiation) takes
on the order of 1-3+ seconds before the fresh compositor actually reaches the point of
doing real Vulkan/DRM work against the GPU. That is comfortably longer than the
sub-second reclaim lag actually measured here. On an idle rig with a single GPU consumer,
that margin was enough every time. The original incident likely needed something this
reproduction didn't have -- heavier concurrent GPU/driver load, or something specific to
that process having been orphaned for 2077s (over half an hour) rather than freshly killed,
that either slowed the reclaim down or otherwise changed the timing. That variable was not
capturable in a short idle-rig test and remains unconfirmed.

### A correction to this doc's own evidence item #2

Both times `jack-in-wayland.sh down` was run against a still-actively-connected Dali
session during this test (once mid-sequence to set up attempt 3, once at final cleanup),
it needed the SIGKILL escalation ("Still running after 10s") -- in neither case was this
part of a stale-tree relaunch race, just a plain teardown of a live, healthy, rendering
session. This suggests the SIGKILL-escalation-on-`down` symptom this doc treated as novel
evidence *for* the race (item #2 above) may simply be normal behavior whenever a real
OpenXR client is attached at teardown time, independent of the specific race described
here. It doesn't rule the race hypothesis out (items #1 and #3, and now the direct VRAM
measurement above, still stand on their own), but it weakens item #2 specifically as
supporting evidence -- worth not leaning on it further without a cleaner isolation test
(a plain `down` with a live client but no prior relaunch, repeated a few times, to see how
often it needs escalation on its own).

### No code fix shipped

Per this investigation's own instructions: the specific failure symptom (the actual DP
disconnect + fence timeout) was not reproduced in four honest, well-instrumented attempts,
including one shaped to match this doc's own read of the incident's preconditions. Sizing
a poll/sleep fix now would mean guessing the one number that matters most -- how much
margin the *worst-case* reclaim lag needs, under conditions this test could not recreate --
exactly the kind of blind guess this doc already said not to make. `vr-launcher.py` and
`game-stop.py` are unchanged, in both the tracked repo (`~/Documents/reverb-g2/scripts/`)
and the live copy (`~/vr/vr-launcher.py`), which were re-confirmed identical (`diff`,
zero output) both before and after this session.

### What would make this fully confirmed

The measured reclaim-lag mechanism is real; what's still missing is a set of conditions
that reliably pushes it past the ~1-3s margin `jack-in-wayland.sh`'s own startup provides.
Candidates for a next attempt, if this comes up again: reproduce under real concurrent GPU
load (something else actively rendering at the moment of the kill+relaunch, not an
otherwise-idle GPU), or catch a live recurrence of the incident itself and immediately run
the same 250ms `nvidia-smi --query-compute-apps` poller this session used, to directly
measure the reclaim lag on the failing case instead of a clean one.

### Cleanup

`jack-in-wayland.sh down` run at the end (needed its own SIGKILL escalation, see above),
`game-stop.py stop all` confirmed `no Proton game trees running`, all three
`card0-DP-*` connectors back to the idle baseline (`disconnected`, matching the pre-test
state), no `~/vr/.jack-in-failed` marker left behind, `coredumpctl` shows nothing new for
the whole session, and the unrelated background Steam app (482390) was left untouched
throughout.
