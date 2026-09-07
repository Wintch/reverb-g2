# 104 — Dalí session-anchor guard runaway (2026-09-05): what's felt, is it a regression, and what to do next

> **Follow-up 2026-09-07 — see [113](113-dali-redraw-is-pose-staleness.md).** A worn A/B of `SLAM_SESSION_ANCHOR_RADIUS_CM` (300 → 150) confirmed the felt jump *is* the radius, but halving it only trades few-big corrections for many-small ones, which the wearer reads as high-frequency jitter. The radius stays at 300. 113 also rules out, with data, the recall-cache leak and the `RESET_OFFSET_CARRY` pinning caveat as explanations for reset storms.

Fulfills the forward reference `docs/100` left dangling ("see the next section below (the
191-reset anchor-guard finding)"). Trigger: today's live 591360 session tripped
`SLAM_SESSION_ANCHOR_RADIUS_CM=300` 191+ times in ~28 minutes, almost every reset a ~3.0-3.13 m
excursion, against the 2026-08-29 approval test's 6 resets of 0.02-0.21 m over 4.8 minutes — and
the wearer felt a real, distinct "went about a meter down and rotated 180°" event during a fast
yaw, coinciding with a late burst of 14 resets in ~40 s. Two independent investigations ran (live
forensics on the session's logs/CSVs/code; historical research on what changed since approval).
This doc synthesizes both into one diagnosis and a call on the live, approved booth profile.

## 1. The CSV puzzle, resolved — what the wearer actually feels

Three distinct streams, confirmed from `t_tracker_slam.cpp` source, not just log-reading:

- `tracking.csv` (~28 Hz): raw SLAM but **rebased by `reset_offset` before the write** — the
  code's own comment says every CSV/EuRoC writer sees the corrected continuous frame;
  `SLAM_RESET_OFFSET_CARRY=0` would restore the literal teleport. Not the raw signal it looks like.
- `filtering.csv` (~180 Hz): predict_pose → `apply_correction_spread` → filter — **this is the
  stream the application actually receives, and what the wearer physically feels.**
- `prediction.csv` (~180 Hz): raw prediction, no correction spread.

The reset transition is deliberately engineered invisible: it re-anchors onto the *last known-good*
pose, so a clean, isolated reset shows no snap in any stream. But the guard check and every reset
are both gated on `nts > quiet_until` (confirmed at `t_tracker_slam.cpp:1210` and `:1368`), and
every reset — anchor, speed, or quat — sets `t.auto_reset.quiet_until = nts + 2LL *
U_TIME_1S_IN_NS` (`:1240`, `:1397`). That is a **2-second blind window per reset where nothing is
checking divergence at all**. Any overshoot Basalt produces while re-localizing inside that window
reaches `filtering.csv` — and the compositor — completely unclamped, before the *next* reset can
even fire.

The felt-event cluster (#178-191) is the exact onset of the runaway, and it confirms this
mechanism directly: 12 of 14 post-reset windows in that cluster are unremarkable (2-8 cm, <1.5°),
but two are real — reset #178's window shows a 3.8-6.0 m position excursion in 33-300 ms with only
~8-9° rotation, and #181's shows 2.6-3.7 m with ~2°. **No rotation anywhere near 180° exists in
this cluster at any timescale.** The wearer's "180°" was almost certainly their own real fast yaw
(matches their account) landing *at the same moment* as a genuine 2.6-6.0 m position collapse
leaking through the guard's blind spot — not the reset snap, which is invisible by design, and not
a rotation artifact of the guard at all. **What's felt is the raw unbounded drift inside the
2-second blind window, not the reset itself.**

## 2. Regression since approval, or a gap in what approval tested? Best-evidenced call

**Reframing the magnitude comparison** (this matters — the task's "15-150x bigger" framing compares
mismatched quantities): approval's "0.02-0.21 m carried" is the *residual after* the 3.00 m-radius
reset, not the pre-reset excursion — `docs/80` says outright the guard "catches the ramp at 3 m."
Approval's actual trigger points were therefore ~3.02-3.21 m — essentially the **same magnitude**
as today's steady-state 3.00-3.13 m over the first ~26 minutes. For the bulk of today's 191+
resets, there is **no magnitude regression** — this is the guard doing exactly what it was measured
to do in `docs/80`, at the same threshold, with the same known limitation already on record then
("restarts SLAM internals but never moves the carried output back toward the anchor").

What is new, and has no precedent in the approval data:

- **Rate.** Approval: 6 resets / 4.8 min. Today, first 26 min: steady ~9 s/reset (already several
  times approval's normalized rate). From minute ~27: the rate hits the `quiet_until` floor
  (~30/min, essentially every 2 s) — a regime approval's 4.8-minute test never ran long enough to
  reach.
- **Magnitude growth.** Flat 3.00-3.09 m for 26 minutes, then **monotonically climbing** — 3.0 m →
  4.4 m+ by minute 34, still live and worsening at last read. Approval never saw growth; it saw a
  flat ramp caught at the same radius every time.
  `docs/80`'s "fake pacer fell behind" stayed flat 5-15/min the whole session — ruling out
  compositor/GPU frame pacing as the driver of the reset-rate climb; this reads as a genuine VIO
  tracking-quality collapse, not a rendering symptom.
- **The felt-cluster excursions themselves** (3.8-6.0 m, 2.6-3.7 m within single 2-second windows)
  are 10-20x approval's carried residuals and were never approached in 4.8 minutes of gentle
  gaze-dwell motion.

**Rig config is unchanged**: `TITLE_PROFILES["591360"]` is bit-identical to the commit `287c2b7`
approval applied (`SLAM_THREADS=6`, `WMR_CONSTELLATION_CONTROLLERS=0`, anchor radius, quat check —
all untouched), and `~/vr/basalt-g2-config.json` predates approval too. This is not a profile-drift
story.

**What did change, verified directly on the rig** (not just cited from docs): `apt history.log`
shows the kernel 6.12.101→6.12.107 upgrade + NVIDIA 595 DKMS rebuild actually ran on **2026-09-03
05:37:59** — despite `docs/92` recording it as "deliberately deferred." `uptime -s` shows this
machine only **booted into 6.12.107 today at 11:48:58**, a few hours before the problem session.
No `post-update-verify.sh` output or physical-90Hz-with-headset-on record exists anywhere in
`docs/` or `~/vr/logs/` for this boot — the exact gate `docs/24` requires before trusting a DKMS
rebuild was never run. This is a real, unverified, just-activated variable, co-timed almost exactly
with the runaway session.

**Call**: this is not a clean either/or, and it would be dishonest to force it into one. The
*steady-state* portion (first 26 minutes, 3.00-3.13 m resets) is best explained as **a gap in what
approval tested** — 4.8 minutes of gentle motion was never going to surface a slow multi-minute
degradation pattern, and the trigger magnitude itself matches approval exactly. But the
**escalating tail** — rate climbing to the 2-second floor, magnitude growing unboundedly minute
over minute, and the two genuine 3.8-6.0 m felt-cluster excursions — has no precedent in the
approval data at all, and lines up with an untested kernel/driver combination that project rules
already flag as needing verification before being trusted. It is also consistent with, and likely
compounded by, Dalí's already-known P2-gate finding (landmark starvation under fast yaw for a
standing wearer, `docs/80`) — the felt cluster did coincide with fast yaw. **Best-evidenced
single call: an untested-duration/untested-yaw gap in the original approval test, plausibly
compounded by a real, unverified, just-booted kernel/driver regression that this project's own
process failed to gate on this time.** Neither investigation's data lets either factor be ruled
out — they need to be separated by test, not asserted.

## 3. Recommendations, prioritized

1. **Flag `TITLE_PROFILES["591360"]` / the approved `demo-591360-6dof` booth button as needing
   re-validation before its next live use — this is not hedge-able.** The steady-state magnitude
   match to approval does not cover the escalating tail or the fast-yaw excursion cluster; both
   are structurally outside what a 4.8-minute gentle-motion test could have shown, and a wearer
   already reported a real, distinct bad sensation today on this exact profile. The booth-safety
   action does not need the root cause settled first.
2. **Immediate and cheap**: run the gate `docs/24`/`docs/92` already require and that was skipped —
   `post-update-verify.sh` plus a physical 90 Hz check with the headset actually on — before any
   further booth session. The kernel/DKMS combo has been live for one boot and zero verification;
   this is exactly the failure mode that check exists to catch, and it costs minutes.
3. **Re-run the approval-style test, but fix both gaps it had**: (a) run it for ~28 minutes, not
   4.8, to see whether the same flat-then-climbing rate/magnitude pattern reappears even on an
   otherwise clean rig — if it does, that's a duration/duty-cycle finding independent of the
   kernel; (b) deliberately add a fast-yaw component partway through (not just gaze-dwell), mirroring
   Dalí's known P2-gate landmark-starvation-under-yaw finding, to see whether that alone reproduces
   #178/#181-style multi-meter excursions.
4. **Split kernel from SLAM/duration as the next isolating step**: run (3) once on the current
   system (6.12.107, post-DKMS-rebuild) and once after rolling back to 6.12.101 (the last kernel
   `docs/92` actually verified) if that's practical here. Reproduction on both = a genuine
   SLAM/duration+yaw gap in the anchor-guard design (candidate fixes: shrink the 2-second
   `quiet_until` blind window, or have repeated same-direction resets nudge `reset_offset` back
   toward the anchor instead of only restarting SLAM internals, since the guard's own documented
   limitation is that it never does this). Reproduction only on 6.12.107 = pin the booth to 6.12.101
   until the 595 DKMS rebuild is independently re-verified against 6.12.107, per `docs/24`.
5. Whichever isolates it, don't leave the approved profile running unexamined between now and the
   next booth slot on the strength of "the trigger magnitude matches approval" alone — that
   argument only covers the first 26 minutes of today's session, not the part that actually
   produced a felt bad experience.

## 4. Post-update verification run, finally done (2026-09-05, later the same evening)

Ran the gate `docs/24` and this doc's own §3 recommendation #2 call for — `post-update-verify.sh`
— which had never been run for this 6.12.107 boot before now. Read-only/non-disruptive; rig was
confirmed idle (`pgrep -af monado-service` empty) before touching anything.

**Checks 1-4 (everything about the kernel/DKMS/driver combination itself) all passed clean:**

1. Running kernel (`6.12.107+deb13-amd64`) matches the newest installed one — the reboot did pick
   up the new kernel, no stale-GRUB-default problem.
2. `dkms status` shows the nvidia module installed for the currently running kernel.
3. The fresh `make.log`
   (`/var/lib/dkms/nvidia/595.71.05/6.12.107+deb13-amd64/x86_64/log/make.log`) shows all 4 tracked
   patches applied cleanly, no reject markers, exit code 0.
4. `verify-bpc.sh`'s physical test woke the panel, took a real DRM lease, and presented
   **90.02 fps then 90.00 fps at requested mode 90.001 Hz** — the load-bearing 90Hz patch is intact
   on this build.

**Check 5 (`preflight.sh`) failed, but on an unrelated, expected condition**: both controllers
came back "paired, offline" (powered off — expected, the user had just closed their session; not
a hot-add gap since nothing was launched). USB enumeration (5/5) and the HMD's own DP connector
(EDID fingerprint confirmed, `non-desktop=1`, real modes) were both READY. So the script's overall
exit code was 1/FAIL, but nothing in that failure implicates the kernel or DKMS rebuild — it's
purely "controllers weren't powered on," unrelated to this investigation's lead.

**Housekeeping note**: `verify-bpc.sh`'s test (T238) intentionally leaves an `hmd-vk` presenter
running indefinitely for a human to look through the headset and confirm visually. No one could
wear the headset during this run, so after capturing the fps numbers above, the leftover `hmd-vk`
and `panel-status.py` processes were killed and T238 was closed in `testlog.py` with an explicit
note that it was **not** visually confirmed by a wearer — so the log doesn't misrepresent this as
a real physical check.

**Additional manual check, beyond the script**: with the rig re-confirmed idle, ran a bare
`jack-in-wayland.sh up 1 3dof` / `down` cycle through the real Monado path (not the standalone
DRM-lease tool `verify-bpc.sh` uses). Log line was identical to every launch tonight:

```
DEBUG [get_primary_display_mode] found display mode 4320x2160@90.00
DEBUG [get_primary_display_mode] Updating compositor frame interval from 11111111 (90.000001 Hz) to 11110987 (90.001000 Hz)
```

Teardown confirmed clean afterward: no `monado-service`, no `hmd-vk`, IPC socket removed.

**`~/vr/basalt-g2-config.json`**: mtime still `Aug 27 08:31`, and its content is byte-identical
(`diff` + matching md5) to the git-tracked `scripts/basalt-g2-config.json`, last touched by commit
`db4457f` (Aug 27 08:34, the same commit that set `SLAM_THREADS=6` and removed 0098). No silent
drift since before approval — this doc's §2 claim holds up under a second, direct check.

## 5. What this settles, and what it still doesn't

**Settled**: the specific, concrete worry raised in §2 — that the untested 6.12.107 kernel + 595
DKMS rebuild silently broke a patch, lost kernel/module alignment, or degraded 90Hz negotiation —
is not what's happening. All 4 patches applied clean to a fresh build tied to the exact running
kernel, and 90Hz negotiates identically through both the raw DRM-lease path and the real
`jack-in-wayland.sh`/Monado path used every night. The only failing check (controller power state)
is an environmental non-issue, not a build defect.

**Not settled, and cannot be settled by anything run tonight**: whether this kernel/driver
combination behaves identically to 6.12.101 under the conditions that actually produced the
runaway — 26-34 minutes of continuous SLAM tracking, sustained real motion, and a deliberate fast
yaw. Every check performed here is a point-in-time or short-duration probe (a 25s fps sample, a
few-second jack-in cycle) — structurally incapable of surfacing a slow multi-minute degradation or
a fast-yaw-triggered excursion. `post-update-verify.sh`'s own header calls this "necessary but NOT
sufficient" for exactly this reason.

**Verdict — go/no-go on the kernel/DKMS lead specifically**: the automated gate is clean (modulo
the unrelated controller-power failure), so nothing found tonight argues for a pre-emptive rollback
to 6.12.101. But this does **not** clear `TITLE_PROFILES["591360"]` / the `demo-591360-6dof` booth
button for unattended live use — §3 recommendation #1 still stands exactly as written. **What still
requires the user to physically wear the headset**: the full-duration (~28 min) approval-style
re-test with a deliberate fast-yaw component partway through, per §3.3/§3.4 — ideally once on the
current 6.12.107 build and once rolled back to 6.12.101, to actually separate the kernel/driver
combination from a duration/duty-cycle gap in the original approval test. Nothing performed
tonight substitutes for that.
