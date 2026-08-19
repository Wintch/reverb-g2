# Next step

> ## START HERE (2026-08-19, ~18:20 — end of a five-hour, three-session day: T223, T224, T225)
>
> **The day's one structural fix**: the constellation range check was measured against the
> WORLD ORIGIN instead of the camera, so a drifted SLAM origin silently discarded every correct
> controller solve. Patch **0085**. Worn positional presence went **1.3%/2.0% → ~50-60%**, and
> in the best single window **74.5%** on one hand. `WMR_CONSTELLATION_MAX_RANGE_M=0.5`
> reproduces the old failure on demand — that is the regression test. Full story: `docs/58`.
>
> **Settled, do not re-litigate:**
> - `WMR_CONSTELLATION_TRACKER_GRAVITY_GATE_DEG=30` (14° is a net negative worn). Now the
>   launcher default, along with the rest of the T215 stack — a bare `up 1 6dof` is the good
>   config, and it echoes what it applied.
> - **The yaw prior is the wrong instrument, not a mistuned one.** The lock forms fine under
>   motion (0086); 98.8% of samples sit below 30° and the ghost's own error lives inside that
>   same band. Stop tuning its threshold.
> - **`WMR_CONSTELLATION_SEED_FIRST` is a measured negative** (presence 49/59% → 7/6%): a
>   FAILING seeded attempt strips blob associations the ordinary path needs. Same call is
>   harmless last, harmful first. Stays off.
> - **`XR_EXT_user_presence` is fully validated**, both directions, sensor confirmed binary
>   (1 worn / 0 resting), debounce measured (0087). Unblocks War Robots VR and doff-to-pause.
>
> **The open problem, stated as narrowly as the evidence allows**: the residual is a
> near-pure-yaw ghost of **10-20 cm horizontal**, which is a **1-2 LED slip around a 32-LED
> ring** (~11° spacing). The trusted heading's own noise floor under worn motion is **10-30°**
> — two to three times too coarse to pick the right LED. Seeding narrows the candidate pool;
> it cannot choose within it. **So the next real lever is the heading's noise floor under
> dynamics (gyro-bias-under-motion, the same class as T203's round-map item 2 for the head),
> not the correspondence search's architecture and not another threshold.**
>
> **Two measured facts still unexplained — do not paper over them:**
> 1. **The hands invert.** Two consecutive windows, identical build and config, wearer changing
>    nothing: L 3.6%/R 62.1% then L 74.5%/R 0.0%. A blob-ownership competition was proposed and
>    then **refuted by its own instrument** (0089): ~30 blobs sit unclaimed while neither hand
>    reaches the 4-blob floor, so nobody is starving anybody. The inversion is real and the
>    explanation is not. **Every historical left-vs-right comparison should be re-read with the
>    possibility that the asymmetry is not a property of the hand.**
> 2. **A ~1 cm high-frequency jitter on both hands**, wearer-reported, distinct from the 10-20 cm
>    shifts. That is the re-triangulation breathe, T203's item 6, and it has never been worked.
>
> **Hardware reality check, and it is getting worse**: the USB2 companion branch degrades
> WITHIN a session — a PC-end replug bought >1 h at 14:30 and ~1 min at 15:52. A full 220V cut
> calmed it best (62/min → 1-3/min). Presence rides that channel and freezes when it dies.
> **The rev2A cable is a live purchase candidate again**, and worth pricing before the next
> session rather than mid-session.
>
> **Still unrun, and now cheap to judge because a working baseline exists**: 0083's exposure
> sweep, and docs/59's three fixture protocols (absolute scale — never validated, and one
> reading of 0.556 m where the tape said 0.750 m says it may be wrong; visibility cliff between
> 50 and 75 cm; gain-vs-quality). All three need the fixture, which is cardboard and 15 minutes.
>
> **Instrument to use from now on**: `scripts/constellation-session-report.py` turns a session's
> logs into every number above in one command. It deliberately refuses to interpret zeros — a
> window with sleeping controllers reads identically to a real measurement, and docs/59's
> invalidation rules are the reader's job.

> ## UPDATE (2026-08-19, ~15:40, lab, WORN — T223): the session-killing bug is FOUND, FIXED
> and the numbers are the best this project has recorded. Read T223 + `docs/58` first.
>
> **What was wrong**: `constellation_sample_store`'s 5 m sanity guard compared the sample's
> **WORLD-frame** position — i.e. distance from the SLAM *origin*, which silently includes
> however far the origin has drifted. Measured worn with the wearer seated still: head pose
> 8.4 m from origin, zero divergence resets, so every CORRECT controller solve was also
> >5 m out and was dropped, at `WMR_DEBUG`, invisibly. Patch **0085** splits it: physical
> plausibility is now **camera-relative** and **per-device** (`params.max_camera_range_m`,
> wmr 3 m, rift/pssense unbounded as before), and the world-frame check stays as a pure
> absurdity guard (`WMR_CONSTELLATION_MAX_RANGE_M`, default 1000 m, throttled `WMR_INFO`).
>
> **Worn, 60 s windows, same session** — positional presence L/R:
> baseline **1.3% / 2.0%** → range fix **46.3% / 47.2%** → fix+0084@14° **27.0% / 1.8%** →
> **fix+0084@30° 47.7% / 45.5%** (first time both hands present at once; previous project
> best was 37.2/22.2 on the everyday rig). `WMR_CONSTELLATION_MAX_RANGE_M=0.5` reproduces
> the wearer-visible symptom on demand — use it as the regression test.
>
> **0084's verdict, first real one**: at its suggested **14° it is a net negative** (right
> 47.2→1.8%). Its default was calibrated on a STATIC DESK capture (true lobe p90 4.3-6.5°);
> worn and in motion the gravity estimate is noisier, and 16 of 70 logged rejects sit at
> 15-30°, i.e. true-lobe samples. Real ghosts live at 75-105° and 135-180°. **Use 30°.**
>
> ## THE NAMED NEXT LEVER (with numbers, not adjectives)
> Residual jumps are **79-100% horizontal, p50 0.35 m, both hands** — the near-pure-yaw
> ghost class, which every gravity gate is blind to *by construction*. The layer that
> should catch it, the yaw prior, is **provably inert**: zero rejections all session while
> 3900 solve-yaw corrections ran with errors to 22.8°. Its gate only engages once
> `solve_yaw_locked` forms, and **nothing logs whether that lock ever forms**. So:
> 1. Make the lock state observable (a log line + a counter — cheap, and today it is the
>    blocker on *measuring* anything about the yaw layer).
> 2. Then re-test the yaw prior worn, and only then judge 0076/0077.
>
> ## UPDATE (2026-08-19, ~16:45 — T224 ran the checklist's items 3 and 4; the lever MOVED)
> - **Item 3 is DONE and the answer inverts it.** The yaw lock is **not** the blocker: 0086's
>   first hardware run shows it LOCKED on both hands under motion, worn. T221's chicken-and-egg
>   is dead. With the lock established the 60° prior still rejects zero, because the yaw-error
>   distribution is 8.2% / 62.0% / 27.8% in the 0-10 / 10-20 / 20-30° bands — 98.8% never
>   approaches the gate, and the ghost's own error sits INSIDE that legitimate band.
>   **So the yaw prior is not mistuned, it is the wrong instrument for this class.** Do not
>   spend another session tuning its threshold.
> - **The real next lever is therefore T215's named major surgery**: generate the correspondence
>   assignment FROM the trusted heading, instead of judging blind-search candidates after the
>   fact. Everything cheaper has now been tried and measured.
> - **Also now separated, and it is a different problem**: the wearer reports a **~1 cm
>   high-frequency jitter on both hands** distinct from the 10-20 cm horizontal shifts. That is
>   the re-triangulation "breathe", item 6 of T203's round map, and it needs its own fix.
> - **Item 4 (presence doff) is BLOCKED ON HARDWARE, not on method.** Two attempts, both lost
>   the same way: the companion survives only ~1-3 min per session now, and the proximity
>   message is change-driven, so a dead channel means the doff never arrives. When it dies the
>   state freezes at WORN — safe direction, feature silently off. Retry only on a session that
>   opens with a genuinely calm branch, and take the doff reading FIRST, in the first minute.
> - **Ops**: the cold 220V cut calmed the storm better than the PC-end replug (1-3/min vs a
>   62/min peak). One observation; confirm before making it procedure. And the 6dof launch mode
>   still leaves `WMR_CONSTELLATION_CONTROLLERS` at 0 — it bit again and cost a relaunch.
>   Pass it explicitly, or use `ctrl`.
>
> ## RESUME CHECKLIST (session ended 2026-08-19 ~16:10 with a 220V power-cut of the headset)
> The build tree is CURRENT (`lab-full` = `3854f3ac7`, binary rebuilt after it) and the
> launcher now carries the measured stack by default — a bare `up 1 6dof` is the good config.
> 1. **Cold start, and give the USB2 branch its rest.** The branch degraded within the day
>    (a PC-end replug bought >1 h at 14:30, ~1 min at 15:52). Check the storm rate BEFORE
>    trusting any measurement: `journalctl -k --since "-5 min" | grep -cE "usb 3-.*(new
>    (full|high)-speed|disconnect)"`. A rate above ~10/min means measure nothing yet.
> 2. **Controllers awake BEFORE the service** (`python3 ~/vr/controller-pair-check.py`), and
>    re-check per measurement window, not per session — they auto-slept mid-session and cost
>    a 272 s window whose counters read as a clean zero.
> 3. **First measurement, 5 min, no fixture needed**: the yaw-lock heartbeat (0086, built but
>    never hardware-run). Launch, wear it, and read `grep -E "yaw lock" ~/vr/jack-in-wayland.log`.
>    The question is NOT "does the prior reject" — it is whether the lock is honest, since it
>    is monotonic and never clears once acquired.
> 4. **Finish the presence calibration, 2 min**: `WMR_USER_PRESENCE=1 WMR_LOG=debug`, a client
>    MUST be running (update_inputs is client-driven), don and doff several times. Missing:
>    the DOFF transition, and how long the byte takes to fall. Known: worn=1, resting=0,
>    and it alternates 0,1,0,1 during donning, so a debounce is needed.
> 5. **With the fixture built**: run docs/59's three protocols, batteries in-band per its
>    battery-control section.
>
> ## NEW, from the tape-measure addendum (same session)
> - **Visibility cliff between 50 and 75 cm**: aimed headset, awake controllers, 50 cm gives
>   118 poses/20 s and 75 cm gives ZERO CAMERA SAMPLES (not failed searches). An arm's reach
>   is ~70 cm. Map this properly (60/65/70 cm) — it bounds the usable play volume.
>   **Trap**: "no blobs at all" is indistinguishable from a dead pipeline in every counter;
>   discriminate by bringing the controllers close and watching it recover.
> - **0083 has its first hardware datapoint**: `WMR_CONTROLLER_CAM_GAIN=255` turns that 75 cm
>   zero into 87 poses — gain buys range — but the solves disagree with the tape (left 0.556 m
>   for a measured 0.75 m; right 0.057 m), matching docs/46's over-bright→ghosts correlation.
>   Next: a 150/200/255 sweep **against a fixture**, scored on solve quality, not just count.
> - **Absolute scale of the constellation solve has never been validated.** 1-2 mm
>   repeatability at 50 cm is repeatability, not accuracy; two hand placements both called
>   "50 cm" differed by 26 mm. Needs a fixture holding a controller at exact, repeatable
>   distances. Until then treat every absolute distance this stack reports as unverified.
> - **Height profile is now measured** (1.70 m standing / 1.35 m seated, was 1.76/1.40) —
>   world was anchored ~6 cm high in every session since 2026-08-12.
>
> ## Still queued from T222, untouched today
> **0083's exposure A/B** (`WMR_CONTROLLER_CAM_EXPOSURE_US` 2000-3000 vs the fixed 6000)
> never ran — the session went to the range bug instead. It is still the standing candidate
> for the in-motion collapse, and it is now much cheaper to judge because there is finally a
> working baseline to compare against.
>
> ## Ops rules re-earned today
> - **The USB2 storm escalates within a session**: 6-18 events/min early → 28-62/min two
>   hours later, 796 in 25 min, ending in a total constellation blackout that invalidated a
>   whole control arm. **PC-end USB-C replug cured it instantly (62→3/min)** — T186's lever
>   holds. Four service relaunches preceded the escalation; the documented "repeated cycling
>   aggravates this" risk is a live suspect, so batch measurements per launch.
> - **Controllers auto-sleep mid-session** and cost a 272 s window entirely (all counters
>   zero). The wearer caught it, not the instrumentation. Check liveness per arm, not per
>   session.
> - A measurement window whose controllers were off, or whose headset was on the desk, is
>   **not a control** — say so and re-run it rather than reading zeros as a result.

> ## UPDATE (2026-08-19, ~03:45, lab/dev, autonomous post-close stretch — T222): three
> deliverables built and one root cause nailed, all awaiting their A/B:
> 1. **T221's trigger-blindness fix IMPLEMENTED**: new optional `get_trusted_gravity`
>    tracking-source callback (gated ONLY on IMU flowing — NOT yaw lock; that asymmetry is
>    the whole point) + pre-delivery gravity-coherence check at all three tracker commit
>    sites (`deviceGravityRejected`), so a wrong-lobe candidate becomes an ordinary
>    "not found" and the existing recovery ladder (incl. seeded recovery) actually runs.
>    Opt-in: `WMR_CONSTELLATION_TRACKER_GRAVITY_GATE_DEG=14` (default 0/off; device-side
>    gate stays as last line). Wearer A/B pending — expected effect: yaw locks form under
>    motion because only true-lobe samples feed the correction loop.
> 2. **In-motion collapse experiment ready**: `WMR_CONTROLLER_CAM_EXPOSURE_US` /
>    `WMR_CONTROLLER_CAM_GAIN` knobs (controller frames were FIXED at 6000/100; 6 ms of
>    exposure on a moving hand = smeared LED centroids, the prime suspect for T221's
>    17k-at-rest vs 0-in-motion). A/B: 2000–3000 µs vs default, in-motion acceptance as
>    the metric. Loud override log line proves what actually ran.
> 3. **The silent windowed-fallback ROOT-CAUSED (docs/51 T222 addendum): compositor
>    debug logging is load-bearing timing** — warn = 6/6 real fallbacks (DRM-sysfs ground
>    truth), debug = 4/4 success. docs/43's quiet contract had broken plain `up` launches.
>    Launcher now pins compositor log at debug everywhere. **Named source task: make
>    `comp_window_direct_wayland` wait for the lease-device's initial connector burst
>    properly (wl roundtrip/event wait) instead of racing it** — that's the real fix, and
>    it's upstream-worthy. Also: play360.sh's `timeout 300` was the real player-death
>    cause (use `-t`); `HELLO_XR_DURATION_S` added (patch 0020) for graceful timed runs.
>
> ## PREVIOUS UPDATE (2026-08-19, ~02:30, lab/dev, WORN): the dev re-run below was EXECUTED and
> the answer is architectural — **the seed layer (0077/0082) never fired: 0 attempts all
> night** (full story: T221 + docs/55 dev-rig addendum). Its trigger only sees
> tracker-side "no pose found", but the worn regime is a GHOST FLOOD: the tracker always
> "finds" a wrong-lobe pose, the driver-side gravity gate discards it (93-99.7% of
> candidates), and the tracker never learns it is failing. Plus the lock chicken-and-egg:
> `solve_yaw_locked` (seeding's other gate) only forms at REST. **The next constellation
> lever is therefore: feed the driver-gate rejection signal back to the tracker (or
> evaluate the yaw prior tracker-side, pre-delivery) so rescue triggers on "pose
> delivered but rejected"** — fresh-brains work on the 0074/0076/0077 signal plumbing.
> Also quantified: rest-vs-motion acceptance is 17k+ samples in 15 min stationary vs +0
> in a 4.9-min worn window (right hand) — in-motion correspondence collapse is the real
> enemy; detection and geometry are fine at rest. Battery note: fresh-off-charger NiMH
> reads raw ~204-206 — the >150 band is chemistry-ambiguous (docs/46 addendum), and the
> "hot alkalines" suspicion from earlier in the night is retracted. Ops: the silent
> windowed-compositor fallback hit the Wayland launcher once (docs/51 addendum;
> `XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="HP Inc."` now baked into jack-in-wayland.sh);
> the player's ~300 s deaths were play360.sh's own `timeout` default (use `-t <s>`;
> hello_xr itself never self-limited — patch 0020 adds HELLO_XR_DURATION_S anyway);
> link-health check now runs at every vr-launcher start (network-link-check.py,
> after the LAN's cutover to the Claro CPE — 192.168.100.x, 791 Mbps).
>
> ## PREVIOUS UPDATE (2026-08-19, everyday/comms box): yaw-ghost stack cross-rig A/B DONE — 0074+0076
> validated (left 5x accepted / 3.4x pos_tracked over baseline), and **0077's first hardware
> run found a seed-poisoning runaway, fixed same night as monado patch 0082** (seed positions
> ran 4m→12m off the `last_known_pose` poison loop; hardened config = best measured on that
> rig, L 37.2% / R 22.2% pos_tracked, right hand rescued 28x). Full story: `docs/55`, T220;
> setup/battery criteria that gated it: `docs/56`; Windows floor/height storage closed (no
> old-Windows install needed): `docs/57`. **Dev next**: fetch
> `~/Documents/handoff-20260819-yawghost.bundle` (see `HANDOFF-20260819.md` there, docs/30
> protocol), rebuild, re-run the T215 wearer mini-protocol with
> `SOLVE_YAW_CORRECT=0.05 YAW_PRIOR_DEG=60 SEED_PRIOR=1`. Beware two instrumentation traps
> now fixed in 0080/0081: telemetry lines didn't name the hand, and the get_tracked_pose
> throttle log muted one hand entirely by call parity — any historical parsing of that line
> is suspect. New battery rules: fresh-alkaline raw ceiling is 208 (docs/46 model invalid
> above ~150; battery-check script now shows percent against 208), and over-bright 3.1V
> alkaline LEDs correlate with 97% ghost solves — NiMH's 1.2V flat band is the sweet spot.
>
> # START HERE (2026-08-18) — THE BAR IS NOW COMMERCIAL: this rig is a showcase for a
> VR-solutions business. "Vendemos soluciones VR, es muy importante que el showcase sea
> lo mejor, que impresione." Every workstream below is now judged against that: a demo
> where a controller dies mid-session, parks in the air, or a frame stutters is a lost
> sale, not a bug ticket. THE TARGET IS BETTER THAN WINDOWS, ideal -- explicitly beyond
> the old "on par" cutoff: Windows WMR is deprecated and frozen forever; this stack
> improves weekly and already carries knobs Windows never had. Experimental layers are
> acceptable en route; the wearer experience is the judge. Read `docs/pruebas.jsonl` T196-T211 for how far 2026-08-17's
> marathon moved everything (clock-skew root cause fixed and wearer-verified; both
> hands' rotation dynamics correct; heading anchored to constellation; machine-grade
> turntable calibration bootstrapped; per-cell battery tracking live; per-stage timing
> telemetry first light; memory leak capped; power/pacing curve started).
>
> ## Showcase-grade workstreams, value-ordered
>
> 1. **Session integrity — the joys must be trustworthy for a FULL demo session.**
>    Keepalive v2 (0058) ticks client-independent — VALIDATE the >15-min wake A/B
>    (pending a quiet window). Battery certainty: `docs/46-battery-management.md` has
>    the model; wire a pre-session battery gate + in-session cliff alert (cliff byte
>    ~65-83, unconfirmed) into power-on/vr-state so a demo never starts on dying cells.
>    Position acquisition: MECHANISM FOUND (T213, the WS3 trace capture): ~180° yaw-GHOST
>    correspondence assignments, structurally invisible to the gravity gate (a half-turn
>    about vertical preserves the down vector), left 13× worse than right (more
>    yaw-symmetric LED ring); blobs abundant, 0056 guards never fire — supply exonerated.
>    Fix in flight: `WMR_CONSTELLATION_YAW_PRIOR_DEG` (locked fusion heading as prior at
>    solve acceptance). SEPARATE open mechanism: hands-still/crossed geometry (P3/P4)
>    collapses correspondence to a flat ZERO for both hands despite healthy blobs.
> 2. **CLOSED 2026-08-18 (T210, patch 0071): the left matrix is machine-complete.**
>    The cradle box delivered the second machine axis; Kabsch over 4 correspondences
>    gives a physically-interpretable half-turn about −Y (179.93°), residuals uniform
>    RMS 4.25°, zero hand data. Wearer: "el 8 vuelve", "los ejes están bien" — the
>    constant offset is dead. Residual: left yaw winds slowly under HEAVY handling
>    (~4° full-stream residual integrating); its healer is the solve-yaw anchor, which
>    starves when hands park — workstream 1's position acquisition cures both at once.
>    HMD twin finding REFUTED same night (T212): the T211 "9% mounting leak" did not
>    reproduce in two held-out chair passes (slope <0.3% over 9518° yaw) and t211's own
>    slope was session-unstable — `WMR_HMD_GYRO_MOUNT_FIX` (0072) is shelved default-off
>    as a negative result, NEVER enable it. Worn roll drift (+0.9°/min) reverts to OPEN;
>    leading hypothesis again Basalt gyro-bias-under-dynamics (`gyro_bias_std`, WS5).
>    Fixture catalog: turntable (controllers, constant-rate), cradle box (second axis),
>    **gamer chair (headset weight class — oscillation ONLY, the tether winds)**; the
>    rigid-plane quorum test (headset + both joys on one board, three gyros, one shared
>    motion) is the cross-validation instrument for all of them.
> 3. **Experience polish**: fast-turn correction visibility (spread=60 shipping; the
>    motion-amplified snap component remains), the docs/45 display-artifact protocol
>    (test patterns built, wearer + 240fps phone pending), the 2-3s rare stall class.
>    **Controller stillness settling (wearer-observed 2026-08-18 ~05:30)**: at rest
>    both joys drift slowly on several axes then settle to pixel-perfect once the
>    gyro bias converges — polish lever: stillness-detected aggressive bias update
>    (low gyro variance → fast bias snapshot) so settling takes seconds, not a long
>    window. Positive datapoint: the settled state is pixel-stable — the whole
>    orientation arc (0062+0071+0066/0067) lands rock solid at rest.
> 4. **Performance & cost calibration (the arcade economics)**: pacing is CPU-bound —
>    105W GPU cap plays Aircar as well as 210W (T209); `scripts/power-log.sh` measures
>    real Wh/h; RT-throttle REFUTED by clean A/B (T209 — the 5% match was coincidence);
>    remaining suspect: the affinity split A/B (0058 knobs, untested); per-box
>    power.conf shipping. Wall-wattmeter validation closes system-total.
>    **Strategic direction (user-sparked 2026-08-18 ~05:50): offload vision stages to
>    the half-idle GPU.** The measured irony: GPU sits at ~50% headroom (105W==210W)
>    while pacing is CPU-bound and the CPU drowns (Basalt tracking 28ms×4 threads,
>    constellation blob matching ~140 solves/s pure CPU). Blob detection and optical
>    flow are image processing — the most GPU-friendly work there is. A CUDA path for
>    either attacks WS4 (pacing) and WS3 (solve rate) at once with watts already paid.
>    Major surgery (neither Basalt nor the constellation tracker has a GPU path);
>    scope it before the showcase freeze, don't start it casually.
>    **Tooling queue (2026-08-18, user-prompted)**: (a) synthetic render benchmark —
>    add a tunable GPU-load dial (fragment-heavy shader knob) to hello_xr's test
>    patterns and sweep GPU utilization vs pacing, no Steam needed — answers "how low
>    can the cap go" scientifically; (b) automated benchmark harness — script the
>    3-window discipline over SLAM_THREADS × GPU cap × affinity, one data row per
>    condition; (c) motion-to-photon trace (IMU→pose→render→present timestamps), the
>    showcase headline number; (d) NVIDIA driver landscape review (agent ran
>    2026-08-18 — see its report; upgrade only in a controlled window, never
>    mid-showcase; PR #1275 status is the trigger to watch).
>    **Per-title VR profiles (user-named 2026-08-18)**: titles played with the Xbox
>    gamepad (Aircar-class) should run with `WMR_CONSTELLATION_CONTROLLERS=0` —
>    constellation costs real CPU (~140 solves/s at good geometry, sank SLAM to
>    9.9 Hz in T180; T190 already logged the off-switch as mitigation). The tty4
>    picker knows the title BEFORE monado launches: give each docs/23 row a profile
>    column (constellation, threads, controllers-needed) and pass it to the launcher.
> 5. **Battery lifecycle / recycling**: per-cell roster live (kos/kub/mar/mik/bob/rio);
>    when a cell's runtime falls well below its siblings' across charges, it graduates
>    to RECYCLING (not trash) — the e-waste ethos is a selling point of the showcase
>    itself: recovered hardware, rechargeable fleet, zero toxic waste.
> 6. **Operational robustness**: the USB2-branch storm remains the #1 hardware risk
>    (6 drops on 2026-08-17; PC-end replug 2/2, 220V cycle 2/2 as levers; the mid-game
>    drop even stalled USB3 cameras 14-24s — suspect shared hid_lock, uninvestigated).
>    The launcher now self-defends (builder-wmr enforcement, pgrep -x, retries) but a
>    showcase needs the cable question settled: rev2A replacement or root-cause.

> # PREVIOUS (2026-08-17) — Windows WMR reverse-engineering landed, + a compile/validate plan
>
> The full Windows WMR driver stack was decompiled and cross-referenced against Monado
> (`docs/re-windows/`, start at its `README.md`). It pinpoints concrete fixes for the open
> tracking bugs — the position pops (clock/optical-timesync, `re-windows/02`+`05`), a real
> 3-axis magnetometer decode bug (`re-windows/03`) — and correlates with the **SLAM pose-rate
> collapse (T192–T195)** (a near-constant ~640 ms interval reads like a fixed timeout).
> **`docs/re-windows/WORKPLAN.md`** is the coordinated comms↔dev plan to compile and validate
> them, SLAM collapse first. Raw decompiled code stays off git — comms box only, NDA.

> # PLANNED (2026-08-12, T163) — a real benchmark suite, and a machine that never varies underneath it
>
> Asked for directly by the user this session, after a night where the same title in the same
> configuration measured 3.44% and 7.22% late frames in **back-to-back windows** — a spread
> wide enough that it nearly produced two wrong conclusions in a row (that constellation
> tracking cost performance, and that more Basalt threads helped). Neither survived a third
> window. Everything below exists because single measurements on this rig are not evidence.
>
> **1. Pin the machine before measuring anything.** `scripts/vr-power-setup.sh` (written this
> session) reports and, with `--apply`, removes the variables: CPU governor `powersave` →
> `performance`, amd-pstate EPP `balance_performance` → `performance`, PCIe ASPM `default` →
> `performance`, GPU to its full 250 W, headset USB autosuspend off (already off here, kept
> explicit because a suspended companion looks exactly like the marginal-cable fault in
> `docs/22`). **Not yet applied or measured** — it needs root, and the before/after is itself
> a benchmark to run.
>
> **2. The GPU watts question, as an experiment rather than a setting.** NVIDIA cards can hold
> identical frame timing across a wide power range. `--gpu-limit 80` caps it; re-measure three
> windows; if pacing is unchanged the watts were buying nothing, then try 70%. Card floor here
> is 100 W of a 250 W max, currently sitting at 240 W.
>
> **3. A benchmark suite worth the name, to catch regressions from updates.** The pieces already
> exist and are already stamped with the environment that produced them
> (`~/vr/logs/frame-pacing.jsonl` records kernel, NVIDIA version, monado commit, xrizer build,
> Proton, render scale). What is missing is the discipline around them: a fixed set of titles,
> a fixed warm-up, three windows per point, and both tracking modes — because 6dof and 3dof are
> different machines from the frame budget's point of view (7.2–11.6% vs 2.8% late frames on
> Aircar). `scripts/machine-specs.sh --save` captures the hardware side.
>
> **Why the hardware profile matters beyond this box**: `num-threads=1` sat in
> `jack-in-wayland.sh` as a literal with nothing saying what it depended on. It is the right
> value here and measurably so, but "right on 6 cores / 12 threads" is an unexamined assumption
> on an 8-thread machine, and this rig is meant to run unattended. Derive from the machine or
> at minimum name the dependency.

> # CLARIFICATION (2026-08-12, ~11:50, lab machine) — "6DoF" below means TWO different subsystems, and only one of them was the stale bundle
>
> The update immediately below root-causes "6DoF looked broken on the lab" as a stale
> handoff bundle. That is correct **for 6DoF controller tracking** (the constellation path,
> `patches/monado/0016`/`0017`, `position_tracked=yes` for the controllers). It is **not**
> the explanation for 6DoF *head* tracking, which was measured on the lab machine the same
> morning and has an unrelated root cause:
>
> - The head-SLAM runaway reproduces on the lab's own binary (`lab-90hz-0017`), which never
>   had `g2-constellation-x11kde` checked out — the bundle was fetched into `~/vr/monado`
>   at 08:44 and `HEAD` never moved off `lab-90hz-0017`. Verified in the reflog.
> - Everything `0016`/`0017` fix lives in `receive_ctrl_cam` / the controller-frame exposure
>   path. Neither touches the head SLAM pipeline.
> - The actual cause was Basalt holding 0.0–0.9 landmarks per camera because its default
>   detection settings are its EuRoC settings. Fixed via `scripts/basalt-g2-config.json`
>   plus `patches/monado/0019–0023` and `patches/basalt/0001`. Full chain in
>   `docs/pruebas.jsonl` T162 and the milestone at the top of `CLAUDE.md`.
>
> So both findings stand, they just answer different questions. The controller-side claim
> below is still **not re-verified building on the lab** — that remains its own next step.

> # UPDATE (2026-08-12, everyday system, community/comms session): why 6DoF "didn't work" on the lab found — the handoff bundle was stale, not the code
>
> Checked the actual source of `patches/monado/0016`/`0017` (the everyday system's own
> `monado` checkout, branch `g2-constellation-x11kde`, 28 commits ahead of that checkout's
> `main` with zero drift) against the bundle that was handed off to the lab. **The bundle
> was made 2026-08-11 and never regenerated after the two commits that actually finish
> 6DoF landed the same night** — including `7cb73701b`, the `container_of` fix that makes
> `position_tracked=yes` report correctly for both controllers. A lab build from that stale
> bundle would have the exposure fix but not the fix that makes it actually report as
> tracked, which matches "we saw it, it's not quite there" far better than a real code bug
> would. Regenerated the bundle, overwrote the stale copy in place, left a second copy on
> the lab disk directly, and (via the mounted disk) fetched the branch straight into the
> lab's own `~/vr/monado` checkout as local ref `g2-constellation-x11kde` (tip
> `7cb73701b`) without touching its then-current branch (`lab-90hz-0017`) or working tree.
> Full detail and the general handoff protocol this led to:
> `docs/30-machine-handoff-protocol.md`, and the recovery command in
> `patches/monado/README.md`. **The build itself is still not verified** — `git checkout
> g2-constellation-x11kde` and building it is the concrete next step for whoever picks
> this up on the lab side.

> # UPDATE (2026-08-12, lab machine, long session). Read `docs/pruebas.jsonl` T156-T159.
>
> ## THE HEADLINE: a graphical session that is not the ACTIVE VT loses its `uaccess` ACLs, and the failures are SILENT
>
> **Xwayland spent this entire boot in SOFTWARE rendering** and nothing ever said so out loud.
> Three lines in the journal at 00:30:54:
>
> ```
> wayland-egl: could not open /dev/dri/renderD128 (Permission denied)
> EGL setup failed, disabling glamor
> Failed to initialize glamor, falling back to sw
> ```
>
> The chain: the user was **not in the `render` group** → the only access to the render node
> is logind's `uaccess` ACL, granted to the **active** session of seat0 → at boot the GNOME
> session was on tty3 while the visible VT was tty2 → no ACL → glamor off, permanently, for
> that Xwayland's lifetime.
>
> **It explains everything measured that night**: every Proton VR title at 13-18 fps, Quake II
> RTX at ~15 fps and its **OpenGL mode at 70-90 fps where a 3060 Ti should give thousands**, the
> DXVK submit thread pegged at 85-92% of one core while the GPU idled at 4-45%. That is
> CPU-side compositing, not a GPU limit. And it explains the one result that fit nothing else:
> **`hello_xr` ran perfectly at 90 Hz with 3024×3024 per eye** — because it reaches the headset
> through Monado's direct DRM lease and **never touches Xwayland**. The one path that bypassed
> Xwayland was the one path that was fast.
>
> **Same mechanism as T143** (hidraw's ACL revoked when the session stops being active), on a
> different device node. And the boot pipeline *deliberately* moves the visible VT (`chvt 4`
> for the picker), so this condition is designed into this system, not exotic.
>
> **Fix applied**: `sudo usermod -aG render iam` — group membership does not care which VT is
> active. **CONFIRMED after reboot (T160)**, three ways:
>
> | check | before | after |
> |---|---|---|
> | Xwayland's GL renderer | software (glamor disabled) | **NVIDIA GeForce RTX 3060 Ti** |
> | Quake II RTX, OpenGL mode | 70–90 fps | **1000 fps** |
> | GPU pstate under load | P3, 555 MHz | **P0, 1665 MHz, 68 W** — unforced |
>
> The 1000 is **id Tech 2's own ceiling** (whole-millisecond frame timing), so the real result
> is "the GPU is no longer the limiting factor at all", not "the GPU delivers 1000". And the
> earlier P3 lock now reads as a *symptom* of the GPU being starved of work — which is why
> forcing PowerMizer helped a little and then decayed.
>
> **Standing rule from this**: anything the VR stack needs from a `uaccess`-controlled device
> node must be secured by **group membership**, never left to depend on which console happens
> to be in front of the user. The other nodes the stack touches are worth auditing the same way.
>
> **WITHDRAWN**: T158's leading hypothesis — that the 2026-08-09 kernel 6.12.101 + NVIDIA DKMS
> rebuild caused the collapse — is wrong. It came from timeline elimination and was reasonable
> on what was known, but the evidence above is direct and mechanistic. **The planned A/B reboot
> into 6.12.100 is cancelled.** Also withdrawn: display mode, render scale, PowerMizer, background
> load, verbose logging, Proton version, xrizer, per-title causes. Each was worth measuring; none
> was the cause.
>
> **How it was found**: the user reported Quake II RTX — *native Vulkan, no Proton, no DXVK, no
> VR* — was also slow. The whole investigation until then was scoped to the Proton/VR path and
> could not have found this. One measurement from outside the assumed scope collapsed a night of
> hypotheses.
>
> ## Verified live this session (user wearing the headset)
>
> - **90 Hz, no flicker** on the rebuilt binary — "no parpadea nada, 90hz clavados"
> - **3dof solid**; the **controller axis gizmos seen for the first time** (T148 had them as
>   "built but NOT seen")
> - **Headset audio works, channels correct** (low tone left / high tone right), test material
>   verified by measurement first (−21 dB live channel, −inf silent channel)
> - **Aircar runs here** — 3D + tracking + audio. This **closes the standing plan**: the
>   Aircar/xrizer failure is specific to the everyday/KDE machine, not a general bug. Stop
>   chasing it there.
> - **VR-controller stick drift fixed** with `WMR_STICK_DEADZONE=0.15` — first live hardware
>   validation of patch 0008 for this. *The user diagnosed this, the agent had wrongly blamed
>   the Xbox pad.*
>
> ## Other findings worth their own lines
>
> - **Reconfiguring the monitors silently resets PowerMizer to adaptive** — SM clock fell back
>   to 555 MHz of 2115 with nothing reporting it. Check `clocks.sm` first on any "it used to run
>   better" report. **`nvidia-settings` lies**: after a successful assignment it still queries as
>   `0`, and `nvidia-smi` still shows `P3`, while the clock has plainly doubled. Trust `clocks.sm`.
> - **Monado supersamples 140% by default** (`XRT_COMPOSITOR_SCALE_PERCENTAGE`,
>   `comp_settings.c:34`) — 2160² native becomes 3024² per eye. Driven by the panel, **not** by
>   the display mode, which is why lowering the video mode does not reduce render cost.
> - **Monado has no FOV-crop option.** All 240 `DEBUG_GET_ONCE` options checked: only the two
>   uniform scalers exist. SteamVR's tangent-multiplier peripheral crop has no equivalent. The
>   FOV is assembled at `wmr_hmd.c:2114` — clear place for a patch. Real gap, not filed.
> - **Trap**: `pw-play --target` accepts the target, **exits 0 and routes nowhere** (sink never
>   leaves `SUSPENDED`). `paplay --device=` works. Three silent "successful" playbacks were
>   blamed on hardware before this was found. Confirm the sink state changed; never trust exit 0.
> - **`patches/monado/` cannot build the lab binary** — 0016/0017 do not apply (divergent
>   history, three independent proofs in T157). **Do not hand-apply them**; that is what caused
>   T068. Needs a clean re-export from the checkout where they were written.
> - **The 90 Hz patch was missing from every clean rebuild since 2026-08-08** because it lived
>   only as a README footnote. Now exported as `patches/monado/0018`.
> - **Adapter/Nisuta watch**: four full `monado-service` restart cycles plus several Proton
>   launches — **zero `error -71`, zero USB2 drops**, and `reqCmd 23` exactly once on first
>   start, never again. First restart-heavy session since the swap. Evidence for the fix, not
>   yet enough to close it.

> **UPDATE (2026-08-11, everyday-system session #3): a SECOND already-lab-verified title
> (Aliens Attack VR, 932190) reproduces Aircar's exact non-connection signature on this
> machine -- points toward a general everyday-system/KDE xrizer regression, not an
> Aircar-specific bug. Zero new `client_connected` in Monado's log, zero `xrizer.txt`
> anywhere on disk, panel powered but blank, despite the Proton-side bridge
> (`C:\vrclient\bin\vrclient_x64.dll`) already correctly present from the Aircar bring-up.
> A `PROTON_LOG=1` relaunch to compare traces against Aircar's (T152) is queued but not yet
> actually captured -- the first relaunch attempt silently failed to pick up the env vars
> (confirmed via `/proc/<pid>/environ`), corrected and re-queued. Full detail in
> `docs/pruebas.jsonl` T154.**
>
> **Same session: external research (not project-specific) turned up three open, unresolved
> public bug reports for NVIDIA + Proton + OpenXR** -- none symptom-for-symptom identical to
> ours (all three describe a visible crash/hang; ours is silent with a clean process exit),
> but real precedent that this exact combination is independently fragile, shifting the
> prior toward "this machine's driver/Proton/OpenXR stack", not "our own xrizer patches or
> Monado build". Sources: `ValveSoftware/steam-runtime#782` (pressure-vessel's
> `graphics-drivers-openxr-1.c` silently strips vendor-specific OpenXR runtime json fields,
> reporter's own example shows a Monado-specific field, `MND_libmonado_path`, vanishing --
> though the exact trigger env var isn't one we set), `ValveSoftware/Proton#7228` (stack
> overflow loading `libopenxr_loader.so.1` on NVIDIA 535.113.01, Proton 8.0+), and an NVIDIA
> Developer Forums thread (driver 550.76, one version-family from this rig's own
> 550.163.01 -- "entire graphics stack crashes" on Proton+OpenXR titles, reproduced with
> both SteamVR and Monado, absent on AMD). Concrete next step if this is picked up again:
> inspect the OpenXR runtime json as the process sees it *inside* the pressure-vessel
> sandbox, not just the original file on disk. Full detail in `docs/pruebas.jsonl` T155.
>
> **Standing plan, explicit**: if the pending PROTON_LOG trace for Aliens Attack VR matches
> Aircar's load/unload-then-exit pattern, stop chasing this on the everyday/KDE machine and
> resume validation on the dev/lab machine (GNOME/Wayland/90Hz/patched), where the full
> game sweep is already confirmed working.

> **UPDATE (2026-08-11, everyday-system session #2, final): head-tracking jitter measured
> quantitatively after tonight's work -- real, not fully explained, two probably-separate
> causes not yet isolated from each other.** User noticed noticeable jitter viewing the
> static-image player. `HELLO_XR_POSE_STATS=1` confirmed it: 4-40x the documented baseline
> (docs/22 T045) while ~18 leftover Steam/Proton processes and `WMR_CONSTELLATION_CONTROLLERS`
> were both active. Closing Steam helped (~50%, user's read) but didn't fully fix it.
> Restarting the service WITHOUT constellation tracking, controllers off, user motionless,
> got MOST windows back to the exact documented baseline (max 0.056 deg, byte-identical) --
> but real isolated spikes (up to 2.14 deg) still occurred with nothing touched, cause
> unknown. Separately, the user directly observed a bigger, controller-standby-wake-
> correlated "ajuste" that wasn't isolated with a clean single-variable measurement. Not
> root-caused -- concrete next step and full numbers in `docs/pruebas.jsonl` T153.

> **UPDATE (2026-08-11, everyday-system session #2, continued further): tried to validate
> 6DoF in a real game (Aircar via a freshly-built xrizer) -- xrizer builds and runs on this
> machine for the first time, but Aircar itself stays in flat 2D. Real progress, not a dead
> end: `PROTON_LOG=1` proved the game's own OpenVR init genuinely reaches xrizer's Proton
> bridge (`vrclient_x64.dll` loads/unloads 4 times) before the process exits after ~9s --
> so the launch plumbing (which consumed most of the investigation: Steam's own
> `openvrpaths.vrpath` silently re-adding SteamVR on every startup, a stale per-title
> Proton-prefix cache, `VR_OVERRIDE` getting filtered by pressure-vessel) is not the
> remaining blocker. What's left is inside the actual OpenVR init handshake itself, and
> needs narrower `WINEDEBUG` tracing to isolate -- stopped here by explicit choice in favor
> of validating 6DoF visually via `hello_xr` instead tonight. Full trace and the concrete
> next diagnostic step in `docs/pruebas.jsonl` T152 and the new trap section in
> `docs/23-game-compatibility.md`.

> **UPDATE (2026-08-11, everyday-system session #2, continued): the "device-specific" clock
> bug the previous entry left as the concrete next step is closed. It was never
> device-specific -- it was `container_of` applied to an array element instead of a
> whole-struct field, a real bug in tonight's own `receive_ctrl_cam` fix. 6DoF constellation
> controller tracking is now fully working end to end: `get_tracked_pose` reports
> `position_tracked=yes` for both controllers consistently. New patch `0017`.**
>
> `container_of(sink, struct wmr_source, ctrl_ts_fix_sinks)` only recovers the right `ws`
> pointer when `sink` is the *start* of the named field. `sink` was actually
> `&ws->ctrl_ts_fix_sinks[i]`, the i-th array element -- for `i==0` that coincides with the
> array's own address so it happened to work, for `i>0` it silently read `ws` offset by
> `i*sizeof(xrt_frame_sink)` bytes into the real struct, and (by the same broken math)
> `cam_id = sink - ws->ctrl_ts_fix_sinks` always resolved to exactly `0` regardless of the
> real `i`. A temporary trace confirmed it: 12947/12948 calls to `receive_ctrl_cam` logged
> `cam_id=0`, literally never anything else, across 4 physical cameras. Since the two
> controllers are seen predominantly by different physical cameras, this reliably looked
> like a "works for controller A, not controller B" bug rather than a camera-indexing one --
> which is exactly what got documented (wrongly) as "device-specific" earlier tonight.
>
> Fixed by giving each camera its own `struct wmr_ctrl_ts_fix_sink` (the `xrt_frame_sink` as
> first member, plus explicit `ws`/`downstream` pointers set once at wiring time), so
> `container_of` recovers the correct instance regardless of array index. Verified live
> twice, including a full clean rebuild + relaunch to rule out stale state: `pushPose`'s
> `cam_sample_ts` now lands 5-40ms behind `os_monotonic_get_ns()` for every device/camera
> combination sampled, comfortably inside the 200ms freshness window. Ran `hello_xr` to
> drive real `get_tracked_pose` calls: both controllers report `position_tracked=yes`
> consistently, with distinct stable positions per device, not intermittently and not for
> only one controller. New patch `patches/monado/0017` (this repo's own sequential
> numbering -- unrelated to whatever the actual `g2-constellation-x11kde` branch's commit
> messages informally call their own next unfiled patch; see the sync-gap note below).
>
> **Also found, while investigating**: `jack-in.sh` does not export
> `WMR_CONSTELLATION_CONTROLLERS`, so a bare relaunch silently runs with the whole
> controller-tracking path disabled -- has to be set manually
> (`WMR_CONSTELLATION_CONTROLLERS=1 ./jack-in.sh`) until it's wired into the script itself.
> Cost about 15 minutes of "why is nothing happening" tonight before being caught.
>
> See `docs/pruebas.jsonl` T151 for the full trace and verification numbers.
>
> **Environment this was developed and verified on, stated explicitly so it isn't confused
> with the lab's setup**: everyday system, Debian 13, **KDE Plasma on X11**, NVIDIA
> `550.163.01` proprietary **unpatched**, headset panel at **60 Hz (the official/stock
> rate)**, launched via this machine's own local `jack-in.sh`. The lab machine is a
> *separate* Debian 13 install on the same physical box -- **GNOME on Wayland**, NVIDIA
> `595.71.05` open-modules **patched**, headset panel at **90 Hz**, launched via
> `jack-in-wayland.sh`. These four axes (X11/Wayland, KDE/GNOME, 60/90 Hz,
> unpatched/patched driver) move together as one bundle between the two installs, not
> independently -- everything in this update is confirmed on the 60Hz/X11/KDE/unpatched
> combination only. Plan: run a simple real game here first (still 60Hz/X11), then revalidate
> the whole 0012-0017 series on dev's 90Hz/Wayland/GNOME/patched combination before treating
> either environment as fully proven for the other.

> **UPDATE (2026-08-11, everyday-system session #2): 0015's controller exposure fix is now
> correct and physically verified live -- real LED tracking, real RANSAC-PnP pose solves.
> A separate clock-domain fix for get_tracked_pose is only partially closed, with a new,
> unexplained bug found in the same session. New patch `0016` supersedes `0015`.**
>
> New USB-C-to-USB-A adapter (swapped after the previous session's degrading-link ending)
> held up clean all session: 5/5 USB the whole time, zero `reqCmd 23`, zero USB2 drops --
> not the remaining bottleneck. Bringup itself was flakier than usual (3 of the first 4
> launches failed on the ordinary `vkAcquireXlibDisplayEXT` race or a slow `wake_panel()`
> probe), all recovered with clean stop+retry, unrelated to hardware wear.
>
> **0015, corrected.** The previous entry left `WMR_LOG=trace` as the concrete next step to
> settle whether controller-tagged frames really read exposure=0 -- done: 99.5% of ~2400
> controller frames read exposure=0, 100% of SLAM frames read 450, confirming it's a real
> exposure condition (also ruled out ambient light and controller positioning as confounds).
> Then found 0015's own two wrong guesses, in order: the `camera_id + tcam_count` slot
> mapping sends its exposure/gain command successfully but the frame's own embedded exposure
> readback stays 0 regardless (ruling in "wrong slot", ruling out "frames not arriving" --
> the open question 0015's commit message left). Switched to a flat `+2` (thaytan's original
> constant -- this hardware's real camera location IDs are 0,1,4,5, not contiguous, so `+2`
> and `+tcam_count` land on different slots) and the readback immediately became nonzero and
> linearly controllable (400->20, 6000->300, both exactly /20). Nonzero wasn't enough by
> itself: thaytan's reference exposure/gain (400/1) still produced a black panel on this
> hardware; raised to 6000/100 and got real images. Result, user-confirmed live multiple
> times ("si! los veo!", "veo que trackean!"): `Controller Blob Cam 0/1` went from solid
> black to real LED blobs tracking controller movement, and `CONSTELLATION_TRACKER_LOG=trace`
> showed RANSAC-PnP actually recovering poses continuously (sample #2070,
> pos=(-0.039,-0.012,-0.130), reprojection error 0.04-0.10px, stable across 2000+ samples).
> New patch `patches/monado/0016` supersedes `0015` with both corrections.
>
> **Clock-domain fix, added, only partially closes the loop.** Even with real pose solves
> happening, `get_tracked_pose` still reported `position_tracked=no` with a constant ~44.5
> million ms (~12.4 hour) delta. Root cause: the SLAM `cam_sinks` path
> (`receive_cam0..3` in `wmr_source.c`) has always applied `xf->timestamp += ws->cam_hw2mono`
> to convert the WMR hardware clock into Monado's host monotonic clock, but the
> controller-tracking frame path never had this -- unrelated to the previous session's
> `d6b84cda1` freshness-check `abs()` fix, which was correctly rejecting the resulting
> always-stale delta the whole time. Added `receive_ctrl_cam`, mirroring the SLAM
> correction. Confirmed via temporary tracing that it reaches `CameraSample` and
> `Camera::pushPose` correctly -- but found a SECOND, unexplained bug in the same run: at
> the `push_sample` call site, the timestamp is deterministically correct for one
> `device_id` and deterministically raw for the other, across an entire session, despite
> both devices reaching the identical code path from the identical
> `camera_sample.timestamp_ns` field. Not a race, not transient, not explained by the sink
> wiring (checked -- symmetric across all 4 cameras). `get_tracked_pose` still reports
> `position_tracked=no` for at least one controller as a result. Documented in place
> (`t_constellation_tracker.cpp`) and in `docs/pruebas.jsonl` T149 as the concrete next
> step: instrument `Camera::pushPose` per-device (not per-call, which has its own throttle
> bug described below) and find what actually differs between the two devices at that
> point, since the code path is provably identical.
>
> **Incidental fix**: `wmr_controller_base_get_tracked_pose`'s own diagnostic log (added
> last session, `9c78bc346`) used a function-local `static` throttle counter shared across
> BOTH controllers, so it only ever logged whichever device's calls happened to land on the
> modulo-90 boundary -- silently hiding the other controller's output all session, and
> nearly hiding the device-specific bug above too. Fixed to gate on the device's own
> `sample_count` instead.
>
> **Sync gap found and flagged**: `git log` on this monado checkout's actual
> `g2-constellation-x11kde` branch shows real committed history well past what
> `patches/monado/` exports as loose `.patch` files -- a "Fuse constellation position into
> the controller's output pose" commit (`332a57f27`) and several logging/freshness-check
> commits already exist there, referred to as "0017" work in their own commit messages, none
> exported yet. Noted in `patches/monado/README.md` so future sessions check `git log`
> directly rather than trusting the exported numbering is current.
>
> **Light-level calibration result**: user raised room light gradually from dark while
> checking blob tracking, aiming to compare against the known-good light level on Windows.
> Tracking held up through a small amount of added light and a controller standby cycle.
> At normal full living-room light (not dim), tracking still worked on standby-wake, but
> real false-positive blobs appeared near bright ambient light sources (lamps) -- consistent
> with the design tradeoff already known from thaytan's reference (short exposure/low gain
> isolates LEDs from ambient light, but sufficiently bright *other* sources can cross the
> same `pixel_threshold` blob detector uses and register as spurious blobs). Not tuned
> tonight -- deliberately left as a note, not a fix, since tuning `pixel_threshold` /
> `blob_required_threshold` (`wmr_source.c`'s `RIFT_BLOBWATCH_PIXEL_THRESHOLD_CV1` etc.) is
> its own separate pass, better done once the device-specific clock-domain bug above is
> resolved and there's an actual tracked pose to judge false positives against.
>
> Patch `0016` is committed locally on the everyday-system monado checkout only -- no fork
> remote configured there, so it hasn't been pushed anywhere. The `.patch` file is in this
> repo's `patches/monado/` already; applying it to the lab machine's tree is a manual
> `git am` away if useful there before the local commit gets pushed properly.

> **UPDATE (2026-08-11, everyday-system session #2): the `WMR_LOG=trace` experiment the
> previous entry left "not yet executed" is done -- controller-tagged frames genuinely
> read back exposure=0, confirmed quantitatively, and there is already an unvalidated
> patch in this repo attempting the exact fix.**
>
> New USB-C-to-USB-A adapter swapped in before this session (previous session closed on a
> degrading-link pattern, `reqCmd 23` + `non-desktop:0`). Clean 5/5 enumeration the whole
> session, zero `reqCmd 23`, zero USB2 branch drops -- the new adapter holds up. `lsusb`
> and `dmesg -T` checked before/after power-on; see `docs/22-cable-connector-diagnosis.md`
> for the established census if this needs re-checking later.
>
> **Bringup was noisier than usual**: 3 of the first 4 `jack-in.sh` launches failed
> (`vkAcquireXlibDisplayEXT: VK_ERROR_UNKNOWN`, and separately `wake_panel()`'s probe
> timing out at 25s with no error, just slow). One failed real-run process didn't exit on
> its own and blocked the next launch's `service_pids` guard ("Already running" with
> nothing actually presenting) -- had to `kill -TERM` it manually. Every failure recovered
> with a clean stop + retry; none correlated with `reqCmd 23` or USB dropping, so this
> reads as ordinary flakiness in the display-acquire race the script already documents,
> not a repeat of the hardware wear pattern. Once up, controllers registered fine after
> power-on + service restart (`left`/`right` show real names, 32 LEDs each in the
> constellation tracker).
>
> **The exposure measurement, finally captured**: set `WMR_LOG=trace`, let it run a few
> seconds, then paired each frame's `"... frame type %u"` trace line with the following
> `"... exposure %u"` line (both logged back-to-back from the same `img_xfer_cb` call in
> `wmr_camera.c`). Result over ~2400 frames: **frame type 2 (controller) -> exposure 0 in
> 2363/2374 cases (99.5%); frame type 0 (SLAM) -> exposure 450 in 1187/1187 (100%)**. The
> 11 outlier controller-frames reading 450 are consistent with brief carryover right after
> a SLAM frame, before the next controller frame's own (unset) exposure register is read
> back. This settles the question the previous entry raised: yes, controller-tagged frames
> read exposure=0, not just "no visible blobs" -- the sensor is not integrating light at
> all for that frametype, so zero detections is the only possible outcome regardless of
> LED brightness, controller distance/angle, or room lighting.
>
> Also ruled out tonight, independently, in case they were confounds: 30 seconds of active
> two-controller movement in front of the tracking cameras (0/17000+ blob observations,
> `constellation_tracker_camera_push_blobs` trace), and a separate 30-second measurement
> with the room's visible light off (0/9832) -- neither ambient light nor controller
> positioning explains the zero, consistent with the exposure=0 finding being sufficient
> on its own.
>
> **This project already has an unvalidated patch for exactly this**:
> `patches/monado/0015-d-wmr-Controller-frame-exposure-and-make-the-constel.patch`
> (committed 2026-08-11 earlier today as part of `266b90a`, lab machine). It adds
> `wmr_camera_set_ctrl_exposure_gain()`, addressing the controller-tracking hardware slots
> at `camera_id + tcam_count` (generalising thaytan's reference implementation's hardcoded
> `+2`, which only fits a two-camera headset), gated behind `WMR_CONSTELLATION_CONTROLLERS`
> (default off). The patch's own commit message says it was tried and **"the controller
> stream stays black on a G2, so either the slot mapping is wrong or the frames are not
> arriving"** -- i.e. already tested on the lab hardware and inconclusive between two
> different failure modes. **This patch is NOT applied to the everyday-system monado
> checkout** (confirmed: `grep -n WMR_CONSTELLATION_CONTROLLERS wmr_camera.c` finds
> nothing there), so tonight's exposure=0 reading is the clean unpatched baseline, exactly
> matching what the patch describes starting from.
>
> **Concrete next step, not yet done**: apply `0015` on a machine with `WMR_LOG=trace`
> wired up (this one, now), run with `WMR_CONSTELLATION_CONTROLLERS=1`, and re-check the
> same frametype/exposure pairing. Two distinguishable outcomes settle the open question
> from the patch's own commit message: if exposure now reads ~400 (`0x0190`) on
> frametype-2 frames but blobs are still zero, the slot mapping *is* landing on the right
> hardware register and the remaining gap is downstream (blob threshold, gain, LED
> visibility) -- narrow there next. If exposure still reads 0, the `camera_id + tcam_count`
> addressing itself is being ignored or rejected by the camera firmware, and the mapping
> hypothesis in the patch's own commit message is confirmed wrong -- worth trying
> `camera_id` unmodified next (i.e. the controller slots might not be offset from the SLAM
> ones at all on a 4-camera G2), or capturing the raw USB gain-command bytes to see if the
> device NAKs an out-of-range `camera_id`.
>
> **Separate, likely-unrelated oddity worth a note**: with the debug GUI's constellation
> tracker panel set to `Trace` log level, `Camera 0`'s "Blob Debug Sink (Fast)" and "(Slow)"
> panels both render as a solid, uniform magenta square -- not black, not a camera image.
> Classic missing/unbound-texture fill color in most graphics debug conventions. Did not
> investigate further; flagging in case it's informative once the exposure fix lands (a
> magenta sink after a real fix would mean the visualization path itself has a separate,
> independent bug from the exposure one).

> **UPDATE (2026-08-11, everyday system session, closing on a wear-pattern hardware
> failure). Second machine (`brunduk`, X11+KDE, unpatched 550.163.01 -- separate box from
> the lab, see `docs/29-source-map.md` for the topology) re-verifying the same 6DoF
> constellation series described below.**
>
> **The black controller-tracking-camera-frame problem is confirmed cross-machine, not
> lab-specific.** Same symptom exactly: `Controller Blob Cam N` panels stayed empty (zero
> blobs, `constellation_tracker_camera_push_blobs` logged "0 blobs" continuously -- frames
> ARE arriving, the pipeline isn't stalled, they just never contain a detectable blob).
> Traced one real candidate mechanism in `wmr_camera.c`: `update_expgain()` only ever runs
> from SLAM-tagged frames (`if (slam_tracking_frame) { ... update_expgain(cam, frames);
> ... }`), and its own loop only actually *writes* new exposure/gain to hardware for
> camera indices where `frames[i] != NULL` -- but on THIS machine `slam_cam_count ==
> tcam_count == 4` (confirmed via `Basalt with cam_count=4` in the log), so that specific
> index-gap theory does **not** explain the bug here the way `NEXT-STEP.md`'s "separate
> hardware slots" framing suggested -- worth re-examining `wmr_camera_set_exposure_gain`'s
> `location` parameter and whatever `WMR_CAMERAS`/frametype-specific addressing exists at
> the USB protocol level instead of the cam-index array, since the count-based theory is
> ruled out on this hardware. Set up `WMR_LOG=trace` to capture the real embedded
> per-frame exposure value (`wmr_camera.c`'s existing `"Camera frame seq ... exposure
> %u"` trace line, paired with the preceding `"... frame type %u"` line) correlated by
> frametype, to settle whether controller-tagged frames genuinely read exposure=0 --
> **never got a clean run with that logging on before the hardware gave out (see below)**,
> so this remains the concrete next step, not yet executed.
>
> **Real jack-in.sh bugs found and fixed on the everyday system** (that script isn't
> tracked in this repo, but worth knowing if `jack-in-wayland.sh` shares any of these
> patterns): `wake_panel()`'s success check trusted `xrandr`'s `DP-0` status, which does
> NOT reliably reflect a real direct-mode lease on this NVIDIA setup -- confirmed twice, a
> probe reached "Started vblank event thread!" (a real working lease) while `xrandr` kept
> reporting disconnected, so the old code declared failure and `kill -9`'d a working
> service. Fixed to check the log instead. Also found and fixed: the portrait monitor's
> output name had silently drifted from `DP-3` to `DP-1` at some point, so the rotation
> reassert had been a no-op for a while; and `wake_panel()`'s own throwaway probe was
> inheriting the caller's `XRT_DEBUG_GUI=1` and opening a real GUI window for a process
> that gets killed seconds later, fixed by forcing `XRT_DEBUG_GUI=0` on just that probe.
> Separately, confirmed a real kernel WARN in `nv_drm_revoke_modeset_permission`
> (`nvidia_drm`, driver 550.163.01) triggered by `kill -9`ing a process that still holds
> modeset permission from a failed `vkAcquireXlibDisplayEXT` -- non-fatal (driver/GPU stay
> healthy) but worth a `dmesg -T` check if `jack-in-wayland.sh` ever hits a similar
> kill-a-half-acquired-lease pattern. Full detail: `docs/22-cable-connector-diagnosis.md`'s
> newest section.
>
> **Session ended on the exact wear pattern this project already documented, not a new
> mystery.** After one full successful 6DoF session (SLAM + both controllers registered
> with the constellation tracker, real camera images, zero regression) and several
> service restarts to chase the exposure bug with heavier logging, the display lease
> started failing consistently (`vkAcquireXlibDisplayEXT: VK_ERROR_UNKNOWN`, 5 times in a
> row) with everything else clean: USB 5/5, brick 12V LED confirmed lit, WMR activation
> report sent every time, a free CRTC confirmed via `xrandr --listproviders` (3 of 4 in
> use). One attempt also logged a new, never-seen-before firmware-side error verbatim from
> the headset itself (`hololens_handle_debug`, not Monado-generated):
> `"ERROR: CommandSet st 0, cmd 0, reqCmd 23"` -- didn't recur on the next attempt, so
> likely a symptom of the same degrading link rather than a separate bug. This matches
> `docs/22`'s own established finding that **panel on/off power cycling is what wears the
> marginal visor-end contact** -- this session did roughly 8-10 full service
> starts/stops. Stopped cycling the hardware once the pattern was recognized rather than
> continuing to chase it as a software bug. **Physical steps for whoever resumes this**:
> let the hardware rest, then a plain PC-end USB reconnect or visor-end reseat per the
> existing ladder before assuming anything code-side regressed.
>
> **External research, for the record (2026-08-11):** looked for prior art on G2 90Hz +
> 6DoF while stuck -- see `docs/29-source-map.md`'s new "External leads checked, found
> unreliable or inconclusive" section. Short version: nothing panned out. Project-VR's
> 6DoF/EKF claim inherits this project's own pre-existing skepticism about that repo (no
> photo/video evidence, same false-positive shape already caught here 9 times). An old
> OpenHMD issue for a different WMR headset hit a strikingly similar unresolved firmware
> error (same message-type number, 23) but was never solved there either.

> **UPDATE (2026-08-11, ~05:15, closing a very long session). Read `docs/pruebas.jsonl`
> T145-T148.**
>
> **FIRST, THE HARDWARE.** The headset's USB2 branch dropped at 04:59 — `error -71` in
> `journalctl -k`, and `lsusb` left with only the SuperSpeed side. The known trigger is
> repeated `monado-service` restarts and this session ran about ten of them. Before doing
> anything else next time: `./preflight.sh`, and if the companion `03f0:0580` is missing,
> follow `docs/22`'s ladder (let it rest, then a PC-end replug, then the visor end) — do
> not restart the service repeatedly to "check again", that is what caused this.
>
> **THE CHECK THAT WOULD HAVE SAVED THREE RESTARTS:** when the controllers come up as
> `left: <none> right: <none>`, run `grep "Using builder" ~/vr/jack-in-wayland.log`
> **first**. With the companion gone, Monado falls back to the legacy builder's *Simulated
> HMD*, which still leases the connector, still logs `found display mode` and still prints
> `Socket ready`. Three restarts were spent diagnosing the T051 controller race when there
> was no WMR headset in the session at all.
>
> **What is verified and done:**
> - **0014** — constellation tracker over the 4 cameras, verified live, no regression
>   (30.1 → 30.0 Hz), extrinsics confirmed against the headset's own calibration.
> - **Player cubes** (hello_xr 0015) — verified on hardware, fixed in world space under head
>   rotation. Two real render bugs fixed to get there (background writing nearest depth;
>   the reference-space cube sealing the viewer inside a box). This is the in-headset
>   instrument for 0017.
> - **Always-on pose log** — head + both controllers, once a second, with `pos:`/`trk:`
>   flags. It is what made the untracked-controller placeholder visible without wearing the
>   headset.
>
> **The two open problems, in priority order:**
>
> 1. **SLAM runs away with the headset static** — 25 cm from the origin somewhere between
>    2.2 s and 50.8 s, then super-quadratic growth (`./scripts/pose-measure.py`). Ambient
>    light and missing frames are both ruled out by measurement; attribution to our own
>    patches failed twice, once because the A/B's "off" arm still ran the code under test,
>    once because a 12× effect claimed from one sample was refuted by the full six-run
>    table. **This blocks the height calibration** — any height reading is the real height
>    plus an unknown drift. Since T060-T061 (2026-08-07) documented 6DoF at rest without
>    divergence, a bisect over 0011-0015 is available and is the cheapest next move.
>
> 2. **Controller-tracking camera frames are black** — the upstream `Controller Tracking
>    Streams` panel, which predates all our patches, shows nothing while `SLAM Tracking
>    Streams` is perfect and the LED rings are plainly lit. This is why every blob panel is
>    black and why 0015's LED model would have fed a solver black images. The gap is
>    exposure: controller frames live in separate hardware slots and nothing sets them.
>    Patch 0015 adds the command but does not fix it, so it is opt-in.
>    **Do not keep guessing the slot mapping one restart at a time.** Build the two
>    instruments first: a one-shot per-frametype frame counter (settles whether the frames
>    arrive at all) and a live `u_var` control for the controller exposure slot (sweeps the
>    mapping with no restarts). A third candidate is not excluded:
>    `t_led_sync_refinement.c` exists because the constellation LEDs *strobe*, so a correct
>    short exposure landing outside the pulse still captures darkness.
>
> **Operational note:** the controllers fall asleep on their own when left still and their
> LEDs go out with them. Any optical test needs them held or moving.

> **UPDATE (2026-08-11) — Patch 0014 written, built clean and VERIFIED LIVE the same night.
> Verbose tracking logs are on. The floor/height question is answered, and it is not what
> SteamVR does. Read `docs/pruebas.jsonl` T145-T146.**
>
> **What 0014 measured, in two clean runs (one restart between them, not a chain):** both
> came up on attempt 1/3 at `4320x2160@90` with `Using builder wmr` and both controllers
> registered; the tracker was created over 4 tracking cameras with no devices registered;
> and the SLAM pose rate was **30.1 Hz without it and 30.0 Hz with it** — no regression,
> which was the whole question, since the blobwatch chain feeding it runs inside the same
> realtime USB callback as the SLAM path. Real 6DoF confirmed against a resting baseline:
> 4.04 m of path and 0.95 m of displacement over 59 s of deliberate movement, versus 2-4 cm
> of drift with the headset sitting on the table.
>
> **One real bug was found in 0014 and fixed before anything consumed it**: the per-camera
> extrinsics were composed the wrong way round (both `tcams[i]->pose` and the stored
> `P_ht0_me` needed inverting — `P_A_B` is the placement of B in A's frame). Caught by the
> printed camera positions being geometrically impossible, not by hardware, and **then
> confirmed fixed on the next run**: the four cameras now come out symmetric, slightly below
> eye level and at **negative Z** (in front of the eyes, as OpenXR −Z is forward), with
> `|pos0−pos1| = 0.1082 m` against the 0.1082 in the headset's own calibration, and
> `|pos0−pos3| = 0.1369 m` against 0.1371. Before the fix all four sat within ~8 mm of each
> other, behind the head.
>
> **Note on the indices, since the obvious check is wrong:** compare `pos0↔pos3` against
> HT2 and `pos0↔pos2` against HT3, *not* index-for-index. This code deliberately applies the
> same HT2/HT3 swap `wmr_hmd_fill_slam_cams_calibration()` already applies — the G2's
> calibration json has those two extrinsics flipped relative to the order the third and
> fourth images arrive over USB. An index-for-index check reads as a failure when everything
> is right.
>
> **What to do first, next session, in this order:**
> 1. Both controllers ON *before* the service starts, then `./preflight.sh` (3/3 or don't
>    burn a launch).
> 2. One clean `WMR_CONSTELLATION_CONTROLLERS=1 XRT_DEBUG_GUI=1 ./jack-in-wayland.sh 1
>    6dof` and check the camera distances above against the config. That closes 0014.
> 3. **Then: patch 0015** — build the G2's LED model from `wcb->config.leds[]` (parsed
>    today and thrown away) and register both controllers with
>    `t_constellation_tracker_add_device`.
>
> **Do not chain `monado-service` restarts to "just check again"** — standing rule from the
> user, and this project's own history (T074) says restart-cycling is itself a trigger for
> the USB2 fault. One clean run per question.
>
> **`det(Q1Jl) == 0` is NOT the divergence signature.** It appeared 859 and 630 times
> across these two runs with zero divergence in either — max step 3.0 cm in one, and in the
> other the only large steps were consecutive samples at a normal 33 ms interval, i.e. a
> fast real movement. Earlier sessions read that message as "Basalt diverged". Check the
> trajectory for an actual discontinuity before believing it.
>
> **Floor/height calibration — the real mechanism, read from the source.** Monado has no
> floor calibration. The WMR driver does not set `supported.stage`, so
> `b_space_overseer_legacy_setup()` makes `STAGE == root` (the tracking origin, i.e.
> wherever the headset was when Basalt initialised), `LOCAL == root + 1.6m` in Y and
> `LOCAL_FLOOR == root` — with that `1.6` a literal constant in
> `target_builder_helpers.c`. The floor is *assumed* to sit exactly 1.6 m below the headset
> at startup. The only knob today is `XRT_TRACKING_ORIGIN_OFFSET_{X,Y,Z}`:
>
>     XRT_TRACKING_ORIGIN_OFFSET_Y = (real headset height at startup) - 1.6
>
> Two procedures that need no code change: measure the headset height with a tape and set
> the difference (it must be at that height when `monado-service` starts, since root is
> pinned there), or run `XRT_DEBUG_GUI=1`, rest the headset on the floor, read Y off the
> HMD's "Tracked Pose" panel and use its negation — `wh->offset` is exposed as an editable
> "Pose Offset" in the same GUI, so it can be trimmed live before being fixed as an env
> var. **Putting the controllers on the floor cannot work until 0017** — they have no
> position at all before that.
>
> **Correction to the 0017 note further down, which says the placeholder has "a hardcoded
> `y=1.2`":** the real values in this tree are `(-0.2, 1.3, -0.5)` / `(0.2, 1.3, -0.5)` for
> the controllers and `(0, 1.6, 0)` for head and eyes, in `u_builder_helpers.c`, applied
> whenever `tracking_origin->type == XRT_TRACKING_TYPE_NONE` — and the *only* assignment of
> that field anywhere in the tree is the default `NONE` in `u_device.c:341`, so it is active
> on the WMR path even in 6DoF. This also fully explains the old "controllers appear offset
> by several metres and only rotate in place" symptom: they are pinned relative to **root**,
> not to the head, so with SLAM running the apparent error grows with how far you have
> walked from the SLAM origin. Check this against the fused result in 0017 before blaming
> the solver.

> **UPDATE (2026-08-09, closing this session) — Patch 0013 PHYSICALLY VERIFIED. The T046
> connector fault below was transient this time: reconnecting the 12V power brick alone
> (no visor-end reseat needed) eventually brought connector 137 back up.** With
> `XRT_DEBUG_GUI=1 ./jack-in-wayland.sh 1 6dof` and both controllers confirmed online first
> (via the new `preflight.sh`, see below), the "Controller Blob Cam N" panels showed blob
> boxes tracking the LED ring live while moving a controller in view, and the user
> confirmed SLAM head-tracking and controller rotation showed zero regression. `docs/03`
> and `patches/monado/README.md` updated to reflect the verified status.
>
> **New tool this session, born directly from tonight's mistakes — `scripts/preflight.sh`,
> also deployed to `~/vr/`.** Consolidates three checks that used to be done ad-hoc (and
> got skipped, causing real wasted attempts tonight) into one script with a clear
> READY/NOT-READY verdict and a concrete next action per failure:
> 1. USB devices 5/5.
> 2. **Controllers paired AND online**, checked directly via `controller-pair-check.py`
>    (now also deployed to `~/vr/`) — no Monado needed. This is the check that would have
>    caught tonight's first post-recovery attempt, which came back `left: <none> right:
>    <none>` simply because the controllers weren't powered on yet (hot-add doesn't exist,
>    already documented, but nothing enforced checking it *before* burning a launch
>    attempt).
> 3. The HMD's own DP connector via `drmprops`, requiring `non-desktop=1` specifically —
>    not just "some DP connector is connected" (see the false-positive bug below).
>
> Run `./preflight.sh` before every `jack-in-wayland.sh` from now on — it's what "no errar
> con las pruebas" (avoid wasting a launch attempt on something checkable in 5 seconds)
> means going forward for this project.
>
> **Script fixes from earlier this session (still in `~/vr/jack-in-wayland.sh` and synced
> to `scripts/jack-in-wayland.sh`, along with `preflight.sh`/`controller-pair-check.py`
> deployment) are NOT YET COMMITTED to git** — ask before committing (repo is public).
>
> The rest of this note (kept below, historical) is the T046-pattern connector-down
> diagnosis from earlier the same session — read it if this recurs, since this time it
> resolved with just a power-brick reconnect, cheaper than the visor-end reseat it
> initially pointed to.

> **UPDATE (2026-08-09, later same session) — Patch 0013 is code-complete but its physical
> verification is blocked: the headset's own DP connector genuinely isn't coming up right
> now, a real T046-pattern hardware symptom, not anything in the patch or the launch
> script.** Trying to run the first `XRT_DEBUG_GUI=1 ./jack-in-wayland.sh 1 6dof` check for
> 0013 (see the block right below this one) hit three straight "Found no connectors
> available for direct mode" failures plus two recurrences of the already-known,
> pre-existing Basalt/pangolin teardown SIGSEGV (`coredumpctl`, `vit_tracker_push_img_sample`
> / `t_slam_node_destroy` → `dlclose`, unrelated to 0013 — confirmed by backtrace, not in
> either crashing thread's stack).
>
> **Two real, separate script bugs found and fixed along the way (both kept regardless of
> tonight's hardware outcome):**
> 1. Added a bounded retry (3 attempts, 3s settle) around the whole service-launch-and-check
>    sequence in `jack-in-wayland.sh`, in case of a genuine transient compositor-side race.
> 2. **The actual root cause of tonight's repeated failures: the DP pre-flight check in
>    `jack-in-wayland.sh` accepted ANY `card*-DP-*/status == connected`, not specifically the
>    headset's own connector.** This machine ("iashur") has a real desktop monitor
>    permanently connected on a different DP port, which satisfied the check every single
>    time regardless of whether the headset's connector ever came up — a silent false
>    positive. Fixed by switching the pre-flight check to `drmprops` (already in
>    `scripts/`), requiring the specific DRM property that's actually HMD-specific:
>    `non-desktop=1` (T096 already established the headset is connector 137 on this
>    machine). Confirmed the new check correctly reports DOWN against the real current
>    state, where the old check was reporting a false UP.
>
> **With the false positive removed, the real state is visible: connector 137 stays
> `disconnected`, `non-desktop=0`, even right after a fresh `panel.py activate` that itself
> reports a fully healthy response (`0x09/0x08/0x06`, no `-1`s -- the same "HID is fine"
> signature T048 already established as normal).** This exactly matches `docs/22`'s T046
> pattern: USB/HID healthy and activation succeeds, but the DP/panel-power path stays dead
> regardless -- a decoupled fault, not a software/timing one. **Next step is physical**,
> per `docs/22`'s ladder: reseat the cable at the visor end (behind the magnetic face
> gasket) first; if that doesn't budge it, check the 12V brick. Don't re-diagnose this in
> software again before that -- the check-lease.sh / drmprops signal is now trustworthy and
> already confirms it's not a compositor or Monado-side problem.
>
> **Script fixes are in `~/vr/jack-in-wayland.sh` and synced to
> `scripts/jack-in-wayland.sh` in this repo, but NOT YET COMMITTED** -- ask before
> committing (repo is public). `~/vr/drmprops.c` was also added (copied from
> `scripts/drmprops.c`, wasn't deployed there before).
>
> **Once the connector comes back up, resume exactly where this left off**: run
> `XRT_DEBUG_GUI=1 ./jack-in-wayland.sh 1 6dof`, and check the new "Controller Blob Cam N"
> debug panels for live LED blob tracking while moving a controller in camera view (see the
> 0013 block below for full detail). Nothing about 0013 itself needs re-work -- it never
> got a chance to be exercised yet, this was blocked before the stack ever came up.

> **UPDATE (2026-08-09) — 6DoF resumed without waiting for upstream reviewer feedback;
> Patch 0013 written and built clean, NOT yet physically verified.** The prior pause (below)
> was waiting on the 4 Monado MRs before touching this again. Decision this session: stop
> waiting — the only reviewer activity so far (Jan Schmidt / thaytan, on `!2967`) is about
> code authorship, not about constellation-tracking design, and there's no signal a
> 6DoF-specific review is coming soon. The plan: build the whole thing working locally first
> (each patch independently verified), which makes every patch easier to justify when it
> does go upstream — same pattern that already worked for 0001-0011.
>
> **Also decided this session: a desktop-only verification loop, no headset-worn required
> for most of the series.** Investigated before writing any code — Monado already ships
> `constellation_debug_scribble.cpp` (draws detected blobs + solved pose over the camera
> image, toggleable, visible in the existing `XRT_DEBUG_GUI=1` window) and the "Controller
> Tracking Streams" panel already used for Stage 0. Nothing new needed to build a visor —
> just wire the existing debug-GUI machinery through as each patch lands. Headset sits
> powered on (not worn) pointed at where a controller moves; only the last two patches
> (position actually fused into the output pose) need the headset on a real head.
>
> **Full staged plan (0013-0018), designed via Claude's plan mode and approved, is written
> out patch-by-patch in `docs/03-controllers.md`'s "Positional tracking (6DoF)" discussion
> and duplicated here for durability** (the interactive plan file itself lives outside this
> repo and may not survive to the next session):
> 1. **0013** (this session, done, NOT physically verified yet): split controller-tracking
>    frames per camera in `wmr_camera.c` (previously dropped at `drop_frame:`), run LED blob
>    detection via `t_rift_blobwatch`, show it in a new "Controller Blob Cam N" debug panel.
>    Builds clean, `ninja monado-service` links. **Next physical step: `XRT_DEBUG_GUI=1`,
>    headset on but not worn, pointed at a controller, both controllers on — the new panels
>    should show live blob boxes tracking the LED ring, and normal SLAM/head-tracking
>    behavior must be unaffected (regression check).**
> 2. **0014**: create a `t_constellation_tracker` over the WMR camera mosaic (build/plumbing
>    only, gated behind `WMR_CONSTELLATION_CONTROLLERS`, default off).
> 3. **0015**: build the G2's LED model from `wcb->config.leds[]` (parsed today, thrown
>    away) and register both controllers with `t_constellation_tracker_add_device`.
> 4. **0016**: store constellation position samples per controller (telemetry only) +
>    live XYZ counters in the debug GUI — this is the desktop instrument that directly
>    answers "is it still just rotating in place, or has it started moving in 3D".
> 5. **0017**: fuse constellation POSITION into the controller's output pose. Orientation
>    stays exclusively from the existing, already-good gyro fusion (`wcb->fusion.rot`),
>    never overwritten — deliberately not doing what rift/pssense do (they replace the whole
>    pose). **First patch needing full physical on-headset verification, no exceptions.**
>    Also the point to sanity-check the user's own hypothesis about a missing height/floor
>    calibration: if the fused position looks offset by a constant amount (not noisy, just
>    shifted), check the tracker's world-frame anchor (`pose_in_origin`) before assuming a
>    solver bug — the placeholder position has a hardcoded `y=1.2` today.
> 6. **0018**: flip the default to on, re-verify physically at least once more.
>
> `patches/monado/0013` exported and in the tree; `patches/monado/README.md` updated.

> **UPDATE (2026-08-08, ~20:10) — G2-controller-6DoF work started for real: Stage 0
> confirmed the LEDs are trackable, Patch 0012 (`patches/monado/0012`) landed and is
> physically verified. Two unrelated pre-existing bugs surfaced along the way and are
> worth knowing about before the next session. Read `docs/pruebas.jsonl` T097-T098 and the
> plan at the bottom of this note.**
>
> Full plan for real positional tracking on the controllers was designed and approved
> (via plan mode, not summarized here — see the plan file referenced by this session, or
> re-derive it from `docs/03-controllers.md` if it's gone) as a staged `patches/monado/
> 0012`-`0017`+ series, each patch with a mandatory physical verification checkpoint.
> **Stage 0** (zero code — just `XRT_DEBUG_GUI=1` and looking at the existing, previously
> ignored "Controller Tracking Streams" debug panel) confirmed the headset's own cameras
> already see the controller LEDs as clean, sharp, moving blobs — the real signal
> constellation tracking needs is there. **Patch 0012** (link `libconstellation.a`,
> already used by `rift`/`pssense`, into `drv_wmr` — build-only, zero call sites added
> yet) is committed in `~/vr/monado` and exported to `patches/monado/0012`, verified
> clean after a detour (below).
>
> **Two real, pre-existing bugs found while regression-testing 0012 — neither caused by
> the patch, but both worth remembering:**
> 1. `monado-service` has a real SIGSEGV bug inside Basalt's `vit_tracker_push_img_sample`,
>    apparently on teardown — `coredumpctl list monado-service` shows this same crash
>    class recurring since 2026-08-04, well before today. Not root-caused or fixed this
>    session (out of scope for the 6DoF work), just confirmed real and pre-existing via
>    `coredumpctl info <pid>`. Worth a look sometime: `coredumpctl` is the tool, not
>    guessing from logs.
> 2. The Logitech wireless mouse/keyboard receiver (`046d:c534`) re-enumerates unstably
>    on this new machine and confuses Monado's USB prober (`p_dev_get_usb_dev` logs "USB
>    device with same address but different vendor and product found!"). Cosmetic noise
>    in the log, not confirmed to break anything, but now identified so it doesn't get
>    mistaken for a headset problem later.
>
> **Process lesson re-confirmed hard, live, in this exact session**: after landing 0012,
> rapid repeated `monado-service` restarts (rebuild → relaunch → check → relaunch again)
> is what actually triggered a USB2 companion+audio drop and, separately, a silent
> mid-startup death with no coredump — matching this project's own long-standing warning
> about restart-cycling being a trigger, not a diagnostic. The fix both times was the
> same as always: stop, let the hardware sit a few minutes, then ONE clean relaunch —
> which worked immediately. Don't skip the pause next time either.
>
> **Next step**: Patch 0013 — add the `else` branch in `wmr_camera.c`'s `img_xfer_cb` to
> route frametype-0x2 (controller) frames into a `t_rift_blobwatch` instance per camera
> and a new debug-visualizer panel, instead of dropping them. This is real code inside
> the same realtime USB callback the already-working SLAM path uses, so its own
> regression check (does head tracking still behave normally right after) matters more
> than usual. Both controllers need to be on before `monado-service` starts, as always.

> **UPDATE (2026-08-08, ~18:55) — third physical machine, full stack re-validated clean,
> now moving on to the big remaining gap: real 6DoF (positional) tracking for the
> controllers.** Read `docs/pruebas.jsonl` T096.
>
> The lab hardware changed again mid-project — new machine ("iashur", Gigabyte A520M K V2,
> RTX 3060 Ti GA104), same lab SSD carried over. User asked to validate everything before
> continuing, and nothing was assumed: checked the NVIDIA driver's actual patch state (not
> just that *a* driver loaded — confirmed via `/var/lib/dkms/.../make.log` that all 4
> patches, including the load-bearing bpc one, applied in the last build and that the
> system uptime postdates it), USB enumeration, DP hotplug, the Wayland DRM lease, and the
> real WMR builder taking 90Hz. **Two separate human-verified runs, both clean**: a 3DoF
> photo test ("todo perfecto, el test se ve claro a 90hz") and a 6DoF+both-controllers run
> with real head movement and Basalt/SLAM ("todo bien"). Both controllers registered on the
> first try with no startup-race loss. Nothing about the move broke anything — the stack's
> reproducibility doesn't depend on any one box.
>
> **Next task, requested directly by the user right after validation: give the controllers
> real 6DoF (positional) tracking, not just 3DoF rotation.** This is the big item flagged
> in `docs/03-controllers.md` under "What's still missing" as *"THE big next step after
> 90Hz"* — constellation tracking (optical LED-based positional tracking using the
> headset's own cameras) already exists upstream and compiles into this build
> (`libconstellation.a`), the headset camera already separates controller frames
> (frametype `0x2`, currently discarded into a debug sink), and the LED geometry is already
> parsed from the controller's calibration and thrown away. What's missing is wiring it
> up: the ring occlusion model, moving-camera mosaic, and camera/IMU temporal alignment.
> `docs/03` names two in-tree reference drivers (rift, pssense) and a fork that has this
> working for WMR specifically — thaytan's `dev-constellation-controller-tracking` — as
> "the base for Project-VR's work." Not started yet as of this note; scope it out (read
> `docs/03`'s section in full, look at thaytan's fork) before writing any code, this is a
> substantially bigger task than anything else closed today.

> **UPDATE (2026-08-08, same-day continuation) — full game compatibility sweep, one more real
> xrizer bug found, the T073 backlog fully closed, and a genuinely open question about our
> own recenter patch that needs picking up.** Full session in `docs/pruebas.jsonl` T087-T095,
> new reference doc `docs/23-game-compatibility.md` (every title tried, Steam AppID + SteamDB
> link, working/broken/failed/untested, with notes).
>
> **Two more titles confirmed fully working, one of them the best result of the whole
> project so far.** VRChat reaches `FOCUSED`, real gameplay, EasyAntiCheat loads clean under
> Proton. **Propagation VR (Unreal Engine) "works just perfect" — trigger/grip AND the
> in-game menu/quit both work out of the box, no patch needed at all**, unlike SUPERHOT
> which needed `patches/xrizer/0002` just for its left-hand menu. Controller hot-add still
> doesn't exist (confirmed again) — Propagation VR's first attempt had `<none>`/`<none>`
> because the controllers were off before Monado started; a clean `jack-in-wayland.sh`
> restart with them on beforehand fixed it.
>
> **A third distinct real xrizer bug found: Water Bears VR.** The compositor recreates the
> swapchain every single frame, for both eyes, forever (`compositor.rs:1247`, ~65
> cycles/sec) — never stabilizes a presentable frame, panel stays dark the whole time. The
> game itself is healthy (trigger gives audible feedback, renders fine to its own 2D
> mirror) — purely a compositor-side bug, not root-caused further. Logged in
> `patches/xrizer/README.md` alongside the Poly Runner and War Robots entries.
>
> **The entire T073 backlog (5 titles left "inconclusive"/"log-only" for weeks) is now
> closed, no exceptions.** Overkill VR and Dark Room VR were both "maybe just needs longer"
> guesses — both physically confirmed as real failures instead: xrizer opens one harmless
> throwaway session then goes permanently silent, headset stays dark, the game keeps
> running/rendering in its own 2D window the whole time (Dark Room VR even shows a black
> square placeholder where its VR view should be, not a crash). Dark Room VR's launch had
> additionally been silently blocked by a hidden "headset may not be supported" dialog
> sitting behind Steam's main window this whole time — worth remembering as a class of
> false "nothing happens" symptom. Welcome to Chornobayivka VR reaches `FOCUSED` with
> working controllers, but has a **fixed camera roll baked in at launch by the game's own
> non-standard calibration** — confirmed our recenter patch neither causes nor fixes it (by
> design, recenter only ever touches yaw + position, matching real SteamVR).
>
> **Open question, NOT resolved, possibly bigger than one game — pick this up next:** on
> Chornobayivka, the user reported that holding the real recenter (menu-hold 3s) always
> seemed to return to the same fixed-feeling wrong spot regardless of where they'd
> physically moved first. This could just be the persistent roll bug above making every
> recenter look equally "wrong," or it could be a real bug in `reset_tracking_space`
> triggered under some condition this game hits (it worked correctly and was confirmed
> position-accurate on VRSailing in T080, so it's not a blanket failure). A discriminating
> test was proposed and NOT run: face a different direction before recentering and check
> whether the facing (yaw) updates independent of the roll, or whether it snaps back to a
> fixed facing too. Do this first before touching `openxr_data.rs` again.
>
> **Non-Steam titles: one real success, one dead end, one bigger idea parked.** Blade Runner
> 9732 (Deckard's apartment tour, delisted from Steam in 2018 over a DMCA claim) was
> recovered via the developer's own still-live Google Drive link and run in a dedicated
> standalone Proton prefix (`~/vr/nonsteam/`, own `openvrpaths.vrpath` pointing at xrizer) —
> reaches xrizer's `ClientCore` but hangs forever on `VR state wait timeout`, a fourth
> distinct failure shape from today, not root-caused further. "The Matrix VR" (DK2-era) has
> a dead source site, not recovered. True DK2-era native-Oculus-SDK demos would need a
> Revive-style shim first (different API generation entirely, pre-dates OpenVR) — parked to
> memory (`idea_dk2_revive_legacy_demos.md`), explicitly NOT started, bigger than this sweep.
>
> **Infra lessons reinforced, not new:** the panel/DP link dropped fully dark twice more
> after roughly an hour of continuous `monado-service` uptime and heavy session churn —
> both times a plain `jack-in-wayland.sh` restart recovered it instantly with zero
> regression (confirmed via SUPERHOT re-checks each time). USB2 storms recurred three more
> times; passive waiting never once cleared one on its own (tested up to 5 minutes
> straight), but a plain 12V power-brick reconnect (not a full visor-end cable reseat)
> cleared every single one, 3/3. Doesn't retire the rev2A cable question — still treat it as
> open — but it's a cheaper first thing to try than a full reseat.

> **UPDATE (2026-08-08, midday session) — item 1 below got real progress (SUPERHOT's menu
> button, a related-but-different bug), and item 1's Poly Runner part got re-characterized,
> not closed.** Full session in `docs/pruebas.jsonl` T082-T086, patch in
> `patches/xrizer/0002`.
>
> **SUPERHOT's unresponsive menu button (T067, never resolved) is fixed for the left
> controller.** Confirmed first, via `XRT_DEBUG_GUI=1`, that raw input was 100% healthy at
> the Monado level on both controllers (trigger, squeeze, menu, Y/B, bt_pairing all
> register) — also confirmed trigger/grab/hand-tracking all work fine in-game now, so
> T067's "no button does anything" was almost certainly that night's USB2 instability, not
> a real bug. The menu specifically was real though: SUPERHOT's default oculus_touch
> bindings only offer two sources for its MENU action — a `long` press on X (input mode not
> implemented anywhere in xrizer) and a click on `system` (never a recognized path string in
> xrizer at all) — so the action was permanently unbound, regardless of controller type, not
> WMR/G2-specific. Patched the `system` half (`patches/xrizer/0002`, one line, same alias
> pattern already used for `application_menu`): confirmed live, left controller's physical
> menu button now opens SUPERHOT's pause menu. The `long`-press half is NOT fixed — more
> invasive, needs real long-press detection added to `ButtonInput`. Right hand also not
> expected to work (`Menu` is Left-only on this profile, matches real hardware).
>
> **Poly Runner VR's `IVRCompositor_013` diagnosis is still a dead end (confirmed again),
> but T072's "clean self-exit" characterization does NOT reproduce.** Retested twice: both
> times the game gets stuck permanently at OpenXR session state `READY`, spamming the
> interface request in a tight infinite loop (~1300 lines/sec, ~190% CPU), never exiting on
> its own — had to be killed by hand both times. The game keeps rendering normally in flat
> 2D throughout (confirmed physically), it just never enters stereo VR. Whoever picks up
> item 1 below for Poly Runner: start from this corrected behavior, not T072's.
>
> Also found and NOT fixed: `wmr_controller_hp.c` parses controller battery level from
> hardware but never wires it into Monado's generic `xrt_device::get_battery_status` API —
> only visible in the interactive debug GUI, not queryable via `libmonado`/IPC. Small,
> same-pattern fix if useful later.

> **RESOLVED (2026-08-08, ~05:25) — the item right below this note is fully closed.** Did
> exactly what it asked: rebuilt `~/vr/monado` clean via `git am` of `patches/monado/0001-
> 0011` only, re-ran the controller-registration scenario (3x, not just once) — clean every
> time, no drift, no `0012` needed. `0012` is now deleted from `patches/monado/`, README
> updated with the postmortem. Along the way, a much bigger and completely unrelated
> "the cable must be dying again" panic turned out to be a missing `panel.py` file in the
> lab's `~/vr/` deployment (not hardware) — see the CLAUDE.md milestone banner dated
> 2026-08-08 for the full night, including a new xrizer patch (global recenter,
> `patches/xrizer/0001`) and four real, human-verified working games with 6DoF head
> tracking. **Next things queued from that session, none started:**
> 1. Root-cause Poly Runner VR's real exit cause from scratch — the `IVRCompositor_013`
>    diagnosis was checked against every OpenVR header Valve ever shipped and found to be
>    wrong (that version never existed); the actual reason its xrizer session exits is
>    still unknown. See `patches/xrizer/README.md`.
> 2. War Robots VR: The Skirmish is blocked on HMD presence detection missing in BOTH
>    Monado (`wmr_hmd.c` never wires its own proximity sensor into `XR_EXT_user_presence`)
>    and xrizer (`ShouldApplicationPause`/`IsInputAvailable` are stubs) — a two-repo fix,
>    scoped but not started. `patches/xrizer/README.md` has the detail.
> 3. The rest of the game list from `docs/pruebas.jsonl` T073 (Overkill VR inconclusive,
>    Dark Room VR never even launched, Surgeon Simulator/Chornobayivka/World of Guns failed
>    fast) still needs a proper, unhurried look now that the panel/DP bug and the recenter
>    feature are both fixed — several of those failures might resolve or look different
>    with a working recenter available.
> 4. `patches/xrizer/0001` (global recenter) has only been field-tested on the
>    `oculus/touch_controller` profile (what our WMR controllers present as) -- the field
>    edits to `knuckles.rs`/`vive_controller.rs`/`simple_controller.rs`/`vive_focus3.rs`/
>    `meta_touch_plus.rs` compile and pass the existing binding tests, but were never tested
>    on real hardware of those types (none is available in this lab).

> **CORRECTION NEEDED (2026-08-07, from the comms session, mounted the lab SSD read-only to
> check upstream status) — patch `0012` does not describe a bug in anything pushed
> upstream; the tracked patch series is fine as-is.**
>
> Checked `wmr-hid-resilience` (MR !2967, tip `9f9ff4d16`, confirmed against the live GitLab
> MR) directly against `patches/monado/0003-...-Bound-the-controller-status-wait...patch`:
> they are byte-identical, and both already use the correct form —
> `while (!(wh->have_left_controller_status && wh->have_right_controller_status) && os_monotonic_get_ns() < deadline_ns)`,
> 10s deadline, `next_request_ns` re-request every second. No AND/OR bug here.
>
> `patches/monado/0012`'s "before" hunk shows a **3-second deadline** with a bare
> `!left && !right` condition and different comment text — that matches *neither* the
> pristine pre-patch upstream code *nor* the finalized/pushed `0003`. Whatever build was
> actually running on real hardware for T051/T066 (the SUPERHOT/xrizer session) had
> **drifted from the tracked patch series** before that test — most likely the 10s deadline
> got hand-shortened to 3s for faster iteration at some point, and the AND/OR slip happened
> in that same untracked edit.
>
> **Nothing was pushed to !2967 over this** — pushing `0012` as-is wouldn't even apply
> (context mismatch), and since `!(A && B)` and `(!A || !B)` are logically identical
> (De Morgan), forcing it through would just rewrite already-correct code.
>
> **Next step for whoever picks this up on the lab machine:** rebuild the actual test
> binary fresh from `patches/monado/0001-0011` (via `bootstrap-lab.sh sources`, no manual
> edits) and re-run T066's scenario against that clean build. If the 9/9 repro still
> happens, it's a real bug somewhere else and worth a fresh look; if it doesn't, the
> earlier finding was an artifact of the drifted live tree and `0012` can be dropped.
> Also worth a quick audit of the lab's build tree for other hand-edits that never made it
> into `patches/` — this is the kind of drift that's easy to lose track of mid-session.

> **UPDATE 2026-08-07:** items 2 of the list below (player/VR180 + playlist) are **DONE
> and verified** — the directory playlist chains videos unattended and real content at
> 4320x2160@90 through the full player is clean (T041, `docs/22-cable-connector-diagnosis.md`).
> That same night the headset appeared to die entirely (DP, panel, then USB2) — root cause
> was the visor-end cable connector, reseat fixed it; read `docs/22` before diagnosing any
> "headset dead" symptom. Items 1 (controllers stress test), 3 and 4 below remain as
> written. Also: the x3600 is now a validated second lab machine.

## READ FIRST — status as of 2026-08-06, early morning

Written from the everyday system with the lab SSD mounted read-write at `/mnt/lab`, before
the user reboots into the lab install to test physically. **This is what needs to be done
when back — the rest of the file, further below, is 90Hz history, do not read
first.**

Repo already public (`github.com/Wintch/reverb-g2`), last night's update posted on the
NVIDIA thread (379240), and the 4 Monado MRs opened against upstream (`monado/monado` #2967,
#2968, #2969, #2971) — none of that needs the lab, it's already resolved.

**What does need the lab, in order:**

1. **Controllers** (the 4 input/connection patches are already in `patches/monado/0001-0008`,
   applied via `bootstrap-lab.sh sources`; also already uploaded upstream as an MR, see
   above, but that doesn't change anything locally):
   ```bash
   ./jack-in.sh 3dof     # controllers must be ON BEFORE this (hot-add doesn't exist: T043
                         # proved late power-on never reaches Monado; the old "before or
                         # after, no longer matters" claim here overstated T025)
   grep -E "left:|right:" ~/Documents/reverb-g2/jack-in.log
   # should say: left: HP Reverb G2 Left Controller / right: HP Reverb G2 Right Controller
   ```
   Live diagnostics (sticks, battery, IMU per controller): `XRT_DEBUG_GUI=1` before
   starting the service, look at each controller's panels. Sticks at rest should read
   exactly (0,0) — if they drift, the deadzone patch didn't load correctly. Stress test:
   10 boot cycles with the controllers on, should connect 10/10 (see `docs/03`).

2. **Player / VR180:**
   ```bash
   ./play360.sh ~/Documents/reverb-g2/photo360/vr180_berlin_8k60.mp4   # 8K60 stereo, the good one
   ./play360.sh ~/Documents/reverb-g2/playlist_test/                   # playlist feature, never tested interactively
   ```
   With the headset on: confirm real stereo image (not flattened), no starves at 8K60, and that
   the transport keys (space pauses, `[`/`]` speed, `n` next, `q` quit)
   respond. If the terminal goes mute afterward: `stty sane`.

3. **Do NOT instrument the USB2 hub reset yet** — investigated by code review (no hardware)
   on 2026-08-06: autosuspend is already ruled out (rule `71-usb-no-autosuspend.rules` covers
   `04b4` from the bootstrap), and the mishandled-keepalive hypothesis doesn't hold up either
   after reading `wmr_hmd.c` (non-blocking poll, no periodic writes). If it needs to be
   picked up again in 1-2: add timestamped logging to `control_read_packets`/
   `hololens_sensors_read_packets` and run under load until it resets — that's the only way
   to see what happens right before, that data doesn't exist yet. Detail in `docs/06-known-issues.md`.

4. **Constellation tracking (controller 6DoF) — paused on purpose.** There's a trial merge
   already done (throwaway branch, already deleted) against `gitlab.freedesktop.org/thaytan/monado`
   branch `dev-constellation-controller-tracking`: 8 conflicts, all mechanical (CMake +
   reconciling the hand-tracking device list), none touching the files from our 4
   patches. **Do not resume yet** — waiting for the Monado reviewers to respond something on
   the 4 MRs before finishing that merge, to avoid rewriting code that might change based on
   feedback. See `docs/03-controllers.md`, section "Positional tracking (6DoF)".

None of this is urgent — the user explicitly asked for pacing ("we'll fit it in over time"). The
only reason for the reboot now is that the headset is physically in front of them and there's a wish to test it.

---

State as of 2026-08-05, late. Written from the everyday system with the lab SSD mounted
read-write at `/mnt/lab`, right before rebooting into the lab OS to resume physically.

Same physical machine, two separate Debian 13 installs on separate disks (see
`docs/17-publishing.md` history / the repo's own notes) — the headset does not need to be
unplugged to switch between them, just reboot and pick the lab SSD at the boot menu, log in
as `iam`.

## IN PROGRESS (2026-08-05, night): the factorial ran — CTRL fails, and points to resolution, not vblank

**The loading path (option 2, `nvidia_modeset.config_file` with the `DP-0` key) is
confirmed end to end**: reboot done, `dmesg` with no warning, `/sys/class/drm/card0-DP-1/edid`
byte-identical to `g2-vblank-test.edid`, and DRM went from seeing 3 modes to 6. Full detail and the
code chain that explains the `DP-0`/`DP-1` off-by-one is further below in this file
("Earlier this same session"), untouched.

**The full factorial ran: CTRL → B → A. All three fail** (HP logo, no video),
with the headset on. But with a new data point that the `docs/16` table didn't anticipate: the headset's
HID (`DEVICE_STATUS`) confirms, in all three cases, a **byte-for-byte identical** timing
to what was injected (exact htotal/vtotal/refresh/bpc) — so the override arrived perfectly all the way to
the physical link. That rules out "the override didn't arrive" as an explanation for the failure.

**What remains as the most likely explanation: the three injected modes are 2880x1440, and
that resolution never showed anything in the entire history of the project**, at any refresh
(the native 2880x1440@90 mode was already failing before). The only case that ever worked is
4320x2160@60. The resolution explains 100% of the results without needing to invoke
vblank or refresh — which **doesn't close the vblank hypothesis, it leaves it untested
for now**: the factorial needs to be repeated injecting into the DisplayID Type I descriptors
(4320x2160) instead of the base block, as `docs/16` already anticipated ("If it needs to be
repeated at 4320x2160"). The decoder for those descriptors already exists and is validated byte by byte against the
real EDID; the encoder (`inject-did`) still needs to be written — the byte layer is documented in
that same section with the exact offsets.

**Full detail, with the HID tables and the unexplained anomaly (byte 1 of A, see
below), in `docs/16-lab-vblank.md`, section "Run (2026-08-05): CTRL fails".**

**`inject-did` is now written, tested, and in use.** Symmetric encoder to `decode_did_type1`
in `scripts/edid-tool.py`, with a round-trip verified by the full decoder and both
checksums (DisplayID section + extension block) correct. It already generated the three EDIDs for
the second round: `experiments/vblank/g2-vblank-4k-{ctrl,b,a}.edid`, each with
descriptor #1 (the one that was failing at 90 Hz) replaced by `CTRL4K`/`B4K`/`A4K` and
descriptor #2 (@60, the one that works) intact as a control. Detail and why `B4K` uses vblank
240 and not 514 (bandwidth at a width of 4320) in `docs/16`, section "Second round".

**`CTRL4K` run and confirmed (T012): WORKS.** Colors alternating (blue/white/green) with
the headset on, HID confirms exact 60Hz and the backlight bit on. Descriptor #1
is not the cause of the failure — cloning a healthy timing there works the same as in its
original position. Detail in `docs/16`, section "`CTRL4K` run". Put together
`scripts/verify-override.sh` (runs as root, bundles dmesg + detect + md5 into a single
`sudo`) to avoid asking for the password command by command in each round.

**`B4K` run and confirmed (T013): FAILS.** Only the HP logo, headset on. Same
descriptor #1 that had just tested healthy with `CTRL4K` at 60 Hz — now at 90 Hz with a short
vblank (240) it doesn't lock. New data point still unexplained: the HID (`panel-status.py`) didn't
even get to report 90 Hz — it stayed showing the last known state (60, from
`CTRL4K`) and the companion re-enumerated with no further messages. Different from the previous
round, where the HID did confirm the injected timing byte for byte despite failing visually. Full
detail in `docs/16`, section "`B4K` run".

**`A4K` run and confirmed (T014): FAILS too — this closes the 2x2 factorial.**
`CTRL4K` (60Hz, vblank514) works; `A4K` (60Hz, vblank116) and `B4K` (90Hz, vblank240) both
fail. **It's not the refresh — it's the short vblank**, and it's not bandwidth either: `A4K` runs
at only 603.6 MHz, well below the HBR3 ceiling, and fails exactly the same as `B4K` at
954.72 MHz. The real limit is a minimum vertical blanking duration, not bits/second.
Full detail in `docs/16`, section "`A4K` run — and this closes the factorial".

**This reopens 90 Hz as achievable.** If the minimum vblank needed is compatible
with 90 Hz within HBR3, there's no need to lower the refresh. The most direct candidate has
already been generated: `experiments/vblank/g2-vblank-4k-90long.edid` — 4320x2160@90 with the same
vblank 514 that does work at 60 Hz (`./scripts/edid-tool.py inject-did ... 514@90:1`). Pixel clock
1063.72 MHz → 25.53 Gbps @24bpp, within the HBR3 ceiling (25.92, ~1.5% margin). The `.conf`
already points there.

**`90long` run and confirmed (T015): FAILS.** Only HP logo, headset on. This time the HID
did confirm 90Hz and exact timing (unlike `B4K`, which had stayed at the old
state) — so the mode arrived complete and still doesn't lock. The four results so far
(`A4K` 0.849ms FAILS, `B4K` 1.111ms FAILS, `90long` 2.136ms FAILS, `CTRL4K` 3.204ms
WORKS) sort cleanly by **vertical blanking time in ms**
(`vblank/((vact+vblank)·rate)`), not by lines — `90long` and `CTRL4K` have the same number
of lines (514) and just the different refresh alone is enough for one to fail and the other not.
Detail and the full table in `docs/16`, section "`90long` run".

**This is a serious problem for 90 Hz:** the HBR3 ceiling limits vblank to ~555 lines at
90 Hz, i.e. **~2.27 ms as the maximum possible** — below the 3.204 ms already known
to work. If the real time threshold is closer to 3.2 than to 2.27, 90 Hz may be
simply impossible within HBR3, regardless of vblank.

Before spending another reboot near the bandwidth limit at 90 Hz, a candidate was put together to
bound the real threshold **at 60 Hz** (without bandwidth pressure):
`experiments/vblank/g2-vblank-4k-bisect1.edid` — vblank=340 lines at 60Hz, the same 2.27 ms
that would be the maximum possible at 90 Hz. The `.conf` already points there.

**`bisect1` run and confirmed (T016): FAILS.** Only HP logo, HID confirms exact timing
(60Hz, vtotal 2500) delivered perfectly. vblank=340@60Hz gives 2.27ms — the same time that
would be the maximum possible at 90Hz within HBR3 — and it fails. **This rules out 90 Hz as
achievable within this HBR3 DisplayPort link**, regardless of what vblank is used: the
real time threshold is above 2.27ms, and the bandwidth ceiling at 90Hz doesn't allow
exceeding that value under any combination.

**Decision with the user (2026-08-05): instead of continuing to bisect the exact threshold at
60Hz, go straight to an intermediate refresh with real margin.** At 80Hz the bandwidth ceiling
allows up to 3.66ms (vs the known-working 3.204ms) — much more margin than at 90Hz.
`experiments/vblank/g2-vblank-4k-80hz.edid` was generated: vblank=775 lines at 80Hz, 1037.82
MHz, 3.301ms, 24.91 of 25.92 Gbps (~4% margin, not at the limit like the 90Hz attempts). The
`.conf` already points there. **This redefines the goal**: `CLAUDE.md` assumes that "the only cure"
for the flicker is 90Hz, but that was never tested at an intermediate refresh — if 80Hz reduces or
eliminates the perceptible flicker, the success criterion changes. Detail in `docs/16`, section
"`bisect1` run".

**`80hz` run and confirmed (T017): FAILS.** No image, only logo. HID confirmed exact
refresh of 80 and exact timing delivered. **This refutes the vblank time threshold
hypothesis**: `80hz` has 3.301 ms of blanking — more than the 3.204 ms of `CTRL4K`, which
does work — and still fails. The pattern that does survive across the 7 data points: the only pixel clock that
ever showed an image is **≈709.15 MHz** (the native 4320x2160@60 and its clone `CTRL4K`);
everything else failed, regardless of bandwidth, vblank in lines or in time. Full detail
and the table in `docs/16`, section "`80hz` run".

**Major pivot (2026-08-05, night):** instead of continuing to bisect blindly, the
hardware was investigated. The user brought the real datasheet for the **ANX7530** bridge (official
Analogix Product Brief, AA-004263-PB-7 — not versioned here, it carries a copyright notice; see `docs/10`
for the public link): it states the link ceiling as **HBR2.5 (6.75 Gbps/lane,
not HBR3)** and an explicit spec line — **"DisplayPort Receiver Input Bandwidth supports
up to 4K x 2K x 60Hz"** — which is a refresh ceiling declared by the manufacturer, not just
a bandwidth calculation. This matches the fact that `2880x1440@90` (total bandwidth LOWER than the
working 4320x2160@60) also always failed.

A separate research effort confirmed that this **is already a bug acknowledged by NVIDIA**: thread
`forums.developer.nvidia.com/t/.../337744`, internal bug **5923212**, reproduced on
RTX 2070S/3090/5070Ti/A5000 across drivers 590–610.43.02, always the same signature (60Hz works,
90Hz doesn't, even at lower resolution). No response from NVIDIA since 2026-03-20.

**Decision with the user: add this evidence to the NVIDIA thread instead of continuing with more
blind EDIDs.** Full draft of the post (in English, ready to copy/paste or edit)
at `docs/19-nvidia-bug-5923212-followup.md` — includes the table of the 7 factorial data
points, the chip identification (new to that thread, nobody had named it there
yet) and the open question for anyone with visibility into DPCD/MSA or the Windows
driver. **I did not post it** — it needs the user's forum account.

**Still to decide after posting:** whether to continue down the empirical path (the
`edid-tool.py` extension with `HBP:VBLANK@RATE` to separate exact-pixel-clock from
refresh/vblank is ready, not used yet) or whether to wait for a response from NVIDIA before
spending more reboots.

---

### Original instructions for the `80hz` reboot (already executed, kept for the record)

**STILL NEED THE REBOOT that loads `g2-vblank-4k-80hz.edid`.** Upon return:

1. `sudo ./scripts/verify-override.sh` — confirms loading (dmesg + md5).
2. Full PREFLIGHT (`docs/16`, at the very top), including `Notify Attach Begin` (root) —
   should say `pclk 1037820000 raster 4420x2935 24 bpp`.
3. `hmd-vk list` — `[1]` should report `80.000 Hz` (different from `[2]` at 60.000, this time
   with no index ambiguity).
4. Present `[1]` with `hmd-vk native 1`, headset on, HID (`panel-status.py`) in parallel,
   `testlog.py` to log it.
5. **If `80hz` WORKS:** besides "is there an image?", ask specifically **whether the
   flicker improved or disappeared** compared to 60Hz — that's the question that actually
   matters now that 90Hz is ruled out. If the flicker stays the same despite the
   image working, the lab's goal needs to be rethought from scratch (is the backlight strobe
   tied specifically to 90Hz by firmware, not to "any high refresh"?).
   **If `80hz` FAILS:** the vblank/time threshold is higher than estimated; go back to
   bisecting (at 60Hz, without bandwidth pressure) between 340 (fails) and 514 (works) to bound it
   before trying another intermediate refresh.

### Earlier this same session: the key was `DP-0`, not `DP-1`

Reboot done. `dmesg` confirmed `nvidia-modeset: Successfully read
/home/iam/Documents/reverb-g2/experiments/vblank/nvkms-override-candidates.conf` — no
warning, the bracket syntax from the previous section (below, untouched) was correct.
But the EDID at `/sys/class/drm/card0-DP-1/edid` was still the original `hmd.edid`.

The timing hypothesis was tested first (that a fresh `detect()` was missing since the
override loaded) by reading `cat /sys/class/drm/card0-DP-1/status` — that DOES trigger a real
`connector->funcs->detect()` (confirmed in `nvidia-drm-connector.c:274-283`, both the
`.force`/`.detect` callback fall into `__nv_drm_connector_detect_internal`). The entire
code chain was walked through by hand to confirm the plumbing exists end to
end: `nvDpyGetDynamicData` (`nvkms-dpy.c:3088`) → `GetEdidOverride` (`nvkms-dpy.c:195`,
which uses `nvDpyReadAndParseEdidEvo` with priority over `ReadEdidFromDP`) → back in
`nvkms-kapi.c:1544` the overridden EDID does get copied to `params->edid` because the
`overrideEdid` flag compared there is the DRM one (`connector->override_edid`, the one from
option 1, at `FALSE`) — not NVKMS's internal one → `nvidia-drm-connector.c:136` copies that EDID to
`nv_connector->edid` → line 301 calls `nv_drm_connector_update_edid_property`. The entire
path exists and should work. But status read `connected` with the old EDID
regardless.

**The real cause: an off-by-one between NVKMS and DRM in connector numbering.**
`nvkms-rm.c:880` — `AllocConnectorDispDataRec allocConnectorDispData = { };` — confirms that
`typeIndices` starts at 0. The first DP connector has `typeIndex = 0`, so its
internal name in NVKMS is **`DP-0`**. DRM, on the other hand, numbers from 1 (which is why the
actual listing in `/sys/class/drm/` is `card0-DP-1`, `card0-DP-2` — a `DP-0` never
appears). Same physical connector, two different names depending on the layer. `DPY_OVERRIDE_MATCHES`
(`nvkms-dpy-override.c:37-39`, `nvDpyEvoGetOverride` line 210) compares the `.conf`
key against NVKMS's **internal** name (`pConnectorEvo->name`), not against DRM's
— so the `DP-1` key never matched. The file was read without error because the parser
doesn't validate that the display name corresponds to a real connector; it just stores it in
the override table waiting for some connector to someday be named that.

`experiments/vblank/nvkms-override-candidates.conf` already has the corrected key:
`override.[0000:05:00.0].DP-0 = .../g2-vblank-test.edid`.

**Still need the reboot that tests the fix.** Upon return:
```
sudo dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read'
cat /sys/class/drm/card0-DP-1/status          # triggers a fresh detect()
sudo cat /sys/class/drm/card0-DP-1/edid | md5sum
md5sum experiments/vblank/g2-vblank-test.edid  # should match
```
If they match, the override loaded successfully — continue with the `docs/16` factorial. If they do NOT
match but there's also no warning in dmesg, the problem may be in the PCI
function number (`0000:05:00.0` vs `.1`, the GPU has two functions — VGA on `.0`, audio on `.1`;
`.0` is already set correctly) or in the `debug=1` not actually enabling the
`nvEvoLogDebug` log from `nvDpyEvoGetOverride` line 212 — check whether
`NVDpyOverrideRec found: DP-0` appears in dmesg, which would confirm the match unambiguously.

### Earlier this same session (historical, untouched)

Option 1 (`debugfs edid_override`) was ruled out with evidence — see `docs/16`, section
under "PENDING". The NVIDIA driver does not go through the generic DRM helper for this
connector's EDID; it reads it through its own channel, and the override is ignored.

Moved on to option 2 (`nvidia_modeset.config_file`). The first attempt (RE via disassembly,
no source) failed: `dmesg` gave a single warning —
`Syntax error in override entry: Unknown GPU designator: 0000:05:00` — and `nvKmsReadConf`
aborts the entire file on the first error, so even the other two candidates never got
tested.

**Found something better than RE: `/usr/src/nvidia-595.71.05/src/nvidia-modeset/src/nvkms-conf.c`
is real source (open part of 595, MIT).** The exact grammar is right there, no need to
reconstruct it blind:

- The key splits `keyhead` (`override`) from `keytail` at the FIRST `.` — everything else goes
  whole to `Subparser_override`. That parser only activates the PCI address branch when
  `key[0] == '['` (`nvkms-conf.c:126`). **The brackets are mandatory**, not optional
  notation — without them it looks for the first loose `.`, which falls in the middle of the PCI
  address, and throws exactly the error we saw.
- Real format: `override.[<domain>:<bus>.<slot>.<function>].<dpy-name> = <value>`
  (the `:` and `.` inside the brackets are the 4-field hex delimiters, same as
  `lspci`/DRM: `0000:05:00.0`).
- Value: absolute path with no quotes or `<angle brackets>` — the file branch only activates if
  `value[0]=='/'` after stripping quotes; the `<angle brackets>` from the first attempt are NOT
  stripped, they remain as a literal part of the value (which is why that candidate wouldn't have
  worked either even if the key had been correct).

`experiments/vblank/nvkms-override-candidates.conf` already has the corrected line:
`override.[0000:05:00.0].DP-1 = .../g2-vblank-test.edid`.

**The `DP-1` display name was confirmed by reading the code, not by assumption:**
`nvkms-rm.c:616-623` builds `pConnectorEvo->name` as `"%s-%u"` with a `typeIndex` counter
per type (0-based, RM enumeration order). `nvidia-drm-connector.c:562` calls
`drm_connector_init()` without an explicit `type_id`, so DRM assigns its own incrementing in
the same order NVKMS already enumerated — same counter, same physical list, same order →
DRM's `DP-1` (`card0-DP-1`, where option 1's `edid_override` had already confirmed
the headset hangs off) and NVKMS's internal `DP-1` are the same connector. No need to
change the name.

`/etc/modprobe.d/99-nvkms-override-test.conf` (`config_file=... debug=1`) still points to the
same `.conf`, so all that's needed is for the module to read it again — it's read-only at
runtime, only read once when the module loads.

**Still need to trigger the reboot.** Upon return, first:
```
sudo dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read'
```
If this time there's no warning (or it says `Successfully read...`), the override loaded
successfully. Only then verify physically: `/sys/class/drm/card0-DP-1/edid` should read as
`g2-vblank-test.edid` instead of `hmd.edid`, and continue with the `docs/16` factorial.

---

## Two independent tracks right now

1. **The vblank experiment** (`docs/16-lab-vblank.md`) — needs the lab OS booted natively.
   Blocked on an open question, see below.
2. **Monado upstreaming** (`docs/18-monado-upstreaming.md`) — needs nothing from the lab
   machine at all. Blocked on a GitLab account-verification issue on the everyday system's
   side. Do not waste lab time on this.

---

## Track 1 — vblank experiment: what to do first

**Before running PREFLIGHT, read the "PENDING" block near the top of
`docs/16-lab-vblank.md`.** While documenting this session I found and fixed a real error in
that doc: it claimed the EDID-override loading mechanism was "already proven in this lab".
It is not. The 6 bpc bug was closed with a *driver source patch* (0004), which sidestepped
ever needing NVIDIA to accept a fake EDID — so that claim was simply wrong, and following it
would have wasted lab time discovering there is no confirmed way to load the modified EDID.

**So the actual first task on the lab machine is resolving that**, trying in this order
(full detail now in `docs/16`, background in `docs/13`):

1. `/sys/kernel/debug/dri/*/DP-1/edid_override` (debugfs) — cheapest to try. Unconfirmed
   whether NVKMS's closed logic reads EDID through the generic DRM helper (would see this)
   or its own AUX channel (would not). Writing the file does not trigger hotplug — disconnect
   and reconnect the connector after.
2. `nvidia_modeset.config_file` — NVKMS's own mechanism, parameter exists and is compiled in,
   but the dpy-name syntax is undocumented. Discover it with `nvidia_modeset.debug=1` and
   reading dmesg as root during a real modeset.
3. Patching the EDID the headset itself reports over the cable, if there's an injection point
   between the Analogix bridge and the host — unexplored.

If none of the three works, the experiment is inconclusive by this route and needs a
different injection strategy before the factorial itself means anything.

### Once loading works: PREFLIGHT (5 checks, `docs/16`)

1. `grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' /proc/driver/nvidia/version` → must say `595.71.05`
2. `modinfo nvidia | grep -i license` → must include "Dual MIT/GPL"
3. `./scripts/verify-bpc.sh` → patch present
4. `lsusb | grep -E '04b4:6506|0bda:4c15|03f0:0580|04b4:6504|045e:0659' | wc -l` → must be 5
5. `dmesg | grep 'Notify Attach Begin' | tail -1` → must say `24 bpp`, not `18`

If any of the five fails, stop — measuring on the wrong driver gives a result that looks
good and points at the wrong thing.

### Then the experiment itself

Order: **CTRL → B → A**. If B works, that's the answer and A is just confirmation.
Verification is physical — put the headset on and look; the API reports 90.0 fps success
even with a black panel. For each mode: does the backlight come on, is there color or just
white/flicker, does `dmesg`'s `Notify Attach Begin` line say `24 bpp`, and the HID status
byte 18 (`scripts/decode-status.sh`).

The read-the-result table and the refresh-sweep follow-up are both in `docs/16`.

---

## Track 2 — Monado upstreaming: status

Four MR branches are ready (rebased on Monado `main` `735e29e4e`, adversarially reviewed,
three real defects found and fixed, zero warnings, DCO-signed, no AI co-author trailer per
the standing decision below). They live in the **everyday system's** clone
`~/Documents/linux_vr_base/monado`, refs `wmr-hid-resilience`, `wmr-controller-input-fixes`,
`wmr-camera-stream-toggle`, `steamvr-drv-origin-rpath`. Same content as
`patches/monado/0001–0010` in this repo.

**Blocked on GitLab account verification.** freedesktop.org's GitLab restricts new accounts
(anti-spam): they can't fork or create projects until an admin approves a request.
Filed as **issue #3736**
(`https://gitlab.freedesktop.org/freedesktop/freedesktop/-/work_items/3736`), open, no fixed
SLA. Check for a notification email, or ask to have it checked.

**Once approved:**
1. Add an SSH key to the GitLab account (can generate one in advance, same pattern as the
   lab machine's deploy key).
2. Fork `monado/monado`.
3. Push the four branches from `~/Documents/linux_vr_base/monado` to the fork.
4. Open four MRs against `main`. Titles and bodies are ready to paste, in
   `docs/18-monado-upstreaming.md`.
5. After each MR gets a number, add its `doc/changes/.../mr.<N>.md` changelog fragment as a
   final commit (path convention explained in docs/18).

---

## Idea to think about (2026-08-05, parked): scoped sudo + session auto-start

Came up while running the vblank factorial: the reboot → "I'm back" → PREFLIGHT →
present → look with the headset cycle has real copy-paste friction in the steps that need
sudo (already caused a bash history-expansion glitch when pasting output). Agreed to
request a scoped `sudoers.d` with `NOPASSWD` only for the read-only commands
(`verify-override.sh`, `dmesg`, the sysfs EDID `cat`, `modinfo`) — no blanket sudo
and no automating the `reboot` itself, because verification is physical: the user has to
be present as soon as the machine comes back anyway, so automating the reboot doesn't
save real time, and this is a single physical machine with no remote recovery if the boot
hangs. After that, the user proposed going one step further: having the Claude
Code session auto-start when the machine boots, to be able to interact as soon as it's back without the
"I'm back" step. **This was explicitly left pending to think about, not decided or implemented** —
pick it back up after running `g2-vblank-4k-90long.edid`. Full detail in memory
(`idea_agent_autostart_lab.md`, type `project`).

## Additional pending item (2026-08-05): GPU power profile

User hypothesis, not yet tested: on Windows it's always recommended to force the NVIDIA
panel to **"Prefer Maximum Performance"** for VR — leaving it at the default ("Adaptive",
dynamic clock) can cause problems. On Linux, the 595-open also boots into adaptive PowerMizer
by default. If the closed GSP firmware that decides the 90Hz lock (see
`docs/13-bug-6bpc.md`) is sensitive to the clock state at the moment of the modeset, a
downclock at the wrong moment could explain why the panel fails to sync.

Not investigated yet. When resumed: check the real P-state during the 90Hz modeset
attempt with `nvidia-smi -q -d PERFORMANCE` or `nvidia-settings`, and try forcing
maximum performance (`nvidia-settings -a '[gpu:0]/GPUPowerMizerMode=1'` or the
equivalent mechanism on the 595-open) before running the vblank experiment or in parallel with it.

## Pending (2026-08-06): comprehensive power management — system sleep + headset proximity sensor

Came up on the side, while a background transcode was running: automatic system
suspend (sleep) killed the process. It was worked around that time with a one-off sleep
inhibitor, but remains as a broader unresolved investigation — giving the user real control over
this machine's power saving so it doesn't kill background work by accident, and evaluating
whether or not automatic sleep should be enabled, and under what conditions.

Two related fronts, neither investigated yet:

1. **RESOLVED (2026-08-06, night).** System sleep (systemd) was killing background processes
   — root cause: it's not `logind` on its own (`IdleAction` unset in
   `/etc/systemd/logind.conf` or any drop-ins, default `ignore`), it's **PowerDevil (KDE Plasma)**
   requesting the suspend over D-Bus after its own idle timer, running with the
   compiled-in default because `~/.config/powerdevilrc` didn't exist. Confirmed in the journal: two
   suspend→resume cycles the same day (`16:09:04` and `16:51:48`). The one-off inhibitor
   (`systemd-inhibit ... sleep:idle` in `block` mode, used by `stereo3d-pack`) was already
   blocking it correctly, but as a per-job workaround, not as a fix. **Permanent fix
   applied:** `AutoSuspendIdleTimeoutSec=-1` in `[AC][SuspendAndShutdown]` of
   `~/.config/powerdevilrc` (created from scratch, didn't exist) — disables the idle-triggered
   suspend in the "Plugged in" profile, without touching `AutoSuspendAction`. Takes
   effect on this install's next boot; there was no Plasma session running here
   to hot-reload. The manual `stereo3d-pack` inhibitor still works the same way
   for one-off jobs, but no longer depends on remembering to use it.
2. **The G2's proximity/face detector was never gotten working.** The WMR stack exposes (on
   Windows) an IR proximity sensor that triggers automatic standby when the headset is
   taken off — not yet confirmed whether Monado reads it or ignores it in this driver. If it can be
   read, it would allow pausing the player and lowering consumption (GPU/panel) automatically when the
   headset comes off, without depending on the user remembering a manual command.

Goal: for this kind of behavior (power saving, automatic standby) to be under
explicit user control instead of running "half-baked" by default. Neither of the two
fronts has been investigated yet — noted for follow-up.

## Pending (2026-08-06): repurpose `test-powermizer-90hz.sh` — real efficiency (power limit vs. automatic regulator)

**Decision: the script is kept, not deleted** — it gets repurposed. Its original purpose (does
the 90Hz handshake fail due to a badly-timed PowerMizer downclock?) became obsolete once the
real cause of the 90Hz block was found (6bpc clamp, patch 0004). But the pattern it already
has (force `GPUPowerMizerMode` via `nvidia-settings`, measure, restore on exit) serves as a
starting point for a different and more general question.

**The phenomenon motivating this:** the user reports, measured more than once on Windows, that
capping the card's power draw in Watts (power limit) can achieve the SAME fps as the
automatic regulator (boost/adaptive PowerMizer) but with lower consumption — the automatic
regulator doesn't find that efficient point on its own. Cause unknown, not yet confirmed —
working hypothesis: the boost algorithm chases the highest P-state available on demand,
without optimizing consumption once the real fps is already capped by something else
(vsync/compositor), not by the GPU's raw throughput. Goal: reproduce and quantify
this on Linux, and decide the best power limit for this machine.

**Confirmed on this machine (2026-08-06), RTX 3060 Ti / driver 595.71.05-open, via
`nvidia-smi -q -d POWER`:** the power limit is indeed controllable here — range 100W-250W,
default/current 240W (`nvidia-smi --query-gpu=power.draw,power.limit,power.min_limit,power.max_limit
--format=csv`). Unlike the old script, this **does not need X11**: `nvidia-smi -pl
<watts>` works the same on Wayland — the original script's X11 requirement was only because
it used `nvidia-settings` to touch `GPUPowerMizerMode`, not because of the power limit itself.

**Two pieces needed before measuring seriously, per the user:**
1. **fps/latency** — already solved, the tools already exist (HID `DEVICE_STATUS`, compositor
   frame timing, `hmd-vk`).
2. **Being able to load the stack in a controlled way, so fps drops a bit below max** —
   does NOT exist yet. Without this, if the stack is already capped by vsync (ceiling = panel
   refresh), the GPU never gets to be constrained by its own throughput ceiling and the
   real power/performance trade-off can't be measured. Still need to decide how to generate that
   adjustable load — unexplored candidates: raising the compositor's supersampling resolution,
   adding a synthetic load multiplier to the player's shader, or running a second
   GPU-bound process in parallel (another `hmd-vk`/`vkcube`) to steal cycles in a measurable way.

**Method planned once both pieces are in place:**
- Sweep `nvidia-smi -pl <watts>` over a range (e.g. 100 to 240W in 20W steps).
- At each point, run the controlled load (#2) and log real fps/frame-time +
  real `nvidia-smi --query-gpu=power.draw` (not the log average, the instantaneous reading under
  steady load).
- Find the lowest power limit that sustains the same fps ceiling as the automatic
  regulator without capping — the "efficient point" the user already identified
  qualitatively on Windows.
- Compare against the automatic regulator at the same fps target, to quantify the gap.

**Not started yet** — the user explicitly left it to resume later. Do not touch
`test-powermizer-90hz.sh` until then (it stays as it was, X11-only, pattern
reference only).

---

## Standing convention decided this session

**No `Co-Authored-By: Claude` trailer on commits, and no repo-level AI disclaimer either.**
The `Signed-off-by` already certifies the content for publication; a tool-attribution note
adds nothing on top of that. Applies going forward to both this repo and the Monado series
(already applied there — the 10 patches and the reverb-g2 history were both rewritten to
drop it, and reverb-g2's rewritten history is already force-pushed to GitHub).

## Repo state

- Renamed `reverb-g2-linux` → **`reverb-g2`** (README explains why: the headset has no
  supported platform left on any OS, not just Linux). Working directory here is already the
  renamed one; GitHub remote is `Wintch/reverb-g2` (made public 2026-08-06 — this line
  predates that; see `docs/17-publishing.md`).
- `main` @ `301eaee`, matches GitHub, gate (`scripts/check-publishable.py`) passes clean.
- FCC PDFs dropped from the tree (linked to fccid.io instead); Oasis driver attribution fixed
  (it's Matthieu Bucchianeri's, not HP's); HP Omnicept noted as a related test target in
  `docs/10-resources.md` (same WMR display path per Monado's prober — a 90 Hz result there
  would show whether this is G2-wide or unit-specific) but not being pursued (no hardware).

> **Tooling addendum (2026-08-18 ~06:40, user-named)**: an fpsVR-equivalent — log
> compositor-side per-frame telemetry (app render time vs pacing deadline, re-shown
> frame events = "reprojection" count) so the felt micro-snaps have a first-class
> log, not just frame-pacing.sh sampling windows. User's HAGS parallel is apt: the
> measured one-slot-miss mechanism is scheduling-class, same feel as Windows HAGS
> stutter — the affinity A/B tests it directly.

> **ARkade storage line (user-directed 2026-08-18 ~07:30)**: demos must never lose a
> frame to storage. Infrastructure landed same hour: 10G tmpfs at /mnt/vrtmp (fstab,
> survives reboots), session CSVs live there (launcher auto-detects, SSD fallback),
> `down` + `VR_ARCHIVE_CSV=1` compresses to SSD else data evaporates (SSD write-cycle
> preservation), old logs purged 5.7G→1.4G. `scripts/vr-prewarm.sh` (agent-built):
> cache mode = page-cache warm via vmtouch (works from mechanical disks too — the
> cheap universal path), ram mode = rsync to tmpfs + symlink swap in steamapps/common
> (the hard guarantee, ≤12G titles). Games mapped on slow storage + prewarmed to RAM
> at pick time = the ARkade boot flow.
