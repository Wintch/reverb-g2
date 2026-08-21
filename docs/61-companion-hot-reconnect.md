# 61 — Surviving the USB2 storm: companion hot-reconnect

**Status: built, measured, 13/13 forced re-enumerations recovered (2026-08-19, T227). Patch
`patches/monado/0090`. Wearer verification still pending.**

## Why this exists

[docs/60](60-windows-usb-storm-control.md) settled who owns the USB2 storm: **the link does.**
Windows takes 3.47 branch drops per minute with ~3 s outages on the same cable, the same
headset and the same machine, while five titles play and the only thing the wearer notices is
audio cutting out. We take the same drops and lose panel control, IPD and
`XR_EXT_user_presence` for the rest of the session.

That difference is not tolerance of a broken handle. It is that the Windows stack **re-opens
the device**. This is that, for us.

## The mechanism, and why the error counter was lying

The companion is `03F0:0580` on the headset's USB2 branch, opened once at startup as a hidraw
node and read from the shared WMR read thread.

**A re-enumeration invalidates that fd permanently.** The kernel tears down the hidraw device
and creates a new one — measured live, the node genuinely moves (`hidraw6` → `hidraw7` →
`hidraw6` …), and it can also come back under the *same name* while still being a different
device. Either way, the fd Monado holds refers to something that no longer exists, every
subsequent `os_hid_read` returns `-1`, and no amount of retrying will ever succeed.

This reframes a number this project has quoted for months. `companion_errors` climbing to
472175 in a session (T188) is **not** a measurement of the storm — past the first
re-enumeration it is a measurement of our own polling of a corpse. It also explains the
observation in T183 that never fitted: read failures continuing at 400-600/s *during stretches
where `lsusb` already showed the branch back at 5/5*. The device was back. Our handle was not.

Everything riding the channel died with it, for the rest of the session:

| what | symptom the project recorded |
|---|---|
| panel control | screen-off at shutdown silently does nothing; a companion re-enumeration after service start left the panel dark until relaunch |
| IPD value | frozen at its pre-outage reading |
| proximity → `XR_EXT_user_presence` | "presence freezes when the storm kills the channel" (T224/T225) |

The only known cure was relaunching the service.

## What patch 0090 does

In `wmr_hmd.c`, on the same read thread:

1. **Notice.** The first failed companion read stamps `companion_dead_since_ns`. A channel
   silent for **500 ms** has stopped looking like a hiccup.
2. **Find the device again.** Scan `/sys/class/hidraw/*/device/uevent` for the companion's
   `HID_ID`, preferring the node whose sysfs path goes through USB interface `:1.0`. The
   VID/PID come from the prober device recorded at creation, **not** a G2 constant — the
   companion's ids differ per WMR headset, and hardcoding ours would have quietly disabled
   recovery for every other model.
3. **Swap.** Open the new node and exchange `hid_control_dev` under `hid_lock`, closing the
   stale handle inside the same critical section. `HID_SEND`/`HID_GET` now evaluate the handle
   *inside* the lock, so no caller can be holding a pointer the reconnect is about to close.
4. **Re-assert the panel.** A companion power cycle is exactly the case where screen-enable is
   lost, and a panel dark until relaunch is the historical symptom. This is the same recovery
   `wmr_hmd_activate_reverb` already performs for the same reason.
5. **Try to re-sync presence.** The proximity message is *change-driven*, so after an outage
   the driver can sit on a pre-outage value indefinitely — if the wearer doffed during the
   dropout, presence would be wrong until they moved the headset again.

Retries are every **250 ms** while dead, and both thresholds are **time**, not error counts:
the error count accrues at whatever rate the shared read loop happens to be running, so a count
threshold would make recovery latency depend on unrelated load.

Knobs: `WMR_COMPANION_RECONNECT=0` restores the old behaviour for an A/B;
`WMR_COMPANION_RECONNECT_SCREEN=0` keeps the reconnect without the panel re-assert.

## Measured

`scripts/usb-reset-device.py` issues `USBDEVFS_RESET`, which reproduces the fault on demand —
no root needed (group `plugdev` suffices), so the lab agent can run it unattended.

Session of 2026-08-19, service up on a real G2, 6dof, forced re-enumerations:

| | before 0090 | with 0090 |
|---|---|---|
| recoveries | **never** (relaunch only) | **13 / 13** |
| time channel dead | rest of session | **3.34 s** (3.341-3.352, n=13) |
| companion read errors | unbounded (472175 in 17 min, T188) | **9 for 7 outages** |
| failed opens | — | **0** |
| service / DP lease / tracking | — | survived every one |

The 3.34 s is not our retry loop: halving the retry interval from 1000 ms to 250 ms did not
change it, and every attempt before the successful one failed to *find* the device rather than
to open it (`0 failed opens`). It is how long the kernel takes to make the device available
again after a reset. A natural storm outage is ~2.9 s, so expect the same order.

**We reopen within one retry interval of the device coming back.** That is the honest claim.

## Side-finding, and it is not small

Across the same run: **13 reconnects, 11 camera-clock recoveries, 10 IMU-clock recoveries** —
essentially one clock-domain disturbance per companion re-enumeration, on the USB3 stream,
which never dropped. The headset's internal clock is perturbed by the companion coming back:
`IMU sample from the past by 3.5 s`, `Dropping frame bundles … older than the last accepted`,
then `clock recovered`. Patches 0021/0022's guards are what keep this from being fatal, and
this is a plausible mechanism for the long-standing note that *"a companion USB2
re-enumeration preceded one total constellation-candidate blackout"*.

**Caveat, stated because it matters:** this was measured with a forced `USBDEVFS_RESET`, which
may be harsher than a natural drop. The cheap next check is to grep a real stormy session's
service log for the same 1:1 pattern between companion errors and `clock recovered`.

## What is NOT covered

* **The dropouts themselves.** They are the link's (docs/60). This makes them survivable, not
  rare. The rev2A cable question stands on its own.
* **Audio.** The USB audio sink is PipeWire's to recreate; it already does, and the wearer
  hears the gap. Out of scope here.
* **The USB3 branch.** Hololens sensors — IMU, cameras, controller tunnel — have never dropped
  in any capture on either OS. Nothing that matters for tracking passes through the companion,
  and the reconnect is deliberately scoped so it can never touch that path.
* **Presence re-sync**, if the feature read turns out unsupported. Measured on this unit: the
  device answers `-1` to a feature-report read of the IPD/proximity id, so after a reconnect
  presence stays on its pre-outage value until the sensor next changes. The driver says so in
  the log rather than pretending. A real fix would be a doff/don during an outage — the failure
  is bounded (presence is wrong only until the wearer next moves the headset), and the debounce
  already fails toward "worn", which is the safe direction.

## How to verify it in a session

```bash
~/vr/jack-in-wayland.sh up 1 6dof
./scripts/usb-reset-device.py -n 3 -i 15      # or: sudo ./scripts/usb-companion-reset.sh
grep -E "RECONNECTED|Error reading from companion" ~/vr/jack-in-wayland.log
```

Expect one error line and one `Companion device RECONNECTED on /dev/hidrawN after NNNN ms dead`
per re-enumeration. `USBDEVFS_RESET` does not always tear the device down — when devnum and the
node both stay put and the driver logs nothing, the reset was a no-op and the run tested
nothing. Run it again; that is why the tool prints context and leaves the verdict to the log.

## Follow-up 2026-08-21 (T244): the side-finding was ours, and it is fixed

The "clock-domain disturbance per re-enumeration" above was not the headset's clock. Timing each
step of `wmr_run_thread` named it: the proximity re-sync `os_hid_get_feature` this patch added
after a reconnect **blocks 1.4-5.0 s** (usbhid control-transfer timeout; the device never answers
— 0 successes, 48 failures) inside the loop that also reads the IMU and cameras. The backlog then
pulled `hw2mono` into a 3.5 s rejection hole. Patch 0094 gates the read off
(`WMR_COMPANION_RECONNECT_RESYNC=1` for an A/B) and keeps the per-step stall warnings; patch 0093
makes the IMU offset filter backlog-aware. 66 natural re-enumerations in one session afterwards:
no rejection, no dropped bundles, no stall above 60 ms but one 3.0 s `open()`. Full chain in
docs/06, "The wearer gets relocated on every companion drop". 0090's recovery itself (re-find,
swap, re-assert panel at ~1.5 ms) is unchanged and was exercised 66 times.
