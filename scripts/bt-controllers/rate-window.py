#!/usr/bin/env python3
"""usage: rate-window.py SECONDS -> prints 'Left=<Hz> Right=<Hz>' (mean report rate per controller over the window; -1 = no hidraw)."""
import glob, os, select, sys, time
secs = float(sys.argv[1]); fds = {}
for h in glob.glob("/sys/class/hidraw/hidraw*"):
    try: u = open(h + "/device/uevent").read()
    except OSError: continue
    if "0000045E:0000066A" in u:
        fds["Left" if "Left" in u else "Right"] = os.open("/dev/" + os.path.basename(h), os.O_RDONLY | os.O_NONBLOCK)
n = {s: 0 for s in ("Left", "Right")}; t0 = time.time()
while time.time() - t0 < secs and fds:
    r, _, _ = select.select(list(fds.values()), [], [], 0.2)
    for s, fd in list(fds.items()):
        if fd in r:
            try:
                while True: n[s] += os.read(fd, 128)[:1] == b"\x01"
            except BlockingIOError: pass
            except OSError: fds.pop(s)
print(" ".join(f"{s}={n[s]/secs:.0f}Hz" if s in fds or n[s] else f"{s}=-1" for s in ("Left", "Right")))
