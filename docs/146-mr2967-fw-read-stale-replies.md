# 146 — !2967 firmware reads over host Bluetooth: stale replies and init timeouts (2026-10-11)

Subject: our open MR !2967 (`d/wmr: Tolerate transient read errors ...`, head `c0231b1f0`), which
makes the WMR controller firmware reads survive a host Bluetooth link: a timed-out command is
resent (`wmr_controller_send_fw_cmd_retry()`), and the chunk loop in `wmr_read_fw_block()` discards
a reply whose block id or size does not match (commit `90c0125c8`). Jan asked on the MR for
evidence that the recovery path actually runs on hardware. This document has it, plus two gaps
found on the way and the local fixes for them. Nothing here is pushed to !2967 yet.

Setup: iashur, G2 on USB, both controllers paired to the host adapter (UB500 Plus),
`monado-cli test` (prober + builders, no compositor) with `WMR_LOG=debug`, `WMR_SLAM=0`,
`WMR_HANDTRACKING=0`. Harness: `scripts/fw-stale-soak/fw-soak.sh` (alternates builds, one log per
cycle + `results.csv`) and `scripts/fw-stale-soak/pc-soak.sh` (asks for a controller power-cycle
before each block). Builds in `~/vr/monado-2967-bin/<variant>/monado-cli`, 0 warnings each:

| Variant | Commit | What it adds |
|---|---|---|
| `base` | `c0231b1f0` | !2967 as published |
| `hdrfix` | `4e3e6b419` | + discard a stale reply on the block header request |
| `fix2` | `b184f1ed2` | + retry the two controller init commands |

## 1. Mechanism (read from the logs, cycle 001-base)

1. A firmware command's reply takes longer than the 250 ms read timeout.
2. `wmr_controller_send_fw_cmd_retry()` resends the command (`attempt 1 of 3`).
3. The original reply arrives late, so every later reply in that block is one request behind.
4. The chunk loop sees a reply for the previous request, discards it and asks again; this repeats
   for every remaining chunk (`Discarding stale fw reply (block 3, 382+68 bytes, wanted 382)` ...
   down to `42+68`) and the block completes correctly. **This is the recovery path working on
   real hardware.**
5. One reply is still in flight when the block ends. It lands either on the next block's header
   request or, after the last block, in the controller's input thread as
   `Unknown message type: 02, size: 78` (harmless).

## 2. Gap 1: the header request did not discard (fixed by `4e3e6b419`)

The header request (`0x06/0x02`) at the start of each block checks the echoed block id, but on a
mismatch `base` aborts instead of discarding:

```
WARN [wmr_controller_send_fw_cmd] Controller fw read timed out after 250 ms
DEBUG [wmr_controller_send_fw_cmd_retry] Controller fw cmd failed (-110), attempt 1 of 3
WARN [wmr_read_fw_block] Failed to read fw - stale reply for block 0 while reading block 3
ERROR [read_controller_fw_info] Failed to read FW info block 3
ERROR [wmr_bt_controller_create] WMR Controller (Bluetooth): Failed to create controller
```

A BT controller creation failure is fatal to the WMR builder, so the headset goes with it.
`4e3e6b419` gives the header request the same treatment as the chunk loop: discard up to 3 stale
replies, then fail. With it (cycle 003-hdrfix):

```
DEBUG [wmr_read_fw_block] Discarding stale fw reply (block 0) while reading the header of block 3
DEBUG [wmr_read_fw_block] Discarding stale fw reply (block 3, 382+68 bytes, wanted 382)
...
DEBUG [wmr_read_fw_block] Discarding stale fw reply (block 3, 42+68 bytes, wanted 42)
```

and both controllers are created.

## 3. Gap 2: the init commands had no retry (fixed by `b184f1ed2`)

Controller creation sends two commands before any firmware read: `0x06/0x00` (zero) and
`0x06/0x04` (quiesce). Both used the single-shot `wmr_controller_send_fw_cmd()`, so one slow reply
kills the controller (cycle 019-base, second controller):

```
WARN [wmr_controller_send_fw_cmd] Controller fw read timed out after 266 ms
ERROR [wmr_bt_controller_create] WMR Controller (Bluetooth): Failed to create controller
```

This is the same signature as docs/143 R5 (`fw read timed out` 250-345 ms at BT controller
creation, 3/3 attempts after a power-cycle). `b184f1ed2` sends both through
`wmr_controller_send_fw_cmd_retry(..., 3)`; both are safe to resend.

## 4. Soaks

### Soak 1 — `base` vs `hdrfix`, 25 cycles each, alternated (`fw-soak-20261011-105613`)

| Variant | Both ctrls created | Chunk stale discarded | Header stale discarded | Header abort | Init timeout |
|---|---|---|---|---|---|
| `base` | **22/25** | 11 | — | 2 (cycles 4, 5) | 1 (cycle 19) |
| `hdrfix` | **25/25** | 28 | 1 (cycle 3) | 0 | 0 |

Every timeout of the run fell in cycles 1-5 (both variants) plus cycle 19; cycles 6-25 were clean
apart from that one. The run started minutes after the worn hello_xr legs on hare_ware's clock-fix branch (same
morning), with the controllers just used by a client.

### Soak 2 — `base` vs `fix2`, 40 cycles each, alternated (`fw-soak-20261011-110712`)

80/80 runs created both controllers. **Zero timeouts, zero retries, zero stale replies** in either
variant.

### Soak 3 — power-cycle blocks (`pc-soak`, order `base fix2 base fix2`, 3 cycles per block)

Before each block both controllers were switched off (host hidraw nodes gone), then on (both back,
~12 s), then the block ran. 12/12 runs created both controllers. **Zero timeouts, zero retries.**
Dirs: `fw-soak-20261011-{165933,170849,171227,171528}`.

## 5. Reading

1. **The !2967 chunk-loop recovery is confirmed on hardware.** Soak 1 has 39 discarded stale
   replies across both variants, every one followed by a correct block. This is the evidence the
   MR was asked for.
2. **`4e3e6b419` closes a real failure.** `base` lost the builder twice to a stale reply on the
   header request; `hdrfix` hit the same situation once and recovered.
3. **`b184f1ed2` is backed by one soak failure plus the three R5 failures, not by an A/B.** In
   soaks 2 and 3 (92 runs) nothing timed out, so neither arm was exercised.
4. **The trigger is not a fresh power-on.** R5 suggested it; soak 3 does not reproduce it. Soak 1's
   timeouts clustered in its first minutes, right after a client session, and then stopped. What
   makes the controllers answer slowly (BT link load, a state left by the previous session) is
   not known; only guesses so far.
5. Neither fix regresses anything: `hdrfix` 25/25, `fix2` 40/40 + 6/6.

## 6. Next

- Let both commits sit, re-review them, then propose the !2967 update (two more commits on the
  branch, or folded) with a note quoting sections 1-2 for Jan. Needs the user's go.
- If the slow replies show up again, note what ran just before; a reproducer for point 4 would
  turn `b184f1ed2` into an A/B result.
