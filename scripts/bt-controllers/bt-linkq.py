#!/usr/bin/env python3
"""Link-quality logger for the two G2 controllers on the system-BT hidraw nodes.

usage: bt-linkq.py LABEL SECONDS
Per second per controller: input-report count, longest gap between reports, host-side RSSI
(`hcitool rssi`, relative to the receiver's golden range: 0 = fine, negative = weak) and our TX power
level for the link. Appends one summary line per controller to ~/bt-linkq.log.
Read-only. Keep the controllers still (or moving the same way) between runs to compare placements.
"""
import glob, os, select, statistics, subprocess, sys, time

LOG = os.path.expanduser("~/bt-linkq.log")
ADDR = {"Left": os.environ["G2_LEFT_BD"], "Right": os.environ["G2_RIGHT_BD"]}


def find(side):
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            u = open(h + "/device/uevent").read()
        except OSError:
            continue
        if "HID_ID=0005:0000045E:0000066A" in u and f"Motion controller - {side}" in u:
            return "/dev/" + os.path.basename(h)


def hci(cmd, addr):
    try:
        out = subprocess.run(["hcitool", cmd, addr], capture_output=True, text=True, timeout=3).stdout
        return int(out.split()[-1])
    except Exception:
        return None


def main(label, seconds):
    fds = {s: os.open(p, os.O_RDONLY | os.O_NONBLOCK) for s in ADDR if (p := find(s))}
    stamps = {s: [] for s in fds}
    rssi = {s: [] for s in fds}
    txp = {s: [] for s in fds}
    t0 = time.time()
    next_sample = t0
    while time.time() - t0 < seconds:
        r, _, _ = select.select(list(fds.values()), [], [], 0.2)
        now = time.time()
        for s, fd in fds.items():
            if fd in r:
                try:
                    while True:
                        d = os.read(fd, 128)
                        if d and d[0] == 1:
                            stamps[s].append(now)
                except BlockingIOError:
                    pass
        if now >= next_sample:
            next_sample = now + 1.0
            for s in fds:
                v = hci("rssi", ADDR[s])
                p = hci("tpl", ADDR[s])
                if v is not None:
                    rssi[s].append(v)
                if p is not None:
                    txp[s].append(p)
    lines = []
    for s in fds:
        v = stamps[s]
        if len(v) < 3:
            lines.append(f"{label} {s}: reports={len(v)} (no data)")
            continue
        gaps = [(b - a) * 1000 for a, b in zip(v, v[1:])]
        rs = rssi[s] or [0]
        lines.append(
            f"{label} {s}: {seconds}s reports={len(v)} rate={len(v)/seconds:.1f}Hz "
            f"gap_ms median={statistics.median(gaps):.0f} max={max(gaps):.0f} "
            f">100ms={sum(g > 100 for g in gaps)} >200ms={sum(g > 200 for g in gaps)} "
            f"rssi min/mean/max={min(rs)}/{statistics.mean(rs):.1f}/{max(rs)} "
            f"tx_power_dBm min/max={min(txp[s] or [0])}/{max(txp[s] or [0])}")
    with open(LOG, "a") as f:
        for l in lines:
            f.write(time.strftime("%H:%M:%S ") + l + "\n")
            print(l)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
