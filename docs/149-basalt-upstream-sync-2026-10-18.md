# 149 — Basalt upstream sync and review, 2026-10-18

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

## 9. Offline A/B of 0022 — result: no measurable difference (2026-10-18)

Setup: `euroc-yaw2_20260829060819` (4 cameras, 9273 frames, 308 s), config
`~/vr/basalt-g2-config.json`, 6 threads, 1x, serial and interleaved ctl/after/ctl/after.
`ctl` = `~/vr/basalt-ctl` at `9c4b60d` (lab minus 0022); `after` = `lab` at `ede87bd`; both
`basalt_vio` built 2026-10-17 (the 08-27 binary is kept as `basalt_vio.aug27`). Script:
`~/vr/run-0022-ab.sh`; raw output `~/vr/logs/replay-0022/{ctlA,ctlB,aftA,aftB}/`.

| metric | ctlA | ctlB | aftA | aftB |
|---|---|---|---|---|
| wall s | 332.5 | 329.8 | 330.9 | 330.3 |
| rms ATE m | 0.5292 | 0.5291 | 0.5280 | 0.5280 |
| position span m | 1.633 | 1.641 | 1.635 | 1.635 |
| max 1 s displacement m | 0.6858 | 0.6859 | 0.6859 | 0.6859 |
| windows > 0.5 m / > 1 m | 4 / 0 | 4 / 0 | 4 / 0 | 4 / 0 |
| frontend p99 ms | 41.43 | 41.03 | 41.31 | 40.95 |
| optimizer p99 ms | 18.60 | 18.89 | 18.24 | 18.54 |
| landmarks p50 / p10, 0-30 deg/s | 146 / 34 | 154 / 40 | 150 / 44 | 150 / 44 |
| landmarks p50 / p10, 30-90 | 207 / 35 | 207 / 35 | 207 / 34 | 207 / 34 |
| landmarks p50 / p10, 90-180 | 118 / 5 | 118 / 5 | 118 / 5 | 118 / 5 |
| landmarks p50 / p10, 180-360 | 24 / 0 | 24 / 0 | 24 / 0 | 24 / 0 |
| keypoints p50 (all bands) | identical to ±2 | | | |

Reading: every difference between ctl and after is inside the ctlA/ctlB spread (the noise
floor: the 0-30 deg/s landmark p10 moves 34→40 between two identical control runs). No
regression in drift, ATE, landmark survival or frame time; no gain either.

Why this is the expected outcome: with `optical_flow_detection_nonoverlap = true`, the epipolar
filter only judges ids shared by cam 0 and cam 2/3, and the optical axes of cam 2 and cam 3
are 76.6° and 95.9° from cam 0 (cam 1: 19.4°) in `calib-g2-yaw2.json`. Cross-camera
matches between cam 0 and the side cameras should be rare, so the line changes almost
nothing for this rig. This was inferred from the geometry; the number of surviving
cam0↔cam2/3 matches was **not** instrumented.

Decision: keep 0022 (it is a correctness fix, harmless here, and it matters for rigs whose
cameras overlap); **no headset session is justified for it** — the plan's gate was "live
only if the offline result is non-null". Caveats: one dataset (yaw protocol), one config,
replay feeds every frame (`outq_dropped=0`), and this proves nothing about `age_in/out` or
the queue patches, which only exist on the live path.

Residue: `~/vr/basalt-ctl` (worktree + build, a few GB) can be removed with
`git -C ~/vr/basalt worktree remove --force ~/vr/basalt-ctl`; kept for now so the A/B can be
re-run.

## 10. Closing the Wayland gap for Oasis — LabWC and Hyprland (2026-10-18, in progress)

Why: the LVRA announcement of Oasis going stable asks for testers; our rule is to leave
nothing for others to test that we can test ourselves. Wayland for Oasis is **already
tested and negative** (docs/119, 121, 122): X11 only works with the panel guard (docs/138);
GNOME/mutter offers the lease but Oasis' `vrcompositor` loses a roundtrip race; KWin and
Sway offer `wp_drm_lease_device_v1` with zero connectors on NVIDIA
(`NVIDIA/open-gpu-kernel-modules#251`). Not yet tested: LabWC and Hyprland.

- **LabWC 0.8.3**: installed from apt (user ran `sudo apt install labwc`). wlroots-based, so
  the expectation is the Sway result; this is to confirm, not to assume.
- **Hyprland**: not in Debian 13, and the latest (0.56.2) cannot build there
  (`wayland-protocols` ≥ 1.49, `libinput` ≥ 1.29, Lua 5.5 vs Debian 1.44 / 1.28 / 5.4).
  **v0.50.1** matches Debian's libraries. Hyprland has its own DRM-lease implementation
  (`src/protocols/DRMLease.cpp`, on aquamarine, not wlroots), so it is an independent test.
  Built in user space only: `scripts/build-hyprland-userspace.sh` →
  `~/vr/hyprland-build/prefix` (hyprwayland-scanner 0.4.5, hyprutils 0.8.1, hyprlang 0.6.3,
  hyprland-protocols 0.6.4, hyprgraphics 0.1.5, hyprcursor 0.1.12, aquamarine 0.9.2,
  Hyprland v0.50.1, `clang-19`, XWayland/uwsm/hyprpm off). C++26 needs two local patches
  for Debian's libstdc++ 14 (`scripts/hyprland-v0.50.1-debian13.diff`: a `string +
  string_view` in `hyprctl/main.cpp:271` and `vector::insert_range` in
  `src/helpers/Monitor.cpp:552`) and `git submodule update --init` for `udis86`. The ~100
  `-dev` packages were installed by the user with sudo (agents must not sudo).
  `Hyprland --version` runs: `0.50.1 ... v0.50.1`.
- **Test harness**: `scripts/lease-test.sh <labwc|hyprland>`, run from a text VT
  (Ctrl+Alt+F3) with the headset connected and awake. It starts the compositor, runs
  `check-lease.sh` inside it, writes `~/vr/logs/lease-test-<name>-<stamp>.txt` and exits
  (90 s timeout). The KDE X11 session on the other VT is left alone.
- **Headset USB**: after the power cycle the headset was missing (0/5 devices, DP-1/2
  disconnected) until the user re-seated it at the PC end; then 5/5.

**Status: the two lease tests have NOT been run.** They need the user at a text console.

### Still open (so nothing is silently dropped)

1. Run `lease-test.sh labwc` and `lease-test.sh hyprland`; record the results here. If
   Hyprland offers the connector, try Oasis on top of it (needs the headset and the other
   AI sessions stopped).
2. Oasis wrapped through Monado's `steamvr_lh` — the thing the wiki asks for; never tried
   here (docs/138 is Oasis alone, "no Monado involved").
3. Headset audio under Oasis (none heard; Monado's `hmd-audio.sh` exists for the other stack).
4. Measured frame rate under Oasis (only "did not feel like 90").
5. Y, left stick click and left grip buttons (unconfirmed, not broken).
6. Do not post to LVRA until 2–5 are tested or explicitly listed as untested; the draft must
   say Wayland was tested and failed (not "untested") and pin the GPU and driver
   (Debian `nvidia-driver` 595.71.05 today; docs/122 ran 595.71.05-open).
7. Basalt: `age_in/out` offset bias and stale comments (§3) need a code touch; `cam_calib.cpp`
   `initCamExtrinsics` is a cherry-pick candidate for the next 4-camera recalibration.
8. `~/vr/basalt-ctl` (229 MB) can be removed once the A/B no longer needs a re-run.
9. Rotate the Matrix token pasted in chat on 2026-10-18 (Element → Settings → Sessions).
10. Uncommitted elsewhere on iashur, unexplained or already known: `vr/tracy-profiler`
    (`dtl/Diff.hpp` modified), `vr/xrizer` (`src/compositor.rs` modified, 14 local
    commits, upstream is 13 commits and a v0.6 tag ahead), `linuxlab-kit`
    (`rollback/manifest.jsonl` untracked).
