#!/usr/bin/env python3
"""Fast network-link health check for the VR launch path.

Born 2026-08-19, the dual-WAN mapping session: the default gateway had had
multi-day burst packet loss (user-observed 60% bursts, later measured as
~70s-periodic multi-second blackouts of the gateway) and NOTHING surfaced
it -- online titles just feel laggy and cloud tooling silently retries.
Single-player titles don't care; the point is knowing BEFORE an online
session starts, not blocking anything.

Same philosophy and calling convention as controller-battery-check.py:
lives flat next to vr-launcher.py in the ~/vr/ deployment, runs standalone
too, informational only, never blocks a launch.

Checks (~3s wall total, pings run in parallel):
- burst ping (10 x 0.2s) to the current default gateway -> LAN/router health
- burst ping (10 x 0.2s) to an internet target -> end-to-end path.
  NET_CHECK_TARGET overrides; default 9.9.9.9 deliberately avoids 1.1.1.1
  and 8.8.8.8, which this box pins through specific gateways as
  net-monitor.sh probes (see scripts/net-monitor.sh) -- a pinned target
  would measure the wrong path.
- DNS resolution of store.steampowered.com -> what a Steam launch needs
- if ~/vr/logs/net-monitor.log is fresh (<10 min old), count recent ALERT
  lines: the loss here comes in periodic bursts that a single 2-second
  snapshot can easily land between -- the monitor's history is the honest
  instrument for "is the link ACTUALLY clean", not one lucky burst.

Verdict: VERDE / AMARILLO / ROJO on stdout. Exit 0 unless the check itself
could not run (matching battery-check's contract with vr-launcher.py).
"""

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

INET_TARGET = os.environ.get("NET_CHECK_TARGET", "9.9.9.9")
DNS_NAME = "store.steampowered.com"
MONITOR_LOG = Path.home() / "vr" / "logs" / "net-monitor.log"
MONITOR_FRESH_S = 600
PINGS = 10


def default_gateway():
    r = subprocess.run(["ip", "route", "show", "default"],
                       capture_output=True, text=True, timeout=5)
    m = re.search(r"default via (\S+)", r.stdout)
    return m.group(1) if m else None


def start_ping(target):
    return subprocess.Popen(
        ["ping", "-n", "-q", "-c", str(PINGS), "-i", "0.2", "-W", "1", target],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def parse_ping(proc):
    """-> (loss_pct, avg_rtt_ms or None); (100, None) when nothing came back."""
    try:
        out = proc.communicate(timeout=PINGS * 0.2 + 5)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        return 100, None
    m = re.search(r"(\d+) packets transmitted, (\d+) received", out)
    if not m or int(m.group(1)) == 0:
        return 100, None
    loss = 100 * (int(m.group(1)) - int(m.group(2))) // int(m.group(1))
    r = re.search(r"= [\d.]+/([\d.]+)/", out)
    return loss, (float(r.group(1)) if r else None)


def dns_ok():
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo(DNS_NAME, 443)
        return True
    except OSError:
        return False


def recent_monitor_alerts():
    """-> (alert_count, age_ok) over the log's last ~10 minutes, or (0, False)
    when the monitor isn't running/fresh (not an error -- it's optional)."""
    try:
        if time.time() - MONITOR_LOG.stat().st_mtime > MONITOR_FRESH_S:
            return 0, False
        cutoff = time.strftime("%FT%T", time.localtime(time.time() - MONITOR_FRESH_S))
        count = 0
        # Tail-bounded read: the log grows ~forever, only the end matters.
        with MONITOR_LOG.open() as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 64 * 1024))
            for line in f:
                if line.startswith("ALERT ") and line.split()[1] >= cutoff:
                    count += 1
        return count, True
    except OSError:
        return 0, False


def main():
    print("=== chequeo de enlace ===")
    gw = default_gateway()
    if gw is None:
        print("  SIN RUTA DEFAULT -- no hay salida a internet configurada")
        print("  VEREDICTO: ROJO (solo titulos single-player)")
        return

    p_gw, p_inet = start_ping(gw), start_ping(INET_TARGET)
    gw_loss, gw_rtt = parse_ping(p_gw)
    inet_loss, inet_rtt = parse_ping(p_inet)
    dns = dns_ok()
    alerts, monitor_fresh = recent_monitor_alerts()

    fmt = lambda loss, rtt: f"{loss}% perdida" + (f" (rtt {rtt:.1f}ms)" if rtt is not None else "")
    print(f"  gateway {gw}: {fmt(gw_loss, gw_rtt)}")
    print(f"  internet ({INET_TARGET}): {fmt(inet_loss, inet_rtt)}")
    print(f"  DNS ({DNS_NAME}): {'OK' if dns else 'FALLA'}")
    if monitor_fresh and alerts:
        print(f"  monitor: {alerts} alertas de perdida en los ultimos 10 min"
              f" (rafagas -- detalle en {MONITOR_LOG})")

    if inet_loss >= 50 or gw_loss >= 50 or not dns:
        verdict, note = "ROJO", "online injugable ahora mismo; single-player no depende de esto"
    elif inet_loss >= 10 or gw_loss >= 10 or (monitor_fresh and alerts >= 3):
        verdict, note = "AMARILLO", "jugable; un titulo online puede sentir tirones en las rafagas"
    else:
        verdict, note = "VERDE", "enlace limpio"
    print(f"  VEREDICTO: {verdict} -- {note}")


if __name__ == "__main__":
    main()
