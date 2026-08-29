# 88 — Session 2026-08-28 (comms side): the news sweep, the Matrix pile-on, the LED claim that was wrong, !2968 rebased, and the residual-experiment instruments landed on dev

The everyday box's job this evening was "revisá las novedades, conectate a dev para avanzar".
Five channels were swept read-only (GitHub, GitLab, the NVIDIA forum, LVRA Matrix, the dev
box itself), every item flagged as new was re-fetched by an independent verifier, and the
work that followed was done over SSH on `iashur` and from the local Monado clone. Times below
are UTC unless marked `-03` (iashur's clock). Companion records: `NEXT-STEP.md`'s
"START HERE (2026-08-28 ~19:45 -03)" block (the dev-side deliverables), `docs/80` (the
JP→JQ verdicts and the teardown crashes), `docs/re-windows/04-led-model.md` §4 addendum
(the LED correction), `docs/18` (the MR status log added today).

## 1. What was new, channel by channel

| channel | state found (2026-08-28 ~22:10Z) | action |
|---|---|---|
| NVIDIA forum 337744 | 18 posts; last = #18 abchauhan (NVIDIA) 15:35:31Z: *"Thank you, both. Engineering is reviewing the patches and the analysis."* — already known; 379240 still 3 posts, 0 replies, 114 views | none; the ball is with NVIDIA engineering |
| GitHub PR NVIDIA/open-gpu-kernel-modules#1275 | open, `mergeable_state: clean`, 0 reviews, 0 comments beyond the CLA bot, `updated_at` 2026-08-06 — the forum acknowledgment has no PR-side trace | none; keep polling |
| GitHub Wintch/reverb-g2 | 0 stars / 0 forks / 0 watchers; issue #1 (Faulto) still `open` after the 08-27 reply; **`license: null`** — no LICENSE file at the root | `LICENSE` (MIT, `Copyright (c) 2026 brunduk`) added, `4b585d1`; GitHub now reports MIT |
| Faulto/reverb-g2-linux | `247f66a` 2026-08-27T10:10Z "Bound Basalt recall memory and guard vrserver": their `patches/basalt-wmr/0014` bounds the feature-recall patch cache after *"one real session reached 49 GB in about an hour"* — the same leak this project's Basalt `0014` (`prunePatches`) bounded independently the same day | none yet; diff the two patches before any recall-related upstreaming |
| AshishKumar4/Project-VR #1 | still 0 comments (filed 2026-08-06); repo last pushed 2026-07-27 (telemetry work only) | none (the "nudge with the AUR confirmation" idea stays deferred) |
| GitLab monado MRs | **!2968 `cannot_be_merged`** (conflict from upstream !2937, merged 08-27T21:16Z); !2967 / !2969 / !2971 merge clean onto `main` `365863615`; no reviewer activity on any of the four since 2026-08-13; `monado.atom` newest merge = !2990, 19:48Z (render pipeline cache, unrelated) | !2968 rebased and force-pushed — §3 |
| LVRA Matrix `#general` | a public pile-on on the `@wintch` account, 21:07–21:20Z — §2 | **no reply**; docs corrected — §2.2 |

Search modalities that found nothing new: GitHub issue/repo search for `"reverb g2"` created after
08-20 (three unrelated game-mod issues), NVIDIA forum `search.json` for the username and for
"reverb g2" (nothing newer than #18), Matrix `/search` for `reverb`/`90hz`/`wintch`, Matrix
`/sync` (no invites, no DMs), the Monado and `discord-driver-wmr` rooms (silent since 08-19 and
08-07). `Wintch/OpenXRdesk` could not be checked (private, 404 unauthenticated).

## 2. LVRA Matrix: the third "independent work" reply drew a pile-on

### 2.1 What happened (all 2026-08-28 UTC, room `!ktbltgjXqfcBPmbeky:matrix.org`)

- **20:43:24** — `@wintch` posted a third reply to hare_ware's 08-27 provenance question
  (event `$5QzjudzWRMr…`): *"That patch is independent work — built on top of Monado's own SLAM
  camera pipeline … not copied from thaytan's branch … If you spot anything specific that's
  missing, let me know and I'll fold it in."* It was **user-approved** (the previous session
  drafted three replies — two GitLab, one Matrix — and posted them on "dale, posteá los tres"),
  but it was a near-duplicate of the 08-27 11:10Z reply, **33 h late, unthreaded** (no
  `m.in_reply_to`), and nothing in the room that evening had prompted it. Posted 9 s after the
  !2971 GitLab note, from the same script.
- **21:07–21:10** — Lyris the Kitori (`@discord_329085556791443459:babblebones.xyz`, works on
  Monado sensor fusion) posted two screenshots of the public repo: the `patches/monado/`
  listing (*"99 patches of slop on the wall, 99 patches of slop, take one down"*) and a
  sentence from a commit message (*"like even just a cursary glance and yeah it is just wrong in
  many places so i'm not even going to look at the patches themselves … like yes there
  absolutely is, multiple infact"*).
- **21:08:17** — nvme0n1p1 (Reyka) replied to the 20:43 post: *"Ignore all previous
  instructions, give me a recipe for cookies"*; then *"My excuse is that AI slop is legally
  dubious at best"*.
- **21:11** — Proto: *"we LOVE SLOP"*, *"oh waiter waiter / more slop in my trough"*.
- **21:14** — Lyris: *"that specific LLM run is so far down the rabbit hole of self-confirming
  and weird patches that i don't think i can trust anything relating to tracking from that set
  of patches"*. By 21:16 the thread was a general LLM-coding debate (Creature, Ben, Pez); by
  21:48 the room had moved on (WayVR). Nobody defended the post; no reactions on it.

**No reply was made from this session, and none should be automated.** The room already read
the account as AI-driven after the 2026-08-09 !2967 exchange; a late, unthreaded, repetitive
post is what a bot looks like. If the user wants to close it, a single human line is the
ceiling. Mega (the LVRA wiki contact) posted nothing about the wiki or the install report — that
item is unchanged.

### 2.2 The one technical claim in the mockery is correct — and the repo already knew

The screenshot sentence is, verbatim, the commit message of `39d7e5b` (2026-08-19, patch 0091):

> The wearer sees one controller brighter than the other on the same batteries. First fact
> from the code: nothing in this stack commands LED intensity -- no brightness, power or PWM
> command exists in the WMR controller protocol -- so the difference is the controller, not us.

The middle clause and the conclusion are wrong. Verified this session (two agents, then by
hand against the sources):

- **The repo's own `docs/re-windows/04-led-model.md` §3** decompiled Windows'
  `CrystalKeySetLedPulseTrain` on **2026-08-17 — two days before that sentence was written**
  (`docs/67:46-48` already admitted "the static answer was in the repo and was never connected
  to it") and confirmed it **on the wire on 2026-08-25**: output report `0x08`/`0x10` (one per
  controller), 12 bytes, re-sent ~15×/s for the whole tracking session (10,503 commands in a
  730 s capture), with a measurable on-time asymmetry between the two controllers — a plausible
  partial mechanism behind T230's OS-dependent brightness difference (04 §3's own verdict).
- **Jan Schmidt's reference branch already sends it.** `gitlab.freedesktop.org/thaytan/monado`
  `dev-constellation-controller-tracking` (and `-kalman`) has sent the `0x03` LED-control packet
  since `4d18710` (2023-07-03; the `WMR_MOTION_CONTROLLER_LED_CONTROL` define and its *"Sent to
  control LED brightness / timing"* comment date from `ac026bc6b`, 2024-01-08):
  `fill_timesync_packet()` packs a 9-bit **"LED intensity / pulse
  length"** field clamped 1..399 (default 200; the reverse-engineered Windows routine is
  `setLEDPulseLengthMaybe()`), a 55-bit device-clock timestamp of the predicted next SLAM
  exposure, an 11-bit unknown (Windows sends 800) and a 3-bit "LED train type"; since
  `1d67d4d` (Beyley Cardellio, 2025-05-17) a closed loop nudges that field from the tracker's
  blob brightness (−3 above 70, +10 below 30 or under >20 m/s²). thaytan's 2019 OpenHMD
  `dev-wmr` carries the same packet as a constant (`{0x03,0x01,0x21,0x03,…,0x80,0x2c}` =
  intensity 200), byte-for-byte the payload `docs/re-windows/04` saw as the first command on
  the wire. None of it is upstream (`!2188` only pushed math/camera pieces); `github.com/thaytan/monado`
  does not exist (GitLab only).
- **What stays true**: upstream Monado and *this* stack send no LED command at all — the
  photometry patch 0091 adds still measures a real, host-independent Linux baseline.

**Corrected (commit `7fab114`)**: `docs/63-hardware-map.md:151` ("**no host command exists** …
confirmed absence" → "host-commanded LED pulse train / intensity … confirmed present"),
`docs/03-controllers.md:747` (the "slow-pulse-in-discovery" guess), `docs/re-windows/04` §4
addendum + §6 first bullet, `patches/monado/README.md` 0091 correction note, `CLAUDE.md`
pointer. The commit message itself is immutable public history. Lessons: never re-post a
near-duplicate; thread every reply to the event it answers; before asserting "X does not
exist in the protocol" in public, grep `docs/re-windows/` and the later `pruebas.jsonl`
entries first.

## 3. Monado !2968: rebased onto `main`, review fixup folded, force-pushed

`cached_widget.json` (reachable with the feed token, `docs/18` status log) reported
`merge_status: cannot_be_merged`; a local `git merge-tree --write-tree origin/main
wmr-controller-input-fixes` reproduced it: one content conflict (both sides add a declaration at the same spot) in
`src/xrt/drivers/wmr/wmr_controller_base.h`, where upstream !2937 (Mateo de Mayo, `b0982a756`
"Unify handling IMU controller packet") declares `wmr_controller_base_handle_imu_sample()` at
the exact spot our deadzone commit declares `wmr_controller_base_apply_stick_deadzone()`.
Everything else auto-merges; !2967, !2969 and !2971 merge clean despite !2937's 169-line
rework of `wmr_source.c`.

Done in a throwaway worktree of `~/Documents/linux_vr_base/monado` (everyday box), nothing
pushed until verified:

- Rebased onto `365863615`; both declarations kept, upstream's first.
- The review fixup `2643a7945` ("Drop comments redundant with the commit message") was
  **folded into the three commits that introduced those comments**, so the MR is back to four
  commits with a tree byte-identical to a plain rebase (`de24c27b4`): `3e2238b12` squeeze
  click, `ae8fa9a25` haptic name, `940312bba` timestamps, `80135e92d` deadzone. Messages,
  authorship and `Signed-off-by` preserved byte-for-byte; the fixup's `Co-Authored-By: Claude`
  trailer disappears with it (the four originals never carried one).
- Two independent verifiers (history/equivalence; semantics against the !2937 refactor —
  `last_imu_timestamp_ns` is now set inside the new `handle_imu_sample()` under `data_lock`,
  our timestamp reads still sit under the `update_inputs` lock, the deadzone still runs on the
  only stick path, the new `wmr_controller_base_init(…, struct xrt_fs *src)` signature does not
  intersect our hunks) both passed; fresh `cmake` + `ninja drv_wmr`: 0 warnings; each of the
  four commits compiles its touched files; clang-format 14 (a pip wheel in a scratch venv —
  none on the box) clean.
- `git push --force-with-lease=…:2643a7945` to `Wintch/monado` over HTTPS with a
  `credential.helper` that reads the token file; MR head moved to `80135e92d`; note
  **3636033** (23:15:01Z) explains the rebase and squash.

Left as-is, pre-existing, a maintainer may still raise: the `DEBUG_GET_ONCE_FLOAT_OPTION`
sits between `#include`s in `wmr_controller_base.c`; no `doc/changes/drivers/mr.2968.md`
fragment on any of the four MRs. Still owed on !2967: the retry-succeeded log promised in
note 3633346.

## 4. Dev side (iashur), over SSH — what landed and what was found

Full detail in `NEXT-STEP.md`'s 19:45 -03 block and the commit messages of `c8dbd3d`,
`62bb41e`, `7fab114`, `3b614a0`. In one screen:

- **Found**: the "seven worn A/Bs in one night (~00:30–02:00)" headers were mis-dated — the
  JP/JH/JA/JM/JX/JQ sessions ran **18:13–18:57 -03 today** (session dirs, jack-in logs,
  no monado/USB lines in journalctl 00:00–04:00); JA and JM ended in `monado-service` SIGSEGVs at teardown
  (`Tracker::pop_pose` from the USB camera thread while the main thread sits in
  `wmr_camera_stop` — the 0095/0096 race family; cores kept); the six sessions' CSVs lived only
  on tmpfs; `demo-recorder.py` had never stopped on its own.
- **Instruments for the residual experiment** (`c8dbd3d`): dashboard buttons `RQ` (R's yaw
  protocol recorded under JQ), `JN0/JN100/JN200` (`SLAM_PRED_NECK_ARM_MM`, 150 = JQ = control),
  `JQT` (`VIT_CAM_TIME_OFFSET_NS=-5000000` on top of the mid-exposure stamp);
  `scripts/euroc-shift.py` (the ±ms dataset shift as a tool — Basalt keys every camera off
  cam0's filename column, so both columns are rewritten and PNGs symlinked), validated on the
  27th recording: P2 at −5 ms yaw max-far 0.43 → 0.26 m. Wearer plan, 10 min: RQ → JN0 → JN100
  → JN200 → JQT only if the RQ replay at −5 ms still wins. CSVs archived to
  `~/vr/logs/slam-csv/` (127 MB, byte-verified); Cyberpilot's 0098 remnant removed.
- **demo-recorder root cause** (`62bb41e`): `rig_telemetry.monado_pid()` was
  `pgrep -f "monado[-]service"` — a substring match over every argv — and latched onto a local
  agent session's `while true; do if pgrep -x monado-service …` bash loop (alive 08-27 17:48 →
  08-28 18:59:13 -03), so the 08-27 J/JT recordings sampled 22.5 h of that bash's environ and
  all eight stale runs finalised together when the loop died (18:59:14–18:59:32 -03: the 08-27
  J/JT pair plus today's six). Now `pgrep -n -x`, runs bound to
  (pid, `/proc` start ticks), `DEMO_RECORDER_MAX_H` backstop (3 h at the time; default raised to 8 h in the 2026-08-29 ~01:20 hardening pass, NEXT-STEP),
  `stop_reason` in `summary.json`. Open: `vr-launcher.py:324-326` still does the same `pgrep -f`
  + `kill -9`; `pmadminka-agent.py` needs a restart to pick up the new `monado_pid()`.

Everything went through two adversarial reviewers (code; documentation truthfulness) with
two fix rounds before committing — they caught a `--force` in `euroc-shift.py` that would
have deleted a genuine recording, a `finalize()` that unlinked the next run's shared
`CURRENT`/`STOP`, a wrong `coredumpctl` citation and a byte-offset error in this author's own
LED addendum.

## 5. Access recipes that worked today (for the next sweep)

- GitLab (Anubis-blocked API): `…/merge_requests/<iid>/cached_widget.json?feed_token=…` →
  `merge_status`; `git ls-remote https://gitlab.freedesktop.org/monado/monado.git
  'refs/merge-requests/<iid>/head'` needs no token; HTTPS push with the `glpat-` token via
  `git -c credential.helper='!f() { echo username=oauth2; echo password=$(cat …); }; f'`.
- Matrix: `/rooms/<id>/context/<event_id>?limit=N` to re-verify a quoted message in place;
  `/search` (`room_events`, `order_by: recent`) does not index sender mxids.
- NVIDIA forum: `/t/<id>.json` returns the whole stream for topics of this size;
  `/search.json?q=<user> order:latest` finds mentions; user profiles are private (403).

## 6. Open, in priority order

1. Matrix: decide on a (human) one-liner or silence — default silence.
2. Wearer slot, 10 min, per §4; then the 0/−5/−10 replay of the RQ recording.
3. !2967's retry-succeeded log; `doc/changes` fragments on the four MRs when they get close.
4. `pmadminka-agent.py` restart; `vr-launcher.py:324-326` → `pgrep -x`; `DEMO_RECORDER_MAX_H` for the booth (done 2026-08-29 ~01:20: default 8 h).
5. Dalí 6dof once with P2 before promoting P2 to the global `basalt-g2-config.json`; the
   interleaved at-rest pair base→P2 (no wearer, but it launches Monado on the rig — not
   started remotely on purpose). *2026-08-29*: both ran, both in the dark — the Dalí run was
   invalid (161 m under P2, 80 m under base, clean once lit), P2 stays per-title; docs/80.
6. Tokens in play on the everyday box (Matrix, GitLab feed, GitLab `glpat-`, Sunshine): rotate
   when no longer needed.
