# 144 — Session 2026-10-10 (comms side): sweep, hare_ware re-diff + desk A/B, upstream BT regression, pairing research

The everyday box ran a "novedades" sweep, then followed the threads it found: a re-diff of
hare_ware's new tip, a hardware A/B on the lab (iashur), an upstream Monado regression found on
the way, and a research pass on pairing G2 controllers to the headset radio from Linux. Times are
local (-03) unless marked Z. Companion records: `docs/135` (re-diff section), `docs/143` (A/B),
`docs/18` (rows 2026-10-10), `docs/03` (pairing research addendum).

## 1. Sweep — what was new

| channel | state found | action |
|---|---|---|
| Monado !3021 | merged 10-07 (already in docs/142) | none |
| Monado !2969 pipeline #1759443 | **passed** 10-05 00:42Z; the "stuck in verify" of 10-05 was a snapshot | none |
| Monado !3020 | head pipeline #1752624 red: `alpine` `tests_worker` SEGFAULT, the known flake, never retried | retry blocked by the agent's permission classifier; left to the user (job 110998280) |
| Monado !2967/2968/2971/3004 | no new human notes since 10-02..05; rpavlik and bl4ckb0ne still silent | none, do not nudge |
| Monado `main` | `13b5c134b` (19 past `045931d12`). !3030 merged 10-06; a SteamVR eye-offset regression was reported on it 10-10 (Mouxon; wallbraker suspects `ovrd_driver.cpp` `GetProjectionRaw` swapping top/bottom). New issue #628 (`SLAM_PRED_NONE` returns the newest pose for past timestamps). All six open MR heads still merge clean | see §6 |
| hare_ware/monado | force-pushed again 10-06: `10a23daab` = the same 45 commits rebased onto `045931d12` + 2 new | §2 |
| GitHub BnuuySolutions/Ignition#3 | **closed** 10-09 by RealSupremium: Ignition only passes the EDID VID/PID; Oasis issues go to `mbucchia/Oasis-Driver-for-Windows-Mixed-Reality`, SteamVR ones to `ValveSoftware/SteamVR-for-Linux`. Their README now defers to the Oasis wiki; none of our X11/panel-guard guidance went in | no reply (silence is the default) |
| LVRA wiki (vronlinux.org) | commit `52ff5066` (10-10, "Simon"): the G2 row no longer says "60Hz-only on Nvidia" but "90 Hz on Nvidia requires driver patches"; every WMR row now points to the Oasis SteamVR driver; new `/docs/hardware/wmr/` page (Oasis + Ignition, BT pairing, thaytan's wmr-utilities, AUR `nvidia-open-dkms-g2`). No credit to us | the wiki correction we wanted is done by someone else; nothing owed |
| NVIDIA | 615.78.08 released 10-07; `nvkms-dpy.c` byte-identical to 615.71.09 (the fix is not integrated). PR #1275 untouched since 09-17; forum 337744 still 18 posts | §5 |
| xrizer | v0.6 released 10-08; does not fix the `wait_image before release_image` panic. Upstream PR #431 (open) fixes it differently (skip the release instead of priming the acquire) | keep our local patch on iashur |
| Faulto fork, Basalt !39, bluez#689, hare_ware issue #1 | unchanged | none |
| Matrix | token dead (`M_UNKNOWN_TOKEN`) | ask for a fresh one only if LVRA reading matters |
| Space Calibrator | hyblocker's repo is active (commits through 09-24, 2.0 via the Steam beta branch); the "family is dormant" note was wrong for it | memory corrected |

## 2. hare_ware `10a23daab` re-diff

Recorded in `docs/135` § "Re-diff against hare_ware 10a23daab". Short version: the double
conversion of the camera exposure time is unchanged; the new `timing_fudge_ns` search is bounded
by a 22 ms window; 10a23daab dropped a constant ~10.5 ms offset the tested tip sent; his own
"HACK ... SUPER wrong" settle-gate slip is a second clock-domain bug. Two corrections were made the
same day:

- docs/135's Run 3 vs Run 4 comparison was not a clean A/B (Run 4 also carried our !2967/!3004
  commits, and Run 3 was worn while Run 4 was on the desk).
- A first claim that host-Bluetooth controllers get no constellation tracking on his branch was
  **wrong** and retracted (`33a7b8d`): the `// TODO` comments in `target_builder_wmr.c` are stale,
  and the builder calls `wmr_constellation_attach_controller_to_hmd()` for BT controllers too.
  Lesson: read past a TODO before claiming a gap.

## 3. Desk A/B on the lab — `docs/143`

Branches `hw-timesync-fix-v2` (fix) and `hw-ab-nofix` differ only by `783cf6ae5`; built on iashur
in `~/vr/monado-hw{,-nofix}` with `scripts/hare-ware-ab/build-on-iashur.sh`; legs run detached
with `scripts/hare-ware-ab/ab-run.sh` (`AB_TRANSPORT=bt`). Controllers on the UB500 Plus.

- **Clock fix confirmed on hardware**: without it ~2600 of ~2650 timesync packets per controller
  are negative and the time runs backwards at ~28x; with it, zero negative, 1.000x wall.
- **Tracking inconclusive**: poses decayed over successive legs in both arms (1389, 992, 0, 0),
  LEDs on, controllers moved at the 60 s cue. After a controller power-cycle the left controller
  failed BT creation (`fw read timed out`) 3/3, so the power-cycle control could not run.
- **Teardown use-after-free in hare_ware's code**: SIGSEGV on SIGTERM in 3 of 4 legs; the BT
  controller read thread pushes to `tracking.constellation_imu_sink` (`wmr_controller_base.c:1054`
  at `10a23daab`) after the tracker is gone.

**Posted** (user's go): hare_ware/monado issue #2,
`https://gitlab.freedesktop.org/hare_ware/monado/-/work_items/2` — the clock double conversion
with the A/B numbers, the stale TRACKED pose, the teardown crash, the Ceres link note, and an
offer of the patch/MR. No mention of his unanswered issue #1. Source text kept outside the repo
(`notify-drafts/03`).

## 4. Upstream regression found: host-BT WMR controllers kill the WMR builder

`b0b1d8b1b` ("drivers: fix dead stores", Simon Zeni, MR !2985, merged 2026-09-30 as part of the clang-tidy dead-store series, docs/134) added
`if (ret != 0) -> fail` after `xrt_prober_get_string_descriptor()` in
`wmr_prober.c:wmr_create_bt_controller()` and in `hdk_prober.c:hdk_found()`. That function returns
the string length on success (`p_prober.c:1438` for Bluetooth, the libusb path likewise), so every
successful lookup is rejected. For WMR a host-paired controller makes the builder fail with
`XRT_ERROR_DEVICE_CREATION_FAILED` and there is no headset at all. `classify_and_assign_controller()`
in the same file already uses `<= 0`.

Fix: branch `prober-string-descriptor-length` (`6eedc6cf8`, DCO signed, both files, `<= 0`), on
`origin/main` `13b5c134b`; `drv_wmr` and `drv_hdk` compile; the WMR half verified on hardware (the
same one-liner let the A/B legs run). **Pushed to `Wintch/monado`**; the MR has to be opened from
the web form (Akismet blocks API MR creation) — text ready in `notify-drafts/04`, then add
`doc/changes/drivers/mr.<N>.md` and a docs/18 row. Our lab pin `735e29e4e` predates `b0b1d8b1b`,
so lab-full was never affected; anything built from current `main` with host-BT controllers is.

## 5. Other local work (nothing pushed upstream)

- **NVIDIA port on 615.78.08**: local branch `g2-90hz-615.78.08` (`929f2a98`) in the
  open-gpu-kernel-modules clone = our `d2028a13` guard cherry-picked onto the tag + Faulto's
  `minBpc` change (`rgb444.minBpc = 8` for manuf `0x0E22` / product `0x36C1` when `bpc == 0`,
  attributed, MIT). Not pushed; adding it to PR #1275 may need Faulto's consent under NVIDIA's CLA.
- **Our NVIDIA patch 0003 is probably a no-op**: it matches `case 0x220E`, but DPLib's
  `getManufId()` reads the EDID bytes little-endian (`dp_edid.h:129-135`; Apple's `06 10` is
  `0x1006` in the same database), so the G2 (`22 0e`) reads `0x0E22`, which is what Faulto's 0003
  uses. 90 Hz never depended on it at runtime as far as we know. Flagged in
  `patches/nvidia/README.md`; docs/12/14/16/26/31 still say `0x220E` (the EISA big-endian spelling)
  and need a pass once checked deliberately.
- **Scripts transplanted** from the stale `reverb-g2-linux` clone (`fedc9e6`):
  `analyze-panel-judder.py`, `extract-wmr-dlls.sh` (docs/38, docs/41, docs/re-windows/00 cited
  them at a path that only existed there). The rest of that clone is superseded; its
  `edid-mode-inject.py` same-file guard was committed long ago (`0cd26c6`) and has no equivalent in
  `edid-tool.py` (optional fix).
- **!3030 impact** (no action until the lab rebases): it fixes a ~1.5 deg / ~27 px right-eye
  vertical shift our G2 carried silently (asymmetric FOV of eye 1, computed from a pre-!3030
  `jack-in.log`, not measured on the headset). We never used `WMR_*_VIEW_Y_OFFSET`. On a rebase
  past `019d9d458`, patch 0072's context breaks (0075 as a knock-on). The SteamVR regression does
  not touch our paths (xrizer maps the FOV correctly; Oasis runs with `driver_monado` disabled).
  #628 does not affect our profiles (Aircar/Cyberpilot use GYRO prediction).

## 6. Pairing to the headset radio from Linux — research (no hardware action yet)

Full addendum in `docs/03` ("2026-10-10 research"). Nobody has published a working Linux pairing
to the headset radio, but there are three untried leads:

1. **Oasis 1.0.4 (10-09) ships a Linux launch option `pair_bluetooth.sh`** "to pair motion
   controllers on Samsung Odyssey+, HP Reverb and HP Reverb G2" (Steam app 3824490, build
   25833996). iashur still has build 25276174; Steam updates it on next start. Read the script
   before running it.
2. **thaytan's wmr-utilities** (`e9dc15a0`, 2024, BSL-1.0), linked by the new LVRA page: same
   PAIR bytes as ours (`16 05 <hand>` Feature on 045e:0659 interface 2), but by default through
   hidapi-libusb (detaches usbhid; never tried by us) and it polls `16 09` for a status flag.
   Built on iashur in `~/vr/wmr-utilities/build-{libusb,hidraw}`, **not run**.
3. **The 0x03 firmware log was never read during a Linux PAIR.** In the Windows capture
   (`pairing3.pcapng`, frame 53970) the headset logs `Received pair request MC: 0` on report 0x03
   1 ms after the PAIR, then the radio's inquiry lines on 0x05. Our Linux attempts read only
   0x05/0x17, so we cannot tell "not dispatched" from "dispatched and declined".
   `scripts/controller-pair-v2.py` (new) decodes 0x03/0x05/0x16/0x17 from before the first send,
   sends exactly one gated PAIR (never UNPAIR), can replay the Windows host preamble, and has a
   `--selftest PCAP` that passes 17/17 checks against the capture (12 when first written; docs/03 still says 12/12).

Any successful PAIR moves that controller off the UB500 bond (single peer); docs/136 has the
recipe back.

## 7. State left behind

- iashur: no monado-service; `~/vr/.jack-in-failed` cleared (cause understood); worktrees
  `~/vr/monado-hw` (`hw-timesync-fix-v2`) and `~/vr/monado-hw-nofix` (`hw-ab-nofix`) each carry the
  **uncommitted** one-line `wmr_prober.c` fix (plus untracked build logs); they share production's `.git` (`refs/ab/*`, a
  `hw-ab-nofix` branch and a worktree entry were added; production checkout untouched,
  `lab-full` `ff6db76f6`). A/B logs in `~/vr/logs/ab-*` (13 MB). Kit copies in `~/vr/tmp/`.
- Everyday box: local monado branches `hw-timesync-fix-v2`, `hw-ab-nofix`,
  `prober-string-descriptor-length` (pushed to the fork); ref `hw/nct-10a23daab`.
  open-gpu-kernel-modules branch `g2-90hz-615.78.08` (local only).
- **Disk: the everyday box's root was at 97 % (7 GB free) when measured for the cleanup list**, up
  from 92 % earlier in the day, not from this session's work (`/tmp` is tmpfs). Re-measured at
  fact-check time: 92 % (16 GB free), so about 9 GB was freed afterwards; the cause was not identified
  (the cleanup list itself was not executed by this session). A ranked cleanup list (about 10 GB regenerable:
  docker build cache and dangling images, browser caches, old claude binaries, ccache; journal and
  apt cache need root) was prepared for the user; nothing deleted by it.

## 8. Open

- User: open the MR for `prober-string-descriptor-length` (web form), then the fragment +
  docs/18 row; retry the !3020 `alpine` job; decide the disk cleanup.
- Pairing from Linux: one controller in discovery, then (a) `controller-pair-v2.py --single-pair`
  with 0x03 decoding, (b) wmr-utilities with both backends, (c) the Windows-preamble variant,
  (d) Oasis 1.0.4 `pair_bluetooth.sh` after reading it.
- With tunnelled controllers: repeat the A/B with a power-cycle before every leg, to judge
  tracking the way hare_ware runs it.
- hare_ware issue #2: wait; do not nudge.
