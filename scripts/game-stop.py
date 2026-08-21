#!/usr/bin/env python3
"""Stop (or list) Steam/Proton games by appid, for real -- the whole Wine tree, verified.

Why this exists (2026-08-21, T244 close): killing the Steam wrapper (`reaper SteamLaunch
AppId=N`, `steam-launch-wrapper`, the `proton` python) or matching the game's name in a
cmdline does NOT stop the game. The Windows binary keeps running under wineserver inside
the pressure-vessel sandbox, keeps its OpenVR/OpenXR session open, keeps rendering. Two
titles were found alive at once this way (Dead Herring VR rendering in the background for
the whole Wolfenstein Cyberpilot run: 151 "Delivered frame"/s = two clients, CPU/GPU
numbers invalid), and when monado-service was taken down both orphans died with xrizer
`ERROR_INSTANCE_LOST` crash dialogs. The reliable handle is the environment every process
of a Proton launch carries: STEAM_COMPAT_DATA_PATH=.../compatdata/<appid> (and SteamAppId /
SteamGameId). This script finds every process by that, SIGTERMs the Windows main binaries
first (lets the game save/quit), waits, then SIGKILLs whatever is left, and verifies.

Usage:
  game-stop.py status              # list running Proton trees: appid, exe names, ages
  game-stop.py stop <appid> [...]  # stop one or more by appid
  game-stop.py stop all            # stop every Proton tree found
Exit 0 when nothing of the requested appid(s) is left, 1 otherwise.
No root. Does not touch Steam itself, Monado, or non-Proton processes.
"""
import os
import re
import signal
import sys
import time

PROC = "/proc"


def read_environ(pid):
    try:
        with open(f"{PROC}/{pid}/environ", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    env = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    return env


def read_cmdline(pid):
    try:
        with open(f"{PROC}/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def proc_age_s(pid):
    try:
        st = os.stat(f"{PROC}/{pid}")
        return int(time.time() - st.st_ctime)
    except OSError:
        return -1


def scan():
    """appid -> list of (pid, cmdline)."""
    trees = {}
    me = os.getpid()
    for name in os.listdir(PROC):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == me or pid == os.getppid():
            continue
        env = read_environ(pid)
        if not env:
            continue
        appid = None
        m = re.search(r"/compatdata/(\d+)/?$", env.get("STEAM_COMPAT_DATA_PATH", ""))
        if m:
            appid = m.group(1)
        elif env.get("SteamAppId", "").isdigit():
            appid = env["SteamAppId"]
        if appid is None:
            continue
        trees.setdefault(appid, []).append((pid, read_cmdline(pid)))
    return trees


def is_windows_main(cmd):
    # The game's own binary: a Wine process whose cmdline starts with a Windows path
    # (drive letter), excluding Wine's system services. The Linux-side wrappers
    # (pv-adverb, proton's python, srt-bwrap) also carry the .exe path in their
    # cmdline but start with a /unix path, so they are not "main".
    low = cmd.lower()
    if not re.match(r"^[a-z]:\\", low):
        return False
    for sysexe in ("services.exe", "winedevice.exe", "plugplay.exe", "svchost.exe",
                   "rpcss.exe", "explorer.exe", "tabtip.exe", "xalia.exe",
                   "conhost.exe", "start.exe", "steam.exe", "unitycrashhandler"):
        if sysexe in low:
            return False
    return True


def show(trees):
    if not trees:
        print("no Proton game trees running")
        return
    for appid, procs in sorted(trees.items()):
        mains = [c for _, c in procs if is_windows_main(c)]
        oldest = max(proc_age_s(p) for p, _ in procs)
        names = set()
        for m in mains:
            head = m.lower().split(".exe", 1)[0]
            names.add(head.replace("\\", "/").rsplit("/", 1)[-1] + ".exe")
        label = ", ".join(sorted(names)) or "(no main exe found)"
        print(f"appid {appid}: {len(procs)} processes, oldest {oldest}s, main: {label}")


def kill_set(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"  no permission to signal {pid}", file=sys.stderr)


def stop(appids):
    trees = scan()
    targets = list(trees) if appids == ["all"] else [a for a in appids if a in trees]
    missing = [] if appids == ["all"] else [a for a in appids if a not in trees]
    for a in missing:
        print(f"appid {a}: nothing running")
    for appid in targets:
        procs = trees[appid]
        mains = [p for p, c in procs if is_windows_main(c)]
        print(f"appid {appid}: {len(procs)} processes, SIGTERM to {len(mains)} main exe(s) first")
        kill_set(mains, signal.SIGTERM)
        # Give the game up to 8 s to quit on its own (saves, VR session teardown).
        for _ in range(16):
            time.sleep(0.5)
            if appid not in scan():
                break
        left = scan().get(appid, [])
        if left:
            print(f"appid {appid}: {len(left)} left after SIGTERM, SIGTERM to all, then SIGKILL")
            kill_set([p for p, _ in left], signal.SIGTERM)
            time.sleep(2)
            left = scan().get(appid, [])
            if left:
                kill_set([p for p, _ in left], signal.SIGKILL)
                time.sleep(1)
    remaining = scan()
    bad = [a for a in targets if a in remaining]
    for a in targets:
        print(f"appid {a}: {'STILL RUNNING (' + str(len(remaining[a])) + ' procs)' if a in remaining else 'stopped'}")
    return 1 if bad else 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("status", "stop"):
        print(__doc__)
        return 2
    if argv[1] == "status":
        show(scan())
        return 0
    if len(argv) < 3:
        print("stop needs an appid (or 'all')")
        return 2
    return stop(argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
