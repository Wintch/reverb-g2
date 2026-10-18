# 148 — Basalt upstream sync and review, 2026-10-18

Status: review done, **patch 0022 compiled but not yet measured**. Nothing here has been
pushed anywhere.

## 1. What was checked

| Source | Result |
|---|---|
| `gitlab.com/mateosss/basalt` | A 2023 fork of VladyslavUsenko/basalt (last activity 2023-03-18; `master` last touched 2022-04-08; six old feature branches). Nothing new. The live project is `gitlab.freedesktop.org/mateosss/basalt`, which is our `origin`. |
| freedesktop `origin/main` | Still `df6e970`, our pinned base. No new commits. |
| New / moved branches there | `mateosss/efix` (09-20), `nikitakarpuks/controller-tracking` (09-17), `tsantucci/loop-closure` (09-07), `mateosss/lp` (08-28), `mateosss/brush-wip` (08-19). |
| MR !39 (recall leak) | No reply since our 09-21 answer to Mateo's "why recall?". Mateo's only newer activity is on issue #29 (HexVIO, not open yet). Do not nudge. |
| Faulto's fork (`Faulto/reverb-g2-linux`) | Last push 09-23. His Basalt patches 0001–0012 are identical to ours; his 0014 (hard-cap recall patch cache) is unchanged since the 09-18 comparison. Not in our series: his 0013 `BASALT_FEATURE_RECALL` env override (launcher convenience, skipped). |

## 2. What was added: patch 0022 (`mateosss/efix`, b8ac608)

One line in `include/basalt/optical_flow/optical_flow.h:222`: the essential matrix for
camera `i` was built from `T_i_c[1]` for every `i`; it is now `T_i_c[i]`. Cherry-picked
unchanged (author Mateo de Mayo kept) onto `lab` as `ede87bd`; patch file
`patches/basalt/0022-optical_flow-fix-multi-camera-essential-constraint-index.patch`.
`libbasalt.so` rebuilt on iashur 2026-10-17 23:35 (exit 0).

Review result (one reviewer + three adversarial verifiers, none could refute):

- **Correct.** `E = hat(t.normalized()) * R` of `T_c0_ci`, consumed as `p3d0^T E[cam_id] p3d1`
  — the same convention `trackPoints` uses. The old code was right only for `i = 1`.
- **Active on the G2 live path.** `optical_flow_type = frame_to_frame`,
  `optical_flow_epipolar_error = 0.005` in both G2 configs; `filterPoints()` runs
  unconditionally after `addPoints()`; the jack-in scripts load
  `build/libbasalt.so`.
- **Narrow effect.** Only `E[2]` and `E[3]` change (`E[0]` is never read, `E[1]` is
  identical), and only for keypoint ids present in both cam 0 and cam 2/3. Points
  detected independently in cam 2/3 are not tested.
- **Nothing downstream relied on the old behaviour** (`E` is read only in the three
  `filterPointsForCam` implementations).
- **Expected direction, unmeasured:** more cam0↔cam2/3 tracks survive, fewer outlier
  cross-camera observations. Possible cost: more observations in the optimizer, and the
  0.005 threshold was tuned under the old behaviour and may need a retune.

## 3. Series audit (0001–0022 vs `lab`)

- Base + the 21 patch files = the `lab` tree exactly (empty `git diff`). 21 files because
  0020+0021 share one file; numbering skips nothing else. `applies-on-base.txt`: 21 clean.
- No semantic conflicts between queue patches (0002/0009/0010/0021) or between the
  `prunePatches` patches (0014/0016/0018).
- README fixes made today (documentation only, no code): 0012 row added (it was missing);
  `VIT_COLLAPSE_LOG` is on for any value of the variable; 0009 flag-name note; 0021
  wording about deterministic mode and `BASALT_VISION_NONBLOCK=0`; 0014/0016 superseded
  notes plus the `frame_to_frame`-only coverage caveat; 0020 offset caveat.
- Open code nits, **not changed** (they need a rebuild and a live check): `age_in_ms` /
  `age_out_ms` are biased by `VIT_CAM_TIME_OFFSET_NS` (subtract the unshifted
  `s->timestamp`); stale comments in `prunePatches()` and the `BASALT_VISION_NONBLOCK`
  block of `vit_tracker.cpp`.

## 4. Upstream branches — verdicts

| Branch | Verdict |
|---|---|
| `nikitakarpuks/controller-tracking` | Name misleading: OptiTrack mocap ground-truth + calibration tooling for the **headset**; controllers explicitly out of scope. Do not merge. Keep `cam_calib.cpp:588-690` (`initCamExtrinsics` via Prim's algorithm; the old chain search left one camera at identity on a 4-camera rig) as a cherry-pick candidate for the next `basalt_calibrate` run. Merge is clean. |
| `tsantucci/loop-closure` | WATCH. Hash-BoW loop detection, PnP-RANSAC, pose graph, loop fusion; 106 commits from an older base (`72e01f7eb`), conflicts in `optical_flow.h`. Could cut long-term head drift; costs CPU; adopting means re-porting our series. Re-check after a rebase onto main. |
| `mateosss/lp` | Ignore. CI/dataset configs only (grid 40 / min_threshold 20 for EuRoC-type sets). Optional offline sweep arm. |
| `mateosss/brush-wip` | Ignore. Real-time Gaussian-splatting demo on top of loop-closure; CUDA/TensorRT; FoundationStereo (NVlabs) and Brush licences must be checked against the MIT policy before anything. |

Controller 6DoF is **not** a Basalt problem: docs/125 and docs/126 put it in Monado's
constellation blob-to-device correspondence (device owns 0 of 15 blobs, recovery needs 4).
No Basalt branch helps.

## 5. Faulto's NVIDIA minBpc — status found by the audit

His 0006 (615 port) carries the orthogonal `rgb444.minBpc = 8` gap for manuf `0x0E22` /
product `0x36C1`. Our local branch `g2-90hz-615.78.08` (929f2a98, unpushed, in the
open-gpu-kernel-modules clone) already has it, attributed and MIT, but it is **not** in
`patches/nvidia/` and docs/128 and docs/85 still call the gap open. Pushing it to PR #1275
may need his consent (NVIDIA CLA question, docs/144). Hold community posts until settled.
His 0003 uses `0x0E22`; our `0x220E` match is probably a no-op (docs/144, 829c452).

## 6. Test plan for 0022 (nothing run yet)

Principle: offline first, headset only if the offline result is non-null.

1. **Authorisation needed (changes iashur):** a control worktree `~/vr/basalt-ctl` at
   `9c4b60d` (= `lab` minus 0022) and a rebuild of `build-tools/basalt_vio` from `lab`
   HEAD, each in its own build dir; keep the 2026-08-27 binary as `basalt_vio.aug27`
   (it predates 0014 and is not a valid control). Disk is at 81 %.
2. **Offline A/B, no headset, no wearer.** Dataset
   `/mnt/videos/euroc/euroc-yaw2_20260829060819` (4 cameras, 9274 frames, calib
   `calib-g2-yaw2.json`). Serial, 1x, box idle. Runs: ctlA, ctlB, aftA, aftB (the A/A
   pair is the noise floor — replay is not deterministic). Metrics from
   `replay-basalt-variants.py`: drift windows, `landmarks_by_yaw_band`, `recall_ms`,
   `frontend_total_ms_p99`, `opt_ms_p99`, `filter_ms`. Offline cannot show
   `age_in/out`, queue depth or drops.
3. **Live, only if step 2 is non-null:** (A) at-rest soak, headset on the desk, lit room,
   **no controllers**, `soak-variant.py --tag ctl|after` swapping the lib by repointing the
   `build/libbasalt.so` symlink (restore and verify with `readlink` afterwards). (B) one
   worn yaw protocol with `EUROC_RECORD`, replayed through both builds so the wearer
   difference cancels. Controllers are not needed for 0022.
4. **Success:** cam 2/3 shared tracks up, drift and pose rate equal or better, frame time
   up by at most ~10 %. **Failure:** more drift/tracking loss or an optimizer spike —
   revert 0022 and retune `optical_flow_epipolar_error`. "No measurable difference" is a
   valid outcome.

Preflight before any live run: `preflight.sh`, no stray `monado-service`, remove the stale
`monado_comp_ipc`, wait for USB to settle, kill by PID (never `pkill -f` over ssh), no Steam
`KickingOtherSession`, no SteamVR-touching launcher (vrpath trap).

## 7. Housekeeping state

- `~/vr/basalt` on `lab`: HEAD `ede87bd`, clean; remote `gitlabcom` added (read-only
  fetch of the 2023 fork — safe to remove).
- `reverb-g2`: README, `applies-on-base.txt`, patch 0022 and this doc, **uncommitted**.
- Other AI sessions: none on iashur; two other Claude sessions on the local machine
  (`proxmox_server`, `bridgeai`), unrelated to these repos.

## 8. LVRA Matrix sweep, 2026-10-08 → 10-18 (read-only; nothing posted)

Six joined rooms; only `general` (4574 messages), `discord-driver-wmr` (9) and
`#announcements` (6) had traffic. Keyword-filtered (283 hits in `general`). Relevant:

- **Oasis WMR support promoted to stable** (announcement 10-09, mbucchia). The announcement
  asks for testers to write a wiki guide for wrapping WMR drivers with Monado's
  `steamvr_lh`. We already have Oasis working end to end on KDE X11 + host BT
  (docs/138); that is directly useful to them, and a candidate contribution — but see the
  community-post rules (thread replies only, no near-duplicates, no unprompted late posts).
- **xrizer v0.6 released** (10-09; dynamic linking by default, rolled-up contributions).
  Our `~/vr/xrizer` is `v0.5-34-gca3b270` with 14 local commits and an uncommitted
  `src/compositor.rs`; upstream `origin/main` is now 13 commits ahead. Not rebased.
- **`steamvr_drv` projection fix** (10-10, `discord-driver-wmr`): `GetProjectionRaw` in
  `ovrd_driver.cpp` negated top/bottom instead of swapping them ("double inversion").
  Affects Monado-as-SteamVR-driver rendering only, not our OpenXR path.
- 10-14 SLAM/constellation chat: general scepticism about SLAM controller tracking; one
  participant says a G2 on Monado was "the best" they tried. Nothing about our work,
  hare_ware or the constellation fix.
- No mention of Basalt, !2967/!2969, or our NVIDIA patches.
