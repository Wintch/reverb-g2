#!/usr/bin/env python3
"""Windows-order HID connect for the two G2 controllers (no `bluetoothctl pair`).

The headset's radio does: connect -> SDP -> HID connect, and the SSP/link key happens as a
consequence of the HID connect. Reproduce that: as soon as a controller is visible, open an L2CAP
socket to HID control (PSM 0x11) with BT_SECURITY_MEDIUM so the kernel pairs on demand, keep it
open, then open the interrupt channel (PSM 0x13), keep both open and log whatever the controller
sends. Needs a running agent for just-works pairing (started here via a long-lived bluetoothctl).
Log: ~/bt-winorder.log
"""
import os, select, socket, struct, subprocess, threading, time

ADDRS = {"right": os.environ["G2_RIGHT_BD"], "left": os.environ["G2_LEFT_BD"]}  # set both, e.g. from bluetoothctl devices
LOG = os.path.expanduser("~/bt-winorder.log")
T0 = time.time()
lock = threading.Lock()
SOL_BLUETOOTH, BT_SECURITY = 274, 4


def log(msg):
    with lock, open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} +{time.time()-T0:6.1f}s {msg}\n")


def ctl(*args, timeout=10):
    try:
        return subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        return ""


def st(addr):
    out = ctl("info", addr, timeout=5)
    return " ".join(l.strip() for l in out.splitlines() if l.strip().startswith(("Paired", "Bonded", "Connected", "Trusted")))


def hid_nodes():
    base, res = "/sys/class/hidraw", []
    for h in sorted(os.listdir(base)):
        try:
            u = open(f"{base}/{h}/device/uevent").read()
            res.append(h + ":" + [l for l in u.splitlines() if l.startswith("HID_ID")][0].split("=")[1])
        except Exception:
            pass
    return " ".join(res)


def sock(addr, psm, tmo):
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
    s.setsockopt(SOL_BLUETOOTH, BT_SECURITY, struct.pack("BB", 2, 0))  # MEDIUM
    s.settimeout(tmo)
    t = time.time()
    try:
        s.connect((addr, psm))
        return s, f"PSM {psm} CONNECTED in {time.time()-t:.2f}s"
    except Exception as e:
        s.close()
        return None, f"PSM {psm} {type(e).__name__} {e} after {time.time()-t:.2f}s"


def work(name, addr):
    log(f"[{name}] waiting for {addr}")
    while time.time() - T0 < 900 and addr not in ctl("devices"):
        time.sleep(0.3)
    if addr not in ctl("devices"):
        log(f"[{name}] never seen"); return
    ctl("pairable", "on")
    log(f"[{name}] seen, connecting control with security MEDIUM")
    c, m = sock(addr, 0x11, 30)
    log(f"[{name}] ctrl {m} | {st(addr)}")
    if not c:
        return
    i, m = sock(addr, 0x13, 15)
    log(f"[{name}] intr {m} | {st(addr)} | hid {hid_nodes()}")
    socks = [s for s in (c, i) if s]
    end, n = time.time() + 40, 0
    while time.time() < end:
        r, _, _ = select.select(socks, [], [], 1.0)
        for s in r:
            try:
                d = s.recv(256)
            except Exception as e:
                log(f"[{name}] recv error {e}"); end = 0; break
            if not d:
                log(f"[{name}] peer closed"); end = 0; break
            n += 1
            if n <= 8:
                log(f"[{name}] {'intr' if s is i else 'ctrl'} len={len(d)} {d[:16].hex()}")
    log(f"[{name}] done: {n} reports | {st(addr)} | hid {hid_nodes()}")
    for s in socks:
        s.close()


if __name__ == "__main__":
    open(LOG, "w").close()
    for a in ADDRS.values():
        ctl("remove", a)
    agent = subprocess.Popen("sleep 3000 | bluetoothctl", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    ths = [threading.Thread(target=work, args=(n, a)) for n, a in ADDRS.items()]
    for t in ths: t.start()
    for t in ths: t.join()
    agent.terminate()
    log("finished")
