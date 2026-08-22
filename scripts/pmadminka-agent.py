#!/usr/bin/env python3
"""pmadminka agent for reverb-g2 (iashur) -- makes this VR rig show up as a
rentable machine in the pmadminka reservation hub, speaking the SAME wire
protocol the existing Windows agent (deploy/agent.ps1 + deploy/run.ps1, in
the pmadminka repo) already uses. The hub (deploy/server.py) is not modified
by this script -- every endpoint used here already exists.

Protocol notes (from reading the Windows agent + hub source directly, not
just the handoff doc's summary):
  - No auth on any agent endpoint. Identity is the MAC address alone. This
    matches the existing Windows agent's contract exactly -- adding auth
    here would just be inconsistent with it, not safer.
  - POST /heartbeat every ~60s: host/mac/ip/gw + hw + live telemetry.
  - POST /agentstuck/<mac> every run-loop iteration: {"agent_age": seconds
    since the last heartbeat that actually completed}. This is how the hub
    tells "agent hung" from "machine powered off".
  - GET /run/<mac>?wait=N (long-poll, hub holds the connection up to N
    seconds, clamped server-side to 30): {"queue": [name, ...], "kill":
    [name, ... ] or "*"}. Entries are Steam display NAMES, not appids --
    resolved locally via the same steam_ids map built for /inventory.
  - POST /run/<mac>/ack: reports what actually launched/died and the full
    current "running" list (the hub just overwrites its state with this,
    so it must be sent every cycle even when nothing changed).
  - POST /inventory/<mac>: throttled client-side (on content-hash change or
    every 30 min), not server-rate-limited.

KNOWN GAP, not fixable from this repo: the hub's heartbeat handler
(deploy/server.py) builds the "hw" dict from a fixed field whitelist
that does NOT currently include "vr_device" -- so the vr_device field this
agent sends is silently dropped until that whitelist gets one entry added
on the pmadminka side. Sent anyway so it's a one-line hub fix away from
working, not a two-sided change.

Explicitly NOT handled here (see docs/handoff-agente-vr-reverb-g2.md in the
pmadminka repo for the original proposal): VR compositor lifecycle
(panel.py, Monado startup/teardown), screen-stream, OS switching. Starting/
stopping Steam titles is as far as this agent's reach goes.

Config: ~/.config/pmadminka-agent/config.json -- {"server": "http://host:8000"}
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
from wmr_usb_ids import all_present as vr_device_present  # noqa: E402
import gui_env  # noqa: E402

CONFIG_PATH = os.path.expanduser("~/.config/pmadminka-agent/config.json")
STEAMAPPS_DIR = os.path.expanduser("~/.steam/steam/steamapps")

HEARTBEAT_INTERVAL_S = 60
RUN_WAIT_S = 25
RUN_HTTP_TIMEOUT_S = RUN_WAIT_S + 10
POST_TIMEOUT_S = 10
INVENTORY_POST_TIMEOUT_S = 15
INVENTORY_MIN_INTERVAL_S = 30 * 60

_last_heartbeat_ok = 0.0


def _load_game_stop():
    import importlib.util

    path = os.path.join(SCRIPT_DIR, "game-stop.py")
    spec = importlib.util.spec_from_file_location("game_stop_lib", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


game_stop = _load_game_stop()


def load_server_url():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    return cfg["server"].rstrip("/")


def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def _default_iface():
    out = _run(["ip", "route", "show", "default"])
    m = re.search(r"\bdev\s+(\S+)", out)
    return m.group(1) if m else None


def identity():
    iface = _default_iface()
    mac = ip = gw = None
    if iface:
        try:
            with open(f"/sys/class/net/{iface}/address") as f:
                mac = f.read().strip()
        except OSError:
            pass
        out = _run(["ip", "-o", "-4", "addr", "show", iface])
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        if m:
            ip = m.group(1)
    out = _run(["ip", "route", "show", "default"])
    m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
    if m:
        gw = m.group(1)
    host = _run(["hostname"]).strip()
    return host, mac, ip, gw


def machine_specs():
    script = os.path.join(SCRIPT_DIR, "machine-specs.sh")
    try:
        out = subprocess.run([script, "--json"], capture_output=True, text=True, timeout=10).stdout
        return json.loads(out)
    except Exception as e:
        print(f"[specs] machine-specs.sh failed: {e}", file=sys.stderr)
        return {}


def gpu_telemetry():
    out = _run([
        "nvidia-smi",
        "--query-gpu=utilization.gpu,power.draw,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]).strip()
    try:
        util, watts, temp = [p.strip() for p in out.split(",")]
        return float(util), float(watts), float(temp)
    except Exception:
        return None, None, None


def ram_percent():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        return round(100.0 * (info["MemTotal"] - info["MemAvailable"]) / info["MemTotal"], 1)
    except Exception:
        return None


def sunshine_active():
    r = subprocess.run(["systemctl", "is-active", "sunshine"], capture_output=True, text=True, timeout=5)
    return r.stdout.strip() == "active"


def _post_json(url, payload, timeout):
    # Not every endpoint returns JSON -- /agentstuck answers "ok" as plain
    # text (confirmed live, 2026-08-22). None of the callers here need the
    # response body, so a non-JSON reply is not an error, just untyped.
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body.decode(errors="replace")


def _get_json(url, timeout):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def scan_inventory():
    """Installed Steam titles only (appmanifest_*.acf), not the whole owned
    library -- that's what the hub's /run queue can actually name and what
    /inventory expects (name -> appid), nothing more."""
    steam, steam_ids = [], {}
    try:
        entries = os.listdir(STEAMAPPS_DIR)
    except OSError as e:
        print(f"[inventory] can't list {STEAMAPPS_DIR}: {e}", file=sys.stderr)
        return steam, steam_ids
    for fn in entries:
        m = re.match(r"appmanifest_(\d+)\.acf$", fn)
        if not m:
            continue
        appid = m.group(1)
        try:
            with open(os.path.join(STEAMAPPS_DIR, fn), encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        nm = re.search(r'"name"\s*"([^"]*)"', content)
        if nm:
            name = nm.group(1)
            steam.append(name)
            steam_ids[name] = int(appid)
    return steam, steam_ids


def inventory_hash(steam, steam_ids):
    blob = json.dumps({"steam": sorted(steam), "steam_ids": steam_ids}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def running_snapshot(steam_ids):
    appid_to_name = {str(v): k for k, v in steam_ids.items()}
    trees = game_stop.scan()
    running = []
    now = time.time()
    for appid, procs in trees.items():
        name = appid_to_name.get(appid, f"appid {appid}")
        pids = [p for p, _ in procs]
        oldest_pid = min(pids) if pids else None
        age = game_stop.proc_age_s(oldest_pid) if oldest_pid is not None else -1
        since = int(now - age) if age >= 0 else int(now)
        running.append({"name": name, "source": "steam", "since": since, "pid": oldest_pid})
    return running


def heartbeat_loop(server, mac):
    global _last_heartbeat_ok
    while True:
        try:
            host, _, ip, gw = identity()
            specs = machine_specs()
            gpu_util, gpu_w, gpu_temp = gpu_telemetry()
            body = {
                "host": host,
                "mac": mac,
                "ip": ip,
                "gw": gw,
                "cpu_name": specs.get("cpu", {}).get("model"),
                "cores": specs.get("cpu", {}).get("cores"),
                "threads": specs.get("cpu", {}).get("threads"),
                "ram_gb": specs.get("ram_gb"),
                "gpu_name": specs.get("gpu", {}).get("name"),
                "ram": ram_percent(),
                "gpu": gpu_util,
                "gpu_w": gpu_w,
                "gpu_temp": gpu_temp,
                "parsec": False,
                "sunshine": sunshine_active(),
                "rec": False,
                "run_age": -1,
                "last_hang": "",
                # See module docstring -- dropped hub-side until server.py's
                # heartbeat "hw" whitelist grows this one key.
                "vr_device": "HP Reverb G2" if vr_device_present() else None,
            }
            body = {k: v for k, v in body.items() if v is not None}
            _post_json(f"{server}/heartbeat", body, POST_TIMEOUT_S)
            _last_heartbeat_ok = time.time()
        except Exception as e:
            print(f"[heartbeat] failed: {e}", file=sys.stderr)
        time.sleep(HEARTBEAT_INTERVAL_S)


def run_loop(server, mac):
    last_inventory_hash = None
    last_inventory_post = 0.0

    while True:
        steam, steam_ids = scan_inventory()
        h = inventory_hash(steam, steam_ids)
        now = time.time()
        if h != last_inventory_hash or (now - last_inventory_post) > INVENTORY_MIN_INTERVAL_S:
            try:
                _post_json(
                    f"{server}/inventory/{mac}",
                    {"steam": steam, "steam_ids": steam_ids, "epic": [], "epic_ids": {}, "apps": []},
                    INVENTORY_POST_TIMEOUT_S,
                )
                last_inventory_hash = h
                last_inventory_post = now
            except Exception as e:
                print(f"[inventory] post failed: {e}", file=sys.stderr)
                try:
                    _post_json(f"{server}/inventory/{mac}", {"err": str(e)[:500]}, INVENTORY_POST_TIMEOUT_S)
                except Exception:
                    pass

        try:
            resp = _get_json(f"{server}/run/{mac}?wait={RUN_WAIT_S}", RUN_HTTP_TIMEOUT_S)
            if not isinstance(resp, dict):
                resp = {}
        except Exception as e:
            print(f"[run] long-poll failed: {e}", file=sys.stderr)
            time.sleep(5)
            continue

        queue = resp.get("queue") or []
        kill = resp.get("kill") or []

        launched = []
        for name in queue:
            appid = steam_ids.get(name)
            if appid is None:
                print(f"[run] queue has unknown title {name!r} (not in local inventory)", file=sys.stderr)
                continue
            try:
                subprocess.Popen(
                    ["steam", "-applaunch", str(appid)],
                    cwd=os.path.expanduser("~"),
                    env=gui_env.get(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                launched.append(name)
            except Exception as e:
                print(f"[run] launch failed for {name!r}: {e}", file=sys.stderr)

        killed = []
        if kill:
            if "*" in kill:
                try:
                    game_stop.stop(["all"])
                except Exception as e:
                    print(f"[run] kill-all failed: {e}", file=sys.stderr)
                killed = list(kill)
            else:
                targets = [str(steam_ids[n]) for n in kill if n in steam_ids]
                if targets:
                    try:
                        game_stop.stop(targets)
                    except Exception as e:
                        print(f"[run] kill failed for {targets}: {e}", file=sys.stderr)
                killed = [n for n in kill if n in steam_ids]

        running = running_snapshot(steam_ids)
        try:
            _post_json(
                f"{server}/run/{mac}/ack",
                {"launched": launched, "running": running, "killed": killed},
                POST_TIMEOUT_S,
            )
        except Exception as e:
            print(f"[run] ack failed: {e}", file=sys.stderr)

        agent_age = int(time.time() - _last_heartbeat_ok) if _last_heartbeat_ok else -1
        try:
            _post_json(f"{server}/agentstuck/{mac}", {"agent_age": agent_age}, POST_TIMEOUT_S)
        except Exception as e:
            print(f"[agentstuck] failed: {e}", file=sys.stderr)


def main():
    if not os.path.exists(CONFIG_PATH):
        print(
            f"No config at {CONFIG_PATH}. Create it with:\n"
            f'  {{"server": "http://<hub-host>:8000"}}',
            file=sys.stderr,
        )
        return 2

    server = load_server_url()
    _, mac, _, _ = identity()
    if not mac:
        print("Could not determine this machine's MAC address (no default route?)", file=sys.stderr)
        return 2

    print(f"[pmadminka-agent] server={server} mac={mac}")

    t = threading.Thread(target=heartbeat_loop, args=(server, mac), daemon=True)
    t.start()

    run_loop(server, mac)
    return 0


if __name__ == "__main__":
    sys.exit(main())
