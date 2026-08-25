# 67 — Everything pending, as one plan: Aircar "like on Windows" first, 6DoF in parallel (2026-08-22/23)

**Status: APPROVED by the user 2026-08-22 ~23:55, S1 started the same night.** This is the
plan of record; `NEXT-STEP.md`'s START HERE block points here. Sessions log to
`docs/pruebas.jsonl` as usual and update the per-topic docs named below **in the same commit**.

## 0. The question, and why it is not an either/or

The user asked: *"o llevamos un título a un estado 'como en Windows' o arreglamos 6DoF"* —
plan everything pending. Reading the whole record (docs/23, 03, 58, 59, 06, 60-63,
`docs/re-windows/`, all of `NEXT-STEP.md`, the scripts, the `~/vr/monado` tree) shows the two
options are the same plan viewed from two ends:

- **Titles that render hands** (Cyberpilot, Dead Herring, Sniper Elite, Google Earth…) are
  blocked, per title, by one of: the docs/58 controller-6DoF residual (worn presence 50-60 %,
  parked hands, 10-20 cm yaw-ghost shifts, hand inversion, right hand absent), an
  xrizer↔title binding bug (Sniper Elite: the driver tracks, `matched_blobs=6`, the in-game
  pointer never moves), one of the named xrizer gaps (Water Bears swapchain loop, Maquette
  chaperone, War Robots presence — re-opened by docs/23:129 in T243 despite NEXT-STEP:190's
  "validated"), or a title-private fault (Tank Mechanic: 405 `0xc0000005` exceptions).
  Cyberpilot in T244 ran 70-80 fps with a second client confounding it, and the wearer's own
  residual was *"the vertical readjustment is nauseating"* — head SLAM under load is not clean
  there either (anchor age ~150 ms + docs/58).
- **Titles that do not render hands** (gamepad class: **Aircar**, ISS Tour VR 8K) are the only
  ones where "like on Windows" is reachable without controller 6DoF — and Aircar is nearly
  there (89-90 fps, 0.13 % late, *"100 % funcional"*, T161/T163). Its residuals are head-SLAM
  residuals: roll drift on long 6dof sessions (+0.9°/min, gyro-bias-under-dynamics, WS2),
  origin anchoring where the headset sat (procedure: start worn, in play position; the A
  button recentres), 6dof pacing 7-11 % late vs 2.8 % in 3dof (T163; 4-7 % pinned with
  threads=4, T204) — **never measured under the T244 defaults** (the T243 retest was
  inconclusive: no gamepad plugged).

The two bugs that masked everything were closed in T244 and verified worn (45/30 fps ceiling →
patch 0092 + `U_PACING_APP_USE_MIN_FRAME_PERIOD`; relocation on every companion drop →
0093/0094). **No docs/23 verdict older than T244 stands without a retest.**

**User decisions (2026-08-22, 23:50):** the parity exam is **Aircar** (gamepad class);
Cyberpilot is the second exam; the Windows session (capture + baseline) happens **later** —
S2-S4 must not depend on it; S1 starts now.

## 1. Findings from the planning pass that the record had not connected

1. **Windows programs the controllers' LED pulse train; Monado sends no LED command at all.**
   `docs/re-windows/04-led-model.md`: `CrystalKeySetLedPulseTrain` (count 1-399, mode 1-4,
   period 1-5 ms, 55-bit duration, 11-byte body), and Monado's own
   `t_led_sync_refinement` is wired only to `pssense`. `NEXT-STEP.md:329` carried "NAMED NEXT
   INVESTIGATION: find what Oasis sends the controllers that we do not" — the static answer was
   in the repo and was never connected to it. Caveats that bound it: `re-windows/06` ranks it
   P4 (last) behind P1 (clock pops — partly covered by 0055/0093, to be reconciled) and P3 (the
   single shared reader loop, still the architecture; it is why one companion stall froze the
   USB3 cameras 14-24 s, WS6); and `04:261` says firing it from Linux is **unverified, static
   analysis only**.
2. **No existing Windows capture shows what Windows sends the controllers during tracking.**
   Checked with tshark on 2026-08-22: `windows-kit2/results/90hz.pcapng` (Oasis at 90 Hz,
   101 s, 45,663 frames) has **zero** controller-tunnel output reports (no `0x06`/`0x0E`), the
   host→HoloLens Sensors vocabulary is `02 {04,06,07,08,0b}` ×849 + one `16 04` — identical to
   pairing3's (T244). Device→host is the HMD IMU report `01` (381 B, 13,538), `02` (33 B), `17`
   (7 B, controller status), `05` (radio log), `03` (config reads). Controllers were off in that
   capture. So the LED lever needs a **new** capture with controllers on and tracking active, and
   it is **not** ported blind (T236/docs/54 rule). It sits behind the gain/exposure sweep, which
   needs no Windows and already has a datapoint (T223: gain 255 turned a 75 cm zero into 87
   poses of poor quality).
3. **`~/vr/monado` (`lab-full`) was two commits ahead of `patches/monado/`** (`c3843a24b`,
   `b5ba12f27`, the `wmr_camera_stop()` USB-thread join) — the T068 class of drift. Exported
   as **0095/0096** in S1 (README updated: 0096 notes the join was dead code until
   `cam->running` was set, and that a second, EGL-side teardown race remains).
4. **`vr-launcher.py` never called `game-stop.py`** — the second-client confounder was still
   armed at the launcher. Fixed in S1 (§6).

## 2. Acceptance criteria (measurable, with instruments that already exist)

| What | Criterion | Instrument |
|---|---|---|
| **Aircar "like on Windows"** | 6dof head, constellation OFF (its profile), Xbox pad; **≥ 30 min** worn; `Delivered frame` 88-90/s sustained; 3 pacing windows ≤ 3 % late (3dof control 2.8 %, T163); no relocation; recentres needed counted (target ≤ 1 per 10 min — no number under T244 yet); companion drops survived (0090); no core at `down`; audio in the headset; started from the picker hands-free | `scripts/app-fps.sh` (new, S1), `frame-pacing.sh`, `constellation-session-report.py` (channel health), `coredumpctl`, wearer |
| **Controller 6DoF "fixed"** (per hand, worn, arm's reach, 10-min window) | positional presence **≥ 90 %** (today 50-60 %); no "parked" > 1 s; no jumps ≥ 10 cm; jitter ≤ ~1 cm; both hands at once (today they invert) | `constellation-session-report.py`, wearer |
| **Tracking volume** | cliff ≥ 80 cm (today 50-75 cm); scale slope in [0.95, 1.05] | docs/59 (b)/(a) with the fixture |
| **Cyberpilot (2nd exam)** | Aircar's bar + controllers usable in-game + no nauseating vertical settle | same + wearer |
| **Better than Windows (one honest number)** | OpenVR Benchmark pass-1 vs pass-1 at 2576×2520 (Windows: 26.02 / 20.39 / 19.70, T226); docs/30 baseline (never run) | benchmark; Windows session |

## 3. Track A — tracking (head first, for Aircar; controllers in parallel)

- **A-head-1. Roll drift / gyro bias under dynamics** (T225's named lever and WS2's residual):
  run the turntable for its primary purpose (docs/38, never done for this); Basalt
  `gyro_bias_std`; a *stillness-detected bias update* for the controllers (WS3 idea, not
  built). Measure with `drift-measure.py`, `head-jitter.py`, recentres/10 min in Aircar. Serves
  Aircar AND the controllers' yaw ghost (heading noise floor 10-30° vs 11° LED spacing).
- **A-head-2. Seeded-recovery runaway guard** (100k+ attempts at 500 % CPU, seen live
  2026-08-21; docs/40's budget mechanism defaults off): bounded retries + backoff; validate that
  "SLAM starvation under load" (anchor age 745→4949 ms) drops — still OPEN and distinct from
  0093/0094. Code without the headset; validation under load.
- **A-ctrl-1. Tracking volume, no Windows needed:** fixture (docs/59 §1, string+knots, 15 min,
  user's hands) → **(c) gain sweep 100/150/200/255 scored by `agree_frac` first** (de-risk:
  if agree_frac saturates on gain/exposure alone, LED drive stops being the presumed
  bottleneck), (b) cliff map in 5 cm steps with 50 cm bracketing, (a) scale; plus the exposure
  sweep (`WMR_CONTROLLER_CAM_EXPOSURE_US`, 0083) docs/59 left out; the position/battery swaps
  of T229/T230 (a minute each). docs/59 rules: battery band 100-150, liveness before/after.
- **A-head-3. SLAM+constellation contention, NEW (2026-08-25) -- REAL ROOT CAUSE FOUND: a
  HARDWARE camera frame-type split, not a software scheduling bug. Two earlier hypotheses
  this same day (SLAM_THREADS undersized; verbose logging) are both now understood to be
  confounded/wrong; kept below for the record with corrections inline, not deleted.**

  **The actual mechanism (found by reading `wmr_camera.c`, confirmed quantitatively against
  7 sessions' `timing.csv`):** every camera frame carries a `frametype` field read straight
  off its header (`WMR_FRAMETYPE_SLAM=0x0` vs `WMR_FRAMETYPE_CONTROLLER=0x2`,
  `wmr_camera.c:411-413`), and `wmr_camera_frame_received()` routes each frame to EITHER
  the SLAM sinks OR the controller/constellation sinks (`if (slam_tracking_frame) {...}
  else {...}`, never both). This is the G2's own camera firmware alternating frame purpose
  within its ~30 Hz stream, not a Monado software decision -- SLAM structurally gets FEWER
  than 30 fps worth of frames whenever constellation is active, at the source, before any
  queue is involved. Confirmed by inter-frame-timestamp analysis: with constellation on,
  ~33ms gaps (consecutive SLAM frames) and ~66ms gaps (one controller frame diverted in
  between) both appear, at a **consistent 34-39% diversion rate across every real-Cyberpilot
  session measured** (34.3%, 37.7%, 38.8%, 29.2%, 39.4%) -- this directly explains the
  21.6-23.6 Hz pose rate seen all day (30 Hz camera × ~62-66% actually SLAM-tagged ≈
  matches exactly) without needing a software-contention story at all.

  **The ~50ms software "queueing delay" (`frames_pushed` -> `frontend_frames_received`) is
  a SEPARATE, smaller effect layered on top, and looks like a fixed per-diversion-event
  cost, not a scaling backlog:** comparing queue delay against diversion % across 7
  sessions, delay jumps from ~0ms (0.2% diversion) to ~47ms already at just 6.8% diversion,
  then stays flat at ~49-50ms all the way through 39.4% diversion -- it does not grow
  further with more diversion. Leading hypothesis (not yet confirmed in the actual
  synchronous-call code path, a good next step): controller-frame constellation/blob
  processing runs synchronously on the same camera-receive thread that also has to hand
  the NEXT frame to SLAM, so any diverted frame's processing blocks that handoff for a
  roughly fixed ~50ms, regardless of how often it recurs.

  **Correcting the day's own two intermediate hypotheses, in order:**
  1. *"SLAM_THREADS=4 undersized for constellation, bump to 6."* The zero-client
     `SLAM_THREADS=6` test that looked like a clean win (29.99 Hz, 0ms queue delay) had
     **0.2% frame diversion** measured after the fact -- the controllers were essentially
     not being tracked in that specific window, by chance, not because 6 threads fixed
     anything. Its own "4-thread control" (same zero-client setup, same thread-count-only
     variable intended) had 21.6% diversion and showed the delay -- the two arms were never
     actually matched on the one variable that matters. The real-game validation (6
     threads, human wearing the headset, 29.2% diversion, pose rate only 23.6 Hz, app
     pacing WORSE at 73.8% late vs 40-45%) remains the one trustworthy datapoint here, and
     it already correctly rejected `SLAM_THREADS=6` as a default -- that verdict stands,
     now for the right reason: more Basalt worker threads cannot manufacture SLAM frames
     the camera firmware routed to controller tracking instead, and under real GPU/CPU load
     the extra threads cost real app pacing for close to nothing in return.
  2. *"Verbose per-frame INFO logging (`WMR_LOG`/`SLAM_LOG` default INFO, `stdbuf -oL`
     write-per-line) could explain the ~50ms delay"* (the user's own hypothesis): tested
     `WMR_LOG=warn SLAM_LOG=warn` (20.4% diversion) against an INFO-default control (21.6%
     diversion) -- both landed at the same ~49.6ms p50 delay. This comparison WAS
     diversion-matched (both arms had real, similar diversion), so the refutation holds:
     logging I/O is not the mechanism, it's downstream of the same hardware-diversion
     effect described above.

  **CLOSED same day (A-win capture executed): the diversion is firmware-fixed, not a
  configurable request -- and there's a second, independent, bigger ceiling underneath it.**
  A live Windows USBPcap capture (`windows-kit2/results/frametype-capture-20260825.pcapng`,
  730s/55GB/690k packets, real Cyberpilot session) plus a 3-way parallel investigation
  (Linux source, the capture's control-transfer traffic, and a CPU-cost model from today's
  own `timing.csv`) converged cleanly:
  - **The camera streams at a fixed ~90 Hz raw rate on BOTH OSes already** -- confirmed two
    independent ways: `wmr_camera.c:398`'s own frame-footer timestamp math (`end_ts` ~111000
    ×100ns after `start_ts`, i.e. ~90Hz, already true on Linux, nobody had connected this to
    the SLAM-rate question before) and live measurement on the Windows capture (39,698
    camera-endpoint frames, median inter-frame delta 11.097ms = 90.09Hz). What's capped at
    ~30fps was never the raw camera rate -- only the SLAM-tagged fraction of it.
  - **No USB command sets or influences the `frametype` tag, on either OS.** The G2's
    camera command vocabulary is exactly three values (`WMR_CAMERA_CMD_{GAIN,ON,OFF}`,
    `wmr_camera.c:65-67`) -- confirmed exhaustive by decoding all 2,193
    Windows→device commands in the full capture: only those same three ever appear, same
    struct layout Linux already implements. Zero vendor-specific control transfers appear
    anywhere in the 730s capture; no USB Video Class descriptors; no alternate-settings
    bandwidth negotiation (the mechanism UVC cameras normally use for rate selection isn't
    present on this device at all). `wmr_source_enumerate_modes()`/
    `wmr_source_configure_capture()` are literal `WMR_ASSERT(false, "Not implemented")`
    stubs -- nobody has ever wired a mode-request path, and the capture confirms there is no
    such mode to request even if one were wired. **Verdict: hardware/firmware-determined,
    not a software knob, on either OS -- as close to a definitive "no" as this kind of
    investigation produces.**
  - **Second, independent, BIGGER ceiling found: Basalt's own frontend already can't keep
    up with the current rate.** Real numbers from today's `timing.csv` (two ~100-200K-row
    sessions, `SLAM_THREADS=4`): frontend total (frame-received to keypoints-pushed) is
    **p50 46ms** -- already 1.4x OVER the 33ms budget the *current* ~30Hz-tagged rate needs,
    and would be 4x over the 11.1ms budget a hypothetical 90Hz rate would need. The
    bottleneck (detection+matching, ~21ms of the 46ms) is confirmed **single-threaded in
    source** (`frame_to_frame_optical_flow.h`: only the LK-tracking half uses
    `tbb::parallel_for`; detection/matching are plain sequential loops) -- so more
    `SLAM_THREADS` cannot close this gap, consistent with and extending this same session's
    earlier `SLAM_THREADS=6` rejection. The backend also runs on every frame (not
    keyframe-gated), so it scales with input count too.
  - **Practical conclusion: retire the "chase higher camera rate" idea entirely.** It's
    closed on both the "can we" (no) and "should we" (frontend can't consume today's rate,
    let alone 3x) fronts. Accept 21-24Hz SLAM pose rate under constellation as the real
    hardware ceiling; put future effort into A-ctrl-1's exposure/gain sweep (may shift WHICH
    fraction gets tagged SLAM within the fixed 90Hz budget, not the frontend's ability to
    consume more) or prediction/filtering UX around the known rate, not the rate itself.
  - **One cheap, no-headset sanity check still worth running, not yet done**: a
    diversion-matched `SLAM_THREADS=8` or `12` A/B, diffing frontend total against today's
    4-thread baseline -- purely to confirm (not fix) the ~21ms detection floor is real
    before this whole line of inquiry is fully closed.

  Separately noted, different axis, not chased as a fix (but independently RE-CONFIRMED,
  see A-ctrl below): the right controller's constellation-vs-IMU orientation disagreement
  ran 160-176° (near-total flip) throughout, reproduced in this session too -- likely
  explains the wearer's own "controllers jump" complaint, feeds A-ctrl below, not A-head.
- **A-ctrl-2. Hand inversion + 1 cm jitter:** re-measure AFTER A-head-1/A-ctrl-1 (they may
  move on their own); if they persist, instrument (0089 already refuted blob competition).
- **A-ctrl-3. Correspondence assignment from the trusted heading** (T215, "major surgery"):
  only if the above does not close the ghost. Do not start earlier. **2026-08-25 update**:
  `scripts/constellation-frame-fit.py` (T181's tool) re-run with a fresh 90s wave-capture
  from today's session (user waving both controllers on request) -- well-conditioned fit
  (rotation-angle agreement p50 1.17°/1.13° left/right, 143/91 usable pairs), and it
  INDEPENDENTLY RE-CONFIRMS T181's original verdict: the LED-model-to-IMU transform is
  **~180° about the X axis on both hands** (179.6°/178.5°), not the factory `P_imu_me`
  (which disagrees by 137-139° from the fitted R -- neither 0 nor a clean match). Residuals
  are still large (p50 ~8°, max 121-160°) -- a single constant rotation does not fully
  explain the data, consistent with the code's own "bimodal, matching the two position
  clusters" comment; NOT solved, but the Rx180 answer itself is now on two independent
  datasets 12 days apart. Also anecdotal from the same session, worth a controlled retest:
  the wearer reported the right hand started "parked" (only left tracking) and both
  recovered together after ~20s of deliberately waving them in view -- a possible practical
  re-acquisition technique, not yet measured as a repeatable procedure.
- **A-win (single Windows boot): MOSTLY DONE 2026-08-25.** USBPcap capture executed
  (`docs/72`'s checklist, manual, all USBPcap interfaces, one merged 730s/55GB/690k-packet
  file, `windows-kit2/results/frametype-capture-20260825.pcapng`) with controllers on and a
  real Cyberpilot play session. Three of the original items now closed by mining this one
  capture (no new boot needed for any of them):
  - **Camera rate question (A-head-3 above)** -- answered, closed.
  - **Pulse-train command -- FOUND and decoded.** Report ID `0x08`/`0x10` (per controller,
    `+8` offset), 11-byte body via `SET_REPORT` output, confirmed by HID descriptor size
    match + rotating sequence field + count-field range + tracking-start/stop timing
    correlation. Full decode, exact frames, and honest open questions (an unexplained
    leading byte, `period_raw`/`duration` units) in `docs/re-windows/04-led-model.md`'s new
    "CONFIRMED LIVE ON THE WIRE" section. **Porting to `wmr` deliberately not attempted**
    yet -- the open questions above need closing first, or an explicit deliberate decision
    to try anyway.
  - **Magnetometer bytes -- CLOSED, not a magnetometer, high confidence.** The trailing 12
    bytes are firmware housekeeping counters (linear real-time ramps, motion-independent
    across stationary/waving/gameplay, correlation with gyro ≤0.02), confirmed on Windows
    too, not just Linux -- `docs/54` updated with the full byte-level evidence and closed.
  **Still not done**: docs/30's CPU baseline, battery calibration (T227), and OpenVR
  Benchmark pass-1 were explicitly NOT done this boot -- the user stuck strictly to the
  capture procedure ("solo respeté el procedimiento") and skipped the other checklist
  items. That's the only real gap left in A-win now; next Windows boot can go straight to
  those three, no more capture-mining needed first.

## 4. Track B — titles

- **B0. Launcher hygiene (no headset; prerequisite of any valid measurement):** DONE in S1 (§6).
- **B1. Aircar certification** (the exam): run #1 in S1 (30 min or what the session gives),
  run #2 soak in S3 after A-head-1/2; residual table in docs/23. Then **ISS Tour VR 8K** (same
  class, heavy content) once A-head-2 lands.
- **B2. Cyberpilot clean** (2nd exam): one verified client, constellation ON, both controllers
  registered, fresh monado; fps by `Delivered frame`, 3 windows, wearer; residual list
  (per-title deadzone; vertical latency → A-head).
- **B3. Sniper Elite VR — xrizer↔title binding** (frozen pointer with valid poses): `PROTON_LOG`
  + xrizer log, action manifest; new, cheap class, protects Cyberpilot.
- **B4. Named xrizer / per-title gaps** (docs/23:288-297): War Robots (retest with don/doff
  calibration first), Maquette `GetPlayAreaSize/Rect` (small fix), Water Bears swapchain loop
  (`compositor.rs:1247`), Tank Mechanic exception storm (isolate).
- **B5. Retest of the 45/30 fps list (16 titles)** under the new defaults: fast triage, fixed
  protocol (fresh monado, one at a time, `game-stop.py status` empty, `Delivered frame`);
  Hellblade deserves a full pass.
- **B6. OpenVR Benchmark** Linux pass-1 at 2576×2520 now (no Windows needed): our half of the
  first honest number.

## 5. Tracks C (session integrity) and D (debt), and the do-not-relitigate list

**C1.** `pop_pose` race #2 (EGL teardown vs camera thread; 21 cores): `thread apply all bt` on
the next cores; destroy the camera BEFORE the graphics teardown, or join before the compositor
is destroyed. Race #1 exported (0095/0096). **C2.** The 1-in-75 3 s `open()` stall: time
`companion_find_hidraw_path` and `os_hid_open_hidraw` separately. **C3.** USB2 link: docs/22's
free ladder in order; label this board's rear sockets (10 min, hands-on); rev2A cable
(`22J68AA` / SPS `M52188-001`) as step 7 of 7. **C4.** Periodic clean restart in unattended
mode (8 GB VRAM marathon hang). **C5.** Keepalive v2 (0058) >15-min A/B (never validated).
**C6.** Battery: cliff byte never observed directly; timed charge cycle; Windows cross-check
(A-win). **C7.** The single shared reader loop (re-windows/06 P3): 0055/0094 removed the worst
blockers, the architecture is still one loop; scope the thread split (companion vs sensors) —
the structural cause of WS6's "USB3 cameras stalled 14-24 s".

**D1.** Export 0095/0096 + README (DONE S1); strike "0090/0091 undocumented" (they are
documented); update docs/43 (up/dev/quiet/down is implemented); decide the 4 upstream MRs
(docs/18: never filed — file or park explicitly). **D2.** Dashboard: `dashboard-kiosk.service`
not installed (half-installed); `pmadminka` install or not; the non-Steam stub in
vr-launcher. **D3.** WS4 tooling (3-window harness, motion-to-photon; per-box `power.conf`
exists, GPU 70 %) — parked unless a free window. **D4.** Buy NiMH cells. **D5.** GPU offload
of the vision stages: scope before the freeze, do not start.

**Do not re-litigate (measured negative or retracted):** yaw prior (wrong instrument),
`SEED_FIRST`, 14° gravity gate, `WMR_HMD_GYRO_MOUNT_FIX` (never enable), `WMR_CLOCK_MIN_LATENCY`,
windowed skew tracker, `SEARCH_BUDGET_US=3000`, discrete keepalive (myth), "engine age" as the
fps-ceiling cause, `companion_errors` as a metric, the cable "ruled out" (that retraction was
itself retracted: the link storms the same on Windows). Magnetometer: not closed but **blocked
on a capture** (docs/54) — goes in A-win, no blind probing.

## 6. S1 — what was done on 2026-08-23, 00:00-00:30 (no headset yet)

- **D1:** `patches/monado/0095` (join the camera USB thread in `wmr_camera_stop()`) and `0096`
  (`wmr_camera_start()` never set `cam->running`, which made 0095 dead code) exported from
  `lab-full` with `git format-patch`; README sections added, including the warning that the
  EGL-side race #2 is not covered.
- **B0:** `scripts/vr-launcher.py` — `status`/`stop` subcommands; `check_no_game_running()`
  runs `game-stop.py status` BEFORE Monado comes up and stops (default after 10 s) / continues
  (`n`, for a deliberate two-client experiment) / aborts (`q`); `check_controllers_registered()`
  reads the first role list in `~/vr/jack-in-wayland.log` and says out loud when a hand is
  `<none>` (loud for hands titles, one line for `NO_HANDS_TITLES`) — it does NOT restart the
  service (chained restarts are a USB2-fault trigger); `TITLE_PROFILES` gained ISS Tour VR and
  OpenVR Benchmark (constellation off, no hands); the `GAMES` catalog gained the docs/23 rows
  that had never been copied (Cyberpilot, Sniper Elite, Vertical Shift, Hellblade, Interkosmos,
  Emergence, Blast the Past, Audio Factory, VersaillesVR, Steam 360 Video Player, Aperture Hand
  Lab, Transmissions, OpenVR Benchmark); `IPC_SOCKET` derives from `XDG_RUNTIME_DIR`/uid. Deployed
  flat to `~/vr/` together with `game-stop.py` (which was not there — docs/53's deployment class).
- **Launch-options audit:** `scripts/backup-steam-config.sh` re-run with Steam closed
  (snapshot `~/vr/backups/steam-20260823-000138`, `docs/steam-launch-options.md` regenerated):
  every installed VR title carries the base recipe (Aircar, DOOM VFR, Sniper Elite, Steam 360
  Video Player, Vertical Shift, Wolfenstein: Cyberpilot); BlazeRush still MISSING (known,
  docs/23); the catalog shrank from 46 to 15 installed since 2026-08-13 (the mass uninstall).
- **New instrument:** `scripts/app-fps.sh [window_s] [repeats] [log]` — counts `Delivered
  frame` lines per second from Monado's log (needs `U_PACING_APP_LOG=debug` on the service;
  ambient wins over `VR_PACING=1`'s `info`). It is the honest app-fps number frame-pacing.sh and
  the Steam overlay cannot give (docs/32, T244).
- **Machine state at that hour:** `vr-power-setup.sh report` shows the box **unpinned after the
  reboot** (governor `powersave`, EPP `balance_performance`, ASPM `default`, GPU 240/250 W);
  `--apply` needs root and is the first thing before any B1 measurement.

## 7. S1 — B1 Aircar run #1 (2026-08-23 00:11-00:41, T245)

Through the real path (`VR_LAUNCH_APPID=1073390 vr-launcher.py 1 6dof`, pinned machine, GPU 70 %
cap, constellation OFF, Xbox pad), wearer on 13.5 min in a **dim** room, then resting.

| Criterion | Result |
|---|---|
| `Delivered frame` 88-90/s sustained | **MET** — 89.5/79.1/85.2 loading, then 88.9-90.05 in four 3×20 s windows |
| 3 pacing windows ≤ 3 % late | **MET** — 0 late frames in 6×30 s |
| Companion drops survived | **MET** — 1 reconnect (3.3 s), 0 holes |
| Started from the picker hands-free | **MET** (the new `VR_LAUNCH_APPID` path) |
| No relocation / recentres ≤ 1 per 10 min | **NOT MET** — 3 VIO runaways in the first 75 s seated (two auto-reset, one parked the raw pose at 41 m), walks read as tens of metres, wearer recentred with A; seated drift 0.33 m/min |
| No core at `down` | **NOT MET as "clean"** — no core, but `down` hung > 10 s → SIGKILL (docs/06) |
| ≥ 30 min worn | not reached (13.5 min worn + resting) |

New facts: the 70 % GPU cap is **active the whole time** (174 W, ~1.8 GHz) yet fps holds — no
longer "free" as in T209 (the app now renders 90, not 45); SLAM was **not starved** during the
runaways (300 frames/10 s, 40 ms) — the dim room is the variable (docs/56 addendum); after t+340 s
SLAM ran at 26 fps / ~100 ms (optflow threads 100/80/80/80 %, machine 37 %); the 10 m/s auto-reset
let a 3.8 m/s runaway through; resting produced a reset storm from 00:30:12 — the wearer
handled the headset at ~00:30 (his own timing), so not a spontaneous storm. **Next for B1:** run #2 in normal light, ≥ 30 min worn (S3), and the in-session light
A/B the user deferred tonight; the startup low-light warning moves to the front of A-head.

## 8. B2 — Cyberpilot run #1 (2026-08-25, extended session)

Reinstalled to the NVMe/NTFS library specifically to size-qualify for `vr-prewarm.sh` ram mode
after the same-day 32G RAM upgrade (tmpfs 10G→20G, cap 12G→16G). Hit and fixed two real bugs
first (full detail in docs/23's Cyberpilot row): the NTFS `dosdevices/c:` Errno 22 (docs/70's
bug, on this title's Proton prefix) and `bench-launcher.py` needing a new `--controllers` flag
to combine `WMR_SLAM=1` with `WMR_CAMERAS=1 WMR_CONSTELLATION_CONTROLLERS=1` (the `--tracking`
enum alone can't). Manual launch (`jack-in-wayland.sh` directly, human wearing the headset each
time — required: the real XR session only opens once the wear sensor fires, which is why every
unattended `bench-launcher.py` attempt saw only a harmless instant capability-probe session and
never the real one).

| Criterion (from §2's acceptance table) | Result |
|---|---|
| Same bar as Aircar (constellation ON here, unlike Aircar's OFF) | fps converges to Aircar-like 89-90 once loaded + unfocused; SLAM+constellation together (a first for this project) costs real pacing headroom — 40-45% late frames both prewarm arms, vs Aircar's 0% in the same table's B1 run |
| Controllers usable in-game | **MET, with the known residual** — wearer: "the joysticks let me manage okay overall," first (dog) mission genuinely playable after in-game control/render-scaling tuning; position tracking "isn't perfect... they jump" — docs/58's already-known controller-jitter residual, reconfirmed, not new |
| No nauseating vertical settle | **Not reported this session** (T244's Cyberpilot residual) — wearer's complaint this time was head-movement judder, not vertical settle; plausibly the same pacing/late-frame cause, not measured as a separate axis |
| One verified client, fresh monado | MET — `game-stop.py status` checked clean before each of the 3 launches this session |

**New, unplanned finding, promoted to a general testing rule** (memory:
`feedback_windowed_default_fullscreen_ab`): window focus state, not just fullscreen/windowed,
swings fps hugely — fullscreen+focused locks a hard 30.00 fps ceiling (`Fake pacer fell behind`
spam), windowed+focused is noisy 60-89, any unfocused state runs clean ~90 when idle. Default to
windowed, A/B fullscreen per title going forward — do not assume Cyberpilot's numbers transfer.

**Cache vs ram, the original question this reinstall was for**: ram mode wins on load (first
frame ~22s vs cache's ~28s from a genuinely cache-cold state; clean fast climb to steady 90fps
vs cache's noisy climb that dipped to 36fps mid-ramp) but the two converge once steady and
unfocused (~62-66fps either way, in real gameplay, not menu) — prewarm buys the transition, not
steady-state, matching T246's Aircar precedent.

**Next for B2**: the vertical-settle question specifically (T244's original Cyberpilot residual)
wasn't re-asked this session — the wearer's spontaneous report was head-movement judder instead;
worth asking directly next time. The 40-45% late-frame rate with SLAM+constellation together is
now this project's first real datapoint on that combined cost and belongs in Track A's pacing
work, not just this title's row.
