#!/usr/bin/env python3
"""Read-only local status dashboard for the HP Reverb G2 lab rig (iashur).
Binds to 127.0.0.1 only. Never writes to any device (no panel.py calls).
First slice per the 2026-08-21 kiosk gap analysis -- run by hand, not wired
into the boot path yet.
"""
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ATTENTION_FILE = "/tmp/vr-needs-attention.json"

# 2026-08-21 incident: the kiosk client polls every few seconds, and with 200+
# coredumps `coredumpctl list` alone can take longer than that -- concurrent
# requests each spawned their own full subprocess fan-out (ThreadingHTTPServer,
# one thread per request), piling up faster than they finished and driving
# load average past 10 with nothing actually wrong on the machine. Cache the
# result and let only one thread at a time actually rebuild it.
_cache_lock = threading.Lock()
_cache = {"data": None, "ts": 0.0}
MIN_REFRESH_INTERVAL_S = 4.0

KNOWN_USB = {
    "04b4:6506": "WMR hub (USB2)",
    "0bda:4c15": "USB Audio",
    "03f0:0580": "QHMD companion (HID control)",
    "04b4:6504": "WMR hub (USB3)",
    "045e:0659": "HoloLens Sensors (cameras)",
}


def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return f"ERROR: {e}", -1


def usb_census():
    out, _ = run(["lsusb"])
    found = {}
    for vidpid, label in KNOWN_USB.items():
        found[vidpid] = {"label": label, "present": vidpid in out}
    tree, _ = run(["lsusb", "-t"])
    present_count = sum(1 for v in found.values() if v["present"])
    return {"devices": found, "present_count": present_count, "total": len(KNOWN_USB), "tree": tree}


def drm_status():
    # Plain read works for most connectors; DP-1 specifically needs the scoped sudo grant.
    result = {}
    for conn in ["DP-1", "DP-2", "HDMI-A-1", "HDMI-A-2"]:
        out, rc = run(["cat", f"/sys/class/drm/card0-{conn}/status"])
        if rc != 0 or not out:
            out, rc = run(["sudo", "-n", "/bin/cat", f"/sys/class/drm/card0-{conn}/status"])
        result[conn] = out if rc == 0 and out else "unknown (no permission)"
    return result


def coredump_info():
    out, _ = run(["coredumpctl", "list", "monado-service"])
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("TIME")]
    last = lines[-1] if lines else None
    return {"count": len(lines), "last": last}


def monado_running():
    out, rc = run(["pgrep", "-x", "monado-service"])
    return {"running": rc == 0, "pids": out.splitlines() if rc == 0 else []}


def driver_info():
    out, _ = run(["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total,temperature.gpu",
                   "--format=csv,noheader"])
    return out


def gpu_power():
    # Numeric, unit-stripped fields for the live indicator -- driver_info()
    # above stays the free-text summary line.
    out, rc = run(["nvidia-smi",
                    "--query-gpu=utilization.gpu,power.draw,power.limit,power.default_limit,power.max_limit",
                    "--format=csv,noheader,nounits"])
    if rc != 0 or not out:
        return None
    try:
        util, draw, limit, default_limit, max_limit = [float(x.strip()) for x in out.split(",")]
        return {
            "util_pct": util,
            "draw_w": draw,
            "limit_w": limit,
            "default_limit_w": default_limit,
            "max_limit_w": max_limit,
        }
    except Exception:
        return None


def git_head():
    out, _ = run(["git", "-C", "/home/iam/Documents/reverb-g2", "log", "-1", "--format=%h %s"])
    dirty, _ = run(["git", "-C", "/home/iam/Documents/reverb-g2", "status", "--short"])
    return {"head": out, "dirty": bool(dirty)}


def uptime():
    out, _ = run(["uptime", "-p"])
    return out


# Action buttons -- each launches a real command, detached (survives this
# server process), with the desktop-session env vars a plain systemd/SSH
# shell doesn't have (found the hard way earlier today: WAYLAND_DISPLAY,
# DISPLAY, XAUTHORITY all needed for anything GUI-shaped). Every command
# here was already run by hand and confirmed working earlier this session --
# nothing new or unverified is exposed as a button.
GUI_ENV = {
    **os.environ,
    "XDG_RUNTIME_DIR": "/run/user/1000",
    "XDG_SESSION_TYPE": "wayland",
    "WAYLAND_DISPLAY": "wayland-0",
    "DISPLAY": ":0",
    "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.50FFU3",
}
HOME = os.path.expanduser("~")
ACTIONS = {
    "compositor-up": {
        "label": "Start compositor (6dof)",
        "cmd": [f"{HOME}/vr/jack-in-wayland.sh", "dev", "1", "6dof"],
        "cwd": f"{HOME}/vr",
    },
    "compositor-down": {
        "label": "Stop compositor",
        "cmd": [f"{HOME}/vr/jack-in-wayland.sh", "down"],
        "cwd": f"{HOME}/vr",
    },
    "activate-panel": {
        "label": "Activate panel (HMD)",
        "cmd": ["python3", f"{HOME}/Documents/reverb-g2/scripts/panel.py", "activate"],
        "cwd": f"{HOME}/Documents/reverb-g2",
    },
    "stop-games": {
        "label": "Stop all games",
        "cmd": ["python3", "scripts/game-stop.py", "stop", "all"],
        "cwd": f"{HOME}/Documents/reverb-g2",
    },
    "launch-aircar": {
        "label": "Launch Aircar",
        "cmd": ["steam", "-applaunch", "1073390"],
        "cwd": f"{HOME}/vr",
    },
    "launch-deadherring": {
        "label": "Launch Dead Herring VR",
        "cmd": ["steam", "-applaunch", "1498490"],
        "cwd": f"{HOME}/vr",
    },
    "launch-cyberpilot": {
        "label": "Launch Wolfenstein Cyberpilot",
        "cmd": ["steam", "-applaunch", "1056970"],
        "cwd": f"{HOME}/vr",
    },
}


def run_action(action_id):
    action = ACTIONS.get(action_id)
    if action is None:
        return False, "unknown action"
    log_path = f"/tmp/vr-action-{action_id}.log"
    with open(log_path, "w") as logf:
        subprocess.Popen(
            action["cmd"],
            cwd=action["cwd"],
            env=GUI_ENV,
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return True, f"launched, log: {log_path}"


def read_attention():
    if not os.path.exists(ATTENTION_FILE):
        return {"active": False}
    try:
        with open(ATTENTION_FILE) as f:
            return json.load(f)
    except Exception as e:
        return {"active": False, "error": str(e)}


def build_status():
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "attention": read_attention(),
        "usb": usb_census(),
        "drm": drm_status(),
        "coredumps": coredump_info(),
        "monado": monado_running(),
        "gpu": driver_info(),
        "gpu_power": gpu_power(),
        "repo": git_head(),
        "uptime": uptime(),
    }


def get_status():
    """Cached wrapper -- only one thread rebuilds at a time, everyone else
    gets the last-known-good result immediately instead of piling on more
    subprocess calls."""
    with _cache_lock:
        now = time.monotonic()
        if _cache["data"] is not None and (now - _cache["ts"]) < MIN_REFRESH_INTERVAL_S:
            return _cache["data"]
        data = build_status()
        _cache["data"] = data
        _cache["ts"] = now
        return data


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>iashur status</title>
<style>
  :root { color-scheme: dark; }
  body { background:#0b0e14; color:#e6e6e6; font-family: 'JetBrains Mono', 'Consolas', monospace;
         margin:0; padding:24px; font-size:16px; }
  h1 { font-size:22px; margin:0 0 20px; color:#7fdbca; }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
  .card { background:#141821; border:1px solid #2a3040; border-radius:10px; padding:16px; }
  .card h2 { margin:0 0 10px; font-size:14px; text-transform:uppercase; letter-spacing:.06em; color:#8b93a7; }
  .ok { color:#4fd67a; } .bad { color:#ff6b6b; } .warn { color:#ffb454; } .dim { color:#6b7488; }
  .row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px dashed #232838; font-size:14px; }
  pre { white-space:pre-wrap; font-size:12px; color:#a9b1c3; margin:6px 0 0; }
  .ts { color:#5b6377; font-size:12px; margin-top:20px; }
  .badge { padding:2px 8px; border-radius:6px; font-size:12px; font-weight:600; }
  .badge.ok { background:#123321; }
  .badge.bad { background:#3a1414; }
  #attn { display:none; background:#4a1414; border:2px solid #ff6b6b; color:#ffdcdc;
          padding:14px 18px; border-radius:10px; margin-bottom:16px; font-size:16px;
          animation: pulse 1.6s infinite; }
  #attn b { color:#ff9d9d; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.55; } }
  #actions { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
  #actions button { background:#1b2130; color:#dfe4ee; border:1px solid #333c50;
                     border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer;
                     font-family:inherit; }
  #actions button:hover { background:#242c40; }
  #actions button:disabled { opacity:.5; cursor:default; }
  #action-msg { font-size:13px; color:#8b93a7; min-height:18px; margin-bottom:16px; }
  .pwr-wrap { margin-bottom:10px; }
  .pwr-nums { display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px; }
  .pwr-track { height:10px; border-radius:5px; background:#1c2230; overflow:hidden; position:relative; }
  .pwr-fill { height:100%; border-radius:5px; transition:width .4s ease, background .4s ease; }
  .pwr-limit-marker { position:absolute; top:0; bottom:0; width:2px; background:#ffffff55; }
</style></head>
<body>
<h1>iashur -- HP Reverb G2 lab status</h1>
<div id="attn"></div>
<div id="actions">loading actions...</div>
<div id="action-msg"></div>
<div class="grid" id="grid">loading...</div>
<div class="ts" id="ts"></div>
<script>
async function loadActions() {
  try {
    const r = await fetch('/api/actions');
    const actions = await r.json();
    const el = document.getElementById('actions');
    el.innerHTML = '';
    for (const [id, label] of Object.entries(actions)) {
      const btn = document.createElement('button');
      btn.textContent = label;
      btn.onclick = () => runAction(id, btn);
      el.appendChild(btn);
    }
  } catch(e) {
    document.getElementById('actions').textContent = 'failed to load actions: ' + e;
  }
}
async function runAction(id, btn) {
  const msg = document.getElementById('action-msg');
  btn.disabled = true;
  msg.textContent = 'running: ' + btn.textContent + ' ...';
  try {
    const r = await fetch('/api/action/' + id, {method: 'POST'});
    const d = await r.json();
    msg.textContent = (d.ok ? 'OK -- ' : 'FAILED -- ') + d.message;
  } catch(e) {
    msg.textContent = 'request failed: ' + e;
  }
  btn.disabled = false;
}
loadActions();
function gpuPowerHtml(p) {
  if (!p) return '<div class="pwr-wrap"><span class="dim">power data unavailable</span></div>';
  const pct = Math.max(0, Math.min(100, (p.draw_w / p.max_limit_w) * 100));
  const defaultPct = (p.default_limit_w / p.max_limit_w) * 100;
  // color ramps with draw relative to the FACTORY DEFAULT limit, not the
  // absolute max -- drawing right up to default is normal, past it is the
  // signal worth flagging (this card is Gigabyte 240W default / 250W max,
  // see docs/22's GPU-identity section).
  const ratio = p.draw_w / p.default_limit_w;
  const color = ratio > 0.95 ? '#ff6b6b' : (ratio > 0.7 ? '#ffb454' : '#4fd67a');
  return `
    <div class="pwr-wrap">
      <div class="pwr-nums">
        <span><b style="color:${color}">${p.draw_w.toFixed(1)} W</b> / ${p.default_limit_w.toFixed(0)} W default (max ${p.max_limit_w.toFixed(0)} W)</span>
        <span class="dim">${p.util_pct.toFixed(0)}% util</span>
      </div>
      <div class="pwr-track">
        <div class="pwr-fill" style="width:${pct}%; background:${color}"></div>
        <div class="pwr-limit-marker" style="left:${defaultPct}%"></div>
      </div>
    </div>`;
}
async function tick() {
  try {
    const r = await fetch('/api/status', {cache: 'no-store'});
    const d = await r.json();
    const attn = document.getElementById('attn');
    if (d.attention && d.attention.active) {
      attn.style.display = 'block';
      attn.innerHTML = `<b>NEEDS HUMAN ASSISTANCE</b> -- ${d.attention.message || '(sin mensaje)'}` +
        (d.attention.since ? ` <span style="opacity:.7">(desde ${d.attention.since})</span>` : '');
    } else {
      attn.style.display = 'none';
    }
    // A DP connector reading "disconnected" and monado not running are the
    // NORMAL resting state -- the G2 never raises DP hotplug until
    // panel.py activate runs, and the compositor is only up during an
    // actual session (docs/22, T048/T049). Only treat these as alarming
    // when a session IS supposed to be active (monado running).
    const sessionActive = d.monado.running;
    const usbRows = Object.entries(d.usb.devices).map(([id, v]) =>
      `<div class="row"><span>${v.label}</span><span class="${v.present?'ok':'bad'}">${v.present?'OK':'MISSING'} (${id})</span></div>`
    ).join('');
    const drmRows = Object.entries(d.drm).map(([c, s]) => {
      let cls, label;
      if (s === 'connected') { cls = 'ok'; label = s; }
      else if (s === 'disconnected' && !sessionActive) { cls = 'dim'; label = s + ' (idle, expected)'; }
      else if (s === 'disconnected') { cls = 'bad'; label = s; }
      else { cls = 'warn'; label = s; }
      return `<div class="row"><span>${c}</span><span class="${cls}">${label}</span></div>`;
    }).join('');
    const monadoCls = sessionActive ? 'ok' : 'dim';
    const monadoLabel = sessionActive ? 'yes (' + d.monado.pids.join(',') + ')' : 'no (idle -- no session running)';
    document.getElementById('grid').innerHTML = `
      <div class="card" style="grid-column:1/-1">
        <h2>Session</h2>
        <div class="row"><span>state</span><span class="${sessionActive?'ok':'dim'}">${sessionActive?'ACTIVE -- compositor running':'IDLE -- no game/compositor session right now, this is normal at rest'}</span></div>
      </div>
      <div class="card"><h2>USB (${d.usb.present_count}/${d.usb.total})</h2>${usbRows}</div>
      <div class="card"><h2>Display connectors</h2>${drmRows}</div>
      <div class="card"><h2>monado-service</h2>
        <div class="row"><span>running</span><span class="${monadoCls}">${monadoLabel}</span></div>
        <div class="row"><span>coredumps (total)</span><span class="${d.coredumps.count>0?'warn':'ok'}">${d.coredumps.count}</span></div>
        <pre>${d.coredumps.last || 'none'}</pre>
      </div>
      <div class="card"><h2>GPU</h2>${gpuPowerHtml(d.gpu_power)}<pre>${d.gpu}</pre></div>
      <div class="card"><h2>repo (reverb-g2)</h2>
        <pre>${d.repo.head}</pre>
        <div class="row"><span>working tree</span><span class="${d.repo.dirty?'warn':'ok'}">${d.repo.dirty?'dirty (routine -- telemetry/logs)':'clean'}</span></div>
      </div>
      <div class="card"><h2>system</h2><pre>${d.uptime}</pre></div>
    `;
    document.getElementById('ts').textContent = 'updated ' + d.generated_at;
  } catch(e) {
    document.getElementById('grid').innerHTML = '<div class="card bad">fetch failed: ' + e + '</div>';
  }
  setTimeout(tick, 6000);
}
tick();
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/actions"):
            body = json.dumps({k: v["label"] for k, v in ACTIONS.items()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/status"):
            body = json.dumps(get_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/api/action/"):
            action_id = self.path.split("/api/action/", 1)[1].strip("/")
            ok, msg = run_action(action_id)
            body = json.dumps({"ok": ok, "message": msg}).encode()
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/attention"):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            if payload.get("active"):
                data = {
                    "active": True,
                    "message": payload.get("message", ""),
                    "since": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                }
                with open(ATTENTION_FILE, "w") as f:
                    json.dump(data, f)
            else:
                if os.path.exists(ATTENTION_FILE):
                    os.remove(ATTENTION_FILE)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("serving on http://127.0.0.1:8765")
    srv.serve_forever()
