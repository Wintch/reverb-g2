# 129 — Phase A of the hare_ware handoff: exposure x LED intensity on a G2, run for real

Date: 2026-09-23. Desk session on iashur, headset connected, both controllers powered on
throughout, nobody wearing anything. Ran from the everyday machine over SSH while the user was
present to move/place the controllers; `status-dashboard.service` / `dashboard-kiosk.service`
stopped before and restarted after, per the handoff's own ground rules
(`handoff-20260917-hareware-ab/HANDOFF.md` §2-3). This closes Phase A; Phase B (building and
running hare_ware's branch) did not happen this session.

## Caveats, stated up front

- **Right controller never registered, in any of the four runs** (`WARN [wmr_hmd_create] Failed
  to request controller status from HMD`). This is the pre-existing startup-race bug
  ([[project_g2_controller_6dof]], T051) recurring, not something Phase A caused — every number
  below is device 0 (left) only. Three back-to-back down/up cycles with both controllers left
  powered on did not fix it, matching the earlier "left wins every time" finding; not chased
  further this session.
- **No battery-level readings** (`controller-battery-check.py` needs the very libmonado
  connection each teardown removes, and it was not run mid-session before each teardown as the
  handoff asks). Numbers below cannot be blamed on or cleared of a battery effect.
- **Room light not characterized** beyond "controllers placed in front of the headset,
  moderately lit room, not dark" — no lux measurement, matching the handoff's own caution that a
  dark room or a headset-hand distance mismatch can produce a zero that looks like a real result.
- Each run's window is a few minutes, single session, n=1 per cell — exactly like the original
  T149 numbers this compares against.

## Results

| Run | Exposure/gain | LED intensity | Poses found (device 0) | Max blobs/frame seen | Notes |
|---|---|---|---|---|---|
| A1 | 6000/100 (default) | 0 | 1826 | 21 | Also: 9 contested-blob-recovery attempts, **1 succeeded** (`device 0 RECOVERED via all-blobs search after 19 consecutive deep-search failures`) — device 1 attempted recovery 4 times, never succeeded, 0 poses all session. First confirmed non-zero success for the 2026-09-14 `CS_FLAG_MATCH_ALL_BLOBS` fix (previous count was 0/15). 559 "Tracker is likely running slow" warnings. |
| A2 | 6000/100 (default) | 200 | 530 | 26 | Higher peak blob count than A1; single-session, not a controlled A/B against A1's identical exposure, but directionally consistent with driving the LEDs helping. |
| A3 | 400/1 | 0 | **0** | 0 (literally zero `blob ownership` lines in ~750 log lines) | Clean reproduction of T149's "black" result: short exposure, no LED command, this G2, in this light — nothing detected at all. |
| A4 | 400/1 | 200 | **970** | 9 | **The open question from the hare_ware issue, answered**: short exposure DOES work on this G2 once the LEDs are driven at the Windows-style intensity. Not as many simultaneous blobs as A1/A2 (9 vs 21/26 — plausibly the short exposure only catches the brightest, closest LEDs), but consistently above the 4-blob floor and producing far more accepted poses than A1 in a comparable window. |

## What this means for the hare_ware issue and our own defaults

The issue we posted (`hare_ware/monado` #1) said our 400/1-black-vs-6000/100-clean numbers were
taken with the LEDs at firmware default (no intensity command at all) and might not carry over to
a stack that drives them. **A3 vs A4 is exactly that test, and the answer is: they don't carry
over.** A short exposure is not inherently unworkable on a G2 controller camera — it needs the LED
drive to go with it. This is worth posting as a follow-up on issue #1 (not done — draft only,
comms session's call per the handoff, and per [[feedback_community_post_hygiene]] this should be
one comment, not scattered updates).

For our own stack: A1 (today's default) already works and has more simultaneous blobs than A4.
Whether A4's shorter exposure buys anything real (lower motion blur in fast motion was the
original T221 hypothesis this whole line of testing traces back to) was **not tested here** — all
four runs were at-rest, desk-only, no deliberate fast motion despite the plan asking for a 30 s
fast-motion window per run. That comparison is still open.

## A genuinely useful side effect: fresh evidence for the blob-ownership investigation

A1's full log (`~/vr/logs/phaseA-A1-6000-100-led0-20260923.log`, on iashur) is a richer capture
than anything `docs/125`/`docs/126` had: 9 contested-recovery attempts instead of 15 spread
across a whole different session, one real success, and multiple frames with 13-21 blobs where
recovery still failed. This is exactly the kind of high-blob-count failing frame docs/126 named
as the next concrete step to trace by hand through `correspondence_search`/`pose_metrics`. Not
done this session (ran out of session time) — the log is saved and ready for it:

```
iashur:~/vr/logs/phaseA-A1-6000-100-led0-20260923.log   (19634 lines)
iashur:~/vr/logs/phaseA-A2-6000-100-led200-20260923.log
iashur:~/vr/logs/phaseA-A3-400-1-led0-20260923.log
iashur:~/vr/logs/phaseA-A4-400-1-led200-20260923.log
```

## Also confirmed, not new but worth another tally mark

`jack-in-wayland.sh down` needed the 10s-grace SIGKILL escalation in **5 of 5** teardowns this
session (matching [[project_controller_6dof_root_cause]]'s 5/5 from 2026-09-14 — now 10/10
across the two sessions). Worth investigating directly rather than continuing to just note it.

## Not done this session

- Phase B (build hare_ware's branch, run the B1-B9 checklist) — headset was released for other
  use before getting to it.
- The 30 s deliberate-fast-motion half of Phase A's own protocol.
- Battery-level and precise light readings per run.
- The blob-ownership frame trace using A1's log, above.
- Posting anything to the public issue.
