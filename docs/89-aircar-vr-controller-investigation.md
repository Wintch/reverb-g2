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
