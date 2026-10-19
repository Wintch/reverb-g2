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

## Bluetooth note

Controllers used on Windows must be re-paired (`scripts/bt-controllers/bt-winorder.py`, docs/136). Keep a
persistent agent running afterwards (`yes yes | bluetoothctl`), otherwise BlueZ refuses the later
reconnect (`Refusing connection ...: setup in progress`) and drops the device.
