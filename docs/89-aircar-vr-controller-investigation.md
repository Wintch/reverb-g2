# 89. Aircar VR controller investigation (2026-08-31 to 2026-09-03)

Aircar (Steam appid 1073390) is a manifest-API (`UpdateActionState` / `GetActionState`) OpenVR title.
Its VR wand input was completely dead under xrizer + Monado; only the Xbox gamepad worked. This doc
records the root cause, the two real-but-unrelated bugs found on the way, and the list of hypotheses
that were refuted (so nobody chases them again).

## 1. Summary

| Finding | Status |
|---|---|
| `wmr_hmd.c` bounded-wait bug: a non-final controller-status packet (UNPAIRED/OFFLINE) latched as "done waiting" | **Fixed** (§2) |
| Right controller undetected across several test runs | **Root cause: weak battery**, not software (§3) |
| Monado raw analog pipeline + OpenXR action-state "any"-aggregation; Aircar's own SteamVR bindings; interaction-profile resolution | **Verified correct** (§4) |
| xrizer legacy-API "buttons dead" bug | Already fixed by xrizer patch 0004 (2026-08-18) |
| Per-frame double `xrSyncActions` race (patch 0004 side effect) | Real, fixed by patch 0011, **but not the cause** of Aircar's symptom (§6) |
| Every manifest action `is_active=false`, both hands, forever | **Root cause: patch 0004's second `xrSuggestInteractionProfileBindings` clobbered the manifest bindings; fixed by patch 0013** (§7) |
| `monado-service` launched outside the jack-in wrappers | Crashes on WMR HMD creation (§8) |

## 2. `wmr_hmd.c` controller-status fix

`hololens_handle_controller_status_packet()` in `src/xrt/drivers/wmr/wmr_hmd.c` sets
`wh->have_left_controller_status` / `have_right_controller_status = true` on **any**
`WMR_CONTROLLER_STATUS_*` packet, including `UNPAIRED` and `OFFLINE`, not just `ONLINE`.
`wmr_hmd_create()`'s bounded wait (added 2026-08-05, commit `fd00aced73`, to fix an earlier `@todo`
hang) used that flag pair as its exit condition, so a transient non-final status for either hand
could end the wait early with a NULL controller pointer.

Fix: wait on `wh->controller[0] != NULL && wh->controller[1] != NULL` instead of the two
status-received booleans, i.e. wait for the controller object to actually exist.

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

This is a genuine race fix, independent of everything else in this doc (the "re-probing" log line
never appeared during the Aircar tests, so it was not the active cause there).

## 3. Battery was the dominant cause of the pairing failures

The right controller repeatedly failed to be detected at all across 20+ second waits, even with both
controllers freshly powered on each time. Replacing the right controller's batteries made detection
reliable immediately. Weak battery gives an unreliable BLE radio to the headset's hub and no status
packets at all (not even a non-final one), which §2's bug cannot explain because it needs *some*
packet to arrive.

**Lesson**: when WMR controller detection is flaky, check batteries before chasing software.

## 4. What was verified clean

- **Monado's raw analog pipeline** (instrumented `hello_xr` with prints on `xrGetActionStateFloat`
  for grab/squeeze/trigger, an explicit `XR_NULL_PATH` "any" query, and a single-hand-bound action):
  analog values come through correctly (0.0-1.0) via both a per-hand `subactionPath` and `XR_NULL_PATH`,
  and a single-hand-bound action activates. This rules out the driver-level analog pipeline, OpenXR
  any-aggregation (`oxr_input.c` / `oxr_get_state.c`) and the single-hand-binding shape. Flat-zero
  reads in early runs were the controller going idle mid-test ("idle (zeroed) IMU packet -- fusion
  paused" in the Monado log): always confirm the controller is awake, not just "on", before trusting
  a zero.
- **Aircar's bindings**: `Aircar/Aircar/Config/SteamVRBindings/oculus_touch.json` maps right `a` to
  `Menu Interaction`, left trigger to `Reverse axis`, right trigger to `Thrust axis`, which is what
  dismisses the splash screen and drives the axes. xrizer's `profiles::oculus_touch::legacy_bindings`
  agrees on the physical mapping (`a`: Left `X` / Right `A`).
- **Profile resolution**, from a live `RUST_LOG=xrizer=debug` startup trace: manifest loaded (1 action
  set / 23 actions), `loading bindings for /interaction_profiles/oculus/touch_controller` succeeds
  ("suggested 28 bindings"), and both hands report `touch_controller` about 150 ms after session start.

## 5. The symptom: uniform `is_active=false`

Instrumented `GetAnalogActionData` / `GetDigitalActionData` in xrizer (`DEBUGVEC1*`, `DEBUGBOOL*`
prints) and captured a worn session with both controllers on and paired before Monado started. Every
one of the 5 boolean-action handles and both Vector1 handles logged `is_active=false` for the entire
~9.5-minute session (zero `true` hits), for both hands and for both the "any device" aggregate and the
explicit per-hand query. So the bug is not specific to Vector1/axis actions, to a binding, or to a
`restrict_to_device` routing problem: it is uniform across every action type and handle, which points
at something structural upstream of per-action logic.

## 6. Real but not the cause: patch 0004's per-frame sync race (fixed by patch 0011)

Bisect (two xrizer patches, both 2026-08-18, are the only commits in the working-to-broken window that
touch any input file; no Monado `oxr` patch and no Proton bump falls in it; patches 0005+ are
compositor/`openxr_data`/chaperone only): `0003` (XR_EXT_user_presence) and `0004` (`input: legacy
state coexists with action manifests`). The regression is a change one of those two introduced.

Patch 0004 made `frame_start_update` sync the legacy OpenVR action set unconditionally every frame,
on the compositor thread (`WaitGetPoses`), while the game drives its own per-frame sync from
`UpdateActionState` on another thread. Monado's `oxr_action_sync_data_with_context` resets every
previously attached action set and repopulates only the sets named in *that* call, and that section is
not lock-protected, so two concurrent callers are last-write-wins at whole-set granularity: whichever
lands second zeroes `is_active` for sets the other named. That would explain a uniform failure.

Fix (xrizer commit `9276835`, `patches/xrizer/0011-input-fold-legacy-sync-into-games-own-updateactionstate.patch`):
`UpdateActionState` folds the legacy set into its own `sync_actions` call when a manifest is loaded and
sets an `AtomicBool legacy_synced_by_game`; `frame_start_update` only does its own standalone legacy
sync when that flag was not set (swap-and-clear), i.e. only for titles that load a manifest but poll
only the legacy `GetControllerState`.

**A live wearer A/B (patch 0011 binary confirmed loaded via `/proc/<pid>/maps`) showed no change:**
`is_active=false` on every handle for minutes. The race is real and correctly fixed, but is not what
broke Aircar. The same log also cleared two startup events: the "no controllers connected" sync branch
fires exactly once at startup and never again, and the one-time session recreation (xrizer creates a
placeholder session, then rebuilds it once the game's real swapchain format is known; the manifest
reloads cleanly against session #2) does not explain a steady-state failure either.

## 7. Root cause: patch 0004's binding clobber (fixed by patch 0013)

The decisive worn capture named the mechanism: a binding-table clobber, also introduced by patch 0004,
one layer earlier than the sync race, at bind/attach time.

- `load_action_manifest` suggests the manifest's bindings for the active profile
  (`oculus/touch_controller` for Aircar) via `load_bindings_for_profile`: one
  `xrSuggestInteractionProfileBindings`.
- It then calls `get_or_create_legacy_actions`, whose init closure runs `run_for_all_profiles` and
  re-suggests **legacy** bindings for **every** supported profile, including the one just bound, using
  a disjoint legacy action set.
- Per the OpenXR spec, a second `xrSuggestInteractionProfileBindings` for the same profile **replaces,
  not merges**, the first (Monado `oxr_binding.c`, `reset_all_keys`). The manifest's bindings are
  discarded before the single `xrAttachSessionActionSets`.
- Every manifest action ends with `cache->input_count == 0`, so `oxr_action_cache_update` never sets
  `.active` and `isActive` reads false from the first `xrSyncActions`, with no error and no
  default-verbosity log.

**Why it hid so long:** the clobber leaves the **legacy** bindings intact, so legacy-API titles
(`GetControllerState`, e.g. Google Earth VR) keep working; only manifest-API titles go dead. That is
why it looked Aircar-specific.

**Live proof** (real G2 hardware, session FOCUSED throughout, both controllers connected, profile
bound): old binary `is_active=true` = 0 of 123010 samples; fixed binary `is_active=true` = 224928
samples with 182 real presses (`current_state=true`). In-game: Y switches music, A starts the game,
flight works.

**Fix** (`patches/xrizer/0013-input-fix-patch-0004-binding-clobber-manifest-action.patch`, xrizer commit
`23df986`): any profile the manifest binds gets ONE suggest call carrying the union of manifest and
legacy bindings (`load_bindings_for_profile` folds in `legacy_bindings_for_profile`);
`suggest_legacy_bindings_except` handles only profiles the manifest did not cover;
`get_or_create_legacy_actions` was split into `get_or_create_legacy_action_data` (create only) plus the
two suggest helpers. Known-benign: `pose_data.grip` is bound twice in the merged call; Monado tolerates
duplicate binding pairs (proven live).

### Deployment note

xrizer is deployed by the build itself: `openvrpaths.vrpath`'s runtime entry points at
`.../xrizer/target/release`, whose `bin/linux64/vrclient.so` is a permanent symlink (made once by
`build.rs`) to `libxrizer.so`. Whatever `cargo build --release` last wrote is what Steam loads on the
next launch. Controllers must be on before Monado starts (no hotplug).

## 8. Refuted hypotheses (do not chase again)

- Wrong binding file / wrong interaction profile / naive profile fallback mismatch: both hands resolve to
  `oculus/touch_controller`, the profile Aircar's manifest binds.
- Monado raw analog pipeline, OpenXR any-aggregation, single-hand-binding shape (§4).
- Stack startup ordering (confirmed dead even with controllers on and stable before Monado).
- The unconditional per-frame sync race as *the* cause (§6; real, fixed, no live effect).
- Startup-only events (the one-time "no controllers connected" sync, the session #1 to #2 recreation).
- **`XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED` gating `is_active`**: the event is purely an
  application notification; Monado recomputes `is_active` live on every `xrSyncActions` from session
  focus and `oxr_input_combine_input()`. A capture showed the event firing correctly for session #2
  with `is_active=false` unchanged 18 minutes later. The `openxr` crate does no caching of action state.
- **Driver-level `xrt_input.active` flag**: `wmr_controller_hp.c` sets every input active once at
  controller creation and never toggles it.
- **`WMR_CONSTELLATION_CONTROLLERS=0`** in Aircar's launcher entry: every reference to that env var
  lives in the WMR driver files, never in `src/xrt/state_trackers/oxr` where attachment, sync and
  `is_active` live.
- **A second `xrAttachSessionActionSets` as a silent failure**: it is a loud
  `XR_ERROR_ACTIONSETS_ALREADY_ATTACHED`, not silent.
- **Session dropping out of `XR_SESSION_STATE_FOCUSED`**: `oxr_action_sync_data` returns the success-class
  `XR_SESSION_NOT_FOCUSED` and zeroes `is_active` when unfocused, and xrizer's `.unwrap()` swallows it,
  so this was a real candidate (xrizer logs every transition at `info!`: "OpenXR session state changed").
  The decisive capture showed FOCUSED throughout.

### Decisive-capture method (reusable for any "every action inactive" symptom)

Launch with ambient env (`vr-launcher.py` inherits it), controllers on first:

```bash
export RUST_LOG=xrizer=debug OXR_DEBUG_BINDINGS=1 XRT_LOG=debug VR_LAUNCH_APPID=1073390
cd ~/vr && python3 vr-launcher.py
```

Worn: about 10 s to settle, then deliberately pull right trigger, left trigger, press right A, 1-2 s
apart, 2-3 repetitions over about 40 s. Then read three things from the same run:

```bash
cp ~/.local/state/xrizer/xrizer.txt ~/aircar-capture-xrizer.txt
cp ~/vr/jack-in-wayland.log ~/aircar-capture-monado.log
# (A) binding resolution, Monado's OXR_DEBUG_BINDINGS trace:
grep -n -A6 '^: Binding main/' ~/aircar-capture-monado.log
# (B) session focus sequence, xrizer's own state log:
grep -n 'OpenXR session state changed' ~/aircar-capture-xrizer.txt
# (C) the is_active reads themselves:
grep -n 'DEBUGBOOLFINAL\|DEBUGPROFILE\|DEBUGVEC1EXPLICIT' ~/aircar-capture-xrizer.txt | grep -v 'is_active=true'
```

(A) points at bindings if no `Bound to:` follows a thrust/reverse/menu binding, the only candidate is
`Rejected! (NO TRANSFORM)`, or `input_count` is 0. (B) points at focus if `Focused` is followed by a
`Visible`/`Synchronized` line with no later `Focused`. If both are clean while (C) is still false, the next
trace is `oxr_input_combine_input`'s `input->active` against the driver's raw `xrt_input` array. Do not
write a fix before the capture names the mechanism (patch 0011 was the cost of theorising first).

## 9. Hazard: `monado-service` launched outside the jack-in wrappers crashes

`VIT_SYSTEM_LIBRARY_PATH`, when unset, defaults to the compiled-in `PREFERRED_VIT_SYSTEM_LIBRARY`
(`t_tracker_slam.cpp`), the **bare name** `"libbasalt.so"`, which only resolves via the system `ld.so`
path. Basalt is built locally (`~/vr/basalt/build/libbasalt.so`) and never `ldconfig`-installed, so
the bare-name lookup fails and HMD creation aborts (the SLAM failure is fatal for the whole WMR HMD, not a
graceful fallback; the service exits with code 0 and the socket is never created):

```
ERROR [t_vit_bundle_load] Failed to open VIT library: libbasalt.so: cannot open shared object file
WARN [wmr_hmd_setup_trackers] Unable to setup the SLAM tracker
ERROR [wmr_create_headset] Failed to create WMR HMD device.
Result: XRT_ERROR_DEVICE_CREATION_FAILED
```

Both `jack-in.sh` and `jack-in-wayland.sh` export the full path. For a manual one-off launch pass
`VIT_SYSTEM_LIBRARY_PATH=$HOME/vr/basalt/build/libbasalt.so` explicitly, or just use a wrapper. Also,
plain `jack-in.sh` (X11/Plasma) refuses to run over SSH ("Not in an X11 session"); `jack-in-wayland.sh`
works headless given the right `DISPLAY` / `WAYLAND_DISPLAY` / `XAUTHORITY` / `DBUS_SESSION_BUS_ADDRESS`.

## 10. Operational notes

- Steam's `srt-logger`-captured `logs/console-linux.txt` (in the Steam installation directory) is a
  reliable place to read `RUST_LOG` output from an xrizer build without a custom log file. It rotates at
  8 MB (`--rotate=8388608`, one `.previous.txt` kept); a chatty `RUST_LOG=xrizer=debug` build fills that
  in minutes at ~90 Hz sync rate, so copy what you need right after the event.
- Killing only the game's `.exe` PID under Steam's Proton/reaper tree can leave orphaned scaffold
  processes (`reaper`, `_v2-entry-point`, `pv-adverb`) that block a clean `-applaunch` relaunch with no
  visible error ("Steam is already running, exiting (command line was forwarded)", no new game
  process). If a relaunch produces no new PID, kill the orphaned tree first.
- Unplugging an Xbox pad mid-session makes Steam pop a "no controller detected" dialog that needs a
  click at the desktop; it cannot be dismissed over SSH. Aircar itself also wants a gamepad connected
  (docs/23), so control that variable before wand A/B tests.
