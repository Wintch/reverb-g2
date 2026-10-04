#!/usr/bin/env python3
"""oasis-binding-fix.py - find and repair Oasis' shipped HP-controller bindings that no longer match the game.

Why (docs/139): the Oasis driver ships per-game bindings (resources/input/steam.app.<id>_hpmotioncontroller.json).
If a game update renames its action set (I Expect You To Die: shipped '/actions/ieytd_default', the game now
declares '/actions/ieytd1_default') SteamVR cannot apply the binding and the game sees NO controller input.

  oasis-binding-fix.py scan                 read-only: list installed games whose shipped binding does not match
  oasis-binding-fix.py fix [--apply]        write corrected bindings to ~/vr/oasis-bindings-fixed/ (dry run by default);
                                            with --apply also copy them into the Oasis input dir (originals backed up
                                            under ~/vr/oasis-bindings-fixed/original/). Steam updates of the Oasis
                                            driver overwrite them: re-run after an update.
Only a rename of an action set is repaired, and only when every action leaf the binding uses exists in the
game's action set (otherwise the entry is reported, not touched).
"""
import glob, json, os, re, shutil, sys

HOME = os.path.expanduser("~")
LIBS = [HOME + "/.steam/debian-installation", "/mnt/videos/SteamLibrary", "/mnt/win5/SteamLibrary"]
OASIS_INPUT = os.environ.get("OASIS_INPUT", "/mnt/videos/SteamLibrary/steamapps/common/Oasis Driver for Windows Mixed Reality/resources/input")
OUT = HOME + "/vr/oasis-bindings-fixed"


def installed_dirs():
    for lib in LIBS:
        for mf in glob.glob(lib + "/steamapps/appmanifest_*.acf"):
            m = re.search(r"appmanifest_(\d+)\.acf", mf)
            txt = open(mf, errors="replace").read()
            d = re.search(r'"installdir"\s*"([^"]+)"', txt)
            if m and d:
                yield m.group(1), os.path.join(lib, "steamapps/common", d.group(1))


def game_actions(gdir):
    """{action_set: set(leaf names)} from the game's actions.json (searched shallowly)."""
    for p in [gdir + "/actions.json"] + glob.glob(gdir + "/*/actions.json") + glob.glob(gdir + "/*/*/actions.json") + glob.glob(gdir + "/*/*/*/actions.json"):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        sets = {}
        for a in d.get("actions", []):
            m = re.match(r"(/actions/[^/]+)/(?:in|out)/(.+)$", a.get("name", ""))
            if m:
                sets.setdefault(m.group(1), set()).add(m.group(2))
        if sets:
            return p, sets
    return None, {}


def binding_sets(b):
    """{action_set: set(leaf names used)} from a binding file."""
    used = {}
    s = json.dumps(b)
    for m in re.finditer(r"(/actions/[^/\"]+)/(?:in|out)/([^\"]+)", s):
        used.setdefault(m.group(1), set()).add(m.group(2))
    return used


def analyse():
    rows = []
    for app, gdir in installed_dirs():
        bf = f"{OASIS_INPUT}/steam.app.{app}_hpmotioncontroller.json"
        if not os.path.isfile(bf):
            continue
        ap, gsets = game_actions(gdir)
        if not gsets:
            rows.append((app, "NO-ACTIONS-JSON", "game has no readable actions.json (OpenVR legacy or other layout)", None))
            continue
        b = json.load(open(bf))
        used = binding_sets(b)
        missing_sets = [s for s in used if s not in gsets]
        if not missing_sets:
            rows.append((app, "OK", f"binding sets {sorted(used)} exist in the game", None))
            continue
        if len(used) == 1 and len(gsets) >= 1:
            old = next(iter(used))
            cands = [s for s in gsets if used[old] <= gsets[s]]
            if len(cands) == 1:
                rows.append((app, "RENAMED-SET", f"{old} -> {cands[0]} (all {len(used[old])} actions exist there)", (bf, old, cands[0])))
                continue
            best = max(gsets, key=lambda s: len(used[old] & gsets[s]))
            rows.append((app, "MISMATCH", f"binding uses {old}; game sets {sorted(gsets)}; best overlap {best} "
                         f"({len(used[old] & gsets[best])}/{len(used[old])}); not auto-fixable", None))
        else:
            rows.append((app, "MISMATCH", f"binding sets {sorted(used)} vs game sets {sorted(gsets)}; not auto-fixable", None))
    return rows


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("scan", "fix"):
        print(__doc__); return 2
    rows = analyse()
    bad = [r for r in rows if r[1] not in ("OK", "NO-ACTIONS-JSON")]
    for app, kind, msg, _ in sorted(rows, key=lambda r: (r[1] == "OK", r[0])):
        if cmd == "scan" or kind != "OK":
            print(f"{kind:16s} appid {app}: {msg}")
    print(f"oasis-binding-fix: {len(rows)} shipped bindings checked, {len(bad)} problem(s)")
    if cmd == "scan":
        return 1 if bad else 0
    apply = "--apply" in sys.argv[2:]
    os.makedirs(OUT + "/original", exist_ok=True)
    for app, kind, msg, fix in rows:
        if kind != "RENAMED-SET":
            continue
        bf, old, new = fix
        txt = open(bf).read()
        fixed = txt.replace(old + "/", new + "/").replace(f'"{old}"', f'"{new}"')
        json.loads(fixed)   # must stay valid JSON
        name = os.path.basename(bf)
        open(f"{OUT}/{name}", "w").write(fixed)
        if not apply:
            print(f"WOULD    write {OUT}/{name} and install it over {bf}"); continue
        if not os.path.exists(f"{OUT}/original/{name}"):
            shutil.copy2(bf, f"{OUT}/original/{name}")
        shutil.copyfile(f"{OUT}/{name}", bf)
        print(f"FIXED    appid {app}: {old} -> {new} (original kept in {OUT}/original/{name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
