#!/usr/bin/env python3
"""steam-launch-options-audit.py - list every installed Steam title's LaunchOptions and flag stale ones.

Read-only: it parses localconfig.vdf and never writes it (Steam rewrites that file from memory
while it runs, so edits must be made in the Steam UI or with Steam fully shut down).

Flags:
  XR_RUNTIME_JSON   pins the OpenXR runtime (usually Monado); wrong when running under SteamVR/Oasis
  MONADO            any other mention of monado (IPC_IGNORE_VERSION, monado_comp_ipc, paths)
  MONADO-IPC        PRESSURE_VESSEL_FILESYSTEMS_RW=/run/user/*/monado_comp_ipc (only useful with Monado)
  PROTON_LOG        debug logging left on (large logs, slower start)

Usage: steam-launch-options-audit.py [--installed] [--strict] [--vdf PATH]
  --installed  only list titles installed in a library (default: ALL titles with LaunchOptions,
               installed or not; uninstalled ones are marked "(not installed)")
  --strict  exit 1 when any flag is raised (default exit 0)
Exit 2 when the file cannot be read.
"""
import argparse
import glob
import os
import re
import sys

HOME = os.path.expanduser("~")
STEAM = os.path.join(HOME, ".steam/debian-installation")


def tokenize(text):
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|([{}])', text):
        if m.group(2):
            yield m.group(2)
        else:
            yield m.group(1)


def parse_vdf(text):
    toks = list(tokenize(text))
    pos = 0

    def block():
        nonlocal pos
        d = {}
        while pos < len(toks):
            t = toks[pos]
            if t == "}":
                pos += 1
                return d
            key = t
            pos += 1
            if pos < len(toks) and toks[pos] == "{":
                pos += 1
                d[key] = block()
            else:
                d[key] = toks[pos]
                pos += 1
        return d

    return block()


def find_apps(tree):
    """localconfig.vdf: UserLocalConfigStore/Software/Valve/Steam/apps (key case varies)."""
    def ci(d, k):
        for kk, v in d.items():
            if kk.lower() == k.lower() and isinstance(v, dict):
                return v
        return {}
    cur = ci(tree, "UserLocalConfigStore")
    for k in ("Software", "Valve", "Steam"):
        cur = ci(cur, k)
    return ci(cur, "apps")


def installed_titles():
    libs = [STEAM]
    vdf = os.path.join(STEAM, "steamapps/libraryfolders.vdf")
    try:
        txt = open(vdf, errors="replace").read()
        libs = re.findall(r'"path"\s+"([^"]+)"', txt) or libs
    except OSError:
        pass
    res = {}
    for lib in libs:
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                t = open(acf, errors="replace").read()
            except OSError:
                continue
            a = re.search(r'"appid"\s+"(\d+)"', t)
            n = re.search(r'"name"\s+"([^"]*)"', t)
            if a:
                res[a.group(1)] = (n.group(1) if n else "?", lib)
    return res


def flags_for(opts):
    f = []
    if "XR_RUNTIME_JSON" in opts:
        f.append("XR_RUNTIME_JSON")
    if re.search(r"monado", opts, re.I):
        f.append("MONADO")
    if re.search(r"PRESSURE_VESSEL_FILESYSTEMS_RW=\S*monado_comp_ipc", opts):
        f.append("MONADO-IPC")
    if "PROTON_LOG" in opts:
        f.append("PROTON_LOG")
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--installed", action="store_true")
    ap.add_argument("--all", action="store_true", help=argparse.SUPPRESS)  # old spelling, now the default
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--vdf", default=None)
    a = ap.parse_args()
    path = a.vdf
    if not path:
        cands = glob.glob(os.path.join(STEAM, "userdata/*/config/localconfig.vdf"))
        if not cands:
            print("no localconfig.vdf found under %s/userdata" % STEAM, file=sys.stderr)
            return 2
        path = max(cands, key=os.path.getmtime)
    try:
        tree = parse_vdf(open(path, errors="replace").read())
    except OSError as e:
        print("cannot read %s: %s" % (path, e), file=sys.stderr)
        return 2
    apps = find_apps(tree)
    inst = installed_titles()
    rows, nflag = [], 0
    for appid, d in apps.items():
        if not isinstance(d, dict):
            continue
        opts = d.get("LaunchOptions", "")
        is_inst = appid in inst
        if not opts or (not is_inst and a.installed):
            continue
        fl = flags_for(opts)
        nflag += bool(fl)
        rows.append((int(appid) if appid.isdigit() else 0, appid, inst.get(appid, ("(not installed)", ""))[0], opts, fl))
    rows.sort()
    print("localconfig: %s (read-only)" % path)
    print("titles with LaunchOptions: %d (%s), installed titles seen in libraries: %d" % (
        len(rows), "installed only" if a.installed else "installed + not installed", len(inst)))
    for _, appid, name, opts, fl in rows:
        print("%-9s %-38s %s" % (appid, name[:38], ("[" + ",".join(fl) + "]") if fl else "[ok]"))
        print("          %s" % opts)
    print("flagged titles: %d (%d of them installed)" % (nflag, sum(1 for r in rows if r[4] and r[1] in inst)))
    if nflag:
        print("hint: under SteamVR/Oasis the Monado variables are dead weight for OpenVR titles and wrong for OpenXR "
              "titles; edit in the Steam UI (or with Steam fully shut down), never while Steam is running. "
              "DOOM VFR (650000): the original line is saved in ~/vr/doom650000-launchoptions.original and must "
              "be restored after the debugging (see docs/139).")
    return 1 if (a.strict and nflag) else 0


if __name__ == "__main__":
    sys.exit(main())
