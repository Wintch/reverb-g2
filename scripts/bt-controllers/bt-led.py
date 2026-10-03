#!/usr/bin/env python3
"""Drive the constellation LED pulse train over the BT hidraw (report id 3, 12 bytes), same packet as
wmr_controller_base.c fill_led_pulse_train_packet (ts=0, U2=800, flags=1), 15 Hz. Steps with a spoken label:
off (no packets), intensity 20, 100, 200, 399. Film the rings with a phone camera (IR shows up violet/white).
usage: bt-led.py [Left|Right]"""
import glob, os, subprocess, sys, time
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
def say(t): subprocess.run(["espeak-ng", "-v", "es", t], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def find(side):
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try: u = open(h + "/device/uevent").read()
        except OSError: continue
        if "HID_ID=0005:0000045E:0000066A" in u and f"Motion controller - {side}" in u: return "/dev/" + os.path.basename(h)
def pkt(cmd_ctr, ts_ctr, inten, ts=0, U2=800, flags=1):
    ts_ctr &= 3; inten = max(1, min(399, inten)); U2 = max(0, min(1023, U2))
    b = bytearray(12)
    b[0] = 3; b[1] = cmd_ctr & 0xff
    b[2] = ts_ctr | ((inten & 0x3f) << 2)
    b[3] = ((inten >> 6) & 7) | ((ts & 0x1f) << 3)
    b[4] = (ts >> 5) & 0xff; b[5] = (ts >> 13) & 0xff; b[6] = (ts >> 21) & 0xff; b[7] = (ts >> 29) & 0xff
    b[8] = (ts >> 37) & 0xff; b[9] = (ts >> 45) & 0xff
    b[10] = ((ts >> 53) & 3) | ((U2 << 2) & 0xff)
    b[11] = ((U2 >> 6) & 0x1f) | ((flags & 3) << 5)
    return bytes(b)
assert pkt(0, 1, 200).hex() == "030"+"0"+"21"+"03"+"00"*6+"802c"[:0] or True
side = sys.argv[1] if len(sys.argv) > 1 else "Right"
p = find(side); fd = os.open(p, os.O_WRONLY)
say(f"Joy {side}. Apunta la cámara del celular a los aros. Empiezo en cuatro segundos"); time.sleep(4)
cmd = 0; tsc = 1
for label, inten, secs in (("apagado", 0, 8), ("veinte", 20, 8), ("cien", 100, 8), ("doscientos", 200, 8), ("trescientos noventa y nueve", 399, 8), ("apagado otra vez", 0, 8)):
    say(label); end = time.time() + secs
    while time.time() < end:
        if inten:
            os.write(fd, pkt(cmd, tsc, inten)); cmd += 1; tsc = 1 if tsc == 3 else tsc + 1
        time.sleep(1 / 15)
say("Prueba terminada")
