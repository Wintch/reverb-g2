# Context for the 90Hz lab agent

> ## START HERE NEXT SESSION (2026-08-17, ~08:00, lab machine) — optimization round 1
> DONE on top of the closed saga (read T199-T203 + `docs/44`): machine pinned
> (`vr-power-setup.sh --apply`, first time ever — governor was schedutil all along),
> `SLAM_THREADS` default now **4** (per-stage timing went live for the first time via
> 0057 and showed the REAL #1 cost is the optical-flow TRACKING stage, 48.5 ms p50 —
> the VIO backend is only ~12 ms; threads=4 on the pinned machine halves tracking to
> 28.4 ms, pose p90 99.9→66.8 ms, wearer-confirmed). Final wearer state: "joysticks
> anclados, nunca desaparecen, fluidos" (best of the project), head "bastante bien, no
> perfecto" — fast rotation still shows correction. Monado = 0049-0057 (`0a8fc0e81`),
> basalt = 0001-0010, launchers carry the docs/43 contract + all hardenings.
>
> **NEXT ROUND MAP, value-ordered, every item measured (T203)**:
> 1. **Motion-amplified snap smoothing** — worn snaps 4-4.6 Hz ≥0.5°/5 mm vs only
>    0.088 Hz at rest (93% positional ~6 mm, backend re-triangulation jitter): the felt
>    component rides motion; weakly anchor-correlated (×1.10), so smooth BETWEEN
>    anchors (0044's timestamp-compensation open item / correction spreading), not just
>    at arrival.
> 2. **Roll drift is motion-induced** — +0.84-0.93°/min worn (R²=0.80) vs −0.027
>    sign-flipping at rest: gyro-bias estimation under dynamics in Basalt, NOT static
>    calibration. The T162 left-roll debt finally has a number and a direction.
> 3. **New rare stall class**: 2.15-2.9 s pipeline stalls (~1/15 min, distinct from the
>    632 ms saga) fling dead-reckoning 7.8-14.4 m and snap back on the next anchor —
>    at rest, zero app: a pure stall SUFFICES (sharpens T162's speed framing; 0057's
>    reset-offset-carry softens the teleport class but the stall itself is unexplained;
>    prediction layer should also clamp DR excursions during anchor gaps).
> 4. **Keepalive v2**: 0054 is query-driven (get_tracked_pose) so it NEVER runs with 0
>    clients — exactly the unattended case it exists for; A/B self-invalidated (0
>    resends, controllers slept on schedule = clean control baseline). Move to a
>    driver-internal timer. Cold power-on stays impossible (T200).
> 5. **GPU wattage cap, user directive**: this board "performa casi igual en 70%";
>    `vr-power-setup.sh --gpu-limit 70` exists but was NOT applied yet (needs sudo +
>    a pacing A/B under 90 Hz load); `--apply` should learn a per-box config
>    (`~/vr/power.conf`), nothing hardcoded. Also guard the benign EPP write on
>    acpi-cpufreq (line ~106 glob error).
> 6. Constellation solve-rate / assignment-prior for the ~1 cm controller position
>    breathe; guards 0056 (MAX_BLOBS / LOST_SEARCH_DIV) are in, default off, awaiting
>    per-box calibration.
> 7. Position y-axis convergence transient at rest (−57→−12 mm/min decaying, −770 mm
>    over 31 min, slam-20260817-063841).
>
> **USB2 branch**: 3 drops tonight (pre-launch, mid-game 06:27 — which stalled USB3
> cameras 14-24 s, suspect shared `hid_lock`, worth its own investigation — and idle
> ~07:05). PC-end USB-C replug 2/2 tonight (T186 holding). Log truncation per run
> means mid-game forensics die with the next launch — consider log rotation.
> **FAIL_MARKER** still unimplemented in both launchers (docs/43 gap).

> ## SUPERSEDED same morning (~06:40) — the saga-closing header below stands; round 1
> above builds on it.

> ## START HERE PREVIOUS (2026-08-17, ~06:40, lab machine) — THE T192-T199 SAGA IS
> CLOSED: the 632-666 ms magic number was **0049's own 10 ms backoff sleep throttling the
> shared read loop** (companion + hololens/IMU share one sequential thread), pinning the
> IMU stream ~630 ms stale (kernel ring fills at ~100 reads/s vs ~250 packets/s), which
> `hw2mono` absorbed, pushing camera stamps ~630 ms into the future. **Fixed in 0055**
> (backoff = deadline-skip, no sleep; `WMR_COMPANION_BACKOFF_BLOCKING=1` restores old
> behavior for A/B) and **validated with the storm active** (39792 consecutive companion
> errors): cam-vs-IMU skew flat −4..−0.7 ms over 8 min/14400 frames, anchor age now
> honest (~144 ms idle). Read `docs/pruebas.jsonl` T199-T201 and `docs/44` first.
> This also explains why the collapse appeared WITH 0049 and never before it (T193).
> **WEARER-VERIFIED same morning (T201, ~06:17): "perfecto! se fue"** — head response
> immediate, controllers "mejoraron mucho tambien" (the throttled loop also carried the
> tunnelled controller packets). Objective, same minutes: skew flat −0.9..−2.1 ms under
> full load, anchor age honest 136-193 ms and gyro-bridged, pose out ~10 Hz / CPU ~703%
> — the backend stays saturated under full constellation load but the wearer no longer
> feels it: perceived latency was the debt HIDDEN from prediction, not the debt itself.
>
> **What needs the WEARER next session, in order**: (1) feel test — head rotation should
> now be immediate (the real pipeline debt ~150-600 ms under load is finally VISIBLE to
> prediction and gyro-bridged); the ~1 s constant lag of T197 should be gone; (2)
> controllers on for a real session (constellation budget stays OFF — 3 ms kills matches
> on both machines, docs/40's blob-guard is the refined path); (3) the keep-awake A/B:
> `WMR_CONTROLLER_KEEPALIVE_S=600` (0054, default off), controller motionless >15 min,
> LED + `imu_age_ms` as instruments — decides if the prototype graduates or reverts
> (cold power-on from software is settled-IMPOSSIBLE, see T200; the timer may be purely
> motion-based, in which case only real motion helps).
>
> **Still real and open after the clock fix**: the backend costs 133-400 ms/frame under
> head motion (SLAM_THREADS 2 vs 4 indifferent) so the pipeline still runs saturated
> when worn — prediction now hides it for rotation, position benefits less (0045's
> asymmetry); the keypoint-detection cost (docs/40) is the next real lever if position
> feel needs it. Basalt 0009's drop-oldest is a measured NEGATIVE result (KF-per-frame
> ratchet, 66→400 ms) — 0010's blocking capacity-2 is the kept shape; don't revisit.
> FAIL_MARKER is unimplemented in both launchers (docs/43 gap, T200).
>
> **State**: lab `monado-service` = 0049-0055 (`6aa1fbd92` on `lab-full`), basalt =
> 0001-0010 (`696a02f` on `lab`), binaries current; both launchers carry the docs/43
> contract + `pgrep -x` + the builder-wmr success check. An idle soak session may still
> be running from the validation — `~/vr/jack-in-wayland.sh down` before relaunching.
> MR !2967 reply still pending — the story is now complete enough to write it well.

> ## SUPERSEDED same night (2026-08-17, ~05:30) — kept for the reasoning chain; the
> "surgical next step" below was executed and the hypothesis it named (startup-burst
> anchor bias) was DISPROVEN by the very first ingest capture (fresh sessions start
> honest; the bias is a load-onset DRIFT, and its true source is 0049's sleep, above).
> Original header: the 632-666 ms magic number is ROOT-CAUSED AND PROVEN with live data: **the camera frame timestamps run
> p50 +578 ms (max 610) in the FUTURE of the query/IMU clock** — a stable clock-domain
> conversion bias born upstream of Basalt. Read `docs/pruebas.jsonl` T196-T198 and
> `docs/44-clock-domain-skew.md` first; they supersede the "logical blocking mechanism"
> framing below (it was the right hunch, and it is now a named, measured mechanism).
>
> **What the bias explains, all at once**: docs/39's "each processed image is ~600 ms
> ahead of the arriving IMU" (the collapse mechanism the handoff's 0007/0008 fix treats
> symptomatically — the fix is real and VERIFIED on the lab headset, T196, the minimal
> repro no longer collapses); the ±1% stability of the 632-666 ms period across runs and
> machines (a code-level constant, not hardware); and the new headline problem: **the
> wearer feels a constant ~1 s head-motion latency** ("muy claro y sin cortes, pero con
> delay constante", first movement included, does not drain at rest) because the pose
> content is genuinely ~0.6-0.7 s stale while its stamps claim ~90 ms — so dead
> reckoning (healthy, never fails — grep proved zero fallback hits) integrates only the
> ~90 ms the lying stamps show it. Monado does NOT re-stamp (`flush_poses` uses
> `data.timestamp` verbatim); the bias arrives from upstream conversion.
>
> **Next step, surgical**: read `wmr_source.c`'s `cam_hw2mono` / clock-offset path and
> find why converted camera stamps land ~+600 ms vs monotonic AT INGEST — a 3-line log
> of converted-ts minus `os_monotonic_get_ns()` at the push site settles it. Strong
> hypothesis: the offset estimator anchors during the startup burst of ~19 buffered
> frames (19 × 33 ms ≈ 630 ms), which would make the bias constant per session, portable
> across machines, and load-indifferent — everything observed. **Minefield**: T162
> already measured `m_clock_windowed_skew_tracker` as a dead end (drift 243-1002 m);
> don't reach for it as the fix.
>
> **Also tonight (T196-T197)**: handoff-20260817 fully integrated (basalt 0001-0010,
> monado 0049-0052, docs/39-43 + docs/re-windows/); `jack-in-wayland.sh` gained docs/43's
> up/dev/quiet/down contract PLUS two live-failure hardenings (all `pgrep -f` →
> `pgrep -x` after `down` killed the agent's own shell; launch success now REQUIRES
> `Using builder wmr` — a companion re-enumeration mid-probe produced a silent Simulated
> HMD session that passed every old check, T050's trap caught live and now enforced in
> code). The repo's `scripts/jack-in.sh` still does NOT have the contract (docs/43: the
> reference lives on the everyday box — standing reconciliation debt). **Basalt 0009's
> drop-oldest on the OF→VIO queue is a measured NEGATIVE result** (keyframe-per-frame
> ratchet to 2.5 Hz — 0010 corrects it to blocking push into the capacity-2 queue; keep
> that shape). Constellation budget 3 ms reproduces the docs/40 tradeoff on the lab too
> (CPU 487→355% but controllers park at the shared placeholder; blob swamping measured
> num_blobs=29 here — NOT everyday-box-specific; the refined fix direction stands).
> Backend service time is ~66 ms/frame at rest but 133-400 ms under real head motion
> with SLAM_THREADS=2 or 4 alike — the pipeline runs saturated whenever someone wears
> the headset, so every bounded queue sits permanently full; fixing the stamp bias makes
> prediction hide that debt, which is why it is the one high-leverage fix.
>
> **State**: lab `monado-service` = 0049+0050+0051+0052 (`9fe21a089` on `lab-full`);
> `~/vr/basalt` = 0001-0010 (`696a02f` on `lab`); both binaries current. The panel ended
> the night dark from a companion re-enumeration AFTER service open (stale fd, known
> class — a fresh launch recovers it). Jan Schmidt MR !2967 reply STILL pending — now
> with a much better story to tell once the stamp bias is fixed.

> ## START HERE NEXT SESSION (2026-08-16, ~22:10, lab machine) — a real `perf sched` trace,
> not another hypothesis, RULES OUT scheduling/CPU-starvation as the SLAM-collapse mechanism.
> Read `docs/pruebas.jsonl` T195 first; it supersedes the RT-priority theory in the block
> below (which was tested directly and disproved, not just reasoned around).
>
> **Two things done, both negative results, both real progress**: (1) disabled SCHED_FIFO
> max priority on the WMR read thread alone (`WMR_HMD_THREAD_NO_RT=1`, env-gated patch
> already in the lab binary, off by default) — the collapse still happened, so T194's
> leading theory is DISPROVEN, not confirmed. (2) Got a working `perf sched record`/
> `latency` pipeline (needed `kernel.perf_event_paranoid=-1` AND, separately,
> `chmod -R o+rX /sys/kernel/tracing` on the WHOLE tree, not just `events/` — sibling files
> like `printk_formats` being root-only caused a cryptic "incompatible file format" on
> read-back that looked like a corrupt/version-mismatched trace but was actually a
> write-time permission gap) and captured two live collapses. **Result: `WMR: USB-HMD`'s
> own max scheduling delay was 0.026ms. The rest of monado-service's threads (29 of them)
> showed max delay 4.004ms and were actively RUNNING 9.2 of the 15 traced seconds (60%+
> utilization).** Nothing anywhere in either trace comes close to explaining a repeating
> ~632-666ms stall. **The threads are getting CPU time promptly and are NOT starved — the
> bottleneck is a LOGICAL blocking mechanism inside the code itself** (a lock held too
> long, a condition-variable wait that isn't signaled, a queue/timestamp-validation path in
> Basalt's own VIO pipeline getting stuck) — not a scheduler problem at all.
>
> **The strongest remaining clue, still unexplained**: the collapsed interval is
> suspiciously tight (~632-666ms, roughly ±1% jitter) across every run tonight, including
> across entirely separate monado-service processes — that smells like a real code-level
> period (a timeout, a retry interval, a fixed sleep somewhere else in the pipeline), not
> organic system noise. **Also worth remembering**: the onset timing itself has no fixed
> timescale — 6m55s (T192), 0.3s and 8.3s (T194), and yet another mid-length one during
> T195's own trace run — five 0049 runs tonight, five different onset delays, same locked-in
> collapsed signature every time.
>
> **Next step, not started**: read Basalt's own source (a separate upstream repo,
> `~/vr/basalt`, not examined at this level yet) and Monado's `t_tracker_slam.cpp` for a
> lock, queue policy, or timestamp-gating constant anywhere near 632-666ms, or that could
> produce that period as a multiple/derivative of something else. This is a source-reading
> task now, not something more live-hardware cycling will crack on its own.
>
> **State**: current lab `monado-service` binary is 0049 + the `WMR_HMD_THREAD_NO_RT` env
> gate (harmless, off unless that var is set) — NOT pure 0049. A pure-0049 backup is at
> `~/vr/monado/build/.../monado-service.0049-backup` (md5 `e92656c8...`) if a clean 0049
> binary is needed again before this gets folded into a real patch.

> ## START HERE NEXT SESSION (2026-08-16, ~21:32, lab machine) — the SLAM pose-rate collapse
> is now isolated to a MINIMAL repro (0049 + SLAM + constellation, zero app, collapses in
> under a second) with a concrete, code-confirmed mechanism hypothesis. Read
> `docs/pruebas.jsonl` T194 before anything else; it supersedes the block below.
>
> **The collapse needs no app at all, and happens almost instantly.** Killed monado-service
> mid-T193-followup and relaunched 0049 + SLAM + constellation with NO OpenXR client
> connected — the pose interval collapsed from a healthy ~37-86ms to the same ~400-650ms
> signature at sample 7, **roughly 0.3-0.5s after startup**. New wrinkle: it briefly
> recovered (samples 24-30) before locking into the collapsed state for good at sample 31 —
> an oscillate-then-lock pattern, not a one-way trip, suggesting a threshold-crossing
> mechanism. This flatly contradicts T190's own pre-0049 finding that SLAM+constellation
> alone idles clean for 1-2 minutes — same subsystems, same hardware, now collapses in under
> a second with 0049 in the binary. Combined with T193 (0/1 valid pre-0049 run, 45m47s with
> real load, never collapsed), this is strong evidence 0049 is the actual trigger, not CPU
> saturation (monado-service's own CPU measured only 59.1% during this minimal repro, far
> below the 400-550% seen with an app running).
>
> **A concrete, code-grounded mechanism hypothesis** (not yet proven — no scheduler trace or
> fix-and-confirm done): `wmr_run_thread` (runs both `control_read_packets`, where 0049
> lives, and `hololens_sensors_read_packets`, which carries the actual IMU/tracking data)
> calls `u_linux_try_to_set_realtime_priority_on_thread()` at startup — confirmed in
> `u_linux.c` to set `SCHED_FIFO` at `sched_get_priority_max(SCHED_FIFO)`, Linux's absolute
> max real-time priority. Before 0049: a failing companion read looped with no sleep,
> producing a tight busy-spin that monopolized ONE core (T183/T188's 400%+ CPU) without
> necessarily disturbing other cores. After 0049: the thread now sleeps 10ms per failing
> read once past the 50-consecutive threshold (which the universal storm crosses almost
> immediately) — so instead of monopolizing one core, it wakes ~100x/second and, holding
> max SCHED_FIFO priority, INSTANTLY PREEMPTS whatever normal-priority thread (almost
> certainly including Basalt's own workers) is running on whatever core it lands on. Trades
> "one core wasted, contained" for "a system-wide ~100Hz max-priority preemption pulse,
> uncontained" — plausible enough to wreck Basalt's tight VIO timing without the offending
> thread's own throughput ever looking abnormal (which is exactly why T192's own loop-rate
> check, ~100-105Hz healthy, missed it — it was checking the wrong thread's own throughput,
> not what its wakeups do to everyone else).
>
> **Next step, not done tonight**: test the fix candidate — don't hold max SCHED_FIFO
> priority through the punitive backoff sleep (drop scheduling class/priority before
> `os_nanosleep`, or just request a lower priority for this thread given it's now known to
> sleep routinely under the — universal, expected — companion dropout). If that stops the
> collapse, the mechanism is confirmed and 0049 gets a real follow-up fix, not just a
> revert. A `perf sched` trace during a live collapse would also settle it directly.
>
> **Also tonight, unrelated to 0049**: a live Aircar crash (`EXCEPTION_ACCESS_VIOLATION`
> reading address `0x38` in the rendering thread, confirmed via `WINEDEBUG` trace and a
> saved `UE4Minidump.dmp`) turned out to be a genuine Unreal Engine null-pointer bug,
> unrelated to Monado/VR — not investigated further, noted for completeness only.
>
> ## START HERE NEXT SESSION (2026-08-16, ~20:35, lab machine) — the pre-0049 A/B is done
> (`docs/pruebas.jsonl` T193), and it makes both of T192's open questions MORE puzzling, not
> less. Read T193 before anything else; it supersedes the "next step" in the block below.
>
> **The SLAM pose-rate collapse (T192's scarier finding) did NOT reproduce without 0049.**
> Ran the pre-0049 binary (`e26ac16b3`, still built at `/tmp/monado-pre0049` if it survived
> reboot) through the identical recipe, took three attempts to get a clean comparison (see
> "what went wrong getting here" below), but the valid run went **45m47s — longer than the
> 0049 arm's ~39min, including real driving, and racking up 893706 companion_errors (~2x
> T188's own peak)** — and its `tracking.csv` **never once showed a gap over 300ms**. The
> 0049 arm collapsed hard and permanently at 6m55s. This directly contradicts the read-loop
> explanation floated in T192 (which argued the loop runs a healthy ~100Hz so 0049 "can't"
> be responsible) — the empirical A/B now says the opposite: something links the collapse
> to 0049 specifically, or to that one original session's own particular conditions, not to
> a universal SLAM-under-load phenomenon. **Next step: repeat the 0049 arm FRESH under
> today's now-proven-clean conditions** (both controllers registered before launch, no
> Xbox 360 gamepad, quiet storm window) to see if the collapse reproduces a SECOND time —
> that's what actually settles whether it's 0049-linked or a one-off.
>
> **The CPU-runaway question (0049's original target) is still fully open.** T188's own
> signature — continuous climb to 400-432%, needing a SIGTERM — has now failed to reproduce
> in THREE separate single-clean-launch sessions tonight, on BOTH binaries. Real evidence
> that T188's runaway depended on its own two-phase launch pattern (start without
> constellation, let it run, kill, relaunch WITH constellation) rather than simply on the
> missing backoff. **A single clean launch is not the right experiment to isolate 0049's
> effect on this** — next time, deliberately reproduce T188's exact two-phase pattern on
> both binaries.
>
> **What went wrong getting to a valid A/B, worth internalizing**: attempt 1 ran 16+ min on
> a completely invalid setup — controllers never registered (`left:|right:` grep showed
> `None` the whole time, zero constellation blob-matching in the log) — HALF the CPU cost
> of a real run, caught only by checking the log instead of trusting a clean-looking
> CPU/SLAM trend. **Always grep for controller registration before trusting any run of this
> kind.** Getting a working attempt 3 also fought an unusually dense USB2-storm window
> across ~6 wasted restart cycles (hammering restarts didn't help, reconfirming T183's
> standing lesson) — a single 220V mains power-cycle cleared it immediately.
>
> **Also reconfirmed live, unrelated to 0049**: patch 0023's known divergence-then-silent-
> reset (T162) fired again — SLAM position ran from 0.24m to 31.26m over ~120 samples, then
> snapped back to 0.024m, textbook `implied speed > 10 m/s` auto-reset, felt by the user as
> the in-game view suddenly "flying off" and first mistaken for a possible new bug. Still
> not fixed (the real fix — carrying the reset offset into the output pose — was never
> implemented); not touched tonight.
>
> **State**: 0049 binary restored and confirmed via md5 in `~/vr/monado/build`; the
> pre-0049 comparison binary lives in a separate worktree at `/tmp/monado-pre0049` (rebuild
> from `657bcd8af^` if it's gone — `/tmp` doesn't survive a reboot). The Jan Schmidt MR
> !2967 reply is still pending — now for a stronger reason than before: post it once the
> collapse question is actually resolved, not just the runaway one.

> ## START HERE NEXT SESSION (2026-08-16, ~19:21, lab machine) — 0049 is VERIFIED (the CPU
> spin is fixed), but the same session caught a separate, more serious, unexplained SLAM
> pose-rate collapse that shows up almost immediately and never self-recovers. Read
> `docs/pruebas.jsonl` T192 before anything else.
>
> **0049 (patches/monado/0049, T191's fix) does exactly what it was written to do.**
> Rebuilt `~/vr/monado` first (T191's "compile-check" was never a real `ninja` build — the
> on-disk binary predated the 0049 commit by ~30h, caught before touching hardware). A
> single clean launch (`jack-in-wayland.sh 1 6dof`, `WMR_CONSTELLATION_CONTROLLERS=1` from
> the start, no mid-session relaunch unlike T188) plus Aircar ran continuously for **39+
> minutes — more than 2x T188's session length — without a single SIGTERM needed.** The
> backoff was confirmed actually engaging live (WMR_WARN escalates at exactly 1, 1000,
> 2000... consecutive failures, as coded) and self-capped the companion-error rate at a
> live-measured ~100-105 lines/s, matching the 10ms sleep's ~100Hz theoretical ceiling.
> `monado-service` CPU peaked at 551% in the first 90s and then **trended steadily
> downward** the entire rest of the session (551%→...→392% at 39min) — the opposite of
> T188's continuous climb to 472175 errors / 400-432% pinned. USB2 branch (companion+audio)
> kept flapping at the same universal rate as T183/T188/T189/T190; USB3 never moved.
>
> **The user's own methodological pushback was correct and is not yet closed**: T192 vs
> T188 is a cross-session comparison (different day-part, different launch sequence — T188
> had a mid-session kill+relaunch, T192 didn't), not a controlled same-day A/B. A pre-0049
> binary (commit `e26ac16b3`, `657bcd8af^`) is already built in an isolated worktree at
> `/tmp/monado-pre0049/build/.../monado-service` (that path is in `/tmp`, not the repo —
> rebuild from `657bcd8af^` again if it's gone). **Next step: run the exact same
> single-clean-launch sequence with that binary** to confirm the runaway genuinely doesn't
> happen without 0049 either — right now that's assumed, not proven.
>
> **Bigger and unplanned: a SLAM pose-rate collapse, unrelated to 0049, still unexplained.**
> The user reported real head-tracking lag mid-session ("como si se moviera bien, pero
> luego de 1 segundo cuando moví la cabeza"). Measured exactly from the pose CSVs
> (`SLAM_WRITE_CSVS=1` is on by default): pose interval was healthy at ~55-58ms (~17-18Hz,
> matches the documented baseline) for the first **6m55s**, then collapsed abruptly and
> permanently to a suspiciously tight, near-constant **~632-648ms (~1.5-1.6Hz)** — and
> **never recovered for the remaining ~32+ minutes**, including several minutes of the
> headset sitting completely untouched after the user stopped playing. **A live narrative
> earlier in that same session wrongly pinned the onset to a deliberate "fly for real"
> stress test at ~22-23min** — that was an eyeballed guess from a sample-count-bucketed CSV
> summary, a misleading proxy once the tail is dominated by 10x-longer samples. The
> corrected, timestamp-precise onset (6m55s) is well before the stress test and lines up
> with ordinary early Aircar gameplay — meaning this isn't exotic-stress-only, it shows up
> almost immediately. **0049's own code was investigated and ruled out as the direct
> cause**: `control_read_packets()` and `hololens_sensors_read_packets()` (the one that
> actually carries IMU/camera-tunnel data) run strictly sequentially in ONE thread
> (`wmr_run_thread`) sharing `wh->hid_lock`, so the fix's unconditional 10ms sleep on every
> failing companion read was a real suspect for starving that shared loop — but the
> companion-error log-line rate (a direct proxy for the loop's own rate) measured a
> healthy, steady ~100-105Hz with no macro-scale stalling, ruling out the read loop as the
> site of the 632ms stall. The bottleneck is downstream, most likely Basalt/SLAM
> processing or CPU-scheduling contention under the full SLAM+constellation+app
> combination — a mechanism T188 already flagged as live but unproven, now measured with
> hard numbers for the first time but still not root-caused.
>
> **Also separately user-reported, not yet characterized**: a distinct positional "tick" in
> head pose, period a bit under 1 second, persisting regardless of headset
> orientation/movement, and explicitly noted by the user as recurring across multiple past
> sessions — not unique to tonight. Same CSV method should nail this down next.
>
> **Open, in order**: (1) run the pre-0049 binary through the identical sequence to close
> the A/B properly; (2) if the collapse reproduces without 0049 too (expected, given the
> read-loop evidence), profile Basalt's own pipeline (`timing.csv` is already being
> recorded alongside `tracking.csv`) to find which stage backs up at the 6m55s mark; (3)
> characterize the separate sub-1s positional tick; (4) the Jan Schmidt MR !2967 reply is
> **still pending** — 0049's own verification is clean now, but don't let the reply imply
> the headset's tracking is fully healthy, only that the specific CPU-spin 0049 targets is
> fixed.

> ## UPDATE (2026-08-16, ~18:20, everyday system, community/comms session, lab disk mounted) —
> the companion-device backoff fix named as T188's most urgent open item below is now WRITTEN
> and COMPILE-CHECKED, but NOT hardware-verified. `patches/monado/0049`, `docs/pruebas.jsonl`
> T191. Committed `657bcd8af` on `lab-full` in both the lab disk's `~/vr/monado` and the
> everyday system's own clone. **First real step for whoever is next on the lab machine**:
> reproduce T188's load (SLAM + constellation + a real app running for ~15+ min) and confirm
> `companion_errors`/CPU% stay bounded instead of climbing forever. A reply to Jan Schmidt on
> MR !2967 citing this is drafted but not posted (gitlab.freedesktop.org's web UI was 504ing
> when this was written) — post it once hardware-verified, or sooner if asked.

> ## START HERE NEXT SESSION (2026-08-16, ~05:16) — the identity/provisioning hypothesis is
> dead (good news), and in its place a live-caught, fully-characterized CPU-spin bug that's
> worse than anyone knew. Read `docs/pruebas.jsonl` T185-T190 and `docs/31`'s "Live capture"
> section before anything else tonight — the ~01:32 header below is superseded on the
> port/identity question, though its orientation A/B findings still stand.
>
> **The Windows-side detour that started this (unlock_wmr.exe failing, then working after a
> reseat) resolved cleanly, and it's a real, useful negative result**: a live registry read
> (`chntpw`'s `reged`, plus `Get-PnpDevice`/`Get-PnpDeviceProperty` in PowerShell — no admin
> needed) confirmed every device behind the active cable's hub shares one `ContainerID`,
> `{ee4482ce-afe7-5844-820a-73f26905a52f}`, derived from the hub chip's own hardware serial —
> stable, not port-derived. A controlled port-swap A/B (T185) then proved it: moving to a
> different port left `InstanceId`/`ContainerId` byte-identical but flipped the companion
> device's `Status` to `Unknown` (a ghost/non-present signature) — **Windows' identity
> tracking is fine; the USB2/companion branch just didn't enumerate on that port.** A
> follow-up 6/6 test (T186) found **PC-end USB-C disconnect/reconnect — not a visor-end
> reseat — reliably restores the branch**, sharply contrasting with T184's 0/3 for visor-end
> reseats in the same conditions. A real Windows gameplay session on the recovered state ran
> clean (T187). **A checkable "known-good fingerprint" (ContainerID, InstanceIds, firmware
> versions) is now in `docs/22`** so a future session can verify against data instead of a
> feeling. **Scope, stated plainly so it doesn't get overclaimed**: this explains *that
> specific* 422 and rules out identity as the mechanism — it does NOT mean 422 is always
> hardware, and it says nothing about error 108, a separately-documented, different bug.
>
> **Then, stress-testing the recovered state with real gameplay (Aircar, `docs/pruebas.jsonl`
> T188), the project caught — live, for the first time, with full timestamped data instead
> of a postmortem log — the companion-storm/CPU-spin bug T183 had flagged as unfixed.**
> `companion_errors` climbed continuously for the entire ~17-minute session to a peak of
> **472175 — more than 3x T183's worst case**, with `monado-service` pinned at **411-432%
> CPU** the whole time (one thread at 99%+), a nested ~4.5-minute controller IMU freeze, and
> USB branch drops that got MORE frequent and severe over time (70 transitions logged, the
> last six in the final 90 seconds) rather than settling. **Three independent physical
> symptoms corroborated it in real time, unprompted**: audio silently jumped from the
> headset to PC speakers (PipeWire sink recreation, T052-T057's mechanism), head-tracking
> drift got noticeably worse at the same moment (plausible CPU-contention bridge to Basalt,
> not proven), and the CPU cooler was heard audibly ramping up and then quieting the instant
> `monado-service` was stopped. **It never once trended toward recovering on its own** —
> closing the game, twice, through two different mechanisms, had zero effect, because the
> spin lives entirely inside `monado-service`'s own `control_read_packets` loop, independent
> of any connected client. Only a direct `SIGTERM` to the service stopped it.
>
> **A same-night follow-up isolation matrix (T189-T190) split this into two separate
> phenomena, which is the most useful thing to carry forward**: the companion storm itself is
> **universal** — it reproduces at the same rate (~200-450 errors/s) in complete idle with
> zero tracking load, zero app, headset untouched (retroactively explains why T052-T057 caught
> the exact same signature weeks ago with nothing running at all). But the **400%+ CPU pin is
> NOT explained by SLAM or constellation alone** — SLAM-only idles at ~227% (matches Basalt's
> already-known ~1-core cost, T163), constellation-only at ~21%, neither climbing over 1-2
> minutes, and simple addition of the two still falls short of T188's peak. **The extreme CPU
> cost needs the full combination — SLAM + constellation + a real running app — not any single
> piece.** Practical, cheap mitigation logged from this: leaving constellation off for titles
> that don't need hand-tracked visuals (most of `docs/23`'s catalog) measurably reduces the
> worst-case CPU-spin risk, even though it does nothing for the underlying storm.
>
> **Not fixed — this is now the single most important open item in the whole project**:
> `control_read_packets` (`wmr_hmd.c`) still has no backoff on repeated companion read
> failures. T183 found it; tonight measured its real severity ceiling (past the point that
> caused a full panel lockup before) and confirmed it's completely independent of the
> client/game layer. It needs an actual code fix, not another workaround — this is more
> urgent than any tracking-quality work right now, because an unattended long session can
> apparently degrade indefinitely with nothing to stop it.
>
> **Open threads, sharpened not closed**: whether a LONGER isolated SLAM-only or
> constellation-only session (matching T188's 17 minutes, not T189/T190's 1-2) eventually also
> climbs toward the CPU pin, or whether the three-way combination is genuinely required
> regardless of duration; whether this same storm/spin pattern happens on Windows under
> sustained real load, never tested (only a short, apparently-clean AirCar session, T187);
> whether PC-end reconnect (T186's 6/6 lever) also rescues a bad orientation or a bad port, only
> tested from an already-good starting condition; controller/headset auto-standby timing on
> Windows, measured on Linux only (T181, ~15 min, and confirmed almost certainly deliberate
> power-saving rather than a defect — see `docs/03`, though the exact protocol was never
> captured); whether Oasis's native Windows stack implements HMD worn/presence detection where
> Monado/xrizer does not (`docs/03`'s War Robots VR gap).
>
> **Documentation completeness pass, same night**: archived a detailed Reddit WMR
> offline-preservation guide (`docs/37`) and two retired Microsoft Learn pages (`docs/35`,
> `docs/36`) before they can disappear; read `HololensSensorsWinUsb.inf` and found a third USB
> interface (`MI_03`, raw WinUSB, no kernel driver — likely Microsoft's own raw camera/sensor
> data path) neither this project nor Monado has ever used, documented in `docs/12`. A
> registry-inspection recipe (mount + `chntpw`) and the PowerShell `ContainerID` check are now
> written up as reusable procedures in `docs/26`, not just narrated inside `docs/31`'s
> chronicle.

> ## START HERE NEXT SESSION (2026-08-16, ~01:32) — a real, deterministic USB-C connector fault
> confirmed by a controlled A/B test; port-swapping and visor-reseat both rigorously cleared as
> unreliable; two tracking findings finally seen through clean windows; the "port switch fixed
> it" note below (same night, earlier) is SUPERSEDED — read this one first. `docs/pruebas.jsonl`
> T184.
>
> **THE HEADLINE, and it changes the whole cable narrative**: a tape-marked, cold-reinsert A/B
> test on the USB-C plug (headset's active-cable hub box -> PC) found something 100%
> reproducible, 6/6 trials: **'matched' orientation = 0/5, always. 'unmatched' orientation = at
> least 2/5 (SuperSpeed branch, cameras + controller tunnel), always.** Not spec-compliant
> USB-C behavior, and not flapping noise — a real, controlled, repeatable fault. **Getting from
> that guaranteed 2/5 up to the full 5/5 (the USB2 branch — companion `03f0:0580` + audio
> `0bda:4c15` — joining) has NO confirmed reliable trigger**: tested rigorously across 4
> different PC ports and 3 separate visor-end reseats, all while holding orientation fixed at
> 'unmatched' — visor reseat never once produced a 2/5->5/5 transition (0/3), and the one port
> change that looked like a fix was debunked on exact timestamps (the climb to 5/5 started
> *before* the port change finished). **Don't spend time port-hopping or visor-reseating
> looking for the USB2 fix — the data says neither works reliably.** `power-on.py`'s dead-panel
> (0/5) guidance now tells the user to flip the USB-C plug, citing this test; deliberately no
> guidance was added for 2/5->5/5, because there's honestly nothing to recommend yet.
>
> **New working hypothesis, the user's own idea and well-grounded, not speculation**: this is
> an ACTIVE cable (already documented: a DP-repeater box) with real USB hub silicon in it
> (Cypress `04b4:6506`/`04b4:6504` seen in `lsusb` all night) — a firmware/state-machine glitch
> in that chip fits the evidence far better than mechanical wear. The user has never felt it
> loose, has pulled on it hard with no effect, and gets rock-solid multi-hour sessions on
> Windows once one is up — inconsistent with ongoing marginal contact, consistent with active
> silicon that occasionally needs *something* to clear a stuck state and doesn't always clear
> even then. **The next real lever to find is what resets the hub chip's firmware, not another
> reseat ritual.**
>
> **Two tracking findings got their first clean look all project, once the storm dropped out
> for extended windows**: (1) the rotation-speed hypothesis ("gira lento, salta menos") held up
> live in SUPERHOT with real hardware noise mostly gone — slow rotation tracks, fast rotation
> "dispara para cualquier lado ... como si le faltara cuadros para dibujar en el medio", which
> matches the already-documented ~4 solves/s per controller against 30Hz cameras. Not yet
> quantified with clean offline data (the in-storm rotexp capture from earlier the same night
> stays inconclusive). (2) **`WMR_CONTROLLER_WMR_AXES=1` (T181's Rx180 bridge) was tried live
> TWICE more, once in a genuinely clean window (0 companion errors at launch) — rotation was
> STILL wrong both times.** Two independent looks agreeing is a real negative result: lower
> confidence in the Rx180 hypothesis itself, not just in the data quality it was measured on.
> `docs/33`'s calibration session still needs the imu_age_ms-gated redo from T183, but go in
> expecting this flag alone may not be the fix.
>
> **A genuinely new, unstarted problem**: the user reported controller HEIGHT (vertical
> position) is also wrong, independent of the known lateral-jump and rotation bugs — "nunca lo
> contemplamos bien". A fork agent tasked with finding the likely cause (camera extrinsics,
> `XRT_TRACKING_ORIGIN_OFFSET_Y`, constellation-vs-world frame mismatch) **went off-task and
> returned a live storm status update instead of touching the question** — a real agent
> failure, logged, not retried this session. Start here fresh next time; the investigation
> itself was never actually attempted.
>
> **Also confirmed clean**: SUPERHOT VR ships no native recenter (all 11 binding files
> inspected — only shoot/grab/mindwave/menu/ui_navigation). The only recenter live in this
> stack is `patches/xrizer/0001` (hold-menu-3s), and it fired zero times this session — rules
> out an accidental recenter as an explanation for tonight's jumps.
>
> **Tooling/process notes**: `scripts/hw-monitor.sh` (new, committed, synced to `~/vr/`) —
> transition-only background USB/DP/companion-error logger, safe to leave running for hours,
> was the instrument behind everything above. Watch for exactly the mistake made tonight:
> promoting a scratchpad copy to the repo mid-session without killing the old running instance
> split the log across two files for over an hour before anyone noticed — confirm only one
> instance is running before trusting its output. And the Steam-Force-Quit-only closing rule
> (don't use `vr-state.sh --close-title` without asking) lapsed a second time tonight, caught
> by the agent itself; still the standing rule for a fresh session, don't assume standing
> permission carries over.

> ## START HERE NEXT SESSION (2026-08-15, ~23:40) — the USB2 branch is actively, measurably
> degrading again, and this session's own methodology error contaminated part of what it
> found before catching itself. Read `docs/pruebas.jsonl` T182-T183.
>
> **Two things happened today, in order: T182 (morning) fixed a real boot-console hang**
> (`vr-boot-selector.sh`'s `timeout` was missing `--foreground`, so any keystroke during
> `wait_for_reseat` — including the documented `[s]+[Enter]` skip — triggered `SIGTTIN` and
> froze the process for good; fixed, verified end-to-end in a pty harness) **— unrelated to
> everything below, already closed.** Then a controller-calibration session ran this
> afternoon with Codex (`docs/33-controller-calibration-2026-08-15.md`, patch vendored at
> `patches/monado/*controller-calibration-telemetry-and-axis-ab-transforms.patch`) — its
> fitted transforms (`WMR_CONTROLLER_WMR_AXES`, `WMR_CONTROLLER_FULL_CAL_RIGHT/LEFT`) are
> **NOT validated and should not be trusted as clean** — see why below.
>
> **T183 (tonight): what started as "confirm the headset still works" found the USB2
> branch (companion `03f0:0580` + audio `0bda:4c15`, behind hub `04b4:6506`) in an active,
> real storm** — first launch hit 152594 consecutive `os_hid_read=-1` errors, panel stuck on
> backlight-only despite DP lease/EDID/OpenXR all reporting clean success (the project's
> core "verification is physical" rule held exactly). **New, real bug found in the process**:
> `control_read_packets` (`wmr_hmd.c`) has no backoff on repeated companion read failures —
> spins, pinned monado-service at 237% CPU with nothing else running. Not fixed yet, a real
> target for next session regardless of cable health. **New tool**: `scripts/hw-monitor.sh`
> (transition-only background logger, safe to leave running for hours) gave the project's
> first real timestamped answer to "how long do the blips last": USB2 drops to 3/5 (once
> 2/5) for consistently **~3 seconds**, spaced 25-90s apart; **USB3 (cameras/controller
> tunnel) never moved once** across 6+ minutes of monitoring. But companion HID
> read-failures climb ~400-600/s nearly continuously, including during "5/5" stretches
> between blips — **`lsusb` reading 5/5 is not proof the companion channel is healthy**,
> check `hw-monitor.sh`'s snapshot line instead.
>
> **A new, more silent failure class was found on top of the already-known placeholder-position
> one (`docs/33`)**: with `WMR_CONTROLLER_CALIBRATION_LOG=1`, a controller's IMU quaternion
> can go bit-for-bit frozen for 196+ seconds — **including through the user actively waving
> both controllers** — while `ori_tracked=1` keeps reporting it as valid. Nothing in the
> normal pose flags this. Live in-game confirmation: the user's own description in
> SUPERHOT/Propagation ("hand floating, very smooth, no jumps") was the freeze itself, not
> good tracking — direct HID probes (`preflight.sh`, bypassing Monado) confirmed the
> controllers stayed alive and responsive the whole time, so the stall is inside Monado's
> fusion thread, not a dead device. **Any future calibration capture must gate samples on
> `imu_age_ms` freshness, not just the `pos_tracked`/`ori_tracked` flags** — both can be
> true while the data is minutes stale.
>
> **User-driven hardware interventions were NOT monotonic — worth knowing before repeating
> one blind**: a "220V power-cut + USB flip" once made things actively WORSE (`lsusb -t`
> showed the entire USB3 SuperSpeed branch vanish, HoloLens Sensors falling back to 480M on
> the same hub as the companion — never seen before), and an *identical* second attempt
> recovered the correct topology. **The physical visor-end cable reseat was never actually
> tried tonight** — only PC-end power-cycle/flip, with inconsistent results. Given the
> user's own "nunca me pasó que trackee tan mal" (worse than any prior session, in his own
> words), **this may finally be the rev2A replacement cable's moment**, not just another
> reseat — `docs/22`'s "still open, not retired" graduates to "do it" territory.
>
> **This session's own self-caught mistake, worth internalizing so it isn't repeated**:
> `jack-in-wayland.sh`'s 6dof mode defaults `WMR_CONSTELLATION_CONTROLLERS` to **0** unless
> explicitly overridden, and every launch until late in the session omitted that flag —
> meaning controller **position** tracking was never actually active, and every
> "hands frozen at the placeholder position" verdict given to the user before that point
> conflated plain default-off 3DoF behavior with USB-storm damage. `vr-state.sh`'s own
> status line printed `constellation=0` on every single check made the whole time; it took
> the user's live description ("solo sobre su eje") to catch it. **Once corrected
> (`WMR_CONSTELLATION_CONTROLLERS=1`), position jumps genuinely improved** — not from
> anything new tonight, but because the gravity gate (patch 0047,
> `WMR_CONSTELLATION_GRAVITY_GATE_DEG` default 14°) is unconditionally active by default.
> Orientation is still wrong with constellation alone (expected — none of today's axis
> options default to on) and `WMR_CONTROLLER_WMR_AXES=1` tried live did **not** clearly fix
> it (the user read position as worse with it on) — not root-caused, muddied by the
> IMU-freeze pattern recurring throughout. **Redo `docs/33`'s whole calibration exercise
> with constellation explicitly on and `imu_age_ms` gating before trusting any of its
> fitted transforms.**
>
> **Process note for next session**: the user's standing rule is that Steam titles get
> closed by the user's own Force Quit in Steam, not by this agent running `vr-state.sh
> --close-title` — the script itself works cleanly (session begin/end counts always
> matched when used), the rule is about who's driving.

> ## START HERE NEXT SESSION (2026-08-13, ~22:05) — both jitters cracked at the source in one night; two wearer verdicts pending and one precisely-scoped open problem
>
> **HEAD (T180, `patches/basalt/0002`): the delivered pose's 10-25 mm resting wander was a
> 0.8-second-old dead-reckoning anchor** — Basalt's `input_img_queue` (capacity 10,
> blocking push) sat permanently full because the optical flow tops out at ~26 fps against
> the camera's 30. Not CPU (freeing 3 cores changed nothing), not `vio_enforce_realtime`
> (drops downstream of the jam, measured no-op). Queue capped at 2 + drop-oldest: anchor
> age p50 819→**109 ms**, delivered position residual at rest p50 9.8→**0.57 mm**, rotation
> p99 0.146→0.107°. `SLAM_THREADS` 2→4 lifts pose rate 17→26 Hz idle but the launcher
> default stays 2 until measured in-game; with 0002, threads buy rate, not freshness.
> **Pending: the wearer.** Feel check static/moving/in-game, and the threads decision under
> game load. `scripts/head-jitter.py` is the objective half (read its blind-to notes).
>
> **CONTROLLERS (T181, `patches/monado/0047`): the 0046 hypothesis is DEAD — `P_imu_me` is
> NOT the solve↔IMU bridge in any composition; the 105°≈low-mode match was a coincidence.**
> The real bridge was IDENTIFIED by motion (user waved the controllers 90 s; Wahba over
> paired relative rotations, `scripts/constellation-frame-fit.py`): **Rx180 — the WMR y/z
> axes flip `wmr_hmd.c` already corrects — 178.9°/178.8° on left/right**, identical on both
> hands as a convention must be. The gravity gate built on it
> (`WMR_CONSTELLATION_GRAVITY_GATE_DEG`, default 14°; true lobes p90 4.3/6.5° vs flip
> ghosts p50 21/p90 89°) drops wrong-lobe samples before they reach the relation history,
> so the tracker's prior stays on the true lobe. Validated live: every sampled drop a
> 105-128° flip. **The orientation-flip class of hand-jumps (the 0.41-0.44 m
> healthy-metrics one) is dead. What survives, measured: near-pure-yaw mis-assignments** —
> gravity-blind by construction — still bounce position between stable clusters 20-30 cm
> apart (3 on the right hand, all 0.07-0.08 px). Next lever: feed the prior into the
> solver's assignment search or disambiguate pattern phase.
> `scripts/constellation-gate-validate.py` is the before/after instrument. **In-game
> verdict pending: Propagation VR with the wearer** (Aircar can't validate hands).
>
> **Hardware truths that cost time tonight, don't relearn them**: the G2 controllers
> **power OFF after ~15 min motionless** (bit three times; LEDs-off signature = garbage
> near-origin solves at 1.4-1.7 px fitting ambient IR blobs — the gate kills those too);
> **re-attach of an already-registered controller after mid-session power-on WORKS, no
> service restart** (twice observed; T043's no-hot-add is about unregistered devices at
> startup); the USB2 branch flapped 3/5↔5/5 all night with a 55k-line companion
> `os_hid_read -1` storm (docs/22 contact — controller tunnel rides the USB3 HoloLens
> device per docs/03, so tracking survives it, but panel control/audio don't). Constellation
> at good geometry solves at ~140/s and eats CPU (SLAM sank to 9.9 Hz); a solve-budget
> throttle is a named future knob — with basalt 0002 the anchor stays fresh regardless.
> `WMR_LOG=debug` is a firehose (per-blob per-frame); the constellation-vs-IMU telemetry is
> INFO now, with device name and raw quaternions — that log line is what made the offline
> identification possible.
>
> **State**: `~/vr/monado` at 63b5317c8 (=0001-0047), `~/vr/basalt` at 76d71a8 (=0001-0002),
> both binaries current and running. Repo committed at session close (see git log; push not
> done). Earlier-today context (filter reorder, 20 Hz cutoff, pacing, scale 100, docs/32
> discipline) unchanged and still true.

> ## NEW MILESTONE (2026-08-12, ~11:50) — 6DoF SLAM went from "runs away to kilometres" to playable in a real game. Five patches, two measured dead ends, one self-inflicted cost. Read `docs/pruebas.jsonl` T162.
>
> **The headline: 6DoF was never actually working on this project, and nobody knew** —
> T060/T061 (2026-08-07) recorded "SLAM works well here" but measured **only rotation
> jitter**; `pose-measure.py` did not exist until T147. In a 360 photo viewer the sphere is
> at infinity, so a position leaving for kilometres is invisible. Treat that entry as
> never-worked, not a regression. Measured properly on 2026-08-12: motionless headset,
> 25 cm in 2.66 s, **1963 m at 79 s**, exponent t^3.8.
>
> **Root cause: a starved visual front-end.** Everything else was fine and verified, not
> assumed — per-camera images visually perfect (screenshotted straight from the debug GUI
> with `import -window`), camera timing 30.04 Hz with 0.2 ms stdev and zero gaps over
> 385 s, raw IMU `|accel| = 9.8118 ± 0.0124 m/s²`, calibration delivered with no parse
> warnings, and stride/distortion-struct-layout/intrinsics-denormalisation/`rpmax`
> semantics all checked in the source. The instrument that cracked it was
> `SLAM_FEATURES_ENABLE=1` (patch `0019`, one of two telemetry knobs that existed but were
> GUI-only): **Basalt was holding a mean of 0.0-0.9 landmarks per camera.** A healthy VIO
> holds 50-150. **Basalt's default detection settings are also its EuRoC settings**
> (`data/default_config.json` and `data/euroc/euroc_config.json` are byte-for-byte
> identical) — tuned for 752x480 pinhole at 20 Hz, not the G2's 640x480 fisheye at 30 Hz.
> `grid_size 30 / num_points_cell 3 / min_threshold 3` → static drift **0.72 m at 60 s**,
> and worn+walking the position stays bounded and *returns* (0.99 m at 180 s, 0.51 m at
> 220 s). A runaway never comes back. Now the default via `scripts/basalt-g2-config.json`.
> It is a **threshold, not one wrong knob**: alone, each of the three gives 4613 m, 1791 m
> and 865 m at 60 s.
>
> **Two crash/failure bugs found along the way, both fixed**: `t_slam` detected camera
> frames with non-monotonic timestamps, warned, **and pushed them anyway** — Basalt aborts
> the process on those, and it killed `monado-service` three times in one session with
> three unrelated triggers (disk I/O, CPU load, and a `CamerasDmaReset` burst from the
> headset). Patch `0021` drops the whole bundle instead, and measured after the fix, **the
> guard fires ~195 times per session** with backwards jumps of 10-106 ms: the G2's camera
> clock hiccups constantly. Separately `receive_imu_sample` was dropping **~10% of the
> entire IMU stream** (5301 samples in 216 s) as "from the past", where the upstream
> comment expects "one or two" — patch `0022` keeps them.
>
> **In-game (Aircar), user wearing it: works, with real caveats.** A session held 0.8 m for
> 600 s, then jumped 2211 m in one step and **froze on that value for 90 s** — the wearer
> stranded 2.5 km away. Patch `0023` adds a divergence auto-reset (implied speed > 10 m/s).
> **Its cost is self-inflicted and not fixed**: a reset re-anchors at the origin without
> telling the application, so the world anchor teleports. "Estoy lejos de la nave" happened
> with the tracker reporting a healthy 0.19 m. The real fix is to carry the reset offset
> through to the output pose.
>
> **The jitter is ROTATIONAL, and an hour went into measuring the wrong axis.** Position
> steps looked bad (p99 152 mm), so the output stage got blamed twice — one euro filter,
> then gyro-only prediction. User verdicts: "el jittering no cambió casi, la posición más
> bien", then "igual mucho jitter". Measuring **rotation** settled it in one command: raw
> Basalt p99 **12.03°**, max 32.35° (970°/s — impossible for a head) against p99 1.13°
> filtered. So the one euro filter, nearly written off as useless, is the biggest win in
> the output path, and the jitter itself is Basalt's, upstream of everything being tuned.
> `SLAM_FILTER=one_euro` is now the 6dof default.
>
> **Two measured dead ends, both documented in the code so they are not rediscovered:**
> (1) `m_clock_windowed_skew_tracker` — in-tree, used by the Rift driver, documented as
> microsecond-accurate under 10s of ms of jitter — took dropped IMU samples to **zero** and
> made drift **worse**: 243 m and 1002 m on two consecutive runs against 0.7-1.0 m. The
> dropped samples were never what limited accuracy; do not re-apply it on the strength of
> the drop counters. (2) Inverting the camera extrinsics: 0.9 → 2.6 features, nothing.
>
> **Open, and stated as open**: 0.72 m of static drift in 60 s is ordinary VIO drift, not
> zero; denser detection (`detect_plus`) is better on every static metric but drops 4x the
> IMU samples under real game load — CPU ↔ clock ↔ tracking is one feedback loop and past
> this point every lever pushes the problem around it; the user's reported left/CCW roll
> drift **has no number** (the Euler decomposition hit gimbal lock at pitch -88°, and
> measuring roll while the wearer moves is confounded — it needs the headset static on a
> flat surface with the gravity direction tracked); and this morning's boot-time lease
> failure has no confirmed cause (the `chvt` A/B needs a password and was never run).

> ## NEW MILESTONE (2026-08-10, ~01:35) — full unattended boot-to-VR pipeline shipped and verified end-to-end with real hardware; four real bugs found and fixed in one night. Read `docs/pruebas.jsonl` T108-T141.
>
> **The headline result: this machine now boots, diagnoses its own hardware, and lands
> in a real VR session with zero manual steps beyond turning the headset/controllers on
> and picking Auto at a boot prompt** — no forced full-desktop login, no manual script
> invocation. Chain, each link independently verified live tonight: bare-console boot
> selector (tty1, SDDM never even starts if Auto is picked and the "not ready" verdict
> holds) → `power-on.py --pre-login`'s 5-step hardware gate → SDDM **autologin**
> straight into "GNOME on Wayland" (no password prompt in Auto mode anymore — Manual
> mode still shows the normal login) → the visible console auto-switches to tty4
> (`chvt 4`) → a picker of the 12 confirmed-working titles from `docs/23`, filtered live
> against what's actually installed → a real Steam VR session that survives the picker
> process exiting. User-confirmed physically working end to end more than once tonight,
> including after a cold reboot with controllers already on (no manual intervention at
> all): "corrio bien, todo de 10."
>
> **Four real, independent bugs were found and fixed to get there — worth remembering
> as a pattern, not just individually:**
>
> 1. **Controllers used to hard-block the whole pipeline; now only the headset itself
>    can.** A missing/off VR controller used to produce `TE NECESITO` and stop
>    everything. Since this project's own controller **hot-add doesn't exist**
>    (confirmed weeks earlier) and Windows-style hot-plug tolerance is aspirational
>    here, not real — the fix was to stop pretending it's blocking: `power-on.py` now
>    warns and continues, and passes a `controllers_ok` flag through to the tty4 picker
>    so it can fall back to an ordinary desktop (no forced VR menu) instead of forcing a
>    broken session.
> 2. **`jack-in-wayland.sh` needs `XDG_SESSION_TYPE=wayland` explicitly** — a real,
>    non-cosmetic sanity check inside the script that a bare `runuser`/`systemd-run`
>    invocation (no login shell) never provides. Found by reproducing the exact failing
>    invocation with `env -i` instead of guessing from the (StandardOutput=tty-hidden)
>    symptom alone.
> 3. **`runuser` was silently killing Monado/Steam the instant the launcher script that
>    started them exited.** `runuser` wraps its command in a PAM/logind **login session**
>    scope, and systemd/logind explicitly tears that whole scope down — killing every
>    process still in it, `setsid` or not — the moment the tracked leader process exits.
>    Since the launcher is *designed* to exit right after handing off ("lanzado en
>    background, no espera"), this killed the VR session every single time, confirmed by
>    watching `monado-service` log a clean `Server exiting: '0'` at the exact same
>    second `runuser`'s PAM session closed in the journal. Fixed with `systemd-run
>    --scope` instead — a transient scope with no login-session ties, which systemd
>    keeps alive as long as its cgroup isn't empty, not tied to whether the process that
>    created it is still running. A follow-up guess (forcing group membership via
>    `--property=SupplementaryGroups=`) turned out to be invalid syntax for a `--scope`
>    unit ("Unknown assignment") and unnecessary — `systemd-run --scope --uid=<user>`
>    already resolves full supplementary groups correctly on its own, verified directly
>    rather than assumed.
> 4. **A cable reseat mid-session needs a full Monado restart, not just
>    `panel.py activate`.** `panel.py`'s HID panel-activation channel and Monado's DRM
>    lease are two separate things — a physical reseat that happens *while Monado is
>    already running* invalidates its lease without the running compositor ever finding
>    out, so the panel stays dark even though the HID activation itself keeps reporting
>    clean success. Full sequence now documented in `docs/22`'s newest section. **A real
>    self-correction along the way, worth keeping as a pattern**: the first write-up of
>    this assumed a visor-end reseat (this doc's own historically-proven fix); the user
>    later clarified it was actually a PC-end USB reconnect that fixed it that time —
>    corrected in the same doc rather than left wrong, and flagged as a genuinely open
>    anomaly (the measured cable anatomy says DP and USB shouldn't be coupled that way)
>    instead of quietly absorbed as if it were expected.
>
> **Debuggability lesson that paid for itself repeatedly tonight**: `StandardOutput=tty`
> on the tty4 systemd service hid every error from `journalctl`, which slowed down each
> of the fixes above. A permanent `2>>/tmp/vr-launcher-console-debug.log` redirect on the
> launcher's stderr (cheap, harmless, already committed) turned the next bug
> (`Unknown assignment`) into an instant, certain diagnosis instead of another guess.
>
> **Also shipped, lower-stakes**: a Matrix-style cosmetic pass on the boot console
> (`setfont` to a larger bold font, bright-green accents — red/warn colors deliberately
> untouched, cosmetics shouldn't blur a real fail signal); the tty4 picker's game catalog
> expanded from just Aircar to all 12 titles confirmed in `docs/23`, filtered live
> against `appmanifest_<id>.acf` so an uninstalled title can't show up as pickable;
> verbose logging (`XR_LOADER_DEBUG=all`, `PROTON_LOG=1` + extended `WINEDEBUG`,
> `DXVK_LOG_LEVEL`, `VKD3D_DEBUG`) turned on for every Steam/player launch, logs landing
> in `~/vr/logs/` — surveyed first in `docs/27` before enabling anything, per the user's
> own instruction not to disable/change logging sources without checking they're useless
> first. **Confirmed live, in passing, that Aircar specifically needs a real
> Xbox-360-shaped gamepad** (`045e:028e`) for its own input — the VR controllers alone
> aren't enough for that title; hot-plugging the gamepad in mid-session worked fine with
> no restart needed (unlike VR controllers, which still can't hot-add).
>
> **Parked, not started**: whether a bare `mutter --wayland` session (no `gnome-shell`
> UI) could keep the DRM lease while shedding gnome-shell's own weight — mutter itself
> implements the lease protocol, gnome-shell is a UI layer built on top of it as a
> library, not a separate swappable backend, so this is plausible but genuinely
> untested. See the parked idea note; don't touch the now-working GNOME+autologin+tty4
> pipeline while investigating it.

> ## NEW MILESTONE (2026-08-08, ~05:25) — 4 real games confirmed working end-to-end with real 6DoF head tracking; the "cable dying again" panic was a missing file, not hardware; a real xrizer patch shipped. Read `docs/pruebas.jsonl` T068-T081.
>
> **Biggest single finding: the night's recurring "USB2/DP is dying, cable is degrading
> again" panic (multiple points tonight) had a mundane root cause for its WORST instance —
> `jack-in-wayland.sh`'s own panel-activation call was silently failing on every single
> automated run, for possibly the whole night, because `panel.py` was never copied into the
> lab's flat `~/vr/` deployment** (it only ever existed at `scripts/panel.py` in this repo).
> `python3 $PANEL_PY activate` errored with a plain `No such file or directory`, but the
> script piped that to `/dev/null 2>&1`, so it silently no-op'd and the panel was never
> actually told to turn on — the subsequent "DP never came up" was 100% consistent with
> that, zero hardware involved. Confirmed by testing the SAME activation call by hand
> (`/home/iam/Documents/reverb-g2/scripts/panel.py activate`, the correct full path): it
> worked every single time it was tried standalone. Fixed at the source
> (`scripts/jack-in-wayland.sh`, now surfaces `panel.py` failures loudly instead of
> swallowing them — this exact bug class can't hide again) and synced to `~/vr/`; verified
> 6/6 clean automatic starts immediately after. **Before ever suspecting the cable/connector
> again, check that `~/vr/panel.py` actually exists and that `jack-in-wayland.sh`'s own
> stderr isn't hiding a plain file-not-found.**
>
> **A REAL USB2 outage also happened tonight, separately, and is worth its own note**
> (`docs/pruebas.jsonl` T074): after a batch of 10 Steam/Proton game launches plus several
> `monado-service` restarts in quick succession, the companion+hub+audio branch died with
> the classic `error -71`/`Cannot enable. Maybe the USB cable is bad?` signature. Neither a
> PC-end replug, nor a visor-end reseat, nor 3 minutes of passive waiting recovered it —
> only reseating **every** connector together (not DP) did. Correlates with the
> already-documented "repeated service/panel cycling aggravates this" risk factor, not new
> hardware decay. Separately, the right controller stopped responding entirely afterward
> (43 consecutive fw-read timeouts, no race — genuinely no response) and needed a **full
> headset power cycle** (12V brick, ~1 min) plus a genuinely idle 2-minute wait (no more
> service restarts) to clear. Lesson reinforced hard tonight: **repeatedly restarting
> `monado-service` to "just check again" is itself a likely trigger** — when something looks
> broken, let it sit before hammering it with more restarts.
>
> **The `patches/monado/0012` correction from the previous session is now fully closed and
> verified.** Rebuilt `~/vr/monado` completely fresh via `git am` of `patches/monado/0001-
> 0011` only (no `0012`, no hand edits) — confirmed both controllers register 3/3 clean on
> that binary. `0012` is deleted from `patches/monado/`; the eleven-patch series alone is
> sufficient. Real lesson, not just a correction: the actual git history in `~/vr/monado`'s
> working branch had drifted from the tracked patch files (a stale, hand-edited commit with
> a 3s deadline instead of 0003's 10s, and the literal AND/OR bug) — every controller test
> for at least a week, maybe longer, ran against that drifted binary, not the tracked
> series. **Whenever "the tracked patches are fine but the lab keeps showing a bug they
> should have fixed" comes up again, suspect this exact class of drift first**: rebuild
> clean from `patches/` via `git am` before trusting anything the running binary does.
>
> **First real, human-verified, unhurried game sessions this entire project has ever had —
> four of them, back to back, with real 6DoF head tracking (`jack-in-wayland.sh 1 6dof`,
> Basalt SLAM) instead of the 3dof used everywhere before tonight:** International Space
> Station Tour VR, Aliens Attack VR, Cosmic Flow: A Relaxing VR Experience, and VRSailing by
> BeTomorrow. All four: stable, real 3D, functional controller input. **Known, expected, not
> a bug:** controllers appear positionally offset (sometimes several meters) and only rotate
> in place — this project's controller **position** tracking (constellation tracking, using
> the headset's cameras) was deliberately paused pending upstream Monado reviewer feedback
> (`docs/03`), so 6DoF head + 3DoF-only controllers is the correct current state, not a
> regression. **Process lesson, said directly by the user and worth keeping**: an earlier
> automated 10-game sweep this same session (`docs/pruebas.jsonl` T073) auto-closed every
> title after a fixed 30s timer before the user had real time to look — good for log-based
> triage (which titles are even worth a look), **useless as actual verification**, since the
> whole point of this project's core rule is that a human has to see it. When testing
> something a human needs to verify, launch it and wait for their real, unhurried
> confirmation — don't script a timeout around them.
>
> **War Robots VR: The Skirmish is genuinely blocked, and the real cause spans two repos.**
> Shows real 3D, calibrates fine, then immediately after calibration drops to backlight-only
> with an un-skippable "put on your VR helmet" prompt. Root-caused: xrizer implements zero
> HMD presence/worn detection (`ShouldApplicationPause`/`IsInputAvailable` in `system.rs` are
> hardcoded stubs) — but even fixing that alone wouldn't be enough, because Monado's own
> `wmr_hmd.c` already reads the headset's real proximity sensor and never wires it into
> Monado's own generic `XR_EXT_user_presence` support (fully implemented and working for
> other drivers). Needs changes in both `~/vr/monado` and `~/vr/xrizer` — not attempted
> tonight, `patches/xrizer/README.md` has the detail for whoever picks it up.
>
> **A same-night self-correction worth remembering as a pattern, not just a one-off: the
> `IVRCompositor_013` "missing interface shim" diagnosis from earlier tonight (T072) was
> wrong, caught before any code was written against it.** Before touching xrizer's
> compositor dispatch, checked every OpenVR SDK header xrizer vendors (0.9.12 through
> 2.15.6, the complete published history) — Valve's own versioning skips straight from
> `IVRCompositor_012` to `_014`; version 013 **never existed on any real SteamVR release**.
> Poly Runner VR requesting it and failing is near-certainly harmless version-probing, not
> the actual reason its session exits — the real cause is still unknown. Good instinct
> that paid off: check primary sources (the vendored headers, in this case) before writing
> a patch against a claim from an earlier session, even one already logged as a finding.
>
> **The actual xrizer patch effort tonight went to something higher-leverage instead, and
> it's real and working: a global "hold the menu button 3s to recenter" shortcut**
> (`patches/xrizer/0001`), reproducing what real SteamVR's dashboard provides and this
> from-scratch reimplementation otherwise has no way to do at all — every game with SLAM
> origin drift and no in-game recenter option was permanently stuck until this. Two real
> bugs found and fixed via live hardware testing before it worked correctly (not just
> compiled): naively reusing the existing `app_menu` action bound to the wrong physical
> button first, then (once bound correctly) discovering it delivered real menu-press events
> into games and broke their input — fixed with a dedicated, game-invisible action; and
> `reset_tracking_space(Standing)` clobbering height/floor calibration on every recenter —
> fixed with a height-preserving flag, Standing-only. Confirmed live on VRSailing (was ~4m
> off its expected play-space center, now recenters correctly with height intact and normal
> gameplay input unaffected). Lives at `patches/xrizer/0001`, not yet upstreamed.
>
> The whole night's second major thread, independent of the cable saga below: **xrizer**
> (OpenVR reimplemented on OpenXR, bypasses SteamVR's broken `vrmonitor` entirely) went
> from "not tested yet" to a real working session. Full toolchain built from scratch this
> session — Steam, Rust, xrizer itself, Basalt (SLAM, also never actually built here
> before despite docs referencing it), `libopenxr-loader1` installed system-wide. Two real
> environment bugs found and fixed along the way: (1) `nvidia-driver-libs:i386` is the
> correct i386 NVIDIA package for the 595 driver series — `libgl1-nvidia-glvnd-glx:i386`
> is the wrong/old one and conflicts; (2) Proton/Steam titles run inside Valve's sandboxed
> Steam Linux Runtime container, which does NOT expose the Monado IPC socket by default —
> needs `PRESSURE_VESSEL_FILESYSTEMS_RW=/run/user/1000/monado_comp_ipc` in the Steam
> launch options alongside `XR_RUNTIME_JSON`, or every attempt fails with
> `ERROR_RUNTIME_UNAVAILABLE` no matter how many other things get fixed. **A real Monado
> bug was also found and fixed** (not just a workaround): `wmr_hmd.c`'s bounded
> controller-status wait used `&&` where it needed `||`, so the loop always exited the
> instant the FIRST controller (always left) answered, never giving the second one (right)
> a chance — reproduced 9/9 times, now fixed and both controllers register every time
> (`patches/monado/0012`, not yet upstreamed). **What's still open**: SUPERHOT's own
> buttons (grab, menu/quit) don't do anything in-game yet, even with both controllers
> correctly registered in Monado and `hello_xr` confirming clean `oculus/touch_controller`
> bindings for both hands — not root-caused, whether it's Monado-level (raw input not
> reaching the driver) or xrizer-level (input not translated to the game) is the first
> thing to check next session, via `XRT_DEBUG_GUI=1`'s live controller panel. Of the 4
> installed OpenVR titles tried, only SUPERHOT reached a real session — Funhouse, InCell,
> and InMind each fail for their own unrelated reason (Proton/PhysX, an xrizer
> `VR_InitInternal` crash, and an unrelated Mono crash respectively), not a shared bug.
>
> ## RESOLVED (2026-08-07, ~00:20) — it was the VISOR-END CABLE CONNECTOR all along; a reseat fixed everything. Playlist + 90Hz-with-real-content BOTH verified. Read `docs/22`.
>
> **Final resolution, superseding every verdict below in this block:** the whole night's
> "progressive multi-group death" (DP+panel first, USB2 hours later) was ONE marginal
> contact — the detachable connector where the cable enters the visor, behind the magnetic
> face gasket. Reseating it (T039→T041) brought back, at once: the USB2 branch, panel
> power (`panel.py activate` → HP logo), DP hotplug (384-byte EDID, `DP-3` on the x3600),
> the mutter lease, and `4320x2160@90`. The controlled result that proves it: a mains
> power-cut alone (T030) fixed nothing; reseat+power-cut together fixed everything — the
> reseat discriminates. **The cable is fine; no rev2A purchase needed unless it recurs.**
> The two frozen verifications then PASSED immediately (T041, user-verified): the
> 3-video directory playlist chains unattended with wraparound, and real video through
> the full player at 90Hz is clean — T021's flicker is gone; the last 90Hz caveat is
> closed. Full measured anatomy of the link (what powers what, what the box LED does and
> doesn't tell you, why the HP logo is a pure power+HID diagnostic independent of DP) and
> the piece-by-piece diagnostic ladder are in **`docs/22-cable-connector-diagnosis.md`** —
> read that before ever debugging "headset dead" symptoms again. Bonus: the x3600 is now a
> validated second lab machine (lab SSD boots, patched driver loads on its 3060 Ti, GNOME
> Wayland leases, headset lands on `DP-3` there — connector names differ per machine).
> The paragraphs below are kept as the honest record of how two wrong verdicts happened.
>
> **Update, ~1h later: the reseat is a MITIGATION, not a repair — the rev2A replacement
> cable is now a firm buy.** The USB2 branch dropped again ~40 min post-reseat (T044,
> recovered with a PC-end USB replug alone), and repeated panel on/off cycling then drove
> the contact into a third failure mode: companion enumerates but all HID I/O returns -1,
> device number climbing dozens/minute (T043). Triggered by panel-activation power
> transitions. **Until the new cable: minimize service restarts / panel cycling; long
> steady sessions are fine** (T042: 25 min at 90Hz, user verdict "se vio perfecto" — the
> CLAUDE.md 15-minute stability criterion is MET, and with it the "on par with Windows"
> cutoff). Also established (T043): controller **hot-add doesn't exist** — power
> controllers on BEFORE starting the service; the 10-boot controller stress test is
> deferred until the new cable. Details in `docs/22`'s "Recurrence" section.
>
> **Update, next morning (T046-T049) — a "dead power rail" turned out to be an unrun
> diagnostic step, not new hardware failure; the rev2A cable is downgraded again.** A
> session hours later (T046) found the panel totally dark with zero DP hotplug on any
> port, and two visor-end reseats fixed the USB2 branch but never budged the panel —
> escalated at the time to "the rev2A cable is the next real step." The very next
> session (T047-T049), a **completely cold Linux boot with zero reseat performed** (USB
> was already 5/5 on its own) reproduced the identical dark panel — and simply running
> `./scripts/panel.py activate` (step 3 of the `docs/22` ladder, which T046 never re-ran
> after its reseats) brought it up instantly: logo lit, `DP-1` connected with the healthy
> 384-byte EDID, and the full stack then played real playlist content cleanly at
> `4320x2160@90` (user: "si, todo perfecto"). The same morning, Windows independently
> showed the same pattern (T047): HP logo always starts dark at cold boot, stays lit only
> after SteamVR activates the headset once — same behavior, both OSes, no reseat involved
> either time. Current read: **the G2 never raises DP hotplug on its own at cold
> power-on, on any OS — it always needs the WMR activation sequence first, which is
> normal, not a fault.** The rev2A cable is back to "keep in mind if USB2/tracking
> recurrence gets worse," not an active purchase. Doesn't touch the separately-evidenced
> USB2 dropouts (T039/T044) or the tracking-thread freeze (T045). **Always run
> `panel.py activate` and look at the visor before declaring the panel dead** — full
> detail in `docs/22`'s final section.
>
> **Same-day update (T052-T053) — walk the downgrade above back partway: caught the USB2
> branch mid-storm, cycling on its own every ~6-12s with nothing running.** 66
> reconnects of `usb 3-2` (hub/audio/companion) logged in one 60-minute window via
> `journalctl -k`, denser than any single isolated event seen before. The
> panel.py-activate fix is still real and still validated for the cold-boot-dead-panel
> case, but this storm shows the underlying marginal contact is NOT calm — **treat the
> rev2A cable as still-open, not retired.** Side effect while diagnosing: real playback
> audio (never tested before this session) works fine electrically, but a stream can
> silently produce nothing if it starts during one of these disconnected windows —
> `./scripts/hmd-audio.sh` added for fast mute access. Full detail in `docs/pruebas.jsonl`
> T052-T053.
>
> **Goal at the start of this session:** verify the directory-playlist feature for
> `hello_xr` (`HELLO_XR_VIDEO360=<dir>`, from patch `0003-360-viewer-directory-playlists...`,
> already built and merged in `~/vr/OpenXR-SDK-Source` since 2026-08-04) actually plays
> multiple videos in sequence with the headset on — it had never been tested interactively,
> only with photos. Built `scripts/playlist-session.sh` (also copied to `~/vr/`, **not yet
> committed to git**) as a one-shot launcher: brings the stack up, plays a directory, tears
> down cleanly (real `SIGTERM` to `monado-service` so the panel gets a proper HID
> screen-off). Test playlist ready at `~/vr/media/playlist-test/` (3 VR180 clips with clean
> metadata, ~70s total, deliberately avoiding the known `sbs`-without-metadata detection gap
> from `docs/02`).
>
> **Important correction made mid-session, keep it:** the launcher must use
> `jack-in-wayland.sh`, **not** `jack-in.sh`. `jack-in.sh` (X11/Plasma) has never been
> retested at 90Hz since the bpc patch, and its own default mode is still hardcoded to
> `XRT_COMPOSITOR_DESIRED_MODE=2` (60Hz) — a leftover pre-fix workaround, still unfixed.
> `jack-in-wayland.sh` needs the **"GNOME" entry under the Wayland list** at SDDM
> specifically — not Plasma X11, not Plasma Wayland (KWin never offers the lease, confirmed
> live again this session with `check-lease.sh`, 0 connectors under KDE). `hello_xr`/
> `play360.sh` don't care which one brought Monado up, so this is purely a launcher choice.
>
> **Bigger caveat, don't lose it:** the "RESOLVED" 90Hz confirmation right above (T026-T029
> in `docs/pruebas.jsonl`) was done entirely through `hmd-vk`, a raw Vulkan tool that
> bypasses Monado/OpenXR/`hello_xr` completely, with solid test colors — not real content.
> The only time real video went through the actual player (`jack-in-wayland.sh` +
> `play360.sh`, T021) it still flickered, but that predates the reboot+USB-replug that's
> believed to have cleared a stuck backlight state. **Nobody has confirmed real content
> through the full player at 90Hz since the fix** — that's still an open verification, not a
> settled one, whenever the blocker below gets cleared.
>
> **The blocker found while trying to run that test:** `jack-in-wayland.sh` fails every
> time with `Found no connectors available for direct mode` → `XRT_ERROR_VULKAN`.
> Root-caused to `/sys/class/drm/card0-DP-1/status` (the headset's own port) staying
> `disconnected`, `0` EDID bytes — not a compositor/lease-policy issue, GNOME/mutter
> correctly publishes `wp_drm_lease_device_v1`, there's just no electrical hotplug for it to
> offer. **Physically confirmed with the user: HP logo and panel both fully black — not
> even the boot logo**, which is a new/different symptom from the "logo on, panel off" 90Hz
> failure mode `docs/13` already documents. Ruled out so far (`docs/pruebas.jsonl` T030,
> T031): USB is fine both times (enumerates clean, activation report sent successfully), a
> 20s power-cut + replug of the whole cable didn't fix it, a USB-only replug (the T025
> precedent) didn't fix it either, no leftover EDID `config_file` override, correct driver
> (`595.71.05`), no `xorg.conf.d` overrides. Kernel logs zero DP/HPD events for `DP-1` this
> entire boot (inconclusive alone — nvidia-drm may just not log HPD at this verbosity — but
> consistent with everything else).
>
> **Decided next step, in progress as this note is written: a plain PC reboot**, before the
> more invasive test (physically moving the headset's cable to `DP-2`, which means
> relocating a desktop monitor, to discriminate cable/dongle vs. GPU port). **If the reboot
> comes up and this document is being read fresh: check `cat
> /sys/class/drm/card0-DP-1/status` before anything else.** If it says `connected`, the
> reboot fixed it — proceed straight to the playlist test above. If still `disconnected`,
> the cable/port swap is the next thing to try, not more software debugging (that side is
> exhausted, see the ruled-out list above).
>
> **Process note so this doesn't cost time again:** `scripts/check-lease.sh` gives a
> trustworthy "0 connectors" **only** once the panel has already been woken by a prior
> Monado run in the same boot — run cold, right after a session switch, it always reads "0
> connectors" regardless of which compositor, because the connector isn't hotplugged yet.
> Don't treat a cold `check-lease.sh` run as evidence about KWin vs. GNOME by itself.
>
> **Update, same night, after the reboot above: reboot did NOT fix it (T032), and it's now
> narrowed to hardware.** Moved the headset's cable from `DP-1` to `DP-2` (a port proven
> healthy — the monitor that lived there works fine elsewhere) and **the failure followed
> the headset** (T033): still `disconnected`, still no HP logo. This rules out "bad GPU
> port" — it's the headset's own combo cable/dongle, or its DP output stage, not the host.
> Cross-checked on the Windows machine with this exact physical cable (T034): SteamVR fails
> with a generic error 422 (documented as common for G2 + the Oasis driver, not conclusive
> on its own) and the panel doesn't light — **but the HP logo DOES show**, unlike the total
> blackout on Linux. So the cable isn't 100% dead (Windows gets further), which complicates
> a clean "dead cable" verdict. Don't re-run the software-side checks already covered
> above (USB replug ×2, power-cut, reboot, both DP ports, both GNOME/Wayland and Plasma/X11
> — T036 confirmed X11 direct-mode fails identically) — they're exhausted, this is a
> physical-layer question now.
>
> **FINAL STATE OF THE NIGHT (T037-T038) — it's progressive hardware failure in the
> headset/cable/power chain, full stop.** Two corrections that reorder everything above:
> (1) T034's "Windows machine" was the **same physical PC** (5600), same port and cable,
> only the SSD swapped — this project has always been one machine until tonight. (2) The
> headset was then tested on a **genuinely different machine** (x3600, different
> board/GPU), with Windows: **not even the HP logo lights anymore**, SteamVR error 108
> ("headset not detected" — generic display-not-found, don't chase it as software). So
> within a few hours the symptom *progressed*: panel fully working (T026-T029, afternoon) →
> logo-but-no-panel on Windows/5600 (T034, ~01:45) → no logo on any host (T038). A
> monotonic decay independent of host hardware, OS, port, and SSD kills every host-side
> theory including T037's "residual software state" suspicion. What's shared across all
> failing configs: the visor, its cable (an **active** cable — the inline box contains a DP
> repeater; a dying repeater explains USB-still-fine + DP-never-hotplugs + gradual decay),
> and the 12V power brick. The community record matches exactly: early-production G2 cables
> failed en masse (HP shipped a rev2A replacement cable; symptoms = "not detected", USB OK
> but display dead, blinking cable-box LED). **The old "power supply ruled out" note in
> docs/06 no longer holds** — it predates tonight's degradation. Next steps, in cost order,
> agreed direction: (a) reseat the cable at the **visor end** — it detaches behind the
> magnetic face gasket, it is NOT fully integrated; (b) check the 12V brick/barrel
> connection; (c) replacement cable (the classic fix); (d) if a new cable changes nothing,
> it's the visor's display board — service territory. The 90Hz/playlist verification queue
> stays frozen until the headset lights again.
>
> **VERDICT, end of the night (T039-T040): the cable is dying wholesale, conductor group
> by conductor group.** After the visor-end reseat (done, connector inspected, no change),
> the lab SSD was booted on the **second machine ("x3600", Ryzen 5 3600)** — and there the
> **USB2 branch died too**: the SuperSpeed branch (USB3 hub + HoloLens sensors) enumerates
> fine, but the USB2 hub → companion `03f0:0580` + audio fail with the kernel literally
> printing `Cannot enable. Maybe the USB cable is bad?` + `error -71` through ~21 retries
> and automatic port power-cycles. Same signature as the 2026-08-04 port saga in `docs/06`
> — but this time **port-independent**: identical on two different USB controllers on the
> x3600, after the 5600's ports earlier the same night. Sequence of death: DP lanes + panel
> power first (~01:00, with USB still 5/5 and activation delivered — so NOT explained by
> the docs/06 "companion missing → no display" corollary), USB2 pair hours later, USB3
> pairs still alive. Three independent conductor groups failing in sequence across two
> machines and two OSes = the cable, full stop. **Buy: "HP Reverb G2 cable rev 2A"**
> (a.k.a. "OCuLink to USB-C + DisplayPort cable"). The visor itself looks healthy (its
> internal sensors still respond through the same cable). Optional pending test: flex/wiggle
> localization with a live USB monitor to find the break point. **Useful side discovery:**
> the lab SSD boots fine on the x3600 — also an RTX 3060 Ti, patched 595.71.05 loads, GNOME
> Wayland available. A second, validated lab machine for when the new cable arrives.
>
> **Unrelated but costly mistake, same night, keep out of the way next time:** while waiting
> to test the X11 path, the user reported black borders around windows (leftover
> `GLPlatformInterface=egl` from the cursor fix in `docs/20`, compositor not starting). The
> agent tried to fix it live with `kwin_x11 --replace` from its own Bash tool shell — **this
> made it worse**: GLX/EGL fell back to `nouveau` instead of NVIDIA even with the fully
> correct session environment copied from a real `plasmashell` process, and `plasmashell`
> itself segfaulted and crash-looped into Mesa `zink`/`VK_ERROR_DEVICE_LOST`. Full incident,
> what was ruled out, and the requested-but-not-yet-built "survival script" idea (scope
> still undecided, ask the user before building) are in `docs/20-desktop-plasma-crash.md`,
> final section. **Rule going forward: don't run `kwin_x11 --replace` (or any
> compositor-replacing command) from this agent's shell.** Plain X11 apps (e.g. `konsole`)
> launch fine from here — it's specifically compositor/heavy-GL processes that break. A
> plain reboot is what actually recovers the desktop; that's what's happening as this note
> is being written, again.

> ## RESOLVED (2026-08-06, evening) — 90Hz works clean, no AMD or anything else needed
>
> The bpc patch (`patches/nvidia/0004`) was the complete solution. Nobody had gone back to
> test the native EDID modes without override after installing it — testing it
> clean, `2880x1440@90` and `4320x2160@90` come up perfect. This **supersedes item 2 of
> the "in order of weight" list below** (getting an AMD GPU for the lab) — it's no longer
> needed, don't chase it if this document comes up in a new session. Full detail in
> `docs/19-nvidia-bug-5923212-followup.md` and the entire project summary in
> `docs/21-project-retrospective.md`. **Watch out with the NVIDIA PR:** further down this
> document says "the bpc bug is closed and published" — that's about the investigation, NOT
> about the PR. `github.com/NVIDIA/open-gpu-kernel-modules/pull/1275` is still **`open`,
> unmerged** (verified 2026-08-06 via the GitHub API, after someone on LVRA pointed it out —
> the retrospective had this same error, now fixed). Don't assume "merged" without checking
> the API again before saying so anywhere public.
> `docs/11-linux-hmd-landscape.md` and the 90Hz sections of
> `docs/06-known-issues.md` got a correction note added at the top, but
> keep the old analysis as-is — don't take it as current status without reading the note.

> ## STATUS AS OF 2026-08-06 — new bug, distinct from the 90Hz one: the headset can break the desktop
>
> With the headset connected, **KDE Plasma (X11) can become unstable to the point of losing
> the panel/icons**, or the lock screen shows only the clock with no password field.
> Confirmed cause at least once: KDE saved `DP-0` (the headset) as a desktop monitor
> enabled at 90Hz — the same mode with the unstable DP link that `docs/13` already
> documents — and that takes down the entire compositor with it (`QRhiGles2: Context is
> lost` in `plasmashell`/`kwin`). Fix: `kscreen-doctor output.DP-0.disable`. **But the crash
> recurred later with DP-0 already disabled** (on the lock screen), so there may be a second
> problem unrelated to the headset. **Same-night update: `kscreen-doctor disable` doesn't
> actually turn off DP-0 while hot** (neither raw RandR nor NVIDIA's native MetaMode manage
> it while the headset stays connected — all three methods fail, see the doc) — that's
> probably why it "recurred" with DP-0 supposedly off. The workaround that did work was
> moving the windows trapped on DP-0 with a KWin script (D-Bus), not touching the display.
> Full detail, working snippets, and the "what to pick back up" list in
> `docs/20-desktop-plasma-crash.md`. **Before debugging any desktop weirdness with
> the headset connected, run `kscreen-doctor -o` and check whether DP-0 is `enabled`** —
> and if there are windows that don't show up, suspect they landed there before spending
> time on anything else.

> ## STATUS AS OF 2026-08-05 (night) — read this before anything else
>
> The bpc bug is **closed and published**:
>
> - **PR on NVIDIA:** https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275
> - **Forum thread:** post 379240, revision 6, corrected and with all three attachments
> - With the patch, the headset's 33-byte HID status ends up byte-for-byte identical to
>   Windows'
>
> **The full factorial in `docs/16-lab-vblank.md` has already been run** (7 points, EDIDs
> injected via nvkms override): it ruled out vblank (both in lines and in time), refresh
> itself, and bandwidth. The only pattern that survived was "the only pixel clock that ever
> showed an image is the one from the 60Hz mode that already worked" — there's no second
> hidden variable in the EDID. **Don't go back down that road**: the user decided to pivot to
> reporting instead of continuing to generate EDIDs blindly, and that decision still stands.
>
> **The headset's USB/HID channel is also exhausted**, not only at steady state (this
> document already said so early on 2026-08-05) but during the live TRANSITION: a 60↔90
> refresh change was captured without reconnecting the headset (`windows-kit/`, see
> `docs/13-bug-6bpc.md` section "2026-08-05 (night)") and no special command or HID report
> appears at the moment of the change — only the usual `DEVICE_STATUS` updating
> refresh/htotal/vtotal. The NVIDIA panel and Windows Settings are no use either for
> checking DSC: the Reverb G2 doesn't show up there as a selectable display (it's in
> direct/HMD mode).
>
> **Conclusion: there's nothing left to investigate with user-level tools, on either
> OS.** What follows, in order of weight:
>
> 1. The report to NVIDIA (bug 5923212, body ready in `docs/19-nvidia-bug-5923212-followup.md
docs/20-desktop-plasma-crash.md >>> THE CONNECTED HEADSET BREAKS THE KDE DESKTOP <<<`)
>    — the user uploads it himself.
> 2. An AMD GPU might arrive at the lab to repeat the 90Hz test on `amdgpu` — it's the
>    experiment most likely to move the needle (see `docs/11`), it's not a surprise if it
>    shows up.
> 3. Sniffing the DisplayPort AUX channel with a logic analyzer — noted, not attempted,
>    depends on having the hardware (see the checklist at the end of `docs/13`).
>
> `windows-kit/` ended up consolidated as a general-purpose tool (`run-diagnostics.ps1`, a
> single command) — not as a list of pending 90Hz tasks. If something says "still need to
> run one more Windows capture", be skeptical: that channel has already been fully mined.
>
> ### Publication
>
> The repo is going to be published on GitHub (`Wintch/reverb-g2`). There are two blockers,
> see `docs/17-publishing.md`. The lab's SSH key is already generated at
> `~/.ssh/id_ed25519`. This repo's git identity already points to gmail.


You are on a **brand-new, clean** Debian 13 install, on a dedicated SSD, whose sole
purpose is to test whether the HP Reverb G2 can run at **90 Hz** with the patched NVIDIA
595-open driver. This repo is all the accumulated knowledge of the project. Read it before
proposing anything: several things have already been tried and ruled out with measurement.

## The goal, in one line

**Get the headset panel to stop flickering.** The flicker is the strobe of the G2's
low-persistence backlight at 60 Hz, and it's inherent to 60 Hz mode. The only cure is
reaching 90 Hz. This isn't a performance goal: the user explicitly said video fps are
secondary compared to the flicker.

## Where to start

1. `docs/04-lab-90hz.md` — the full lab plan, step by step. This is your script.
2. `scripts/bootstrap-lab.sh` — automates steps 1 through 4 of that document.
3. `docs/06-known-issues.md` — what NOT to chase again.

Actual order:
```bash
./scripts/bootstrap-lab.sh deps
./scripts/bootstrap-lab.sh nvidia      # and REBOOT
./scripts/bootstrap-lab.sh sources
./scripts/bootstrap-lab.sh build
# baseline WITHOUT patches: confirm 90Hz STILL fails (step 3 of chapter 04)
sudo ./scripts/bootstrap-lab.sh patch-nv    # and REBOOT
# and only then, the 90Hz test
```

**Don't skip the baseline without patches.** It's what separates "the 595 driver alone
changed something" from "the patches fixed it", and it's the only way to know what to
report.

### Where things stand (2026-08-05, 09:15) — report published; needs EDITING

The report was published: [thread 379240](https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240)
(no replies yet). External feedback came in with six items; the full triage, with each
one checked against what's already been measured, is in **`docs/15-feedback-triage.md`**.

**Urgent: the published post has an error and needs editing before more people read it.**
It says *"its DisplayID 2.0 extension carries only a Type VII timing block"*. It's
DisplayID **1.2** and the block is Type I. The conclusion doesn't change and the argument
gets **stronger**: `nvt_edid.c:1101` branches by version (`(pExt[1] & 0xF0) == 0x20`), so
the G2 goes through the DisplayID 1.3 parser, which **never writes `digital.bpc`** —
meaning the clamp to 6 bpc is unavoidable for *any* DP sink with DisplayID 1.x that leaves
depth undeclared.

Full corrected body, ready to paste over the original, in **`docs/14`**. Attachments
already assembled in `forum-attachments/` (raw EDID + 8-bpc repro EDID + annotated decode,
the patch, and the `nvidia-bug-report.log.gz`). There's also text ready to open the issue
on `NVIDIA/open-gpu-kernel-modules`.

**From the feedback, what was already closed** (don't redo it):

- *"Apply the Project-VR patches on top of the bpc one and bisect"* — all three are already
  applied (`PATCH[0..2]` in `dkms.conf`) plus `0004`. The current result **is** the full
  stack on GA104. And there's no verified positive case on Ada to port anything from.
- *"It could be the color space"* — the EDID itself rules it out: CTA-861 byte 3 = `0x00`,
  the headset doesn't advertise YCbCr 4:4:4 or 4:2:2. The link is mandatorily RGB in all
  three modes.
- *"Compare the modeline derived from the EDID against the one nvkms programs"* — done by
  hand (`scripts/edid-tool.py decode`): they match exactly in all three modes. There's no
  second root cause there.

**What's still open, in order:** (2) refresh sweep at 61/72/75/80 Hz — the one that
discriminates most, unblocked by going back to X11 with `Option "CustomEDID"`, which had
been dropped for convenience, not for technical reasons; (3) USBPcap capture on Windows of
the 60→90 transition (the Oasis disassembly only bounds what that binary can send, not what
goes over the bus, and the `driver_oasis.dll` Detours are still unexamined); (4) DPCD via RM
control call, expensive and probably redundant.

#### Previously (2026-08-05, 05:15) — the bpc patch half-works, and the software route is exhausted

**Update (01:50): the firmware route is exhausted too.** `NVreg_EnableGpuFirmwareLogs=1`
enabled and tested — the driver explicitly says it's missing `gsp_log_ga10x.bin` to
log the GSP firmware. Downloaded NVIDIA's full official installer (403 MB) to
look for it: **NVIDIA doesn't distribute it there either** — the installer's
`gsp_ga10x.bin` is byte-for-byte identical (same MD5) to the one we already had. The logic
that decides the 90Hz handshake runs in closed firmware with no public version to speak of.
Full detail in `docs/13-bug-6bpc.md`.

With DSC, color space, and the modeline also ruled out already (see below), **what can be
investigated from Linux without NVIDIA's help is exhausted.** The next step is to report,
not keep digging alone.

#### Previously (2026-08-05, 05:15) — the bpc patch half-works

**The bpc bug was real and the patch works exactly as the code predicted: the headset's
byte 18 went from 06 to 08.** But that did NOT fix the 90Hz. Physical verification:

- `4320x2160@90` and `2880x1440@90` (two bandwidths that differ by 2x): BOTH now
  show **white flicker, no color** — before it was a static logo with no activity. Real
  progress, but not the fix.
- `4320x2160@60` (control, with the same patch): still shows normal colors.
- Since both 90Hz modes fail the same way despite having very different bandwidths, **it's
  not a MIPI bandwidth limit**.

**The most important finding: the state the headset now reports is BYTE-IDENTICAL to
Windows'** (the 33 bytes of `DEVICE_STATUS`, including byte 11 which had been pending — it
got fixed by the bpc change alone). Meaning what this measurement channel can tell us is
exhausted: the headset tells the host the same thing it tells Windows, and the visual
result is different. The missing difference isn't visible from this angle — it has to be
looked for in NVIDIA's logs (silent DSC? RGB vs YCbCr color space? fine timing that
htotal/vtotal don't capture?).

Full detail and the concrete next step (run through `collect-nv.sh` with the patch
applied): **`docs/13-bug-6bpc.md`**.

#### Previously (2026-08-04, 20:45)

**The entire second display path was tested — Wayland + DRM lease on GNOME/mutter — and
90Hz fails identically. Eight failures now. The cause can barely be in NVIDIA.**

The lease **works**: Debian 13's mutter 48.7, unpatched, offers the headset's connector
(`connector 130 DP-1 (HPN)`), Monado leases it and takes `4320x2160@90.00`. That rules out
the NVIDIA forum thread about DRM lease: **the culprit for that block was KWin**, which
advertises the device but offers zero connectors. And yet, with the lease granted and the
90 mode taken, the panel is still dead with the HP logo. The 60Hz control over the **same**
path gave a perfect image. Table and logs in `docs/04-lab-90hz.md`, "GNOME/mutter run".

We swapped X11 Direct-Mode for Wayland DRM lease — two mechanisms that share almost no
driver-side code — and the symptom didn't move. Added to the fact that the patched
595-open failed the same as the unpatched one, there's almost nothing left on the
display-path side.

To check the lease without bringing up Monado: `scripts/check-lease.sh`.

**And the two remaining hypotheses got closed, both by evidence:**

- **There's NO missing mode HID command.** The Oasis driver was disassembled (the one that
  drives the G2 at 90Hz on Windows, talking to the headset directly). Its only panel
  command is *Display Enable* — HID Usage Page `0x03`, Usage `0x21` — which is exactly the
  `{0x04,0x01}` Monado already sends. **There's no refresh-rate command.** Method, false
  positives, and firmware strings in `docs/09-oasis-driver-re.md`. `docs/07` is now
  archived: no need to boot Windows.
- **It's NOT DSC.** From the headset's EDID: `2880x1440@90` needs **10.29 Gbps**, less than
  half of the `4320x2160@60` that works perfectly (17.02), against a 25.92 Gbps link. That
  mode can't need compression and it fails the same. Fourth bandwidth theory ruled out by
  measurement.

**The only thing the two failing modes share is 90 Hz.** It's not bandwidth, it's not
compression, it's not a missing command, it's not the display path, it's not head
contention, it's not the power supply or the cable.

**The cheapest discriminating test that has NOT been run:** `2880x1440@90` (mode 0) via
Wayland DRM lease — `./scripts/jack-in-wayland.sh 0`. It's only been tested on X11.

#### Previously (2026-08-04, 19:10): the 595-open patches do NOT fix 90Hz

Reboot done, patched module confirmed in memory, test run with physical verification
across six cases (full table in `docs/04-lab-90hz.md`, "Step 5 executed"). Both 90Hz modes
still leave the panel off with the HP logo, identical to the unpatched baseline. The 60Hz
control was run *after* the failures and gave a perfect image, so the setup was sound and
the result is clean.

A new hypothesis from the user was also tested and **ruled out**: head contention / GPU
clock domains (he'd already had to turn off 60Hz panels to reach 144Hz on X11). Tested with
a single monitor and with **zero** — the headset as the system's only display — and it's
still off. That's not it. To repeat it without losing your display there's
`scripts/solo-hmd-test.sh`, which restores the desktop via a `trap EXIT`.

~~**The live lead now is different**: maybe the headset is never asked to switch to 90Hz
(`wmr_hmd.c:767` sends the same thing at 60 and at 90). The Windows HID capture is still
needed.~~

> **RULED OUT the same day, twice** (see above and `docs/09-oasis-driver-re.md`). Left
> struck through instead of deleted because this paragraph, after going a few hours without
> an update, caused the hypothesis to be resurrected and cited as "the only one that
> explains the results."
> **When closing a lead, update this section in the same commit.**

Pending items that need sudo (RT priority for Monado, zram, audio, basalt deps) are still
not done; none of them blocked the test.

## The single most important rule of the whole project

**Verifying 90 Hz is PHYSICAL. You have to look inside the headset.**

The Vulkan/OpenXR API reports success and a happy 90.0 fps **with the panel completely
black**. The failure is invisible above the driver. Any conclusion based on logs,
on `xrandr`, or on the reported framerate is invalid. Ask the user to put on the
headset and tell you what they see — it's the only instrument that works.

This applies to the whole project, not just 90 Hz: the 360 photo, the video, VR180
stereo, everything was validated with the user watching. If a human hasn't seen it, it
isn't verified.

## Hardware status and what's already ruled out

**The headset works end-to-end on Linux.** Flawless 3DoF tracking, panel at 60 Hz, audio,
and a custom 360/VR180 player that plays 8K stereo at 60 fps. None of that is the
problem.

Things that **have already been investigated and should be left alone** (detail in `docs/06-known-issues.md`):

- **The cable / the USB port.** It was a bad USB-A port, already fixed. If the
  `03f0:0580` companion is missing, check the port, don't debug Monado.
- **The G2's power supply.** Suspected and **ruled out**: the same headset runs
  90 Hz for hours on Windows 11 without a single drop. It's not electrical.
- **The tracking cameras.** Measured: turning them off changes nothing (`WMR_CAMERAS=0`).
- **DisplayPort bandwidth.** Measured: the working 60 Hz mode has a HIGHER pixel
  clock than the failing native 90 Hz mode. It's not bandwidth: it's the refresh rate.
- **The GPU's DP ports.** Cross-tested with a monitor: both healthy.

**What does remain open** (but AFTER the 90 Hz, not now): with the panel on, the headset's
internal USB2 hub resets every so often and takes the companion and audio down with it. It
comes back on its own ~5 s after killing `monado-service`. Current suspect: how Monado's
WMR driver handles keepalive HID reports compared to Windows. It's an annoyance, not a
blocker.

## Concrete traps that will bite you

- **The player shows BLACK if it can't find its default content.** `LoadPhotoTexture()`
  does a `THROW` when the file won't open, and that kills the XR session: the compositor
  keeps presenting black and the rest of the log says "success". The default points to
  `~/Documents/linux_vr_base/photo360/venice_sunset.jpg`, which only exists on the
  main system. Pass `HELLO_XR_PHOTO360=` pointing to something that exists (the lab has a
  test equirect at `~/vr/media/test-equirect.jpg`). Before blaming video mode, check
  Monado's log for `BEGIN_SESSION` **without** an immediate `END_SESSION`.
- **The player exits on its own if you give it `< /dev/null`.** `hello_xr` v3 reads
  transport keys from stdin and treats `EOF` as "end of timed run": launched with stdin
  closed, it dies in under a second, with **exit 0 and not a single error line**. Monado's
  log shows `client_connected`, swapchains created and destroyed, and `client_disconnected`,
  with no `BEGIN_SESSION` from the app at all — it looks like a compositor failure and it
  isn't. Use `sleep N | hello_xr ...`. Note that **monado-service** needs the opposite
  (`XRT_NO_STDIN=1`, otherwise it dies with `epoll_ctl(stdin) failed`): the service gets
  stdin taken away, the player gets it kept alive.
- **For Wayland you need to pick the right session in SDDM:** there are **two** entries
  both just labeled "GNOME", one Wayland and one X11. Pick "GNOME on Wayland". And KWin
  doesn't work for the lease. `scripts/check-lease.sh` verifies it in two seconds before you
  waste time.
- **`jack-in.sh` no longer hardcodes video outputs** (fixed 2026-08-04): it snapshots the
  actual layout with `xrandr` before touching the CRTCs and restores it afterward, cycling
  the rotation and using `kscreen-doctor` on KDE. It doesn't hardcode paths either: it
  detects `~/Documents/linux_vr_base` or `~/vr`, and accepts `VR_BASE=` and `HMD_OUTPUT=`.
- **`play360.sh` had the same hardcoded path** (fixed 2026-08-04): it pointed to
  `~/Documents/linux_vr_base` and in the lab it would die with "hello_xr not built". It now
  autodetects the same way `jack-in.sh` does. If you touch one, sync `scripts/` with the
  copy in `~/vr/`.
- **`XRT_COMPOSITOR_DESIRED_MODE` from the environment**: until 2026-08-04 `jack-in.sh`
  overrode it with 60Hz, so the chapter 04 90Hz test was silently running at 60 and
  reporting success. It now respects the external value — but **always check the log** for
  which mode it picked: `grep "found display mode" ~/vr/jack-in.log`.
- **The user gets annoyed, rightly, when you break his vertical monitor.** It's happened
  several times. Every time Monado takes `DP-0` in direct-mode, the NVIDIA driver
  reprograms the CRTCs and loses the portrait monitor's rotation — and `xrandr` keeps
  *reporting* "right" while the panel shows landscape. The fix that works is cycling the
  rotation (`none` → `right`), and on KDE it's best done with `kscreen-doctor`, not
  `xrandr`.
- **Monado's startup sequence**: the panel only powers on when Monado sends the WMR
  activation, but Monado can only take the display if X isn't using it. That's why
  `jack-in.sh` starts the service, kills it with `kill -9` (a `SIGTERM` would send the
  screen-off and we'd be back at square one), frees `DP-0`, and only then starts it for
  real. `WMR_DISPLAY_INIT_SLEEP_SECONDS=2` is load-bearing: with the default of 4 s the
  panel has already turned off by the time Monado looks for it, and the service hangs
  forever.
- **Delete `/run/user/1000/monado_comp_ipc` before EVERY startup.** `SIGKILL` doesn't clean
  it up.
- **`"found display mode"` in the log does NOT prove the real WMR headset was used**
  (found 2026-08-07, T050). If the `wmr` builder fails to build a head device (e.g. a
  transient `Did not find HoloLens Sensors' companion device`), Monado silently falls back
  to its `legacy` builder's **Simulated HMD** — which still leases the already-hotplugged
  DP connector and still logs `found display mode`, indistinguishable from a real success
  under a naive grep. Always also check for `Using builder wmr` (not `Using builder
  legacy`/`Simulated HMD`) before trusting a session.
- **The right controller can silently lose the startup race and never register — even
  though it's powered on and pairs fine** (found 2026-08-07, T051). Both controllers
  share one HID tunnel through the headset (docs/03) and Monado finalizes its device/role
  list early; if the right controller's config read (`Reading right controller config`)
  finishes after that list is built, it ends up `right: <none>` for the whole session with
  no error logged. Reproduced 9/9 times in a row with both controllers on the entire time —
  this is a left-wins-every-time race, not occasional BT flakiness. Check with
  `grep -E "left:|right:"` in the log; don't trust the physical LED alone. Not fixed yet —
  candidate fix is parallel/round-robin controller reads instead of strictly sequential
  ones in the startup path (`patches/monado`).
- **`jack-in-wayland.sh` now pre-activates the panel and polls sysfs for DP `connected`
  itself before ever starting `monado-service`** (added 2026-08-07, T050), instead of
  relying on Monado's own fixed `WMR_DISPLAY_INIT_SLEEP_SECONDS=2` window — measured
  activate→hotplug latency is NOT fixed (as fast as ~0.5s clean, as slow as ~6s right
  after a prior failed attempt), and 2s wasn't always enough. This is what actually fixed
  the intermittent "Found no connectors available for direct mode" failures that used to
  look like hardware death.
- **The USB Audio sink needs a mute-on-demand plan.** The companion's audio device
  (`0bda:4c15`) becomes the system default output the instant it enumerates, and any
  already-playing stream (e.g. a browser tab) can jump onto it mid-cycle at whatever
  volume it was at — startling right next to your ears. `./scripts/hmd-audio.sh
  {mute|unmute|status|set <pct>}` finds the sink by name via `wpctl` (no ID to
  memorize, survives PipeWire re-numbering the sink on every USB2 re-enumeration) and is
  the fast way to kill it.
- **"No audio" can be the USB2 branch cycling under you, not a real fault — check
  `journalctl -k` for `usb 3-2` disconnects before debugging PipeWire.** (T052-T053,
  corrected: an initial "it was the off-ear speaker position" theory was WRONG and
  retracted — the G2 has no proximity sensor there, only one near the nose bridge for
  wear detection, `WMR_CONTROL_MSG_IPD_VALUE`, unrelated to audio.) Real mechanism,
  caught live: the USB2 branch (hub `04b4:6506` + audio `0bda:4c15` + companion
  `03f0:0580`) can reconnect on its own repeatedly at idle with nothing running — one
  session logged 66 cycles in 60 minutes, including a dense stretch of one every
  ~6-12 seconds with the companion transiently missing from `lsusb`. PipeWire
  creates/destroys the ALSA sink on every cycle, so playback that starts or is already
  running has a real chance of landing in a disconnected window and simply producing
  nothing, with no error anywhere. This is denser than the isolated single-event
  recoveries in T039/T044/T046 — **don't treat the panel.py-activate fix (T048-T050) as
  proof the underlying marginal contact is calm; this storm suggests otherwise, and the
  rev2A cable recommendation should be treated as still-open, not retired.** Not yet
  tested: whether audio glitches mid-playback during a live dropout (vs. just failing to
  start), the mic path, or what makes the storm start/stop.
- **`~/vr/basalt` can look built when it isn't — check for the actual `.so`, not just
  the directory.** Found 2026-08-07 (T060): `cmake --preset library` was silently
  failing on undocumented deps (`libepoxy-dev libyaml-cpp-dev libsqlite3-dev`, on top of
  the already-known `libbz2-dev liblz4-dev libssl-dev`), leaving a `CMakeCache.txt` with
  no `build.ninja` and no `libbasalt.so` — `docs/06`'s Basalt-divergence entry had never
  actually been reproduced in this checkout. Once built clean, SLAM (`WMR_SLAM=1`) works
  well: real 6DoF, no divergence, comparable jitter to 3DoF both at rest and moving
  (T060-T061). **`./scripts/jack-in-wayland.sh [mode] [3dof|6dof]`** now wires this in
  properly (second arg, default `3dof`) instead of hardcoding `WMR_SLAM=0
  WMR_CAMERAS=0` — it checks `~/vr/basalt/build/libbasalt.so` exists before promising
  6dof and sets `VIT_SYSTEM_LIBRARY_PATH` automatically.
- **A game that launches with audio in the headset but a FLAT 2D image is almost certainly
  `openvrpaths.vrpath`'s runtime ORDER, not the headset** (found 2026-08-13, T174).
  OpenVR takes the **first** entry of `"runtime"` in `~/.config/openvr/openvrpaths.vrpath`.
  T170's parked SteamVR-native experiment left `.../steamapps/common/SteamVR` ahead of
  `~/vr/xrizer/target/release`, so every OpenVR title loaded SteamVR's `vrclient`, found no
  session or lease, and silently fell back to flat rendering — `client_connected` stays at
  0 in Monado's log while the game looks alive and even routes audio to the headset.
  Check that file before debugging anything else; xrizer must be first (or alone).
- **`pgrep -f` matches itself** in environments where the shell carries the pattern in its
  cmdline. Use `pgrep -f "monado[-]service"`. A PID that changes on every check is the
  tell. **This bites when killing games too**: `kill $(pgrep -f "Aircar")` from this
  agent's shell killed the shell itself (exit 144, chain aborted) on 2026-08-13 — bracket
  the pattern (`AirCar[-]Win64`) for game processes as well, not just for monado.
- **`pkill` is blocked** in the Claude Code environment (exit 144, aborts the chain).
  Use `kill` on PIDs from `pgrep`.
- **Project-VR's Monado 90Hz patch** (`nominal_frame_interval_ns = 1e9/90`) **is already
  applied** in the lab tree as of 2026-08-04. It was applied *before* the baseline on
  purpose, so the only change between the unpatched measurement and the later one is the
  NVIDIA driver. `bootstrap-lab.sh` doesn't bring it in: if you redo `sources` from
  scratch, grab it from `patches/consolidated/monado/0001-*.patch` in the Project-VR repo
  (applies clean).

## What's in this repo

```
docs/00-hardware-usb.md     USB topology, the SuperSpeed/USB2 split, procedures
docs/01-bringup-monado.md   runtime build and startup
docs/02-player-360.md       the 360/VR180 player (v3): projections, pipeline, measurement
docs/03-controllers.md      controller status (3DoF, upstream driver limitation)
docs/04-lab-90hz.md         >>> YOUR SCRIPT <<<
docs/05-resolve.md          DaVinci Resolve (another rig goal, unrelated to this)
docs/06-known-issues.md     what's ruled out, with evidence
docs/07-windows-hid-capture.md  ARCHIVED: the mode command doesn't exist (see ch. 09)
docs/08-passthrough-limits.md  passthrough idea + limits by brand (not started)
docs/09-oasis-driver-re.md  what Windows sends to the panel, read from the Oasis driver
docs/10-resources.md         source index: HP driver, FCC, chips, installed base
docs/11-linux-hmd-landscape.md  is it just NVIDIA? other headsets, DK2, and where to publish
docs/12-g2-protocol.md     >>> PROTOCOL REFERENCE <<< everything we know about the headset
docs/13-bug-6bpc.md         >>> THE BUG <<< NVIDIA clamps the G2 to 6 bits per color
docs/14-nvidia-report.md    >>> PUBLISHED REPORT <<< + the corrected body ready to edit in
docs/15-feedback-triage.md  external feedback on the report, item by item, with verdict
docs/16-lab-vblank.md       vblank/pixel-clock factorial (conclusion superseded, see its banner)
docs/17-publishing.md       preparing the repo for publication
docs/18-monado-upstreaming.md  upstreaming the Monado WMR patches (4 MRs open)
docs/19-nvidia-bug-5923212-followup.md  >>> THE RESOLUTION <<< how 90Hz actually got fixed
docs/20-desktop-plasma-crash.md  the connected headset vs. the KDE desktop
docs/21-project-retrospective.md  project retrospective
docs/22-cable-connector-diagnosis.md  >>> LINK ANATOMY <<< piece-by-piece diagnosis of cable/connector/power
docs/31-windows-bringup-and-errors.md  >>> WINDOWS MANUAL <<< Oasis on 24H2, and what errors 108/422 mean
forum-attachments/          the thread's attachments, already assembled and ready to upload
windows-kit/                Windows capture package (packaged into windows-kit.7z)
windows-kit/power-on.ps1    Windows bring-up gate: USB census by branch, pairing, Oasis/SteamVR state (see docs/31)
patches/nvidia/             the 3 Project-VR patches for 595-open + OUR 0004 bpc fix (the 90Hz solution)
patches/monado/             7 of our patches (companion, controllers, WMR_CAMERAS)
patches/hello_xr-player/    3 patches: the full 360/VR180 player
scripts/bootstrap-lab.sh    automated lab install
scripts/jack-in.sh          brings up the VR pipeline (ADJUST the video outputs)
scripts/play360.sh          plays 360/VR180/flat content on the headset
scripts/get360.sh           downloads VR video from YouTube (needs the android_vr client)
scripts/solo-hmd-test.sh    test with the headset as the ONLY display (restores via trap EXIT)
scripts/check-lease.sh      does the Wayland compositor offer the headset's connector? (no Monado)
scripts/xref.py             string xrefs in PE binaries, using only binutils
scripts/edid-tool.py        decodes the headset's EDID and generates variants (bpc, checksum)
scripts/jack-in-wayland.sh  brings up the VR pipeline via DRM lease (Wayland; needs GNOME)
scripts/reseat_audio.py     audible bring-up guide: speaks the census while your hands are on the connector
scripts/drmprops.c          reads non-desktop/modes straight from the kernel connector
scripts/capture-hid.sh      captures the companion's HID per mode (usbmon, needs root)
scripts/analyze-hid.py      diffs HID captures: usbmon (Linux) and tshark TSV (Windows)
```

The code trees don't come in the bundle: `bootstrap-lab.sh` clones them from upstream at
the exact SHAs the patches were generated against, and applies the patches. That way the
bundle weighs kilobytes and it's exactly clear what's ours.

## How this user works

- He speaks Spanish. Reply to him in Spanish.
- He's technical and wants the why, not just the what. Measurements matter more to him than
  opinions — if you're going to claim something, measure it.
- **Correct course when the evidence contradicts it.** In this project there have already
  been three conclusions accepted as good that turned out false (the cable, the power
  supply, the "hardware-blocked" audio). Each one cost weeks. If something doesn't add up,
  say so.
- Don't declare anything verified without him having seen it. It's already happened that a
  render was accepted as good that had never actually been looked at.

## If 90 Hz works

Record in `docs/04-lab-90hz.md`: which mode worked (`XRT_COMPOSITOR_DESIRED_MODE`),
stability at 15+ minutes, and re-run the video smoke test from chapter 02 (the
NVDEC/cuvid path should work the same on 595, but it needs to be verified explicitly).

Only then is the final install planned. The cutoff criterion agreed with the
user is **"the headset on par with Windows or better"**.
