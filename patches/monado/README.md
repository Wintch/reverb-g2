# Monado patches

Twelve patches on top of Monado `main` @ `735e29e4e` (the SHA `bootstrap-lab.sh sources`
pins). The first ten are the linear form of four independent MR branches prepared for
upstreaming — see [`docs/18-monado-upstreaming.md`](../../docs/18-monado-upstreaming.md) for
the branches, the review that shaped them, and the submission runbook. 0011 and 0012 came
later (2026-08-06, 2026-08-07) and aren't part of that grouping yet.

| patches | MR branch | what |
|---|---|---|
| 0001–0004 | `wmr-hid-resilience` | tolerate transient HID errors: companion read loop, fw-read retry with reply validation, bounded status wait, BT thread error cap |
| 0005–0008 | `wmr-controller-input-fixes` | G2 squeeze click, G2 haptic output name, input timestamps + misc, opt-in `WMR_STICK_DEADZONE` |
| 0009 | `wmr-camera-stream-toggle` | `WMR_CAMERAS=0`: orientation-only, cameras never start |
| 0010 | `steamvr-drv-origin-rpath` | `$ORIGIN` runtime path on `driver_monado.so` for pressure-vessel |
| 0011 | (unfiled) | G2 driver was missing the native `microsoft/motion_controller` binding remap — every binding under that profile silently failed to resolve, not just one input. See `docs/03-controllers.md` |
| 0012 | (unfiled) | The bounded controller-status wait from 0003 used `&&` where it needed `||` — the loop exited the instant EITHER controller answered, not when BOTH did, so on the G2's shared HID channel the second controller (observed: always right) never got a chance to register. Reproduced 9/9 times; fixed and verified both controllers register every time now. See `docs/pruebas.jsonl` T051/T066. |

All twelve apply with plain `git am` onto the pinned SHA and build with zero warnings.

Still needed on top for 90 Hz testing: the Project-VR nominal-frame-interval patch, see
`docs/04-lab-90hz.md` step 5.
