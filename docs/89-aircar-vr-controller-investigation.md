# 89. Aircar VR controller investigation (2026-08-31)

Session goal: Aircar (Steam appid 1073390) is one of two approved demo-day booth titles
(docs/demo-day plan). Its VR wand controller input was completely dead — only the Xbox
gamepad worked. This doc records everything found while chasing that, what got fixed, and
what is still open.

## 1. Summary of outcomes

| Finding | Status |
|---|---|
| `wmr_hmd.c` bounded-wait bug: a non-final controller-status packet (UNPAIRED/OFFLINE) latched as "done waiting" | **Fixed**, uncommitted on `lab-full` (§2) |
| Right controller undetected across several test runs that day | **Root cause: weak battery**, not software (§3) |
| Monado raw analog pipeline + OpenXR action-state "any"-aggregation | **Verified correct** via instrumented hello_xr (§4) |
| xrizer's "legacy API buttons-dead" bug (docs/49 §5) | **Already fixed 2026-08-18** (commit `48fc243`); docs/49 was stale, corrected today |
| Aircar's actual SteamVR binding files + interaction-profile resolution | **Verified correct** — right A → Menu Interaction, profile resolves to `oculus/touch_controller` for both hands within ~150ms of session start (§5) |
| Aircar's Vector1 actions (Thrust axis / Reverse axis) `is_active` | **Still always `false`** in the real game, cause unknown (§6, open) |
| Aircar's A button (Menu Interaction) in actual play | **Still confirmed dead** even with correct startup order (§6, open) |
| `monado-service` launched outside `jack-in.sh`/`jack-in-wayland.sh` | **New hazard found and documented**: crashes on WMR HMD creation (§7) |

Net effect for demo day: Aircar is **not currently playable with VR wands** — Xbox pad
remains the only working input. If demo day arrives before §6 is resolved, the pad is the
fallback, not the wand.

## 2. `wmr_hmd.c` controller-status fix

`hololens_handle_controller_status_packet()` in `src/xrt/drivers/wmr/wmr_hmd.c` sets
`wh->have_left_controller_status` / `have_right_controller_status = true` on **any**
`WMR_CONTROLLER_STATUS_*` packet, including `UNPAIRED` and `OFFLINE` — not just `ONLINE`.
`wmr_hmd_create()`'s bounded wait (added 2026-08-05 by brunduk, commit `fd00aced73`, to fix
an earlier `@todo` hang) used exactly that flag pair as its exit condition, so a transient
non-final status for either hand could end the wait early with a NULL controller pointer.

Fix (still uncommitted on `lab-full`): wait on `wh->controller[0] != NULL &&
wh->controller[1] != NULL` instead of the two status-received booleans — i.e. wait for the
controller object to actually exist, not merely for *some* status packet to have arrived.

```c
// OLD:
while (!(wh->have_left_controller_status && wh->have_right_controller_status) &&
       os_monotonic_get_ns() < deadline_ns) { ... }
have_controller_status = wh->have_left_controller_status && wh->have_right_controller_status;

// NEW:
while (!(wh->controller[0] != NULL && wh->controller[1] != NULL) &&
       os_monotonic_get_ns() < deadline_ns) { ... }
have_controller_status = wh->controller[0] != NULL && wh->controller[1] != NULL;
```

This is a real, valid fix for a genuine race condition, independent of everything else in
this doc. **Not yet committed** — do that separately (`git diff --stat` on `lab-full` shows
only this file, 15 insertions/6 deletions).

## 3. Battery was the dominant cause of that day's pairing failures

Before the fix above was even fully proven not to fire (it never did — no "re-probing" log
line ever appeared during testing), the right controller repeatedly failed to be detected at
all across 20+ second waits, even with the user confirming both controllers freshly powered
on each time. The fix in §2 is real but was not the active cause that day: the user replaced
the right controller's batteries and detection became reliable immediately afterward. Weak
battery → unreliable BLE radio to the headset's hub → no status packets at all (not even a
non-final one), which §2's bug can't explain since it requires *some* packet to arrive.

**Lesson**: when WMR controller detection is flaky, check batteries before chasing software.

## 4. Monado's raw pipeline is not the bug (hello_xr validation)

Built a custom-instrumented native OpenXR test harness (`~/vr/OpenXR-SDK-Source`, hello_xr)
with debug prints on `xrGetActionStateFloat` for grab/squeeze and trigger, plus an explicit
`XR_NULL_PATH` ("any") query variant. Also temporarily rebound the Oculus Touch profile's
`pauseAction` to right-hand-only (mirroring Aircar's Thrust-axis binding shape) for a
controlled comparison.

Result across multiple live-controller test runs: analog trigger/squeeze values come through
correctly (0.0–1.0 real values) via both an explicit per-hand `subactionPath` and
`XR_NULL_PATH` ("any"), and a single-hand-only-bound action activates correctly. This rules
out Monado's driver-level analog pipeline, OpenXR's any-aggregation mechanism
(`oxr_action_get_pose_input`/`oxr_state_update_*` in `oxr_input.c`/`oxr_get_state.c`), and
the single-hand-binding shape as causes for Aircar's specific failure.

(Some early runs showed flat-zero reads that turned out to be the controller going idle
mid-test — Monado's `jack-in-wayland.log` shows "idle (zeroed) IMU packet -- fusion paused"
with a climbing counter. Always confirm the controller is awake, not just "on", before
trusting a zero reading.)

## 5. Aircar's own SteamVR bindings are correct

Aircar ships default bindings for all standard controller types at
`Aircar/Aircar/Config/SteamVRBindings/`. Checked `oculus_touch.json` (the profile Monado's
G2 driver actually resolves to) directly:

```
/user/hand/right/input/a  --click-->  /actions/main/in/Menu Interaction
/user/hand/left/input/trigger  --pull-->  /actions/main/in/Reverse axis
/user/hand/right/input/trigger --pull-->  /actions/main/in/Thrust axis
```

This is exactly what should dismiss the "A-Start" splash screen and drive the axes. xrizer's
own `profiles::oculus_touch::legacy_bindings` independently confirms the physical mapping
(`a`: Left `X` / Right `A`), matching docs/49 §2.

Captured a full live `RUST_LOG=xrizer=debug` startup trace (via Steam's own
`console-linux.txt`, which the srt-logger wrapper captures — no extra instrumentation
needed; see §7 for why direct stderr capture doesn't work for this title). Confirmed:

- `loading action manifest from ".../steamvr_manifest.json"` fires, 1 action set / 23 actions loaded.
- `loading bindings for /interaction_profiles/oculus/touch_controller` succeeds, "suggested 28 bindings".
- `/user/hand/left interaction profile changed: /interaction_profiles/oculus/touch_controller`
  and the same for `right`, **~150ms after session start** — both hands resolve to the
  correct profile essentially immediately.

So: correct binding file, correct profile resolution, correct physical mapping, all
confirmed from a real log during a real Aircar session. None of this is the bug.

## 6. Open: Vector1/boolean actions read `is_active=false` in real Aircar (UNRESOLVED)

Despite everything in §4 and §5 checking out, live-instrumented `GetAnalogActionData` calls
in xrizer (`DEBUGVEC1`/`DEBUGVEC1EXPLICIT` prints added to `src/input.rs`, not yet reverted)
show `is_active=false`, `current_state=0` for the Thrust axis and Reverse axis actions
**continuously, at the full ~90Hz sync rate, for the entire session** — regardless of
whether queried via `restrict_to_device=0` ("any") or an explicit per-hand
`subactionPath`, and regardless of whether the trigger is actually pulled. Confirmed live
with real button presses on both re-paired controllers with fresh batteries, and confirmed
again after a from-scratch stack relaunch done in the strict order the user identified as
previously reliable (controllers powered on and stable **before** Monado starts — see §7 for
why that ordering matters for a different reason too). The A button (Menu Interaction) was
also confirmed dead in the same clean-order retest — user report: "ningun boton hace nada,
solo xbox anda" even after the reorder.

Ruled out so far: wrong binding file, wrong interaction profile, Monado-level pipeline bugs,
the legacy-buttons-dead bug (already fixed), single-hand-binding shape, and stack startup
ordering (confirmed dead even when ordering was done correctly). Code review of xrizer's
action creation (`actions.rs`), binding suggestion (`bindings.rs`/`context.rs`), and session
restart/re-attach (`openxr_data.rs::restart_session`, `input.rs::post_session_restart`)
did not surface an obvious bug on inspection.

One structural fact noticed but not yet chased down: Aircar's OpenXR session gets
**recreated once, moments after the first one is created** (`compositor: Received game
texture, restarted session with new data` — "Creating OpenXR session" fires twice, at
`.408`/`.409` then again at `.627`/`.628`; SteamVR session states cycle
READY→SYNCHRONIZED→STOPPING→IDLE→EXITING→READY within milliseconds). Both the manifest load
and legacy-action creation happen a second time for the post-restart session, which the code
comments say is by design (mirrors `input.rs::post_session_restart`). Whether the specific
`ManifestLoadedActions`/action objects that xrizer's `GetAnalogActionData`/
`GetDigitalActionData` read from are reliably the *post-restart* ones, vs. some stale
reference surviving from the pre-restart session, has not been directly verified — this is
the most promising remaining lead.

**Not yet tried**: instrumenting the boolean action path (`GetDigitalActionData` /
`get_legacy_controller_state`) the same way `GetAnalogActionData` was instrumented — all of
today's live `is_active` evidence is for the two Vector1 axis actions; the A button's
`is_active` state has never actually been read from a live debug log, only inferred from the
in-headset symptom.

## 7. New hazard: `monado-service` launched outside the jack-in wrappers crashes

Found while trying to bring up the (unrelated) hello_xr 360 photo/video player
(`~/vr/play360.sh`) via `~/vr/jack-in.sh 3dof`. `monado-service` crashed at HMD creation:

```
INFO [t_slam_create] Loading VIT system library from VIT_SYSTEM_LIBRARY_PATH='libbasalt.so'
ERROR [t_vit_bundle_load] Failed to open VIT library: libbasalt.so: cannot open shared object file
ERROR [t_slam_create] Failed to load VIT system library from 'libbasalt.so'
WARN [wmr_hmd_setup_trackers] Unable to setup the SLAM tracker
ERROR [wmr_create_headset] Failed to create WMR HMD device.
...
Result: XRT_ERROR_DEVICE_CREATION_FAILED
```

Root cause: `VIT_SYSTEM_LIBRARY_PATH` defaults (when unset) to the compiled-in
`PREFERRED_VIT_SYSTEM_LIBRARY` macro in `t_tracker_slam.cpp:58`, which is the **bare name**
`"libbasalt.so"` — resolvable only via the system's standard `ld.so` search path. Basalt is
only ever built locally at `~/vr/basalt/build/libbasalt.so`, never `ldconfig`-installed, so
a bare-name lookup always fails. Both `jack-in.sh` and `jack-in-wayland.sh` correctly set
`VIT_SYSTEM_LIBRARY_PATH` to the full local path before launching `monado-service` — but
**whatever launched `monado-service` this time did not go through either wrapper**, so it
inherited the bare compiled-in default and crashed outright on HMD creation (not a graceful
SLAM-disabled fallback — `wmr_hmd_setup_trackers`'s SLAM failure is treated as fatal for the
whole HMD device, and `p_create_system`'s only builder that "was certain it could create a
head" was `wmr`, so the whole system creation failed and the service exited cleanly, exit
code `0`, with the socket never created).

Also confirmed while investigating: plain `jack-in.sh` (X11/Plasma-only) refuses to run over
this SSH session at all ("Not in an X11 session (XDG_SESSION_TYPE=tty)") — it requires being
run from an actual logged-in Plasma X11 session at the physical console, unlike
`jack-in-wayland.sh` which works fine headless/over SSH given the right `DISPLAY`/
`WAYLAND_DISPLAY`/`XAUTHORITY`/`DBUS_SESSION_BUS_ADDRESS` exports.

**Practical rule going forward**: if `monado-service` ever needs bringing up manually
(outside a wrapper) for a one-off test, always pass `VIT_SYSTEM_LIBRARY_PATH=$HOME/vr/basalt/build/libbasalt.so`
explicitly, or just use the wrapper. The fix applied this session was simply to relaunch
via `jack-in-wayland.sh`, which worked cleanly (verified: no basalt error, IPC socket
present).

## 8. Operational notes from this session

- Steam's `srt-logger`-captured `logs/console-linux.txt` (in the Steam installation
  directory) is a reliable way to read RUST_LOG output from an xrizer build without adding
  a custom log file — no need to hunt for where a game's stderr pipe goes. It rotates at 8MB
  (`--rotate=8388608`, one `.previous.txt` kept), and a chatty `RUST_LOG=xrizer=debug` build
  can fill that in a few minutes at ~90Hz sync rate — grab what you need immediately after
  the event you care about, or it's gone.
- Killing only the game's `.exe` PID under Steam's Proton/reaper process tree can leave
  orphaned scaffold processes (`reaper`, `_v2-entry-point`, `pv-adverb`) that block a clean
  relaunch via `-applaunch`, with no visible error — the relaunch silently no-ops
  ("Steam is already running, exiting (command line was forwarded)" with no new game
  process). If a relaunch doesn't produce a new PID, check for and kill the orphaned tree
  before retrying.

## 9. docs/49 correction

docs/49-controller-input-map.md §5 ("Fix specification") was written as a not-yet-implemented
plan for the legacy-buttons-dead bug. `git blame` on `src/input/legacy.rs` shows this was
actually implemented 2026-08-18 (commit `48fc243`), with a regression test
(`legacy_input_still_works_with_manifest`). docs/49 has been corrected in place (header +
status note) rather than rewritten, since the original spec is still an accurate historical
record of the design.

## 10. 2026-09-02: the bug is NOT Vector1-specific -- boolean/digital actions show the exact same is_active=false

Added matching debug instrumentation to `GetDigitalActionData` (`DEBUGBOOL`/`DEBUGBOOLEXPLICIT`/
`DEBUGBOOLFINAL`, mirroring the existing `DEBUGVEC1`/`DEBUGVEC1EXPLICIT` prints in
`GetAnalogActionData`), rebuilt `libxrizer.so` (`--features static-openxr`, confirmed via
`/proc/<pid>/maps` that the freshly-built `~/vr/xrizer/target/release/libxrizer.so` was the one
actually loaded), and captured a real wearer session (headset on, both G2 controllers on and
paired before Monado start, both explicit button/trigger/grip presses attempted).

**Result: every one of the 5 boolean-action handles, plus both Vector1 handles, logged
`is_active=false` continuously for the entire ~9.5-minute captured session** (16:49:07-16:58:49,
`~/.local/state/xrizer/xrizer.txt`) -- a grep for any `true` value across the whole file
(current_state/changed/right_state/left_state) returns **0 hits**. `DEBUGBOOLEXPLICIT` confirms
both `right_active` and `left_active` are false at every single sample, not just the "any
device" aggregate -- ruling out a `restrict_to_device`/subaction-path routing bug for the
digital path too, the same way section 6 already ruled it out for the analog path.

**This changes the shape of the bug**: it is not specific to Vector1/axis actions (as section 6
left it), and not specific to any one binding or action -- it's uniform across every action type
and every handle checked, both hands. This points AWAY from a per-action binding/manifest
problem (already exhaustively checked clean in section 5) and TOWARD something upstream and
structural: either the action SET itself never registers as truly "active" from the runtime's
perspective despite "Activating set /actions/main" firing every sync (dozens of times per
second, i.e. per-frame, per the log), or the session's synced-action-state bookkeeping has a bug
that makes every subsequent action-state read return stale/inactive data regardless of the
actual input. The section 6 "session gets silently recreated once ~200ms after start" lead is
still open and now looks like the most likely remaining thread to pull -- but this session's
data alone can't distinguish "stuck on the pre-restart action objects forever" from "some other
single, one-time init step never completes" without directly instrumenting the sync-actions call
in xrizer itself, not just its own action-state readback. Not done this session; next step for
whoever picks this up.

**Practical note**: given this is broader than previously scoped, don't budget "a quick session
fix" for it again -- it needs either xrizer's own sync-actions call instrumented directly (one
more debug print, cheap) or a from-scratch synthetic OpenXR client test isolating just
"activate an action set, sync actions, read one boolean action" against Monado, to see whether
the bug is xrizer-side or reachable in raw OpenXR too (the hello_xr harness in section 4 tested
the *analog pipeline* end-to-end via Monado's raw API, not the action-set/sync-actions layer
specifically -- these are different code paths and this gap was not closed by section 4).

## 11. 2026-09-02: root cause found and fixed -- patch 0004's unconditional legacy sync races the game's own UpdateActionState

This closes the "uniform across every action type and both hands" mystery section 10 left open. The
regression window bisects to the same two commits already on record for this repo's xrizer fork:
`5b957d4` (patch 0003, HMD presence) and `48fc243` (patch 0004, "legacy state coexists with action
manifests") are the only two commits in the window that touch any input-related file
(`src/input.rs`, `src/input/action_manifest.rs`, `src/input/legacy.rs`, `src/devices.rs`,
`src/openxr_data.rs`) -- confirmed again this session via `git log`. Patch 0004 is the regression:
before it, `frame_start_update` only synced the legacy OpenVR action set when no manifest was
loaded (or no controllers were connected). Patch 0004 made that call **unconditional** -- it now
fires every frame from `frame_start_update` regardless of whether a manifest is loaded and the
game is already driving its own per-frame sync via `UpdateActionState`.

**Mechanism, verified against the live source, not just the patch text:**

- `UpdateActionState` (input.rs, game-logic thread) and `frame_start_update` (input.rs, called from
  `Compositor::WaitGetPoses` -- the compositor/render thread) each independently call
  `session.sync_actions(...)` every frame, with nothing in xrizer serializing them against each
  other -- each just takes its own `session_data.get()` read-guard.
- Monado's `oxr_action_sync_data_with_context` (`oxr_input.c`) resets (`U_ZERO`) every
  previously-attached action set's state, then repopulates only the sets named in *that specific
  call*. `oxr_action_cache_update` zeroes `cache->current` (including `active`) for any set that
  comes back unselected.
- The only mutex in that path (`sess_context->sync_actions_mutex`) guards an earlier, unrelated
  "redo dynamic-role bindings" block -- the reset+repopulate section itself is **not** lock-protected
  against a second, concurrent caller.
- Net effect: two independent per-frame `xrSyncActions` callers on two different threads are
  last-write-wins at the whole-action-set granularity. Whichever call's reset+repopulate lands
  second zeroes `is_active` for every set the other call named that it didn't also name. No
  sub-millisecond interleaving is required -- any ordering where one call finishes after the other
  is sufficient. This explains why the failure was 100% of samples, both hands, every action type
  (boolean and Vector1 alike, per section 10) rather than intermittent: the clobbering happens
  upstream of any per-action or per-binding logic, at the whole-set level, on effectively every
  frame.
- A real 2026-09-02 failing-session log (the one behind section 10's findings) already shows the
  two call sites on distinct threads -- `WaitGetPoses`/session-state activity on one `ThreadId`,
  `UpdateActionState`/`GetActionState` on another -- with no synchronization between them, which is
  exactly the precondition for this to fire on effectively every frame.
- Alternative candidates were ruled out: Aircar's launcher entry `WMR_CONSTELLATION_CONTROLLERS=0`
  is real (`vr-launcher.py:164-167`) but every reference to that env var in Monado's source lives in
  the WMR driver files (`wmr_hmd.c`, `wmr_camera.c`, `wmr_source.c`, `wmr_controller_base.c`,
  `target_builder_wmr.c`) -- never in `src/xrt/state_trackers/oxr`, where action attachment, sync,
  and `is_active` computation actually live -- so it cannot be a contributing mechanism to this
  bug. Patches 0005-0010 are compositor/`openxr_data`/chaperone-only and don't touch the input
  path at all.

**Fix applied (a real fix, not instrumentation).** `UpdateActionState` now folds the legacy action
set into its *own* `sync_actions` call whenever a manifest is loaded (so legacy and the game's own
sets land in one combined call instead of two racing ones), and sets a new `legacy_synced_by_game`
flag (`AtomicBool`) when it does. `frame_start_update` now only performs its own standalone legacy
sync when that flag was *not* set this frame (swap-and-clear) -- i.e. only for the case patch 0004
was actually trying to serve: a title that loaded a manifest defensively but only ever polls the
legacy `GetControllerState` API and never calls `UpdateActionState` itself. Applied to
`~/vr/xrizer/src/input.rs` on iashur (4 hunks: struct field, `Input::new` init, the
`UpdateActionState` sync-set build, and the `frame_start_update` fallback branch), matching the
current tree byte-for-byte before editing -- re-read from the live file first, not patched blind
by line number. Committed as `9276835` ("input: fold legacy sync into game's own UpdateActionState
call") on top of `ed77ef8`, isolated from an unrelated, still-uncommitted debug-instrumentation diff
already sitting in the working tree from section 10's investigation (left untouched, not mine to
remove). Vendored as
`patches/xrizer/0011-input-fold-legacy-sync-into-games-own-updateactionstate.patch` in this repo,
following the existing 0001-0010 convention.

**Build result:** `cargo build --release --features static-openxr` on iashur --
`Finished \`release\` profile [optimized] target(s) in 6.51s`, zero errors, zero warnings (forced a
full recompile of `input.rs` via `touch` to confirm, not relying on a stale incremental cache).
`target/release/libxrizer.so` regenerated (16201056 bytes, timestamped to the build).

**Confidence:** high on the mechanism -- independently re-derived from Monado's actual source
(`oxr_input.c`) and xrizer's actual current source in this session, not taken on faith from an
earlier report. Still **NOT wearer-confirmed**: no live test was available this session.

**Outstanding: needs a live wearer A/B test before this can be marked resolved.** Both G2
controllers powered on and paired *before* Monado start, **no Xbox 360 pad connected** (Aircar's
own gamepad requirement, docs/23, was already controlled out once in the unrelated T193 A/B and
should be again here so it can't confound the result), following the same before/after methodology
as that A/B: launch Aircar, attempt real button/trigger/grip input on both controllers, confirm
`is_active=true` and real gameplay response where section 10's captured session showed
`is_active=false` for the full ~9.5 minutes on every handle checked. If section 10's debug
instrumentation (`DEBUGBOOL`/`DEBUGVEC1`/etc., still present uncommitted) is left in place for that
test, its log output can be used to confirm the fix directly rather than relying on gameplay feel
alone.
