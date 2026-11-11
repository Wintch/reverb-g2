#!/usr/bin/env python3
"""Check that the repo can be published without leaking anything or hitting GitHub's
limits. Modifies nothing. Run it before every push to a public remote.

    ./scripts/check-publishable.py                    # every blob in the whole history
    ./scripts/check-publishable.py --head             # only the files in HEAD's tree
    ./scripts/check-publishable.py --head --worktree  # HEAD's tree + the working tree
    ./scripts/check-publishable.py --worktree         # whole history + the working tree

`--head` is for verifying a cleanup BEFORE a history rewrite: it answers "is the tree I am
about to commit clean?" without being drowned by old blobs that the rewrite will drop anyway.
`--worktree` adds the files as they are on disk now (tracked and untracked, but not ignored),
which is what the next commit would contain.

The patterns to look for do NOT live in here: they are read from `scripts/.private-patterns`,
which is in .gitignore. That way the checker does not publish the very thing it looks for —
which is the mistake we made the first time, when the script carried the address and serial
number it was redacting inside itself.

Format of .private-patterns: one pattern per line, lines starting with # are ignored.

Checks (over ALL objects in the repo by default, not just HEAD):

  1. that there is a single identity across the commits
  2. that no blob exceeds 100 MB (GitHub rejects them)
  3. that no private literal pattern appears in the content of any blob,
     **including binaries, compressed files and UTF-16 text**
  4. that no blob contains an identifying value of a generic class, whether or not it is
     listed in .private-patterns:
        - MAC / Bluetooth device addresses   six hex bytes joined by ':' or '-'
        - RFC 1918 IPv4 addresses            192.168.x.x, 10.x.x.x, 172.16-31.x.x
        - SteamID64                          7656119xxxxxxxxxx
     These are reported like literal hits and make the check fail. Some hits will be false
     positives (a documentation example, a version string that looks like an address):
     the checker prints them and a human decides. The all-zero and all-ff MAC are skipped.

Point 3 is the one that matters. `git grep -I` skips binaries, so a .gz with private data
inside passes a git-grep-based check without anyone looking at it. That is exactly what
happened to us: an old nvidia-bug-report, carrying the headset's serial number and the
network card's MAC address, survived the cleanup and reached the remote inside a
compressed blob. Windows tools (USBPcap/Procmon exports, `dxdiag`, PowerShell redirections)
write UTF-16, where a literal such as an address is interleaved with NUL bytes and a plain
byte search never sees it; so every body is also decoded as UTF-16 when it has a BOM
(ff fe / fe ff) or looks like UTF-16 (many NUL bytes at alternating offsets).

No dependencies: stdlib only.
"""

import argparse
import gzip
import re
import subprocess
import sys
from pathlib import Path

LIMIT = 100 * 1024 * 1024           # GitHub rejects blobs larger than 100 MB
BOLD, RED, RESET = "\033[1m", "\033[31m", "\033[0m"
MAX_EXAMPLES = 3                    # distinct matches printed per file and class

_OCTET = rb"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
CLASSES = {
    "MAC address": re.compile(
        rb"(?<![0-9a-f])(?<![0-9a-f][:-])[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}(?![0-9a-f])(?![:-][0-9a-f]{2})",
        re.IGNORECASE),
    # RFC 1918: 192.168.A.B | 10.A.B.C | 172.16-31.A.B, every octet validated 0-255
    "RFC1918 IPv4": re.compile(
        rb"(?<![\d.])(?:192\.168\.%(o)b\.%(o)b|10\.%(o)b\.%(o)b\.%(o)b"
        rb"|172\.(?:1[6-9]|2\d|3[01])\.%(o)b\.%(o)b)(?!\d)" % {b"o": _OCTET}),
    "SteamID64": re.compile(rb"(?<!\d)7656119\d{10}(?!\d)"),
}

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


class BlobReader:
    """One long-lived `git cat-file --batch`, instead of one process per blob."""

    def __init__(self):
        self.p = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE)

    def read(self, sha):
        self.p.stdin.write(sha.encode() + b"\n")
        self.p.stdin.flush()
        header = self.p.stdout.readline().split()
        if len(header) < 3:
            return b""
        data = self.p.stdout.read(int(header[2]))
        self.p.stdout.read(1)               # trailing newline
        return data

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def looks_utf16(raw):
    """'le' / 'be' / None. A BOM decides; otherwise many NULs at alternating offsets."""
    if raw[:2] == b"\xff\xfe":
        return "le"
    if raw[:2] == b"\xfe\xff":
        return "be"
    sample = raw[:65536]
    pairs = len(sample) // 2
    if pairs < 16:
        return None
    odd = sample[1:2 * pairs:2].count(0)     # NUL at odd offsets -> UTF-16LE ASCII text
    even = sample[0:2 * pairs:2].count(0)    # NUL at even offsets -> UTF-16BE ASCII text
    if odd > pairs * 0.3 and even < pairs * 0.05:
        return "le"
    if even > pairs * 0.3 and odd < pairs * 0.05:
        return "be"
    return None


def bodies_of(raw):
    """The raw bytes plus every decoded view of them (gzip, UTF-16), as bytes to search."""
    out = [raw]
    if raw[:2] == b"\x1f\x8b":                       # gzip
        try:
            out.append(gzip.decompress(raw))
        except Exception:
            pass
    for b in list(out):
        enc = looks_utf16(b)
        if enc:
            try:
                out.append(b.decode("utf-16-" + enc, errors="replace").encode("utf-8", errors="replace"))
            except Exception:
                pass
    return out


def class_hits(bodies):
    """{class name: sorted distinct matches} over every body."""
    found = {}
    for b in bodies:
        for name, rx in CLASSES.items():
            for m in rx.finditer(b):
                text = m.group(0).decode("ascii", errors="replace")
                if name == "MAC address":
                    digits = re.sub(r"[:-]", "", text).lower()
                    if len(set(digits)) == 1 and digits[0] in "0f":
                        continue                       # 00:..:00 / ff:..:ff carry no identity
                found.setdefault(name, set()).add(text)
    return {k: sorted(v) for k, v in found.items()}


ap = argparse.ArgumentParser(description="Check that the repo is publishable.")
ap.add_argument("--head", action="store_true",
                help="check only the files in HEAD's tree, not every blob in history")
ap.add_argument("--worktree", action="store_true",
                help="also check the working tree (tracked and untracked, not ignored)")
args = ap.parse_args()

root = Path(git("rev-parse", "--show-toplevel").strip())
patterns_file = root / "scripts" / ".private-patterns"

say("commit identity")
authors = sorted(set(git("log", "--format=%an <%ae>", *(["HEAD"] if args.head else [])).splitlines()))
for a in authors:
    print(f"        {a}")
ok("a single identity") if len(authors) == 1 else bad("more than one identity")

# What to scan: {sha: path} for git blobs, and a list of working-tree files.
inventory = {}
blobs = {}
if args.head:
    scope = "HEAD tree"
    for entry in git("ls-tree", "-r", "-l", "-z", "HEAD").split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        mode, kind, sha, size = meta.split(None, 3)
        if kind == "blob":
            inventory.setdefault(sha, path)
            blobs[sha] = int(size.strip())
else:
    scope = "all history"
    for line in git("rev-list", "--objects", "--all").splitlines():
        sha, _, path = line.partition(" ")
        inventory.setdefault(sha, path or "<no path>")
    types = git("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                "--batch-all-objects")
    for line in types.splitlines():
        sha, kind, size = line.split()
        if kind == "blob":
            blobs[sha] = int(size)

worktree = []                       # (path, size)
if args.worktree:
    scope += " + working tree"
    listing = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for rel in sorted(set(p for p in listing.split("\0") if p)):
        f = root / rel
        if f.is_symlink() or not f.is_file() or f == patterns_file:
            continue
        worktree.append((rel, f.stat().st_size))

say(f"blob sizes ({scope})")
large = [(inventory.get(s, "?"), n) for s, n in blobs.items() if n > LIMIT]
large += [(p, n) for p, n in worktree if n > LIMIT]
if large:
    bad("files over GitHub's 100 MB limit:")
    for p, n in sorted(large, key=lambda x: -x[1]):
        print(f"        {n / 1048576:8.1f} MB  {p}")
else:
    ok(f"none of the {len(blobs)} blobs{f' / {len(worktree)} working-tree files' if worktree else ''}"
       " exceeds 100 MB")
size = next((l.split(": ", 1)[1] for l in git("count-objects", "-vH").splitlines()
             if l.startswith("size-pack:")), "?")
print(f"   {'.git (size-pack)':<38} {size}")

say(f"private patterns and identifying classes ({scope})")
patterns = []
if not patterns_file.exists():
    print(f"   (no {patterns_file.relative_to(root)}: literal patterns skipped, classes still checked)")
    print("   Create that file with one pattern per line to check for addresses,")
    print("   serial numbers, MACs or anything else that must not ship. It is gitignored.")
else:
    ignored = subprocess.run(["git", "check-ignore", "-q", str(patterns_file)]).returncode == 0
    ok("the patterns file is gitignored") if ignored else \
        bad("the patterns file is NOT gitignored — it would ship with the repo")
    patterns = [l.strip().encode() for l in patterns_file.read_text().splitlines()
                if l.strip() and not l.startswith("#")]


def scan(raw):
    """-> (literal patterns found, {class: matches}) for one file's bytes."""
    bodies = bodies_of(raw)
    lit = [p.decode() for p in patterns if any(p in b for b in bodies)]
    return lit, class_hits(bodies)


git_dirty = []          # (sha, path, literals, classes)
reader = BlobReader()
for sha in blobs:
    lit, cls = scan(reader.read(sha))
    if lit or cls:
        git_dirty.append((sha, inventory.get(sha, "?"), lit, cls))
reader.close()

wt_dirty = []           # (path, literals, classes)
for rel, _ in worktree:
    try:
        raw = (root / rel).read_bytes()
    except OSError:
        continue
    lit, cls = scan(raw)
    if lit or cls:
        wt_dirty.append((rel, lit, cls))


def show(label, lit, cls):
    for pat in lit:
        print(f"        {label}  <- literal: {pat}")
    for name, matches in cls.items():
        shown = ", ".join(matches[:MAX_EXAMPLES]) + (f", ... (+{len(matches) - MAX_EXAMPLES})"
                                                      if len(matches) > MAX_EXAMPLES else "")
        print(f"        {label}  <- {name} x{len(matches)}: {shown}")


total_blobs = len(blobs)
if git_dirty:
    bad(f"{len(git_dirty)} of {total_blobs} blob(s) contain private patterns or identifying values:")
    for sha, path, lit, cls in git_dirty:
        show(f"{sha[:12]}  {path}", lit, cls)
else:
    ok(f"nothing in any of the {total_blobs} blobs (binaries, .gz and UTF-16 included)")

if worktree:
    if wt_dirty:
        bad(f"{len(wt_dirty)} of {len(worktree)} working-tree file(s) contain private patterns "
            "or identifying values:")
        for rel, lit, cls in wt_dirty:
            show(rel, lit, cls)
    else:
        ok(f"nothing in any of the {len(worktree)} working-tree files")

if git_dirty and not args.head:
    # A blob that no commit references is not in the inventory, so it would never be
    # pushed — but it is still sitting in this clone's object store, typically left
    # behind by an earlier filter-repo. That needs a gc, not another history rewrite,
    # and telling you to force-push would not remove it.
    reachable = sorted({s for s, _, _, _ in git_dirty if s in inventory and inventory[s] != "?"})
    unreachable = sorted({s for s, _, _, _ in git_dirty if s not in inventory})

    if unreachable:
        print(f"\n        {len(unreachable)} of these are UNREACHABLE (path '?'): no commit")
        print("        references them, so they would not be pushed. They are local")
        print("        leftovers. Drop them from this clone with:")
        print("            git reflog expire --expire=now --all")
        print("            git gc --prune=now")
    if reachable:
        print(f"\n        {len(reachable)} are reachable and WOULD be published."
              " To strip them from history:")
        print("            printf '%s\\n' " + " ".join(u[:12] for u in reachable)
              + " > /tmp/shas")
        print("            git filter-repo --force --strip-blobs-with-ids /tmp/shas")
        print("        and then force-push, because this rewrites history.")
        print("        (Class hits that are false positives do not need stripping: judge each one.)")
elif git_dirty:
    print("\n        --head: fix these files in the tree (or accept the false positives),"
          " then commit; history is not examined in this mode.")

say("verdict")
print(f"   scope: {scope}"
      f" | blobs scanned: {total_blobs} | working-tree files scanned: {len(worktree)}")
print(f"   blobs with hits: {len(git_dirty)} | working-tree files with hits: {len(wt_dirty)}")
if failures:
    print("   DO NOT publish until the above is resolved.")
    print("   The cleanup procedure is in docs/17-publishing.md.")
else:
    print("   Publishable.")
sys.exit(failures)
