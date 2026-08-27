#!/usr/bin/env python3
"""deploy-check.py -- catch drift between this repo's scripts/ and the deployed copies in ~/vr.

Why this exists (2026-08-27 night, three bites in one session): ~/vr/ holds COPIES of repo
scripts, not symlinks. vr-launcher.py was edited in the repo and a headset test silently ran
the stale ~/vr copy; basalt-g2-config.json the same; and demo-recorder.py had crashed on
EVERY launch since it was born (2026-08-26) because the modules it imports
(rig_telemetry.py, gui_env.py, wmr_usb_ids.py) existed only in the repo -- so a whole night
of "auto-recorded" variant sessions never existed. Run this BEFORE trusting that a launch
reflects an edit, and at the start of every session.

Reports, without changing anything:
  (a) shared files whose content differs (and which side is newer)
  (b) Python modules imported by any ~/vr/*.py that are missing beside it
  (c) repo scripts that have no deployed copy at all (informational -- many never need one)

Exit status: 0 = clean, 1 = drift or missing modules found (so it can gate a session script).
Deploying is deliberately NOT automated here: a ~/vr copy can carry a local-only fix that
was never committed (found live: vr-power-setup.sh's USB autosuspend block), and blindly
copying repo -> ~/vr would erase it. Diff, decide, then copy by hand.

Usage: deploy-check.py [--repo DIR] [--deploy DIR] [--quiet]
"""
import argparse
import ast
import os
import sys
from pathlib import Path

DEFAULT_REPO = Path(__file__).resolve().parent
DEFAULT_DEPLOY = Path.home() / "vr"

# Repo modules that are imported by name; anything else imported is stdlib/site-packages.
LOCAL_MODULE_HINT = {"rig_telemetry", "gui_env", "wmr_usb_ids", "vr_i18n", "game_stop"}


def local_imports(py_path):
    """Top-level module names imported by a Python file (import X / from X import ...)."""
    try:
        tree = ast.parse(py_path.read_text(errors="replace"))
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--deploy", type=Path, default=DEFAULT_DEPLOY)
    ap.add_argument("--quiet", action="store_true", help="only print problems")
    args = ap.parse_args()
    repo, dep = args.repo, args.deploy
    problems = 0

    # (a) shared files that differ
    shared = sorted(p.name for p in repo.iterdir() if p.is_file() and (dep / p.name).exists())
    differ = []
    for name in shared:
        a, b = repo / name, dep / name
        if a.read_bytes() != b.read_bytes():
            newer = "repo" if a.stat().st_mtime > b.stat().st_mtime else "~/vr"
            differ.append((name, newer))
    if differ:
        problems += len(differ)
        print(f"DRIFT: {len(differ)} of {len(shared)} shared files differ (newer side in brackets):")
        for name, newer in differ:
            print(f"  {name}  [{newer}]")
    elif not args.quiet:
        print(f"ok: all {len(shared)} shared files identical")

    # (b) modules imported by deployed .py files but missing beside them
    missing = {}
    for py in sorted(dep.glob("*.py")):
        for mod in local_imports(py):
            if mod in LOCAL_MODULE_HINT or (repo / f"{mod}.py").exists():
                if not (dep / f"{mod}.py").exists() and not (dep / mod).exists():
                    missing.setdefault(mod, []).append(py.name)
    if missing:
        problems += len(missing)
        print("MISSING MODULES in the deploy dir (importers in parentheses):")
        for mod, users in sorted(missing.items()):
            print(f"  {mod}.py  ({', '.join(users)})")
    elif not args.quiet:
        print("ok: every repo module imported from the deploy dir is present there")

    # (c) informational: repo scripts with no deployed copy
    if not args.quiet:
        undeployed = sorted(p.name for p in repo.iterdir()
                            if p.is_file() and p.suffix in {".py", ".sh", ".json"} and not (dep / p.name).exists())
        print(f"info: {len(undeployed)} repo scripts have no copy in {dep} (fine unless something in ~/vr runs them)")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
