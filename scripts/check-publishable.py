#!/usr/bin/env python3
"""Check that the repo can be published without leaking anything or hitting GitHub's
limits. Modifies nothing. Run it before every push to a public remote.

    ./scripts/check-publishable.py

The patterns to look for do NOT live in here: they are read from `scripts/.private-patterns`,
which is in .gitignore. That way the checker does not publish the very thing it looks for —
which is the mistake we made the first time, when the script carried the address and serial
number it was redacting inside itself.

Format of .private-patterns: one pattern per line, lines starting with # are ignored.

Checks, over ALL objects in the repo and not just HEAD:

  1. that there is a single identity across the commits
  2. that no blob exceeds 100 MB (GitHub rejects them)
  3. that no private pattern appears in the content of any blob,
     **including binaries and compressed files**

Point 3 is the one that matters. `git grep -I` skips binaries, so a .gz with private data
inside passes a git-grep-based check without anyone looking at it. That is exactly what
happened to us: an old nvidia-bug-report, carrying the headset's serial number and the
network card's MAC address, survived the cleanup and reached the remote inside a
compressed blob.

No dependencies: stdlib only.
"""

import gzip
import subprocess
import sys
from pathlib import Path

LIMIT = 100 * 1024 * 1024           # GitHub rejects blobs larger than 100 MB
BOLD, RED, RESET = "\033[1m", "\033[31m", "\033[0m"

failures = 0


def git(*args, binary=False):
    r = subprocess.run(["git", *args], capture_output=True)
    if r.returncode:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace')}")
    return r.stdout if binary else r.stdout.decode(errors="replace")


def say(t):
    print(f"\n{BOLD}== {t}{RESET}")


def ok(t):
    print(f"   ok    {t}")


def bad(t):
    global failures
    failures = 1
    print(f"   {RED}FAIL {RESET} {t}")


root = Path(git("rev-parse", "--show-toplevel").strip())

say("commit identity")
authors = sorted(set(git("log", "--format=%an <%ae>").splitlines()))
for a in authors:
    print(f"        {a}")
ok("a single identity") if len(authors) == 1 else bad("more than one identity")

# blob inventory: sha -> path (the first one that references it)
inventory = {}
for line in git("rev-list", "--objects", "--all").splitlines():
    sha, _, path = line.partition(" ")
    inventory.setdefault(sha, path or "<no path>")

types = git("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            "--batch-all-objects")
blobs = {}
for line in types.splitlines():
    sha, kind, size = line.split()
    if kind == "blob":
        blobs[sha] = int(size)

say("blob sizes")
large = [(s, n) for s, n in blobs.items() if n > LIMIT]
if large:
    bad("blobs over GitHub's 100 MB limit:")
    for s, n in sorted(large, key=lambda x: -x[1]):
        print(f"        {n / 1048576:8.1f} MB  {inventory.get(s, '?')}")
else:
    ok(f"none of the {len(blobs)} blobs exceeds 100 MB")
size = next((l.split(": ", 1)[1] for l in git("count-objects", "-vH").splitlines()
             if l.startswith("size-pack:")), "?")
print(f"   {'.git (size-pack)':<38} {size}")

say("private patterns, across every blob")
patterns_file = root / "scripts" / ".private-patterns"
if not patterns_file.exists():
    print(f"   (no {patterns_file.relative_to(root)}, skipped)")
    print("   Create that file with one pattern per line to check for addresses,")
    print("   serial numbers, MACs or anything else that must not ship. It is gitignored.")
else:
    ignored = subprocess.run(["git", "check-ignore", "-q", str(patterns_file)]).returncode == 0
    ok("the patterns file is gitignored") if ignored else \
        bad("the patterns file is NOT gitignored — it would ship with the repo")

    patterns = [l.strip().encode() for l in patterns_file.read_text().splitlines()
                if l.strip() and not l.startswith("#")]
    dirty = []
    for sha in blobs:
        raw = git("cat-file", "blob", sha, binary=True)
        bodies = [raw]
        if raw[:2] == b"\x1f\x8b":                   # gzip
            try:
                bodies.append(gzip.decompress(raw))
            except Exception:
                pass
        for pat in patterns:
            if any(pat in b for b in bodies):
                dirty.append((sha, inventory.get(sha, "?"), pat.decode()))

    if dirty:
        bad(f"{len(dirty)} blob(s) contain private patterns:")
        for sha, path, pat in dirty:
            print(f"        {sha[:12]}  {path}  <- {pat}")
        print("\n        To strip them from history:")
        unique = sorted({s for s, _, _ in dirty})
        print("            printf '%s\\n' " + " ".join(u[:12] for u in unique)
              + " > /tmp/shas")
        print("            git filter-repo --force --strip-blobs-with-ids /tmp/shas")
        print("        and then force-push, because this rewrites history.")
    else:
        ok(f"no private pattern in any of the {len(blobs)} blobs (binaries and .gz included)")

say("verdict")
if failures:
    print("   DO NOT publish until the above is resolved.")
    print("   The cleanup procedure is in docs/17-publishing.md.")
else:
    print("   Publishable.")
sys.exit(failures)
