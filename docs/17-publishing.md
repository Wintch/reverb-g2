# 17 — Publishing the repo

Goal: that anyone with a Reverb G2 can keep developing this. Destination
`github.com/Wintch/reverb-g2`.

**The history cleanup has already been done** (2026-08-05, from the main system with the
lab SSD mounted). What follows documents what was there, what was done, and how to verify
it before each push.

---

## What was blocking publication

### 1. Blobs above GitHub's limit

The two USB captures were **in the git history**, not just in the working tree:

```
858.1 MB  docs/dump90hz.pcapng
428.9 MB  docs/dump60hz.pcapng
```

GitHub rejects any blob over 100 MB, so the push failed right away, and deleting them from
the tree wasn't enough. Git LFS didn't work either: the free tier is 1 GB and this was
1.29 GB.

They were removed from the history. There was no real loss: the value is in the analysis
(`docs/12-g2-protocol.md`, `scripts/parse-usbpcap.py`), not in the raw dumps. Also removed
was `nv-report-*/build/hmd-vk`, a compiled binary that should never have been tracked.

`.git` went from **412 MB to 8.8 MB**.

### 2. Identity and hardware identifiers

- Three distinct identities in the commits, unified into one.
- The headset's USB serial appeared in 6 files, redacted.
- The `nvidia-bug-report` attached to the forum thread also carried the network card's MAC
  address (twice, forward and reversed as PCI Device Serial) and the motherboard serial. It
  was regenerated redacted: same 42787 lines, only those four modified.

---

## How it was done

With `git filter-repo`, in two passes. **Both are needed** — the first alone isn't enough,
and that was the trap:

```bash
# 1. blobs + commit identity
git filter-repo --force \
    --path docs/dump90hz.pcapng --path docs/dump60hz.pcapng \
    --path nv-report-20260804-223535/build/hmd-vk --invert-paths \
    --mailmap /tmp/mailmap

# 2. the CONTENTS of the files
git filter-repo --force --replace-text /tmp/redacciones
```

`--mailmap` rewrites **author and committer**, which is metadata. It doesn't touch what's
inside the files. Here there were two patches in `patches/hello_xr-player/` with the old
address in their `From:` line, and they survived the first pass intact. You have to search
the content of all commits, not just the authors:

```bash
git grep -lI "<pattern>" $(git rev-list --all)
```

The files `/tmp/mailmap` and `/tmp/redacciones` carry literal values that must not be
published, so they stay outside the repo. Formats:

```
# mailmap
New Name <new@example.com> <old@example.com>

# redacciones (replace-text)
OLD_LITERAL==>REPLACEMENT
```

### The trap that actually got us

The first version of this was a script `publicar.sh` that carried **inside it** the serial
and the address it was redacting, because it needed them as search patterns. When the
cleanup ran, it redacted itself, ending up with `SERIAL="REDACTED"` and a check that looked
for the word `REDACTED`. Useless, and worse: if it had been published before the cleanup,
it would have published exactly what it was trying to hide.

That's why the patterns now live in `scripts/.private-patterns`, which is in `.gitignore`.

---

## Before each push

```bash
./scripts/check-publishable.py
```

Checks that there's a single identity across the commits, that no blob exceeds 100 MB, and
that none of the patterns in `scripts/.private-patterns` appear in the history. It doesn't
modify anything. Returns non-zero if something fails.

That patterns file **is not in the repo** (on purpose). If you clone this on another
machine, create your own: one pattern per line, and lines starting with `#` are ignored.

## Publishing

```bash
git remote add origin git@github.com:Wintch/reverb-g2.git
git push -u origin main
```

`git filter-repo` deliberately deletes the remote after rewriting, which is why
`remote add` comes after the cleanup and not before.

The repo was created **private**. It's best to push it private, check on the web that it
looks as expected, and only then switch it to public from Settings. A later force-push
doesn't reliably remove what's already been indexed.

---

## What redaction doesn't fix

The original `nvidia-bug-report` **is still on NVIDIA's server** at its current URL, even
though the thread's attachment gets replaced: Discourse doesn't purge orphaned uploads
instantly. And anyone who downloaded it has the original. At the time it was redacted, the
post had 7 views and 0 replies, so the actual exposure is low — but the redaction matters
going forward, for when the thread gets traffic if NVIDIA replies.

---

## Structure: a single repo

Splitting player / tools / drivers into three repos was considered and **ruled out**. What's
in `patches/` isn't forks: it's series of patches against upstream. A patch without the doc
explaining why it exists isn't useful, and the doc without the patch isn't either.

```
docs/          17 chapters, from the USB to the NVIDIA bug
patches/nvidia/            3 from Project-VR + ours (0004, see PR #1275)
patches/monado/            7 of ours
patches/hello_xr-player/   3, the 360/VR180 player
scripts/       34 tools
experiments/   the EDIDs from the vblank experiment (docs/16)
```

The only thing that goes outside the repo is the NVIDIA fix, and it already went out:
https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275

The code trees aren't versioned: `bootstrap-lab.sh` clones them from upstream at the exact
SHAs the patches were generated against. That's why the bundle weighs kilobytes, and it's
clear exactly what's ours.

## What was missing before making it public

- [x] **An entry-point README** (`README.md`, in English). Updated 2026-08-05 (night) to
      reflect that the `docs/16` factorial has already been run (it's no longer left as a
      pending task for a third party) and that the USB/HID channel was also closed on the
      Windows side.
- [x] **The FCC PDFs** (6.8 MB, `docs/*.pdf`) are linked, not versioned — `.gitignore`
      excludes all of them (`*.[Pp][Dd][Ff]`), consistent with the same criterion already
      applied to the ANX7530 datasheet.

Before switching the repo from private to public, besides running `check-publishable.py`:
check on the GitHub web UI that the README renders well, and that no file in
`windows-kit2/` (third-party binaries, our own captures) was left tracked by mistake —
that folder is intentionally local, see `.gitignore`.

---

## Git access from the lab

Resolved. There's a key **specific to the lab** (the main system's key wasn't copied, so
one machine can be revoked without touching the other), at `~/.ssh/id_ed25519`, with its
`Host github.com` entry in `~/.ssh/config`. The public key is already loaded into the
account.

Verify with `ssh -T git@github.com` — it has to respond `Hi Wintch!`.
