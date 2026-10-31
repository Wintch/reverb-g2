# 152 — Session 2026-10-30 (comms): !2971 merged, draft AI policy !3066, version sweep, Discord visibility

Nothing was built or tested on hardware this session. The only public change is one correction to
the !2967 description (§6); no comment was posted anywhere. Times are UTC unless marked.

## 1. !2971 merged

wallbraker requested Beyley's review on 10-02, Beyley approved on 10-27 20:31, marge-bot merged on
10-29 22:35 as `c85192751` + `a1cf1479a`. It is our third merged MR after !3021 and !3036.
`c85192751` keeps a `Co-Authored-By: Claude` trailer, the only AI trailer a grep finds on `main`
since 2025. Patch `0010` is redundant on the next rebase past it.

The other five (!2967, !2968, !2969, !3004, !3020) merge clean against `main` `b1174ee76` and have
no human notes since 10-14 or earlier.

## 2. Draft AI policy !3066

Opened 10-27 by Frederic Plourde (`fredinfinite23`), announced on Discord on 10-26 with the reason:
"it's been tough on our reviewers and allocating more review workforce has been a challenge". It is
a draft and not in force. As written it:

- bans AI output in commit messages, code comments, docs, MR, issue and review comments;
- bans machine translation output;
- forbids an AI `Co-authored-by` and requires `Assisted-by: TOOL:MODEL` plus a per-commit note of
  the tool's role;
- lets maintainers request prompts or logs, and raises the testing burden for AI-generated code;
- rejects non-compliant AI submissions automatically.

Positions so far:

- **wallbraker**: wants a small mandatory disclosure policy first, bans later; "MRs that break this
  policy has already landed".
- **Beyley**: wants machine translation allowed with the original attached. Cites !2967 as an
  example of text where "seemingly no human wrote the text", adding "not trying to shame".
- **danielcamposramos**: argues for disclosed AI prose, with review statistics.

Maintainers already disclose their own use: haagch in !3027 and !2953, wallbraker in !3049. xrizer
has a policy in force (issue #433, announced in v0.6): no pasted LLM issues, diagnoses, PR
descriptions or review replies; AI-assisted PRs are fine "as long as you generally understand what
is going on".

Our five open branches have no `Assisted-by`, so even the disclosure-only version would touch them.

## 3. Discord visibility

No Discord account is needed for the Monado server. Its channels are bridged through t2bot into
Matrix rooms under the `#monado:matrix.org` space, and they are world-readable, so a live Matrix
token reads them **without joining**: resolve `/directory/room/<alias>`, then
`/rooms/<id>/messages`. No join event, no footprint.

| Room alias | Messages since 10-20 | Newest |
|---|---|---|
| `#monado-general-discord:matrix.org` | 179 | 10-30 22:39 |
| `#monado-controller-tracking-discord:matrix.org` | 61 | 10-30 23:55 |
| `#monado-slam-discord:matrix.org` | 74 | 10-27 16:00 |
| `#monado-support-discord:matrix.org` | 58 | 10-28 03:40 |
| `#monado-driver-wmr-discord:matrix.org` | 2 | 10-30 23:53 |
| `#monado-linux-discord:matrix.org` | 3 | 10-22 22:14 |

The LVRA server is the gap. Its bridge stopped in every room checked (`general` 10-22 19:46,
`#steamvr` 10-22 18:05, `#xrizer` 10-22 15:07, `#monado` 10-22 14:39), and users reported it broken
on 10-29. Reading it needs a Discord account or a repaired bridge. Decision for now: wait for the
bridge. Discord's terms do not allow automating a user account, so no token scraping.

The scan found no mention of us, !2967 or !2971 in any bridged room since 10-20. Things worth
remembering:

- LVRA `#monado`, 10-20: "Oops, all slop", about `lbgos/rift-s-linux`, not us. The mood is the point.
- LVRA `#steamvr`, 10-20: "if you're on reverb g2 on nvidia then yes you _must_ use 60hz due to a
  driver bug". Our patches do reach 90 Hz; not corrected, low-profile mode.
- `discord-driver-wmr`, 10-30: haagch asks whether Azure Kinect's `cx/cy - 0.5` should apply to WMR
  cameras; Beyley is looking at it. `wmr_hmd.c:1251-1253` applies no such offset. Unmeasured by us.

## 4. Versions

| Component | iashur | Latest | Note |
|---|---|---|---|
| Monado | base `a6d31c6c1` (09-11), 209 behind `main` | `b1174ee76`; last release v25.1.0, 2025-12-09 | 145 local commits on top |
| NVIDIA | 595.71.05 | 595.112.07, 615.71.10, 615.78.08 | 615.71.10 only bumps the version over 615.71.09 |
| xrizer | 14 ahead, 14 behind `main` | v0.6 (10-08) | dynamic OpenXR linking is now the default |
| SteamVR | manifest from 09-23 | 2.18 stable (10-21) | an update can trigger the vrpath trap, docs/120 |
| Basalt | branch `lab` | upstream unchanged since 07-24 | !39 last note is ours, 09-21 |
| Kernel / Debian | 6.12.111 / 13.7 | 6.12.115 / 13.7 | |

595.112.07 adds an SST EDID recovery fix behind a regkey and shows no DRM-lease change. All four
`patches/nvidia` pass `git apply --check` on it; they were not built. PR #1275 is still open and the
6 bpc clamp is not fixed upstream. No update is needed.

Also released: Ignition v1.1.0, Envision 3.2.0, WiVRn v26.9, Proton 11.0-2e, OpenXR 1.1.65.

New to us: `BnuuySolutions/SteamVRLinuxFixes`, a Vulkan layer for `vrcompositor` (refresh rates,
`present_wait` lag, `FIFO_LATEST_READY` on NVIDIA). Its list of wired headsets does not name WMR.
Untested here.

LVRA wiki, 10-24 (Krzeszny): all WMR headsets went from Bronze to Gold through Oasis, and the Monado
column went from ✅ to 🚧.

## 5. What the next Monado rebase will meet

- `129ed9cf7` removes `xrt_binding_profile` from `xrt_device` after !3049 moved bindings to JSON.
  Patches 0006, 0011 and 0078 need rework.
- !3015, !3060, !3071: new constellation fusion and threading. Evaluate before writing a controller
  freeze fix.
- Open: !2535 (hidapi, picked up by fzeruhn on 10-30, proposes keeping a hidraw backend) touches the
  layer !2967 and !3004 rely on. !3038 (`xrt_fs` rename) touches `wmr_hmd.c` and more.
- !3052 merged, !3069 open: IPC teardown fixes, possibly related to our service-teardown SIGSEGV.
  Not tested.
- Issue #632 (`m_imu_3dof` never estimates gyro bias) describes the problem patches 0031-0035
  address. 0031 alone was a 53% reduction, not a cure. Nothing proposed; see §7.

## 6. Corrections

**!2967 description, edited in place 2026-10-31 00:11, no comment posted.** thaytan explained on
08-12 that #491 is a different failure, and we said we would fix the description if so; it was never
done. Direct Bluetooth was tested on 10-03. Old text, then new text:

```
- one lost firmware-read reply fails the whole controller for the session (#491 is this path in the wild);
- one lost firmware-read reply fails the whole controller for the session;

Tested on an HP Reverb G2 (rev B), tunnelled transport, Debian 13/X11. Odyssey-era BT controllers untested;
Tested on an HP Reverb G2 (rev B), Debian 13, over the tunnelled transport and, since 2026-10-03, with the controllers re-paired to a host Bluetooth adapter (see the notes below). Odyssey-era BT controllers untested;

over the tunnelled transport, on Debian 13 / X11, mostly 3DoF sessions. The direct-Bluetooth path and other WMR headsets (Odyssey, Explorer, Visor, G1) are untested by us.
over the tunnelled transport and a host Bluetooth adapter, on Debian 13, mostly 3DoF sessions. Other WMR headsets (Odyssey, Explorer, Visor, G1) are untested by us.
```

**Repo**: docs/18 (state line, open list, missing 10-20 row, stale "not pushed"), docs/151 (!3015),
`patches/monado/README.md` (0010), `CLAUDE.md` (MR count).

**Checked and left alone**:

- Note 3723595 (17/20 vs 20/20): matches docs/150 §fresh batteries. It omits the earlier 13/15 vs
  12/15 run from before the battery change, but it does state the failure regime it does not cover.
- PR #1275 and Project-VR#1 do not mention `0x220E`. Forum thread 379240 post 1 does, but only as
  the key of a workaround it lists as applied, and that was accurate about what was applied. The
  dead `case` is already corrected in docs/12, 14, 16 and `patches/nvidia/README.md`.
- !3004's "four commits ... the last two" is slightly off (five from !2967, three of its own, the
  last being its changelog), but it names the two code commits. Not worth a second edit.
- !2968 and !2969's testing disclosures describe what those MRs were validated on. No retest changed
  that.

## 7. Working mode from here (owner decision, 10-30)

No rush, low profile. The owner does not have time to validate much, and more output creates more of
these problems. So:

- No new MRs and no new comments on upstream projects. #632 stays an idea.
- Our own public text gets corrected when it is wrong, in place and with the smallest edit, without
  a comment.
- Open MRs sit until a reviewer engages. Reviewer questions go to the owner.
- The draft's "personally vouch for every line" cannot be met for new work without validation time,
  which is one more reason not to open any.
- The patch series keeps living in this repo, where it serves the rig regardless of upstream.
