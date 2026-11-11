# 17 — Publishing the repo

Goal: that anyone with a Reverb G2 can keep developing this. Destination
`github.com/Wintch/reverb-g2`. This chapter is the checklist to run before each push.

## Rules

- No raw USB captures or compiled binaries in the tree: GitHub rejects any blob over 100 MB
  and Git LFS's free tier is too small. The value is in the analysis (`docs/12-g2-protocol.md`,
  `scripts/parse-usbpcap.py`), not in the raw dumps.
- One commit identity across the whole history.
- No hardware identifiers (headset USB serial, NIC MAC, motherboard serial, device UIDs) in any
  file, including attachments such as `nvidia-bug-report` logs. Redact before attaching.
- FCC PDFs and vendor datasheets are linked, not versioned (`.gitignore` excludes `*.pdf`).
- Third-party binaries and our own raw captures stay local (see `.gitignore`).

## Before each push

```bash
./scripts/check-publishable.py
```

Checks that there is a single identity across the commits, that no blob exceeds 100 MB, and
that none of the patterns in `scripts/.private-patterns` appear in the history. It doesn't
modify anything and returns non-zero if something fails.

The patterns file **is not in the repo** (on purpose: it carries the literal values that must
not be published, so a script holding them would publish them). If you clone this on another
machine, create your own: one pattern per line, lines starting with `#` are ignored.

If a rewrite is ever needed (`git filter-repo`), two passes are required:

1. blobs and commit identity (`--invert-paths`, `--mailmap`): rewrites author/committer
   metadata only;
2. file contents (`--replace-text`): search the content of all commits too, because
   `--mailmap` does not touch what is inside files, for example a `From:` line in a patch:

```bash
git grep -lI "<pattern>" $(git rev-list --all)
```

Keep the mailmap and replace-text files outside the repo. `git filter-repo` deliberately
deletes the remote after rewriting, so `git remote add` comes after the cleanup.

## Publishing

```bash
git remote add origin git@github.com:Wintch/reverb-g2.git
git push -u origin main
```

For a first publication: push the repo private, check on the web that it looks as expected
(the README renders, nothing in the local-only folders was tracked by mistake), and only then
switch it to public from Settings. A later force-push doesn't reliably remove what has already
been indexed, and uploads attached to forum posts are not purged instantly even when the post
is edited.

## Structure: a single repo

Splitting player / tools / drivers into several repos was considered and ruled out. What is
in `patches/` isn't forks but series of patches against upstream. A patch without the doc
explaining why it exists isn't useful, and the doc without the patch isn't either.

```
docs/          chapters, from the USB to the NVIDIA bug
patches/nvidia/            3 from Project-VR + ours (0004, see PR #1275)
patches/monado/            WMR driver, tracking and pacing patches (+ unapplied/)
patches/basalt/            SLAM fixes and instrumentation
patches/xrizer/            OpenVR-on-OpenXR fixes for SteamVR titles
patches/hello_xr-player/   the 360/VR180 player
scripts/       tools
experiments/   the NVKMS EDID-override candidate config (docs/16)
forum-attachments/  the headset's EDID (serial zeroed) and decode, as posted to NVIDIA
windows-kit/   Windows-side bring-up and capture tools
tools/         ovrplugin-stub: a do-nothing OVRPlugin for native Unity VR games
web/           the credits and licenses page
```

The NVIDIA fix went upstream as https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275

The code trees aren't versioned: `bootstrap-lab.sh` clones them from upstream at the exact
SHAs the patches were generated against. That keeps the repo small and makes it clear exactly
what is ours.

## Git access from the lab machine

The lab machine has its own SSH key (not copied from the main system, so one machine can be
revoked without touching the other) at `~/.ssh/id_ed25519`, with its `Host github.com` entry
in `~/.ssh/config`. Verify with `ssh -T git@github.com`: it has to respond `Hi Wintch!`.
