# 128 — Status check 2026-09-23: what is left to move forward, by front

Requested by the user as "que nos falta para avanzar" across five fronts: upstream branches,
controller 6DoF, headset 6DoF, latency, and title compatibility. This doc consolidates the
current state of each from existing records, states the one concrete next action per front, and
is meant to be re-read (not re-derived) at the start of the next session on any of them.

## 1. Upstream Monado branches

Seven MRs open against `monado/monado`, all from `Wintch/monado`:

| MR | Branch | State | Blocked on |
|---|---|---|---|
| !2967 | `wmr-hid-resilience` | open, `can_be_merged` | our own public promise to rpavlik (re-pair G2 controllers to system Bluetooth and report on `wmr_bt_controller.c:69`) — **needs a working USB BT dongle**, ours (Nisuta) is dead |
| !2968 | `wmr-controller-input-fixes` | open, approved by thaytan, bl4ckb0ne's asks fixed | reviewer silence, nothing to do |
| !2969 | `wmr-camera-stream-toggle` | open | reviewer silence, nothing to do |
| !2971 | `steamvr-drv-origin-rpath` | open, second fix pushed 09-21 | bl4ckb0ne's re-review |
| !3004 | `companion-hot-reconnect` | open | reviewer silence (never looked at) |
| !3020 | `wmr-camera-stop-drain` | open, just created 09-23 | too new, no activity expected yet |
| !3021 | `euroc-playback-cam-count` | open, just created 09-23 | too new |

**The one actionable item across all seven**: buy a working USB Bluetooth dongle (TP-Link UB500 /
UB500 Plus, RTL8761B, mainline `btusb`). It unblocks !2967's promise, tests Monado's own
direct-Bluetooth controller path for real, and separately unblocks G2 motion controllers under
Oasis/Ignition on Windows-side testing (`docs/121`). Everything else on this front is waiting on
someone else; do not nudge. See `docs/18` for the full MR-by-MR log.

## 2. Controller 6DoF (constellation tracking)

The deepest open front. State as of `docs/125`/`docs/126` (2026-09-14/15):

- Root cause of the "controller loses position" complaint traced to a blob-ownership deadlock
  (`solve_yaw_locked` → `trySeededRecovery` gate → `correspondence_search`'s shared-pool
  exclusion) and fixed with a `CS_FLAG_MATCH_ALL_BLOBS` escalation. **Live-verified as real but
  partial**: the fix fires correctly (15 contested attempts, alternating between both
  controllers) but **0 of 15 actually recovered a pose**. Something else still blocks full
  recovery.
- **Next concrete step, not started**: pick a specific failing frame that had a high total blob
  count (26-36 were seen) where the contested search still failed, and trace it by hand through
  `correspondence_search`/`pose_metrics` to see exactly which check rejects it — a RANSAC-PnP
  outright failure vs. a found-but-gravity/reprojection-rejected candidate. That distinguishes
  "still the correspondence/ghost problem `docs/125` already named" from "something new."
- A second, independent wiring of the same upstream constellation tracker exists on
  `hare_ware/monado`'s `wmr-new-constellation-tracking` branch. A full A/B test plan was
  researched and handed to dev on 2026-09-17
  (`handoff-20260917-hareware-ab/HANDOFF.md`, on both the everyday machine and iashur) —
  **not yet run**. His branch is predicted to segfault once a controller registers
  (`get_tracked_pose` assignment is commented out) and never fuses the optical solve into the
  output pose, so it likely will not itself unblock anything — but the A/B needs to actually run
  to confirm that rather than assume it. Public issue #1 on his fork is posted, no reply, do not
  nudge (checked live 2026-09-23: still 1 note, ours).
- The floor/scale calibration procedure requested back in August (place controllers on the
  floor, compare against reported displacement) was never designed — confirmed no such
  procedure exists anywhere in the repo's docs.
- The controller hotplug gap (`wmr_hmd.c` only reads controller status once, at startup —
  works on Windows, not on Linux) remains workaround-only (power controllers on before
  `jack-in-wayland.sh up`). Not scoped. Relevant to booth robustness
  (`docs/demo_day_prep`/[[project_demo_day_prep]] in memory) since a guest who forgets to power
  controllers on first is a realistic failure mode.

## 3. Headset 6DoF

Not an open front — head-tracking SLAM (Basalt) is confirmed working across multiple full game
sessions, only occasional divergence on long-uptime sessions. What people mean by "6DoF still
open" is exclusively the controller-tracking front above.

## 4. Latency

Root cause of Dalí's "redraw" complaint closed: it was pose staleness, not drift
(`docs/113-dali-redraw-is-pose-staleness.md`). Shipped and wearer-validated profile: detection
density 30/2, `XRT_COMPOSITOR_SCALE_PERCENTAGE=85`.

Two things left open on this front:
- The "delay when walking" residual is explained by `SLAM_PRED_FREEZE_POSITION=1` holding
  position flat across the prediction gap. The lever built for exactly that,
  `SLAM_PRED_POSITION_HORIZON_MS` (patch 0100, default 0/OFF), **has never been swept**.
- A wearer-felt difference from a donning-position A/B had no measured correlate; a blinded
  repeat was offered and never run. Do not resurrect the donning-position idea without it.

Both no longer need a worn session to test: `docs/124` (offline SLAM config sweeps, headless,
record once + replay through the real tracker) can run the horizon sweep directly. **Next step**:
run that sweep before asking for any more wearer time on this front.

## 5. Title compatibility

8 of 12 VR-capable titles in the library work. Of the remaining 4:

- **DOOM VFR**, **Sniper Elite VR** — OpenVR-only, need OpenComposite; blocked upstream, repo
  dormant since 2025-07 (`docs/doom_vfr_openvr` in memory).
- **Aperture Hand Lab** — renders real content but needs a room-scale/guardian boundary this
  Monado/Linux stack does not expose; never investigated whether one exists to configure.
- **The Night Cafe** — fails identically on Windows (joysticks work there), so it is the title's
  own bindings, not a Linux/Monado bug. **Batman** needs manual key reassignment, same category.

**The one untested lead for the last two**: lab patch `patches/monado/0011` ("d/wmr: Add native
WMR motion_controller binding profile") exists but has never been evaluated against this
symptom. The hypothesis (titles that ship explicit WMR bindings behave, titles that fall back to
a generic profile need hand-remapping) fits Night Cafe/Batman's pattern but is unverified.

## Priority call

If only one thing gets picked up next, it should be **buying a working USB Bluetooth dongle**
(§1): it is the only item on any of these five fronts that is purely external (not blocked on a
reviewer, a wearer session, or more of our own tracing) and it unblocks three separate things at
once (the !2967 promise, the direct-BT controller path, and Oasis/Ignition controller support).
