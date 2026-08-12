# Monado patches

Eighteen patches on top of Monado `main` @ `735e29e4e` (the SHA `bootstrap-lab.sh sources`
pins) — **but two of them (0016, 0017) do not apply; read the box further down before
trusting this series.** The first ten are the linear form of four independent MR branches prepared for
upstreaming — see [`docs/18-monado-upstreaming.md`](../../docs/18-monado-upstreaming.md) for
the branches, the review that shaped them, and the submission runbook. 0011 came later
(2026-08-06) and isn't part of that grouping yet.

**Known sync gap (2026-08-11):** the lab machine's actual `g2-constellation-x11kde` branch
has real committed history well past what's exported here — at least a "fuse constellation
position into the controller's output pose" step and several freshness/clock-domain fixes
on top of it, referenced by their own commit messages as "0017" work. **That "0017" is a
different fix on a different checkout than this directory's `0017`** (the container_of bug
fix below, done on the everyday-system checkout) — the numbering collided by coincidence,
not by design. Don't assume this directory's numbering reflects the full state of the lab
branch; check `git log` there before assuming something past 0016 doesn't exist.

| patches | MR branch | what |
|---|---|---|
| 0001–0004 | `wmr-hid-resilience` | tolerate transient HID errors: companion read loop, fw-read retry with reply validation, bounded status wait, BT thread error cap |
| 0005–0008 | `wmr-controller-input-fixes` | G2 squeeze click, G2 haptic output name, input timestamps + misc, opt-in `WMR_STICK_DEADZONE` |
| 0009 | `wmr-camera-stream-toggle` | `WMR_CAMERAS=0`: orientation-only, cameras never start |
| 0010 | `steamvr-drv-origin-rpath` | `$ORIGIN` runtime path on `driver_monado.so` for pressure-vessel |
| 0011 | (unfiled) | G2 driver was missing the native `microsoft/motion_controller` binding remap — every binding under that profile silently failed to resolve, not just one input. See `docs/03-controllers.md` |
| 0012 | (unfiled, in progress) | First step of real 6DoF controller tracking: link `constellation` (the optical LED tracker rift/pssense already use) into `drv_wmr`. Build-only, no behavior change — nothing calls into it yet. See `docs/03-controllers.md` |
| 0013 | (unfiled, in progress, physically verified 2026-08-09) | Second step of 6DoF: split controller-tracking frames (frametype `0x2`) per camera in `wmr_camera.c` (previously dropped) and run LED blob detection on them via `t_rift_blobwatch`, visualized in a new "Controller Blob Cam N" debug GUI panel per camera. Still debug-only — no `t_constellation_tracker` wired up yet. Confirmed live with `XRT_DEBUG_GUI=1`: blob boxes track the LED ring in real time while moving a controller, and SLAM/controller rotation showed zero regression. See `docs/03-controllers.md` and the plan referenced from `NEXT-STEP.md`. |
| 0014 | (unfiled, in progress, verified live 2026-08-11) | Third step of 6DoF: `WMR_CONSTELLATION_CONTROLLERS` (default off) creates a `t_constellation_tracker` with one camera mosaic over the headset's tracking cameras and feeds 0013's blobs into it. The mosaic gets a *tracking source* reporting the headset's own pose rather than the fixed room pose a Rift sensor gets — the WMR cameras move with the head. No devices registered yet, so nothing solves and no pose changes — confirmed live: SLAM pose rate 30.1 Hz without it, 30.0 Hz with it. See `docs/pruebas.jsonl` T146. |
| 0015 | (unfiled, superseded by 0016) | Sets exposure/gain for the controller-tracking camera frames, which live in separate hardware slots from the SLAM ones, and gates the whole constellation path behind `WMR_CONSTELLATION_CONTROLLERS`. The controller frame stream is black on a G2 even with the LEDs plainly lit; this alone did not fix it (slot mapping and values were both wrong) — see 0016. |
| 0016 | (unfiled, verified live 2026-08-11, everyday system) | Corrects 0015's two wrong guesses (slot offset `+tcam_count` → flat `+2`; exposure/gain `400/1` → `6000/100`) and adds a clock-domain fix (`+cam_hw2mono`) for constellation frame timestamps. Confirmed live: `Controller Blob Cam N` panels went from solid black to real tracked LED blobs, and RANSAC-PnP started recovering real device poses (2000+ consecutive samples, reprojection error 0.04–0.10px). Left `get_tracked_pose` still reporting `position_tracked=false` due to what looked like a device-specific timestamp bug — see 0017, it wasn't device-specific. |
| 0017 | (unfiled, verified live 2026-08-11, everyday system) | Fixes a real bug in 0016's own `receive_ctrl_cam`: `container_of` was applied to an array element (`&ws->ctrl_ts_fix_sinks[i]`) instead of a whole-struct field, which only resolves correctly for `i==0` — for every other camera index it silently read garbage instead of the real `cam_hw2mono`/downstream sink. What looked like a "works for controller A, not B" bug was actually "works for physical camera 0, silently broken for 1–3," coincidentally correlated with which controller each camera happens to see most. Fixed with a small per-camera wrapper struct so `container_of` recovers the right instance regardless of array index. Confirmed live twice (incl. a full clean rebuild): `pushPose`'s sample timestamp now lands 5–40ms behind the host clock for every device/camera combination, and running `hello_xr` shows both controllers reporting `position_tracked=true` consistently. See `docs/pruebas.jsonl` T151. This closes out 6DoF constellation controller tracking end to end. **Does not apply to this series — see the box below.** |
| 0018 | (third-party: Project-VR) | Sets `screens[0].nominal_frame_interval_ns = 1e9/90` on WMR HMDs. `u_extents_2d_split_side_by_side()` leaves it at 0, so a downstream consumer computes refresh = 1/0 = infinite and falls back to 60 Hz, mis-pacing frames against the 90 Hz panel. **Scope caveat, from the commit message itself: the consumer it names is the SteamVR driver bridge**, not the native OpenXR path — whether its absence is visible through `jack-in-wayland.sh`/`hello_xr` or xrizer has **not** been measured, so don't claim it either way. Authored by Ashish Kumar Singh (`bf3a2e4b9`), lived only as a README footnote until T157. Applies clean on top of 0015. |

> ## THE SERIES IS BROKEN — 0016 and 0017 DO NOT APPLY (measured 2026-08-12, T157)
>
> This section used to read *"All seventeen apply with plain `git am` onto the pinned SHA
> and build with zero warnings."* **That is false.** Measured on the lab machine by
> applying the series from scratch onto `735e29e4e`:
>
> - **0001–0015 apply clean.** 0016 fails on three files at once:
>   `wmr_camera.c:37`, `wmr_controller_base.c:576`, `wmr_source.c:74`.
> - **Two of 0016's own pre-image blobs do not exist in this repository at all**
>   (`0eaa8be3e` for `wmr_controller_base.c`, `a0f87946f` for `wmr_source.c`). They were
>   generated against commits that were never exported — the "known sync gap" warned about
>   above is not a footnote, it makes the series unbuildable.
> - **Decisive**: 0016 tries to *add* lines to `wmr_camera.c` that the exported 0015
>   **already contains** (`DEBUG_GET_ONCE_BOOL_OPTION(wmr_constellation_controllers, …)`).
>   So 0016 was generated against a **different 0015** than the one exported here. Two
>   divergent histories, not one series.
> - Consistent with all of the above, the exported 0015 still carries the values 0016 is
>   supposed to correct (`DEFAULT_CTRL_EXPOSURE 0x0190` = 400, `DEFAULT_CTRL_GAIN 0x0001`
>   = 1, slot offset `camera_id + cam->tcam_count`), and `ctrl_ts_fix_sinks` — the struct
>   0017 fixes — **does not exist** in this tree's `wmr_source.c`.
>
> **What this costs:** `patches/monado/` cannot currently reproduce the lab build, which is
> the only reason this directory exists. This is the same failure class as T068.
>
> **Do NOT hand-apply 0016/0017's intent onto this series.** Hand-editing the live tree is
> exactly what caused T068 and a week of tests against the wrong binary. The fix is to
> re-export a consistent series from the checkout where 0016/0017 were developed.
>
> **Current buildable state**: `0001–0015` + `0018` (the 90 Hz patch) — 16 commits, builds
> with zero warnings, verified on the lab machine 2026-08-12. The constellation controller
> path stays at 0015's unvalidated state, but it is opt-in
> (`WMR_CONSTELLATION_CONTROLLERS`, default off), so nothing regresses.

Patches 0001–0015 and 0018 apply with plain `git am` onto the pinned SHA and build with
zero warnings. 0016 and 0017 do not — see the box above.

> ## UPDATE (2026-08-12): a second, unrelated cause of "6DoF isn't working on the lab" found — the handoff bundle itself was stale
>
> Separately from the loose-`.patch`-file divergence documented above, the **actual
> commits** for 0016/0017 live cleanly on the everyday system's own `monado` checkout,
> branch `g2-constellation-x11kde` — confirmed 28 commits ahead of that checkout's own
> `main` with **zero drift** between them (no rebase conflicts on that side at all). The
> durable handoff bundle
> (`~/Documents/linux_vr_base/g2-constellation-x11kde.bundle` on the everyday system) used
> to get this branch onto the lab machine was created 2026-08-11 and **never regenerated
> after the two commits that actually fix the bug landed later that same night** — so a
> lab build from that bundle would have had the exposure fix but not the `container_of`
> fix that makes `position_tracked=yes` report correctly. That reads exactly like "we saw
> it, it's not quite there" rather than "nothing happened", which is what was reported.
>
> The bundle has been regenerated and the stale copy overwritten in place, plus a fresh
> copy left on the lab disk directly. **Recommended recovery path — fetch the branch as
> real commit objects instead of hand-applying `.patch` files**, which sidesteps the
> divergent-history problem above entirely (a bundle carries the actual objects, not text
> hunks that need a matching parent to apply):
>
> ```bash
> git fetch /path/to/g2-constellation-x11kde.bundle g2-constellation-x11kde:g2-constellation-x11kde
> git checkout g2-constellation-x11kde
> git log -1 --oneline   # should show 7cb73701b "Fix container_of misuse in receive_ctrl_cam..."
> ```
>
> **Update, same day**: the branch is now already fetched into the lab machine's own
> `~/vr/monado` checkout (as local ref `g2-constellation-x11kde`, confirmed tip
> `7cb73701b`) — done via the mounted disk from the everyday system, without touching the
> lab checkout's then-current branch (`lab-90hz-0017`) or working tree. Whoever picks this
> up on the lab side just needs `git checkout g2-constellation-x11kde && ./build.sh` (or
> the project's usual build invocation) — **the build itself is still not verified**, that
> remains the concrete next step. See `docs/30-machine-handoff-protocol.md` for the
> general protocol this incident led to.

**A twelfth patch existed briefly (2026-08-07) and was retracted (2026-08-08).** It "fixed"
an AND/OR bug in 0003's bounded controller-status wait, reproduced 9/9 times in a real
session. Turned out the bug only existed in a hand-edited lab build that had drifted from
this tracked series — applying 0001–0011 fresh via `git am`, with zero manual edits, never
reproduces it (0003 already has the correct form). The apparent bug was an artifact of the
drifted live tree, not something wrong with the tracked patches. Full postmortem in
`docs/pruebas.jsonl` T068 and the (now-historical) correction in this repo's git log. Lesson
learned: the lab's built-and-tested binary must periodically be reconstructed from a clean
`git am` of this directory, not just accumulated live edits, or drift like this can hide for
a long time behind a plausible-looking "found a real bug" story.

~~Still needed on top for 90 Hz testing: the Project-VR nominal-frame-interval patch, see
`docs/04-lab-90hz.md` step 5.~~ **Closed 2026-08-12 (T157): that patch is now exported as
`0018` in this directory.** Leaving it as a prose footnote cost real time — the T068 clean
rebuild silently dropped it, and every lab binary built from `patches/` between 2026-08-08
and 2026-08-12 ran without it. A patch the build needs belongs *in the series*, not in a
sentence at the bottom of the README.
