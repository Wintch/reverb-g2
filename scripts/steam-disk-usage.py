#!/usr/bin/env python3
"""Report installed Steam games sized largest-first, per library, and how much needs
freeing to get each library's filesystem under a target disk-usage percentage.

Read-only -- lists and suggests, never deletes or uninstalls anything. VR-capable titles
(cross-referenced against docs/steam-library-vr-map.json) are marked and kept out of the
"what to remove first" suggestion by default, since this is a VR test-bench and those are
the titles the project actually needs.

Sizes come straight from Steam's own libraryfolders.vdf per-app accounting (what Steam's
own UI uses), not a slower/less accurate du walk.

    ./scripts/steam-disk-usage.py               # target 80%, all libraries
    ./scripts/steam-disk-usage.py --target 75
    ./scripts/steam-disk-usage.py --include-vr  # allow VR titles in the removal suggestion
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VR_MAP = REPO / "docs" / "steam-library-vr-map.json"

STEAM_ROOT_CANDIDATES = [
    Path.home() / ".steam" / "debian-installation",
    Path.home() / ".steam" / "steam",
    Path.home() / ".local" / "share" / "Steam",
]


def find_steam_root():
    for c in STEAM_ROOT_CANDIDATES:
        if (c / "steamapps" / "libraryfolders.vdf").is_file():
            return c
    return None


def parse_libraryfolders(path):
    """Minimal VDF parser -- only understands the shape libraryfolders.vdf actually has
    (flat key/value pairs inside nested { } blocks), not general VDF."""
    libraries = {}
    stack = []
    pending_key = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line == "{":
                stack.append(pending_key)
                pending_key = None
                continue
            if line == "}":
                if stack:
                    stack.pop()
                continue
            m = re.match(r'^"([^"]*)"(?:\s+"([^"]*)")?$', line)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            if val is None:
                pending_key = key
                continue
            if len(stack) == 2 and stack[0] == "libraryfolders" and key == "path":
                idx = stack[1]
                libraries.setdefault(idx, {"apps": {}})["path"] = val
            elif len(stack) == 3 and stack[0] == "libraryfolders" and stack[2] == "apps":
                idx = stack[1]
                libraries.setdefault(idx, {"apps": {}})["apps"][key] = int(val)
    return libraries


def app_name(library_path, appid):
    acf = Path(library_path) / "steamapps" / f"appmanifest_{appid}.acf"
    try:
        text = acf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'"name"\s+"([^"]*)"', text)
    if m:
        return m.group(1)
    m = re.search(r'"installdir"\s+"([^"]*)"', text)
    return m.group(1) if m else None


def load_vr_map():
    if not VR_MAP.is_file():
        return {}
    try:
        data = json.loads(VR_MAP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for entry in data.get("apps", []):
        appid = entry.get("appid")
        if appid is not None:
            out[str(appid)] = entry
    return out


def is_vr(entry):
    if not entry:
        return False
    if entry.get("vr_capable"):
        return True
    flags = entry.get("vr_flags") or {}
    return bool(flags.get("vr_only") or flags.get("vr_supported"))


def human(n):
    g = n / (1024 ** 3)
    return f"{g:,.2f} GiB"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=float, default=80.0, help="target disk-usage percent (default 80)")
    ap.add_argument("--include-vr", action="store_true",
                     help="allow VR-capable titles in the 'remove first' suggestion (default: skipped)")
    args = ap.parse_args()

    root = find_steam_root()
    if root is None:
        print("Could not find a Steam install (looked in ~/.steam/*, ~/.local/share/Steam).", file=sys.stderr)
        return 1

    libfolders_vdf = root / "steamapps" / "libraryfolders.vdf"
    libraries = parse_libraryfolders(libfolders_vdf)
    if not libraries:
        print(f"No libraries parsed out of {libfolders_vdf}.", file=sys.stderr)
        return 1

    vr_map = load_vr_map()
    overall_exit = 0

    for idx in sorted(libraries, key=lambda i: int(i)):
        lib = libraries[idx]
        path = lib.get("path")
        apps = lib.get("apps", {})
        if not path:
            continue

        try:
            total, used, free = shutil.disk_usage(path)
        except OSError as e:
            print(f"=== library {idx}: {path} -- disk_usage failed: {e} ===")
            continue

        pct = used / total * 100
        target_used = total * args.target / 100
        over_bytes = max(0, used - target_used)

        print(f"=== library {idx}: {path} ===")
        print(f"  filesystem: {human(used)} used / {human(total)} total "
              f"({pct:.1f}% used, target {args.target:.0f}%)")
        if over_bytes > 0:
            print(f"  NEEDS FREEING: {human(over_bytes)} to reach {args.target:.0f}%")
            overall_exit = 1
        else:
            print("  OK: already under target.")

        rows = []
        for appid, size in apps.items():
            entry = vr_map.get(appid)
            name = app_name(path, appid) or (entry or {}).get("name") or f"appid {appid}"
            rows.append((size, appid, name, is_vr(entry)))
        rows.sort(key=lambda r: -r[0])

        print(f"  {len(rows)} apps, largest first:")
        for size, appid, name, vr in rows:
            tag = " [VR]" if vr else ""
            print(f"    {human(size):>14}  {name}{tag}  (appid {appid})")

        if over_bytes > 0:
            candidates = rows if args.include_vr else [r for r in rows if not r[3]]
            skipped_vr = len(rows) - len(candidates)
            picked = []
            freed = 0
            for size, appid, name, vr in candidates:
                if freed >= over_bytes:
                    break
                picked.append((size, appid, name))
                freed += size
            print(f"  suggestion to reach target (largest non-VR first"
                  + (", VR included" if args.include_vr else f", {skipped_vr} VR title(s) skipped")
                  + "):")
            if freed < over_bytes:
                print(f"    !! even removing every non-VR title here only frees {human(freed)} of the "
                      f"{human(over_bytes)} needed -- re-run with --include-vr to see the full picture.")
            for size, appid, name in picked:
                print(f"    remove {name}  ({human(size)}, appid {appid})")
        print()

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
