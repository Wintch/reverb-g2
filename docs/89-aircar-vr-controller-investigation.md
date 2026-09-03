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

## 12. 2026-09-02 (later same day): the live A/B test ran -- patch 0011 does NOT fix it, real cause still open

Ran the exact test section 11 asked for: `RUST_LOG=xrizer=debug`, both G2 controllers on and
paired before Monado start (confirmed `{'left': True, 'right': True}` via `rig_telemetry.
controller_status()`), Aircar launched fresh (3dof). **Wearer verdict: "solo anda xbox, no los
vr"** -- the Xbox pad (which stayed connected this run, not yet controlled out) worked, the VR
wands did not.

**Confirmed independently, not just from the wearer's impression**: the exact binary loaded into
the live game process (`/proc/<pid>/maps` on the real `AirCar-Win64-Shipping.exe` PID, inode
matched against the on-disk file) *is* the patch-0011 build (process started 19:04:57, binary
built 18:46 -- the fix genuinely was running). `DEBUGBOOLFINAL`/`DEBUGVEC1EXPLICIT` still logged
`is_active=false` for every handle, both hands, continuously, minutes into the session
(19:06:43, 19:08:13-14 sampled) -- **the fix did not change the observed symptom at all.**

**So the sync-actions race (patch 0004/0011) is confirmed real and correctly fixed, but is
either not the actual cause of Aircar's specific failure, or only one contributing factor among
several.** Read `frame_start_update`'s logic directly against this session's own log to check
the two remaining unconditional-sync code paths patch 0011 did NOT touch:

- The "no controllers connected -- syncing info set" branch (fires only when xrizer's own
  `devices.get_controller()` sees no connected hand) fired **exactly once**, at `19:05:19.122`,
  right at startup, on the compositor thread -- before xrizer's own device tracking had caught up
  with Monado's already-registered controllers. It never fired again for the rest of the session
  (checked via a later window of the same log). Real, but a narrow one-time startup race, not an
  ongoing per-frame cause.
- **A legitimate session recreation does happen, confirmed directly in the log**: session #1
  created `19:05:00.291` (`ThreadId(1)`), manifest loaded against it at `19:05:19.006`; ~30ms
  later the session cycles `SYNCHRONIZED -> STOPPING -> IDLE -> EXITING` and **session #2** is
  created at `19:05:19.162` (`ThreadId(3)`, right after "Creating real backend for texture type
  Vulkan" / a new 2160x2160 swapchain) -- this is xrizer's own known deferred-graphics-binding
  design (create a placeholder session, then rebuild it once the game's real swapchain format is
  known), not a bug by itself. **The manifest correctly reloads fresh against session #2**
  (`19:05:19.166`, same 23 actions, same bindings) -- `InputSessionData` is confirmed
  per-session (the second `actions.set(loaded)` call would have panicked via
  `unwrap_or_else(|| unreachable!())` if the `OnceLock` had already been set once by session #1;
  the process did not crash, so this path is clean). **This one-time resync at ~19:05:19 is not
  the ongoing cause either** -- the failure persists in steady state for minutes afterward, long
  past both of these startup-only events.

**Net: two more candidate mechanisms directly ruled out with primary evidence, real cause of the
STEADY-STATE (not startup) `is_active=false` still open.** Whoever picks this up next should
stop looking at startup/session-lifecycle events (three separate ones now checked and cleared)
and instead trace what happens to a *specific* action's `xr::Action` handle and its owning
`xr::ActionSet` across many consecutive `UpdateActionState` frames deep into a session, since
that's where the failure actually lives. The raw capture behind this section is
`~/.local/state/xrizer/xrizer.txt`, Aircar PID 245947 launched 19:04:57 -- keep a copy before it
rotates/grows further, this is the richest primary-source session recorded on this bug so far
(full manifest load, both session generations, and live steady-state failure all in one file).

## 13. Operational note: unplugging the Xbox pad mid-flow trips a Steam "no controller detected" dialog

Found while planning a cleaner A/B (Xbox physically disconnected, not just ignored): Steam pops
a "no controller detected" style dialog when its previously-tracked Xbox 360 pad disappears
mid-session, and it needs a manual click to dismiss -- there is no known way to suppress or
auto-dismiss it from here (SSH has no GUI access to click it, and this project deliberately does
not attempt to drive a real desktop dialog from a headless session, see the "manos remotas"
gap noted 2026-08-xx in `NEXT-STEP.md`). **Practical consequence for the booth**: do not plan on
unplugging/re-plugging the Xbox pad live during a demo as a troubleshooting step -- it is not a
transparent hot-swap, a guest-visible Steam dialog appears and someone has to be at the physical
desktop to clear it. This is now the second reason (after the wand-input bug itself) that the
Xbox pad has to be treated as a standing, physically-present booth requirement for Aircar, not
an occasional fallback.

## 14. 2026-09-02 (later still): interaction-profile-changed-event hypothesis refuted; session/event identity confirmed clean; new is_active-and-profile-state instrumentation added (NOT a fix)

A fresh hypothesis was chased in parallel with section 12's own open question: could `is_active`
be gated somewhere on the one-time `XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED` event, such
that it fires correctly for session #1 but never re-fires (or is never consulted) once section
12's session #2 comes up? **Refuted, with primary source read in full on both sides of the
xrizer/Monado boundary:**

- xrizer's `GetDigitalActionData`/`GetAnalogActionData` (`input.rs`) call `action.state(&session,
  subaction_path)` straight into the vendored `openxr` crate (`github.com/ralith/openxrs` @
  `d0afdd3`, matching `Cargo.lock`), which does nothing but forward to
  `xrGetActionStateBoolean`/`_float` on every single call -- zero caching in that crate.
- Monado's own `oxr_action_get_boolean`/`oxr_get_state.c` reset `isActive=XR_FALSE` and fill it
  from `act_attached-><path>.current.active`, which `oxr_action_cache_update`
  (`oxr_input.c`) recomputes **live, on every `xrSyncActions`**, from session-focus state and
  `oxr_input_combine_input()` (itself live: bound-input count + driver `xrt_input->active`). The
  `XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED` push exists purely to notify the *application*
  -- nothing in this gating path reads it.
- A same-day capture (`~/.local/state/xrizer/xrizer.txt`, 19:04:57-19:23:39, since rotated out)
  showed the event firing correctly and specifically for session #2 (4 ms after it reached
  FOCUSED, correct profile for both hands), with `is_active=false` unchanged 18 minutes later --
  direct evidence against the hypothesis, not just source-reading.
- An adversarial re-check (independent, 92→refuted confidence writeup) additionally found: (a)
  Monado's `session_update_action_bindings()` computes the profile-changed event and the actual
  per-action binding call from the *same* `dynamic_roles_generation_id`-gated struct in the same
  pass, so the event firing correctly for session #2 is direct proof the real bind call ran for
  session #2 too, not merely correlated with it; (b) the WMR G2 controller driver
  (`wmr_controller_hp.c`) sets every `xrt_input.active=true` exactly once at controller-object
  creation and never toggles it again, ruling out a driver-level-active-flag cause; (c) this rig's
  `wmr_controller_hp.c` already carries a `binding_profiles[]` compat table (dated 2026-08-06 in
  its own comment) mapping the exact resolved profile from section 12's log
  (`oculus/touch_controller`) to the G2's native inputs -- weakening (not proving false, but
  substantially de-prioritizing) a profile-identity/binding-count-zero theory as the steady-state
  cause; (d) the process runs for minutes without ever panicking on `GetAnalogActionData`'s bare
  `.unwrap()` on `action.state(...)`, which is direct proof (a panic, not an inference) that
  action-set attachment against the current session succeeds and Monado's `false` is a legitimate
  `Ok(is_active=false)`, not a stale-session/detached-actionset error surfacing as a fluke.

**Net result:** this closes the event-identity/session-generation branch of the investigation
that section 12 left implicitly open (it already showed the manifest reload across session #1→#2
was clean; this extends that to the interaction-profile-changed event specifically). It also
narrows section 12's own parting instruction ("trace what happens to a specific action's `xr::
Action` handle... across many consecutive frames") down to one concrete remaining candidate:
**Monado's per-action binding resolution (`cache->input_count==0` inside
`oxr_input_combine_input`/`oxr_action_cache_update`, `oxr_input.c`)** -- still unconfirmed, not yet
directly observed, and the adversarial check's own proposed instrumentation for it
(`OXR_DEBUG_BINDINGS=1` on `monado-service`, and a grep for Monado's `"Failed to get/combine input
values '%s'"` log line) is Monado/env-side, not something to patch into xrizer.

**What was actually done this session: instrumentation only, NOT a fix** (the specific hypothesis
under test was refuted, so per the task's own branching there was nothing here to patch). Three
changes applied to `~/vr/xrizer` (on top of the already-committed `9276835` / patch 0011, which
section 12 already showed does not fix Aircar), re-reading each file's current source before
editing and diffing the edited copy back against a fresh fetch before pushing it back (no
blind/by-line-number patching):

1. `src/openxr_data.rs`, `poll_events_impl`: the `InteractionProfileChanged` arm now binds the
   event (was `(_)`) and logs `event.session()` (the raw session the event itself names, straight
   off `XrEventDataInteractionProfileChanged`) next to `session_data.session.as_raw()` (whatever
   `poll_events_impl` currently treats as "current"), plus whether they match and the session
   state -- `XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED polled: event_session=... current_
   session=... same_session=... session_state=...`. A live tripwire: if a captured run ever shows
   `same_session=false`, that is direct proof of the exact session-identity bug the original
   hypothesis guessed at, without needing to re-derive it from source again.
2. `src/input.rs`, `Input::interaction_profile_changed`'s existing per-hand log line now also
   prints the session's raw handle and state, so it can be correlated against (1) and against
   Monado's own log by session identity, not just by timestamp.
3. `src/input.rs`: a new `log_profile_snapshot!` macro, called from both `GetDigitalActionData`
   and `GetAnalogActionData` immediately before the existing `action.state(...)` call, logging
   `DEBUGPROFILE(bool|analog) handle=... session=... session_state=... left_profile=...
   left_connected=... right_profile=... right_connected=...` -- i.e. exactly what xrizer's own
   `TrackedDevice` bookkeeping believes about profile binding for both hands, on the same call
   that immediately afterward logs the resulting `is_active` (the pre-existing `DEBUGBOOL*`/
   `DEBUGVEC1*` lines from section 10). This is the piece neither the primary trace nor its
   adversarial check could produce without a live capture: whether `connected`/`profile_path` are
   healthy throughout the steady-state failure window, which — if they come back clean — would
   finish ruling out anything on xrizer's side of the boundary and point Monado's
   `cache->input_count` squarely at the sole remaining candidate.

**Build result:** `cd ~/vr/xrizer && source ~/.cargo/env && cargo build --release --features
static-openxr` on iashur -- `Finished \`release\` profile [optimized] target(s) in 9.49s`, zero
errors, zero warnings. `target/release/libxrizer.so` regenerated (16,217,904 bytes, timestamped to
the build). **Not installed/deployed** and **not committed** -- see the live-session note below;
the working tree is left with these two files modified, uncommitted, on top of `9276835`, the same
way section 10's own debug instrumentation was left uncommitted in the tree per section 11's note.

**Heads-up, unresolved by this session: a live session appears to be running right now.**
`monado-service` (PID 290187) has been running continuously since ~19:30 at 500-560% CPU (checked
twice, 19:39 and 19:59, ~29 min elapsed at the second check), with the same Steam/Aircar PIDs
(28292/30278) alive since 16:47 -- this looks like an active wearer session, which is why the new
build was deliberately **not** installed or hot-loaded and `monado-service` was **not** touched.
This contradicts this task's own stated assumption that "no live session is currently running
Aircar" -- flagging it for whoever picks this up rather than silently overriding it. No heavy log
analysis was performed against `~/.local/state/xrizer/xrizer.txt` while this appeared to be live,
per the standing rule (only cheap `ls`/`grep -c` checks to confirm rotation, both showing zero
hits for the section 10-12 capture window, meaning that primary evidence has already rotated out
of the live file and only exists as quoted in this document and the session transcripts that
produced sections 10-12).

**What a live wearer test still needs to check to close this out:**

- Confirm no one is currently wearing the headset, then build+install this instrumented binary
  into whatever path the live `monado-service`/Steam session actually loads `libxrizer.so` from
  (not identified this session -- no install script was found under `~/vr/xrizer`; check how
  patch 0011's build made it into the process section 12 tested, since that same mechanism applies
  here), and restart the affected process(es) cleanly (stale-socket + USB-settle hygiene as usual).
- Launch Aircar with `RUST_LOG=xrizer=debug` as before, reproduce the dead-wand symptom, and pull
  the new `XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED polled` lines: confirm `same_session`
  reads `true` for the whole session (expected, per the source-level refutation above -- but this
  is the first time it will be *observed* rather than reasoned about).
- Correlate the new `DEBUGPROFILE` lines against the adjacent `DEBUGBOOLFINAL`/`DEBUGVEC1EXPLICIT`
  lines for the same handle, deep into the steady-state failure window (minutes in, not just at
  startup): if `left_connected`/`right_connected` are `true` and `left_profile`/`right_profile`
  are non-null (matching `oculus/touch_controller`) throughout while `is_active` stays `false`,
  that finishes eliminating xrizer's side of the boundary entirely and confirms the remaining work
  is purely inside Monado's `oxr_input_combine_input`/`oxr_action_cache_update`.
- In the same run, set `OXR_DEBUG_BINDINGS=1` on `monado-service` (the adversarial check's own
  suggestion, exported the same way `jack-in-wayland.sh` already exports other Monado env vars)
  and grep its output for the specific Aircar actions (Thrust/Reverse axis, Menu Interaction) on
  both hands -- this answers directly whether `cache->input_count` is 0 for them, without needing
  any further xrizer or Monado source patch to find out.

## 15. 2026-09-03: RESOLVED — the real cause was a SECOND patch-0004 defect (binding clobber), fixed in patch 0013

§14's open item is closed. The decisive worn capture ran (docs/93) and named the mechanism. The
cause was NOT the sync race §11 chased — that was a real but separate bug, correctly fixed by
0011 and correctly found not to help here (§12). The real cause is a binding-table **clobber**,
also introduced by patch 0004, one layer earlier: at bind/attach time, before any `sync_actions`
call is even relevant.

**Mechanism (code-confirmed + live-confirmed):**
- `load_action_manifest` suggests the manifest's bindings for the active profile
  (`oculus/touch_controller` for Aircar) via `load_bindings_for_profile` → one
  `xrSuggestInteractionProfileBindings`.
- It then calls `get_or_create_legacy_actions`, whose init closure runs `run_for_all_profiles`
  and re-suggests **legacy** bindings for **every** supported profile — including the one just
  bound — using a disjoint legacy action set.
- Per the OpenXR spec, a second `xrSuggestInteractionProfileBindings` for the same profile
  **replaces (not merges)** the first (Monado `oxr_binding.c` `reset_all_keys`, line 587). So the
  manifest's `touch_controller` bindings are discarded before the single
  `xrAttachSessionActionSets`.
- Every manifest action ends with `input_count==0` → `is_active=false`, no error, forever.

**Why it hid so long:** the clobber leaves the **legacy** bindings intact (the legacy suggest
wins), so legacy-API titles (`GetControllerState`, e.g. Google Earth VR) keep working — only
manifest-API titles (`UpdateActionState`/`GetActionState`, e.g. Aircar) go dead. That reconciles
every prior "but that other title works" observation and is why this looked Aircar-specific.

**Live capture proof** (real G2 hardware, session FOCUSED throughout, both controllers connected,
profile bound):
- OLD binary: `is_active=true` = **0** of 123010; `DEBUGVEC1` true = 0.
- FIXED binary: `is_active=true` = **224928**; `DEBUGVEC1` true present; **182 real presses**
  (`current_state=true`).
- Wearer confirmed in-game: Y switches music, A starts the game, flight works.

**Fix** (`patches/xrizer/0013`, xrizer commit `23df986`): any profile the manifest binds now gets
ONE suggest call carrying the union of manifest + legacy bindings (`load_bindings_for_profile`
folds in `legacy_bindings_for_profile`); `suggest_legacy_bindings_except` handles only the
profiles the manifest did not cover. `get_or_create_legacy_actions` was split into
`get_or_create_legacy_action_data` (create only) + the two suggest helpers. Compiles clean
(`cargo build --release`, 36.7 s, 0 warnings); adversarially verified (2 skeptics, HOLDS).
**Known-benign follow-up**: `pose_data.grip` is bound twice in the merged call — Monado tolerates
duplicate binding pairs (proven live), dedup later.
