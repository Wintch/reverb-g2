# The constellation range check measured against the wrong frame

**2026-08-19 (T223), lab machine, headset worn.** A one-line sanity guard, written a week
earlier against a real problem, was silently discarding every correct controller solve for
minutes at a time and had probably been doing it, to some degree, in every long session
since it was written.

## Symptom, as the wearer described it

> "los consoles giran bien sobre todos los ejes, pero por lo general están anclados sobre el
> mismo punto 3d (todos sus ejes se comparten) a un costado mío. A veces parpadean en el
> lugar correcto."

Both hands sharing one fixed position off to the side, orientation perfect, occasional
flashes of correct placement. That is not "bad tracking" — it is the **placeholder**: when a
controller has no fresh constellation sample, the driver reports a fixed per-hand position,
and the wearer sees both hands parked. The "flashes" are the few percent of samples that got
through.

## What the check did

`constellation_sample_store()` (`src/xrt/drivers/wmr/wmr_controller_base.c`), before the fix:

```c
static const float WMR_CONSTELLATION_MAX_RANGE_M = 5.0f;
const struct xrt_vec3 *sp = &sample->pose.position;   /* WORLD frame */
if (fabsf(sp->x) > 5.0f || fabsf(sp->y) > 5.0f || fabsf(sp->z) > 5.0f) {
        ...
        return;                    /* logged at WMR_DEBUG only */
}
```

The published pose is `Txr_world_device` — the controller in the **world/tracking-origin
frame**, composed as `Txr_world_cam ∘ Txr_cam_device`, where `Txr_world_cam` comes from the
headset's own live SLAM pose. So this check measures **distance from the SLAM origin**, and
that quantity contains a term nobody intended: however far the origin has drifted.

## The measurement

Wearer seated, not walking, headset on, controllers held in front:

```
POSE head (-3.500 +1.073 +7.656)     <- 8.4 m from the tracking origin
left  (-0.151 +0.675 -1.804) trk:--  <- placeholder
right (-0.151 +0.675 -1.804) trk:--  <- same point: the shared placeholder
```

Zero `Tracker diverged ... Resetting` lines in the whole session — the origin walked there,
it did not teleport. Meanwhile, inside the tracker, the same seconds:

```
[pushPose] Found pose      +153 in 8 s      (~19/s)
"not publishing it"        +23  in 8 s      (post-refinement POSE_MATCH_GOOD gate)
constellation sample #     +0                (driver-side: nothing arrived at all)
```

and the camera-relative poses being produced were **correct**:

```
pos  0.195 -0.045 -0.429      (right)
pos -0.063 -0.044 -0.474      (left)
```

Two hands 26 cm apart, 45 cm in front of the headset. The solver was working perfectly. 130
good poses per 8 s were composed into world coordinates ~8 m from origin and dropped by a
check that thought it was rejecting nonsense.

## Why nobody saw it for a week

The drop logged at **`WMR_DEBUG`** — a per-poll firehose level no real session runs at — and
its counter (`out_of_range_count`) lives only in that line. From a normal session the drop
path is *completely invisible*: no counter, no rate, no symptom except hands that park.

Roughly an hour of this investigation went into inferring, by diffing counters by hand across
8-second windows, what a single visible log line would have stated outright. **A drop path
with no visible counter is a trap**, and this one had been armed since it was written.

## Where 5 m came from

Commit `b7c929c17` (2026-08-12), whose comment is still in the source: *"A controller is on
the end of an arm. Anything beyond a generous room away is not a bad measurement of where it
is, it is a failed solve reporting a number — observed live: `pos=(-3432890, -7235085,
-15194503)`, i.e. thousands of kilometres."* The motivation was real and the check catches
that case. The number was a round guess ("a generous room away"), never validated against a
drifting origin — which is exactly what broke it a week later.

## The fix (patch 0085)

One check was doing two different jobs. They are separated:

**(a) Physical plausibility — camera-relative, in the tracker.** What bounds a tracked
object is its distance to the *camera that saw it*. That is `Txr_cam_device`, already
computed in `Camera::pushPose` right after RANSAC-PnP refinement, and it is independent of
where the origin drifted to. A hand cannot be 8 m from the headset looking at it; a ghost
lobe routinely is.

Carried as a **per-device** field, `t_constellation_tracker_device_params.max_camera_range_m`,
**not** a tracker-wide constant — because the right value is a property of the **rig
topology**, not of the tracker:

| driver | camera topology | bound |
|---|---|---|
| `wmr` | cameras on the wearer's head, object handheld | **3 m** |
| `rift`, `pssense` | external stationary sensors, room-scale | **0 = unbounded** (unchanged) |

A blanket 3 m in shared code would have silently degraded any external-camera rig whose
tracked object is legitimately metres from the sensor. (Latent today — that path is opt-in
and off by default — but it is shared code with open upstream MRs.)

It gates the `last_known_pose` update **as well as** the publication. Gating only the
publication would have left the poisoning path 0082 exists to close wide open: an impossible
pose would still have become the prior the next search starts from.

**(b) Absurdity — world-frame, still in the driver.** Keeps catching the
finite-but-astronomical solves, now as `WMR_CONSTELLATION_MAX_RANGE_M` (default **1000 m**,
throttled **`WMR_INFO`**, and the line says out loud that if the wearer has not moved that
far, the origin has drifted and good samples are being dropped).

**Coupling, stated because it is not obvious:** (b) is only safe at 1000 m *because* (a)
filters ordinary bad solves upstream. Disabling (a) while leaving (b) at 1000 m would let a
500 m solve into the relation history, where the velocity estimator would turn it into an
implied ~19 km/s and hand that to prediction — this project's known "fling" class.

## Verification

**Forced reproduction**, which is what turns this from inference into proof:
`WMR_CONSTELLATION_MAX_RANGE_M=0.5` makes hands at 45 cm exceed the world bound, simulating a
far-away origin without waiting for drift. Result: 124 drop lines, **0 samples delivered**,
and the wearer, blind to the configuration, reported *"los 2 joy anclados a dos metros a mi
derecha en el mismo punto, como antes"* — the identical symptom, on demand.

**Camera-relative gate proven live** by forcing it too: at `MAX_CAM_RANGE_M=0.2` it rejects
at 0.43 m and 0.52 m — the true distances of two controllers on a desk from the headset,
which independently confirms the quantity being measured is what it claims to be.

**Worn A/B, 60 s windows, same rig, same session** (positional presence, sampled at the
driver's own output):

| arm | left | right |
|---|---|---|
| baseline (bug live) | 1.3% | 2.0% |
| range fix | 46.3% | 47.2% |
| range fix + 0084 tracker gate @14° | 27.0% | 1.8% |
| **range fix + 0084 tracker gate @30°** | **47.7%** | **45.5%** |

Best worn numbers this project has measured (previous best: 37.2% / 22.2% on the everyday
rig, T220; 4.55% / 30.3% worn, T215) and the first time **both** hands are present at once.

## 0084's own verdict, now that it is measurable

The tracker-side gravity gate could not be evaluated before, because there was no working
baseline underneath it. With one:

- **14° (the suggested value) is a net negative** — right hand 47.2% → 1.8%, ~7000 rejects,
  delivery cut 4×.
- The rejected-angle distribution explains it: real ghosts cluster at **75-105°** and
  **135-180°**, but **16 of 70** logged rejects sit at **15-30°** — true-lobe samples with
  worn, in-motion gravity noise. The 14° default was calibrated from a **static desk**
  capture where the true lobe measured p90 4.3-6.5°; worn and moving is a noisier regime.
- **30° is the measured value**: neutral on presence, ~400 rejects, ghosts still killed.

## What is still open

Residual jumps, measured from the delivered poses: **79-100% horizontal, p50 0.35 m, both
hands**. A purely horizontal displacement at near-constant magnitude is the geometric
signature of a rotation about the vertical axis — the **near-pure-yaw ghost**, which every
gravity gate is blind to by construction (yaw does not move the down vector).

The layer that should catch it is the yaw prior, and it is **provably inert**: `yaw prior`
logged **zero** rejections across the whole session while 3900 solve-yaw corrections ran with
errors up to 22.8°. Its gate only engages once `solve_yaw_locked` is established, and **no
log line anywhere reports whether that lock ever forms** — so the chicken-and-egg T221 named
cannot even be observed today. First step on that thread: make the lock state visible.

## Lesson, generalised

Two of this session's four hours went to a check that was *correct in intent, wrong in
frame*, and *silent in failure*. Both properties are worth hunting for elsewhere in this
codebase:

1. **A threshold on a composed quantity inherits every term in the composition.** `|world
   position|` looked like "how far away is the hand"; it was actually "how far is the hand,
   plus how far the origin has drifted". Bound quantities in the frame where the physics
   lives.
2. **Any silent `return` in a data path is a future investigation.** The two rules that fell
   out and are now enforced in the patch: a drop path gets a throttled counter at a level a
   real session runs at, and a log line names the *reason it fired*, not a generic one — the
   `else` branch that would have blamed the yaw gate for a range rejection was fixed for the
   same reason.
