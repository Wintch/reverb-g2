#!/usr/bin/env python3
"""Quick per-game summary from the SteamVR logs of the current/last run: which apps connected to vrserver, their compositor
cumulative stats (presents / dropped / reprojected, fps target), crash dumps and Steam app run windows."""
import os, re, glob, time
L = os.path.expanduser("~/.steam/debian-installation/logs")
def lines(f):
    try: return open(os.path.join(L, f), errors="replace").read().split("\n")
    except OSError: return []
pids = {}
for l in lines("vrserver.txt"):
    m = re.search(r"SetApplicationPid: Setting app (\S+) PID to (\d+)", l)
    if m: pids[m.group(2)] = m.group(1)
print("apps seen by vrserver:", sorted(set(pids.values())) or "none")
cur = None; stats = {}
for l in lines("vrcompositor.txt"):
    m = re.search(r"Cumulative stats for pid: (\d+)", l)
    if m: cur = m.group(1); stats[cur] = {}
    if cur:
        m = re.search(r"Total\.+\s+(\d+) presents\.\s+(\d+) dropped\.\s+(\d+) reprojected", l)
        if m: stats[cur]["total"] = tuple(map(int, m.groups()))
        m = re.search(r"FPS Average Target (\d+)\s+ApplicationTime CPU: ([\d.]+)ms / GPU: ([\d.]+)ms", l)
        if m: stats[cur]["fps"] = m.groups()
for pid, s in stats.items():
    print(f"  pid {pid} ({pids.get(pid, '?')}): {s}")
print("Steam app windows:")
for l in lines("content_log.txt"):
    if "App Running" in l or re.search(r"state changed : Fully Installed,\s*$", l) and "AppID" in l:
        if re.search(r"2026-10-03 20:[2-5]", l): print("  ", l[:120])
dumps = sorted(glob.glob("/tmp/dumps/*.dmp"), key=os.path.getmtime)[-5:]
print("recent dumps:", [(os.path.basename(d), time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(d)))) for d in dumps])
