# 150 — !2967 firmware-read recovery: fault-injection matrix (2026-10-19)

Follow-up to docs/146. The soaks there could not discriminate `b184f1ed2` (the init-command retry):
no slow reply ever showed up on demand. This run forces the failure instead of waiting for it.

## Method

Setup: the lab machine, G2 on USB, both controllers paired to the host adapter (UB500 Plus),
`monado-cli test` (`WMR_LOG=debug`, `WMR_SLAM=0`, `WMR_HANDTRACKING=0`). Tree: current `main`
(34584b360) plus the 5 commits of !2967 (R = `48006497c`), with and without the two fixes
(F = `1343443a7`, i.e. `4e3e6b419` and `b184f1ed2` cherry-picked). Both carry a test-only
`fault-inject.patch` (never upstreamed): `WMR_FWFAULT=cmd,blk,addr_min,addr_max,count` makes
`wmr_controller_send_fw_cmd()` skip reading the reply of matching commands and return `-ETIMEDOUT`,
so the reply reaches the host late, like a >250 ms reply on a loaded link. A runner script repeated
each scenario and counted runs that created both controllers. Builds: 0 warnings; clang-format 19
clean (the version CI uses). `main` needs `-DCMAKE_DISABLE_FIND_PACKAGE_Ceres=ON` here (Ceres cannot
find glog), unrelated to this change.

A controller only reads two blocks: block 0 (67 bytes, header reply only) and block 3 (450 bytes).

## Results (runs creating both controllers / runs)

| Scenario | Fault | R (!2967 as posted) | F (plus both fixes) |
|---|---|---|---|
| none | no injection | 9/11 | 11/11 |
| zero1 | first `0x06/0x00` reply late | **0/3** | **3/3** |
| quiesce1 | first `0x06/0x04` reply late | **0/3** | **3/3** |
| zero2 | two consecutive `zero` replies late | **0/3** | **3/3** |
| hdr-stale | block 0 header reply late, the duplicate lands on the block 3 header | **0/8** | **8/8** |
| chunk-mid | one mid-block chunk reply late | 3/3 | 3/3 |
| zero3-neg | three consecutive `zero` replies late | 0/3 | 0/3 |
| chunk3-neg | three consecutive chunk replies late | 0/4 valid | 0/3 valid |

Reading:

1. **`b184f1ed2` is an A/B result, not an inference.** A late reply to `zero`/`quiesce` fails 9/9
   without it and recovers 9/9 with it (retries logged).
2. **`4e3e6b419` likewise:** the header request aborts with
   `stale reply for block 0 while reading block 3` 8/8 without it; with it, 8/8
   `Discarding stale fw reply (block 0) while reading the header of block 3` and both controllers come up.
3. The chunk-loop recovery already in !2967 holds on current main (chunk-mid 3/3 on both).
4. Three lost replies in a row still fail, for both (bounded, no hang): the retry limit is 3 by design.
   Confirmed for the init commands (zero3-neg) and for the chunk loop (chunk3-neg): the failure lands on
   attempt 3 of 3 every time.

Trap: the first pass aimed hdr-stale at a block that is never read (0 injections); aim it at the block 0
header. Mis-aimed rows count as non-injected runs.

## Spontaneous failures (no injection)

R: 3 of 17 non-injected runs failed, each in a mode the fixes cover: an init-command timeout (the first
run after a fresh pairing) and two header aborts on a stale reply. F: 1 of 17 failed, with three
consecutive 250 ms timeouts on a block 3 chunk (`cmd 0x02 failed @ offset 68`), i.e. sustained loss
beyond the 3-attempt bound of the chunk loop already in !2967; not a regression of the fixes.

### Runs that do not count

chunk3-neg had 12 runs, 5 of them with 0 injections: the controller did not answer the first init
command at all (base: one 250 ms timeout; F: three, i.e. over 750 ms of silence). Four came in the first
pass, after the controllers had sat idle; one came right after a run aborted in the middle of the block 3
read. Not valid as chunk tests (7 valid: base 4, F 3), and a limit of the init retry worth knowing: it
absorbs one slow reply, not a controller that is not answering yet. Which of "idle" and "previous run
aborted mid-read" is the trigger is not established.

## Natural soaks (no injection), exact candidate binaries

Repeated `monado-cli test` cycles, counting cycles that created both controllers. `probe12` is a
test-only patch: the two init commands with 12 attempts, logging the time to the first reply.

| Soak | R / A (no fixes) | F / B (with fixes) |
|---|---|---|
| 15 cycles, minutes after re-pairing | 13/15 | 12/15 |
| 20 cycles, F against `probe12` | n/a | 20/20 (`probe12` 20/20) |
| 20 cycles, hw-lineage base, slow link | 1/20 | 2/20 |
| 20 cycles, hw-lineage base, healthy link | 17/20 | 20/20 |

- First soak, classified: F failures were three consecutive 250 ms timeouts on the **first** init command
  (retries ran and got no reply); R failures were one 250 ms timeout on the first init command (the
  single-shot case `b184f1ed2` targets); one F cycle lost `/dev/hidraw6` before it was opened (the
  Bluetooth link dropped; nothing in the firmware path can cover that).
- `probe12` in the clean soak: 80 samples answered in 7 to 123 ms except two at about 306 ms (one retry
  each, exactly the late reply the single-shot code cannot survive). No sample was unanswered.
- Healthy-link soak, the three A failures are exactly the targeted modes: a late header reply landing on
  the next header request (`4e3e6b419`), and a single 250 ms timeout on an init command (`b184f1ed2`). B
  logged retries and stale-reply discards in 4 cycles, recovered each time, never needed attempt 3. This is
  the first natural-link A/B where the fixes show a gain (20/20 vs 17/20; small numbers, consistent with the
  mechanisms, not a rate).
- Slow-link soak: almost every run died on the first init command with no reply (B after the full three
  attempts). The link then answered in seconds (first replies of 650 to 2500 ms, one not in 4.3 s even with
  12 attempts), at RSSI -26/-33 dBm with no other Bluetooth client. The cause was not identified (candidates:
  controller batteries, 2.4 GHz interference, the adapter); with fresh batteries the silences did not return.
  Moving the controllers did not help, so the "idle controllers answer badly" idea is not supported.

Reading: there are two regimes. In the normal one replies take 7 to 120 ms with a rare ~300 ms outlier,
and the fixes cover it (they help wherever a reply takes 250 to ~750 ms: init commands, header, chunks).
Right after the controllers were re-paired or woken, or on a degraded link, they can stay silent for more
than 750 ms on the first command, and neither R nor F recovers; the retry only changes which attempt gives
up. That regime could not be provoked on demand (reconnect rounds over BlueZ: 72 init commands, all
answered, median 19 ms, two first replies at ~291 and ~311 ms), so it is documented, not solved. Whether a
longer init window would cover it is untested.

## Real sessions (worn)

`ab-run`-style session: DRM lease on GNOME Wayland, controllers on the host BT adapter, `hello_xr` for
120 s, headset worn. Build: F on current main, 0 warnings, `ctest` 28/28.

- Cold start: the launcher's first two attempts failed in controller creation just after the controllers were
  shaken awake (`Failed to create controller`; `cmd 0x02 failed to read header for block 0`), the third
  created them but found no leasable connector, because the killed earlier attempts left the lease dangling.
  The same cold regime as above.
- Warm controllers: `Socket ready (attempt 1/3)`, both controllers created, `hello_xr` rc=0, 119 pose samples
  per hand, no coredump. The recovery code ran on its own: two 250 ms timeouts then success on attempt 3 of a
  chunk read, followed by two `Discarding stale fw reply (block 3, 42+68 bytes, wanted 42)`. `tracked_s=0` is
  expected: current main has no clock-conversion fix for the controllers (docs/135). 24 `Invalid packet
  received` lines (one every ~6.3 s) were not in earlier logs; the status dashboard polls controller state
  through `libmonado` of the production build, so a protocol mismatch with the newer service is the likely
  cause (inferred, not checked).
- Blind A/B on the hw-lineage base (A = no fixes, B = both fixes; 3 pairs of 2 x 120 s, wearer not told the
  order): the wearer's judgements favoured opposite arms in pairs 1 and 2 and did not separate them in pair 3;
  app-side frozen seconds (left+right, of 119 s) were B 27, 43, 95 vs A 56, 42, 79; tracked seconds 108 to 119
  per hand in every leg. No leg logged a firmware retry, stale-reply discard or creation failure, so the fixes
  never ran: the changed code only touches firmware-block reads and the two init commands, which succeeded
  first try. Tracking quality varies run to run on this base (no clock fix) and the data show no effect of
  the fixes in either direction. Every leg ends with the known teardown SIGSEGV of `monado-service`, not
  related to !2967. Trap: stale logs of an earlier run with the same label make the launcher think the socket
  is ready, so the client starts before the service; clear old logs of a label before a run.

## Cold reconnect rounds, A vs B (hw base)

Disconnect both controllers over BlueZ, run `monado-cli test` as soon as they are back, then again 3 s later.
The controllers stopped reconnecting by themselves after round 3 (those rounds are not counted).

| | Runs creating both controllers | Failures |
|---|---|---|
| A (no fixes) | 3/6 | 3, all `stale reply for block 0 while reading block 3` (the case `4e3e6b419` fixes) |
| B (with fixes) | 3/4 | 1: after the first controller was created and its config read, a single 250 ms timeout ended the creation |

The B failure is the third init command, `0x06/0x21` ("Reset device time before controller outputs",
`wmr_controller_base.c`), which still goes through the single-shot `wmr_controller_send_fw_cmd()`. That
command does not exist on current `main` nor in !2967: it comes from the timesync work of the hw lineage
(`65a418d52 WIP implementation of timesync protocol`), so there is nothing to add to !2967 for it. If that
lineage is upstreamed, its `0x21` should use `wmr_controller_send_fw_cmd_retry()` too (resending only resets
the device time again, the status reports are not enabled yet).

## Bluetooth note

Controllers used on Windows must be re-paired (`scripts/bt-controllers/bt-winorder.py`, docs/136). Keep a
persistent agent running afterwards (`while sleep 20; do echo yes; done | bluetoothctl >/dev/null`, never an
unbounded `yes` into a file), otherwise BlueZ refuses the later reconnect
(`Refusing connection ...: setup in progress`) and drops the device.
