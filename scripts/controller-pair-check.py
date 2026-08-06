#!/usr/bin/env python3
"""Pregunta al CASCO si tiene los controllers vinculados, por HID directo (sin Monado).

Los controllers del G2 no hablan Bluetooth con la PC (ver docs/03-controllers.md): estan
apareados de fabrica con el radio interno del casco, y su estado de vinculacion se consulta
mandando un comando al mismo dispositivo Hololens Sensors (045e:0659) que ya usa Monado -
protocolo leido de wmr_hmd.c / wmr_protocol.h:

  Pedido  (report 0x16, WMR_MS_HOLOLENS_MSG_BT_CONTROL):
      byte0=0x16  byte1=0x17 (subtipo CONTROLLER_STATUS)  resto en cero, 64 bytes

  Respuesta (report 0x17, WMR_MS_HOLOLENS_MSG_CONTROLLER_STATUS), una por controller:
      byte0=0x17  byte1=controller_id (0=izq, 1=der)  byte2=pkt_type
          pkt_type 0x0 UNPAIRED  -> nunca vinculado / se desvinculo (boton oculto de reset)
          pkt_type 0x1 OFFLINE   -> vinculado, pero apagado o fuera de rango ahora
          pkt_type 0x2 ONLINE    -> vinculado y respondiendo ahora
      si OFFLINE/ONLINE, bytes3-4=VID bytes5-6=PID (little-endian)

Investigado 2026-08-06 leyendo el driver Monado (fuente autoritativa: el mismo casco). El
comando de "vincular" (linkear) en cambio NO existe en ningun binario de Windows examinado
(ver docs/03-controllers.md, seccion "Vinculacion / pairing") - es un handshake de radio
interno al casco, disparado por el boton fisico del controller, sin comando de host. Este
script solo CONSULTA estado; no intenta vincular nada.

  ./controller-pair-check.py [segundos_de_espera]

Funciona con o sin monado-service corriendo (el hidraw permite abrirse mas de una vez).
"""
import glob, os, select, sys, time

HOLOLENS_SENSORS = (0x045E, 0x0659)
PKT_TYPE = {0x0: "SIN VINCULAR (unpaired)", 0x1: "vinculado, offline", 0x2: "vinculado, online"}
NAME = {0: "izquierdo", 1: "derecho"}


def find_hololens_sensors():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split(":")
                if (int(vid, 16), int(pid, 16)) == HOLOLENS_SENSORS:
                    return "/dev/" + os.path.basename(d)
    return None


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    dev = find_hololens_sensors()
    if not dev:
        sys.exit("no encuentro el Hololens Sensors (045e:0659) - esta el casco prendido y conectado?")

    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except PermissionError:
        sys.exit(f"sin permiso para {dev} - deberia ser rw para el grupo plugdev "
                  f"(ver scripts/70-wmr-reverb.rules); estas en ese grupo? (groups)")
    except OSError as e:
        sys.exit(f"no pude abrir {dev}: {e}")

    cmd = bytes([0x16, 0x17]) + bytes(62)
    try:
        os.write(fd, cmd)
    except OSError as e:
        os.close(fd)
        sys.exit(f"no pude escribir el pedido de estado en {dev}: {e}")

    print(f"  pedido de estado enviado, escuchando {dev} durante {secs:.0f}s...")
    seen = {}
    t0 = time.time()
    while time.time() - t0 < secs and len(seen) < 2:
        r, _, _ = select.select([fd], [], [], 0.3)
        if not r:
            continue
        b = os.read(fd, 64)
        if not b or b[0] != 0x17 or len(b) < 3:
            continue
        cid, pkt_type = b[1], b[2]
        vidpid = None
        if pkt_type in (0x1, 0x2) and len(b) >= 7:
            vid = b[3] | (b[4] << 8)
            pid = b[5] | (b[6] << 8)
            vidpid = (vid, pid)
        seen[cid] = (pkt_type, vidpid)
    os.close(fd)

    print()
    for cid in (0, 1):
        label = f"  {NAME.get(cid, cid)} (id {cid}): "
        if cid not in seen:
            print(label + "sin respuesta (no llego ningun paquete 0x17 para este id)")
            continue
        pkt_type, vidpid = seen[cid]
        desc = PKT_TYPE.get(pkt_type, f"tipo desconocido 0x{pkt_type:02x}")
        if vidpid:
            desc += f"  (VID 0x{vidpid[0]:04x} PID 0x{vidpid[1]:04x})"
        print(label + desc)

    if len(seen) < 2:
        print("\n  (si falta alguno: el casco solo contesta por el que tiene noticias - "
              "probá con el controller prendido y cerca)")


main()
