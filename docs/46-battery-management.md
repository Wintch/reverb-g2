# 46: Battery management: the Windows chemistry setting, the raw-byte model, and the charge advisor

> **Status (corrected 2026-08-19).** The raw byte's 0-255 scale is confirmed (matches Windows'
> own HidP scaling, patch `0079`). The `using_1v2_batteries` setting is a Windows-side display
> calibration, not a firmware write. The linear voltage fit in section 2 is valid **only in the
> settled NiMH band (about byte 65-150)**; a raw byte above ~150 does not identify chemistry.
> The alert threshold is raw 85. The NiMH cliff byte is an extrapolation, partly supported by one
> field failure (section 3).

## 1. The Windows "1.2V battery" setting

Windows has a setting for 1.2 V rechargeable vs 1.5 V alkaline cells. Disassembly of the Windows
Oasis driver (same method as `docs/09-oasis-driver-re.md`; `docs/03-controllers.md` "Battery
status") found:

- `driver_oasis.dll` contains the config key `using_1v2_batteries`. That boolean gates a choice
  between two cached lookups whose result is multiplied (`mulss`) into the battery reading before
  it is exposed as a device property: a battery-chemistry *display calibration curve*.
- Windows reads the controller's raw HID `Battery Strength` field (Usage Page `0x06`, Usage
  `0x20`, unscaled `HidP_GetUsageValue`; `docs/re-windows/03-controller-packets.md` row 11)
  exactly as the firmware sends it. No output or feature report is written anywhere near this
  path: **the controller is never told which chemistry is installed.**
- Windows' own `(raw*100)/255` equals Monado's `raw/255.0f` (`wmr_controller_hp_get_battery_status`,
  `patches/monado/0040`), so the 0-255 -> 0-1 map is correct; what the byte means physically
  (voltage, which curve) is what section 2 models.

So there is no knob to flip on the Linux side: Monado needs its own chemistry-aware
interpretation from measurement. Confidence is `strings` + `objdump` + manual reading, no
decompiler: "confident, not 100% proven". The two chemistry-curve constant blobs were never
decoded; decoding them (or the HID descriptor's logical min/max) would give a validated curve
instead of the fitted one below.

## 2. The raw-byte voltage model (valid in the NiMH band only)

The controller reports **one** `battery` byte (`wmr_controller_hp.c`,
`last_input->battery = read8(&p)`); there is no per-cell telemetry. Four representative readings
across a discharge/rest/load cycle on a NiMH set:

| Condition | Raw byte |
|---|---|
| Fresh off charger (surface charge) | ~150 (153 L / 148 R) |
| NiMH plateau, settled | ~110-115 |
| Under sustained LED (constellation) load | ~79 |
| Resting rebound after load | ~146 |

These match the textbook NiMH curve in shape: a surface-charge bump, a flat plateau at the
chemistry's 1.2 V nominal, voltage sag under load that is not capacity loss, and a rest-rebound
slightly below the fresh reading. A linear fit through the two most chemistry-grounded anchors
(fresh ~1.475 V at byte 153, plateau 1.200 V at byte 112.5):

```
slope  = (1.475 - 1.200) / (153 - 112.5) ≈ 0.00679 V/count
V(byte) ≈ 0.00679 × byte + 0.436
```

Check against the unused points: byte 79 -> 0.97 V (a NiMH AA under load sags into 0.9-1.1 V
well before exhaustion; consistent), byte 146 -> 1.43 V (consistent with partial surface-charge
recovery). Whether the byte is one cell's tap, an averaged pack reading or something else is
unknown, so the ~6.8 mV/count slope is a working approximation, not a calibrated instrument.

**Ceiling and chemistry ambiguity.**
- Brand-new alkaline cells read **raw 208** on the first packet. The fit would imply ~1.85 V per
  cell, impossible for alkaline (<=1.6 V open-circuit), so the byte is not linear over the full
  range. An earlier "fresh alkaline = 152" observation was actually a worn pair.
- Fresh-off-charger NiMH reads ~204-206 and sags to ~191 over ~40 min of LEDs-on (surface charge
  burning off, ~1.44 V per cell). **A byte above ~150 therefore does not identify chemistry**;
  alkaline fresh ~208, NiMH fresh ~204-206.
- `controller-battery-check.py` displays percent against a visual ceiling of 208
  (`min(100, raw/208)`), because raw/255 showed a brand-new cell as a misleading 82 %. Alert
  thresholds stay on the raw scale.

**Cliff estimate.** Extrapolating the line to the usual NiMH single-cell floor (~1.0 V "still
usable", ~0.9 V deep-discharge territory under load) gives V=1.0 -> byte ~83, V=0.9 -> byte ~68:
the cliff is predicted in the **raw byte 65-83** range, sustained rather than a load sag.

## 3. Load vs rest: sag is not the cliff

A load-sagged reading (~79) is not evidence of a dying battery by itself: it rebounded to ~146
at rest. An alert built on one instantaneous byte read while the controller drives its
constellation LEDs would false-alarm on that pattern. The real cliff should be a low reading
that does **not** recover after the controller idles a minute or two, or a rest-reading trend
that declines run over run.

**Alert threshold.** `scripts/controller-battery-check.py` uses `BATTERY_LOW_THRESHOLD = 85/255`
(~0.333), derived from the model (byte ~83 ~ 1.0 V floor). The original `0.20` (byte ~51, ~0.79 V
predicted) would fire only deep inside the cliff. The check still runs once with no load/rest
distinction; ideally it runs after a quiet moment or tracks a short rolling window.

**Field validation (series-pair physics).** A NiMH pair that had sagged 113 -> 79 under load the
previous evening failed within hours: the right controller powered itself off at power-on while
a voltage-only tester at rest still read the individual cells "good". One bad cell kills a series
pair: the pack voltage is the sum, but a degraded cell's internal resistance spikes under load,
so at the radio's power-on TX burst it collapses (and can be driven into polarity reversal by its
healthy sibling), the pack sags below the brownout threshold and the controller shuts off.
Rules that follow:
1. **Pre-session gate:** an in-session raw byte in the 70s under load means swap before the
   session.
2. A voltage-only tester at rest proves nothing about load capacity; runtime-under-load history
   is the judge.
3. **Pair discipline:** pair cells of similar health/charge, test them individually, swap
   pairwise. A mismatched pair stresses the good cell.
4. A failed cell goes to recycling; its sibling gets an individual verdict before re-service.

The cells are tracked per physical cell and per hand (project-side bookkeeping; the hardware
reports one aggregate byte per controller), so a cell degraded by past overcharge reveals itself
as a shorter runtime and an earlier cliff than its siblings.

## 4. Charge advisor math (this charger, these cells)

A dumb (timer-only, no -dV/thermal cutoff) charger delivering **250 mA per pair** into **2600 mAh
NiMH AA cells**:

```
Ideal time to push the rated capacity through:  2600 mAh / 250 mA = 10.4 h
Real acceptance is below 100 %; budget 1.2-1.5x for slow timer-only charging:
  1.25x -> 13.0 h   ("should be genuinely full by now" estimate)
  1.50x -> 15.6 h, rounded to 16 h   (hard ceiling)
```

**~13 h from empty is the working "full" estimate; 16 h is the hard ceiling** at which the charger
must come off, because it has no automatic cutoff and NiMH overcharge is a real hazard: heat,
permanent capacity loss, in worse cases venting or leakage. Both multipliers are engineering
guidelines, not yet validated against a timed empty-to-full cycle. Always charge and install
pairs from the same tracked set, never mixed.

This is part of a deliberate stance: rechargeables plus recycling over disposables. The advisor
(how long a charge takes, where the cliff sits) exists to make rechargeables practical for
unattended sessions without babysitting a dumb charger.

## 5. Battery level affects tracking before power-off

- **Dim LEDs starve blob detection** (low battery: constellation matches weaken and a hand can
  anchor meters off before anyone notices).
- **Over-bright LEDs appear to corrupt correspondence** (suspected, needs a controlled
  follow-up): with 3.1 V fresh alkalines the right hand's gravity-gate drop fraction hit 97 % at
  baseline (vs 8 % on 2.5 V NiMH, same room class) and yaw lock could not settle. Suspected
  mechanism: blob bloom merges neighboring LEDs and shifts centroids so the solver lands on mirror
  lobes. NiMH's flat 1.2 V band is the sweet spot, but fresh-off-charger NiMH drives the LEDs
  nearly as hot as alkaline, so use cells that have rested after charging. (A later ghost flood
  also hit a settled-NiMH hand equally, so brightness is not always the dominant factor.) The
  experiment: same controller and scene, cells at ~3.1/2.6/2.4 V, measure ghost fraction.
- Alkalines sag fast under LED load (a worn pair went raw 119 -> 79 in ~45 min of LEDs on; another
  152 -> 75 in one session): emergency tier only.
- **A mid-session battery swap means relaunching the session**: a late-attached controller gets
  no constellation registration or role (Monado's device list is fixed at startup).

Warnings must be proactive ("charge or swap before the next session"), not reactive. Wishlist
for the launcher: battery type and mAh per profile, estimated remaining session time from the
measured discharge curves (assuming an unmixed pair), proactive warnings.

## 6. Open question: Windows read 90 %+ on the same cells

After a Windows control session on the same cells and controllers, with `using_1v2_batteries`
validated at 1.2 V, Oasis showed 90 %+ charge; Windows normally reads low, even with alkalines.
That is coherent with section 1: NiMH at its 1.2 V plateau read through the alkaline curve
(~1.5 V fresh) looks almost empty, so the cells may have been fine and the readout wrong. It is
also a free calibration anchor: Oasis's percentage is the only independent readout, so if it says
90 %+ while our raw byte for the same cells sits at the settled-NiMH ~110-115, the fit gains an
external check. Test (queued, not run): note the Windows % per controller with the setting
confirmed, then without recharging read the raw byte per hand under Linux (`grep -E
"battery|BATT"` in the service log; patch `0073` names the hand), twice (near full and well into
a session); also check whether the setting is per controller or global and whether it survives
an Oasis update. This does not affect the cliff model or the fit, which use our own raw bytes.

## 7. The low-battery warning was silently never running (fixed 2026-08-18)

A real incident (2026-08-13): a controller battery got low, its LEDs dimmed, constellation
tracking starved and a hand anchored meters off before anyone noticed. `patches/monado/0040`
wired the battery byte into `xrt_device::get_battery_status` and
`scripts/controller-battery-check.py` was written as the consumer, to run from `vr-launcher.py`
after Monado comes up. Live check found it had **never been reachable on the lab machine**:
`vr-launcher.py` looks for the script flat next to itself in `~/vr/`, but it existed only under
`scripts/` in the repo. The launcher's exception handling swallowed the `FileNotFoundError` and
printed a one-line "could not run it" note on every launch since 2026-08-13. Fix: the script was
deployed flat next to the launcher, the threshold moved from 0.20 to 85/255 (section 3), the
stale "scale unverified" hedge was removed, and the check was verified end to end through a real
launcher run (`left: 74% / right: 69%`, raw ~153/143 against the 208 display ceiling). Lesson: a
safety net that fails silently is not a safety net; verify the consumer through its real path.

## 8. Remaining open questions

1. **The cliff byte is a prediction.** Run a controller down until a *non-rebounding* low reading
   is seen, log it, and replace the extrapolation with a real anchor.
2. **Single-cell vs pack-voltage framing** is unresolved; the fit is self-consistent, not proof.
3. **`wmr_controller_og.c`** needs the same battery wiring `wmr_controller_hp.c` got in
   `patches/monado/0040`; no OG hardware exists to verify it.
4. **Mixed chemistry per hand breaks the model.** An earlier live session ran NiMH right and
   alkaline left; Windows' `using_1v2_batteries` is a single global flag and cannot represent
   that either. The fit does not apply to an alkaline side.
5. Minor: `wmr_controller_hp.c` describes the controller as "2x AAA batteries"; the cells in use
   are AA (likely a pre-existing comment error).

Sources: `docs/03-controllers.md` (battery status), `docs/re-windows/03-controller-packets.md`
(row 11), `patches/monado/0040` and its README entry, `scripts/controller-battery-check.py`.
