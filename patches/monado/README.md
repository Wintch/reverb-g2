# Monado patches

Ten patches on top of Monado `main` @ `735e29e4e` (the SHA `bootstrap-lab.sh sources` pins).
They are the linear form of four independent MR branches prepared for upstreaming — see
[`docs/18-monado-upstreaming.md`](../../docs/18-monado-upstreaming.md) for the branches, the
review that shaped them, and the submission runbook.

| patches | MR branch | what |
|---|---|---|
| 0001–0004 | `wmr-hid-resilience` | tolerate transient HID errors: companion read loop, fw-read retry with reply validation, bounded status wait, BT thread error cap |
| 0005–0008 | `wmr-controller-input-fixes` | G2 squeeze click, G2 haptic output name, input timestamps + misc, opt-in `WMR_STICK_DEADZONE` |
| 0009 | `wmr-camera-stream-toggle` | `WMR_CAMERAS=0`: orientation-only, cameras never start |
| 0010 | `steamvr-drv-origin-rpath` | `$ORIGIN` runtime path on `driver_monado.so` for pressure-vessel |

All ten apply with plain `git am` onto the pinned SHA (verified: the resulting tree is
byte-identical to cherry-picking the four branches) and build with zero warnings.

Still needed on top for 90 Hz testing: the Project-VR nominal-frame-interval patch, see
`docs/04-lab-90hz.md` step 5.
