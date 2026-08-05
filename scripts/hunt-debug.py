#!/usr/bin/env python3
"""Caza el canal HID 0x03 DEBUG del casco durante un intento de modo.

Motivo: en el issue #332 de Monado, otro usuario (Kukeltje) reportó ver un error
`DMA CMT ERR` en el canal 0x03 DEBUG justo durante el intento de 90Hz. Nosotros buscamos ese
canal EN REPOSO y no emitía nada — pero puede emitir sólo cuando algo falla.

Escucha los DOS dispositivos y muestra todo lo que NO sea el stream de sensores (0x01), en
hex y en ASCII, porque los mensajes de debug del firmware suelen ser texto.

  ./hunt-debug.py [segundos]

Correr en paralelo con hmd-vk pidiendo el modo que falla.

Tipos (wmr_protocol.h): 0x01 SENSORS, 0x02 CONTROL, 0x03 DEBUG, 0x05 BT_IFACE,
0x06/0x0E controllers, 0x16 BT_CONTROL, 0x17 CONTROLLER_STATUS.
En la interfaz BT hay además un sub-mensaje 0x19 = WMR_BT_IFACE_MSG_DEBUG.
"""
import collections, glob, os, select, sys, time

NAMES = {0x01: "SENSORS", 0x02: "CONTROL", 0x03: "DEBUG", 0x05: "BT_IFACE",
         0x06: "LEFT_CTRL", 0x0E: "RIGHT_CTRL", 0x16: "BT_CONTROL", 0x17: "CTRL_STATUS"}
DEVS = (("sensors", (0x045E, 0x0659)), ("companion", (0x03F0, 0x0580)))


def find(vp):
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if line.startswith("HID_ID="):
                _, v, p = line.split(":")
                if (int(v, 16), int(p, 16)) == vp:
                    return "/dev/" + os.path.basename(d)
    return None


def ascii_of(b):
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40
    fds = {}
    for label, vp in DEVS:
        p = find(vp)
        if not p:
            print(f"  !! no encuentro {label}")
            continue
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = label
            print(f"  {label}: {p}")
        except OSError as e:
            print(f"  !! {label}: {e}")
    if not fds:
        sys.exit("sin dispositivos")

    counts = collections.Counter()
    interesting = 0
    t0 = time.time()
    while time.time() - t0 < secs:
        r, _, _ = select.select(list(fds), [], [], 0.4)
        for fd in r:
            try:
                b = os.read(fd, 2048)
            except OSError:
                continue
            if not b:
                continue
            label = fds[fd]
            rid = b[0]
            counts[(label, rid)] += 1
            if rid == 0x01 and label == "sensors":
                continue                      # el stream de IMU, ruido para esto
            interesting += 1
            t = time.time() - t0
            print(f"  [{t:6.2f}s] {label:<9} 0x{rid:02x} {NAMES.get(rid,'?'):<12} len={len(b)}")
            print(f"            hex   {b[:48].hex(' ')}")
            txt = ascii_of(b)
            if sum(1 for c in txt if c != ".") > 4:      # solo si hay texto de verdad
                print(f"            ascii {txt}")

    print("\n  conteo por tipo:")
    for (label, rid), n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {label:<10} 0x{rid:02x} {NAMES.get(rid,'?'):<13} {n}")
    print(f"\n  mensajes no-SENSORS: {interesting}")
    if not counts.get(("sensors", 0x03)) and not counts.get(("companion", 0x03)):
        print("  (ningun 0x03 DEBUG -- el canal sigue mudo)")


main()
