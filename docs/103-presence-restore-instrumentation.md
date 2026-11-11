# 103 -- Presence auto-standby: why RESTORE failed, the final design, and the lease-kill trap

Everything we know about the G2 presence sensor and Monado's auto-standby feature
(`WMR_USER_PRESENCE*`, `XR_EXT_user_presence`): the state machine, four independent root
causes found in sequence, the design that came out of them, what real Windows does instead, and
the operator recovery sequence for "the headset went dark". The driver work lives on the `lab-full`
branch of the Monado checkout (`src/xrt/drivers/wmr/wmr_hmd.c`/`wmr_hmd.h`); only the earliest
pieces are in `patches/monado/` (0075 presence wiring, 0087 asymmetric debounce, 0116 stale notice).

## 0. Where it stands (read this first)

| Layer | Status |
|---|---|
| Presence detection (`XR_EXT_user_presence`, debounce, motion rescue) | Works; live-validated with a wearer (motion-primary WORN commits in ~250 ms). |
| Evaluation without an OpenXR client | Fixed: the decision runs on the driver's read thread. |
| Auto-standby HID **blank** of the panel | **Disabled by default** (`WMR_USER_PRESENCE_BLANK_PANEL=0`): a real screen-off kills the DRM lease (§6). |
| RESTORE after a blank (screen reassertion + fresh fd) | Works when blanking is enabled, but moot while the kill switch is off. |
| Windows/Oasis reference | Uses no HID Feature-report toggle at all (§7). |

Do not re-enable the blank until the compositor can re-acquire a lost lease.

## 1. The feature and its state machine

The companion HID device (`03f0:0580`) carries a proximity/IPD packet (`WMR_CONTROL_MSG_IPD_VALUE`)
that Monado turns into `XRT_INPUT_GENERIC_HEAD_DETECT`. The decision logic (`wmr_hmd_presence_tick()`):

```
DON_MS       = 250     continuous "worn" reading before WORN commits
DOFF_MS      = 1000    continuous "not worn" reading before NOT WORN commits
SCREENOFF_MS = 120000  committed NOT WORN before the panel is blanked (presence.conf default)
REASSERT_MS  = 15000   re-arm interval while blanked (§3)
```

- Timeline of a forgotten headset: ~1 s to commit NOT WORN, then the grace period. Of the ~121 s the
  panel stays lit, ~120 s are `SCREENOFF_MS` and ~1 s is detection; the lever for protecting the
  panel is `SCREENOFF_MS`, not detection speed. An IMU "picked up" classifier was evaluated and
  rejected for that reason (it cannot touch the grace period and is fragile).
- The state machine itself is clean: there is no one-shot latch, `committed` is re-derived on
  every call and `screen_off_by_presence` is cleared the instant `committed` goes true. RESTORE
  therefore never failed for logic reasons; it failed for the input reasons below.
- The proximity packet is **change-driven** (code comment: "This message is CHANGE-driven"), not a
  stream, and arrives irregularly (2 s to 100+ s apart in captured logs). A passive startup packet
  always arrives; a quiet channel is not by itself an anomaly.
- The read thread runs at ~250 Hz, measured from the 2 s heartbeat (`calls` delta ~506), matching
  the IMU packet rate (1000 Hz / 4 samples per packet). An earlier "~750 Hz" figure was wrong.
- Presence needs `WMR_USER_PRESENCE=1`. `jack-in-wayland.sh` also reads `~/vr/presence.conf`
  (`PRESENCE_ENABLE`, `PRESENCE_SCREENOFF_MS`); an ambient `WMR_USER_PRESENCE_SCREENOFF_MS` wins
  over the conf file. The conf file is only read at `up`; changing it needs `down` + `up`.

### The `PRESENCE_ENABLE=0` bypass (fixed in `jack-in-wayland.sh`)

`PRESENCE_SCREENOFF_VAL` was computed independently of `PRESENCE_ENABLE`: exporting
`WMR_USER_PRESENCE=1` (just to get telemetry) while the conf said `PRESENCE_ENABLE=0` still applied
the conf's `PRESENCE_SCREENOFF_MS=120000`, and a Dali session went dark after 120 s of
"not worn" (log: `panel blanked by auto-standby (120000 ms NOT WORN)`, then
`vk_swapchain_present: VK_ERROR_UNKNOWN`, `_lease_finished: Lease has been closed`). Fix:

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

Ambient `WMR_USER_PRESENCE_SCREENOFF_MS` still wins outright; telemetry (`WMR_USER_PRESENCE`) is
independent of the auto-standby side effect. Live-validated: `WMR_USER_PRESENCE=1`, headset
untouched for 2:30 with `PRESENCE_ENABLE=0` produced no blank and DP stayed connected. To check
what a running service got: `tr '\0' '\n' < /proc/<pid>/environ | grep SCREENOFF`.

## 2. Root cause 1: the companion channel goes dead after BLANK

**Symptom.** BLANK fired every time (`User presence: panel blanked by auto-standby (<N> ms NOT
WORN)`); RESTORE never did, even minutes after a real re-don. Rendering stayed healthy (steady
~90 Hz pacer), so the session was alive.

**Instrumentation** (`WMR_PRESENCE_DIAG=1`, default off): an unconditional per-packet log
(`PRESENCE-DIAG raw packet #N: proximity=.. ipd=..`) and a 2 s heartbeat from the presence
logic (`update_inputs calls=.. raw_packets=.. raw_proximity=.. candidate=.. committed=..
screen_off_by_presence=.. last_packet_age_ms=..`). Reading it: `calls` climbing with `raw_packets`
stalled = channel dead; `raw_packets` climbing with `committed` stuck = logic bug; both stalled =
nothing is polling.

**Result (three independent reproductions, button-press-timed with an Xbox pad marker).** After
the session had auto-blanked, `raw_packets` stayed frozen (1 packet at launch, none after) across
real don/doff/re-don cycles while `calls` climbed at ~90-250/s. Before any blank, the same channel
reported 5 consecutive real transitions correctly. So: the proximity channel works for ordinary
transitions and fails to report a fresh WORN once the session is blanked. Hardware was ruled out
(`panel.py activate` showed the HP logo; a plain session showed real image).

**Ruled out: a feature-report poll of the proximity value.** Patch 0090 already measured that the
device does not answer that query and each attempt blocks 1.4-5.0 s (usbhid timeout) inside the
shared run loop that also reads IMU and cameras, which relocates the wearer. That is why
`WMR_COMPANION_RECONNECT_RESYNC` is off by default.

## 3. The fix that works: re-send the full activation on a fresh fd

A/B with the existing `scripts/panel.py activate` while blanked: **0/1 RESTORE without it, 2/2 with
it** (a second block of manual pairs: 3/3 with, 2/2 without failing). The activate sends the
companion's screen-enable command, not a proximity read, and returns in <1 s. Wiring it into the
driver took four failed live attempts, each disproving one hypothesis:

1. Reassert inside the RESTORE branch: dead code, because `committed` only turns true from a fresh
   packet, which is exactly what never arrives.
2. One-shot reassert at the blank transition: the "wake" decays; a don ~100 s later got nothing.
3. Periodic re-arm every 15 s over the shared handle (`wh->hid_control_dev`): still nothing, and
   each call blocked the IMU/camera loop ~4-5 s (`hid_lock` contention).
4. Periodic re-arm on a fresh, independent hidraw fd (`wmr_hmd_reassert_reverb_fresh_fd()`):
   ~368 ms per call (matches `panel.py`) and no loop stall, but still nothing.

**Root cause, found by diffing byte-for-byte against `panel.py`'s printed output.** The 0x50 loop
and 0x09/0x08/0x06 identification reads matched exactly; the difference was structural.
`panel.py activate()` sends the trailing screen-on `HIDIOCSFEATURE({0x04, 0x01})` on the **same
fd**, right after the identification reads, before closing. All four attempts had split that
atomic sequence across two connections at two different times.

**Final form**: `wmr_hmd_reassert_reverb_fresh_fd()` replicates `panel.py activate()` in order on
one fresh fd (300 ms sleep, 4x (0x50 send + get + 10 ms), the three identification reads, then
`{0x04, 0x01}`, close), exposed as the Reverb family's `reassert_func` (NULL for Odyssey+). It
runs at the blank transition and then every `WMR_PRESENCE_REASSERT_INTERVAL_MS` (15000) while
blanked; opt out with `WMR_PRESENCE_RESTORE_REASSERT=0`. Later fixes in the same family:

- The RESTORE call itself must also use `reassert_func`, not the bare shared-handle
  `screen_enable_func`: that send reported success but sometimes left the panel dark (a bare
  `panel.py activate` after a long off stretch could also fail).
- Screen-off is sent over a fresh fd too (`wmr_hmd_screen_off_reverb_fresh_fd()`).
- The periodic reassert ends in a real screen-ON, so it must be followed by a re-blank, or every
  poke relights the backlight permanently. Each poke still flashes the HP logo briefly (accepted).
- Validation: 3 consecutive fully automatic blank -> WORN -> restored -> NOT WORN cycles, then
  through the real `presence.conf` path at the real 120 s threshold.

**Limit of the effect.** Later in the same night a blanked channel stayed silent for 228+ s even
with the 15 s reassert firing on schedule the whole time. The "reassert wakes the channel" result
is real but not reliable, so the driver does not depend on it alone (motion rescue, §5).

## 4. Root cause 2: evaluation was dormant without an OpenXR client

`wmr_hmd_update_inputs()` only runs while a client has an active, frame-synced session. When the
presence decision lived there, then with no client (or after the client exited, once the
compositor idled) there was no blank, no restore, no log line: a lit panel stayed lit forever.
Heartbeats appear the moment a client connects and vanish when it is gone.

**Fix**: the whole decision moved to `wmr_hmd_presence_tick()`, called from `wmr_run_thread()` (the
always-on thread that already calls `control_read_packets()` and the controller keepalives).
`update_inputs` now only reports the already-committed state to the XRT input system. A new
`presence_lock` protects the shared fields. Validated with zero clients ever connected: heartbeat
climbing, blank at the test threshold.

**Operator rule: if presence heartbeats or transitions go missing, check for an active OpenXR
client (or an old driver build) before suspecting the driver.** A test client that exits (e.g.
`play360.sh -t 60`) stops presence evaluation on old builds; use a long `-t` for old-build tests.

## 5. Root cause 3: debounce gaps (stray packet, then no packet at all)

**3a. A single stray packet relit the panel.** The wall-clock debounce measures time since the
candidate value last *changed*, not how many independent packets reported it. With packets 2-100+ s
apart, one stray packet flipping the byte to 1 satisfied `DON_MS` in a few hundred ms of real time
with zero corroboration. In a captured session with the headset untouched on a desk, 4 of 4
blank -> `WORN (held 253 ms)` -> `panel restored` -> next packet `NOT WORN` cycles had exactly this
shape. Fix: `WMR_USER_PRESENCE_DON_CONFIRM_PACKETS` (default 2, floor 1 = old behavior) requires N
independent packets (counted via `presence.last_update_ns` advancing) in addition to `DON_MS`,
WORN direction only.

**3b. That alone left a real don uncommitted.** A real wearer donned; `candidate=1 committed=0`
held 43+ s because no second packet arrived, and the next packet (caused by the session teardown)
contradicted it. Fix: IMU motion corroboration plus a bounded timeout:

- `WMR_USER_PRESENCE_DON_MOTION_RAD_S` (default 0.10): peak `|angular velocity|` since the
  candidate flipped (from `wh->fusion.last_angular_velocity`, refreshed every tick) satisfies
  confirmation. 0.10 is Monado's own `STILL_GYRO_RAD_S` (`m_imu_3dof.c gyro_bias_auto`); this unit
  at rest measures 0.011-0.016 rad/s, 6-9x below it. Real don peaks observed: 0.104, 0.867, 0.977,
  1.106, 0.860 rad/s.
- `WMR_USER_PRESENCE_DON_CONFIRM_TIMEOUT_MS` (default 4000): hard ceiling, commits on wall clock
  alone. This bounds latency, it is **not** a noise filter: a stray byte that survives 4 s
  uncontradicted still falsely commits. The original relight bug is bounded, not eliminated; the
  commit log prints which path fired (`via packets|motion|timeout`).

**3c. The corroboration never ran when no candidate existed.** All of 3b lives inside
`if (candidate != committed)`; with the channel silent after a blank the proximity byte never
changes, so no candidate is ever created and nothing executes. Fix: a per-tick `worn_signal` that
replaces the raw byte as the candidate driver:

1. Raw byte says worn: always wins.
2. Raw byte says not worn (or never reported) **and** the channel has been silent for
   `WMR_USER_PRESENCE_MOTION_RESCUE_STALE_MS` (30000): if a sustained motion run is in progress,
   assert worn; otherwise HOLD the current candidate (never force false).
3. Raw byte says not worn and the channel is fresh: trust the sensor.

A "run" starts when magnitude crosses `WMR_USER_PRESENCE_MOTION_PRIMARY_RAD_S` (0.10), tolerates
gaps up to `WMR_USER_PRESENCE_MOTION_GAP_MS` (250), and counts as sustained after
`WMR_USER_PRESENCE_MOTION_SUSTAIN_MS` (500). Rejected alternatives: a bare peak (cannot tell a
knock from a don) and a leaky integrator (no waveform data to size the constants). Setting all four
to 0 reproduces the 3b behavior. Commit log line:
`User presence: WORN (raw proximity sensor value 0 [stale], held 254 ms, 1 confirming packet(s),
motion peak 0.31 rad/s, via motion)`.

**Why motion never drives NOT WORN.** Stillness while worn (a seated cockpit, a 360 photo) looks
exactly like stillness while resting, so a motion-quiet doff rule would turn calm VR use into
spurious doffs. DON and DOFF are asymmetric; the DOFF path stays pure wall-clock. Cost: if the
channel goes silent while worn and the headset is later removed, `raw_worn` stays true until the
channel speaks again (pre-existing, not worsened).

**Live validation.** First live use: two of three WORN commits happened while the proximity byte
was silent/stale and motion alone committed WORN in ~250 ms each; no noise relight, no multi-second
hang. Not validated: ambient-vibration stress (door slam, fan on the table), the 250/500 ms
constants against real gesture waveforms, a long still-while-worn soak on the rescue path.

## 6. Root cause 4: a real screen-off kills the DRM lease

**Symptom.** Within ~5 s of `hello_xr` connecting and `BEGIN_SESSION`, every launch:
`vk_swapchain_present: VK_ERROR_UNKNOWN` then `_lease_finished: Lease has been closed`. The
companion HID keeps working (`panel.py activate` shows the logo) but no video returns. Reproduced
100% headless, surviving `down`+`up` and a reboot.

**Bisection** (rebuild + test at each point): `c44ba4a23` (RESTORE fix) clean; `754beed30` (move
the presence decision to the read thread) **reproduces**; HEAD reproduces. Mechanism for why the
move exposed it: before, the NOT WORN countdown could only advance from client-gated
`update_inputs`, so the first blank could never precede a client's first content; afterwards it
runs from driver init and a 15 s countdown completes before a slow-loading client connects.

**Three wrong mechanisms excluded** (each rebuilt and live-tested, all still crashed): gating the
first blank on a client having connected (one `update_inputs` call site runs inside
`xrBeginSession` itself); narrowing `presence_lock` so no blocking I/O runs under it; moving the
~370 ms HID I/O to a detached thread (`presence_action_lock` + join barrier in destroy). A 90 s
threshold (55+ s of healthy rendering before the first blank) also crashed. **The isolating test:**
`WMR_PRESENCE_RESTORE_REASSERT=0`, so the tick did nothing but one lone screen-off: still crashed.
A real, effective panel screen-off is sufficient to drop HPD and the lease by itself.

The two hardening changes (narrow lock scope, off-thread HID I/O) were kept: they remove a real
cross-thread hazard and stop a ~370 ms HID transaction starving the IMU loop.

**Why earlier tests looked fine.** At `c44ba4a23` the blank still used the shared-handle
`screen_enable_func(false)`, which the driver's own comments document as silently swallowed while a
client is rendering. A first claim that the fresh-fd screen-off commit made blanking newly
reliable was checked and is wrong (the crash already reproduces at `754beed30`, before that commit
exists). The shift is the move to the read thread; the exact `hid_lock` contention difference was
not instrumented, so that account is inferred.

**Fix.** `WMR_USER_PRESENCE_BLANK_PANEL` (default OFF) gates only the destructive action (the real
screen-off and the `screen_off_by_presence` transition). Debounce, motion logic and
`XR_EXT_user_presence` keep working; RESTORE and the periodic reassert simply have nothing to do.
No script or `presence.conf` change is needed. Validated with a real wearer: playlist playback
across clip transitions with zero `VK_ERROR_UNKNOWN`/`Lease has been closed`. The real follow-up
(not done) is lease recovery in the compositor: `comp_window_direct_wayland.c`'s
`_lease_finished` only sets `finished = true` and closes the fd (a literal TODO), nothing
re-requests a lease, and the fake-vblank pacer keeps producing "Delivered frame" lines for a
dark panel.

## 7. Windows/Oasis ground truth (USBPcap)

Two captures with the same G2 on Windows 11 (SteamVR + Oasis driver): motion standby (~717 s,
485k packets) and proximity standby (~160 s, 162k packets). Method note: USB device addresses are
recycled over a long capture (address 5 was the Realtek audio device at t=1 s and the HP companion
at t=285 s), so cross-reference `usb.idVendor/idProduct` sightings with timestamps before filtering
by address.

1. **Zero HID Feature-report SET_REPORT requests in either capture**
   (`usb.bmRequestType==0x21 && usb.setup.bRequest==9 && usb.setup.wValue` in 0x0300-0x03ff).
   Windows does not send the `{0x04,0x00}`/`{0x04,0x01}` toggle Monado's auto-standby uses.
2. The motion capture shows the companion doing a full re-enumeration (GET DESCRIPTOR device/
   config, SET CONFIGURATION, SET_IDLE, HID report descriptor) three times (t~283, ~317, ~365 s),
   followed ~0.8 s later by the HoloLens Sensors interface. That looks like a port-level reset,
   not an in-band command. Not proven to be standby-specific (several manual wake attempts were made).
3. The proximity capture shows only the startup enumeration and no later event.

Reading: Windows' lighter standby is most plausibly a compositor-side render-black (backlight stays
lit; only a full SteamVR exit darkens the panel), with a device-level reset reserved for session
end. That supports treating render-side dim/black as the "worn but idle" mechanism and the HID blank
as the risky one (§6). A capture bracketing a single time-marked standby-then-wake would settle it.

## 8. Stale DRM lease after an out-of-band activation (merged from the old doc 98)

Independent of everything above: `./scripts/panel.py activate` (its own process, talking straight
to the companion) can report success and even light the HP splash while Monado's DRM lease stays
stale, so no game content reaches the panel. Signature: `/sys/class/drm/card*-DP-*` stays
`disconnected` although the log says `full activation + screen on`. This is the stale-lease case of
`docs/22-cable-connector-diagnosis.md` ("logo on, panel off mid-session"). Re-running `activate`
never fixes it. **Fix**: kill `monado-service`, `rm -f /run/user/1000/monado_comp_ipc`, relaunch.

`jack-in-wayland.sh` also has a failure marker that blocks relaunch after a recorded failure until
cleared with `--force up` (`down` never touches it); it stops blind retry loops after a genuine
hardware fault.

### Operator sequence for "headset went dark and won't come back"

Cheapest/most-likely cause first:

1. Check `~/vr/presence.conf`. With `PRESENCE_ENABLE=1`, a blank-capable build and nobody wearing
   the headset, a dark panel is the expected auto-standby BLANK. Put it on; if it does not come
   back within a few seconds, do not wait longer (RESTORE can fail, §2); continue below. With the
   default kill switch off (`WMR_USER_PRESENCE_BLANK_PANEL`), auto-standby never blanks.
2. Run `./scripts/panel.py activate` once and look for the HP logo (`docs/22` step 0). Logo but no
   game view = stale lease: kill `monado-service`, remove the IPC socket, relaunch. No logo = a
   possible genuine hardware fault; follow `docs/22` from step 0 and do not assume a USB-C flip or
   PC-end reconnect helps without matching its symptom table.
3. If `jack-in-wayland.sh` refuses to launch citing a recorded failure, fix the underlying cause
   first, then `jack-in-wayland.sh --force up`.

## 9. Knobs reference

| Variable | Default | Role |
|---|---|---|
| `WMR_USER_PRESENCE` | 0 | Surface the proximity sensor as `XR_EXT_user_presence` and run the logic. |
| `WMR_USER_PRESENCE_SCREENOFF_MS` | 0 / conf | Grace period before a blank (needs `BLANK_PANEL`). |
| `WMR_USER_PRESENCE_BLANK_PANEL` | 0 | Allow the real screen-off (kills the lease, §6). |
| `WMR_USER_PRESENCE_DON_MS` / `_DOFF_MS` | 250 / 1000 | Wall-clock debounce. |
| `WMR_USER_PRESENCE_DON_CONFIRM_PACKETS` | 2 | Independent packets required for WORN. |
| `WMR_USER_PRESENCE_DON_MOTION_RAD_S` | 0.10 | Motion peak that corroborates a candidate. |
| `WMR_USER_PRESENCE_DON_CONFIRM_TIMEOUT_MS` | 4000 | Latency bound (weak noise filter). |
| `WMR_USER_PRESENCE_MOTION_PRIMARY_RAD_S` / `_SUSTAIN_MS` / `_GAP_MS` / `_RESCUE_STALE_MS` | 0.10 / 500 / 250 / 30000 | Motion as an independent WORN signal when the channel is silent. |
| `WMR_PRESENCE_RESTORE_REASSERT` / `WMR_PRESENCE_REASSERT_INTERVAL_MS` | 1 / 15000 | Fresh-fd keep-alive while blanked. |
| `WMR_PRESENCE_DIAG` | 0 | Per-packet log and 2 s heartbeat. |

Values for a quick dev loop: `WMR_USER_PRESENCE_SCREENOFF_MS=5000` (above the 1 s DOFF floor, ~96%
less needless lit time than 120000) via the ambient env, leaving `presence.conf` alone.

## 10. How to test it

```
WMR_USER_PRESENCE=1 WMR_USER_PRESENCE_SCREENOFF_MS=15000 WMR_PRESENCE_DIAG=1 \
    ./scripts/jack-in-wayland.sh up
```

- Keep a client alive for old builds (`sleep 1800 | hello_xr ...`, or `play360.sh -t 1800`);
  `play360.sh` wraps the player in `timeout` (default 300 s). Do not reuse one long-lived
  `monado-service` across many client connect/kill cycles: a fresh client can hang after
  `vkCreateDevice`; restart the service.
- Time the don/doff with button presses logged to wall-clock timestamps and correlate with the log.
- Pass criteria: `[stale] ... via motion` WORN within ~1 s of a don after a silent channel; no
  relight over several minutes of an untouched headset; `grep -c "VK_ERROR_UNKNOWN\|Lease has been
  closed"` is 0.
- Known harmless build warnings: a `control_read_packets` sign-compare and an `int` overflow on
  `30 * U_TIME_1S_IN_NS` (see `docs/147-full-code-review-2026-10-12.md`: the stale-channel notice
  was dead code until patch 0116). Rebuild the whole tree, not one target, or `libopenxr_monado.so`
  goes stale.

## 11. Open items

- Lease recovery after a real screen-off (compositor side); until then keep the blank off.
- Whether 0.10 rad/s / 500 ms / 250 ms hold against ambient vibration and real gesture waveforms.
- Whether the 4 s timeout path ever falsely commits in practice (watch for `via timeout` with a
  low motion peak on an untouched headset).
- The DOFF direction is untouched; revisit only if a spurious mid-worn doff or a stuck-worn doff
  is observed.
- A Windows capture bracketing one time-marked standby/wake cycle.
