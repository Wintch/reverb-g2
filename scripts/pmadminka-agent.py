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
  - POST /screens/<mac>: throttled like inventory. GET /stream/<mac> says
    whether anyone is watching right now ({"on": bool}). Only when "on",
    capture ONE jpeg and POST it raw to /frame/<mac> (header X-Screen: 0) --
    zero cost while nobody's looking, matches the existing Windows agent's
    demand-gated design (deploy/run.ps1's Capture-Jpeg, maxW=1280, q=50).

PREVIEW CAPTURE, Linux-specific finding (2026-08-22, tested live): GNOME's
own screenshot D-Bus interface (org.gnome.Shell.Screenshot) refuses non-
portal callers (AccessDenied), and the XDG portal equivalent pops an
interactive consent dialog -- neither is scriptable headlessly. Root-window
capture via Xwayland (`import -window root`) also fails outright: Xwayland
in rootless mode has no real composited root framebuffer to grab. What DOES
work: capturing a SPECIFIC mapped window by ID via XComposite (`import
-window <id>`) -- confirmed live against a plain xterm. So this can only
preview an actual running Xwayland client (a game), picked heuristically as
the largest mapped window -- not the native Wayland desktop background.
That's an acceptable trade for this use case: an idle desktop isn't a
useful preview anyway, and a running game is exactly what a renter wants to
see.

KNOWN GAP, not fixable from this repo: the hub's heartbeat handler
(deploy/server.py) builds the "hw" dict from a fixed field whitelist
that does NOT currently include "vr_device" (or, as of 2026-08-23,
"power_mode"/"tracking") -- so those fields this agent sends are silently
dropped until that whitelist gets an entry added on the pmadminka side,
one per field. Sent anyway so it's a one-line hub fix away from working,
not a two-sided change.

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
import rig_telemetry  # noqa: E402 -- shared with status-dashboard.py

CONFIG_PATH = os.path.expanduser("~/.config/pmadminka-agent/config.json")
STEAMAPPS_DIR = os.path.expanduser("~/.steam/steam/steamapps")

HEARTBEAT_INTERVAL_S = 60
RUN_WAIT_S = 25
POST_TIMEOUT_S = 10
INVENTORY_POST_TIMEOUT_S = 15
INVENTORY_MIN_INTERVAL_S = 30 * 60
SCREENS_MIN_INTERVAL_S = 5 * 60
STREAM_WANT_TIMEOUT_S = 8
PREVIEW_MAX_W = 1280
PREVIEW_QUALITY = 50
PREVIEW_MIN_WIN_W = 200
PREVIEW_MIN_WIN_H = 150

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


# machine_specs/gpu_telemetry/ram_percent/sunshine_active/power_mode moved to
# rig_telemetry.py (2026-08-23) -- shared verbatim with status-dashboard.py so the two
# never drift into reporting the same fact two different ways.


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
            specs = rig_telemetry.machine_specs()
            gpu_util, gpu_w, gpu_temp = rig_telemetry.gpu_telemetry()
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
                "ram": rig_telemetry.ram_percent(),
                "gpu": gpu_util,
                "gpu_w": gpu_w,
                "gpu_temp": gpu_temp,
                "parsec": False,
                "sunshine": rig_telemetry.sunshine_active(),
                "rec": False,
                "run_age": -1,
                "last_hang": "",
                # See module docstring -- dropped hub-side until server.py's
                # heartbeat "hw" whitelist grows this one key.
                "vr_device": "HP Reverb G2" if vr_device_present() else None,
                # Same KNOWN GAP as vr_device above: sent anyway, one hub-side whitelist
                # entry away from actually showing up. "saver"/"performance", or absent
                # if vr-power-watchdog.service isn't installed on this box.
                "power_mode": rig_telemetry.power_mode(),
                # "3dof"/"6dof"/"ctrl", absent when no VR session is live.
                "tracking": rig_telemetry.tracking_mode(),
            }
            body = {k: v for k, v in body.items() if v is not None}
            _post_json(f"{server}/heartbeat", body, POST_TIMEOUT_S)
            _last_heartbeat_ok = time.time()
        except Exception as e:
            print(f"[heartbeat] failed: {e}", file=sys.stderr)
        time.sleep(HEARTBEAT_INTERVAL_S)


_WIN_RE = re.compile(r'(0x[0-9a-f]+)\s+(?:"[^"]*"|\(has no name\))\s*:\s*\(([^)]*)\)\s+(\d+)x(\d+)\+-?\d+\+-?\d+')


def find_preview_window(min_w=PREVIEW_MIN_WIN_W, min_h=PREVIEW_MIN_WIN_H):
    """Best mapped Xwayland window to preview: the largest by area (a running
    game is almost always the biggest thing on screen), among windows that
    have a real WM_CLASS. Root-window capture doesn't work here -- see
    module docstring. The empty-class requirement matters: Mutter's own
    "mutter guard window" is a real, full-screen (1920x1080), invisible
    utility window with NO class -- without this filter it wins on size
    every time and the preview would always capture nothing (confirmed
    live, 2026-08-22)."""
    try:
        out = subprocess.run(
            ["xwininfo", "-root", "-tree"], capture_output=True, text=True,
            env=gui_env.get(), timeout=5,
        ).stdout
    except Exception:
        return None
    best_id, best_area = None, 0
    for line in out.splitlines():
        m = _WIN_RE.search(line)
        if not m:
            continue
        wid, wm_class, w, h = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        if not wm_class.strip():
            continue
        if w < min_w or h < min_h:
            continue
        area = w * h
        if area > best_area:
            best_area, best_id = area, wid
    return best_id


def capture_jpeg(max_w=PREVIEW_MAX_W, quality=PREVIEW_QUALITY):
    wid = find_preview_window()
    if not wid:
        return None
    tmp = f"/tmp/pmadminka-agent-preview-{os.getpid()}.jpg"
    try:
        r = subprocess.run(
            ["import", "-window", wid, "-resize", f"{max_w}x", "-quality", str(quality), tmp],
            env=gui_env.get(), capture_output=True, timeout=10,
        )
        if r.returncode != 0 or not os.path.exists(tmp):
            return None
        with open(tmp, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"[preview] capture failed: {e}", file=sys.stderr)
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def report_screens(server, mac, last_hash, last_post):
    # Static single-screen report -- this rig has no desktop mirroring
    # concept to expose, just "is there something to preview or not"
    # (see capture_jpeg). Resolution from the X11 root geometry.
    w, h = 1920, 1080
    try:
        out = subprocess.run(["xwininfo", "-root"], capture_output=True, text=True,
                              env=gui_env.get(), timeout=5).stdout
        mw = re.search(r"Width:\s*(\d+)", out)
        mh = re.search(r"Height:\s*(\d+)", out)
        if mw and mh:
            w, h = int(mw.group(1)), int(mh.group(1))
    except Exception:
        pass
    screens = [{"i": 0, "w": w, "h": h, "primary": True, "name": "iashur"}]
    h_now = hashlib.sha256(json.dumps(screens, sort_keys=True).encode()).hexdigest()
    now = time.time()
    if h_now != last_hash or (now - last_post) > SCREENS_MIN_INTERVAL_S:
        try:
            _post_json(f"{server}/screens/{mac}", screens, POST_TIMEOUT_S)
            return h_now, now
        except Exception as e:
            print(f"[screens] post failed: {e}", file=sys.stderr)
    return last_hash, last_post


def maybe_post_preview(server, mac):
    """Zero-cost while nobody's watching: one GET to check, nothing else."""
    try:
        want = _get_json(f"{server}/stream/{mac}", STREAM_WANT_TIMEOUT_S)
    except Exception as e:
        print(f"[preview] stream-want check failed: {e}", file=sys.stderr)
        return False
    if not isinstance(want, dict) or not want.get("on"):
        return False
    jpg = capture_jpeg()
    if not jpg:
        return False
    try:
        req = urllib.request.Request(
            f"{server}/frame/{mac}", data=jpg,
            headers={"Content-Type": "image/jpeg", "X-Screen": "0"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=POST_TIMEOUT_S):
            pass
        return True
    except Exception as e:
        print(f"[preview] frame post failed: {e}", file=sys.stderr)
        return False


def run_loop(server, mac):
    last_inventory_hash = None
    last_inventory_post = 0.0
    last_screens_hash = None
    last_screens_post = 0.0

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

        last_screens_hash, last_screens_post = report_screens(server, mac, last_screens_hash, last_screens_post)
        previewed = maybe_post_preview(server, mac)
        # Stay responsive to the preview loop while someone's watching, don't
        # burn a full long-poll window on it -- same tradeoff run.ps1 makes.
        wait = 2 if previewed else RUN_WAIT_S

        try:
            resp = _get_json(f"{server}/run/{mac}?wait={wait}", wait + 10)
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
