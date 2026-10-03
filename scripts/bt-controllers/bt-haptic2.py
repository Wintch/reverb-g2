#!/usr/bin/env python3
"""Subjective haptic test v2. Report [04, ManualTrigger 0..100, Intensity 0..100] (BT HID descriptor logical max 0x64).
NO [04 00 00] stop writes: that one made the controller stop streaming. Per hand: waits until it is awake (>100 reports/s,
i.e. being held/moved), speaks the trigger index, sends, logs the report rate for 1.5 s after. Log ~/bt-haptic2.log"""
import glob, os, select, subprocess, sys, time
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
LOG = os.path.expanduser("~/bt-haptic2.log")
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
open(LOG, "w").close()
INT = int(sys.argv[1]) if len(sys.argv) > 1 else 100
for side, word in (("Left", "izquierdo"), ("Right", "derecho")):
    p = find(side)
    if not p: log(f"{side}: no hidraw"); continue
    fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK); fw = os.open(p, os.O_WRONLY)
    say(f"Joy {word}. Agítalo y agárralo fuerte"); t0 = time.time()
    while rate(fd, 1.0) < 100:
        if time.time() - t0 > 60: break
    r0 = rate(fd, 1.0); log(f"{side} awake rate {r0:.0f} Hz"); time.sleep(1)
    for t in range(1, 7):
        say(f"{t}"); time.sleep(0.3)
        try: os.write(fw, bytes([4, t, INT])); e = ""
        except OSError as ex: e = f" WRITEFAIL {ex}"
        r = rate(fd, 1.5); log(f"{side} trigger={t} intensity={INT}{e} rate_after={r:.0f} Hz")
        time.sleep(1.5)
    os.close(fd); os.close(fw)
say("Prueba terminada"); log("done")
