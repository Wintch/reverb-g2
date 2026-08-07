#!/usr/bin/env python3
"""Headset witness: is it being worn? did it move?

Exists to solve a real problem in this project: the 90Hz verification is PHYSICAL,
and until now there was no way to know whether the user actually looked or the headset
was sitting on the table. A "I see nothing" from a headset that nobody is wearing is not
a data point.

Two signals, both read directly from HID (without Monado running):

  proximity   companion 03f0:0580, control packet 0x01, byte 1.
              This is the G2's face sensor. Decoded the same way as
              control_ipd_value_decode() in wmr_hmd.c:555.

  movement    HoloLens Sensors 045e:0659, packet 0x01 (WMR_MS_HOLOLENS_MSG_SENSORS).
              The IMU is not decoded into physical units: the energy of the int16
              values in the gyro block is enough, auto-calibrated against the rest
              baseline of the first few seconds.

  ./hmd-watch.py [seconds]

The "acknowledgement" agreed with the user: move the headset and let it settle again.
The script detects this and prints SEEN.
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


# Layout of struct hololens_sensors_packet (wmr_protocol.h), packed:
#   0      id
#   1..8   temperature[4]      uint16
#   9..40  gyro_timestamp[4]   uint64
#   41..232 gyro[3][32]        int16   <-- this one
#   233..  accel_timestamp[4], accel[3][4]
GYRO_OFF, GYRO_LEN = 41, 3 * 32 * 2


def gyro_energy(buf):
    """Standard deviation of the gyro block. Deliberately crude: only rest vs. moved matters."""
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
            print(f"  !! can't find {name}")
            continue
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = name
            print(f"  {name}: {p}")
        except OSError as e:
            print(f"  !! {name} ({p}): {e}")
    if not fds:
        sys.exit("no devices to watch")

    print("\n  calibrating rest baseline for 3 s -- don't touch the headset...")
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
                # control_ipd_value_decode: id 0x01, byte1 = proximity
                if buf[0] == 0x01 and len(buf) in (2, 4):
                    new = buf[1]
                    if new != prox:
                        print(f"  [{now:6.1f}s] PROXIMITY {prox} -> {new}"
                              f"   ({'WORN' if new else 'removed'})")
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
                # Calibrated with real data: rest ~26, background noise up to ~50,
                # head movement ~174. The additive floor has to be SMALL or it eats
                # the whole gesture.
                thresh = max(rest * 4, rest + 30)
                peak = max(peak, e)
                if e > thresh:
                    if moved_at is None:
                        print(f"  [{now:6.1f}s] MOVEMENT (energy {e:.0f} vs rest {rest:.0f})")
                    moved_at = now
                elif moved_at is not None and now - moved_at > 1.5 and not acked:
                    acked = True
                    print(f"\n  >>> SEEN: moved and settled back to rest "
                          f"at {now:.1f}s <<<\n")
        if now > 3.0 and now - last_print > 10:
            last_print = now
            rest = sum(baseline) / len(baseline) if baseline else 0
            estado = "no data" if prox is None else ("WORN" if prox else "NOT worn")
            print(f"  [{now:6.1f}s] proximity={estado}  rest={rest:.0f}  peak={peak:.0f}")

    print("\n  summary:")
    print(f"    final proximity  : {'no data' if prox is None else ('WORN' if prox else 'NOT worn')}")
    print(f"    acknowledgement  : {'YES -- the user saw it' if acked else 'NO'}")


main()
