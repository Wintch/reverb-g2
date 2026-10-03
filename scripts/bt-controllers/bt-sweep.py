#!/usr/bin/env python3
"""Guided control sweep for the two G2 controllers on their system-BT hidraw nodes.

For every hand and control it speaks a prompt (espeak-ng, Spanish), records 2 s of idle baseline
then a 4 s action window, and logs which report bytes moved (offset, baseline, min..max).
Read-only on the hidraw nodes. Log: ~/bt-sweep.log
"""
import glob, os, select, subprocess, time

LOG = os.path.expanduser("~/bt-sweep2.log")
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
CONTROLS = [
    ("trigger", "el gatillo"),
    ("grip", "el grip, apriétalo a fondo"),
    ("stick_right", "el stick a la derecha"),
    ("stick_left", "el stick a la izquierda"),
    ("stick_up", "el stick hacia arriba"),
    ("stick_down", "el stick hacia abajo"),
    ("stick_click", "el click del stick, apretándolo"),
    ("btn_lower", "el botón de abajo, X o A"),
    ("btn_upper", "el botón de arriba, Y o B"),
    ("menu", "el botón de menú, las tres rayas"),
    ("home", "el botón de Windows"),
]


def say(text):
    subprocess.run(["espeak-ng", "-v", "es", text], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log(msg):
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def find(side):
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            u = open(h + "/device/uevent").read()
        except OSError:
            continue
        if "HID_ID=0005:0000045E:0000066A" in u and f"Motion controller - {side}" in u:
            return "/dev/" + os.path.basename(h)


def capture(fd, seconds):
    out, t0 = [], time.time()
    while time.time() - t0 < seconds:
        r, _, _ = select.select([fd], [], [], 0.3)
        if r:
            try:
                while True:
                    d = os.read(fd, 128)
                    if d and d[0] == 1:
                        out.append(d)
            except BlockingIOError:
                pass
    return out


def moved(base, win):
    if not base or not win:
        return "no data"
    n = min(len(r) for r in base + win)
    res = []
    for off in range(1, n):
        b = [r[off] for r in base]
        w = [r[off] for r in win]
        # ignore noisy IMU/ticks region by requiring a change vs the baseline envelope
        if min(w) < min(b) or max(w) > max(b):
            if off >= 9:
                continue
            res.append(f"[{off}] base {min(b)}..{max(b)} act {min(w)}..{max(w)} vals {sorted(set(w))[:6]}")
    return "; ".join(res) if res else "no change"


if __name__ == "__main__":
    open(LOG, "w").close()
    PLAN = {"Left": ["trigger", "btn_upper", "home", "stick_click"], "Right": ["stick_click"]}
    for side, label in (("Left", "izquierdo"), ("Right", "derecho")):
        path = find(side)
        if not path:
            log(f"{side}: no hidraw"); continue
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        say(f"Joy {label}. Agárralo, empezamos")
        time.sleep(1.5)
        for key, phrase in [c for c in CONTROLS if c[0] in PLAN[side]]:
            say(f"Siguiente: {phrase}. Espera mi ya")
            time.sleep(1.5)
            base = capture(fd, 1.2)
            say("ya")
            win = capture(fd, 3.0)
            log(f"{side} {key}: {moved(base, win)}")
            time.sleep(0.5)
        os.close(fd)
    say("Barrido terminado")
    log("done")
