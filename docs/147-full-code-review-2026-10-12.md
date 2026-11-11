# 147 — Full code review, 2026-10-12

A read-only review of everything this project wrote at the time: the scripts, the patch series
(Monado, xrizer, Basalt, NVIDIA, hello_xr player), the Monado fork branch with the reconnect work
and the lab automation kit. Roughly 39k lines of scripts and 41k patch lines went through a
find / verify / refute pipeline of Sonnet agents (three finders and three verifiers per unit,
two adversarial refuters per high finding). The per-finding reports quote private identifiers and
are kept outside this repo. This document keeps what is reusable: the headline defects, the
recurring defect classes and the lessons, and which fixes were made.

Totals: 2191 raw entries (~1450 distinct after de-duplication): 20 headline highs (10 distinct
defects), 10 contested highs, 313 mediums, 1848 lows, no criticals. Entries overcount defects
because several lenses report the same bug. Mechanical baseline: every Python and shell file
parses, flake8 and shellcheck gave only unused-import and warning-class hits.

What held up: the two daily launchers carry their safety nets and drew only edge-case findings;
the quaternion, Lie-map, SLERP and timestamp-shift arithmetic in the analysis tools drew no
dispute; the companion-reconnect patches drew only lows; NVIDIA 0004 (the 90 Hz fix) drew nothing
substantive; the EDID injector's byte arithmetic checks out against EDID 1.4.

## 1. Limits of the review (read before trusting "confirmed")

- Nothing was compiled or executed beyond pure-function snippets and the critics' spot checks.
  "Confirmed" means three readers agreed, not that the behaviour was observed. The critics found
  defects the readers missed, e.g. an `int` overflow in Monado patch 0087 (`30 * U_TIME_1S_IN_NS`
  wraps, so the presence stale-channel check was dead code) and a shutdown use-after-free in 0027.
- Same model throughout, so agreement is correlated; the refute panel overturned 10 of 30 highs,
  and severities mostly moved down, so severity ranks fix order better than it ranks risk.
- Coverage gaps: the Rust series was never type-checked; the NVIDIA review covered the 595
  lineage while the active branch is the 615 one; about 900 lab-branch lines had no exported
  patch; the large tracking patches drew few correctness findings for their size.
- At review time the exported Monado series did not apply end to end on its pinned base (two
  lineages were mixed; 36 of 112 files failed), and the hello_xr series applied only 9 of 22.

## 2. Headline defects (survived verification and the refute panel)

| # | Where | Defect | Fix size |
|---|---|---|---|
| 1 | Monado `0095` | `wmr_camera_stop()` joins a USB thread parked in a condition wait nobody signals, so every camera teardown hangs until the launcher's SIGKILL at 10 s. | replaced by the camera drain pair (see §4) |
| 2 | Monado `0035` | Skipping fusion on zeroed idle packets leaves the fusion clock stale, so the first live packet after a controller wakes integrates the whole idle gap (10 to 136 degrees in replays). With the never-released yaw lock a hand can stay wrong until restart. | small |
| 3 | cockpit panel script | Monado prints an empty device slot as `<none>`; the code compared with `none`, so an unregistered controller read as registered and the panel said GO. | one line |
| 4 | cockpit panel script | Patch 0073 changed the battery log line to `raw byte [<name>]:`; the regex still expected `raw byte:`, so the battery readout and low-battery warning never fired. A lab-only patch (0080, not exported) broke a constellation validator the same way. | one line each |
| 5 | `scripts/jack-in.sh` | `reassert_monitors` passed `--pos 1920+0`; xrandr rejects it and stderr went to `/dev/null`, so the layout re-apply never happened. | one line |
| 6 | `scripts/collect-nv.sh` | A comment inside a backslash continuation split the `sudo -u ... env` command: `hmd-vk` ran as root without the session environment and the 60/90 Hz capture came out empty. | move two lines |
| 7 | NVIDIA BPC patch helper (retired) | `dkms remove --all` before an install that can fail, no rollback: a failed rebuild left the box with no nvidia module. It also double-applied 0004. | build before remove |
| 8 | hare-ware A/B analyzer | The builder token was parsed as `wmr:` (Monado prints `Using builder %s: %s`), so every valid leg was flagged `WRONG_BUILDER ... run is void`. The published tables in docs/143 do not depend on this flag (they come from raw log lines). | two lines |
| 9 | `patches/hello_xr-player/0004`+ | Spanish user-visible strings in 0006 and later, and a partial translation of 0001-0005, broke the series: four text pre-images in `playercontrol.cpp` no longer chained, which explained all 13 apply failures. | one translation pass, re-export |

Contested (the panel refuted them): the session-anchor guard re-firing (0099; do not fix the
stale-pose race in 0057 before re-measuring it), world-writable udev rules in an old installer, a
hard-coded desktop layout in a solo-HMD test script, and two hello_xr fork-design choices.

## 3. Recurring defect classes

1. **Instruments that fail green.** Gates and monitors that print OK, PASS, `0 trips`, `fps=0.0`
   or "registered" when they measured nothing: `verify-bpc.sh` exit status, the `speak.sh`
   silence switch (`jq // true` turns `false` into `true`), `reseat_audio.py`'s panel-lit test,
   `soak-variant.py` passing a soak whose player died, `hw-monitor.sh` (`grep -c connected` also
   counts `disconnected`). **A false pass is
   worse than a crash here, because post-update verification and the analysis docs treat the
   output as evidence.** Test every gate with one known-bad input before trusting its green.
2. **Cleanup that never runs, or runs on what the script does not own.** Python's default SIGTERM
   skips `finally` (a benchmark launcher left the power watchdog stopped and the GPU capped);
   EXIT traps installed before a "refusing: a game is running" guard tear down the live session
   they refused to touch (`light-preflight.sh`, `gpu-pacing-baseline.sh`); root-hub unbinds and
   companion de-authorizations with no trap; a playlist runner killed only the wrapper and
   orphaned the player.
3. **Parsers coupled to log text that later patches changed** (#4 above, plus the constellation
   gate and session-report parsers and the A/B analyzer). A check that greps `scripts/` for
   every log string a patch changes would catch the next one.
4. **The exported series is not the tree that runs.** Many Monado patch files failed on the pin;
   `bootstrap-lab.sh sources` stopped partway and never applied Basalt or xrizer; several fixes
   lived only on lab or MR branches.
5. **The same `grep -c ... || echo 0` bug** (prints `0` twice on no match, then the arithmetic
   fails) in two scripts; a recording script waited for a non-empty go file while its prompt
   said `touch`.
6. **Stale forks and copies.** `jack-in-wayland-tracing.sh` was ~400 lines behind production and
   its default mode could not succeed; loose workspace copies of `jack-in.sh`, `get360.sh`,
   `play360.sh` and `controller-pair.py` drifted from the repo; `controller-pair-btlog.py` sent
   a PAIR command on import.
7. **Environment knobs parsed five different ways** across Monado, Basalt, xrizer and hello_xr
   (presence-only enable, `0/f/F`, `atol` without an end pointer, panic on a bad float); 0058's
   CPU-list parser pinned the README's own example `1-5,7-11` to `{1,7}`.
8. **English-only rule.** 47 findings: Spanish output, spoken prompts, data keys, the
   `docs/pruebas.jsonl` filename, patch strings (#9 above).
9. **Public-repo hygiene.** Tracked docs, data and patch headers carried per-device and
   per-account identifiers, and the repo's `check-publishable.py` could not see some encodings.
   Exported patches must not carry tool session-URL trailers.

## 4. Fixes made

Everything below was checked at the stated level only (syntax, synthetic logs, applies on the
pin, builds); only the Monado camera teardown and the NVIDIA lease were exercised on hardware.

- **Instruments (§3.1):** `verify-bpc.sh` exits 0 only for 8 bpc and a live hmd-vk; `speak.sh`
  silence switch, `hw-monitor.sh`, `testlog.py` id allocation, the recording prompt and the
  `grep -c` pair fixed.
  Checked with jq/grep cases and synthetic logs.
- **One-liners (§2 #3-#8):** cockpit `<none>` and tagged battery regex, `jack-in.sh` `--pos XxY`,
  `collect-nv.sh` continuation, analyzer builder token (a read-thread exit at shutdown is not a
  death).
- **Traps and ownership (§3.2):** `light-preflight.sh`, `gpu-pacing-baseline.sh`,
  the benchmark launcher, the playlist runner, `usb-companion-reset.sh`, `usb-bus-reset.sh`,
  `capture-hid.sh` and `power-on.py` now clean up only what they own; verified with a
  process-group kill test. `controller-pair-btlog.py` no longer pairs on import.
- **Monado:** 0095/0096 are the camera drain pair; 0114 restarts the fusion clock after an idle run; 0115 fixes the neck-arm sign
  (ratio -1 to +1 on random rotations; it had shipped in two profiles tuned with the inverted
  sign); 0116 fixes 0087's presence-stale overflow (`-Woverflow` gone). On hardware,
  `teardown-stress.sh 8 20` in 6dof: 8/8 cycles pass, one camera start and stop each, about 4 s
  to go down, no SIGKILL escalations, cores or `ERROR` lines.
- **Series bootstrap (§3.4):** `bootstrap-lab.sh sources` applies `patches/<series>/applies-on-base.txt`
  (generated by `check-series-apply.sh`), can be re-run, applies Basalt and adds xrizer;
  `patch-nv` builds before it installs over the old module. `teardown-stress.sh` fails on a
  SIGKILL escalation, a missing client or a core.
- **hello_xr player:** the series was re-exported in English and all patches apply on the pin;
  new 0023 recenter sign, 0024 seek while paused and frame-accurate, 0025 audio clock hand-back.
  Worn check: 90 Hz, seek and frame steps while paused, playlist advance all fine (frame-step
  accuracy rests on the log, not the eye).
- **NVIDIA 0002:** the lease hook now puts the master and takes locks in the revoke path's order
  (builds on 595.71.05, kernel 6.12); `teardown-stress.sh 6 20`: 6/6 pass, every cycle leased the
  HMD at `4320x2160@90.00` with no nvidia/drm kernel messages.
- **xrizer 0014-0017:** 0013 had broken upstream's `load_actions_race` test (fixed); a repeated
  manifest no longer restarts the session; frame-timing ring; refresh-rate fallback; hold-time
  parsing. `cargo test --lib`: 88 passed.
- **English sweep:** operator-script output and comments are English. Deliberately left in
  Spanish: spoken TTS prompts, data tokens other programs parse (`ROJO/AMARILLO/VERDE`,
  `voz-*` cue ids), `docs/pruebas.jsonl` keys, and strings that go through the `vr_i18n.py` preset.

## 5. Still open

- Neck-arm wearer A/B (0115): the Aircar 100 mm and Cyberpilot 150 mm values were tuned with the
  inverted sign. One game through the patched xrizer is also still owed.
- `solve_yaw_locked` has no release path. NVIDIA 0002's `lesseeFlipPermissive` stays set after a
  lessee exits without REVOKE_LEASE. NVIDIA 0003 is keyed on the wrong manufacturer id (DPLib
  reads it little-endian: the `0x220E` case is dead code; the right key would be `0x0E22`
  plus product `0x36C1`). The session-anchor / stale-pose pair needs a re-measurement before any
  change.
- xrizer is GPL-3.0-or-later and its derivative patches sit under this repo's MIT `LICENSE`
  with no carve-out.
- Retracted finding: the `constellation sample #` regex did not match "no log line"; it matches
  the line a lab-branch commit emits. That line is absent only from the exported series, whose
  pinned base has no controller constellation path at all.
