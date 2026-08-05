#!/usr/bin/env python3
"""Escucha lo que el CASCO dice sobre su propio panel, por HID.

El companion (03f0:0580) manda un mensaje DEVICE_STATUS (0x05) cuando cambia el estado de
pantalla. Del comentario de Monado en wmr_hmd.c (control_read_packets):

    On Reverb G1 this message is received twice after having sent an 'enable screen' command.
    The first one is received promptly. The second one is received a few seconds later once
    the HMD screen backlight VISIBLY POWERS ON.
      1er mensaje: 05 00 01 01 00 00 00 00 00 00 00
      2do mensaje: 05 01 01 01 01 00 00 00 00 00 00

O sea que el hardware nos avisa cuando el panel realmente prendió. Es la unica instrumentacion
del lado del SINK que tenemos: todo lo demas (Vulkan, el log de NVIDIA) reporta exito con el
panel muerto.

Idea del experimento: capturar esto mientras se pide 60Hz (engancha) y mientras se pide 90Hz
(no engancha), y diffear. Si los bytes difieren, el casco nos esta diciendo donde se rompe.

  ./panel-status.py [segundos]

Mensajes conocidos (wmr_protocol.h):
  0x01 IPD_VALUE     byte1 = sensor de proximidad, bytes2-3 = IPD
  0x02 UNKNOWN_02    visto junto a eventos de proximidad en el G1
  0x05 DEVICE_STATUS estado del dispositivo / pantalla   <-- el que importa
"""
import glob, os, select, sys, time

COMPANION = (0x03F0, 0x0580)
NAMES = {0x01: "IPD_VALUE", 0x02: "UNKNOWN_02", 0x05: "DEVICE_STATUS"}


def find_companion():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split(":")
                if (int(vid, 16), int(pid, 16)) == COMPANION:
                    return "/dev/" + os.path.basename(d)
    return None


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    dev = find_companion()
    if not dev:
        sys.exit("no encuentro el companion 03f0:0580")
    print(f"  escuchando {dev} durante {secs:.0f}s")
    print(f"  (el companion puede RE-ENUMERAR con el screen-off; si desaparece, se reabre)")

    t0 = time.time()
    fd = None
    n = 0
    while time.time() - t0 < secs:
        if fd is None:
            p = find_companion()
            if not p:
                time.sleep(0.3)
                continue
            try:
                fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                time.sleep(0.3)
                continue
        r, _, _ = select.select([fd], [], [], 0.3)
        for f in r:
            try:
                b = os.read(f, 512)
            except OSError:
                os.close(fd)
                fd = None
                print(f"  [{time.time()-t0:6.2f}s] -- el companion se fue, reabriendo --")
                break
            if not b:
                continue
            n += 1
            rid = b[0]
            # El mensaje tiene 33 bytes. Imprimirlo ENTERO: los bytes de la segunda mitad
            # tambien cambian entre modos y truncar a 16 tiraba la mitad del dato.
            print(f"  [{time.time()-t0:6.2f}s] 0x{rid:02x} {NAMES.get(rid,'?'):<14} "
                  f"len={len(b):<3} {b.hex(' ')}")
    print(f"\n  total: {n} mensajes del companion")
    if n == 0:
        print("  (ninguno -- el companion solo habla cuando cambia algo: hay que "
              "activar/apagar el panel mientras esto escucha)")


main()
