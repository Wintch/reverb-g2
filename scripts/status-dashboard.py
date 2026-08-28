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


# ---- pmadminka rental-hub attach/detach (2026-08-27) ----
# pmadminka-agent.py (see project_machine_reservation_system) is what actually makes this
# box remotely rentable -- it runs as its own systemd --user service, independent of this
# dashboard. This just surfaces + toggles that service's state so the operator always knows
# at a glance whether the rig is "standalone" (this dashboard's own read-only status only) or
# "attached" (a remote renter via the hub could queue/kill Steam titles on it too), and can
# detach it in one click. No sudo needed -- it's a --user unit. Matters most right before a
# live demo: the hub is very likely unreachable from the venue network anyway, so standalone
# must be the safe, fully-functional default, not a degraded fallback.
PMADMINKA_SERVICE = "pmadminka-agent.service"


def pmadminka_status():
    out, _ = run(["systemctl", "--user", "is-active", PMADMINKA_SERVICE])
    state = out.strip() or "unknown"
    return {"attached": state == "active", "state": state}


def pmadminka_set_attached(attached):
    action = "start" if attached else "stop"
    out, rc = run(["systemctl", "--user", action, PMADMINKA_SERVICE], timeout=10)
    if rc != 0:
        return False, f"systemctl --user {action} {PMADMINKA_SERVICE} failed: {out}"
    return True, f"pmadminka {'attached' if attached else 'detached'}"


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
    # --no-optional-locks: a plain `git status` refreshes the index and holds .git/index.lock for
    # an instant; polled every few seconds it races a real `git commit` in the same repo (hit
    # 2026-08-27: "Unable to create .git/index.lock: File exists" with no git process alive).
    out, _ = run(["git", "-C", "/home/iam/Documents/reverb-g2", "--no-optional-locks", "log", "-1", "--format=%h %s"])
    dirty, _ = run(["git", "-C", "/home/iam/Documents/reverb-g2", "--no-optional-locks", "status", "--short"])
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
    # Spoken booth cues (voice-guide.py, espeak-ng, Spanish). Play through whatever sink is
    # active -- route audio first (headset for in-visor cues, external for "ponete el casco").
    "voz-ponete": {
        "label": "🔊 Ponete el casco",
        "cmd": [f"{HOME}/vr/voice-guide.py", "cue", "ponete-casco"],
        "cwd": f"{HOME}/vr",
    },
    "voz-secuencia": {
        "label": "🔊 Secuencia guiada",
        "cmd": [f"{HOME}/vr/voice-guide.py", "sequence"],
        "cwd": f"{HOME}/vr",
    },
    "voz-listo": {
        "label": "🔊 Listo, disfrutá",
        "cmd": [f"{HOME}/vr/voice-guide.py", "cue", "listo"],
        "cwd": f"{HOME}/vr",
    },
    "voz-recentrar": {
        "label": "🔊 Apretá A (recentrar)",
        "cmd": [f"{HOME}/vr/voice-guide.py", "cue", "recentrar"],
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
    ("Aircar", "1073390", "6dof", "gold", "2026-08-26 fix (patch 0097): gyro-pred + freeze + 150mm neck-arc + 50ms spread, auto-applied by the launcher. 2026-08-27 SOAK (several min worn): held 90 (0 pacer stalls), 0 USB/companion drops, 0 SLAM loss -- stability certified. Wearer: still/gamepad-only = very good; STAYS GOLD, not approved. The gold->perfect blocker is a felt ~100-200ms positioning-latency (SLAM anchor-age floor) on FAST full-axis head motion -- A recentres, tolerable but 'rompe todo' when moving fast. NOTE: any fps counter you see is the DESKTOP MIRROR (mutter 60Hz vsync); no in-headset counter works (xrizer overlay whitelist)."),
    ("Dreams of Dali", "591360", "6dof", "approved", "Headset-only gaze-dwell, no controllers. 46-67 fps measured, experience still good."),
    ("Wolfenstein: Cyberpilot", "1056970", "6dof", "testing", "2026-08-27: WORKS in-headset (native Bethesda idTech, motion controllers). Launcher auto-applies the Aircar 6dof head recipe (patch 0097 knobs) WITH constellation ON (the game needs 6dof hands). Wearer: hands ~ok, less drift than before, playable; ~2m drift on FAST head turns (bounded). RESET = RIGHT SHIFT held 3s. Perceived ~60fps ('Fake pacer fell behind' spam) -- for 90: minimize the game window (mutter vsyncs any visible window to the 60Hz desktop), lift the GPU 70% power cap, lower graphics/render-scale (docs/23). NOT guest-ready until the 60->90 residual is settled."),
    ("Hellblade", "747350", "6dof", "broken", "2026-08-27 retest: prefix relocated NTFS->ext4 (docs/70), and it's GAMEPAD-played (not motion controllers -- constellation not needed). But it CRASHES in the UE4 render thread on 'start' (LowLevelFatalError RenderingThread.cpp:933, UE4 minidump in the prefix). Worked ONCE 2026-08-21 pre-reinstall ('very promising, steady 45fps' -- docs/75:198); uninstalled+reinstalled 2026-08-26 since. The Aug-21 working prefix still exists at ~/.steam/.../compatdata/747350 but Steam bypasses it (game moved to /mnt/win5). Dedicated retest pending: reuse the Aug-21 prefix / drop SCALE=100 / try another Proton (docs/67 §4 B5)."),
    ("The Night Cafe", "482390", "6dof", "untested", "CORRECTED 2026-08-27: the 2026-08-26 'broken/flat-2D' verdict was WRONG -- that one launch died inside the OpenXR loader because XR_RUNTIME_JSON was unset for that process (the launch-options trap, not a Unity flat-fallback). Never actually reached the runtime. Needs launch options set + a real retest before any verdict."),
    ("Anne Frank House VR", "2877690", "6dof", "broken", "CORRECTED 2026-08-27: DOES reach a real Monado session (BEGIN_SESSION, controllers registered) -- the earlier '0 delivered frames' framing came from the dead-grep metric trap (needs U_PACING_APP_LOG=debug), not a proven flat-fallback. Real cause: engine abandons the session after ONE capability probe and never retries -- matches Valve unity-xr-plugin #97/#111. Engine-side give-up, not a render failure. Parked."),
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

# Aircar 6dof head-tracking VARIANTS (2026-08-27 night, docs/80's closing sections): one button
# per candidate so the wearer can A/B several approaches back to back without an agent editing
# TITLE_PROFILES between runs. Each sets ONLY the env vars that differ from the gold profile;
# vr-launcher.py lets ambient env override its own profile by design ("an operator exporting the
# var explicitly is doing an experiment and the picker must not fight them"), so everything else
# stays exactly the profile. All record via demo-recorder.py with the variant in the comment --
# the recordings ARE the A/B log. VIT_COLLAPSE_LOG=1 on all: free keypoint-count diagnostic.
AIRCAR_VARIANTS = [
    ("A", "horizonte 50ms + clamp 1.5 m/s",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150"},
     "CANDIDATO PRINCIPAL (patch 0100 completo). El 1er test del horizonte SIN clamp mando al wearer 1-3 m fuera de la cabina: la velocidad cruda del SLAM tiene 0.2% de picos de re-localizacion de hasta 127 m/s (= 6 m en UN frame de 50 ms). El clamp al techo fisico de una cabeza sentada (1.5 m/s) mata esos picos y deja pasar todo el movimiento real (p99 = 1.66 m/s). Esperado: el 'menos delay' de antes SIN el 'mas desfasaje'."),
    ("B", "horizonte 25ms + clamp 1.5 m/s",
     {"SLAM_PRED_POSITION_HORIZON_MS": "25", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150"},
     "Igual que A con la mitad de horizonte. Si A todavia se pasa en giros rapidos, esto devuelve algo del delay a cambio de menos deriva."),
    ("C", "sin horizonte (freeze puro 0097) -- CONTROL",
     {"SLAM_PRED_POSITION_HORIZON_MS": "0"},
     "CONTROL: la config de esta misma noche que el wearer aprobo ('viene muy bien, responde mas agil') = SLAM_THREADS=6 + optical-flow mas laxo, SIN horizonte de posicion. Comparar A/B/D/E contra ESTO, no contra la memoria."),
    ("D", "horizonte 50ms + clamp 1.0 m/s",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "100"},
     "A con clamp mas apretado (1.0 m/s). Para si A se siente bien en general pero todavia 'salta' en los giros MAS rapidos."),
    ("E", "sin horizonte + spread 25ms",
     {"SLAM_PRED_POSITION_HORIZON_MS": "0", "SLAM_CORRECTION_SPREAD_MS": "25"},
     "Palanca DISTINTA (investigacion docs/80): reduce a la mitad la ventana de decaimiento del correction-spread, asi un re-anclaje en movimiento rapido 'se acomoda' el doble de rapido. Riesgo: volver al jitter/snap duro de T202. Freeze puro en lo demas, aisla esta sola variable."),
    # ---- round 2 (2026-08-27 night, docs/80): A won on latency; E was smoother but slower.
    # F = the wearer's own ask (A + E's spread). G-J attack where the METERS of yaw drift
    # actually live -- Basalt's backend landmark collapse under yaw (p10 = 0 landmarks above
    # 90 deg/s while the frontend still tracks ~2600 keypoints) -- via per-variant Basalt
    # configs in ~/vr/basalt-variants/ (SLAM_CONFIG=<toml> is passed straight through by
    # jack-in-wayland.sh). All carry F's Monado-side env so only the backend differs.
    ("F", "A + spread 25ms (menos delay + mas suave)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25"},
     "Lo que pediste: la baja demora de A + la suavidad de E. Solo cambia el spread respecto de A. Si es >= A, spread 25 pasa a ser el default."),
    ("G", "F + Basalt recall de landmarks",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/G.toml"},
     "BACKEND. recall_enable=true + vio_marg_lost_landmarks=false: hoy un landmark que sale del encuadre en un giro se BORRA en la siguiente marginalizacion (casi cada frame), y el recall solo re-encuentra los que siguen vivos -- sin apagar el borrado, el recall no tiene que recuperar. Objetivo: que los landmarks sobrevivan al barrido y vuelvan al volver la cabeza."),
    ("H", "F + triangulacion 2cm + 12 keyframes",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/H.toml"},
     "BACKEND. vio_min_triangulation_dist 0.05->0.02 m (un yaw sentado tiene ~0 de baseline: los keyframes que se crean durante el giro no agregan NINGUN landmark porque el umbral de 5 cm los rechaza) + vio_max_kfs 7->12 (los keyframes viejos se marginalizan con sus landmarks; mas ventana = sobreviven mas tiempo). Sin recall."),
    ("I", "F + recall + triangulacion (G+H)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/I.toml"},
     "BACKEND. La combinacion de G y H: los dos mecanismos juntos. Candidato principal del backend si G y H ayudan cada uno por su lado."),
    ("J", "I + recall mas permisivo",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/J.toml"},
     "BACKEND. I + optical_flow_recall_max_patch_norms = los defaults de C++ de Basalt (nuestro JSON usa valores 4x mas estrictos -- una discrepancia interna de Basalt). Si G/I recuperan pocos landmarks, puede ser que el umbral estricto rechace recalls validos."),
    ("K", "F + recall + 12 keyframes (G + kfs, sin tocar triangulacion)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/K.toml"},
     "BACKEND. Agregada tras los soaks: H (triangulacion 2 cm) DESESTABILIZA en reposo (21 disparos en 4 min vs 7 en 20 min de la base) -- profundidades mal condicionadas. K se queda con lo que si sirve: recall (G, ~6x landmarks) + ventana de 12 keyframes para que los landmarks sobrevivan mas tiempo, con la baseline de 5 cm intacta. Requiere patch 0014 (recall acotado en memoria)."),
    # ---- round 3 (2026-08-27 evening, docs/80): the yaw recording replayed offline ranked J
    # first by far (yaw drift 2.62 -> 0.28 m) and then confirmed H1: shifting the camera stamps
    # -10 ms against the IMU cut I's yaw drift 0.96 -> 0.24 m (+10 ms: 4.2 m). Basalt patch 0017
    # exposes that shift as VIT_CAM_TIME_OFFSET_NS. JT = J + that shift.
    # The J sweep pinned the value: -5 and -10 ms tie (rot sum 0.53 vs J's 0.63), -15 is
    # already worse (0.70), -20 breaks (1.86). -7 ms = the middle of the plateau; the driver
    # arithmetic (wmr_camera.c stamps at start + 5.55 ms instead of start + exposure/2) puts
    # the true error at 1-5.5 ms depending on auto-exposure, so the midpoint is the safe bet.
    ("JT", "J + camaras -7 ms (offset IMU-camara)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/J.toml",
      "VIT_CAM_TIME_OFFSET_NS": "-7000000"},
     "TIMING. J + los timestamps de camara adelantados 7 ms respecto del IMU (patch basalt 0017). Offline, sobre tu grabacion, el desfase explica mas deriva en yaw que cualquier config: -5 y -10 ms empatan (0.53 vs 0.63 de J), -15 ya empeora, +10 rompe (4.2 m). Causa: wmr_camera.c estampa el frame en start + medio periodo (5.55 ms) en vez de start + media exposicion. Si en vivo J ya esta bien, esto deberia dejar el giro rapido casi clavado. Comparar contra J."),
    # ---- round 4 (2026-08-27 night, docs/80): J worn = the metres are gone ("varios cm"), what
    # is left is delay on fast motion + jitter/latency on slow motion. Three code reads named
    # three levers, each a Monado patch or env knob on top of J (Basalt config unchanged):
    ("JH", "J + horizonte de posicion 100 ms",
     {"SLAM_PRED_POSITION_HORIZON_MS": "100", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/J.toml"},
     "PREDICCION. Con J el frontend tarda ~46 ms (antes 28) y la pose SLAM llega con 60-100 ms de edad; el horizonte de 50 ms de 0100 CONGELA la posicion el resto de ese tiempo (t_tracker_slam.cpp:1672-1691), o sea un retraso fijo de posicion en cada anchor. 100 ms cubre la edad real; el clamp de 1.5 m/s sigue protegiendo de los picos. Si baja la demora en movimientos rapidos sin volver a 'irse', queda."),
    # 0102 measured the age with Aircar running: p50 115 ms, p90 151, max 359. 100 covers the
    # median only; 180 covers p90 with margin, the 1.5 m/s clamp bounds any single frame to
    # 27 cm of extrapolation.
    ("JH2", "J + horizonte 180 ms (cubre el p90 medido)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "180", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml"},
     "PREDICCION, escalon 2 (sobre P2). La edad de pose medida con Aircar corriendo es p50 115 ms / p90 151 / max 359: JH (100) solo cubre la mediana. 180 cubre el p90; el clamp de 1.5 m/s acota la extrapolacion a 27 cm por frame. Si JH ayudo pero sigue congelando en los giros rapidos, este es el siguiente."),
    # (2026-08-28 00:50: JA and JM moved from J.toml to P2.toml -- JP is the new base after its
    # wearer test, and JH (horizon 100) was refuted worn: more jitter, larger excursions.)
    ("JA", "P2 + correccion promediada (3 anchors)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
      "SLAM_CORRECTION_AVG_N": "3"},
     "JITTER LENTO. Patch 0103: el paso de correccion (spread 25 ms) recibe el PROMEDIO de los ultimos 3 deltas de anchor en vez de cada delta crudo. Con la cabeza casi quieta cada delta es ruido mm del VIO y un decaimiento de 25 ms contra anchors cada 33 ms nunca termina de asentarse: reproduce el ruido a 30 Hz (el 'jitter al mirar lento'). Promediar el input rechaza ese ruido con ~1 anchor de retraso solo en la correccion, no en el movimiento real. Comparar contra J cerca del panel."),
    ("JM", "P2 + stamp a mitad de exposicion (driver)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
      "WMR_CAM_TS_MID_EXPOSURE": "1"},
     "TIMING (arreglo de driver, patch Monado 0101). wmr_camera.c estampaba el frame en start + medio SLOT de 90 Hz (5.55 ms) en vez de start + media EXPOSICION (0.03-4.5 ms, auto): el frame llegaba 1-5.5 ms tarde respecto del IMU. Esto sigue la exposicion frame a frame en vez del -7 ms fijo de JT. Sin VIT_CAM_TIME_OFFSET_NS. Offline JT ya no se distinguia de J en el casco; esta es la version correcta para dejar por defecto si no empeora nada."),
    # ---- round 5 (2026-08-27 ~21:00, docs/80 round P): the frontend cost has a config answer.
    # Offline, single stream, same recording: J = 45 ms p50 (matches the 46 measured worn),
    # J + optical_flow_detection_grid_size 30->40 ("P2") = 26.6 ms p50 / 33 p90 -- under the
    # base's 28 and under the 33 ms camera period -- with J's drift (rot sum 0.78 vs 0.70,
    # noise 0.1). Fewer, larger cells = ~1900 keypoints instead of ~3200; the recall keeps
    # doing its job. JP = that config alone; JX = JP + every Monado-side lever from round 4.
    ("JP", "J con grid 40 (frontend 27 ms en vez de 45)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml"},
     "COSTO. Config P2 = J + optical_flow_detection_grid_size 30->40. Offline sobre tu grabacion: misma deriva que J (0.78 vs 0.70, ruido 0.1) con el frontend en 26.6 ms p50 / 33 p90 en vez de 45 / 56 -- por debajo de la base (28) y del periodo de camara (33). O sea, J sin los 18 ms de demora extra. Si se siente como J pero con menos retraso, es la config nueva de Aircar."),
    # (JX: horizon back to 50 after JH was refuted worn -- 100 ms = more jitter, larger excursions.)
    ("JX", "TODO JUNTO: grid 40 + correccion promediada + stamp exposicion",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
      "SLAM_CORRECTION_AVG_N": "3", "WMR_CAM_TS_MID_EXPOSURE": "1"},
     "La pila completa de esta noche: config P2 (J barato) + JH (horizonte 100 ms) + JA (correccion promediada 3 anchors) + JM (stamp a mitad de exposicion). Para probar DESPUES de JP/JH/JA/JM por separado: si alguno empeora solo, aca se mezcla y no se sabe cual fue."),
    # ---- round 6 (2026-08-28 ~01:30): JA kept (jitter), JM kept (excursions), JH refuted.
    # 0020's age_in/age_out split the pose age: transport 11 ms flat, Basalt in->out p50 59 /
    # p90 170 / p99 265 with the frontend at 29/39/53 -- the 2+2 queue slots are the tail.
    # JQ = JX + both live queues at depth 1 (Basalt patch 0021, VIT_QUEUE_DEPTH).
    ("JQ", "JX + colas de profundidad 1 (menos edad de pose)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
      "SLAM_CORRECTION_AVG_N": "3", "WMR_CAM_TS_MID_EXPOSURE": "1", "VIT_QUEUE_DEPTH": "1"},
     "LATENCIA LATERAL. JX + VIT_QUEUE_DEPTH=1 (patch Basalt 0021): las dos colas vivas (imagen->frontend y frontend->backend) pasan de 2 a 1 slot. Medido en JM: transporte 11 ms fijo, pero exposicion->pose p50 59 / p90 170 / p99 265 ms con el frontend en 29/39/53 -- el resto es cola (4 frames x 33 ms tras un frame lento del backend). Con 1 slot la edad queda acotada a ~2 frames + proceso; se descarta un frame solo cuando hay un atasco real (el IMU cubre). Si baja la demora lateral sin sumar jitter, queda."),
    # R = the ONE wearer session the offline pipeline needs: F's config + EUROC_RECORD (PNG,
    # lossless -- JPG changes the features) + the live calibration dump. ~3 min following
    # yaw-protocol-voice.py's spoken script. Afterwards replay-basalt-variants.py replays the
    # recording through base x2 + G/H/I/J in ~15 min with no headset. EUROC_RECORD_PATH is a
    # PREFIX (the recorder appends _datetime, t_euroc_recorder.cpp:408-414).
    ("R", "GRABAR protocolo yaw (F + EuRoC 3 min)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "EUROC_RECORD": "1",
      "EUROC_RECORD_PATH": "/mnt/vrtmp/euroc-yaw", "VIT_DUMP_CALIB": f"{HOME}/vr/logs/calib-g2-yaw.json"},
     "LA GRABACION. Config F (A + spread 25) + grabacion EuRoC en PNG a /mnt/vrtmp/euroc-yaw_<fecha> + volcado de calibracion. Ponete el casco, arranca Aircar, y segui la voz de yaw-protocol-voice.py (30 s quieto, 10 giros rapidos izq-der, 10 arriba-abajo, 10 inclinaciones, 60 s de juego libre). Despues el agente replayea la grabacion contra todas las configs de backend sin casco. ~3 GB en tmpfs; cerrar el juego al terminar."),
]
for _tag, _label, _env, _note in AIRCAR_VARIANTS:
    ACTIONS[f"variant-1073390-{_tag}"] = {
        "label": f"Aircar · 6dof · variante {_tag}",
        "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": "1073390", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
                # 0102: every 512 predictions log the SLAM anchor age p50/p90/max -- the
                # wearer's "demora" as a number, for every variant from here on.
                "SLAM_POSE_AGE_LOG": "512",
                "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": f"Aircar 6dof variante {_tag}: {_label}",
                **_env},
        "demo": {"title": f"Aircar variante {_tag} ({_label})", "tracking": "6dof",
                 "status": "testing", "note": _note},
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


# ---- Demo round / playlist sequencer (drives playlist-runner.py) -------------
# The web builds a round (name + ordered entries) and fires it; the runner plays each
# experience with a spoken "proximo titulo" cue and a clean teardown between, and can be
# paused (don't start the next) or stopped (teardown + end the round) from here.
PLAYLIST_RUNNER = f"{HOME}/vr/playlist-runner.py"
PLAYLIST_CONTROL = f"{HOME}/vr/logs/playlist-control.json"
PLAYLIST_STATUS = f"{HOME}/vr/logs/playlist-status.json"
DAV2_DEMO_DIR = f"{HOME}/Documents/stereo3d-pack/out/dav2_demo"

# The pool a round can be built from -- ONLY the best (mirror the "approved" DEMO_LAUNCHES)
# plus the in-house sizzle video. Keep the Steam entries in sync with what is guest-ready.
PLAYLIST_CATALOG = [
    {"id": "video-dav2", "type": "video", "name": "Sizzle 2D→3D (dav2)",
     "path": DAV2_DEMO_DIR, "seconds": 180, "mode": "1"},
    {"id": "steam-aircar", "type": "steam", "name": "Aircar",
     "appid": "1073390", "tracking": "3dof", "seconds": 240},
    {"id": "steam-dali", "type": "steam", "name": "Dreams of Dalí",
     "appid": "591360", "tracking": "6dof", "seconds": 240},
]
# The automatic "recommended round": sizzle video -> Aircar (approved 3dof) -> Dali.
DEFAULT_PLAYLIST = {"name": "Ronda automática", "gap_seconds": 6,
                    "entries": [dict(c) for c in PLAYLIST_CATALOG]}


def playlist_running():
    """Truth = is a playlist-runner.py process alive (survives a dashboard restart)."""
    try:
        out = subprocess.run(["pgrep", "-f", "playlist-runner[.]py"],
                             capture_output=True, text=True, timeout=5)
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def playlist_start(pl):
    if playlist_running():
        return False, "ya hay una ronda corriendo"
    entries = pl.get("entries") if isinstance(pl, dict) else None
    if not entries:
        return False, "la ronda no tiene experiencias"
    os.makedirs(f"{HOME}/vr/logs", exist_ok=True)
    path = f"{HOME}/vr/logs/playlist-current.json"
    with open(path, "w") as f:
        json.dump(pl, f, ensure_ascii=False)
    with open(PLAYLIST_CONTROL, "w") as f:
        json.dump({"command": "run"}, f)
    log = open(f"{HOME}/vr/logs/playlist-runner.log", "a")
    subprocess.Popen(["python3", PLAYLIST_RUNNER, path], stdout=log,
                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    return True, f"ronda '{pl.get('name', '?')}' lanzada ({len(entries)} experiencias)"


def playlist_control_cmd(cmd):
    mapped = {"resume": "run"}.get(cmd, cmd)
    if mapped not in ("run", "pause", "stop", "skip"):
        return False, f"comando invalido: {cmd}"
    if not playlist_running() and mapped != "stop":
        return False, "no hay ronda corriendo"
    with open(PLAYLIST_CONTROL, "w") as f:
        json.dump({"command": mapped}, f)
    return True, f"comando: {cmd}"


def playlist_status():
    try:
        st = json.load(open(PLAYLIST_STATUS))
    except Exception:
        st = {}
    st["running"] = playlist_running()
    return st


# ---- Per-user command centre: fixed headset props + adjustable per-user settings ----
USER_PROFILES_FILE = f"{HOME}/vr/logs/user-profiles.json"
BRIGHTNESS_FILE = f"{HOME}/vr/logs/xrizer-brightness"

# What CANNOT be changed on this headset -- read-only reference for the operator, so the
# distinction between "fixed" and "adjustable" is explicit (the user's own framing).
HEADSET_FIXED = {
    "model": "HP Reverb G2 (VR3000 / TPC-Q077-VH)",
    "panel": "2160x2160 per eye, LCD",
    "refresh": "90 / 60 Hz (mode-selectable, not per-user)",
    "panel backlight": "FIXED -- no host brightness command exists (Windows included)",
    "lenses / FOV": "fixed optics, no FOV-crop lever on this stack",
    "IPD": "hardware slider on the headset (60-68 mm) -- physical, not host-settable",
}

# Per-user ADJUSTABLE settings. brightness is the xrizer color-scale gain (1.0 = passthrough).
# "lang" (en/es/ru) picks which STRINGS locale the page's static chrome renders in for that
# user -- default "es" here to match this dashboard's actual daily-use language up to now
# (2026-08-27), not "en", so switching to per-user i18n doesn't silently change what today's
# real operator sees.
DEFAULT_USERS = {
    "active": "default",
    "users": {
        "default": {"height_m": 1.70, "dof": "3dof", "brightness": 1.0,
                    "mapping": "Xbox pad; A recentre", "notes": "", "lang": "es"},
    },
}

SUPPORTED_LANGS = ("en", "es", "ru")


def load_users():
    try:
        d = json.load(open(USER_PROFILES_FILE))
        assert isinstance(d.get("users"), dict) and d.get("active")
        # Migration: profiles saved before "lang" existed default to "es", same reasoning
        # as DEFAULT_USERS above -- don't silently change an existing operator's language.
        for u in d["users"].values():
            u.setdefault("lang", "es")
        return d
    except Exception:
        return json.loads(json.dumps(DEFAULT_USERS))


def save_users(d):
    os.makedirs(f"{HOME}/vr/logs", exist_ok=True)
    tmp = USER_PROFILES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USER_PROFILES_FILE)


def set_brightness_gain(gain):
    """Write the xrizer brightness gain file the patched compositor.rs polls (~every 30 frames)."""
    try:
        g = max(0.0, min(4.0, float(gain)))
    except (TypeError, ValueError):
        return False, "gain must be a number in [0, 4]"
    os.makedirs(f"{HOME}/vr/logs", exist_ok=True)
    with open(BRIGHTNESS_FILE, "w") as f:
        f.write(f"{g:.3f}\n")
    return True, f"brillo -> {g:.2f}x (live si hay juego con el xrizer nuevo)"


def user_center():
    d = load_users()
    active = d["active"]
    cur = d["users"].get(active, {})
    gain = cur.get("brightness", 1.0)
    try:
        gain = float(open(BRIGHTNESS_FILE).read().strip())
    except Exception:
        pass
    return {"fixed": HEADSET_FIXED, "active": active,
            "users": d["users"], "brightness_live": gain}


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
        "pmadminka": pmadminka_status(),
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
  /* ---- Night Panel: iashur's own visual system (2026-08-27) -------------------
     Grounded in the rig's actual constraints, not a generic dark-dashboard skin:
     the booth room is kept dim on purpose (bright light degrades the G2's own
     tracking cameras), the page must render correctly with zero internet access
     (no web fonts -- every stack below is a real font already installed on this
     Debian/GNOME box), and the ok/bad/warn/dim colors are load-bearing safety
     semantics carried over unchanged, not a decorative palette. Two visual
     registers: the always-visible OPERATOR TRAY above (generous, glanceable,
     read every ~30s) and the collapsed ACCESS PANEL at the bottom (dense, mono,
     read rarely -- only when something is actually wrong). */
  :root {
    color-scheme: dark;
    --bg:#17181a; --surface:#212327; --surface-2:#262a30; --line:#34363b;
    --ink:#eae5d8; --ink-dim:#a3a7ac; --ink-inactive:#6b6d72;
    --accent:#7c93a6;
    --ok:#5fae6b; --ok-bg:#1c2c1f; --ok-glow:rgba(95,174,107,.5);
    --bad:#d6483f; --bad-bg:#3a1614; --bad-glow:rgba(214,72,63,.55);
    --warn:#d19a3d; --warn-bg:#332510;
    --font-display:"Liberation Sans Narrow","Arial Narrow","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    --font-body:Cantarell,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
    --font-mono:"DejaVu Sans Mono","Liberation Mono","Noto Sans Mono","Ubuntu Mono",Consolas,"SF Mono",monospace;
    --radius:7px;
  }
  * { box-sizing:border-box; }
  body { background:var(--bg); color:var(--ink); font-family:var(--font-body);
         margin:0; padding:20px; font-size:14px; line-height:1.45; }
  a { color:var(--accent); }
  :focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  h1.wordmark { font-family:var(--font-display); text-transform:uppercase; letter-spacing:.08em;
                font-weight:700; font-size:18px; color:var(--ink); margin:0; }
  h1.wordmark small { display:block; font-family:var(--font-body); text-transform:none;
                       letter-spacing:normal; font-weight:400; font-size:12px; color:var(--ink-dim);
                       margin-top:2px; }
  .card { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px; }
  .card h2 { margin:0 0 10px; font-family:var(--font-display); font-size:16px; font-weight:700;
             text-transform:uppercase; letter-spacing:.05em; color:var(--ink); }
  .card h2 .sub { display:block; font-family:var(--font-body); text-transform:none; letter-spacing:normal;
                  font-weight:400; font-size:12px; color:var(--ink-dim); margin-top:3px; }
  .ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); } .dim { color:var(--ink-inactive); }
  .row { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:5px 0;
         border-bottom:1px solid var(--line); font-size:13px; }
  .row:last-child { border-bottom:none; }
  pre { white-space:pre-wrap; font-family:var(--font-mono); font-size:12px; color:var(--ink-dim); margin:6px 0 0; }
  .ts { font-family:var(--font-mono); color:var(--ink-inactive); font-size:11px; margin-top:18px; text-align:right; }

  #attn { display:none; background:var(--bad); border:none; color:var(--ink);
          padding:14px 18px; border-radius:var(--radius); margin-bottom:14px;
          font-family:var(--font-display); font-weight:800; font-size:18px; text-transform:uppercase;
          letter-spacing:.04em; }
  #attn b { text-decoration:underline; text-underline-offset:3px; }
  @media (prefers-reduced-motion:no-preference) { #attn.pulsing { animation:pulse 1.8s infinite; } }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.7; } }

  .tray-header { display:flex; flex-wrap:wrap; align-items:center; gap:14px; margin-bottom:14px; }
  .status-strip { display:flex; flex-wrap:wrap; gap:6px 16px; align-items:center; margin-left:auto;
                  font-family:var(--font-mono); font-size:12px; }
  .status-dot { display:inline-flex; align-items:center; gap:6px; }
  .status-dot::before { content:""; width:8px; height:8px; border-radius:50%; background:var(--ink-inactive);
                         display:inline-block; flex:0 0 auto; }
  .status-dot.ok::before { background:var(--ok); box-shadow:0 0 6px var(--ok-glow); }
  .status-dot.warn::before { background:var(--warn); }
  .status-dot.bad::before { background:var(--bad); box-shadow:0 0 6px var(--bad-glow); }

  #actions-row { display:flex; flex-wrap:wrap; gap:18px; align-items:center; margin-bottom:10px; }
  .action-group { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding-left:14px; border-left:1px solid var(--line); }
  .ag-label { font-family:var(--font-display); text-transform:uppercase; letter-spacing:.07em;
              font-size:10.5px; color:var(--ink-inactive); margin-right:2px; }
  .ag-buttons { display:flex; flex-wrap:wrap; gap:8px; }
  .ag-buttons button, #compositor-toggle { background:var(--surface-2); color:var(--ink); border:1px solid var(--line);
                     border-radius:6px; padding:9px 14px; font-size:13px; cursor:pointer;
                     font-family:var(--font-body); font-weight:500; }
  .ag-buttons button:hover, #compositor-toggle:hover { border-color:var(--accent); }
  .ag-buttons button:disabled, #compositor-toggle:disabled { opacity:.5; cursor:default; }
  .ag-buttons button.btn-caution { border-color:var(--bad); color:var(--bad); }
  .ag-buttons button.btn-caution:hover { background:var(--bad-bg); }
  #compositor-toggle { font-weight:700; border-width:2px; text-transform:uppercase; letter-spacing:.03em; font-size:12px; }
  #compositor-toggle.on { border-color:var(--ok); color:var(--ok); }
  #compositor-toggle.off { border-color:var(--line); color:var(--ink-dim); }
  #action-msg { font-family:var(--font-mono); font-size:12px; color:var(--ink-dim); min-height:16px; margin-bottom:14px; }

  .glance-grid { display:grid; grid-template-columns: 1.3fr 1fr; gap:14px; margin-bottom:14px; align-items:start; }
  .glance-grid .stack { display:flex; flex-direction:column; gap:14px; }
  @media (max-width:960px) { .glance-grid { grid-template-columns:1fr; } }
  .session-card .row span:first-child { color:var(--ink-dim); }

  .pwr-wrap { margin-bottom:10px; }
  .pwr-nums { display:flex; justify-content:space-between; font-family:var(--font-mono); font-size:12px; margin-bottom:5px; }
  .pwr-track { height:8px; border-radius:4px; background:var(--surface-2); overflow:hidden; position:relative; }
  .pwr-fill { height:100%; border-radius:4px; transition:width .4s ease, background .4s ease; }
  .pwr-limit-marker { position:absolute; top:0; bottom:0; width:2px; background:var(--ink-inactive); opacity:.6; }

  /* Demo launch grid: switch-plates. A title is always fully clickable, but only
     APPROVED reads as lit/go -- gold/untested/broken stay visibly held-back, per
     the brief's safety rule (only "approved" is a real demo option). */
  .demo-group-label { font-family:var(--font-display); text-transform:uppercase; letter-spacing:.07em;
                       font-size:11px; color:var(--ink-inactive); margin:14px 0 8px; }
  .demo-group-label:first-of-type { margin-top:0; }
  .demo-group-label:has(+ .demo-group:empty) { display:none; }
  .demo-group { display:grid; grid-template-columns:repeat(auto-fill, minmax(230px,1fr)); gap:10px; }
  .demo-group:empty { display:none; }
  .demo { display:flex; flex-direction:column; gap:8px; padding:12px; border-radius:var(--radius);
          border:1px solid var(--line); background:var(--surface-2); }
  .demo button { font-family:var(--font-body); font-weight:600; font-size:13px; text-align:left;
                 background:transparent; border:none; color:var(--ink); padding:0; cursor:pointer; width:100%; }
  .demo .note { font-family:var(--font-mono); font-size:11.5px; color:var(--ink-dim); line-height:1.4; }
  .demo .st { font-family:var(--font-mono); font-size:10.5px; font-weight:700; letter-spacing:.03em;
              padding:2px 6px; border-radius:4px; margin-right:6px; text-transform:uppercase; }
  .st.approved { background:var(--ok-bg); color:var(--ok); }
  .st.gold, .st.testing { background:var(--warn-bg); color:var(--warn); }
  .st.untested { background:var(--surface); color:var(--ink-inactive); }
  .st.broken { background:var(--bad-bg); color:var(--bad); }
  .demo:has(.st.approved) { border-color:var(--ok); background:linear-gradient(180deg,#1e2c22,var(--surface-2)); }
  .demo:has(.st.approved) button { font-weight:700; }
  .demo:has(.st.broken) { opacity:.75; }

  .guide { background:var(--surface-2); border:1px dashed var(--line); border-radius:var(--radius);
           padding:12px 16px; margin-top:14px; }
  .guide li { font-size:12.5px; color:var(--ink-dim); margin:5px 0 5px 16px; }
  .guide b { color:var(--ink); }

  .adev { display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid var(--line); }
  .adev:last-child { border-bottom:none; }
  .adev input[type=checkbox] { width:17px; height:17px; accent-color:var(--ok); flex:0 0 auto; }
  .adev .aname { flex:1 1 auto; font-size:13px; }
  .adev .aname.on { color:var(--ink); font-weight:600; }
  .adev .aname.off { color:var(--ink-dim); }
  .adev input[type=range] { width:120px; accent-color:var(--accent); }
  .adev .aval { font-family:var(--font-mono); font-size:11.5px; color:var(--ink-dim); min-width:38px; text-align:right; }

  /* Access panel: the "rarely opened" tier -- everything here is diagnostic, not
     operational, so it stays closed and visually quiet by default; the fault dot
     on the summary is the only thing allowed to interrupt that quiet. */
  details.access-panel { margin-top:16px; border-top:1px solid var(--line); padding-top:10px; }
  details.access-panel > summary { cursor:pointer; list-style:none; display:flex; align-items:center; gap:8px;
      font-family:var(--font-display); text-transform:uppercase; letter-spacing:.07em; font-size:12px;
      font-weight:700; color:var(--ink-dim); padding:6px 0; }
  details.access-panel > summary::-webkit-details-marker { display:none; }
  details.access-panel > summary::before { content:"▸"; display:inline-block; transition:transform .15s ease; }
  details.access-panel[open] > summary::before { transform:rotate(90deg); }
  details.access-panel > summary:hover { color:var(--ink); }
  .fault-dot { width:7px; height:7px; border-radius:50%; display:inline-block; }
  .fault-dot.ok-hidden { background:transparent; }
  .fault-dot.bad { background:var(--bad); box-shadow:0 0 6px var(--bad-glow); }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:10px; }
  .grid .card h2 { font-size:11px; letter-spacing:.07em; color:var(--ink-dim); }
  .grid .row { font-family:var(--font-mono); font-size:12px; }
  @media (max-width:720px) { .grid { grid-template-columns:1fr; } }

  .preview-img { max-width:100%; border-radius:6px; background:var(--bg); display:none; }
  #screen-note { font-size:12px; }
  #screen-empty { font-size:13px; padding:22px 0; text-align:center; }
  #pl-msg { font-size:12px; margin-top:6px; }
</style></head>
<body>
<div id="attn"></div>
<div class="tray-header">
  <h1 class="wordmark"><span data-i18n="h1">iashur</span><small data-i18n="h1_sub">HP Reverb G2 lab status</small></h1>
  <div class="status-strip" id="status-dots">
    <span class="status-dot" id="dot-session"><span data-i18n="dot_session">SESSION</span></span>
    <span class="status-dot" id="dot-audio"><span data-i18n="dot_audio">AUDIO</span></span>
    <span class="status-dot" id="dot-hw"><span data-i18n="dot_hw">HARDWARE</span></span>
    <span class="status-dot" id="dot-hub"><span data-i18n="dot_hub">HUB</span></span>
  </div>
</div>
<div id="actions-row">
  <button id="compositor-toggle" disabled>compositor: --</button>
  <div class="action-group">
    <span class="ag-label" data-i18n="ag_system">System</span>
    <div id="actions-system" class="ag-buttons">loading...</div>
  </div>
  <div class="action-group">
    <span class="ag-label" data-i18n="ag_voice">Voice cues</span>
    <div id="actions-voice" class="ag-buttons"></div>
  </div>
</div>
<div id="action-msg"></div>
<div class="glance-grid">
  <div class="card">
    <h2><span data-i18n="preview_h2">Headset preview</span><span class="sub" id="screen-note"></span></h2>
    <img id="screen" class="preview-img" alt="no preview">
    <div id="screen-empty" class="dim" data-i18n="preview_empty">no window to preview (start a game/player)</div>
  </div>
  <div class="stack">
    <div class="card session-card">
      <h2 data-i18n="session_h2">Session</h2>
      <div id="session-rows">loading...</div>
    </div>
    <div class="card">
      <h2 data-i18n="audio_h2">Audio outputs -- check one, another, or several (duplicate); per-device volume</h2>
      <div id="audio-devices">loading audio devices...</div>
    </div>
  </div>
</div>
<div class="card" style="margin-bottom:14px">
  <h2 data-i18n="cc_h2">Command centre -- headset &amp; user</h2>
  <div id="user-center">loading...</div>
</div>
<div class="card" style="margin-bottom:14px">
  <h2 data-i18n="playlist_h2">Demo round (playlist) -- sequence with "next title" voice cue + clean teardown between each</h2>
  <div id="pl-live"></div>
  <div id="pl-build">loading...</div>
  <div id="pl-msg" class="dim"></div>
</div>
<div class="card">
  <h2 data-i18n="demos_h2">Demos -- one button per title + head-tracking mode (only "approved" goes to guests)</h2>
  <div class="demo-group-label" data-i18n="demos_approved_label">Approved for guests</div>
  <div id="demos-approved" class="demo-group">loading demos...</div>
  <div class="demo-group-label" data-i18n="demos_other_label">In testing -- do not offer to guests</div>
  <div id="demos-other" class="demo-group"></div>
  <div class="guide">
    <h2 style="margin-top:0" data-i18n="guide_h2">Operator guide (standing, every guest)</h2>
    <ul>
      <li data-i18n="guide_1"><b>Audio</b>: the "audio" toggle above must read <b>headset</b> before handing over (130%). If sound vanishes mid-session the stream got orphaned by a USB re-enumeration -- click "Audio -&gt; headset" again, it re-routes live.</li>
      <li data-i18n="guide_2"><b>Window focus</b>: the game's desktop window must be <b>focused</b> or Wine drops gamepad + audio (only head tracking keeps working). If a guest says "no sound / pad dead", click the game window first, don't debug.</li>
      <li data-i18n="guide_3"><b>Fast head turns (6dof only)</b>: yaw is the weak axis -- a quick side-to-side look drifts the seat. Tell the guest <b>"press A"</b> the moment you see it, don't wait for them to notice.</li>
      <li data-i18n="guide_4"><b>Light</b>: no automated low-light warning exists. Dim room = tracking runaways in the first ~75 s. Check the room before each 6dof session.</li>
      <li data-i18n="guide_5"><b>Between titles</b>: "Stop all games" then wait for the session card to read IDLE before the next demo button. Never launch a second title on top of a live one.</li>
    </ul>
  </div>
</div>
<details class="access-panel">
  <summary><span class="fault-dot ok-hidden" id="access-fault-dot"></span><span data-i18n="access_h2">Diagnostics</span></summary>
  <div class="grid" id="grid">loading...</div>
</details>
<div class="ts" id="ts"></div>
<script>
// ---- i18n -------------------------------------------------------------------
// Pattern from tools/docs/GUIA_SITIOS.md's site toolkit: an I18N object keyed by
// lang, data-i18n attributes on static elements, a t() helper for JS-built
// strings, localStorage for per-browser persistence, no page reload on switch.
// Scope, deliberately: this covers static chrome (headers, guide, command-centre
// and playlist labels) -- the heavily dynamic per-tick telemetry text in tick()
// and renderAudioDevices() is NOT localized yet, that's a separate future pass.
const I18N = {
  en: {
    h1: "iashur",
    h1_sub: "HP Reverb G2 lab status",
    dot_session: "SESSION", dot_audio: "AUDIO", dot_hw: "HARDWARE", dot_hub: "HUB",
    session_h2: "Session", access_h2: "Diagnostics",
    ag_system: "System", ag_voice: "Voice cues",
    demos_approved_label: "Approved for guests", demos_other_label: "In testing -- do not offer to guests",
    preview_h2: "Headset preview",
    preview_empty: "no window to preview (start a game/player)",
    audio_h2: "Audio outputs -- check one, another, or several (duplicate); per-device volume",
    cc_h2: "Command centre -- headset & user",
    playlist_h2: "Demo round (playlist) -- sequence with \\"next title\\" voice cue + clean teardown between each",
    demos_h2: "Demos -- one button per title + head-tracking mode (only \\"approved\\" goes to guests)",
    guide_h2: "Operator guide (standing, every guest)",
    guide_1: "<b>Audio</b>: the \\"audio\\" toggle above must read <b>headset</b> before handing over (130%). If sound vanishes mid-session the stream got orphaned by a USB re-enumeration -- click \\"Audio -&gt; headset\\" again, it re-routes live.",
    guide_2: "<b>Window focus</b>: the game's desktop window must be <b>focused</b> or Wine drops gamepad + audio (only head tracking keeps working). If a guest says \\"no sound / pad dead\\", click the game window first, don't debug.",
    guide_3: "<b>Fast head turns (6dof only)</b>: yaw is the weak axis -- a quick side-to-side look drifts the seat. Tell the guest <b>\\"press A\\"</b> the moment you see it, don't wait for them to notice.",
    guide_4: "<b>Light</b>: no automated low-light warning exists. Dim room = tracking runaways in the first ~75 s. Check the room before each 6dof session.",
    guide_5: "<b>Between titles</b>: \\"Stop all games\\" then wait for the session card to read IDLE before the next demo button. Never launch a second title on top of a live one.",
    cc_active_user: "Active user", cc_new_user_ph: "new user", cc_add_btn: "+ add",
    cc_adjustable: "Adjustable (per user)", cc_brightness: "brightness", cc_height: "height (m)",
    cc_dof: "preferred DoF", cc_mapping: "controller mapping", cc_notes: "notes",
    cc_save_btn: "Save user", cc_fixed: "Fixed (not changeable on this headset)", cc_lang: "language",
    pl_name_label: "Name:", pl_name_default: "Demo round",
    pl_auto_btn: "▶ Auto round (all, recommended)", pl_custom_btn: "▶ Fire selection",
    pl_hint: "\\"Next title\\" voice cue + clean teardown between each. Pausable / stoppable once launched.",
    pl_pause: "⏸ Pause (won't start the next one)", pl_resume: "▶ Resume",
    pl_skip: "⏭ Skip", pl_stop: "⏹ Stop and clear the round",
    pm_row_label: "pmadminka (rental hub)", pm_attached: "ATTACHED -- remotely rentable",
    pm_standalone: "standalone -- not attached", pm_attach_btn: "attach", pm_detach_btn: "detach now",
  },
  es: {
    h1: "iashur",
    h1_sub: "estado del lab HP Reverb G2",
    dot_session: "SESIÓN", dot_audio: "AUDIO", dot_hw: "HARDWARE", dot_hub: "HUB",
    session_h2: "Sesión", access_h2: "Diagnóstico",
    ag_system: "Sistema", ag_voice: "Voz",
    demos_approved_label: "Aprobado para invitados", demos_other_label: "En prueba -- no ofrecer a invitados",
    preview_h2: "Vista previa del casco",
    preview_empty: "no hay ventana para previsualizar (arrancá un juego/player)",
    audio_h2: "Salidas de audio -- marcá una, otra, o varias (duplicado); volumen por dispositivo",
    cc_h2: "Centro de comando -- casco & usuario",
    playlist_h2: "Ronda de demo (playlist) -- secuencia con voz \\"próximo título\\" + teardown limpio entre cada uno",
    demos_h2: "Demos -- un botón por título + modo de head-tracking (solo \\"approved\\" se muestra a invitados)",
    guide_h2: "Guía del operador (permanente, para cada invitado)",
    guide_1: "<b>Audio</b>: el toggle de \\"audio\\" de arriba tiene que decir <b>headset</b> antes de entregar el casco (130%). Si el sonido desaparece a mitad de sesión, el stream quedó huérfano por una re-enumeración de USB -- hacé clic en \\"Audio -&gt; headset\\" de nuevo, re-rutea en vivo.",
    guide_2: "<b>Foco de ventana</b>: la ventana de escritorio del juego tiene que estar <b>enfocada</b> o Wine deja de mandar el gamepad + audio (solo el head tracking sigue andando). Si un invitado dice \\"no hay sonido / el pad no anda\\", hacé clic en la ventana del juego primero, no debuguees.",
    guide_3: "<b>Giros rápidos de cabeza (solo 6dof)</b>: el yaw es el eje débil -- un giro rápido de lado a lado hace driftear el asiento. Decile al invitado <b>\\"apretá A\\"</b> apenas lo veas, no esperes a que se dé cuenta.",
    guide_4: "<b>Luz</b>: no existe una alerta automática de poca luz. Sala oscura = descontroles de tracking en los primeros ~75 s. Revisá la sala antes de cada sesión 6dof.",
    guide_5: "<b>Entre títulos</b>: \\"Stop all games\\" y después esperá a que la tarjeta de sesión diga IDLE antes del próximo botón de demo. Nunca lances un segundo título encima de uno en vivo.",
    cc_active_user: "Usuario activo", cc_new_user_ph: "nuevo usuario", cc_add_btn: "+ agregar",
    cc_adjustable: "Ajustable (por usuario)", cc_brightness: "brillo", cc_height: "altura (m)",
    cc_dof: "DoF preferido", cc_mapping: "mapeo de controles", cc_notes: "notas",
    cc_save_btn: "Guardar usuario", cc_fixed: "Fijo (no modificable en este casco)", cc_lang: "idioma",
    pl_name_label: "Nombre:", pl_name_default: "Ronda demo",
    pl_auto_btn: "▶ Ronda automática (todo, recomendada)", pl_custom_btn: "▶ Disparar selección",
    pl_hint: "Voz \\"próximo título\\" + teardown limpio entre cada uno. Pausable / detenible una vez lanzada.",
    pl_pause: "⏸ Pausa (no arranca el próximo)", pl_resume: "▶ Reanudar",
    pl_skip: "⏭ Saltear", pl_stop: "⏹ Detener y limpiar la ronda",
    pm_row_label: "pmadminka (hub de alquiler)", pm_attached: "CONECTADO -- alquilable remotamente",
    pm_standalone: "standalone -- no conectado", pm_attach_btn: "conectar", pm_detach_btn: "desconectar ya",
  },
  ru: {
    h1: "iashur",
    h1_sub: "статус лаборатории HP Reverb G2",
    dot_session: "СЕССИЯ", dot_audio: "АУДИО", dot_hw: "ЖЕЛЕЗО", dot_hub: "ХАБ",
    session_h2: "Сессия", access_h2: "Диагностика",
    ag_system: "Система", ag_voice: "Голосовые подсказки",
    demos_approved_label: "Одобрено для гостей", demos_other_label: "На тестировании -- не предлагать гостям",
    preview_h2: "Предпросмотр с гарнитуры",
    preview_empty: "нет окна для предпросмотра (запустите игру/плеер)",
    audio_h2: "Аудиовыходы -- отметьте один, другой или несколько (дублирование); громкость по устройству",
    cc_h2: "Панель управления -- гарнитура и пользователь",
    playlist_h2: "Демо-раунд (плейлист) -- последовательность с голосовым объявлением «следующий тайтл» + чистое завершение между показами",
    demos_h2: "Демо -- одна кнопка на тайтл + режим head-tracking (гостям показываются только «approved»)",
    guide_h2: "Руководство оператора (постоянное, для каждого гостя)",
    guide_1: "<b>Звук</b>: переключатель «audio» вверху должен показывать <b>headset</b> перед передачей гарнитуры (130%). Если звук пропал посреди сессии -- поток осиротел из-за пере-энумерации USB, нажмите «Audio -&gt; headset» ещё раз, маршрут перестроится на лету.",
    guide_2: "<b>Фокус окна</b>: окно игры на рабочем столе должно быть <b>в фокусе</b>, иначе Wine перестаёт передавать геймпад и звук (продолжает работать только head tracking). Если гость говорит «нет звука / пад не работает» -- сначала кликните по окну игры, не отлаживайте.",
    guide_3: "<b>Быстрые повороты головы (только 6dof)</b>: yaw -- слабая ось, быстрый взгляд из стороны в сторону сдвигает «сиденье». Скажите гостю <b>«нажми A»</b> в момент, когда это заметите, не ждите, пока заметит он.",
    guide_4: "<b>Освещение</b>: автоматического предупреждения о слабом освещении нет. Тёмная комната = сбои трекинга в первые ~75 с. Проверяйте освещение перед каждой 6dof-сессией.",
    guide_5: "<b>Между тайтлами</b>: нажмите «Stop all games» и дождитесь статуса IDLE в карточке сессии перед следующей кнопкой демо. Никогда не запускайте второй тайтл поверх работающего.",
    cc_active_user: "Активный пользователь", cc_new_user_ph: "новый пользователь", cc_add_btn: "+ добавить",
    cc_adjustable: "Настраиваемое (по пользователю)", cc_brightness: "яркость", cc_height: "рост (м)",
    cc_dof: "предпочитаемый DoF", cc_mapping: "раскладка контроллеров", cc_notes: "заметки",
    cc_save_btn: "Сохранить пользователя", cc_fixed: "Фиксировано (нельзя изменить на этой гарнитуре)", cc_lang: "язык",
    pl_name_label: "Название:", pl_name_default: "Демо-раунд",
    pl_auto_btn: "▶ Автораунд (всё, рекомендуется)", pl_custom_btn: "▶ Запустить выбранное",
    pl_hint: "Голосовое объявление «следующий тайтл» + чистое завершение между показами. Можно приостановить / остановить после запуска.",
    pl_pause: "⏸ Пауза (следующий не запустится)", pl_resume: "▶ Продолжить",
    pl_skip: "⏭ Пропустить", pl_stop: "⏹ Остановить и очистить раунд",
    pm_row_label: "pmadminka (хаб аренды)", pm_attached: "ПОДКЛЮЧЕНО -- доступен для удалённой аренды",
    pm_standalone: "автономно -- не подключено", pm_attach_btn: "подключить", pm_detach_btn: "отключить сейчас",
  },
};
let currentLang = 'en';
function t(key) { return (I18N[currentLang] && I18N[currentLang][key]) || I18N.en[key] || key; }
function applyLang(lang, opts) {
  opts = opts || {};
  if (!I18N[lang]) lang = 'en';
  currentLang = lang;
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const val = I18N[lang][key];
    if (val != null) el.innerHTML = val;
  });
  try { localStorage.setItem('iashur-dashboard-lang', lang); } catch(e) {}
  const sel = document.getElementById('cc-lang');
  if (sel) sel.value = lang;
  // Re-render the dynamically-built sections so they pick up the new language
  // immediately instead of waiting for their own next poll.
  if (typeof refreshUserCenter === 'function') refreshUserCenter();
  if (typeof refreshPlaylistBuild === 'function' && !opts.skipPlaylist) refreshPlaylistBuild();
  if (typeof tickPlaylist === 'function') tickPlaylist();
}
async function applyLangAndSave(lang) {
  applyLang(lang);
  try {
    const d = await (await fetch('/api/users', {cache:'no-store'})).json();
    const active = d.active;
    const u = (d.users || {})[active] || {};
    await fetch('/api/user/save', {method:'POST', body: JSON.stringify({
      name: active, height_m: u.height_m, dof: u.dof, brightness: u.brightness,
      mapping: u.mapping, notes: u.notes, lang: lang,
    })});
  } catch(e) {}
}
// compositor-up/down are handled by the dedicated toggle button below, not
// listed among the generic one-shot action buttons.
const COMPOSITOR_ACTION_IDS = new Set(['compositor-up', 'compositor-down']);
const AUDIO_ACTION_IDS = new Set(['audio-headset', 'audio-external', 'audio-both']);

async function loadActions() {
  const sysEl = document.getElementById('actions-system');
  const voiceEl = document.getElementById('actions-voice');
  try {
    const r = await fetch('/api/actions');
    const actions = await r.json();
    sysEl.innerHTML = ''; voiceEl.innerHTML = '';
    for (const [id, label] of Object.entries(actions)) {
      if (COMPOSITOR_ACTION_IDS.has(id) || AUDIO_ACTION_IDS.has(id)) continue;
      const btn = document.createElement('button');
      btn.textContent = label;
      if (id === 'stop-games') btn.classList.add('btn-caution');
      btn.onclick = () => runAction(id, btn);
      // Anything id-prefixed "voz-" (the spoken booth cues) groups separately
      // from the system/hardware actions -- generic on the id, not a hardcoded
      // list, so a future voice cue groups correctly with no code change here.
      (id.startsWith('voz-') ? voiceEl : sysEl).appendChild(btn);
    }
  } catch(e) {
    sysEl.textContent = 'failed to load actions: ' + e;
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
async function pmToggle(currentlyAttached) {
  const msg = document.getElementById('action-msg');
  msg.textContent = currentlyAttached ? 'pmadminka: detaching...' : 'pmadminka: attaching...';
  try {
    const r = await fetch(currentlyAttached ? '/api/pmadminka/detach' : '/api/pmadminka/attach', {method: 'POST'});
    const d = await r.json();
    msg.textContent = (d.ok ? 'OK -- ' : 'FAILED -- ') + d.message;
  } catch(e) {
    msg.textContent = 'pmadminka toggle failed: ' + e;
  }
  tick();
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
  const approvedEl = document.getElementById('demos-approved');
  const otherEl = document.getElementById('demos-other');
  try {
    const r = await fetch('/api/demos');
    const demos = await r.json();
    approvedEl.innerHTML = ''; otherEl.innerHTML = '';
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
      // "approved" is the only status a guest should ever see offered -- kept as
      // its own visually separate group instead of blended into one grid.
      (d.status === 'approved' ? approvedEl : otherEl).appendChild(row);
    }
  } catch(e) {
    approvedEl.textContent = 'failed to load demos: ' + e;
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
  const color = ratio > 0.95 ? '#d6483f' : (ratio > 0.7 ? '#d19a3d' : '#5fae6b');
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
      attn.classList.add('pulsing');
      attn.innerHTML = `<b>NEEDS HUMAN ASSISTANCE</b> -- ${d.attention.message || '(sin mensaje)'}` +
        (d.attention.since ? ` <span style="opacity:.7">(desde ${d.attention.since})</span>` : '');
    } else {
      attn.style.display = 'none';
      attn.classList.remove('pulsing');
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
    // DoF is a per-(player x headset) property: how many axes the current session
    // tracks depends on both the mode Monado was started in AND which headset is
    // connected (a different headset can change what's available). Read live from
    // monado-service's WMR_SLAM/WMR_CAMERAS env (rig_telemetry.tracking_mode).
    const dofMap = {
      '6dof': '6DoF - head + controllers (SLAM)',
      '3dof': '3DoF - head orientation only',
      'ctrl': 'controllers only (no head position)',
    };
    const headset = d.vr_device ? 'HP Reverb G2' : 'headset not detected';
    const trackingRow = sessionActive
      ? `<div class="row"><span>DoF (head tracking)</span><span class="ok">${dofMap[d.tracking] || (d.tracking || '?')} <span class="dim">&middot; ${headset}</span></span></div>`
      : `<div class="row"><span>DoF (head tracking)</span><span class="dim">n/a -- no session (set per player &times; headset when a demo starts)</span></div>`;
    const audio = d.audio || {};
    const audioCls = audio.route === 'headset' ? 'ok' : 'warn';
    const audioLabel = `${audio.route || '?'}${audio.muted ? ' (MUTED)' : ''} -- ${audio.volume_pct != null ? audio.volume_pct + '%' : '?'}`;
    const audioRow = `<div class="row"><span>audio output</span><span class="${audioCls}">${audioLabel}</span></div>`;
    const pm = d.pmadminka || {};
    const pmCls = pm.attached ? 'warn' : 'dim';
    const pmLabel = pm.attached ? t('pm_attached') : t('pm_standalone');
    const pmBtnLabel = pm.attached ? t('pm_detach_btn') : t('pm_attach_btn');
    const pmRow = `<div class="row"><span>${t('pm_row_label')}</span><span class="${pmCls}">${pmLabel}
      <button onclick="pmToggle(${!!pm.attached})" style="margin-left:8px;padding:2px 8px;font-size:12px">${pmBtnLabel}</button></span></div>`;
    const specs = d.specs || {};
    const cpu = specs.cpu || {}, gpuSpec = specs.gpu || {};
    // ---- Operator-tray tier: session state (always visible, the "2-second glance") ----
    document.getElementById('session-rows').innerHTML = `
      <div class="row"><span>state</span><span class="${sessionActive?'ok':'dim'}">${sessionActive?'ACTIVE -- compositor running':'IDLE -- no game/compositor session right now, this is normal at rest'}</span></div>
      <div class="row"><span>power mode</span>${powerRow}</div>
      ${trackingRow}
      ${audioRow}
      ${pmRow}
    `;
    // Master status-strip dots (header row): the true at-a-glance read, one level
    // above even the session card -- SESSION mirrors the state row above; AUDIO
    // mirrors audioCls; HARDWARE folds USB/display/coredump faults into one dot so
    // a real problem is visible without opening the access panel; HUB mirrors the
    // pmadminka attach state (worth a glance before every demo, per docs/86).
    const usbFault = d.usb.present_count < d.usb.total;
    const drmFault = Object.entries(d.drm).some(([, s]) => s === 'disconnected' && sessionActive);
    const hwFault = usbFault || drmFault || d.coredumps.count > 0;
    document.getElementById('dot-session').className = 'status-dot ' + (sessionActive ? 'ok' : 'dim');
    document.getElementById('dot-audio').className = 'status-dot ' + audioCls;
    document.getElementById('dot-hw').className = 'status-dot ' + (hwFault ? 'bad' : 'ok');
    document.getElementById('dot-hub').className = 'status-dot ' + (pm.attached ? 'warn' : 'dim');
    const faultDot = document.getElementById('access-fault-dot');
    if (faultDot) faultDot.className = 'fault-dot ' + (hwFault ? 'bad' : 'ok-hidden');
    // ---- Access-panel tier: diagnostics, read rarely, collapsed by default ----
    document.getElementById('grid').innerHTML = `
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
// ---- Demo round / playlist -------------------------------------------------
async function refreshPlaylistBuild() {
  try {
    const r = await fetch('/api/playlist/catalog');
    const d = await r.json();
    const el = document.getElementById('pl-build');
    const rows = d.catalog.map((c, i) =>
      `<label style="display:block;margin:3px 0"><input type="checkbox" class="pl-cb" data-i="${i}" checked> ${c.name} <span class="dim">(${c.type}${c.tracking ? ', ' + c.tracking : ''}, ${c.seconds}s)</span></label>`
    ).join('');
    el.dataset.catalog = JSON.stringify(d.catalog);
    el.innerHTML =
      `<div style="margin-bottom:6px">${t('pl_name_label')} <input id="pl-name" value="${t('pl_name_default')}" style="width:200px"></div>` +
      rows +
      `<div style="margin-top:8px">
         <button onclick="plStart(false)">${t('pl_auto_btn')}</button>
         <button onclick="plStart(true)">${t('pl_custom_btn')}</button>
       </div>
       <div class="dim" style="font-size:12px;margin-top:6px">${t('pl_hint')}</div>`;
  } catch (e) {
    document.getElementById('pl-build').textContent = 'catalog error: ' + e;
  }
}
async function plStart(custom) {
  let body = '';
  if (custom) {
    const el = document.getElementById('pl-build');
    const catalog = JSON.parse(el.dataset.catalog || '[]');
    const picked = Array.from(document.querySelectorAll('.pl-cb'))
      .filter(cb => cb.checked).map(cb => catalog[parseInt(cb.dataset.i)]);
    if (!picked.length) { document.getElementById('pl-msg').textContent = 'elegí al menos una experiencia'; return; }
    const name = (document.getElementById('pl-name').value || 'Ronda').trim();
    body = JSON.stringify({ name: name, gap_seconds: 6, entries: picked });
  }
  document.getElementById('pl-msg').textContent = 'lanzando ronda...';
  try {
    const r = await fetch('/api/playlist/start', { method: 'POST', body: body });
    const d = await r.json();
    document.getElementById('pl-msg').textContent = (d.ok ? 'OK -- ' : 'FALLO -- ') + d.message;
  } catch (e) { document.getElementById('pl-msg').textContent = 'error: ' + e; }
}
async function plControl(cmd) {
  document.getElementById('pl-msg').textContent = cmd + '...';
  try {
    const r = await fetch('/api/playlist/control?cmd=' + cmd, { method: 'POST' });
    const d = await r.json();
    document.getElementById('pl-msg').textContent = (d.ok ? '' : 'FALLO -- ') + d.message;
  } catch (e) { document.getElementById('pl-msg').textContent = 'error: ' + e; }
}
async function tickPlaylist() {
  try {
    const s = await (await fetch('/api/playlist/status', { cache: 'no-store' })).json();
    const live = document.getElementById('pl-live');
    const build = document.getElementById('pl-build');
    if (s.running) {
      build.style.display = 'none';
      const idx = (s.index != null && s.index >= 0) ? (s.index + 1) : '-';
      const rem = s.remaining_s != null ? (s.remaining_s + 's') : '';
      const paused = s.state === 'paused';
      live.innerHTML =
        `<div class="row"><span><b>${s.name || 'Ronda'}</b> &nbsp; ${idx}/${s.total || '?'} &nbsp; ${s.current || ''}</span>` +
        `<span class="${paused ? 'warn' : 'ok'}">${s.state || ''} ${rem}</span></div>` +
        `<div style="margin-top:8px">
           <button onclick="plControl('pause')">${t('pl_pause')}</button>
           <button onclick="plControl('resume')">${t('pl_resume')}</button>
           <button onclick="plControl('skip')">${t('pl_skip')}</button>
           <button onclick="plControl('stop')">${t('pl_stop')}</button>
         </div>`;
    } else {
      live.innerHTML = '';
      if (build.style.display === 'none') build.style.display = '';
    }
  } catch (e) { /* transient */ }
}
setInterval(tickPlaylist, 2000);
refreshPlaylistBuild();
tickPlaylist();
// ---- Command centre: per-user settings + fixed headset props ----------------
async function refreshUserCenter() {
  try {
    const d = await (await fetch('/api/users', {cache:'no-store'})).json();
    const u = (d.users||{})[d.active] || {};
    // Per-user language PRESET: switching active user (or a fresh load) applies
    // that user's saved "lang" automatically. Guard against the loop this would
    // otherwise cause (applyLang() itself calls refreshUserCenter()): only
    // re-apply and bail out when it actually differs from what's showing now.
    const wantLang = u.lang || currentLang;
    if (wantLang !== currentLang) { applyLang(wantLang); return; }
    const el = document.getElementById('user-center');
    const names = Object.keys(d.users || {});
    const opts = names.map(n => `<option value="${n}" ${n===d.active?'selected':''}>${n}</option>`).join('');
    const gain = (+(d.brightness_live!=null?d.brightness_live:(u.brightness!=null?u.brightness:1))).toFixed(2);
    const esc = s => (s||'').replace(/"/g,'&quot;');
    const fixedRows = Object.entries(d.fixed||{}).map(([k,v]) =>
      `<div class="row"><span>${k}</span><span class="dim">${v}</span></div>`).join('');
    const langOpts = ['en','es','ru'].map(l => `<option value="${l}" ${l===currentLang?'selected':''}>${l.toUpperCase()}</option>`).join('');
    el.innerHTML = `
      <div class="row" style="gap:8px"><span><b>${t('cc_active_user')}</b></span>
        <select id="uc-user" onchange="userSelect(this.value)">${opts}</select>
        <input id="uc-new" placeholder="${t('cc_new_user_ph')}" style="width:130px">
        <button onclick="userAdd()">${t('cc_add_btn')}</button>
        <span style="margin-left:auto">${t('cc_lang')}</span>
        <select id="cc-lang" onchange="applyLangAndSave(this.value)">${langOpts}</select></div>
      <div style="margin-top:10px"><b>${t('cc_adjustable')}</b></div>
      <div class="row"><span>${t('cc_brightness')}</span>
        <input type="range" min="0.5" max="2.5" step="0.05" value="${gain}" id="uc-bri"
               oninput="document.getElementById('uc-bri-v').textContent=(+this.value).toFixed(2)+'x'"
               onchange="setBrightness(this.value)" style="width:220px">
        <span id="uc-bri-v" class="ok">${gain}x</span></div>
      <div class="row"><span>${t('cc_height')}</span>
        <input id="uc-height" type="number" step="0.01" min="1.0" max="2.2" value="${u.height_m||1.7}" style="width:80px"></div>
      <div class="row"><span>${t('cc_dof')}</span>
        <select id="uc-dof"><option ${u.dof==='3dof'?'selected':''}>3dof</option><option ${u.dof==='6dof'?'selected':''}>6dof</option></select></div>
      <div class="row"><span>${t('cc_mapping')}</span><input id="uc-map" value="${esc(u.mapping)}" style="width:260px"></div>
      <div class="row"><span>${t('cc_notes')}</span><input id="uc-notes" value="${esc(u.notes)}" style="width:260px"></div>
      <div style="margin-top:6px"><button onclick="userSave()">${t('cc_save_btn')}</button>
        <span id="uc-msg" class="dim" style="font-size:12px"></span></div>
      <div style="margin-top:12px"><b>${t('cc_fixed')}</b></div>${fixedRows}`;
  } catch(e) { document.getElementById('user-center').textContent = 'error: '+e; }
}
async function userSelect(name) { await fetch('/api/user/select?name='+encodeURIComponent(name), {method:'POST'}); refreshUserCenter(); }
function userAdd() {
  const n = (document.getElementById('uc-new').value||'').trim(); if (!n) return;
  fetch('/api/user/save', {method:'POST', body: JSON.stringify({name:n, height_m:1.7, dof:'3dof', brightness:1.0, mapping:'', notes:'', lang:currentLang, make_active:true})}).then(()=>refreshUserCenter());
}
async function setBrightness(g) { await fetch('/api/brightness?gain='+encodeURIComponent(g), {method:'POST'}); }
async function userSave() {
  const name = document.getElementById('uc-user').value;
  const body = JSON.stringify({ name: name,
    height_m: parseFloat(document.getElementById('uc-height').value)||1.7,
    dof: document.getElementById('uc-dof').value,
    brightness: parseFloat(document.getElementById('uc-bri').value)||1.0,
    mapping: document.getElementById('uc-map').value, notes: document.getElementById('uc-notes').value,
    lang: currentLang });
  const d = await (await fetch('/api/user/save', {method:'POST', body})).json();
  document.getElementById('uc-msg').textContent = (d.ok?'guardado ':'FALLO ')+d.message;
}
(function() {
  let initial = 'en';
  try { initial = localStorage.getItem('iashur-dashboard-lang') || (navigator.language||'en').slice(0,2); } catch(e) {}
  applyLang(initial, {skipPlaylist: true});
})();
refreshUserCenter();
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
        elif self.path.startswith("/api/playlist/catalog"):
            body = json.dumps({"catalog": PLAYLIST_CATALOG,
                               "default": DEFAULT_PLAYLIST}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/playlist/status"):
            body = json.dumps(playlist_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/users"):
            body = json.dumps(user_center()).encode()
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
        elif self.path.startswith("/api/playlist/start"):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            try:
                pl = json.loads(raw) if raw.strip() else DEFAULT_PLAYLIST
            except Exception:
                pl = DEFAULT_PLAYLIST
            try:
                ok, msg = playlist_start(pl)
            except Exception as e:
                ok, msg = False, str(e)
            self._json_post(ok, msg)
        elif self.path.startswith("/api/playlist/control"):
            q = parse_qs(urlparse(self.path).query)
            cmd = q.get("cmd", [""])[0]
            try:
                ok, msg = playlist_control_cmd(cmd)
            except Exception as e:
                ok, msg = False, str(e)
            self._json_post(ok, msg)
        elif self.path.startswith("/api/brightness"):
            q = parse_qs(urlparse(self.path).query)
            ok, msg = set_brightness_gain(q.get("gain", ["1.0"])[0])
            if ok:  # also remember it on the active user's profile
                try:
                    d = load_users()
                    d["users"].setdefault(d["active"], {})["brightness"] = round(
                        max(0.0, min(4.0, float(q.get("gain", ["1.0"])[0]))), 3)
                    save_users(d)
                except Exception:
                    pass
            self._json_post(ok, msg)
        elif self.path.startswith("/api/user/select"):
            q = parse_qs(urlparse(self.path).query)
            name = q.get("name", [""])[0]
            d = load_users()
            if name in d["users"]:
                d["active"] = name
                save_users(d)
                set_brightness_gain(d["users"][name].get("brightness", 1.0))
                self._json_post(True, f"usuario activo: {name}")
            else:
                self._json_post(False, f"no existe el usuario '{name}'")
        elif self.path.startswith("/api/user/save"):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                p = json.loads(raw)
                name = (p.get("name") or "").strip()
                assert name
                d = load_users()
                u = d["users"].get(name, {})
                for k in ("height_m", "dof", "brightness", "mapping", "notes", "lang"):
                    if k in p:
                        u[k] = p[k]
                d["users"][name] = u
                if p.get("make_active"):
                    d["active"] = name
                save_users(d)
                self._json_post(True, f"usuario '{name}' guardado")
            except Exception as e:
                self._json_post(False, str(e))
        elif self.path.startswith("/api/pmadminka/attach"):
            ok, msg = pmadminka_set_attached(True)
            self._json_post(ok, msg)
        elif self.path.startswith("/api/pmadminka/detach"):
            ok, msg = pmadminka_set_attached(False)
            self._json_post(ok, msg)
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
