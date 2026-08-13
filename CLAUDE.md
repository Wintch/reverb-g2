# Context for the 90Hz lab agent

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
