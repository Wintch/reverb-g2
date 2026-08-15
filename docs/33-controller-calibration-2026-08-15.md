# WMR controller calibration — 2026-08-15

This investigation and its tooling were carried out collaboratively by the
project owner, Claude, and Codex (OpenAI's coding agent).

## Resultado

The HP Reverb G2 headset reached real HMD 6DoF and both WMR controllers could be
paired and queried directly. Controller position tracking remained intermittent:
when constellation data was absent, Monado correctly exposed a placeholder pose,
which looks like a 3DoF-anchored hand in the application.

The headset USB preflight is therefore a hard gate. A valid session requires
`./scripts/preflight.sh` to report all `5/5` USB devices before starting Monado.
During the final interruption the preflight reported only `2/5`, while both
controllers were online. This is not sufficient for spatial hand tracking: the
missing headset companion/camera interfaces prevent the constellation path from
providing reliable positions.

## Measurements

The calibration logger was added to the external Monado checkout at
`/home/iam/vr/monado/src/xrt/drivers/wmr/wmr_controller_base.c`. With
`WMR_CONTROLLER_CALIBRATION_LOG=1` it records:

- raw fused IMU quaternion (`q_imu`);
- final output quaternion (`q_out`);
- IMU age;
- position/orientation tracking flags;
- angular velocity;
- output position.

The gizmo tests showed that a pure physical roll could move the OpenXR forward
vector through `UP`, `AWAY`, `AT-ME`, `LEFT`, and `DOWN`. This proves the issue is
an IMU-to-controller frame mismatch, not merely a low-angle scale error.

Controlled tests were performed for roll, pitch, and yaw on each controller.
The right-controller yaw was repeated after the first capture mixed with roll;
the repeated axis was approximately `(-0.132, -0.989, -0.075)`, sufficiently
separate from its roll axis to produce a usable first full-frame fit.

## Software experiments

The following temporary A/B options were added externally and should not be
treated as upstream fixes until the USB/constellation path is stable:

- `WMR_CONTROLLER_IMU_TO_DEVICE` and opposite-composition experiments;
- `WMR_CONTROLLER_WMR_AXES` (Rx180);
- `WMR_CONTROLLER_FULL_CAL_RIGHT` with the first fitted right-hand frame;
- `WMR_CONTROLLER_RIGHT_ROLL_180`;
- `WMR_CONTROLLER_FULL_CAL_LEFT`;
- `WMR_CONTROLLER_LEFT_YAW_MINUS90` (rejected: it fixed a static direction but
  mixed the left pitch and roll axes).

The right full-frame fit improved roll subjectively, and the user reported that
right yaw was correct. The left yaw-only offset was rejected after the user
reported that left pitch appeared as roll. The next valid A/B run must use both
controllers with `5/5` USB and inspect spatial position and all three axes
together.

The offline helper committed in this repository is
`scripts/wmr-fit-roll-axis.py`. It estimates a dominant controller-local roll
axis from `CALIB` quaternion samples; it deliberately does not apply a matrix
automatically.

## Reproduction rules

1. Run `./scripts/preflight.sh`.
2. Do not start Monado unless USB is `5/5` and the DP/EDID check passes.
3. Keep the tested controller moving so its IMU does not enter the firmware idle
   zero-packet state.
4. Treat `pos:OK trk:--` or the placeholder position `(-0.200, 1.200, -0.500)`
   as invalid position data, not as a calibration sample.
5. Restart Monado when changing which controller is present at startup; an
   unregistered controller cannot be assumed to hot-add cleanly.
