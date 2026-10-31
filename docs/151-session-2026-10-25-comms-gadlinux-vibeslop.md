# 151 — Session 2026-10-25 (comms): routine "novedades" sweep, gadLinux's CV1 fork, and what the "vibeslop" pushback actually was

Nothing was posted or pushed upstream this session. This records three things: the routine
sweep, a surprise found during it, and a deep-dive the user asked for afterward into an
unrelated upstream thread that turned out to matter for how we approach our own work.

## 1. Routine sweep — one real surprise

**!2967's two held-back fixes were pushed on 2026-10-20, contradicting this repo's own
2026-10-19 record.** Note 3723595 (2026-10-20T03:53:29Z, author Wintch) shows `4e3e6b419`
(discard a stale reply to a firmware block header request) and `b184f1ed2` (retry the two
controller init commands) landed as a fast-forward on !2967. docs/150 explicitly describes
these as held back — the soaks proved the fixes' mechanism (fault injection) but gave zero
natural-reliability gain, and the stated plan was "only on the user's go" after a wearer
session that was never recorded. Someone pushed anyway, outside this session's visibility.
Pipeline is green. **No reviewer reaction in the 5 days since** (rpavlik/thaytan silent).
Flagged to the user; not re-litigated here — if it was intentional there's nothing to do but
watch for a reply.

Everything else, unchanged from the last sweep (docs/150):

- !2968/!2971/!3004: zero new notes since 10-14.
- !2969: unchanged since its own 10-14 rebase.
- Basalt `mateosss/basalt` !39: no reply from Mateo since our 09-21 answer. Don't nudge.
- `hare_ware/monado`: our issues #1 (09-17) and #2 (10-11) both still 0 replies, but his
  `wmr-new-constellation-tracking` branch force-pushed 10-20 and picked up a real new
  commit 10-23 ("calculate LED blink duration correctly") — he's actively iterating, just
  not engaging our reports.
- NVIDIA PR #1275, Ignition#3, bluez#689: unchanged.
- Faulto's fork: confirmed idle since 09-23 (re-checked the commit list directly, not
  trusted from memory). His issue #1 on our repo: still open, unanswered beyond our 08-27
  reply.
- Matrix: the saved token was dead (expected, ~24h pattern); a fresh one was supplied
  mid-session. Scan of all 6 joined rooms since the last check found nothing about us.

## 2. The LVRA Matrix "vibeslop" complaint, and what it was actually about

While scanning `#general-linux-vr-adventures` for the routine sweep, one vocal participant
(Matrix handle tied to a real contributor to the upstream constellation tracker — mentions
working alongside thaytan and someone called "marker") was venting about "literally 6
different vibeslop ports/forks of my constellation tracker", urging people to donate to
thaytan instead of burning AI budget on forks, and linking `monado/monado` issue **#633**
as the example not to dogpile on.

**Checked #633 directly — it is not about us.** It's **gadLinux**, a different person,
working on the **Oculus Rift CV1** (not WMR/G2), with a fork at
`gitlab.freedesktop.org/gadLinux/monado` (branch `cv1-fusion`) plus two companion repos
(`vr-tuning-tools`, `oculus`). No mention of Wintch/reverb-g2 anywhere in the issue, its
comments, or the room scan.

### What actually happened on #633

1. **2026-10-21**: gadLinux opens the issue, says upfront the work is "mostly AI" ("Don't
   blame me for that. But I wanted to get the job done"), lists what the fork does
   (distortion/FOV fixes, HMD + controller fusion, a validation framework for replaying
   captured sessions against different algorithms, ~20% faster blobwatch, three small
   tools), and says he'll post individual PRs after validating.
2. **2026-10-22**: **Beyley** (the maintainer who rewrote Monado's constellation tracker in
   !2940 — the exact codebase our own 0012+ series and hare_ware's branch both sit on)
   replies. Firm but not hostile: there's already an in-progress, from-scratch CV1
   driver + fusion rewrite of his own pending in !3015 (CORRECTION 2026-10-30: it was already
   on `main` as `54eebd9a4` when this was written, not pending); gadLinux's fusion approach is "a
   carbon copy of how I understand Oculus to do the fusion on PC", which he considers not
   extendable/maintainable across Monado's other drivers; he does not want to maintain two
   parallel fusion stacks; and he explicitly asks to wait until his own tracker work
   settles, since a lot of what the fork touches is going to change or become redundant.
3. gadLinux accepts, clarifies the LLM was used to understand the problem, not to make
   design decisions, and offers to downscale to small, isolated PRs instead (a blobwatch
   performance patch, a USB device-management patch, "a few others").
4. **Beyley declines those too**, for specific reasons: he doesn't want SIMD in blobwatch
   yet (he has a different idea — search less of the frame instead of vectorizing the
   search — and doesn't want to add something he's likely to rip out during his own
   refactor); he asks for more detail on the USB change since cross-platform correctness is
   sensitive (there's already a pending incompatible setting in `d/uvc` affecting Windows);
   and he states plainly that **any LLM-authored code needs to be hand-rewritten or at
   least hand-reviewed to match Monado's style before a PR**, because his review time is
   limited.

### Why this is worth recording here, not just in chat

Beyley is the same person whose tracker rewrite our own controller-6DoF line of work and
hare_ware's branch both build on (see docs/133/134/135, [[project_g2_controller_6dof]] in
the agent's memory). His stance in this thread — one evolving fusion stack, wait for it to
settle, LLM code must be manually brought up to the project's style before posting — is a
direct preview of what we'd hear if we ever brought our own constellation-tracking series
back to his attention while he's mid-rework. The Matrix room's "vibeslop" irritation is a
community reaction to exactly this pattern (multiple people using heavy AI assistance to
touch the same actively-changing tracker and generating review load nobody asked for) — it
doesn't name us, but we're sitting in the same category of risk, and this room already
called out our own AI-written !2967 comments once before (docs/85, 2026-08-27).

### Technical ideas in gadLinux's fork worth remembering (design, not code)

Looked at the `cv1-fusion` branch's commit list (not the diffs in depth — the fork is for a
different headset and a different fusion architecture, so a line-by-line port doesn't
apply). Two ideas map directly onto our own open problem (below):

- **"hold when lost" + an explicit "report lost position"** (commits `5853d85c`,
  `ab742242`, `85278a80`) — when the optical solve runs out of usable samples, the pose
  either holds the last value *and* flags it as lost, or the tracker invalidates it, rather
  than silently continuing to report `TRACKED` on a stale sample. This is precisely the gap
  our own host-BT controller path doesn't have (see §3).
- Adaptive matched-LED-count requirements and a gravity-direction check against the prior
  (`47578e21`, `73fb206b`, `2c9ee2bd`) — the gravity check is convergent with our own
  `WMR_CONSTELLATION_GRAVITY_GATE_DEG`, which is a good sign the general idea is sound, not
  a reason to import his implementation.
- A capture/replay validation framework (blobs + images, rerun different algorithms against
  a stored session) — a reasonable methodology to borrow in spirit for our own soak/A-B
  work, independent of anything CV1-specific.

None of this is being proposed as something to copy. Per Beyley's own stated reasoning
(not extendable, not maintainable, needs hand-rewriting regardless of origin), the useful
takeaway is the *design decision* — explicit tracked/lost state instead of silent
staleness — to implement natively in our own code, in Monado's existing idioms, not a port.

## 3. What's actually left to move our own controller 6DoF forward

Asked directly: estimate what's blocking further progress. The real blocker is not
Bluetooth communication anymore — the clock-domain fix is proven on hardware (docs/143)
and the firmware-retry fixes are now upstream (§1). **The open blocker is in the fusion
layer**: in both the 10-10 and 10-11 A/Bs (docs/143, this file's hare-ware-ab records), a
host-BT controller acquires 6DoF and then, after roughly 10-20 seconds, **freezes while
still flagged `TRACKED`** — stale `relation_history`, no IMU fallback, no downgrade of the
tracked flag. The soaks since have shown this is not something either !2967 fix touches:
natural reliability was statistically identical with and without them (13/15 vs 12/15,
etc.) — they fix the communication layer, not the "is this pose still good" decision.

Two further open items, neither root-caused:

- A cold-BT-link silence regime (750ms-4s with zero response on the first command after a
  controller has been idle) that no variant tested so far recovers from.
- Whether to keep iterating our own branch or lean further into hare_ware's, which is still
  actively evolving (force-pushed 10-20, a real new commit 10-23) and has pieces we don't
  (LED-ring self-occlusion visibility model, aim/grip offsets, his own timesync scaffolding)
  — this file's 2026-09-17 handoff already found concrete bugs in his branch too (a
  predicted segfault from an unassigned `get_tracked_pose` source, a fixed-placeholder pose
  that never reads the constellation history), so neither branch is simply "ahead" of the
  other on every axis.

And the structural risk from §2: Beyley is actively rewriting the shared tracker base right
now and has said, in a different but directly analogous thread, that he'd rather people wait
than build on a moving target. Any fix to the freeze bug should be developed and tested
locally first; there is no reason to expect a receptive audience for it upstream until his
own rework settles, independent of how good the fix is.

**No concrete ETA** — the freeze bug isn't diagnosed yet, only characterized (stale
relation_history, flag never downgrades). The next real step is a dedicated instrumentation
+ wear-test session aimed specifically at that transition (when do samples stop arriving,
what does the tracker do with a stale `relation_history` entry, does an IMU-only fallback
exist anywhere in the path today), not a quick patch.
