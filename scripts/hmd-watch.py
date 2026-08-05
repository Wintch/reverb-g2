#!/usr/bin/env python3
"""Testigo del casco: ¿lo tiene puesto? ¿lo movió?

Existe para resolver un problema real de este proyecto: la verificación de 90Hz es FÍSICA,
y hasta ahora no había forma de saber si el usuario llegó a mirar o si el casco estaba
apoyado en la mesa. Un "no veo nada" de un casco que nadie tiene puesto no es un dato.

Dos señales, las dos leídas del HID directamente (sin Monado corriendo):

  proximidad  companion 03f0:0580, paquete de control 0x01, byte 1.
              Es el sensor de cara del G2. Lo decodifica igual que
              control_ipd_value_decode() en wmr_hmd.c:555.

  movimiento  HoloLens Sensors 045e:0659, paquete 0x01 (WMR_MS_HOLOLENS_MSG_SENSORS).
              No se decodifica la IMU en unidades físicas: alcanza con la energía de los
              int16 del bloque de giro, autocalibrada contra el reposo de los primeros
              segundos.

  ./hmd-watch.py [segundos]

El "acuse de recibo" acordado con el usuario: mover el casco y volver a dejarlo quieto.
El script lo detecta e imprime VISTO.
"""
import glob, os, select, struct, sys, time

SENSORS = (0x045E, 0x0659)
COMPANION = (0x03F0, 0x0580)


def find(vid_pid):
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split(":")
                if (int(vid, 16), int(pid, 16)) == vid_pid:
                    return "/dev/" + os.path.basename(d)
    return None


# Layout de struct hololens_sensors_packet (wmr_protocol.h), packed:
#   0      id
#   1..8   temperature[4]      uint16
#   9..40  gyro_timestamp[4]   uint64
#   41..232 gyro[3][32]        int16   <-- esto
#   233..  accel_timestamp[4], accel[3][4]
GYRO_OFF, GYRO_LEN = 41, 3 * 32 * 2


def gyro_energy(buf):
    """Desvío estándar del bloque de giro. Crudo a propósito: sólo interesa quieto vs movido."""
    body = buf[GYRO_OFF:GYRO_OFF + GYRO_LEN]
    n = len(body) // 2
    if n == 0:
        return 0.0
    vals = struct.unpack(f"<{n}h", body[: n * 2])
    mean = sum(vals) / n
    return (sum((v - mean) ** 2 for v in vals) / n) ** 0.5


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    paths = {"sensors": find(SENSORS), "companion": find(COMPANION)}
    fds = {}
    for name, p in paths.items():
        if not p:
            print(f"  !! no encuentro {name}")
            continue
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = name
            print(f"  {name}: {p}")
        except OSError as e:
            print(f"  !! {name} ({p}): {e}")
    if not fds:
        sys.exit("sin dispositivos que mirar")

    print("\n  calibrando reposo 3 s -- no toques el casco...")
    t0 = time.time()
    baseline, prox, moved_at, acked = [], None, None, False
    last_print = 0.0
    peak = 0.0

    while time.time() - t0 < secs:
        r, _, _ = select.select(list(fds), [], [], 0.5)
        now = time.time() - t0
        for fd in r:
            try:
                buf = os.read(fd, 512)
            except OSError:
                continue
            if not buf:
                continue
            if fds[fd] == "companion":
                # control_ipd_value_decode: id 0x01, byte1 = proximidad
                if buf[0] == 0x01 and len(buf) in (2, 4):
                    new = buf[1]
                    if new != prox:
                        print(f"  [{now:6.1f}s] PROXIMIDAD {prox} -> {new}"
                              f"   ({'PUESTO' if new else 'sacado'})")
                    prox = new
            else:
                if buf[0] != 0x01:
                    continue
                e = gyro_energy(buf)
                if now < 3.0:
                    baseline.append(e)
                    continue
                if not baseline:
                    baseline = [e]
                rest = sum(baseline) / len(baseline)
                # Calibrado con datos reales: reposo ~26, ruido de fondo hasta ~50,
                # movimiento de cabeza ~174. El piso aditivo tiene que ser CHICO o se
                # come el gesto entero.
                thresh = max(rest * 4, rest + 30)
                peak = max(peak, e)
                if e > thresh:
                    if moved_at is None:
                        print(f"  [{now:6.1f}s] MOVIMIENTO (energia {e:.0f} vs reposo {rest:.0f})")
                    moved_at = now
                elif moved_at is not None and now - moved_at > 1.5 and not acked:
                    acked = True
                    print(f"\n  >>> VISTO: se movio y volvio a quedar quieto "
                          f"a los {now:.1f}s <<<\n")
        if now > 3.0 and now - last_print > 10:
            last_print = now
            rest = sum(baseline) / len(baseline) if baseline else 0
            estado = "sin dato" if prox is None else ("PUESTO" if prox else "NO puesto")
            print(f"  [{now:6.1f}s] proximidad={estado}  reposo={rest:.0f}  pico={peak:.0f}")

    print("\n  resumen:")
    print(f"    proximidad final : {'sin dato' if prox is None else ('PUESTO' if prox else 'NO puesto')}")
    print(f"    acuse de recibo  : {'SI -- el usuario lo vio' if acked else 'NO'}")


main()
