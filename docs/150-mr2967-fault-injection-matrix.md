# 150 — !2967 firmware-read recovery: fault-injection matrix (2026-10-19)

Follow-up to docs/146. The soaks there could not discriminate `b184f1ed2` (the init-command retry):
no slow reply ever showed up on demand. This run forces the failure instead of waiting for it.

Setup: iashur, G2 on USB, both controllers paired to the host adapter (UB500 Plus), `monado-cli test`
(`WMR_LOG=debug`, `WMR_SLAM=0`, `WMR_HANDTRACKING=0`). Tree: current `main` (34584b360) plus the 5 commits
of !2967 (R = `48006497c`), with and without the two fixes (F = `1343443a7`, i.e. `4e3e6b419` and
`b184f1ed2` cherry-picked). Both carry `fault-inject.patch` (test-only, never upstreamed):
`WMR_FWFAULT=cmd,blk,addr_min,addr_max,count` makes `wmr_controller_send_fw_cmd()` skip reading the reply
of matching commands and return `-ETIMEDOUT`, so the reply reaches the host late, like a >250 ms reply
on a loaded link. Runner: `scripts/fw-stale-soak/fw-fault-matrix.sh`. Builds: 0 warnings; clang-format 19
clean (the version CI uses). `main` needs `-DCMAKE_DISABLE_FIND_PACKAGE_Ceres=ON` on iashur (Ceres cannot
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

1. **`b184f1ed2` is now an A/B result, not an inference.** A late reply to `zero`/`quiesce` fails 9/9
   without it and recovers 9/9 with it (retries logged).
2. **`4e3e6b419` likewise:** the header request aborts with
   `stale reply for block 0 while reading block 3` 8/8 without it; with it, 8/8
   `Discarding stale fw reply (block 0) while reading the header of block 3` and both controllers come up.
3. The chunk-loop recovery already in !2967 holds on current main (chunk-mid 3/3 on both).
4. Three lost replies in a row still fail, for both (bounded, no hang): the retry limit is 3 by design.
   Confirmed for the init commands (zero3-neg) and for the chunk loop (chunk3-neg): the failure lands on
   attempt 3 of 3 every time.

The first pass aimed hdr-stale at a block that is never read (0 injections); it was corrected to the
block 0 header and rerun with 8 repetitions. The mis-aimed rows count as non-injected runs below.

## Spontaneous failures (no injection)

R: 3 of 17 non-injected runs failed, each in a mode the fixes cover: an init-command timeout (the first
run after a fresh pairing) and two header aborts on a stale reply. F: 1 of 17 failed, with three
consecutive 250 ms timeouts on a block 3 chunk (`cmd 0x02 failed @ offset 68`), i.e. sustained loss
beyond the 3-attempt bound of the chunk loop already in !2967; not a regression of the fixes.

## Runs that do not count

chunk3-neg had 12 runs, 5 of them with 0 injections: the controller did not answer the first init
command at all (base: one 250 ms timeout; F: three, i.e. over 750 ms of silence). Four came in the first
pass, after the controllers had sat idle; one came right after a run aborted in the middle of the block 3
read. Not valid as chunk tests (7 valid: base 4, F 3), and a limit of the init retry worth knowing: it
absorbs one slow reply, not a controller that is not answering yet. Which of "idle" and "previous run
aborted mid-read" is the trigger is not established.

## Natural soaks (no injection), exact candidate binaries

`fw-soak.sh`, `monado-cli test`, alternating R (`mbase`) and F (`mfix2`):

| Soak | When | R | F |
|---|---|---|---|
| 15 cycles | minutes after re-pairing the controllers | 13/15 | 12/15 |
| 20 cycles (F against `probe12`, see below) | 15 min later | n/a | 20/20 (`probe12` 20/20) |

Failures of the first soak, classified: F cycles 4 and 5, three consecutive 250 ms timeouts on the **first**
init command (retries ran and did not reach a reply); R cycles 6 and 15, one 250 ms timeout on the first init
command (the single-shot case `b184f1ed2` targets); F cycle 6, `/dev/hidraw6` vanished before it was opened
(the Bluetooth link dropped, nothing in the firmware path can cover that).

`probe12` is `init-latency-probe.patch`: the two init commands with 12 attempts, logging the time to the
first reply. In the clean soak 80 samples answered in 7 to 123 ms except two at about 306 ms (one retry
each, exactly the late reply the single-shot code cannot survive). No sample was unanswered.

Reading: there are two regimes. In the normal one replies take 7 to 120 ms with a rare ~300 ms outlier,
and the fixes cover it. Right after the controllers were re-paired or woken they can stay silent for more
than 750 ms on the first command, and neither R nor F recovers; the retry only changes which attempt gives
up. That regime could not be provoked on demand (the controllers do not sleep within 10 minutes of
idling), so it is documented, not solved. Whether a longer init window would cover it is untested.

## Real session (worn)

`worn-leg-2967.sh` = `worn-leg.sh` with the `monado-2967-v2` build allowed: `ab-run.sh` (`up 1 ctrl`, DRM
lease on GNOME Wayland, controllers on the host BT adapter) plus `hello_xr` for 120 s, headset worn.
Build: F on current main, 0 warnings, `ctest` 28/28.

- Leg f2967-1: the launcher's first two attempts failed in controller creation just after the controllers
  were shaken awake (`Failed to create controller`; `cmd 0x02 failed to read header for block 0`), the third
  created them but found no leasable connector, because the killed earlier attempts left the lease
  dangling. The same cold regime as above. No session.
- Leg f2967-2 (controllers warm): `Socket ready (attempt 1/3)`, both controllers created, `hello_xr` rc=0,
  119 pose samples per hand, no coredump, service gone and socket removed at the end. The recovery code ran
  on its own: two 250 ms timeouts then success on attempt 3 of a chunk read, followed by two
  `Discarding stale fw reply (block 3, 42+68 bytes, wanted 42)`. `tracked_s=0` is expected: current main
  has no clock-conversion fix for the controllers (docs/135). 24 `Invalid packet received` lines (one every
  ~6.3 s) are not in the 10-11 logs; the status dashboard polls controller state through `libmonado` of the
  production build, so a protocol mismatch with the newer service is the likely cause (inferred, not checked).
- Wearer feedback (controls, tracking, comfort): not recorded yet.

## Incident: disk

The persistent Bluetooth agent started for the re-pairing (`yes yes | bluetoothctl > ~/bt-agent.out`) wrote
an error line per "yes" and grew to 24 GB in about three hours (root went from 82% to 94%). Stopped and
removed; the replacement feeds one line every 20 s and discards its output.

## Bluetooth note

Controllers used on Windows must be re-paired (`scripts/bt-controllers/bt-winorder.py`, docs/136). Keep a
persistent agent running afterwards (`while sleep 20; do echo yes; done | bluetoothctl >/dev/null`, never an unbounded `yes` into a file), otherwise BlueZ refuses the later
reconnect (`Refusing connection ...: setup in progress`) and drops the device.
