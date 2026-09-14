# Controller LED pulse train, and where the visibility cliff actually is (2026-09-13)

Session result. Four measurements, three of which contradict something this project believed.

Setup, identical across both arms: headset **stationary** on the desk facing forward, `ctrl` mode
(`WMR_SLAM=0 WMR_CAMERAS=1`, constellation on), so the tracking origin is the head and a sample's
distance from origin *is* its hand-to-camera range. Operator holds the **right** controller only
(left set aside), at tape-marked 50 / 75 / 100 cm, 20 s per window, wrist orientation held as
constant as a person can. Right-controller battery read **raw 83 in both arms** — the same cell
state, so nothing below is a battery artifact.

Instrument: `WMR_CONSTELLATION_RAW_SAMPLES_LOG` (patch 0109), one line per sample at the very top
of `constellation_sample_store`, **before every gate and guard**. This is deliberately a different
quantity from `WMR_CONTROLLER_HEADING_CSV` (0107), which sits after the gravity gate and therefore
counts what survives. This one counts what the cameras produced.

## 1. The numbers

| | 50 cm | 75 cm | 100 cm |
|---|---|---|---|
| **control** (no LED command, historical behaviour) | **610** (30.5/s) | **634** (31.7/s) | **0**, repeat **1** |
| **LED intensity 200** | **0** | **0**, repeat **0** | **1** |
| measured distance, control arm | p50 **0.490 m** | p50 **0.767 m** | — |

Both 100 cm arms produced one lone sample each, reading `dist=0.122` and `dist=0.153` against a
1 m tape. Those are failed solves reporting a number, not weak detections.

## 2. Lab patch 0108 (LED pulse train) must stay OFF — it destroys constellation tracking

In the whole 4-minute intensity-200 session, across three measurement windows at three distances,
**one** raw sample arrived. The control arm produced 610, 634, and 7284 (a 90 s free hunt). The
cameras were healthy throughout — `clockskew` lines flowing, `WMR camera started` logged, both
controllers registered with the tracker.

The wearer independently reported the rings looked **brighter** to the eye in this arm, and the
command is confirmed present in the live service environment (`WMR_CONTROLLER_LED_INTENSITY=200`,
`WMR_CONTROLLER_LED_HZ=15`). So the command is reaching the device and doing something real. What
it is not doing is leaving the LEDs visible to the tracker.

**The mechanism this points at** (consistent with everything measured, not independently proven):
Windows syncs the pulse train to camera exposure through the packet's 55-bit `TS` field, which is
the entire point of the timesync half of the command. 0108 resends a **constant** `ts=0`, so the
train free-runs. The tracking cameras expose in short windows; a free-running train is simply not
guaranteed to be lit during them. A higher duty cycle reads as "brighter" to a human eye while
being worth nothing to a 
sensor that only looks for a few hundred microseconds at a time.

This is the exact failure the 0108 commit message called out in advance as the unvalidated half of
the change, and the reason it shipped defaulting to 0. That default is what kept the rig working;
treat it as load-bearing, not as a formality.

**So the honest verdict is not "LED intensity does not help".** It is **"the LED command without
exposure timesync is worse than sending nothing"**. The hypothesis that Windows' brighter rings
help tracking is untested either way — testing it requires plumbing `wmr_camera.c`'s exposure
timestamps into the packet, which is a much larger change than 0108 was.

## 3. Absolute scale is fine — retire that suspect

`docs/125` lists absolute scale as never validated, on the strength of one hand reading 0.556 m
against a 0.75 m tape. Measured here on the control arm, tight distributions both times:

- 50 cm tape → p50 **0.490 m** (min 0.480, max 0.511) — **2% low**
- 75 cm tape → p50 **0.767 m** (min 0.741, max 0.792) — **2% high**

Two percent, in opposite directions, with spreads of ~3 cm. The solve's metric scale is sound.
Whatever produced the old 0.556 m reading, it was not a scale error — and since scale holds at both
distances, it was not a uniform scale factor either.

## 4. The cliff is real, it is a WALL, and it is not where docs/125 puts it

`docs/125` says 75 cm yields zero samples. **That is wrong for raw samples**: 75 cm yields 634 in
20 s, statistically indistinguishable from 50 cm's 610. The cliff sits between **77 cm** (the
largest distance actually measured, p50 0.767) and **1 m**.

More important than the location is the *shape*. 31.7/s → 0 with nothing in between. An optical
brightness limit degrades: fewer blobs, noisier poses, scale starting to lie. None of that happened
— the 75 cm window was as clean and as well-scaled as the 50 cm one, and then there was nothing.

**Unverified hypothesis, stated so it can be killed:** this is an angular-resolution limit, not a
photometric one. The tracking cameras are 640×480 with `fx ≈ 270.8` (from this rig's own logged
calibration). The ring carries **32 LEDs**. If its diameter is ~10 cm, adjacent LEDs subtend:

| distance | ring | adjacent-LED spacing |
|---|---|---|
| 50 cm | ~54 px | ~5.3 px |
| 75 cm | ~36 px | ~3.5 px |
| 100 cm | ~27 px | **~2.6 px** |

Below ~3 px neighbouring LEDs stop resolving as separate blobs, correspondence has nothing to match,
and the output goes to zero rather than getting worse — which is the observed shape. It also
predicts that **more brightness makes it worse**, since blooming grows each blob and merges them
sooner, and brightness indeed did not move the wall.

**The 10 cm diameter is assumed, and that is the weak link in the whole argument.** The real
geometry is already parsed into `wmr_controller_config.leds[]` (`wmr_config.c`'s
`wmr_controller_led_config_parse`), so the check is cheap: log the extent of those positions at
init and redo the arithmetic. Do that before this section is cited as established.

## 5. Method notes, because two of tonight's readings were artifacts

- A `0` from a stationary operator who is not where you think they are looks exactly like a `0` from
  a physical limit. Tonight produced two of them: one full 90 s sweep run with nobody holding a
  controller, and one "75 cm" window measured from 1 m. Both were caught only because a control
  measurement was repeated. **Always re-run a zero before believing it.**
- The free hunt (`led_hunt.sh`, speaks "te veo" on each new sample) went from 18/s to 175/s as the
  operator found the camera cone. Controller *orientation* moves the sample rate by ~10x, far more
  than the distances under test. Any cross-arm comparison has to hold wrist attitude fixed, and
  that is a real limit on how fine a difference this protocol can resolve.
- Scripts: `led_measure.sh` (one window, operator-confirmed, never self-starting),
  `led_hunt.sh`, `led_arm.sh`. Nothing auto-starts — an earlier timed version began its phases
  before the operator was in the room.

## 6. What this changes for docs/125

- **Remove** absolute scale from the open-suspect list (§3 above).
- **Correct** the cliff's location: 75 cm is healthy, the wall is 77 cm–1 m.
- **Reframe** the LED lead: not a fix to try, a change that is actively harmful until exposure
  timesync exists. The `WMR_CONTROLLER_LED_INTENSITY=0` default stays.
- **Add** the resolution hypothesis as the leading explanation for the wall, pending the ring-diameter
  check.
- **Still open, untouched tonight:** the yaw ghost, which is a different failure and is what the
  wearer actually feels as "los joys no respetan la posición" inside arm's reach. Nothing here
  addresses it.
