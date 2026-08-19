# The low-battery warning was silently never running — found live, fixed and deployed (2026-08-18)

## Context

T167 (2026-08-13) documented a real incident: a controller's battery got low, its LEDs dimmed,
optical constellation tracking starved (dim LEDs → weak/no blob matches), and the wearer saw
that hand "anchored meters off" mid-session before anyone noticed the battery was the cause.
`patches/monado/0040` wired the already-parsed battery byte into `xrt_device::get_battery_status`,
and `scripts/controller-battery-check.py` was written the same night as the consumer — a
loud, non-blocking check meant to run from `vr-launcher.py` right after Monado comes up,
naming the hand and the tracking consequence if a controller is low.

## What was actually found, live, today

Checked both controllers' real battery on this everyday-system rig (after the user turned them
on and asked to "map their battery status" and flagged a recollection of a past
tracking-degradation incident — this is that incident, T167). Left: raw byte 83 (33%). Right:
raw byte 17 (7%, after settling from an initial post-wake transient 31→19→17) — both consistent
with "cuantas horas apagadas... las va drenando" (parasitic drain while off with batteries
still installed).

**Tried to run the actual safety check `vr-launcher.py` is supposed to invoke — it was never
actually reachable on the lab machine.** `vr-launcher.py`'s `check_controller_battery()` looks
for `HERE / "controller-battery-check.py"` (i.e. flat, next to itself in `~/vr/`, same
convention as sibling `controller-pair-check.py`). The script only ever existed at
`scripts/controller-battery-check.py` in the canonical GitHub repo — `~/vr/` on the lab machine
(confirmed via the mounted lab disk) never had a copy at any path. `vr-launcher.py`'s own
exception handling (`except OSError as e: print(f"...no pude correr...no bloquea, sigo igual")`)
swallows exactly this `FileNotFoundError` and continues silently — so every launch through
`vr-launcher.py` since 2026-08-13 has been printing a one-line "couldn't run it" note and moving
on, not the loud red warning the design intended. The safety net T167 built had a hole in it
from day one.

## Fix

1. **Deployed** `scripts/controller-battery-check.py` to `/mnt/lab/home/iam/vr/controller-battery-check.py`
   (flat, matching where `vr-launcher.py` actually looks) via the mounted lab disk. Confirmed
   `patches/monado/0040`'s battery-status wiring is already present in dev's `lab-full`
   `wmr_controller_hp.c`, so the script should work immediately on dev's next launch.
2. **Updated the alert threshold**, `BATTERY_LOW_THRESHOLD`: was `0.20` (raw byte ~51), picked
   2026-08-13 before the raw-byte scale was confirmed and before any voltage model existed. Now
   `85/255` (~0.333), based on [[docs/46]]'s fitted voltage model (`V ≈ 0.00679×byte + 0.436`)
   and its cliff prediction (byte ~83 ≈ 1.0V "still usable" floor, byte ~68 ≈ 0.9V deep-discharge
   risk) — and validated by [[docs/46]]'s own field-failure case study **from this same day**,
   where a pair sagging to byte 79 under load preceded a real cell failure. The old 51 threshold
   would not have caught that failure in time; 85 fires with lead time instead of inside the
   cliff. Also removed the "raw scale unverified" hedge from the script's messages — the scale
   is now confirmed (`raw/255` matches Windows' own `(raw*100)/255` exactly, see the driver's
   updated `wmr_controller_hp_get_battery_status` comment and `docs/re-windows/03+06`).
3. **Verified live** against this rig's real running `monado-service`, before and after the
   threshold change: old threshold flagged only the right controller (7%); new threshold flags
   both (left 33%, right 7%) — left sits right at the newly-understood cliff boundary, which is
   exactly the case the old threshold was too permissive to catch.

## Not done this session

Only deployed to the lab machine's live `~/vr/` working tree, not committed there (that
directory isn't a git checkout — see [[project-vr-diagnostic-automation]] and
[[reference-vr-lab-topology]] for the deployment model). Whoever is next on dev should confirm
`vr-launcher.py` now actually prints the warning on a real launch, not just via this direct
test. The driver-side comment at `wmr_controller_hp.c:328` on dev's `lab-full` still says "Scale
unverified" (stale, matches the everyday system's pre-fix state) — not edited directly on dev's
live checkout to avoid hand-editing outside the normal patch/handoff process; worth a small
follow-up patch next time dev's tree gets touched for something else.
</content>

## Closure 2026-08-19 (~04:05, T222): verified live through the real path

The one verification this doc left owed is done: a full `vr-launcher.py` run on the
lab/dev machine (piped menu selection, real monado bring-up) printed the battery check
for the first time ever through its intended path — `✓ left: 74% / ✓ right: 69%`
(raw ~153/143 against the 208 display ceiling, exact). The T167 safety net is now
actually live end-to-end, six days after it was built. (Same run also exercised the
new network-link-check.py at the menu: VERDE.)
