#!/usr/bin/env python3
"""Left joy only, one control at a time (10 s windows). Detects: menu byte1&4, windows byte1&2, stick click byte1&1,
squeeze click byte1&8, X byte7&2, Y byte7&1, trigger byte5>0, squeeze analog byte6>0. Log ~/bt-left-probe.log"""
import glob, os, select, subprocess, time
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
LOG = os.path.expanduser("~/bt-left-probe.log")
def say(t): subprocess.run(["espeak-ng", "-v", "es", t], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def log(m): open(LOG, "a").write(time.strftime("%H:%M:%S ") + m + "\n")
def find(side):
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try: u = open(h + "/device/uevent").read()
        except OSError: continue
        if "HID_ID=0005:0000045E:0000066A" in u and f"Motion controller - {side}" in u: return "/dev/" + os.path.basename(h)
TESTS = [("menú, las tres rayas", "menu", lambda d: d[1] & 4),
         ("el botón de Windows", "windows", lambda d: d[1] & 2),
         ("el botón Y, el de arriba", "Y", lambda d: d[7] & 1),
         ("el botón X, el de abajo", "X", lambda d: d[7] & 2),
         ("el gatillo", "trigger", lambda d: d[5] > 0),
         ("el click del stick, empujándolo hacia abajo", "stick_click", lambda d: d[1] & 1),
         ("el grip, apretándolo a fondo", "squeeze", lambda d: d[1] & 8 or d[6] > 0)]
open(LOG, "w").close()
p = find("Left")
if not p: log("Left: no hidraw"); raise SystemExit
fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
say("Joy izquierdo. Empiezo en tres segundos. Un botón a la vez, tres toques con calma"); time.sleep(3)
for phrase, key, test in TESTS:
    say(f"Ahora {phrase}"); time.sleep(0.5)
    n = hits = 0; t = time.time()
    while time.time() - t < 10:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                while True:
                    d = os.read(fd, 128)
                    if d[:1] == b"\x01" and len(d) > 8:
                        n += 1; hits += 1 if test(d) else 0
            except BlockingIOError: pass
            except OSError: log(f"{key}: read error"); break
    log(f"{key}: reports={n} pressed_reports={hits} -> {'SEEN' if hits else 'not seen'}")
    say("listo"); time.sleep(1)
say("Terminé"); log("done")
