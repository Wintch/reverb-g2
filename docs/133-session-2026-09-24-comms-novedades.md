# 133 — Session 2026-09-24 (comms): "novedades" sweep, three real findings

Routine check of every outward-facing thread this project has open. Nothing here needed action
during the session; it's recorded so the next session — comms or dev — can pick straight up
instead of re-deriving. Supersedes docs/128 §1 and §2 on the specific points below; read that doc
first for the full five-front picture, this one only adds what changed since it was written
(2026-09-23).

## 1. Monado: !3020 and !3021 exist now, still silent; !2940 merged

Confirmed via the GitLab API (`glpat-` token, GETs working today): all seven open MRs
(!2967/!2968/!2969/!2971/!3004/!3020/!3021) have had **zero reviewer activity since the 09-21
sweep** — note counts match exactly what our own 09-21 posts left them at. bl4ckb0ne has not
re-reviewed !2971; nobody has looked at !3004, !3020 or !3021 yet.

**The real event of the week is upstream, not on any of our MRs: Monado !2940 (Beyley, "Replace
OpenCV pose optimization and RANSAC with custom implementations") merged to `main` 2026-09-21T19:28Z.**
This is the constellation tracker our own controller-6DoF series (docs/125, docs/126) and
`hare_ware/monado`'s `wmr-new-constellation-tracking` branch both sit on top of. It doesn't
conflict textually with any of our seven MRs (`main` is now `6b41c5b39`, all seven still rebase
clean), but it *is* a real rewrite of the pose-solve internals underneath the
`CS_FLAG_MATCH_ALL_BLOBS` fix from docs/125/126 — **do not trust any pre-09-21 constellation
measurement without re-checking it against post-!2940 `main` first.** This is new work for
whoever next picks up controller 6DoF, not something this session did.

`hare_ware/monado`'s branch got its first push since 2026-09-14 right after that merge —
2026-09-23T22:35Z, tip `f41362eb` (was `cb98eba`). Plausibly a reaction to !2940 landing. His
issue #1 on `Wintch/reverb-g2` (ours) is still unanswered — per standing instruction, not nudged.

Basalt `mateosss/basalt` !39: no reply from Mateo since our 09-21 answer to his "why enable
recall?" question. Nothing to do; wait for him.

NVIDIA PR #1275 and forum thread 337744: both unchanged since 09-17/08-28 respectively.

## 2. NVIDIA 615: Faulto independently closed the gap our own 615 port left open

`Faulto/reverb-g2-linux` was recorded in this repo (docs/85, and `project_faulto_reverb_g2_fork`
in memory) as idle since 2026-08-27. **That was stale** — it pushed 3 commits 2026-09-23:

- `patches/nvidia/0006-nvkms-615-handle-undefined-bpc-and-force-G2-8bpc.patch` — ports the same
  `bpc != 0 &&` guard our own PR #1275 branch (`d2028a1`, docs/127 §on the 615 port) already
  carries, **and also fixes the thing that port explicitly left open**: `rgb444.minBpc` stays
  hardcoded to 6 upstream regardless of the guard above it. Faulto's patch adds an exact G2
  manufacturer/product-ID check (`0x0E22`/`0x36C1`) that raises the minimum to 8 when the EDID
  depth is undefined, leaving every other DP sink's 6-bpc floor untouched. Base is the same
  615.71.09 (`61dcc93`) commit our own port used.
- "Force DKMS compilation before installing patched NVIDIA modules" and "Keep Steam running
  during VR startup" — unrelated tooling commits, not reviewed this session.

This closes exactly the caveat flagged in this repo when the 615 port was done (09-17): "still-open,
orthogonal: `rgb444.minBpc = 6` stays unconditional (Faulto's point)". Worth doing, next time this
line of work is picked up: diff Faulto's `0006` against our own `patches/nvidia/` series, fold the
minBpc fix into PR #1275 (or credit/link it there), and decide whether to also pull his other two
615/DKMS commits. Not started — no NVIDIA-615 hardware in hand to test either patch against.

## 3. Nothing else moved

Faulto's issue #1 (ours): still open, no new comment. AUR package, LVRA wiki correction, everything
else tracked in memory under [[project_lvra_wiki_correction]] / [[project_faulto_reverb_g2_fork]]:
unchanged.

## Concrete next steps, in priority order

1. Controller 6DoF: before resuming docs/125/126's work, re-verify against `main` post-!2940 — the
   ground under that fix moved.
2. NVIDIA 615: diff Faulto's `0006` against our port, decide whether to fold it into PR #1275.
3. Everything in docs/128's own priority call (the USB Bluetooth dongle) still stands unchanged.
