# Monado patches

Seventeen patches on top of Monado `main` @ `735e29e4e` (the SHA `bootstrap-lab.sh sources`
pins). The first ten are the linear form of four independent MR branches prepared for
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
| 0017 | (unfiled, verified live 2026-08-11, everyday system) | Fixes a real bug in 0016's own `receive_ctrl_cam`: `container_of` was applied to an array element (`&ws->ctrl_ts_fix_sinks[i]`) instead of a whole-struct field, which only resolves correctly for `i==0` — for every other camera index it silently read garbage instead of the real `cam_hw2mono`/downstream sink. What looked like a "works for controller A, not B" bug was actually "works for physical camera 0, silently broken for 1–3," coincidentally correlated with which controller each camera happens to see most. Fixed with a small per-camera wrapper struct so `container_of` recovers the right instance regardless of array index. Confirmed live twice (incl. a full clean rebuild): `pushPose`'s sample timestamp now lands 5–40ms behind the host clock for every device/camera combination, and running `hello_xr` shows both controllers reporting `position_tracked=true` consistently. See `docs/pruebas.jsonl` T151. This closes out 6DoF constellation controller tracking end to end. |

All seventeen apply with plain `git am` onto the pinned SHA and build with zero warnings.

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

Still needed on top for 90 Hz testing: the Project-VR nominal-frame-interval patch, see
`docs/04-lab-90hz.md` step 5.
