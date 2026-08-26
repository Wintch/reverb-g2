#!/usr/bin/env python3
"""Read-only local status dashboard for the HP Reverb G2 lab rig (iashur).
Binds to 127.0.0.1 only. Never writes to any device (no panel.py calls).
First slice per the 2026-08-21 kiosk gap analysis -- run by hand, not wired
into the boot path yet.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wmr_usb_ids import KNOWN_USB, all_present as vr_device_present  # noqa: E402 -- shared with pmadminka-agent.py
import gui_env  # noqa: E402 -- shared with pmadminka-agent.py
import rig_telemetry  # noqa: E402 -- shared with pmadminka-agent.py

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


def audio_status():
    # Per-device audio for the command center (2026-08-26): a checkbox + volume slider per
    # output the machine has. `hmd-audio.sh list` prints name|description|active|volume% per
    # sink -- active = it's the default OR a live pw-loopback mirror target (so 'both'/'all'
    # shows several checked). The dashboard checks a set -> POST /api/audio-outputs; a per-row
    # slider -> POST /api/sink-volume. One source of truth: the same script the CLI uses.
    out, rc = run([f"{HOME}/vr/hmd-audio.sh", "list"])
    devices = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) == 4:
                name, desc, active, vol = parts
                devices.append({"name": name, "desc": desc,
                                "active": active == "1",
                                "volume_pct": int(vol) if vol.isdigit() else None})
    default_sink, _ = run(["pactl", "get-default-sink"])
    route = "headset" if "usb" in default_sink.lower() else "external"
    dv = next((d for d in devices if d["name"] == default_sink), None)
    mic_out, _ = run([f"{HOME}/vr/hmd-audio.sh", "mic", "status"])
    return {
        "devices": devices,
        "default_sink": default_sink,
        "route": route,
        "volume_pct": dv["volume_pct"] if dv else None,
        "mic": {"muted": mic_out.strip() == "muted"},
    }


# ---- Headset/screen preview (2026-08-26) ----
# The command-center's embedded headset image. Same PROVEN capture mechanism as
# pmadminka-agent.py (which already pushes these to a remote server from this exact box):
# on this Wayland rig, GNOME's screenshot D-Bus refuses non-portal callers and `import -window
# root` fails (Xwayland rootless has no composited root framebuffer) -- but capturing a SPECIFIC
# mapped Xwayland window by id via XComposite DOES work. We pick the largest mapped window with a
# real WM_CLASS (the mutter guard window has none and would otherwise always win on size). For a
# running game that's its companion window = what the headset shows.
PREVIEW_MAX_W = 1280
PREVIEW_QUALITY = 50
_WIN_RE = re.compile(r'(0x[0-9a-f]+)\s+(?:"[^"]*"|\(has no name\))\s*:\s*\(([^)]*)\)\s+(\d+)x(\d+)\+-?\d+\+-?\d+')


def find_preview_window(min_w=320, min_h=240):
    try:
        out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True,
                             env=gui_env.get(), timeout=5).stdout
    except Exception:
        return None
    best_id, best_area = None, 0
    for line in out.splitlines():
        m = _WIN_RE.search(line)
        if not m:
            continue
        wid, wm_class, w, h = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        if not wm_class.strip() or w < min_w or h < min_h:
            continue
        if w * h > best_area:
            best_area, best_id = w * h, wid
    return best_id


def capture_jpeg(max_w=PREVIEW_MAX_W, quality=PREVIEW_QUALITY):
    wid = find_preview_window()
    if not wid:
        return None
    tmp = f"/tmp/dashboard-preview-{os.getpid()}.jpg"
    try:
        r = subprocess.run(["import", "-window", wid, "-resize", f"{max_w}x", "-quality", str(quality), tmp],
                           env=gui_env.get(), capture_output=True, timeout=10)
        if r.returncode != 0 or not os.path.exists(tmp):
            return None
        with open(tmp, "rb") as f:
            return f.read()
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


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
GUI_ENV = gui_env.get()
HOME = os.path.expanduser("~")
ACTIONS = {
    "compositor-up": {
        # TRIED going through power-on.py -> vr-launcher.py here (2026-08-23, T246
        # follow-up) so the panel diagnostic would run before every manual launch
        # too, not just so it stopped running at boot. REVERTED live the same day:
        # (1) vr-launcher.py's game picker reads stdin with a 15s select() timeout,
        # but this button's subprocess runs with stdin=DEVNULL -- /dev/null is
        # always "ready", so the read returns EOF instantly instead of waiting,
        # landing on "Opcion invalida" with nothing launched (the exact trap
        # vr-launcher.py's own VR_LAUNCH_APPID comment already documents -- this
        # button just wasn't setting it). (2) Worse, even fixing that would change
        # this button's actual job: it's meant to bring up a BARE compositor for
        # the separate "Launch Aircar/Cyberpilot/..." buttons below to use,
        # power-on.py always ends by launching a specific title. jack-in-wayland.sh
        # already does its own panel.py activate + DP-connector poll before Monado
        # comes up (T050) -- that was never the boot-time problem. The actual fix
        # for "don't wake the panel at boot" is disabling vr-boot-selector.service
        # (NEXT-STEP.md, same date); this button never needed to change.
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
    "audio-headset": {
        "label": "Audio -> headset",
        "cmd": [f"{HOME}/vr/hmd-audio.sh", "headset"],
        "cwd": f"{HOME}/vr",
    },
    "audio-external": {
        "label": "Audio -> external",
        "cmd": [f"{HOME}/vr/hmd-audio.sh", "external"],
        "cwd": f"{HOME}/vr",
    },
    "audio-both": {
        "label": "Audio -> both",
        "cmd": [f"{HOME}/vr/hmd-audio.sh", "both"],
        "cwd": f"{HOME}/vr",
    },
}


# Demo launches: one button per (title, head-tracking mode) pair, so the booth
# only ever runs a combination that has been worn and signed off in that EXACT
# setting (docs/75) -- the old "Launch <title>" buttons ran `steam -applaunch`
# against whatever compositor happened to be up, tracking mode unknown. These go
# through vr-launcher.py, which does the full compositor down/up in the requested
# mode, applies the title's own resource profile, refuses to be a second client,
# then launches. VR_LAUNCH_APPID is what skips its 15 s stdin prompt (the trap
# noted on compositor-up above -- stdin is DEVNULL here). U_PACING_APP_LOG=debug so
# app-fps.sh can measure the session afterwards.
# status: "approved" = worn, measured and signed off for guests; "gold" = worn and
# good but explicitly NOT approved yet (see docs/75 for the reason); "untested" =
# never worn in this setting on this stack; "broken" = tried on this stack and it
# does NOT work (kept visible so nobody re-tries it live thinking it's untested).
# Only "approved" is a demo option.
DEMO_LAUNCHES = [
    ("Aircar", "1073390", "3dof", "approved", "Xbox pad. Recentre: A button."),
    ("Aircar", "1073390", "6dof", "gold", "2026-08-26 fix (patch 0097): gyro-pred + freeze + 150mm neck-arc + 50ms spread, auto-applied by the launcher. Wearer: 'super similar a windows', smooth, no bad redraws. Residual: positioning latency on FAST motion (~1m bounded, A recentres). Needs a 30-min soak to certify -> approved."),
    ("Dreams of Dali", "591360", "6dof", "approved", "Headset-only gaze-dwell, no controllers. 46-67 fps measured, experience still good."),
    ("Hellblade", "747350", "6dof", "untested", "Proton prefix still on NTFS (docs/70 bug) -- will not launch until relocated. Motion-controller title."),
    ("The Night Cafe", "482390", "6dof", "broken", "2026-08-26: launches + reaches runtime but renders FLAT 2D (0 delivered frames, headset backlight only) -- old Unity title does not engage VR via xrizer. Parked."),
    ("Anne Frank House VR", "2877690", "6dof", "untested", "Needs Steam Launch Options set first (the XR_RUNTIME_JSON... recipe). Motion-controller title (docs/77)."),
]
for _name, _appid, _tracking, _status, _note in DEMO_LAUNCHES:
    ACTIONS[f"demo-{_appid}-{_tracking}"] = {
        "label": f"{_name} · {_tracking} [{_status}]",
        "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", _tracking],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": _appid, "U_PACING_APP_LOG": "debug",
                # Demo buttons auto-record (RAM -> permanent on session end, docs/80). Approved
                # titles record by default; the record is what turns the live demo into the soak.
                "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": f"{_name} {_tracking} [{_status}]"},
        "demo": {"title": _name, "tracking": _tracking, "status": _status, "note": _note},
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
            env={**GUI_ENV, **action.get("env", {})},
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
    monado = monado_running()
    specs = rig_telemetry.machine_specs()
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "attention": read_attention(),
        "usb": usb_census(),
        "drm": drm_status(),
        "coredumps": coredump_info(),
        "monado": monado,
        "tracking": rig_telemetry.tracking_mode(monado["pids"][0] if monado["running"] else None),
        "gpu": driver_info(),
        "gpu_power": gpu_power(),
        "power_mode": rig_telemetry.power_mode(),
        "audio": audio_status(),
        # Everything below this line mirrors pmadminka-agent.py's heartbeat body
        # (2026-08-23) -- same source functions, so the two never disagree.
        "specs": specs,
        "ram_pct": rig_telemetry.ram_percent(),
        "sunshine": rig_telemetry.sunshine_active(),
        "vr_device": vr_device_present(),
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
  #actions { display:flex; flex-wrap:wrap; gap:8px; }
  #actions button, #compositor-toggle { background:#1b2130; color:#dfe4ee; border:1px solid #333c50;
                     border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer;
                     font-family:inherit; }
  #actions button:hover, #compositor-toggle:hover { background:#242c40; }
  #actions button:disabled, #compositor-toggle:disabled { opacity:.5; cursor:default; }
  #compositor-toggle { font-weight:600; border-width:2px; }
  #compositor-toggle.on { border-color:#4fd67a; color:#4fd67a; }
  #compositor-toggle.off { border-color:#6b7488; color:#dfe4ee; }
  #audio-toggle.on { border-color:#4fd67a; color:#4fd67a; }
  #audio-toggle.off { border-color:#ffb454; color:#ffb454; }
  #vol-wrap { display:flex; align-items:center; gap:8px; }
  #vol { width:150px; accent-color:#7fdbca; }
  #vol-val { font-size:13px; color:#8b93a7; min-width:42px; }
  #action-msg { font-size:13px; color:#8b93a7; min-height:18px; margin-bottom:16px; }
  .pwr-wrap { margin-bottom:10px; }
  .pwr-nums { display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px; }
  .pwr-track { height:10px; border-radius:5px; background:#1c2230; overflow:hidden; position:relative; }
  .pwr-fill { height:100%; border-radius:5px; transition:width .4s ease, background .4s ease; }
  .pwr-limit-marker { position:absolute; top:0; bottom:0; width:2px; background:#ffffff55; }
  .demo { display:flex; align-items:flex-start; gap:12px; padding:8px 0; border-bottom:1px dashed #232838; }
  .demo button { flex:0 0 auto; min-width:190px; text-align:left; }
  .demo .note { font-size:13px; color:#a9b1c3; }
  .demo .st { font-size:11px; font-weight:700; padding:1px 7px; border-radius:5px; margin-right:6px; }
  .st.approved { background:#123321; color:#4fd67a; }
  .st.gold { background:#3a2a0f; color:#ffb454; }
  .st.untested { background:#2a2f3d; color:#8b93a7; }
  .st.broken { background:#3a1414; color:#ff6b6b; }
  .guide li { font-size:13px; color:#c7cdd9; margin:4px 0 4px 16px; }
  .guide b { color:#7fdbca; }
  .adev { display:flex; align-items:center; gap:10px; padding:7px 0; border-bottom:1px dashed #232838; }
  .adev input[type=checkbox] { width:18px; height:18px; accent-color:#4fd67a; flex:0 0 auto; }
  .adev .aname { flex:1 1 auto; font-size:13px; }
  .adev .aname.on { color:#4fd67a; }
  .adev .aname.off { color:#8b93a7; }
  .adev input[type=range] { width:120px; accent-color:#7fdbca; }
  .adev .aval { font-size:12px; color:#8b93a7; min-width:40px; text-align:right; }
</style></head>
<body>
<h1>iashur -- HP Reverb G2 lab status</h1>
<div id="attn"></div>
<div id="actions-row" style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:16px;">
  <button id="compositor-toggle" disabled>compositor: --</button>
  <div id="actions">loading actions...</div>
</div>
<div id="action-msg"></div>
<div class="card" style="margin-bottom:16px">
  <h2>Headset preview <span id="screen-note" class="dim" style="font-size:12px"></span></h2>
  <img id="screen" alt="no preview" style="max-width:100%; border-radius:8px; background:#0b0e14; display:none">
  <div id="screen-empty" class="dim" style="font-size:13px">no hay ventana para previsualizar (arrancá un juego/player)</div>
</div>
<div class="card" style="margin-bottom:16px">
  <h2>Audio outputs -- check one, another, or several (duplicate); per-device volume</h2>
  <div id="audio-devices">loading audio devices...</div>
</div>
<div class="card" style="margin-bottom:16px">
  <h2>Demos -- one button per title + head-tracking mode (only "approved" goes to guests)</h2>
  <div id="demos">loading demos...</div>
  <h2 style="margin-top:14px">Operator guide (standing, every guest)</h2>
  <ul class="guide">
    <li><b>Audio</b>: the "audio" toggle above must read <b>headset</b> before handing over (130%). If sound vanishes mid-session the stream got orphaned by a USB re-enumeration -- click "Audio -&gt; headset" again, it re-routes live.</li>
    <li><b>Window focus</b>: the game's desktop window must be <b>focused</b> or Wine drops gamepad + audio (only head tracking keeps working). If a guest says "no sound / pad dead", click the game window first, don't debug.</li>
    <li><b>Fast head turns (6dof only)</b>: yaw is the weak axis -- a quick side-to-side look drifts the seat. Tell the guest <b>"press A"</b> the moment you see it, don't wait for them to notice.</li>
    <li><b>Light</b>: no automated low-light warning exists. Dim room = tracking runaways in the first ~75 s. Check the room before each 6dof session.</li>
    <li><b>Between titles</b>: "Stop all games" then wait for the session card to read IDLE before the next demo button. Never launch a second title on top of a live one.</li>
  </ul>
</div>
<div class="grid" id="grid">loading...</div>
<div class="ts" id="ts"></div>
<script>
// compositor-up/down are handled by the dedicated toggle button below, not
// listed among the generic one-shot action buttons.
const COMPOSITOR_ACTION_IDS = new Set(['compositor-up', 'compositor-down']);
const AUDIO_ACTION_IDS = new Set(['audio-headset', 'audio-external', 'audio-both']);

async function loadActions() {
  try {
    const r = await fetch('/api/actions');
    const actions = await r.json();
    const el = document.getElementById('actions');
    el.innerHTML = '';
    for (const [id, label] of Object.entries(actions)) {
      if (COMPOSITOR_ACTION_IDS.has(id) || AUDIO_ACTION_IDS.has(id)) continue;
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
function updateCompositorToggle(running) {
  const btn = document.getElementById('compositor-toggle');
  btn.disabled = false;
  btn.className = running ? 'on' : 'off';
  btn.textContent = running ? '● compositor ON -- click to stop' : '○ compositor off -- click to start';
  btn.onclick = () => runAction(running ? 'compositor-down' : 'compositor-up', btn);
}
let audioDragging = false;   // a per-device volume slider is being dragged right now
document.addEventListener('mouseup', () => audioDragging = false);

async function applyAudioOutputs() {
  const checked = [...document.querySelectorAll('#audio-devices input[type=checkbox][data-name]')]
    .filter(c => c.checked).map(c => c.dataset.name);
  const msg = document.getElementById('action-msg');
  if (checked.length === 0) { msg.textContent = 'dejá al menos una salida activa'; return; }
  msg.textContent = 'salidas -> ' + checked.length + ' ...';
  try {
    const r = await fetch('/api/audio-outputs?names=' + encodeURIComponent(checked.join(',')), {method:'POST'});
    const d = await r.json();
    msg.textContent = d.ok ? ('audio: ' + d.message) : ('FALLO: ' + d.message);
  } catch(e) { msg.textContent = 'audio falló: ' + e; }
}
async function setSinkVolume(name, pct) {
  try {
    await fetch('/api/sink-volume?name=' + encodeURIComponent(name) + '&pct=' + encodeURIComponent(pct), {method:'POST'});
  } catch(e) {}
}
async function toggleMic(muted) {
  const msg = document.getElementById('action-msg');
  try {
    const r = await fetch('/api/mic?on=' + (muted ? '1' : '0'), {method:'POST'});
    const d = await r.json();
    msg.textContent = d.ok ? ('mic ' + (muted ? 'ON' : 'OFF (mute)')) : ('mic FALLO: ' + d.message);
  } catch(e) { msg.textContent = 'mic falló: ' + e; }
}
function renderAudioDevices(audio) {
  const el = document.getElementById('audio-devices');
  const devs = (audio && audio.devices) || [];
  // Rebuild only when the device SET changes; otherwise update values in place so we don't
  // yank a checkbox/slider the operator is touching.
  const sig = devs.map(d => d.name).join('|') + '|mic';
  if (el.dataset.sig !== sig) {
    el.dataset.sig = sig; el.innerHTML = '';
    // Mic row first (default OFF/muted).
    const micRow = document.createElement('div'); micRow.className = 'adev';
    micRow.innerHTML = '<input type="checkbox" id="mic-cb"><span class="aname off">🎙️ Micrófono</span>' +
                       '<span class="aval" id="mic-state">off</span>';
    micRow.querySelector('#mic-cb').onchange = e => toggleMic(e.target.checked);
    el.appendChild(micRow);
    for (const d of devs) {
      const row = document.createElement('div'); row.className = 'adev';
      const cb = document.createElement('input'); cb.type='checkbox'; cb.dataset.name=d.name; cb.checked=d.active;
      cb.onchange = applyAudioOutputs;
      const nm = document.createElement('span'); nm.className='aname ' + (d.active?'on':'off'); nm.textContent=d.desc; nm.dataset.name=d.name;
      const sl = document.createElement('input'); sl.type='range'; sl.min=0; sl.max=130; sl.step=5;
      sl.value=d.volume_pct==null?100:d.volume_pct; sl.dataset.name=d.name;
      const vv = document.createElement('span'); vv.className='aval'; vv.textContent=(sl.value)+'%';
      sl.addEventListener('mousedown', () => audioDragging = true);
      sl.oninput = () => vv.textContent = sl.value + '%';
      sl.onchange = () => { setSinkVolume(d.name, sl.value); audioDragging=false; };
      row.appendChild(cb); row.appendChild(nm); row.appendChild(sl); row.appendChild(vv);
      el.appendChild(row);
    }
  } else {
    // in-place value refresh, skipping anything focused/being dragged
    if (audio && audio.mic) {
      const mcb=document.getElementById('mic-cb'), mst=document.getElementById('mic-state');
      if (mcb && document.activeElement!==mcb) mcb.checked = !audio.mic.muted;
      if (mst) mst.textContent = audio.mic.muted ? 'off' : 'ON';
    }
    for (const d of devs) {
      const cb = el.querySelector('input[type=checkbox][data-name="'+CSS.escape(d.name)+'"]');
      const nm = el.querySelector('.aname[data-name="'+CSS.escape(d.name)+'"]');
      const sl = el.querySelector('input[type=range][data-name="'+CSS.escape(d.name)+'"]');
      if (cb && document.activeElement!==cb) cb.checked = d.active;
      if (nm) nm.className = 'aname ' + (d.active?'on':'off');
      if (sl && !audioDragging && document.activeElement!==sl && d.volume_pct!=null) {
        sl.value = d.volume_pct; if (sl.nextSibling) sl.nextSibling.textContent = d.volume_pct + '%';
      }
    }
  }
}
async function loadDemos() {
  try {
    const r = await fetch('/api/demos');
    const demos = await r.json();
    const el = document.getElementById('demos');
    el.innerHTML = '';
    for (const [id, d] of Object.entries(demos)) {
      const row = document.createElement('div');
      row.className = 'demo';
      const btn = document.createElement('button');
      btn.textContent = `Launch ${d.title} · ${d.tracking}`;
      btn.onclick = () => runAction(id, btn);
      const info = document.createElement('div');
      info.className = 'note';
      info.innerHTML = `<span class="st ${d.status}">${d.status.toUpperCase()}</span>${d.note}`;
      row.appendChild(btn);
      row.appendChild(info);
      el.appendChild(row);
    }
  } catch(e) {
    document.getElementById('demos').textContent = 'failed to load demos: ' + e;
  }
}
loadActions();
loadDemos();
// Headset preview: reload the JPEG every ~2s. A 204 (no window) hides the image and shows the
// hint; a real frame swaps in only once it's fully decoded (no flof a half-loaded image).
function refreshScreen() {
  const img = document.getElementById('screen');
  const empty = document.getElementById('screen-empty');
  const probe = new Image();
  probe.onload = () => { img.src = probe.src; img.style.display = 'block'; empty.style.display = 'none'; };
  probe.onerror = () => { img.style.display = 'none'; empty.style.display = 'block'; };
  probe.src = '/api/screen.jpg?t=' + Date.now();
}
setInterval(refreshScreen, 2000);
refreshScreen();
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
    updateCompositorToggle(sessionActive);
    renderAudioDevices(d.audio);
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
    let powerRow;
    if (d.power_mode === 'performance') {
      powerRow = `<span class="ok">PERFORMANCE -- session/game live, full watts</span>`;
    } else if (d.power_mode === 'saver') {
      powerRow = `<span class="dim">SAVER -- idle, minimum watts (normal at rest)</span>`;
    } else {
      powerRow = `<span class="warn">unknown -- vr-power-watchdog.service not installed</span>`;
    }
    const trackingRow = sessionActive
      ? `<div class="row"><span>tracking</span><span class="ok">${d.tracking || '?'}</span></div>`
      : `<div class="row"><span>tracking</span><span class="dim">n/a -- no session</span></div>`;
    const audio = d.audio || {};
    const audioCls = audio.route === 'headset' ? 'ok' : 'warn';
    const audioLabel = `${audio.route || '?'}${audio.muted ? ' (MUTED)' : ''} -- ${audio.volume_pct != null ? audio.volume_pct + '%' : '?'}`;
    const audioRow = `<div class="row"><span>audio output</span><span class="${audioCls}">${audioLabel}</span></div>`;
    const specs = d.specs || {};
    const cpu = specs.cpu || {}, gpuSpec = specs.gpu || {};
    document.getElementById('grid').innerHTML = `
      <div class="card" style="grid-column:1/-1">
        <h2>Session</h2>
        <div class="row"><span>state</span><span class="${sessionActive?'ok':'dim'}">${sessionActive?'ACTIVE -- compositor running':'IDLE -- no game/compositor session right now, this is normal at rest'}</span></div>
        <div class="row"><span>power mode</span>${powerRow}</div>
        ${trackingRow}
        ${audioRow}
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
      <div class="card"><h2>system</h2>
        <div class="row"><span>cpu</span><span>${cpu.model || '?'}${cpu.cores ? ' (' + cpu.cores + 'c/' + (cpu.threads||'?') + 't)' : ''}</span></div>
        <div class="row"><span>gpu</span><span>${gpuSpec.name || '?'}</span></div>
        <div class="row"><span>ram</span><span class="${d.ram_pct > 90 ? 'warn' : ''}">${d.ram_pct != null ? d.ram_pct + '%' : '?'}${specs.ram_gb ? ' of ' + specs.ram_gb + ' GB' : ''}</span></div>
        <div class="row"><span>sunshine (remote play)</span><span class="${d.sunshine?'ok':'dim'}">${d.sunshine ? 'active' : 'inactive'}</span></div>
        <div class="row"><span>vr device present</span><span class="${d.vr_device?'ok':'dim'}">${d.vr_device ? 'yes' : 'no'}</span></div>
        <pre>${d.uptime}</pre>
      </div>
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
            body = json.dumps({k: v["label"] for k, v in ACTIONS.items() if "demo" not in v}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/demos"):
            body = json.dumps({k: v["demo"] for k, v in ACTIONS.items() if "demo" in v}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/screen.jpg"):
            img = capture_jpeg()
            if img is None:
                self.send_response(204)  # no window to preview right now
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(img)))
            self.end_headers()
            self.wfile.write(img)
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

    def _json_post(self, ok, msg):
        body = json.dumps({"ok": ok, "message": msg}).encode()
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        from urllib.parse import urlparse, parse_qs
        if self.path.startswith("/api/sink-volume"):
            q = parse_qs(urlparse(self.path).query)
            try:
                name = q.get("name", [""])[0]
                pct = max(0, min(150, int(q.get("pct", ["100"])[0])))
                assert name
                ok = subprocess.run([f"{HOME}/vr/hmd-audio.sh", "setsink", name, str(pct)],
                                    capture_output=True, text=True).returncode == 0
                self._json_post(ok, f"{name} -> {pct}%")
            except Exception as e:
                self._json_post(False, str(e))
        elif self.path.startswith("/api/mic"):
            q = parse_qs(urlparse(self.path).query)
            on = q.get("on", ["0"])[0] == "1"
            ok = subprocess.run([f"{HOME}/vr/hmd-audio.sh", "mic", "on" if on else "off"],
                                capture_output=True, text=True).returncode == 0
            self._json_post(ok, "mic " + ("on" if on else "off"))
        elif self.path.startswith("/api/audio-outputs"):
            q = parse_qs(urlparse(self.path).query)
            names = [n for n in q.get("names", [""])[0].split(",") if n]
            if not names:
                self._json_post(False, "at least one output must stay checked")
                return
            ok = subprocess.run([f"{HOME}/vr/hmd-audio.sh", "outputs", *names],
                                capture_output=True, text=True).returncode == 0
            self._json_post(ok, "outputs: " + ", ".join(names))
        elif self.path.startswith("/api/volume"):
            q = parse_qs(urlparse(self.path).query)
            try:
                pct = max(0, min(150, int(q.get("pct", ["100"])[0])))
                ok = subprocess.run([f"{HOME}/vr/hmd-audio.sh", "set", str(pct)],
                                    capture_output=True, text=True).returncode == 0
                self._json_post(ok, f"set to {pct}%")
            except Exception as e:
                self._json_post(False, str(e))
        elif self.path.startswith("/api/action/"):
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
    # Mic defaults OFF (muted) on startup -- a demo booth should never come up hot-mic'd.
    try:
        subprocess.run([f"{HOME}/vr/hmd-audio.sh", "mic", "off"], capture_output=True, timeout=5)
    except Exception:
        pass
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("serving on http://127.0.0.1:8765")
    srv.serve_forever()
