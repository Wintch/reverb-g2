# Two-machine topology and the handoff protocol

This project runs on **two separate Debian 13 installs on the same physical box**
(Ryzen 5600X + RTX 3060 Ti/GA104) — not one machine with two configurations. Getting
that confused has cost real time more than once (see `docs/21-project-retrospective.md`
and the 2026-08-12 incident below), so it gets its own chapter instead of staying a
footnote in someone's head.

| | everyday system | lab (dev) |
|---|---|---|
| disk | `/dev/sda1`, plain ext4 | separate SSD, LUKS + LVM (`iashur-vg`), mounted read-write at `/mnt/lab` from the everyday system when needed |
| user | `brunduk` | `iam` |
| desktop | KDE Plasma, X11 | GNOME, Wayland |
| launch script | `jack-in.sh` (local only, not tracked here) | `jack-in-wayland.sh` (tracked here) |
| NVIDIA | Debian's `nvidia-current`, **unpatched** | patched open kernel modules |
| panel refresh | 60 Hz (stock) | 90 Hz (needs the patched driver, see `docs/13-bug-6bpc.md`) |
| repo | `~/Documents/linux_vr_base/reverb-g2-linux` — **stale, not authoritative** | `~/Documents/reverb-g2` — **authoritative**, this repo, pushed to `github.com/Wintch/reverb-g2` |

These axes move together as a bundle between the two installs, not independently — a
result confirmed on one combination is not automatically valid on the other (refresh
rate is the one known exception so far: everything else tested has reproduced across
both).

## The incident this chapter exists to prevent (2026-08-12)

The 6DoF constellation-controller work (`patches/monado/0016`/`0017`, see
`patches/monado/README.md`) was developed and verified entirely on the **everyday
system**'s own `monado` checkout, branch `g2-constellation-x11kde`. It was handed off to
the lab machine as a `git bundle` — `~/Documents/linux_vr_base/g2-constellation-x11kde.bundle`
on the everyday system, copied across to the lab.

**The bundle was created on 2026-08-11 and never regenerated after two more commits
landed on the branch the same night** — including the `container_of` fix that is *the*
commit that makes `position_tracked=yes` fire correctly for both controllers. The lab
side pulled the bundle, built it, and reasonably concluded "this isn't quite working" —
because the one commit that finishes the job was never in the file it fetched. Nothing
was wrong with the code; the handoff artifact was stale and nothing about the bundle
itself signals its own staleness (a `.bundle` file's name doesn't carry a HEAD SHA or a
date by default).

This is a different failure from `docs/pruebas.jsonl` T068 and the "series is broken"
box in `patches/monado/README.md` (those are about *textual* patch files losing their
common ancestor across divergent histories). This one is simpler and easier to miss:
the artifact itself was just old.

## Protocol going forward

**Before treating any bundle/branch handoff as current, verify its HEAD against the
source branch's actual HEAD — don't trust the filename or the date you remember making
it.**

```bash
# On the source side, right before handing off:
git rev-parse <branch>
git bundle create /path/to/handoff.bundle <branch>
git bundle verify /path/to/handoff.bundle   # confirms it's a complete, self-contained history

# On the receiving side, right after fetching:
git fetch /path/to/handoff.bundle <branch>:<branch>
git log -1 --oneline <branch>   # compare by eye against what the source side reported
```

A `git bundle create <path> <branch>` with no revision-range restriction bundles the
**entire history** reachable from that branch, not a diff — `git bundle verify` printing
"The bundle records a complete history" confirms this. That matters here: it means
fetching it and checking out the branch tip works regardless of whatever state the
receiving repo's own `main` is in, since the bundle carries every commit object it
needs, not text hunks that depend on a matching parent. **Prefer this over loose
`.patch` files for any handoff between these two installs** — `git am` needs textually
matching context and silently produces the divergent-history failure class documented
in `patches/monado/README.md`; a bundle fetch + branch checkout does not, because it
never tries to reapply a diff against a possibly-different tree.

**Concretely, when picking up a handoff:**

1. `git bundle verify` it first — a corrupt or partial bundle fails loudly here instead
   of silently later.
2. Check out the branch by name and read its own `git log`, don't assume a `.patch`
   export in this repo reflects the same commits — `patches/monado/README.md` already
   documents one case where it didn't.
3. Before reporting a result back ("this works" / "this doesn't"), state which commit
   SHA was actually tested. "I tried the 6DoF branch" is not verifiable after the fact;
   "I tried `7cb73701b`" is.

The 2026-08-12 incident's fix: the stale bundle was regenerated from the everyday
system's `g2-constellation-x11kde` branch (confirmed 28 commits ahead of local `main`
with zero drift between them — no rebase needed on that side) and the durable copy at
`~/Documents/linux_vr_base/g2-constellation-x11kde.bundle` was overwritten in place, plus
a copy left on the lab disk itself (`/mnt/lab/home/iam/Documents/`) so the lab side
doesn't depend on a second manual copy step. See `patches/monado/README.md` for what to
do with it once fetched.
