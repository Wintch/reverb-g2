# 98 -- Auto-standby RESTORE confirmed broken; a stale-DRM-lease bug (2026-09-05)

Findings from a live troubleshooting session (real wearer, repeated Aircar 6dof relaunches),
following up on the presence/auto-standby feature built 2026-09-04
(`~/vr/monado` commit `d1314913f`) and the sensor-wiring round in `docs/97`. No code changes in
this doc's own commit -- this is a findings writeup plus one config change
(`~/vr/presence.conf`, untracked, not in this repo).

## 1. Auto-standby RESTORE: confirmed broken, not just unvalidated

Previous status (per the driver commit's own comment and `docs/97`'s predecessor material): BLANK
(panel off when the presence sensor reports NOT WORN past `PRESENCE_SCREENOFF_MS`) was live-tested
and worked; RESTORE (panel back on when WORN is detected again) was untested with a real wearer,
flagged as "reasonably likely to work, same primitive as blank" but not proven.

Tested twice tonight, with a real wearer actually doffing and re-donning the headset (not a patched
test client): **BLANK fired correctly both times**, at whatever threshold `PRESENCE_SCREENOFF_MS`
was set to (30000ms, then 120000ms) -- exact log line both times:

```
INFO [wmr_hmd_update_inputs] User presence: panel blanked by auto-standby (<N> ms NOT WORN)
```

**RESTORE never fired, either time.** After the blank, no further `User presence: WORN` log line
ever appeared for the rest of that session, even minutes after the wearer had put the headset back
on and well past any reasonable debounce window. The render pipeline stayed healthy throughout
(steady ~90Hz pacer log, no crash, no coredump) -- this rules out a session/process death as the
cause. Not root-caused at the code level tonight: unclear whether the proximity sensor itself stops
reporting after the panel is commanded off, or whether `wmr_hmd_update_inputs()` stops evaluating
new WORN transitions once it has already fired the blank once per session. Needs real driver
instrumentation (temporary logging of every raw proximity read, not just committed transitions) to
tell those two apart.

**Consequence, applied immediately**: `~/vr/presence.conf`'s `PRESENCE_ENABLE` set back to `0`
(disabled) for now. This feature is not safe for real guest use in its current state -- a guest
handing the headset back and forth would get stuck on a dark panel with no supported recovery path
short of an operator manually killing and relaunching Monado. Re-enable only after RESTORE is
actually fixed and validated, not just re-tested against the same bug.

## 2. A second, separate bug: stale DRM lease after an out-of-band panel activation

Independent of the RESTORE bug above, running `./scripts/panel.py activate` by hand (its own
process, separate from Monado, talking directly to the companion HID device) can report success --
and even produce the real HP splash logo -- while Monado's own DRM lease on the video connector
stays stale/unclaimed, so no actual game content ever reaches the panel. Confirmed live: after this
happened, `/sys/class/drm/card*-DP-*` stayed `disconnected` throughout, even though `panel.py`'s own
log said `full activation + screen on` and the logo was genuinely visible for a moment.

This matches an existing documented case in `docs/22-cable-connector-diagnosis.md` (step 4, point
4: "logo on, panel off mid-session... that's a stale DRM lease, not a hardware fault") -- this
session reconfirms it live and specifically ties it to the RESTORE-bug workflow (an operator
reaching for `panel.py activate` as a recovery step after a failed auto-restore is exactly the
situation that triggers it). **Fix**: kill `monado-service`, remove the stale IPC socket
(`rm -f /run/user/1000/monado_comp_ipc`), and relaunch fresh. Re-running `panel.py activate` again
does not fix it, no matter how many times.

`jack-in-wayland.sh` also has its own failure-marker safety mechanism (T074/T183) that blocks
relaunch after a recorded failure until explicitly cleared with `--force up` -- confirmed this
worked exactly as designed tonight (stopped a blind retry loop after a genuine hardware fault, see
`docs/22`'s 2026-09-05 entry for that half of the same night). `down` never touches this marker.

## 3. Practical operator sequence for "headset went dark and won't come back"

Distilled from tonight, cheapest/most-likely-cause first:

1. Check `~/vr/presence.conf` -- if `PRESENCE_ENABLE=1` and a while has passed with nobody wearing
   it, this is almost certainly the auto-standby BLANK (expected), not a fault. Put the headset on;
   if it doesn't come back within a few seconds, RESTORE is broken (see §1) -- proceed below rather
   than waiting longer, it will not recover on its own.
2. Run `./scripts/panel.py activate` once and look for the HP logo (per `docs/22` step 0). Logo
   visible but the game view never follows = stale DRM lease (§2) -- kill `monado-service` + remove
   the IPC socket + relaunch. No logo at all = possible genuine hardware fault -- go to `docs/22`'s
   full decision tree, starting at step 0, and do NOT assume a USB-C flip or a PC-end reconnect will
   help without first matching the exact symptom table there.
3. If `jack-in-wayland.sh` refuses to launch citing a recorded previous failure, that's the
   T074/T183 safety marker, not a new problem -- fix the underlying cause first, then
   `jack-in-wayland.sh --force up` to clear it and launch.
