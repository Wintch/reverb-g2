#!/usr/bin/env python3
"""Does the controller itself report the menu (0x04) and Windows (0x02) buttons? Reads byte 1 of the BT hidraw
input report (shared read, SteamVR/Oasis keeps running). Per hand and button: prompt, 6 s window, log the set of values seen."""
import glob, os, select, subprocess, time
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
LOG = os.path.expanduser("~/bt-menu-probe2.log")
def say(t): subprocess.run(["espeak-ng", "-v", "es", t], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def log(m): open(LOG, "a").write(time.strftime("%H:%M:%S ") + m + "\n")
def find(side):
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try: u = open(h + "/device/uevent").read()
        except OSError: continue
        if "HID_ID=0005:0000045E:0000066A" in u and f"Motion controller - {side}" in u: return "/dev/" + os.path.basename(h)
def window(fd, s):
    seen = set(); t = time.time()
    while time.time() - t < s:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                while True:
                    d = os.read(fd, 128)
                    if d[:1] == b"\x01" and len(d) > 8: seen.add(d[1])
            except BlockingIOError: pass
            except OSError: return None
    return seen
open(LOG, "w").close()
for side, word in (("Left", "izquierdo"), ("Right", "derecho")):
    p = find(side)
    if not p: log(f"{side}: no hidraw"); continue
    fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
    for key, phrase, bit in (("menu", "el botón de menú, las tres rayas", 0x04), ("home", "el botón de Windows", 0x02)):
        say(f"Joy {word}. {phrase}. Toques cortos, no lo mantengas. Ya"); time.sleep(0.5)
        w = window(fd, 8)
        if w is None: log(f"{side} {key}: read error"); continue
        hit = any(v & bit for v in w)
        log(f"{side} {key}: values seen byte1={sorted(hex(v) for v in w)} -> bit {hex(bit)} {'SEEN' if hit else 'NOT seen'}")
        time.sleep(1)
    os.close(fd)
say("Listo"); log("done")
