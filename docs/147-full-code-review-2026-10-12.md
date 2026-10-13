# 147 — Full code review, 2026-10-12

A read-only review of everything this project wrote: the scripts, the patch series, the Monado
fork branch, the loose workspace scripts and the lab automation kit. Nothing was fixed during the
review. This doc records the scope, the method and its limits, the results per area, and the fix
plan. The per-finding reports (evidence, failure scenario and suggested fix for every entry) are
kept **outside this repo** on the everyday box, because their raw data quotes private identifiers;
see §8.

Status: review CONCLUDED. Fixes: none applied yet. Owner decisions pending: §6.

## 1. Scope

| Included | Size |
|---|---|
| `scripts/`, `tools/`, `windows-kit/`, `web/`, `experiments/` (~250 files: shell, Python, C, PowerShell, systemd/udev/nginx/wireplumber config) | ~39k lines |
| `patches/monado` (113 numbers in 112 files), `patches/xrizer` (13), `patches/basalt` (20 numbers in 19 files), `patches/nvidia` (4), `patches/hello_xr-player` (22), `patches/hare-ware-test` (1) | ~41k patch lines |
| The Monado fork branch `companion-hot-reconnect` (the !2967/!3004 work: 8 commits, +522/-30 in `drivers/wmr`) | — |
| Loose scripts in the workspace root (older copies of `jack-in.sh`, `get360.sh`, `play360.sh`, `controller-pair*.py`, a udev installer, the NVIDIA PR helpers, Ghidra scripts) and the lab automation kit (agent runner, sudoers allowlist, backup and rollback) | — |
| Eight cross-cutting sweeps over all of the above: privacy and secrets, English-only rule, duplication and drift, hard-coded paths, privilege and destructive operations, docs vs code, deployable system config, environment knobs | — |

Not reviewed: the upstream projects themselves; `docs/` prose except where a sweep or a docs-vs-code
check reached it; the ~900 added lines on `lab/lab-full` that have no exported patch (presence
and auto-standby subsystem among them, §7).

## 2. Method

78 review units in five batches, run one batch at a time with the maintainer's go-ahead between
batches. Every unit went through the same pipeline:

1. **Find.** Three independent finder agents per unit, each with one lens. Scripts:
   correctness / runtime robustness / safety-portability-maintenance. Patches: correctness /
   concurrency-robustness / upstream quality. Cross-cutting units: a pattern-driven sweep and a
   reading-driven sweep.
2. **Verify.** Three verifiers per unit (two for cross-cutting), each trying to refute every
   finding through a different lens: literal reader (is it in the code as described), runtime
   realist (does the project ever hit it), repro constructor (build a concrete trigger; run it if
   it is a pure function). Majority vote decides confirmed / dropped / uncertain; verifiers may
   correct the line and the severity.
3. **Refute.** Every confirmed critical or high finding (up to four per unit) went to two
   adversarial refuters, plus a tie-breaker on a split. Survivors are **headline**; the rest are
   **contested**.
4. **Synthesize.** One report per area, plus a completeness critic per batch that spot-checked
   files, re-ran some claims and listed what the pipeline missed.

All agents ran on Sonnet. Mechanical baseline, run first and handed to every agent:

| Check | Result |
|---|---|
| Python AST parse (105 files), `bash -n` (105 files) | no syntax error |
| JSON / TOML / JSONL validity (51 tracked data files) | all valid |
| flake8 (pyflakes class) | 35 hits, all unused imports, f-strings without placeholders, unused locals |
| shellcheck `-S warning` | 49 warnings, 0 errors |

Patch-series apply check, cumulative `git am` on each pinned base:

| Series | Base | Applies |
|---|---|---|
| Monado | `735e29e4e` | 76 of 112 files (2 of them via 3-way); 36 fail — two lineages are mixed (README boxes) |
| xrizer | `6c3e45f` | 13 of 13 |
| Basalt | `df6e970` | 19 of 19 files |
| NVIDIA | `595.71.05` | 4 of 4 |
| hello_xr | `c610211f38f4` | 9 of 22; first failure at 0004 (cause in §5.4) |

Cost: 525 agents, about 40M subagent tokens, roughly 8 hours of wall clock across the batches.

## 3. Results by area

| Area | Entries | High (headline / contested) | Medium | Low | Dropped by verifiers | Approx. distinct |
|---|---|---|---|---|---|---|
| Launch sessions (launchers, preflight, cockpit, boot selector) | 154 | 3 / 1 | 18 | 132 | not kept (v1) | — |
| Devices (USB, controllers, audio, EDID, NVIDIA diagnostics, C tools) | 213 | 3 / 0 | 23 | 187 | not kept (v1) | — |
| Tracking analysis (SLAM, soaks, drift/jitter, A/B kits) | 324 | 1 / 1 | 40 | 282 | 32 | ~211 |
| Steam, player, dashboard, bootstrap, windows-kit, loose scripts, lab kit | 545 | 3 / 5 | 85 | 452 | 52 | ~357 |
| Monado patch series | 350 | 4 / 1 | 36 | 309 | 51 | ~243 |
| xrizer, Basalt, NVIDIA series and the Monado fork branch | 142 | 0 / 0 | 11 | 131 | 23 | ~96 |
| hello_xr player series | 136 | 0 / 2 | 19 | 115 | 23 | ~86 |
| Cross-cutting sweeps | 327 | 6 / 0 | 81 | 240 | 3 | ~172 |
| **Total** | **2191** | **20 / 10** | **313** | **1848** | | **~1450** |

No finding is critical. Entries overcount defects because several lenses report the same bug.
The 20 headline entries are 10 distinct defects; the six sudoers entries are one of them.

What held up: the two daily launchers carry their safety nets and draw only edge-case findings;
`controller-pair-v2.py` has only low findings; the quaternion, Lie-map, SLERP and timestamp-shift
arithmetic in the analysis tools drew no dispute; the companion-reconnect patches behind !3004
(0090, 0093, 0094) drew 9 lows; NVIDIA 0004, the 90 Hz fix, drew nothing substantive; the EDID
injector's byte arithmetic checks out against EDID 1.4.

## 4. Headline defects (survived verification and the refute panel)

| # | Where | Defect | Fix size |
|---|---|---|---|
| 1 | lab kit sudoers allowlist | The NOPASSWD entries point at scripts inside the agent user's own home tree, which the agent can edit and `git pull`s before running them; one diagnostic entry also accepts arbitrary arguments. The "scoped allowlist" is root-equivalent for that user. Whether the file is installed on the lab box today was **not checked** (needs `sudo -l` there, §6). | small: root-owned copies or digest pins, exact argument forms |
| 2 | `patches/monado/0095` | `wmr_camera_stop()` joins a USB thread parked in a condition wait nobody signals, so every camera teardown hangs until the launcher's SIGKILL at 10 s. | prepared: `docs/upstream/wmr-camera-stop-drain-0001/0002`, drop 0096 with it |
| 3 | `patches/monado/0035` | Skipping fusion on zeroed idle packets leaves the fusion clock stale, so the first live packet after a controller wakes integrates the whole idle gap (10 to 136 deg in the refuters' replays). With the never-released yaw lock a hand can stay wrong until restart. | small |
| 4 | `scripts/vr-cockpit.py:300` | Monado prints an empty device slot as `<none>`; the code compares with `none`, so an unregistered controller reads as registered and the panel says GO. | one line |
| 5 | `scripts/vr-cockpit.py:264` | Patch 0073 changed the battery log line to `raw byte [<name>]:`; the regex still expects `raw byte:`, so the battery readout and the low-battery warning never fire. Patch 0080 broke `constellation-gate-validate.py:31` the same way. | one line each |
| 6 | `scripts/jack-in.sh:242` | `reassert_monitors` passes `--pos 1920+0`; xrandr rejects it and stderr goes to `/dev/null`, so the layout re-apply never happens. | one line |
| 7 | `scripts/collect-nv.sh:98-105` | A comment inside a backslash continuation splits the `sudo -u ... env` command: `hmd-vk` runs as root without the session environment and the 60/90 Hz capture comes out empty. | move two lines |
| 8 | `scripts/apply-bpc-patch.sh:78` | `dkms remove --all` before an install that can fail, no rollback: a failed rebuild leaves the box with no nvidia module. Also double-applies 0004 where `dkms.conf` already carries it. | retire in favour of `bootstrap-lab.sh patch-nv`, or build before remove |
| 9 | `scripts/hare-ware-ab/ab-analyze.py:254` | The builder token is parsed as `wmr:` (Monado prints `Using builder %s: %s`), so every valid leg is flagged `WRONG_BUILDER ... run is void`. **docs/143's published tables do not depend on this flag** (they come from raw log lines), nor on `HMD_READ_THREAD_DEAD`, which also fires on a clean shutdown. | two lines |
| 10 | `patches/hello_xr-player/0004`+ | Spanish user-visible strings in 0006 and later, and a partial translation of 0001-0005, break the series: four text pre-images in `playercontrol.cpp` no longer chain, which explains all 13 apply failures. Repairing those four makes all 22 apply. | one translation pass, re-export |

Contested (the panel refuted them; reasons in the area reports): the session-anchor guard
re-firing (0099; the panel warns not to fix the stale-pose race in 0057 before re-measuring
it), the dashboard's nginx proxy exposing unauthenticated POST actions to the LAN (no
code-execution path found), the hard-coded Steam account ids in `steam-library-vr-map.py`, the
world-writable udev rules of the old workspace installer, a hard-coded desktop layout in
`solo-hmd-test.sh`, two hello_xr fork-design choices, a PowerShell switch-name claim (wrong on
the facts), the fan monitor's tight loop under `nohup`, and `bench-launcher.py`'s VR-root
fallback.

## 5. Recurring defect classes

1. **Instruments that fail green.** Gates and monitors that print OK, PASS, `0 trips`, `fps=0.0`
   or "registered" when they measured nothing: `verify-bpc.sh` exit status, the `speak.sh`
   silence switch (`jq // true` turns `false` into `true`), `reseat_audio.py`'s panel-lit test,
   `soak-variant.py` passing a soak whose player died, `hw-monitor.sh` (`grep -c connected` also
   counts `disconnected`), `fs-backup.sh` reporting success with no archive. A false pass is
   worse than a crash here, because `post-update-verify.sh` and the analysis docs treat the
   output as evidence.
2. **Cleanup that never runs, or runs on what the script does not own.** Python's default SIGTERM
   skips `finally` (`bench-launcher.py` leaves the power watchdog stopped and the GPU capped);
   EXIT traps installed before a "refusing: a game is running" guard tear down the live session
   they refused to touch (`light-preflight.sh`, `gpu-pacing-baseline.sh`); root-hub unbinds and
   companion de-authorizations with no trap; `playlist-runner.py` kills only the wrapper and
   orphans the player.
3. **Parsers coupled to log text that later patches changed** (#5 above, plus
   `constellation-gate-validate.py`, `constellation-session-report.py`, `ab-analyze.py`). A check
   that greps `scripts/` for every log string a patch changes would catch the next one.
4. **The exported series is not the tree that runs.** 36 Monado patch files fail on the pin;
   `bootstrap-lab.sh sources` stops at Monado 0016 and hello_xr 0004 and never applies Basalt or
   xrizer; several fixes live only on lab or MR branches; about 900 lab-branch lines have no
   exported patch.
5. **The same `grep -c ... || echo 0` bug** (prints `0` twice on no match, then the arithmetic
   fails) in `led_hunt.sh` and `triage-sweep.sh`; `record-euroc.sh` waits for a non-empty go file
   while its prompt says `touch`.
6. **Stale forks and copies.** `jack-in-wayland-tracing.sh` is ~400 lines behind production and
   its default mode cannot succeed; the loose workspace copies of `jack-in.sh`, `get360.sh`,
   `play360.sh` and `controller-pair.py` drifted from the repo; `controller-pair-btlog.py` sends
   a PAIR command on import.
7. **Environment knobs parsed five different ways** across Monado, Basalt, xrizer and hello_xr
   (presence-only enable, `0/f/F`, `atol` without an end pointer, panic on a bad float);
   0058's CPU-list parser pins the README's own example `1-5,7-11` to `{1,7}`.
8. **English-only rule.** 47 findings: Spanish output, spoken prompts, data keys, the
   `docs/pruebas.jsonl` filename, patch strings (#10 above).
9. **Public-repo hygiene.** Tracked docs, data and patch headers still carry per-device and
   per-account identifiers, and the repo's own `check-publishable.py` fails on HEAD and cannot
   see some encodings. This is the open docs/91-92 workstream; the per-item list stays in the
   private report on purpose. The exported xrizer 0013 also carries a tool session-URL trailer.

## 6. Decisions for the maintainer

1. **Lab sudo.** Check `sudo -l` on the lab box to see whether the allowlist is installed, then
   decide the threat model (single-owner lab vs an unattended agent that pulls from the network).
2. **Privacy scrub of HEAD and history** (docs/91 plan): including whether the Bluetooth
   controller bond should be treated as burned and re-paired.
3. **Licensing.** xrizer is GPL-3.0-or-later, and its 13 derivative patches sit under this
   repo's blanket MIT `LICENSE` with no carve-out.
4. **Which Monado lineage is authoritative** for `patches/monado`, so the series can be
   re-exported and `git am`-tested end to end.
5. **NVIDIA 0003:** drop it, or re-key it to `0x0E22` plus product `0x36C1` (DPLib reads the
   manufacturer id little-endian, so the current `0x220E` case is dead code).
6. **The uncommitted edit in `scripts/jack-in-wayland.sh`** (hard-coded VR root for the
   everyday box): revert it or turn it into an opt-in override; it must not be committed as is.
7. **The fate of `jack-in-wayland-tracing.sh`:** a thin wrapper over production, or delete.

## 7. Limits of this review

- **Nothing was compiled or executed** beyond pure-function snippets and the critics' spot
  checks. "Confirmed" means three readers agreed, not that the behaviour was observed. The
  critics found defects the readers missed, the clearest being an `int` overflow in 0087
  (`30 * U_TIME_1S_IN_NS` wraps, so the presence stale-channel check is dead code; docs/103
  lists the resulting `-Woverflow` warning as pre-existing) and a shutdown use-after-free in
  0027 that the verifiers left uncertain.
- **Same model throughout.** Finders, verifiers and refuters are all Sonnet reading the same
  text, so their agreement is correlated; the refute panel overturned 10 of 30 highs, and
  severities mostly moved down (to "does the lab hit this"), so severity ranks fix order better
  than it ranks risk.
- **Batch 1 used a coarser de-duplication** (same file within three lines), which merged at
  least 13 distinct defects into others and did not keep the dropped findings; batches 2-5
  used the corrected script.
- **Lab-box premises are unverified**: the installed sudoers and systemd units, the Steam
  library layout, the deployed `~/vr` copies.
- **Coverage gaps:** the Rust series was never type-checked (`cargo` exists on the everyday box
  but the vendored crates are missing offline); the NVIDIA review covered the 595 lineage, while
  the active branch is the 615 one; ~900 lab-branch lines have no exported patch; the large
  tracking patches (0076, 0077, 0061-0071) drew few correctness findings for their size;
  `analyze-panel-judder.py` was never run against known answers.

## 8. Where the full reports are

On the everyday box, outside every repo: `~/Documents/linux_vr_base/code-review-20261012/`.
`INDEX.md` has the totals and every finding still rated high; one `<area>.md` per area has the
executive summary, every finding with evidence and fix, the recurring patterns, a suggested fix
order and an appendix of dropped findings. The `<area>.json` files are the raw pipeline data;
they quote private identifiers verbatim and must never be committed to a public repo (they are
mode 0600). `tooling/` keeps the workflow script, the unit manifest and its builder, the
apply-check script and the lint baseline, so a unit or a batch can be re-run after fixes;
the folder's `README.md` explains how.

## 9. Suggested fix order

1. Lab sudo allowlist and the rollback path (playbook restores into a nested directory;
   `fs-backup.sh` fails green). Do both before the lab agent runs unattended again or before the
   next DKMS change.
2. The one-line instrument fixes: #4, #5, #6, #7, #9, `speak.sh`, `hw-monitor.sh`, `led_hunt.sh`,
   `record-euroc.sh`, `triage-sweep.sh`; repair the duplicate T237/T238 rows in
   `docs/pruebas.jsonl` and the id allocation in `testlog.py`.
3. Monado: swap 0095 for the prepared drain patches and drop 0096; re-prime the controller
   fusion clock after idle (0035); fix the 0097 neck-arm sign (it ships in the Aircar and
   Cyberpilot profiles) and re-run the wearer A/B; fix the 0087 overflow.
4. `apply-bpc-patch.sh` (retire) and `bootstrap-lab.sh` (curated patch lists, build before
   `dkms remove`, Basalt and xrizer steps), so a from-scratch install is truthful.
5. hello_xr: one English translation pass that repairs the four pre-images, then the recenter
   sign (0005), the seek path (0004, 0006) and the audio clock (0021).
6. Signal and trap hygiene across the stateful tools (class 2), then the stale fork and the loose
   copies (class 6).
7. NVIDIA 0002 lease hook (a `drm_master` reference leaked per lease, lock order against the
   revoke path, a flip-permission flag only an explicit revoke clears), then the xrizer input and
   frame-timing items.
8. Mechanical sweeps: English-only strings, hard-coded paths, one env-knob helper per codebase.

## 10. Fix status (updated 2026-10-13)

"Verified" below means what was actually checked on the everyday box, except where a row says
"rig". On 2026-10-13 the Monado, player, xrizer and NVIDIA changes were built on the lab box
(details after the table); only the Monado camera teardown has run on hardware so far.

| # | Item | Commit | Verified |
|---|---|---|---|
| §4 #4, #5 | `vr-cockpit.py` reads `<none>` as unregistered and parses 0073's tagged battery line; `constellation-gate-validate.py` accepts 0080's gravity-gate tag | 3ec9e6b | synthetic logs |
| §4 #6 | `jack-in.sh` passes `--pos XxY` | 3ec9e6b | `bash -n`; xrandr syntax |
| §4 #7 | `collect-nv.sh`: comment moved out of the continuation; no other instance in the repo | 3ec9e6b | `bash -n`, repo scan |
| §4 #8 | `apply-bpc-patch.sh` retired (stub that exits 1); `bootstrap-lab.sh patch-nv` builds before it installs over the old module | 3ec9e6b, 38e9bf7 | `bash -n` |
| §4 #9 | `ab-analyze.py`: builder token without the colon; read-thread exit at shutdown is not a death | 3ec9e6b | synthetic clean and dead logs |
| §5.1 | `verify-bpc.sh` exit status (0 only for 8 bpc and a live hmd-vk), `speak.sh` silence switch, `hw-monitor.sh`, `led_hunt.sh`, `triage-sweep.sh`, `record-euroc.sh` prompt, `testlog.py` ids (T246/T247 renumbered) | 3ec9e6b | jq and grep cases, testlog list |
| §9.1 | `fs-backup.sh` fails loudly and also archives `/var/lib/dkms/nvidia*`; the playbook restores with `tar -C /mnt/lab` and runs depmod/initramfs (linuxlab-kit) | linuxlab-kit df0c9cb | `bash -n` |
| §4 #2 | Monado 0095/0096 replaced by the camera drain pair, adapted to the pin | a866812 | applies; `-fsyntax-only`; 0097-0113 apply as before |
| §4 #3 | Monado 0114: fusion clock restarted after an idle run | a866812 | `-fsyntax-only` |
| M14-1 | Monado 0115: neck-arm sign (docs/80's ruling-out corrected) | a866812 | ratio -1 to +1 on random rotations through the correction code |
| §9.3 | Monado 0116: 0087's stale-presence notice (int overflow) | a866812 | gcc `-Woverflow` gone |
| §5.4 | `bootstrap-lab.sh sources` applies `patches/<series>/applies-on-base.txt` (new `check-series-apply.sh`), can be re-run, applies Basalt, adds xrizer; deps/nvidia statuses checked | 38e9bf7 | apply lists generated and replayed on fresh clones |
| §5.1 | `teardown-stress.sh` fails on a SIGKILL escalation, a missing client or a core | 38e9bf7 | `bash -n` |
| §4 #10 | hello_xr series re-exported in English: all 25 apply; 0023 recenter sign, 0024 seek while paused and frame-accurate, 0025 audio clock hand-back | ced9684 | applies on the pin; `ninja hello_xr` builds |
| §5.2 | Traps and ownership: `light-preflight.sh`, `gpu-pacing-baseline.sh`, `bench-launcher.py`, `playlist-runner.py`, `usb-companion-reset.sh`, `usb-bus-reset.sh`, `capture-hid.sh`, `power-on.py` self-repair, bootstrap WirePlumber step | 741568c | `bash -n`, process-group kill test |
| §5.6 | `controller-pair-btlog.py` no longer pairs on import | e2c92b8 | syntax |
| §9.7 | NVIDIA 0002: lease hook puts the master and takes locks in the revoke path's order | 4690a0c | `make modules` on 595.71.05, kernel 6.12 |
| §9.7 | xrizer 0014-0017: 0013 had broken upstream's `load_actions_race` test (fixed); repeated manifest no longer restarts the session; timing ring; refresh-rate fallback; hold-time parsing | 505c075 | `cargo test --lib`: 88 passed |

**On the rig, 2026-10-13.** The lab box's checkouts were behind: `reverb-g2` by 12 commits
(fast-forwarded, clean tree) and 18 of the `~/vr` script copies (each one an older repo version
or, for `parse-metrics.py`, a superseded draft; backed up to `~/vr/backups/deploy-20261013/`,
then refreshed; `deploy-check.py` clean). Each fix went onto a new branch, so the old state is one
checkout away:

- **Monado:** branch `review-fixes-20261013` on the rig's `lab-full` (ff6db76f6, 2026-10-04,
  newer than the 09-14 snapshot the local branch used). The 6 commits applied cleanly, it builds,
  and this is now the binary in `~/vr/monado/build`; the previous one is in
  `~/vr/backups/monado-lab-full-ff6db76f6-20261013/`. `teardown-stress.sh 8 20` in 6dof, headset
  on the desk, controllers off (UB500 powered down for the run, `VR_BT_CTRL_CHECK=0`): **8/8
  cycles pass**. Each used the real `wmr` builder with 5/5 USB devices, logged exactly one camera
  start and one stop, and went down in about 4 s. There were no SIGKILL escalations, no cores, no
  `ERROR` lines and no failed resubmits. The 4 client cycles had a live `hello_xr`.
- **Player:** branch `review-fixes-20261013` on `lab` (fdc6c80). 0023-0025 apply and
  `hello_xr` builds; the old binary is in `~/vr/backups/hello_xr-lab-fdc6c80-20261013/`.
- **xrizer:** worktree `~/vr/xrizer-review` (branch `review-fixes-20261013`), kept apart from
  `~/vr/xrizer`, whose `compositor.rs` holds an uncommitted `wait_image` fix (DRAP work).
  0014-0017 apply, `cargo test --lib` passes 88, and the release builds. The vrpath still points
  at `~/vr/xrizer`.
- **NVIDIA:** the DKMS source is pristine and its installed 0002 is the 2026-08-04 version. The
  new series applies to a copy, and `make modules` builds against the rig's 6.12.111 kernel.
  Installing it needs root: `~/vr/backups/nv-0002-20261013/install-0002.sh` takes an fs-backup,
  replaces 0002, rebuilds, installs and refreshes the initramfs, and then the box needs a reboot.

Still open:

- **Owner decisions (§6), all seven.** The sudoers allowlist waits on the root check output. A
  read-only script was handed over on 2026-10-12; the lab box was unreachable over SSH then.
- **Still owed on the rig:** the neck-arm wearer A/B (the Aircar 100 mm and Cyberpilot 150 mm
  values were tuned with the inverted sign), a recenter, seek and frame step in the player, a
  two-file playlist with audio, a DRM lease on the rebuilt NVIDIA module, and one game through
  the patched xrizer.
- **Publishing the Monado branch.** The same fixes are on the rig (above) and on the everyday
  box's local branch `lab-full-review-fixes-20261012`. Neither is pushed: `lab-full` carries lab
  commits that were never published. The fork's `lab-full` (22e081141) is older than both.
- **Not fixed:** `solve_yaw_locked` has no release path (review §3.7). NVIDIA 0002's
  `lesseeFlipPermissive` stays set after a lessee exits without REVOKE_LEASE. NVIDIA 0003 is
  still keyed on the wrong manufacturer id (owner decision). The Monado series is still
  two lineages, and 36 of its patches do not apply on the pin. The session-anchor/stale-pose
  pair (M14-2, M08-2) needs a re-measurement before any change.
- **Retracted:** the review said the `constellation sample #` regex in
  `constellation-gate-validate.py` matches no log line. It matches the line lab commit
  e58036e6f emits, which is on `lab-full` (local and the fork). The line is missing only from
  the exported series, because the pinned base plus the applying patches has no controller
  constellation path at all. The validator's docstring now says it needs a `lab-full` build.
- **Sweeps (§9.8):** the English-only pass covers printed output and comments of the operator
  scripts. It deliberately leaves the spoken TTS prompts in Spanish (the user's choice),
  data tokens other programs parse (`ROJO/AMARILLO/VERDE`, `TE NECESITO/HAY QUE COMPRAR/LISTO`,
  `voz-*` cue ids), `docs/pruebas.jsonl`'s name and keys, quoted wearer feedback in docs, and
  the dashboard and launcher strings that go through `vr_i18n.py`. `power-on.py` and
  `windows-kit/power-on.ps1` also stay Spanish: on 2026-08-13 the owner decided their
  boot-console text moves to English through the `vr_i18n.py` preset in one dedicated pass, not
  piecemeal. Done in this sweep: `play360.sh`, `usb-bus-reset.sh`, `play-with-legend.sh`, the
  boot selector and launcher console, the two installers, `fix-vr-launcher-console.sh`,
  `pose-lag.py`, `reseat_audio.py`, `network-link-check.py` and `.gitignore`. Hard-coded paths
  and a shared env-knob helper are not done.
