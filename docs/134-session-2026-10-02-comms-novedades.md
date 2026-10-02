# 134 — Session 2026-10-02 (comms): "novedades" sweep, hare_ware's branch is the real news

Routine check of every outward-facing thread, eight days after docs/133. Nothing was posted or
pushed upstream during the session. Read docs/133 first; this only records what changed since.

## 1. hare_ware rebuilt his controller branch on post-!2940 `main`

`hare_ware/monado` `wmr-new-constellation-tracking` was **force-pushed** — the 09-23 tip
`f41362eb` is no longer reachable. New tip `9e1773326` (2026-09-30T23:36-04:00), rebased onto
upstream `main` `9950e2a5f` (09-27), i.e. *on top of* Beyley's !2940 tracker rewrite.

- 45 commits over `main`, 19 files, +1449/-65, all under `src/xrt/drivers/wmr/` plus
  `target_builder_wmr.c` and the drivers `CMakeLists.txt`.
- New `wmr_constellation_tracking.{c,h}` (294 lines) wiring WMR controllers into the upstream
  constellation tracker; `wmr_controller_base_get_tracked_pose` reworked to use the tracker's
  relation history; camera exposure timing exposed through `wmr_source`; LED model ids,
  visibility angles and coordinate conversion out of OpenCV/WMR space; controller exposure/gain
  loop fixed; a first timesync implementation.
- Self-described as work in progress: tip commit is "broken, but less broken timesync", and
  `eddd8609c` is "HACK add magical mystery offset to constellation tracking space origin".

What it means for us: this is the integration path upstream is likely to take for G2 controller
6DoF, and it sits on the new tracker, not the old one our docs/125/126 fix
(`CS_FLAG_MATCH_ALL_BLOBS`) targeted. Our seven MRs merge cleanly into his branch
(`git merge-tree`, all seven clean), so there is no collision with !3020's `wmr_camera_stop()`
change despite both touching `wmr_camera.c`.

Issue #1 on his repo (ours): still zero replies. Not nudged.

## 2. Monado: our seven MRs, still silent

No reviewer activity on !2967/!2968/!2969/!2971/!3004/!3020/!3021 since the 09-21 sweep; the last
note on every one of them is ours. Upstream maintainers are active elsewhere (Jakob, Simon,
Beyley, Frederic Plourde on !2889/!2985/!3006/!3024 in the last three days), so this is queueing,
not a dead project.

`main` moved 32 commits (`6b41c5b39` → `045931d12`): Simon Zeni's clang-tidy dead-store and
uninitialized-branch series (!2985, !2988), Cooper Morgan's `[NFC]` function-name fixes
(!3022/!3023), Beyley's recommended-view-configuration series and SO(3) `quat_exp/ln` (!3001).
Three hunks land in files we touch:

- `wmr_hmd.c`: `hmd_type = cur->hmd_type` became an `assert`.
- `wmr_prober.c`: `wmr_create_bt_controller()` now fails cleanly when the product string
  descriptor read fails — adjacent to the BT path rpavlik raised on !2967.
- `euroc_player.cpp`: the camera-count preload loop was rewritten (dead-store fix). !3021 edits
  `euroc_runner.c` and `p_tracking.c`, not this file; no semantic overlap.

`git merge-tree` of each MR head against the new `main`: **all seven clean**, each 32 commits
behind. A rebase is cosmetic until a reviewer picks one up.

New upstream issue worth knowing about: **#623** (2026-10-01), segfault on startup with
`steamvr_lh` on SteamVR 2.18.2. Relevant to anyone running Lighthouse tracking through Monado
(Faulto's setup, docs/85), not to our own G2-only path.

## 3. Everything else: unchanged

- Basalt `mateosss/basalt` !39: last note is our 09-21 answer; Mateo has not replied. Wait.
- NVIDIA PR #1275: open, `clean`, 1 comment, last update 09-17. Latest driver tag still 615.71.09.
- NVIDIA forum 337744: 18 posts, last 08-28.
- `Faulto/reverb-g2-linux`: no commits since the three of 09-23. Issue #1 on ours: open, no new
  comment.
- vronlinux.org hardware table: still "Bronze — experimental 6dof controllers, 60Hz-only on
  Nvidia" for the G2. Maintainers' call, not ours.

## 4. Housekeeping noticed

- Lab (`iashur`) root filesystem at **87%** (26 GB free), above the ~80% target.
- This machine's `reverb-g2` clone has a local, uncommitted edit to `scripts/jack-in-wayland.sh`
  (2026-09-17): the `VR=` path hard-coded to this box's workspace. Machine-local, deliberately not
  committed.

## Proposed next steps, in priority order

1. **Controller 6DoF: switch from our fork's fix to hare_ware's branch.** Build `9e1773326` on the
   lab, run it against the G2 with controllers, and record what works (tracking acquisition,
   latency, the "magical offset"). If it tracks at all, a short, factual test report on his
   branch's issue tracker is the most useful thing we can send upstream right now — it is data,
   not a nudge. Our docs/125/126 work becomes reference material for him rather than an MR.
2. **NVIDIA 615 minBpc** (carried over from docs/133): diff Faulto's `0006` against our port and
   fold the `minBpc` fix into PR #1275 with credit.
3. **Bluetooth dongle** (carried over from docs/128): still the one thing that unblocks rpavlik's
   point on !2967; buy the UB500.
4. **Lab disk**: free ~15 GB on `iashur` before the next large build or capture.
5. MR rebases: only when a reviewer engages; all seven are conflict-free today.
