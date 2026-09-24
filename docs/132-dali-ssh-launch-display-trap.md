# 132 — SSH-launched Dalí: pre-exporting `WAYLAND_DISPLAY` silently skips `gui_env`'s DISPLAY fallback

**Status: RESOLVED, worn-confirmed 2026-09-23.** Two remote-launch mistakes fixed in the same
session, neither in the scripts themselves — both were operator-side environment handling when
driving `vr-launcher.py` over SSH. Ends with a clean 6dof, controller-off Dreams of Dali (appid
591360) session, wearer verdict "anduvo bien" (went well).

## Setup

Remote launch of Dreams of Dali over SSH into iashur, head-only 6DoF (wearer confirmed no
controllers needed for this session before anything started — see the standing rule in
`feedback_confirm_controllers_before_vr_test`). `WMR_CONSTELLATION_CONTROLLERS=0` is already the
title's shipped profile default (`vr-launcher.py` `TITLE_PROFILES["591360"]`), so this matched
without any override.

## Mistake 1 — tracking mode is a positional arg, not an env var

`vr-launcher.py`'s tracking mode is `sys.argv[2]`, defaulting to `"3dof"` when absent:

```python
MODE = sys.argv[1] if len(sys.argv) > 1 else "1"
TRACKING = sys.argv[2] if len(sys.argv) > 2 else "3dof"
```

There is no `VR_TRACKING` env var. A launch shaped like `VR_LAUNCH_APPID=591360 python3
vr-launcher.py` silently brings Monado up in 3dof — confirmed in `jack-in-wayland.log`
("Starting Monado (action up, mode 1, tracking 3dof)") even though the demo-day default for this
title is 6dof (`project_demo_day_prep`). No error, no warning: the run looked completely healthy,
it was just tracking the wrong thing. Fix: always pass tracking explicitly —
`python3 vr-launcher.py 1 6dof`.

## Mistake 2 — pre-exporting `WAYLAND_DISPLAY` disables the script's own DISPLAY fallback

`vr-launcher.py` already has a documented guard for exactly this class of problem (its own
comment cites a 2026-09-03 incident where an Aircar capture lost the game the same way):

```python
if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
    try:
        import gui_env
        _gui = gui_env.get()
        for _k in ("XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"):
            if _gui.get(_k):
                os.environ.setdefault(_k, _gui[_k])
    except Exception as _e:
        print(f"(gui_env not applied: {_e} -- fine on an interactive desktop session)")
```

The guard only fires when **both** `WAYLAND_DISPLAY` and `DISPLAY` are unset. Following
`feedback_detached_hardware_runs`'s "export gui_env and verify each up" guidance too literally,
the first attempt this session pre-exported `WAYLAND_DISPLAY=wayland-0` by hand before invoking
the launcher. That alone satisfied the guard's condition (`WAYLAND_DISPLAY` was set) and skipped
the whole `gui_env` block — so `DISPLAY` was never resolved. Monado itself came up fine (it does
its own, separate `gui_env` resolution inside `jack-in-wayland.sh`), but the `steam -applaunch
591360` child inherited no `DISPLAY` at all and died immediately:

```
Unable to open X11 display, exiting
Unable to open X11 display, exiting
```

No coredump, no OOM kill, no crash signature — `~/.steam/steam/logs/console_log.txt` just stops
after "Verification complete" and the process list goes empty within a couple of seconds. Easy to
mistake for a hang if you're not tailing the actual Steam log.

**Fix:** don't pre-export `WAYLAND_DISPLAY`/`DISPLAY` for `vr-launcher.py` at all — leave both
unset and let its own `gui_env.get()` resolve them live from `mutter-x11-frames`'
`/proc/<pid>/environ`, the same way `jack-in-wayland.sh` already does for Monado. Only
`XDG_RUNTIME_DIR` needs setting ahead of time for a non-interactive SSH shell. Verified directly:

```
$ python3 -c 'import gui_env; e=gui_env.get(); print(e["DISPLAY"], e["XAUTHORITY"])'
:1 /run/user/1000/.mutter-Xwaylandauth.HJY0V3
```

The takeaway generalizes past this one launcher: `feedback_detached_hardware_runs`'s "export
gui_env" advice means *let the script's gui_env.py run*, not *pre-seed display vars by hand* —
seeding only one of the two vars a script checks can disable a fallback that was written to
handle exactly the missing-env case.

## Recovery sequence used

1. `jack-in-wayland.sh down` — clean teardown, confirmed socket removed
   (`/run/user/1000/monado_comp_ipc`), no stale `monado-service` left running, no
   `.jack-in-failed` marker.
2. Waited for USB settle (per `feedback_monado_process_hygiene`).
3. Relaunched inside `tmux` (so the session could be watched live instead of guessed at
   blind through a detached `nohup`) with `unset WAYLAND_DISPLAY DISPLAY` first, then
   `VR_LAUNCH_APPID=591360 WMR_USER_PRESENCE=1 python3 ~/vr/vr-launcher.py 1 6dof`.
4. Confirmed via `jack-in-wayland.log`: OpenXR `xrGetSystem` selected `HP Reverb Virtual Reality
   Headset G2` as the head device, SLAM 6dof ticking normally (`predict_pose` anchor ages in the
   50–90 ms range, `wmr_hmd_presence_tick` toggling WORN/NOT WORN with real motion — the wearer
   was already handling the headset by this point). `DreamsOfDali.exe` alive and CPU-active
   shortly after.
5. Wearer confirmed good in-headset.

## Side note, not fixed here — flag for next OpenVR launch

The `steam -applaunch` path for this title runs `vrenv.sh`, which calls `vrpathreg.sh adddriver`
for `MixedRealityVRDriver` and the Oasis WMR driver as a side effect of Steam's own VR
environment setup — even though Dalí itself is OpenXR-native and talks to Monado directly, never
touching SteamVR. This is the known trigger described in `project_openvr_vrpath_priority_trap`:
any SteamVR-touching activity can silently reorder `openvrpaths.vrpath` ahead of xrizer, breaking
OpenVR titles until a full Steam restart with the runtime order fixed. Not addressed in this
session — fixing it would have required a Steam restart that would have killed the live Dalí
session. **Check `openvrpaths.vrpath` ordering before the next OpenVR (not OpenXR-native) title
launch.**
