# 127 — Session 2026-09-17 (comms side): hare_ware's constellation branch, the "old interface" claim that was wrong, the MRs rebased with changelog fragments, PR #1275 ported to 615.71.09

The everyday box's job today was "fijate si hubo novedades" and then whatever the news
justified. Channels swept read-only: GitLab (Monado MRs, hare_ware's fork), GitHub (NVIDIA PR,
Faulto), the NVIDIA forum, LVRA Matrix. Public actions were all approved by the user before
posting and are signed Nikolai. Times are UTC. Companion records: `docs/18` (status log rows
08-30 → 09-18, added today), the dev handoff `handoff-20260917-hareware-ab/HANDOFF.md`
(outside this repo, on both machines, see §6), `docs/125`/`docs/126` (the tracking state this
session's comparison stands on).

## 1. What was new, channel by channel

| channel | state found | action |
|---|---|---|
| GitLab monado MRs | no reviewer activity on any of the five since rpavlik's 09-08 comment on !2967; `main` +17 commits (`a6d31c6c1` → `09741cbcb`, 09-16), zero file overlap with our branches, !2968 / !3004 back to `need_rebase` | all five rebased, changelog fragments added, pushed — §4 |
| LVRA Matrix `#general` | two members remarked that the constellation tracker now in Monado `main` has "a very different interface" from thaytan's branch; nobody mentioned this project | none posted; the remark led to a wrong conclusion here, corrected — §3 |
| hare_ware/monado | branch `wmr-new-constellation-tracking`, tip `cb98ebaee` (09-13, 16 commits on `a6d31c6c1`): a second WMR→constellation wiring, parallel to `patches/monado/0012–0018` | read commit by commit, then an issue on the fork — §2, §3 |
| GitHub NVIDIA/open-gpu-kernel-modules#1275 | `mergeable_state: dirty` after the 615.71.09 drop refactored the function the patch touches; 0 reviews, 0 new comments | rebased and force-pushed — §5 |
| NVIDIA forum 337744 / 379240 | unchanged (#18 abchauhan "Engineering is reviewing" is still the last word) | none |
| GitHub Wintch/reverb-g2 #1 (Faulto) | open, no new comments; Faulto's fork unchanged since `247f66a` (08-27) | none; the Basalt `0014` vs `0014` diff is still owed |
| LVRA wiki (`lvra/lvra.gitlab.io`) | the G2 row still says "60Hz-only on Nvidia"; commits through 09-14, none touching it | none — it is Mega's MR to send (`docs/88` §1) |

## 2. hare_ware's branch, read against ours

Both wirings sit on the **same upstream tracker**: `src/xrt/tracking/constellation/` has been in
Monado `main` since 2026-03-26 (first commit `64de5eb8d`, the blobwatch implementation, authored
02-14 and merged by Marge Bot five weeks later); `68a4a3767` (2026-09-11) only added the
`XRT_MODULE_CONSTELLATION_TRACKING` CMake option. Our
`0014` creates its tracker through `constellation/t_constellation_tracker.h`; hare_ware's branch
does the same. What differs is the WMR-side glue. Verified on his tip, and stated in the issue:

- `wmr_camera.c:531` is `for (int i = cam->tcam_count; i < cam->tcam_count; i++)` — a dead
  loop, so `wmr_camera_set_ctrl_exposure_gain` is never called and the controller cameras run
  at whatever exposure the firmware defaults to. His own fix for that line, `0a176c224`, sits on
  his `wmr-tinkering` branch and is not in `wmr-new-constellation-tracking`. On our G2 that
  state gave fully black controller frames (exposure readback 0).
- The controller-camera slot is `config->location + 2`. G2 camera locations are 0, 1, 4, 5; with
  `location + tcam_count` the command succeeds but the exposure readback stays 0, with `+ 2` it
  follows the requested value (patch `0015` as corrected in `docs/pruebas.jsonl` T149).
- Exposure/gain: we saw 400/1 black and 6000/100 clean blobs at rest, **with the driver never
  sending an LED intensity** (firmware default), one dark-room session, battery uncontrolled.
  His branch sends 200 once in the timesync packet, so the numbers may not carry over.
- Things his branch has that ours does not: an LED-ring self-occlusion model, separate aim and
  grip pose offsets. Things ours has that his does not: the blob-ownership fix (`docs/126`), the
  Rx180 bridge and the gravity gate (patch `0047`), the LED-intensity resend
  (`WMR_CONTROLLER_LED_INTENSITY` / `WMR_CONTROLLER_LED_HZ`).

The rest of the read — how his tracking source is registered, how the pose reaches the device,
where the tracker origin sits — produced predictions, not measurements. They are in the dev
handoff (§6) with the test that settles each one, and stay out of this doc and out of the issue
until a build has run.

## 3. The issue on hare_ware/monado, and the sentence that was wrong

Posted 16:28Z as issue #1 on `hare_ware/monado`
(`gitlab.freedesktop.org/hare_ware/monado/-/work_items/1`), over the API — Akismet blocks MR
creation over the API but not issue creation, a new data point for `docs/18`'s access notes.
Content: the three findings above, an offer to build his branch on the G2 and send logs, no ask.

Two drafts died before it went out:

1. **v1** attributed the dead loop to thaytan (it is hare_ware's own commit `392aac374`;
   thaytan is only `Co-Authored-By`) and did not know he had already fixed it on
   `wmr-tinkering`. Caught by a review pass that re-read the branch history instead of trusting
   the summary.
2. **v2, as posted, carried one wrong clause**: that our `0012–0018` "target the old
   interface" while his branch targets the upstream tracker. That came straight from the Matrix
   remark in §1 plus a commit title ("Add … build option") read as "module is new". Only *his*
   side had been checked against the code. A grep of our own patches shows `0014` on the same
   upstream header. Two reviewers had flagged the sentence; it was dismissed. **Edited 17:46Z**
   (the clause now reads "Your branch and my series both wire WMR into the upstream
   constellation tracker"), the retraction is recorded in memory, and the rule that comes out of
   it is the one `docs/126` §8 applies to readings, applied to code: **verify both sides of any
   comparison against primary sources before publishing it** — "they are on X, we are on Y" needs
   a grep of *our* code too.

No reply from hare_ware as of 2026-09-18 00:40Z. Do not nudge; the next message to him is a
test result from the handoff, or nothing.

## 4. Monado MRs: rebased onto `09741cbcb`, runbook step 5 done, all green

`docs/18`'s status log has the row. Short form: every branch rebased clean (`range-diff` `=`
on every code commit), then one final commit per branch, `doc: Document !NNNN`, carrying the
changelog fragment (`doc/changes/drivers/mr.{2967,2968,2969,3004}.md` with `d/wmr:`,
`doc/changes/misc_fixes/mr.2971.md` with `build:` — a prefix upstream's `CHANGELOG.md` already
uses for CMake-only fixes; `t/steamvr_drv:` has no precedent there). A two-agent review caught four wording errors in the fragments before the
push ("during startup" for a session-long tolerance; "BT" where the changelog never
abbreviates; the `t/steamvr_drv:` prefix; "Linux only" covering the back-off, which is not
`#ifdef`'d). Pushed by the user with an explicit `--force-with-lease=<branch>:<old-sha>` per
branch. Pipelines green; !2971's `alpine` job segfaulted once in `tests_worker` (upstream's
thread-pool test, a flake) and passed on retry.

rpavlik's 09-08 comment on !2967 (the controllers *can* be re-paired to system Bluetooth)
was answered 2026-09-18T00:27Z, note 3667686: the adapter on hand was dead; will get a working
one, re-pair, run `wmr_bt_controller.c` for real and report either way. **That is a promise
with a shopping item attached** (TP-Link UB500 / UB500 Plus, RTL8761B; the Nisuta on hand never
enumerates) and a dev-session test behind it — the same setup also unlocks controllers under
Oasis/Ignition.

## 5. NVIDIA PR #1275 ported to 615.71.09

615.71.09 refactored `nvDpyGetOutputColorFormatInfo()`: the 6-bpc clamp for DisplayPort sinks
is still `if (info->input.u.digital.bpc < 8)` (now `nvkms-dpy.c:3715`), and a new helper
`GetMaxOutputColorBpc()` returns 8 bpc for `edidBpc == 0` in the else branch. So the fix is the
same guard in the new place:

```c
-                if (info->input.u.digital.bpc < 8) {
+                if (info->input.u.digital.bpc != 0 &&
+                    info->input.u.digital.bpc < 8) {
```

Branch `fix-dp-6bpc-clamp-undefined-edid-depth` `9644d29` → `d2028a1` (tag
`backup/pr1275-pre-615` on the old tip), pushed over SSH as Wintch; GitHub shows
`mergeable: true` again. **Compile-tested only** against 615.71.09; the runtime verification is
the 595.71.05 one (`docs/19`) plus babblebones' independent confirmation in forum post #16.
The PR comment saying exactly that is drafted and waits for the user to paste it (no GitHub
token here). Commit message has no trailers (CLA repo).

## 6. Handoff to dev: `handoff-20260917-hareware-ab/HANDOFF.md`

Delivered to `~/Documents/linux_vr_base/handoff-20260917-hareware-ab/` here and
`iashur:~/Documents/handoff-20260917-hareware-ab/` (same md5). Two phases, desk only, with the
user's OK for the dashboard/kiosk services:

- **Phase A, on `lab-full`**: four runs, exposure 6000/100 vs 400/1 × `WMR_CONTROLLER_LED_INTENSITY`
  0 vs 200, all with `WMR_LOG=info` (the override proof line and the `constellation sample`
  telemetry are INFO and silent at the default `warn`). Settles whether the exposure numbers
  in the issue survive a driven LED ring.
- **Phase B, hare_ware's branch**: fetch his two branches, detached worktree at
  `~/vr/monado-hareware`, cherry-pick `0a176c224`, build, hand-launch with the pre-launch
  sequence and its own log file, confirm `Using builder wmr`, then a nine-item checklist
  (B1–B9) that turns each prediction from §2 into a yes/no.

Ground rules restated in the file: no sudo, no `git push` to anyone's remote, no posting; the
result comes back here and the next public message is written from it.

## 7. Housekeeping

- Everyday box root fs was at 81 %: a stale scratch build (1.8 G) removed, then the user ran
  `apt clean` + a journal vacuum (`SUDO_ASKPASS=/usr/bin/ksshaskpass sudo -A …` is the way to
  sudo from here — a bare `! sudo` has no TTY) → 76 % right after the cleanup. iashur was at
  86 %, enough for one more Monado build, not touched.
- This clone's `scripts/jack-in-wayland.sh` has an uncommitted local edit (an absolute `VR=`
  path for this machine, 09-10). It is deliberate and must never be committed; stash around
  pulls.
- The Matrix token supplied today is on disk with mode 600 and should be rotated; it dies on
  its own in ~24 h anyway.

## 8. Open, in priority order

1. Dev: run the handoff (Phase A first). Its result decides the next message to hare_ware.
2. User: paste the PR #1275 comment; buy the UB500; rotate the Matrix token.
3. Dev, once the dongle exists: the system-Bluetooth `wmr_bt_controller.c` test promised on
   !2967, reported on that thread whatever the result.
4. ~~Comms: diff our Basalt `0014` against Faulto's `0014` (owed since 08-28).~~ Done, §9.
5. Nothing to post anywhere until one of the above produces a fact.

## 9. Addendum (2026-09-18 ~01:15Z): the Basalt recall leak is upstream's, and upstream already has a stalled fix

The diff owed since 08-28 turned out to be a three-way comparison. `mateosss/basalt` `main` still
carries `// TODO: Patches are never getting deleted` (`frame_to_frame_optical_flow.h:590`), so the
leak both forks bounded is upstream's; recall is off by default upstream and in our shipped
`basalt-g2-config*.json`, which is why it never bit production here. Mateo's own fix, **!39 "Free
feature patches used in recall"** (2023-11, last push 2024-03, `need_rebase`, debug `printf`s still
in), routes `removed_lmids` from the backend to the frontend and stalled, per his 2023-12 note, on
never being sure when a landmark is gone from both threads. Issue **#25** (2025-10, open) is an
`out_of_range` in `recallPointsForCamera()` — plausibly the `patches.at()` both forks turn into
`find()`.

Faulto's series is our `0001–0012` imported unchanged (his README credits this repo) plus his own
`0013` (recall-mode env var) and `0014`: a 16384-entry cap that, when hit, keeps the bundle ids and
the last 4096 ids, erases the rest, and stops storing new patches while the cap is full. Ours
(`0014`+`0016`+`0018`) is time-based, 90 frames of grace, amortised sweeps; it costs more memory
(1.1–1.7 GB steady vs ~40 MB) and keeps recall working. An unmeasured inference, kept out of the
public comment: at our ~1,950 detections per frame his 4096-id grace is about two frames, less than
the bundle's lag, so his version is a sound OOM guard that probably recalls little.

Posted with the user's approval as **note 3667707 on !39** (signed Nikolai): the two field
measurements (18 GB in 3 min here, ~49 GiB per hour on Faulto's rig), our approach in one
paragraph, and an offer to turn it into an MR with the env var made a config field. Next move is
Mateo's; if he takes the offer, the MR needs the three patches squashed, the `reverb-g2` markers
removed, their clang-format, and a rebase onto their `main`. The `patches/basalt/README.md` entry
for `0014` now carries the upstream pointer.

## 10. Addendum (2026-09-18, 01:30–03:40Z): the upstream queue, two new MR branches, tested on the desk headset

The user left the headset and controllers on, which turned "prepare MR #6" into "prepare and test it".

### 10.1 Triage of the lab entries marked upstreamable (five verifiers, all against `main` `09741cbcb`)

| lab patch | verdict | why |
|---|---|---|
| 0096 (`cam->running = true`) | **already upstream** | Christoph Haag, `8ed03a5cf`, 2026-09-07, !3005 |
| 0095 (join the USB thread in `stop()`) | **superseded, rewritten** | the thread is started in `open()` and joined in `free()`; a join in `stop()` breaks `stop()`→`start()`. Upstream's own `c236c11fd` (Mateo, !2937: callback returns early when `!running`) shrinks the window but leaves two holes: the callback already past the check, and its unconditional resubmit at `out:` after a cancel that found nothing |
| 0106 `cam_count` | **MR-ready, done** | present in `euroc_runner.c:95` and its twin `p_tracking.c:268`, both from `c39dc977c` (the commit that added `EUROC_CAM_COUNT`). The `SLAM_BATCH_POLL_HZ` half is a behaviour change and stays out |
| 0026 (`pushPose` gating) | still present, **needs care** | `3c001896d` "Always trust RANSAC" (Beyley, 08-27) made `tryDeviceBlobRecovery` bypass `POSE_MATCH_GOOD` on purpose; a bare re-check at the push site would silently undo that. Three callers now, not two |
| 0104 (`t_slam` push-after-stop guard) | valid, complementary | node order is LIFO so the tracker is broken apart before the camera on every driver; needs a headless repro via the EuRoC player and the lab-only `correction.mutex` reference stripped |
| 0044 (filter before predict) | **issue first** | the filters are opt-in and GUI-only upstream; half the patch's rationale (the divergence guard) is lab-only code |

### 10.2 Branch `wmr-camera-stop-drain` (fork tip `30da35bbf`, two commits)

`wmr_camera_stop()` now counts the submitted image transfers under a dedicated `os_mutex`, cancels
them, and waits (bounded, 500 × 1 ms, then a warning, as `uvc_fs_stream_stop()` does) until each
has had its final completion; `img_xfer_cb()` decides between resubmit and retire under the same
lock, so a stop landing mid-frame retires instead of resubmitting onto a camera told to stop. The
USB thread is untouched. Second commit removes the vestigial trailing `os_thread_helper_wait_locked()`
in the USB thread (upstream's own `@todo`): a lost-wakeup hang of `wmr_camera_free()`'s join.
Three reviewers found no correctness hole in the final shape; they caught an init `||`
short-circuit, the unbounded wait, and over-long commit messages, all fixed before the push.

**Test, on iashur, no compositor**: `scripts/wmr-camera-teardown-cycles.sh` runs one
`monado-cli probe` process per cycle with `WMR_SLAM=1` (creates the HMD, streams the cameras
through Basalt, destroys everything). 40 cycles on unpatched `main`, 40 on an interim variant
(condition variable instead of the bounded poll), 40 on the final: **0 SIGSEGV, 0 hangs**, camera
started and stopped in every log, no "still in flight" warning. The baseline was also clean: the
window is narrow and the lab's 20+ cores came from game teardowns, so the MR argues from the code
and reports the counter honestly. Logs: `iashur:~/vr/camstop-test/{baseline,patched,final}/`.

### 10.3 Branch `euroc-playback-cam-count` (fork tip `96ff5d895`, one commit, two lines)

Reproduced headless with the 08-27 yaw recording:
`EUROC_CAM_COUNT=2 EUROC_MAX_SPEED=1 VIT_SYSTEM_LIBRARY_PATH=~/vr/basalt/build/libbasalt.so
monado-cli slambatch ~/vr/logs/euroc/euroc-yaw_20260827170436 g2.toml out` where `g2.toml` carries
`cam-calib="~/vr/logs/calib-g2-2cam.json"` (slambatch's default config has no calibration; the
G2's own dump trimmed to two cameras is what `replay-euroc.sh` builds). Before: `Basalt with
cam_count=4`, then Basalt's `calib_cam_count == cam_count` assert and a hang until `timeout`.
After: `cam_count=2`, the whole dataset plays, 2842 rows in `tracking.csv`, exit 0 in 43 s.

### 10.4 State at the end of the session, and how to resume

- Both branches are on `Wintch/monado`; **the MRs are not created** (Akismet: web form only). Titles
  and descriptions: `docs/upstream/mr-texts-2026-09-18.md`; the patches themselves:
  `docs/upstream/wmr-camera-stop-drain-000{1,2}-*.patch`, `docs/upstream/euroc-playback-cam-count-0001-*.patch`.
- Once the MR numbers exist: add one `doc: Document !NNNN` commit per branch
  (`doc/changes/drivers/mr.NNNN.md`, `d/wmr:` for the first, `d/euroc:` for the second), push,
  add the rows to `docs/18`, check the pipelines.
- The branches also exist as local branches of `~/Documents/linux_vr_base/monado` on the everyday
  box (`git worktree prune` there if the scratch worktrees are gone). On iashur:
  `~/vr/monado-camstop` (worktree of `~/vr/monado`, branch `wmr-camera-stop-drain` + the euroc
  commit on top, 501 MB build) and `~/vr/camstop-test/` (harness copy, logs, patches). Delete the
  build once the MRs are green; `~/vr/monado` itself was not touched.
- Next in the queue: 0026 as an MR that respects `kAlwaysTrustRansac` (gate only the pushes whose
  score was actually re-evaluated, or gate on the refined score only when refinement ran), 0104
  with a EuRoC-based reproduction, 0044 as an issue with the +42.5 ms measurement.
- Related, same night: `mateosss/basalt` !39 got our comment (§9); Faulto's issue and hare_ware's
  issue unchanged.

