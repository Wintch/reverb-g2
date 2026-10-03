#!/usr/bin/env python3
"""Haptic probe v3: what stops the continuous buzz (index 3)? Left joy, held and gently waved the whole time.
Steps: A=1 alone, B=2 alone, then buzz(3) for 3 s followed by C=1, D=2, E=4, F=intensity0 on index 3.
Logs report rate in the 1 s after each send. Log ~/bt-haptic3.log"""
import glob, os, select, subprocess, time
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
LOG = os.path.expanduser("~/bt-haptic3.log")
def say(t): subprocess.run(["espeak-ng", "-v", "es", t], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def log(m): open(LOG, "a").write(time.strftime("%H:%M:%S ") + m + "\n")
def find(side):
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try: u = open(h + "/device/uevent").read()
        except OSError: continue
        if "HID_ID=0005:0000045E:0000066A" in u and f"Motion controller - {side}" in u: return "/dev/" + os.path.basename(h)
def rate(fd, s):
    n = 0; t = time.time()
    while time.time() - t < s:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                while True: n += os.read(fd, 128)[:1] == b"\x01"
            except BlockingIOError: pass
            except OSError: return -1
    return n / s
def send(fw, trig, inten, tag):
    try: os.write(fw, bytes([4, trig, inten])); e = ""
    except OSError as ex: e = f" WRITEFAIL {ex}"
    return e
open(LOG, "w").close()
p = find("Left"); fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK); fw = os.open(p, os.O_WRONLY)
say("Joy izquierdo en la mano. Muévelo despacio todo el rato. Empiezo en cinco segundos"); time.sleep(5)
def step(name, trig, inten, pre=None):
    say(name); time.sleep(0.5)
    if pre:
        send(fw, *pre, "pre"); say("zumbido"); time.sleep(3.0)
    e = send(fw, trig, inten, name)
    r = rate(fd, 1.5); log(f"{name}: sent trig={trig} int={inten}{e} rate_after={r:.0f}Hz")
    time.sleep(3.0); r2 = rate(fd, 1.0); log(f"  {name}: 4.5 s later rate={r2:.0f}Hz")
step("A, uno", 1, 100)
step("B, dos", 2, 100)
step("C, tres y luego uno", 1, 100, pre=(3, 100))
step("D, tres y luego dos", 2, 100, pre=(3, 100))
step("E, tres y luego cuatro", 4, 100, pre=(3, 100))
step("F, tres y luego tres con cero", 3, 0, pre=(3, 100))
say("Prueba terminada"); log("done")
