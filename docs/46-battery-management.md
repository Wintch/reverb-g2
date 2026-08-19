# 46 — Battery management: the Windows chemistry setting, the raw-byte voltage model, and the charge advisor

> ## STATUS AS OF 2026-08-17 (~20:15) — chemistry setting traced to a Windows/Oasis-side
> reinterpretation (not a firmware config write); a first raw-byte voltage model fit from
> tonight's per-cell tracking data; charge-advisor math and the anti-e-waste policy written
> down. **The NiMH cliff itself has not been observed yet** — everything about its byte
> value below is extrapolation, flagged as such.
>
> **Later updates**: the raw/255 SCALE was CONFIRMED 2026-08-18 (matches Windows' own HidP
> scaling; the driver comment now says so — patch 0079); the alert threshold moved to raw 85
> the same day (`docs/53`); and **2026-08-19's first genuinely-fresh alkaline reading (raw
> 208) bounds this doc's linear fit to the NiMH band only — see the dated addendum at the
> bottom before using the model outside ~byte 65-150.**

## 1. The Windows "1.2V battery" setting — where it actually lives

The user's own memory triggered this investigation: *"hay un setting en Windows que indica
si es pila 1.2V recargable o 1.5V comun — sospecho que aparte de reflejarlo en % de carga
no hace nada."* `docs/03-controllers.md` ("Battery status" section, 2026-08-13) already ran
this down, using the same disassembly method as `docs/09-oasis-driver-re.md`, against a real
local copy of the Windows Oasis driver:

> *"`driver_oasis.dll` contains the literal config key string `using_1v2_batteries`... The
> disassembly shows that boolean gating a choice between two different cached lookups (two
> distinct GUID-shaped queries), whose result is multiplied (`mulss`) into the battery
> reading before it's reported onward as a device property... it reads as a battery-chemistry
> *display calibration curve* (alkaline AA and NiMH rechargeable have different
> voltage-discharge curves for the same remaining charge...), not a functional setting."*

**Verdict for question 2 of tonight's brief: this is a HOST-side reinterpretation, not a
controller-side/firmware configuration write.** The mechanism found is: Windows reads the
controller's raw HID `Battery Strength` field (Usage Page `0x06` "Generic Device Controls",
Usage `0x20`, unscaled `HidP_GetUsageValue` — `docs/re-windows/03-controller-packets.md`,
mapping row 11) exactly as the firmware sends it, and *afterward*, inside `driver_oasis.dll`,
multiplies that raw reading by one of two different chemistry-curve constants depending on
the `using_1v2_batteries` config flag, before exposing the result as a device property to
the rest of the Windows Mixed Reality stack. No output report, feature-report write, or
`CykSetOutputReport`/`CykSetFeatureReport` call was found anywhere near this code path — the
controller is never told which chemistry is installed. It just streams the same raw byte
regardless, and Windows' own driver decides how to read it.

**What this means for our stack, stated plainly**: there is no Windows-equivalent knob to
flip on the Monado/Linux side. `raw / 255.0f` (`wmr_controller_hp_get_battery_status`,
`patches/monado/0040`) is chemistry-blind by construction — it can't become NiMH-aware by
finding a hidden setting, because the setting genuinely isn't there to find; it lives
entirely in the host driver we don't run. **Monado has to build its own chemistry-aware
interpretation from measurement, from scratch** — which is what §2 below is a first pass at.

**Caveats on this verdict, stated at the same confidence level `docs/03` gave it**: this is
`strings` + `objdump` + manual reading, no decompiler — "confident, not 100% proven." The
two GUID-shaped cached lookups and the actual chemistry-curve constant blobs were never
pinned down to literal values (`docs/03`: *"Not chased further, deliberately... needs either
the raw report-descriptor bytes or decoding the two chemistry-curve constant blobs"*). If
either of those ever gets fully decoded, it would give Monado a *validated* curve instead of
tonight's fitted one — real next-session work if it's ever worth the time.

**A resolved side-question, not the chemistry one but adjacent and already settled**: the
raw byte's overall *scale* against the HID spec's own definition. `docs/re-windows/03` row
11 cross-referenced Windows' own `(raw*100)/255` against Monado's `raw/255.0f` and found them
identical ratios — Monado's existing formula is correct as a 0-255→0-1 linear map. That part
of the "UNVERIFIED SCALE" comment can be considered resolved; what stays unverified, and is
this document's actual subject, is what physical quantity (voltage, at what curve) that
linear 0-255 range actually represents.

## 2. The raw-byte voltage model, from tonight's data

`docs/battery.jsonl` (the new per-cell tracking log, started tonight) gives four
representative raw-byte readings across a real discharge/rest/load cycle on the current
NiMH set:

| Condition | Raw byte (representative) | `battery.jsonl` source |
|---|---|---|
| Fresh off charger (surface charge) | ~153 (L)/148 (R) → ~150 | line 2 |
| NiMH plateau, settled | ~110-115 (measured 113/111) | line 7 |
| Under sustained LED (constellation) load | ~79 | tonight, live session |
| Resting rebound after load | ~146 | tonight, live session |

These four numbers line up, in relative order and shape, with the textbook NiMH AA
single-cell discharge curve almost exactly: a brief "surface charge" bump above nominal
right off the charger, a long flat plateau around the chemistry's own 1.2 V nominal voltage
(worth noting: the *same* 1.2 V the Windows setting names literally, which is a good sign
this framing is on the right track), voltage sag under load that is NOT capacity loss (it
recovers almost all the way back at rest), and a rest-rebound that lands a little below the
original fresh reading rather than all the way back to it (consistent with the surface
charge partially, not fully, bleeding off after first real use).

**Fitting a linear map from the two most chemistry-grounded anchors** — the fresh
surface-charge reading (~1.45-1.5 V open-circuit, midpoint 1.475 V) and the NiMH plateau
(exactly 1.2 V nominal, the chemistry's own textbook value):

```
byte 153  ≈ 1.475 V
byte 112.5 ≈ 1.200 V

slope  = (1.475 - 1.200) / (153 - 112.5) = 0.275 / 40.5 ≈ 0.00679 V/count
offset = 1.200 - 0.00679 × 112.5 ≈ 0.436 V

V(byte) ≈ 0.00679 × byte + 0.436
```

**Checked against the two points NOT used to fit it:**

- byte 79 (under load) → predicted **0.97 V**. A NiMH AA under real current draw commonly
  sags into the 0.9-1.1 V band well before the cell is actually exhausted — pure IR-drop,
  not depletion. Consistent.
- byte 146 (rest rebound) → predicted **1.43 V**. Close to, but a little under, the fresh
  1.475 V reading — exactly the "surface charge only partially returns" shape described
  above, not a coincidence given how the model was built, but at least self-consistent
  across four independent readings instead of only the two it was fit to.

**Big caveat, stated up front so this isn't over-trusted**: this treats the byte as linear
in a *single-cell-equivalent* voltage. The controller reports **one** `battery` byte total
(`wmr_controller_hp.c:209`, `last_input->battery = read8(&p)`) — there is no per-cell
telemetry on the wire. Whether that byte reflects one cell's tap point in the 2-series pack,
an averaged/halved pack reading, or something else the firmware computes internally is
unknown; this model works entirely in "whatever voltage-like scale produces these four
numbers in the right relative order," anchored to well-known NiMH single-cell figures
because that's the only external chemistry data available to anchor against, and because
the fit is internally consistent across independent points. Treat the ~6.8 mV/count slope
as a working approximation, not a calibrated instrument.

**Cliff estimate — explicitly open, not measured**. Extrapolating the same line toward the
classic NiMH single-cell cutoff region (design guides commonly cite ~1.0 V as a
"still usable" floor and ~0.9 V as deep-discharge/damage territory under load):

```
V=1.0 → byte ≈ (1.0 - 0.436) / 0.00679 ≈ 83
V=0.9 → byte ≈ (0.9 - 0.436) / 0.00679 ≈ 68
```

So the model's best guess for where the real cliff sits is **somewhere in the raw byte
~65-83 range**, sustained (not a load-sag that rebounds — see §3). This is a prediction from
a two-point fit checked against two more points, not an observation. Tonight's own ~79
reading is *inside* that predicted band but was a load-sag that fully rebounded to ~146 at
rest — i.e., **tonight did not see the cliff**, it saw ordinary IR-drop sag near where the
cliff is predicted to be, which is exactly why this needs a real first-cliff observation
before anyone trusts a number here (§6).

## 3. Load vs. rest: sag is not the cliff, and the alert logic needs to know that

The single most actionable thing in tonight's four datapoints: **a load-sagged reading
(~79) is not evidence of a dying battery by itself — it rebounded to ~146 at rest**, close
to the original fresh reading. A battery-health signal built on a single instantaneous raw
byte read while the controller is actively drawing current for its constellation-tracking
LEDs would false-alarm on exactly this pattern. The real cliff, when it happens, should look
different: a low reading that does **not** recover after the controller sits idle for a
minute or two, or a rest-reading trend that itself declines run over run — not a
load-coupled dip.

`scripts/controller-battery-check.py`'s original `BATTERY_LOW_THRESHOLD = 0.20` (raw/255 ≈
byte 51) predated this whole per-cell/voltage investigation. **UPDATED same day
(2026-08-18, `docs/53`): the threshold is now `85/255` (~0.333)**, derived from this doc's
own model (byte ~83 ≈ 1.0 V floor) and validated by the same-day field failure below — the
old byte-51 trigger (~0.79 V predicted) would have fired only deep inside the cliff, too
late. The remaining structural caveat still stands: the check runs once, whenever the
script happens to run, with no load/rest distinction — it should ideally either run right
after a quiet moment (controller not actively tracking) or track a short rolling window
instead of one instantaneous sample, once the cliff's real signature is known from a first observed
case.

## 4. Charge advisor math (this charger, these cells)

Hardware: a dumb (timer-only, no `-ΔV`/thermal cutoff) charger delivering **250 mA per
pair** into **2600 mAh NiMH AA cells** (brand "fulltotal", `battery.jsonl:4`).

```
Ideal (100%-efficient) time to push the full rated capacity through the cell:
  2600 mAh ÷ 250 mA = 10.4 h

Real NiMH charge acceptance is well under 100%, especially without a real end-of-charge
detector. Standard guidance for slow, timer-only NiMH charging is to budget 1.2-1.5x the
ideal time:

  1.25x → 2600 × 1.25 / 250 = 13.0 h   ("should be genuinely full by now" estimate)
  1.50x → 2600 × 1.50 / 250 = 15.6 h → rounded to 16 h   (hard ceiling)
```

**~13 h from empty is the advisor's working "full" estimate; 16 h is the absolute-max
ceiling** — the point at which the charger must come off regardless of what the estimate
says, specifically because this charger has no automatic cutoff and NiMH overcharging is a
real, named hazard (§5). Both numbers are project-applied engineering-guideline multipliers
on the rated capacity and the known charge current, **not yet validated against an actual
timed full empty→charger→full cycle** under the new per-cell tracking scheme — that
validation is a natural next step once a cell is run down far enough to be worth a controlled
recharge.

**Pairing rule: always charge/install pairs from the same tracked set, not mixed.** Two
cells with different capacity or internal resistance, wired in series inside a controller,
discharge unevenly — the weaker cell hits its cliff first while the stronger one is still
fine, risking cell reversal on the weak one and definitely muddying any future per-cell
runtime comparison. This is also why `battery.jsonl` tracks assignments explicitly rather
than treating "two AAs" as interchangeable.

**Per-cell roster** (`battery.jsonl:6-7`), six NiMH cells total, tested "good" on a coarse
voltage-only battery tester and named for tracking: **kos, kub, mar, mik, bob, rio**. Current
assignment: left = `[kub, rio]`, right = `[mar, mik]`, spares = `[kos, bob]`. Every future
`batteries_changed` event should record the new assignment so each cell accrues its own
runtime history — the whole point being that a cell overcharged or degraded before this
tracking started (the current set is explicitly suspected of exactly that, `battery.jsonl:5`:
*"sospecho que las sobrecargue"*) reveals itself as a shorter runtime and an earlier cliff
than its siblings, something a single "two AAs, whatever" model could never catch. Worth
restating clearly since it's easy to misread: **the controller hardware itself reports one
aggregate `battery` byte per controller, not per cell** (§2) — the per-cell roster is
project-side bookkeeping, correlating known physical cells to whichever controller they're
currently installed in, not a second telemetry channel.

## 5. NiMH overcharge hazard and the project's e-waste stance

Verbatim, `battery.jsonl:3`, the user's own words starting this whole tracking effort:
*"son complicadas si las sobrecargas"* — NiMH cells are genuinely finicky about overcharge,
unlike the alkaline AAs this project used to run without a second thought. A dumb charger
with no `-ΔV`/thermal cutoff will happily keep pushing current well past full, which cooks
NiMH cells (heat, permanent capacity loss, and in worse cases venting/leakage) — this is the
concrete reason §4's 16 h figure is framed as a hard ceiling the user should be actively
warned about, not just a background estimate.

**This sits inside a deliberate project stance, not an incidental convenience choice**:
rechargeables plus a real recycling habit over disposable batteries, consistent with the
project's own broader hardware-recovery, anti-e-waste character (a Reverb G2 pulled back
from the edge of being landfill in the first place). The charge advisor being built here —
knowing roughly how long a real charge takes and roughly where the cliff sits — exists to
make rechargeables *practical* for unattended museum/arcade-style sessions (`project_vr_museum_goal`
memory note) without the user having to babysit a dumb charger by feel, which is exactly
the situation that produced the "sospecho que las sobrecargue" caveat on the current set in
the first place.

## 6. Open questions

1. **The cliff byte value is a prediction, not an observation.** §2's ~65-83 estimate comes
   from extrapolating a two-point fit past the data actually collected tonight; the next
   session that runs a controller down far enough to see a *non-rebounding* low reading
   should log it explicitly in `battery.jsonl` and this document should be updated with a
   real anchor instead of an extrapolation.
2. **Host-vs-firmware is answered with the caveats stated in §1, not with total certainty.**
   The `using_1v2_batteries` finding is `strings`/`objdump`-level confident, not
   decompiler-verified; the actual chemistry-curve constant blobs were deliberately not
   chased down. If Monado's own byte-to-voltage scale is ever worth pinning exactly (rather
   than the fitted approximation here), decoding those blobs — or getting the raw HID
   report-descriptor logical-min/max for the Battery Strength field — is the real next step,
   per `docs/03-controllers.md`'s own "not chased further" note.
3. **Single-cell-equivalent vs. pack-voltage framing is unresolved.** §2's model works in
   "whatever scale produces these four numbers in the right order," anchored to single-cell
   NiMH figures because the fit is self-consistent that way — it is not proof the firmware
   actually measures one cell rather than an averaged/divided pack reading.
4. **`wmr_controller_og.c` needs the same battery wiring `wmr_controller_hp.c` got in
   `patches/monado/0040`** — no OG hardware exists in this project to verify it against, per
   the patch's own README note.
5. **Mixed chemistry per hand breaks this whole model.** `patches/monado/0040`'s README
   entry already flagged that an earlier live session ran NiMH right / alkaline left
   simultaneously — Windows' `using_1v2_batteries` is a single global flag and can't even
   represent that case correctly either. Everything in §2 assumes the current all-NiMH set;
   if alkaline AAs ever go back into one side only, the fitted curve above does not apply to
   that side.
6. **Minor, not chased**: `wmr_controller_hp.c`'s own comment describes the G2 controller as
   running "2x AAA batteries" (`wmr_controller_hp.c:578`) — the cells actually in use here,
   per `battery.jsonl:4`, are AA. Likely a pre-existing driver-comment error, unrelated to
   the scale question and not touched by this document.

## Sources

`docs/03-controllers.md` ("Battery status" section, 2026-08-09/2026-08-13) — the
`using_1v2_batteries` disassembly finding and the original "raw/255, unverified" investigation.
`docs/re-windows/03-controller-packets.md` (row 11, §4.2) — the Windows/Monado battery-scale
cross-reference. `docs/pruebas.jsonl` T104 (first battery investigation), T167 (patches
0036-0040 batch, live battery-alert motivation, mixed-chemistry note).
`patches/monado/0040-d-wmr-Wire-the-G2-controller-s-already-parsed-batte.patch` and its
README entry. `docs/battery.jsonl` lines 1-7 (per-cell tracking, chemistry note, roster,
current assignment). `scripts/controller-battery-check.py` (current alert threshold).
`~/vr/monado/src/xrt/drivers/wmr/wmr_controller_hp.c` (read only — driver source as it
stands 2026-08-17, being actively edited by another agent this same night; nothing in this
document required touching it).

## Field failure case study (2026-08-18): mik, and the series-pair physics

First real-world validation of this doc's model, hours after it was written. The
right controller began powering itself off at power-on (three service launches saw
only the left register; misread at first as a radio fault). Diagnosis by the user:
cell **mik** dead — its sibling **mar** tested perfect individually.

**Why ONE bad cell kills the pair**: the pack voltage is the series SUM, but a
degraded NiMH cell's internal resistance spikes under load. At the radio's power-on
TX burst the dead cell collapses (and can be driven into **polarity reversal** by
the healthy sibling pushing current through it — damaging both). Pack sags below
the controller's brownout threshold → instant self-power-off, while a voltage-only
tester at rest still reads the pack "alive".

**The model called it**: mar+mik was the worked set that sagged 113→79 under load
the previous evening — 79 sits inside this doc's extrapolated cliff zone (byte
65-83). The set went over the cliff within hours.

Rules distilled:
1. **Pre-session gate**: an in-session raw byte in the 70s under load = swap before
   any demo/session. (Showcase gate rule, empirical basis: this failure.)
2. **A voltage-only tester at rest proves nothing about load capacity** — mik read
   "good" 7 h before dying. Runtime-under-load history (this roster) is the judge.
3. **Pair discipline**: pair cells of similar health/charge; test individually;
   swap pairwise. A mismatched pair stresses the good cell (reverse-charging risk).
4. A cell that fails goes to **tester → RECYCLING**, and its sibling goes to the
   pool for an individual verdict before re-service (mar's current status).

## Addendum 2026-08-19 — the model's ceiling found: fresh alkaline reads raw 208, the linear fit is NiMH-band-only

A genuinely-new (0 km) Energizer MAX pair installed in the right controller read **raw byte
208** on its first packet (2026-08-19 00:34). Under this doc's linear fit that would imply
~1.85 V/cell — impossible for alkaline chemistry (≤1.6 V open-circuit) — so **the byte is
not linear across the full range; the fit above is valid only in the NiMH band it was
fitted on (~byte 65-150)**. Prior context correction from the user: the earlier "fresh
alkaline = 152" observation (T216) was actually an already-worn pair; 208 is the first
true-fresh data point this project has.

Consequences applied same night (`docs/56` has the full session context):
- `controller-battery-check.py` now displays percent against a **visual ceiling of 208**
  (`min(100, raw/208)`) — raw/255 showed a brand-new cell as a misleading "82%". Alert
  thresholds stay on the raw scale this doc calibrated.
- **New two-sided hazard**: over-bright LEDs (3.1 V fresh alkaline) correlated with a 97%
  gravity-gate ghost fraction on the same hand that ran 8% on 2.5 V NiMH — suspected blob
  bloom/saturation corrupting correspondence. Dim starves detection (T167); hot corrupts
  matching. NiMH's flat 1.2 V band is the sweet spot. Controlled experiment queued: same
  controller, same scene, cells at ~3.1/2.6/2.4 V, measure ghost fraction.
- User-facing feature spec (per-profile battery type + mAh → estimated remaining session
  TIME, unmixed-pair assumption, proactive charge-before-session warnings) captured in
  `docs/56`.
