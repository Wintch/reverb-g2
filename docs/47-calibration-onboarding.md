# Calibration & onboarding: what is generic, what is per-unit, what to check on a new G2

Written 2026-08-18, after the calibration marathon (T196-T212) closed the controller
mapping with machine data. The question this answers: **if a second (third, tenth)
Reverb G2 arrives for the showcase, does the whole calibration process repeat?**

Short answer: **no**. Almost everything that graduated is model-generic driver code or
runtime self-calibration. The turntable/cradle/chair rituals were the *discovery*
process — they are not per-unit setup. A new unit should be: plug in, run the
validation checklist (~10 min), play.

## Layer 1 — model-generic fixes (ship as defaults, apply to every G2)

These correct **design-level** properties of the product line or plain driver bugs.
Nothing per-unit about them:

| what | patch(es) | why it's generic |
|---|---|---|
| Left controller gyro convention (half-turn about −Y composed on the Y-negation) | 0062 + 0071 | The fitted matrix is 179.93° about (0.077,−0.997,0.001) — within noise of a *perfect* half-turn about vertical. That is the industrial design of mirrored shells, not one unit's tolerance. Same class as the Rx180 flip `wmr_hmd.c` already applies to the HMD. Driver-convention bug: upstream candidate. |
| Companion backoff deadline-skip (the clock-skew root fix) | 0055 | Pure code: shared read-loop must never sleep. Universal. |
| Solve-yaw heading anchor + wrap + ghost-solve trust | 0066/0067 | Algorithmic; any WMR headset with constellation has no yaw reference and needs it. |
| Timestamp guards, queue shapes, ExecutionStats cap | monado 0021/0022, basalt 0010/0011 | Code fixes for the G2's real clock hiccups and Basalt's pipeline. Model-generic. |
| Basalt detection config for G2 cameras | `scripts/basalt-g2-config.json` | Tuned to 640x480 fisheye @30 Hz — per-model, identical across units. |
| Keepalive tick, stick deadzone default | 0058 driver tick, launcher env | Behavior-level. Universal. |

## Layer 2 — per-unit calibration that is ALREADY automatic

Each device carries its own factory calibration and the stack reads it at connect —
per-unit precision with zero manual steps:

- **Controller factory calib blocks** (gyro/accel mix matrices + Rt): read at every
  connect, logged since 0060/0063 with determinants. All-proper matrices on the two
  units measured; the log line is the health check.
- **HMD factory calib** (camera extrinsics, IMU calib): delivered by the device,
  parsed with no warnings (verified T162-era).
- **Stick centers** (0070, `WMR_STICK_AUTOCENTER=1`): measured in the first 5 s
  after connect, per stick, aborts safely if the user is touching the stick.
  The measured offsets double as per-unit health data (log them per unit).

## Layer 3 — genuinely per-unit residuals (small, and how to check them)

- **~4° full-stream residual** on the left matrix (RMS 4.25° at fit). Some share may
  be unit tolerance. Below normal perception in-game; the solve-yaw anchor absorbs
  slow yaw wind whenever the controller is camera-visible. If a future unit feels
  worse: one turntable-roll + one cradle-yaw capture per hand (~12 min) re-derives
  the matrix with the scripts in the repo history (T209/T210 method).
- **Battery cells**: per-cell chemistry curve is generic (NiMH, docs/46); per-cell
  *health* is inventory (the named-cell roster, docs/battery.jsonl).
- **What is NOT per-unit, proven the hard way**: the HMD "gyro mounting misalignment"
  (T211's 9% leak) was REFUTED as a static device property by two held-out chair
  passes (T212): slope <0.3% over 9518° of yaw traveled, and the t211 slope was
  unstable within its own session (quarters +0.012→+0.189, sign flip). Do not
  re-introduce a per-unit mount calibration on the strength of one correlated session.

## Onboarding checklist for a new G2 unit (~10 min)

1. **USB census 5/5** (`lsusb`: 04b4:6504, 04b4:6506, 045e:0659, 03f0:0580,
   0bda:4c15) — the cable, not the unit, is the usual suspect (docs/22).
2. **Launch with the standard env** (launcher defaults; nothing unit-specific).
   Verify `Using builder wmr`, both controllers register (`Reading left/right
   controller config`), factory-calib log lines show `det=1.000000` ×4.
3. **Stick check**: rest sticks, confirm autocenter offsets logged and |offset| < 0.25
   (bigger = tired stick hardware, note it in the unit's roster).
4. **Wearer 2-min feel test**: head rotation immediate; figure-8 with EACH controller
   returns to start; RGB gizmo axes match physical motion.
5. **If anything fails**: the instruments (turntable + cradle + chair oscillation) and
   analysis methods live in T209-T212 and the scratch scripts referenced there. Follow
   the discovery method — do not guess.

## The philosophy (why this beats the blob)

We keep the device's own factory data (it is calibration, not code) and replace the
**proprietary runtime** that interprets it. Windows/Oasis is deprecated and frozen;
every correction in this stack has a measurement, a mechanism, and a document, and
improves weekly. That is the e-waste ethos in software form: the vendor gave this
hardware an end-of-life; this stack gives it a future.
