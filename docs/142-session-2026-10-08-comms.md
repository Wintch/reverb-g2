# 142 — Session 2026-10-08 (comms side): !3021 merged, main conflict survey, pin stays

The everyday box's job was "see what's new", then keep the records straight. Channels swept
read-only: GitLab (the seven Monado MRs, hare_ware's fork, Basalt !39), GitHub (NVIDIA PR),
the NVIDIA forum, LVRA Matrix. Nothing was posted anywhere. Times are UTC. Companion record:
`docs/18` (rows 2026-10-08).

## 1. What was new

| channel | state found | action |
|---|---|---|
| Monado !3021 | **merged 10-07 15:41Z**: mateosss "Yup I think this is sensible" + approval, marge-bot rebased and merged (`de2068bdf` + `ec188bb13` `doc: Document !3021`). First MR of ours in upstream `main` | docs/18 row |
| Monado !2967/2968/2969/2971/3004/3020 | no reviewer activity beyond wallbraker's 10-02 notes; last note on each is ours or his | none, do not nudge |
| Monado `main` | `f07dd1348` → `ec188bb13`; two WMR commits from Beyley (MR !3030): `019d9d458` removes `WMR_LEFT/RIGHT_DISPLAY_VIEW_Y_OFFSET` and `poly_3k.y_offset`, `351ac528b` fixes the distortion texture range | see §2 |
| hare_ware/monado | `wmr-new-constellation-tracking` got two commits 10-06 (`apply timing_fudge_ns more correctly`, `d/wmr: expose LED ramp pattern to debug gui`); his issue #1 still unanswered | none |
| Basalt !39 | unchanged since our 09-21 answer to Mateo | none |
| NVIDIA PR #1275 / forum 337744 | unchanged (open, 1 comment, 09-17; 18 posts, last 08-28) | none |
| Faulto fork | not checked: `Faulto/reverb-g2` returns 404 on the GitHub API (owner or repo name differs) | find the right name next sweep |
| LVRA Matrix `#general-linux-vr-adventures` | 2414 messages 10-04 → 10-08, keyword-filtered: nothing about us, hare_ware or constellation. A G2+NVIDIA user is adding an "NVIDIA users" section to a wiki MR on his fork (10-05); others call Monado's experimental controller tracking "ROUGH" | none; whether his section repeats the false "60 Hz-only on Nvidia" claim was not checked |

## 2. Conflict survey against the new `main`

`git merge-tree --write-tree` of each open MR head against `ec188bb13`: **!2967, !2968, !2969,
!2971, !3004, !3020 all merge clean.** No rebase needed until a reviewer engages.

The lab series is another story. `patches/monado/` (113 patches) is applied by
`bootstrap-lab.sh sources` with plain `git am` on the pin `735e29e4e`, and it **already fails
at 0016** on that pin (the README documents 0016/0017 as non-applying). So the Y-offset removal
is only a late symptom: 0072 and 0075 carry the two `DEBUG_GET_ONCE_NUM_OPTION` lines as
context. Lab branches against new `main`:

| branch | ahead of pin | conflicts |
|---|---|---|
| `lab-full` | 59 | `t_tracker_slam.cpp` |
| `lab-full-dev` | 98 | `wmr_camera.c`, `wmr_controller_base.c/.h`, `wmr_source.c`, `wmr_hmd.c`, `tracking/constellation/correspondence_search.*` |
| `g2-constellation-x11kde` | 24 | `wmr_camera.c`, `wmr_controller_base.c/.h`, `wmr_source.c` |

Most likely causes: !2940 (constellation tracker rewrite) and other `d/wmr` churn.

**Decision: the pin stays on `735e29e4e`.** A real rebase of `lab-full-dev` is a multi-session
job with a worn test at the end; do it only when something from `main` is needed (for example
the !3030 distortion-range fix). `docs/83` still lists the Y-offset knob as "have, don't use";
it is only wrong once the pin moves. `patches/monado/README.md` carries a note.

## 3. iashur

Powered on by the user at the end of the session. `reverb-g2` there was clean at `c186faa` and
was fast-forwarded to `e3eaace` (its `origin` is GitHub). No Monado process running.
**Root filesystem at 91 %** (179 G of 207 G, 18 G free), above the ~80 % headroom rule; nothing
was deleted, a "what is big" pass is still owed.

## 4. State left behind

- Commits pushed to `Wintch/reverb-g2` main: `fe47113`, `e3eaace`, plus this doc.
- The Matrix token supplied in chat is stored in `~/.config/reverb-g2-tokens/matrix.token`
  (600) and is flagged for rotation; expect it dead within ~24 h.
- Uncommitted on purpose: the pre-existing `scripts/jack-in-wayland.sh` diff.
- Scratch worktrees and the `refs/mrcheck/*` refs in the `monado` clone were removed.
