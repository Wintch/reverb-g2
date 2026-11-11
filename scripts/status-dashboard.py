#!/usr/bin/env python3
"""Read-only local status dashboard for the HP Reverb G2 lab rig.
Binds to 127.0.0.1 only. Never writes to any device (no panel.py calls).
Run by hand; not wired into the boot path.
"""
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wmr_usb_ids import KNOWN_USB, all_present as vr_device_present  # noqa: E402 -- shared with the other scripts
import gui_env  # noqa: E402 -- shared with the other scripts
import rig_telemetry  # noqa: E402 -- shared with the other scripts

ATTENTION_FILE = "/tmp/vr-needs-attention.json"

# 2026-08-21 incident: the dashboard client polls every few seconds, and with 200+
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


def _hmd_connector():
    """DRM connector the HP Reverb G2 panel is on, by EDID fingerprint (HPN + product
    0x36c1 = bytes 8..11 '22 0e c1 36'); None if the panel is asleep. This is the G2
    display MODEL's id, identical on every G2 unit -- NOT rig-specific, and it never
    reads the per-unit serial (EDID base-block bytes 12..15). /sys .../edid is world-readable."""
    import glob, os
    for edid in glob.glob("/sys/class/drm/card*-*/edid"):
        try:
            with open(edid, "rb") as f:
                head = f.read(12)
        except OSError:
            continue
        if len(head) >= 12 and head[8:12] == b"\x22\x0e\xc1\x36":
            return os.path.basename(os.path.dirname(edid))
    return None


def drm_status():
    # Enumerate the DRM connectors actually present and flag the one the HP Reverb G2
    # panel is on (auto-detected by EDID fingerprint -- the port moved DP-1 -> DP-3 after
    # the 2026-09-03 GPU swap and could move again, so nothing is hardcoded). status is
    # world-readable, so the old scoped-sudo fallback is no longer needed.
    import glob, os
    hmd = _hmd_connector()  # e.g. "card0-DP-3", or None when the panel is down
    result = {}
    for path in sorted(glob.glob("/sys/class/drm/card*-*")):
        name = os.path.basename(path)            # card0-DP-3
        if "-" not in name:
            continue
        conn = name.split("-", 1)[1]             # DP-3, HDMI-A-1, ...
        if not (conn.startswith("DP-") or conn.startswith("HDMI")):
            continue
        out, rc = run(["cat", f"{path}/status"])
        key = conn + (" (HMD)" if name == hmd else "")
        result[key] = out if rc == 0 and out else "unknown"
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
# The command-center's embedded headset image. The capture mechanism is proven on this rig:
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


# ---- Tracking-camera live preview ----
# wmr_camera.c (monado, WMR_CAMERA_SNAPSHOT env, default on) dumps one throttled (~1fps) raw 8-bit
# grayscale PGM per SLAM-tracking camera to ~/vr/cameraN.pgm -- but ONLY while the cameras are
# actually streaming, i.e. 6dof or ctrl tracking mode (rig_telemetry.tracking_mode(); 3dof has no
# cameras at all, see jack-in-wayland.sh's TRACKING_ENV). Same split as the HMD-temperature
# snapshot feature: cheap raw dump in C, the real JPEG encoding happens
# here, in Python, only when a browser actually requests a frame -- never continuously.
CAMERA_COUNT = 4  # HP Reverb G2: 4 tracking cameras (see wmr_camera.c's compute_frame_size comment)
CAMERA_MAX_W = 640
CAMERA_QUALITY = 60
CAMERA_MAX_AGE_S = 8  # older than this -> stale (tracking stopped/3dof/no session), don't serve a frozen frame
_CAMERA_JPG_RE = re.compile(r'^/api/camera(\d+)\.jpg')

try:
    from PIL import Image, ImageOps
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False


def capture_camera_jpeg(index, max_w=CAMERA_MAX_W, quality=CAMERA_QUALITY):
    path = os.path.join(os.path.expanduser("~"), "vr", f"camera{index}.pgm")
    try:
        st = os.stat(path)
    except OSError:
        return None
    if time.time() - st.st_mtime > CAMERA_MAX_AGE_S:
        return None

    if _HAVE_PIL:
        try:
            with Image.open(path) as im:
                im = im.convert("L")
                # WMR SLAM tracking cameras run at low exposure/gain by design (feature
                # detection, not photography) -- raw frames average ~7% brightness, reading as
                # solid black at a glance. Stretch for DISPLAY only, never touches the raw .pgm
                # or the real camera exposure/gain used for tracking.
                im = ImageOps.autocontrast(im)
                if max_w and im.width > max_w:
                    ratio = max_w / im.width
                    im = im.resize((max_w, max(1, round(im.height * ratio))))
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=quality)
                return buf.getvalue()
        except Exception:
            return None

    # Fallback (no Pillow available): shell out to ImageMagick, same subprocess style as
    # capture_jpeg() above -- already confirmed installed and working on this box.
    try:
        r = subprocess.run(
            ["convert", path, "-auto-level", "-resize", f"{max_w}x", "-quality", str(quality), "jpg:-"],
            capture_output=True, timeout=10)
        if r.returncode != 0 or not r.stdout:
            return None
        return r.stdout
    except Exception:
        return None


def git_head():
    # --no-optional-locks: a plain `git status` refreshes the index and holds .git/index.lock for
    # an instant; polled every few seconds it races a real `git commit` in the same repo (hit
    # 2026-08-27: "Unable to create .git/index.lock: File exists" with no git process alive).
    repo = os.path.join(os.path.expanduser("~"), "Documents", "reverb-g2")
    out, _ = run(["git", "-C", repo, "--no-optional-locks", "log", "-1", "--format=%h %s"])
    dirty, _ = run(["git", "-C", repo, "--no-optional-locks", "status", "--short"])
    return {"head": out, "dirty": bool(dirty)}


def uptime():
    out, _ = run(["uptime", "-p"])
    return out


# Action buttons -- each launches a real command, detached (survives this
# server process), with the desktop-session env vars a plain systemd/SSH
# shell doesn't have (WAYLAND_DISPLAY, DISPLAY and XAUTHORITY are all needed for
# anything GUI-shaped). Every command here is known to work when run by hand --
# nothing unverified is exposed as a button.
GUI_ENV = gui_env.get()
HOME = os.path.expanduser("~")
ACTIONS = {
    "compositor-up": {
        # Going through power-on.py -> vr-launcher.py here was tried and rejected, so the
        # panel diagnostic would not run before every manual launch. Reasons:
        # (1) vr-launcher.py's game picker reads stdin with a 15s select() timeout,
        # but this button's subprocess runs with stdin=DEVNULL -- /dev/null is
        # always "ready", so the read returns EOF instantly instead of waiting,
        # landing on "Invalid option" with nothing launched (the exact trap
        # vr-launcher.py's own VR_LAUNCH_APPID comment already documents -- this
        # button just wasn't setting it). (2) Even fixing that would change
        # this button's actual job: it is meant to bring up a BARE compositor for
        # the separate title-launch buttons below to use, whereas
        # power-on.py always ends by launching a specific title. jack-in-wayland.sh
        # already does its own panel.py activate + DP-connector poll before Monado
        # comes up (T050) -- that was never the boot-time problem. The actual fix
        # for "don't wake the panel at boot" is disabling vr-boot-selector.service;
        # this button needs no change.
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
    # Spoken cues (voice-guide.py, espeak-ng, Spanish speech). Play through whatever sink is
    # active -- route audio first (headset for in-visor cues, external for the "put on the headset" cue).
    "voz-ponete": {
        "label": "🔊 Cue: put on the headset",
        "cmd": [f"{HOME}/vr/voice-guide.py", "cue", "ponete-casco"],
        "cwd": f"{HOME}/vr",
    },
    "voz-secuencia": {
        "label": "🔊 Cue: guided sequence",
        "cmd": [f"{HOME}/vr/voice-guide.py", "sequence"],
        "cwd": f"{HOME}/vr",
    },
    "voz-listo": {
        "label": "🔊 Cue: ready, enjoy",
        "cmd": [f"{HOME}/vr/voice-guide.py", "cue", "listo"],
        "cwd": f"{HOME}/vr",
    },
    "voz-recentrar": {
        "label": "🔊 Cue: press A (recentre)",
        "cmd": [f"{HOME}/vr/voice-guide.py", "cue", "recentrar"],
        "cwd": f"{HOME}/vr",
    },
    # (xrizer patch 0008): recenter the RUNNING title's play space on the current head
    # pose, for titles with no button to hold (Dreams of Dali is headset-only; the A-button cue
    # above is Aircar's own recentre). xrizer polls this file every ~30 frames, removes it and
    # resets the Standing + Seated origins; a touch older than 10 s is discarded, so pressing it
    # with no title running is harmless. Flow: the wearer sits, looks straight ahead, the
    # operator presses. See docs/80 (Dalí 6dof section).
    "recenter-xrizer": {
        "label": "🎯 Recentre (wearer looking straight ahead)",
        "cmd": ["/usr/bin/touch", f"{HOME}/vr/logs/xrizer-recenter"],
        "cwd": f"{HOME}/vr",
    },
    # (xrizer patch 0009, worn-validated on Dali 6dof and Aircar 6dof; now baked into the 6dof
    # demo buttons): Dali test action.
    # WMR_USER_PRESENCE=1 makes Monado surface the G2 proximity sensor as XR_EXT_user_presence
    # (patches 0075/0087, threshold flagged provisional); the flag file (content = delay ms) arms
    # xrizer to recentre 2 s after the PRESENT edge. The plain demo button never creates the flag,
    # so its behaviour is unchanged. Worn test: headset on the desk -> title loads -> put it on
    # looking sideways -> the scene should come round by itself ~2 s later (xrizer.txt logs it).
    # Same test for Aircar 6dof (its own profile applies: JQ stack, neck arm 100). The Dali run
    # validated 0009 live: PRESENT edge -> recentre 2.0 s later, scene came round by itself;
    # a 15 s headset adjustment re-armed and fired again (by design: > 15 s since the last fire).
    "test-1073390-autorecenter": {
        "label": "🧪 Aircar auto-recentre on donning (0009)",
        "cmd": ["bash", "-c", f"echo 2000 > {HOME}/vr/logs/xrizer-recenter-on-don; exec python3 {HOME}/vr/vr-launcher.py 1 6dof"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": "1073390", "WMR_USER_PRESENCE": "1", "U_PACING_APP_LOG": "debug",
                "VIT_COLLAPSE_LOG": "1", "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Aircar 6dof autorecenter test (0009)"},
    },
    "test-591360-autorecenter": {
        "label": "🧪 Dalí auto-recentre on donning (0009, unvalidated)",
        "cmd": ["bash", "-c", f"echo 2000 > {HOME}/vr/logs/xrizer-recenter-on-don; exec python3 {HOME}/vr/vr-launcher.py 1 6dof"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": "591360", "WMR_USER_PRESENCE": "1", "U_PACING_APP_LOG": "debug",
                "VIT_COLLAPSE_LOG": "1", "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof autorecenter test (0009)"},
    },
}


# Demo launches: one button per (title, head-tracking mode) pair, so only a combination that
# has been worn and signed off in that EXACT setting is offered as a standard option -- the old
# "Launch <title>" buttons ran `steam -applaunch` against whatever compositor happened to be up,
# tracking mode unknown. These go through vr-launcher.py, which does the full compositor
# down/up in the requested mode, applies the title's own resource profile, refuses to be a
# second client, then launches. VR_LAUNCH_APPID is what skips its 15 s stdin prompt (the trap
# noted on compositor-up above -- stdin is DEVNULL here). U_PACING_APP_LOG=debug so
# app-fps.sh can measure the session afterwards.
# status: "approved" = worn, measured and signed off; "gold" = worn and good but explicitly
# NOT approved yet; "untested" = never worn in this setting on this stack; "broken" = tried
# on this stack and it does NOT work (kept visible so nobody re-tries it live thinking it's
# untested). Only "approved" is a demo option.
DEMO_LAUNCHES = [
    ("Aircar", "1073390", "3dof", "approved", "Xbox pad. Recentre: A button (in-game) or the recentre button (operator). The donning auto-recentre (xrizer 0009) is NOT enabled here -- on this 3dof button the cockpit follows a runtime recentre by only a few degrees (game-side re-basing; it works at the logo and in 6dof). docs/80."),
    ("Aircar", "1073390", "6dof", "gold", "Patch 0097 fix: gyro-pred + freeze + 150mm neck-arc + 50ms spread, auto-applied by the launcher. Multi-minute worn soak: held 90 fps (0 pacer stalls), 0 USB/companion drops, 0 SLAM loss -- stability certified. Still/gamepad-only use is very good; stays gold, not approved. The gold->perfect blocker is a felt ~100-200ms positioning latency (SLAM anchor-age floor) on FAST full-axis head motion; A recentres, tolerable but disruptive when moving fast. NOTE: any fps counter visible on the desktop is the DESKTOP MIRROR (mutter 60Hz vsync); no in-headset counter works (xrizer overlay whitelist)."),
    ("Dreams of Dali", "591360", "6dof", "approved", "Headset-only gaze-dwell, no controllers. Worn check (scale 100, anchor profile): 89-90 fps in 6/8 20-s windows, dips to 79/85 when the GPU hits the 250 W cap (91-96 %) -- keep the cap at 250 W; pacer 0.02 % late; SLAM 30 Hz, 0 guard trips, max 1.57 m. RULES: lit room (light-preflight.sh); headset still on the desk until the title has loaded (~60 s); then put it on, sit looking straight ahead and press the Recentrar button (xrizer 0008, worn-validated: 90-degree test, 0.2 s). It also recentres by itself ~2 s after donning (xrizer 0009, worn-validated); the button stays as fallback. PROFILE CHANGE after the 3060 Ti swap put the machine on a 210 W cap: render scale 100 -> 85, and Basalt detection density 30/3 -> 30/2. Scale 85 restores 7/8 20-s windows at >= 89 fps (scale 100 had fallen to 2/8 under the new cap). Density 30/2 fixes the felt redraw -- it was pose staleness, age_out p50 100.8 -> 36.7 ms. Cost: half the landmarks, so an anchor correction now reads 1.53 m instead of 1.15 m. STILL TO CONFIRM: 30/2 was only ever worn at 4 Basalt threads and this profile runs 6."),
    ("Wolfenstein: Cyberpilot", "1056970", "6dof", "testing", "WORKS in-headset (native Bethesda idTech, motion controllers). Launcher auto-applies the Aircar 6dof head recipe (patch 0097 knobs) WITH constellation ON (the game needs 6dof hands). Hands are usable with less drift than before; ~2m drift on FAST head turns (bounded). RESET = RIGHT SHIFT held 3s. Perceived ~60fps ('Fake pacer fell behind' spam) -- for 90: minimize the game window (mutter vsyncs any visible window to the 60Hz desktop), lift the GPU 70% power cap, lower graphics/render-scale (docs/23). The 60->90 residual is not settled."),
    ("Hellblade", "747350", "6dof", "broken", "Prefix relocated NTFS->ext4 (docs/70); the game is GAMEPAD-played (not motion controllers -- constellation not needed). It CRASHES in the UE4 render thread on 'start' (LowLevelFatalError RenderingThread.cpp:933, UE4 minidump in the prefix). It worked once on an earlier install ('steady 45fps'); that working prefix still exists at ~/.steam/.../compatdata/747350 but Steam bypasses it (game moved to /mnt/win5). Retest options: reuse the old prefix / drop SCALE=100 / try another Proton."),
    ("The Night Cafe", "482390", "6dof", "untested", "An earlier 'broken/flat-2D' verdict was WRONG -- that launch died inside the OpenXR loader because XR_RUNTIME_JSON was unset for that process (the launch-options trap, not a Unity flat-fallback). After the Steam env fix (docs/80), an unworn retest reaches a FOCUSED Monado session, 89 fps delivered, 1 harmless unknown-interface line (IVRSettings_001). Root cause was Steam not applying this title's LaunchOptions; XR_RUNTIME_JSON/IPC_IGNORE_VERSION/PRESSURE_VESSEL_FILESYSTEMS_RW now come from the Steam client env (vr-launcher GAME_ENV) + active_runtime.json. Still needed: a worn test (does it need controller point/grab?)."),
    ("Anne Frank House VR", "2877690", "6dof", "broken", "DOES reach a real Monado session (BEGIN_SESSION, controllers registered) -- an earlier '0 delivered frames' reading came from the dead-grep metric trap (needs U_PACING_APP_LOG=debug), not a proven flat-fallback. Real cause: engine abandons the session after ONE capability probe and never retries -- matches Valve unity-xr-plugin #97/#111. Engine-side give-up, not a render failure. Parked."),
]
# 6dof titles with status approved/gold recentre by themselves when the headset is put on --
# xrizer patch 0009, worn-validated on Dali 6dof and Aircar 6dof (90-degree tests on both
# sides, recentre within ~2 s). WMR_USER_PRESENCE=1 makes Monado surface the G2 proximity
# sensor as XR_EXT_user_presence; the flag file (content = delay in ms) arms xrizer to recentre
# 2 s after the PRESENT edge; a fire < 15 s ago blocks re-arming (sensor flap / headset
# adjustment). The recentre button stays as the manual fallback. Every other button REMOVES
# the flag so the behaviour is explicit per launch. See docs/80 (Dalí 6dof section).
_DON_FLAG = f"{HOME}/vr/logs/xrizer-recenter-on-don"
for _name, _appid, _tracking, _status, _note in DEMO_LAUNCHES:
    # 6dof only. On Aircar 3dof the fire is correct but the cockpit follows it by only a few
    # degrees (the game re-bases the view itself there; docs/80), so the 3dof button keeps the
    # A-button / recentre flow. One-liner to flip once understood.
    _auto = _status in ("approved", "gold") and _tracking == "6dof"
    _prep = f"echo 2000 > {_DON_FLAG}" if _auto else f"rm -f {_DON_FLAG}"
    ACTIONS[f"demo-{_appid}-{_tracking}"] = {
        "label": f"{_name} · {_tracking} [{_status}]",
        "cmd": ["bash", "-c", f"{_prep}; exec python3 {HOME}/vr/vr-launcher.py 1 {_tracking}"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": _appid, "U_PACING_APP_LOG": "debug",
                # Demo buttons auto-record (RAM -> permanent on session end). Approved
                # titles record by default; the record doubles as the soak log.
                "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": f"{_name} {_tracking} [{_status}]",
                **({"WMR_USER_PRESENCE": "1"} if _auto else {})},
        "demo": {"title": _name, "tracking": _tracking, "status": _status, "note": _note},
    }

# The ONE run that can still promote P2 into the global basalt-g2-config.json -- Dali 6dof
# under the P2 backend in a LIT room (a gate run in the dark says nothing; docs/80). Same
# launch as the approved Dali button plus SLAM_CONFIG from the env (ambient env wins over the
# title profile in vr-launcher.py, so Dali's own profile -- scale 100, 6 threads, constellation
# off, no head-prediction knobs -- stays as shipped); records like every demo button so
# worn-grade.py has the CSVs afterwards. If in doubt about the light, run
# scripts/light-preflight.sh first (detached).
ACTIONS["gate-591360-P2"] = {
    "label": "Dreams of Dali · 6dof · P2 gate [lit room only]",
    "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
    "cwd": f"{HOME}/vr",
    "env": {"VR_LAUNCH_APPID": "591360", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
            "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
            "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof P2 gate (lit room)"},
    "demo": {"title": "Dali P2 gate (lit room)", "tracking": "6dof", "status": "testing",
             "note": "RESULT (lit room, 887 landmarks): jumps of 6.6 m at 30 s and 38.6 m at "
                     "107 s -> gate NOT passed; P2 stays on Aircar only, Dali stays on base (docs/80). "
                     "The button remains for repeating the test. P2 PROMOTION TO THE GLOBAL CONFIG, final gate: "
                     "Dali 6dof with the P2 backend in a LIT room, ~10 min, same routine as the "
                     "approval (look around, lean, slow and fast turns). If it feels like base in "
                     "the light ('solid'), P2 can go into the global basalt-g2-config.json. Low light "
                     "does not count: in the dark Dali drifted 161 m with P2 and 80 m with base. If "
                     "in doubt, run scripts/light-preflight.sh first (DARK = do not start)."},
}

# Lever 2 for Dali: the 0099 session anchor Aircar/Cyberpilot already run. Both configs
# drifted ~40 m away in the first two minutes of a worn Dali session (VIO scale snap after a
# rotation-only start), then settled; the anchor bounds an excursion to a 3 m restart.
# Env-only test button; if the worn check is clean it goes into TITLE_PROFILES["591360"].
ACTIONS["test-591360-anchor"] = {
    "label": "Dreams of Dali · 6dof · base + anchor 3 m [test]",
    "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
    "cwd": f"{HOME}/vr",
    "env": {"VR_LAUNCH_APPID": "591360", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
            "SLAM_SESSION_ANCHOR_RADIUS_CM": "300", "SLAM_QUAT_NORM_CHECK": "1",
            "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof base + session anchor 300 cm (test)"},
    "demo": {"title": "Dali base + anchor 3 m (test)", "tracking": "6dof", "status": "testing",
             "note": "RESULT: max 3.45 m (vs 38 m without the anchor), 6 resets of 0.02-0.21 m and yaw <= 0.02 degrees, "
                     "played very similarly -> APPLIED to the Dali profile (vr-launcher.py); the button stays as a reference. "
                     "TEST (docs/80): Dali with the usual base config plus the 3 m anchor guard "
                     "(0099, the same one Aircar runs). Reason: with both configs Dali drifts ~40 m in "
                     "the first 2 min of a session with the headset on from startup and then "
                     "settles; the anchor bounds that to 3 m restarts. Procedure to test alongside: headset "
                     "still on the desk until the game has loaded, only then put it on. Check the log for "
                     "'Tracker diverged ... from the session anchor' and the yaw delta of each reset."},
}

# (docs/113): the Aircar/Cyberpilot head-prediction recipe (SLAM_PREDICTION_TYPE=2 +
# SLAM_PRED_FREEZE_POSITION=1 + SLAM_PRED_NECK_ARM_MM + SLAM_CORRECTION_SPREAD_MS) has NEVER been
# tried on Dali. The earlier "gate-591360-P2" test above is a DIFFERENT axis entirely (Basalt's
# backend landmark/recall config, SLAM_CONFIG=P2.toml) and was rejected for a reason unrelated to
# this recipe (raw VIO/landmark starvation while standing, not a prediction-knob question) -- do
# not read that gate's failure as evidence against this. Values below start conservative, not
# copied blindly: neck-arm 100mm matches Aircar's own tuned value (a roughly fixed neck-pivot-to-
# eye anatomy, not seated/standing-dependent -- see docs/113 for the full reasoning), spread 50ms
# matches Cyberpilot's untested-conservative choice, NOT Aircar's title-specific 25ms (only ever
# validated worn on Aircar itself). Env-only, layers on top of Dali's already-approved anchor +
# quat-check base (ambient env wins over TITLE_PROFILES by design) -- does not touch the approved
# demo button or TITLE_PROFILES["591360"]. UNVALIDATED, needs a worn A/B (docs/113).
ACTIONS["test-591360-predict"] = {
    "label": "🧪 Dalí 6dof + Aircar prediction recipe [unvalidated]",
    "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
    "cwd": f"{HOME}/vr",
    "env": {"VR_LAUNCH_APPID": "591360", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
            "SLAM_PREDICTION_TYPE": "2", "SLAM_PRED_FREEZE_POSITION": "1",
            "SLAM_PRED_NECK_ARM_MM": "100", "SLAM_CORRECTION_SPREAD_MS": "50",
            "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof prediction-recipe test (unvalidated, docs/113)"},
    "demo": {"title": "Dalí + prediction recipe (test)", "tracking": "6dof", "status": "testing",
             "note": "UNVALIDATED (docs/113): adds Aircar/Cyberpilot's head-prediction knobs (TYPE=2 + "
                     "FREEZE + NECK_ARM=100mm + SPREAD=50ms), never tried on Dali, to Dali's approved "
                     "base (anchor 300cm + quat-check); the earlier P2 gate is a DIFFERENT axis (Basalt "
                     "backend) and does not measure this. Goal: see whether the head 'redraw' (the same "
                     "mechanism as docs/80) improves on a standing/gaze-dwell title, not only in the "
                     "seated Aircar cockpit. Protocol: lights on (light-preflight.sh), headset still on "
                     "the desk until the title has loaded, compare against the approved button with the "
                     "same routine (look around, lean, slow and fast turns), and ask specifically about "
                     "'redraw'/'settling' on fast turns -- not only drift in metres."},
}

# (docs/113): the GPU swap dropped the card's max draw 250 W -> 210 W. Dali's approved sign-off
# (DEMO_LAUNCHES note above) needed the OLD card's full 250 W to avoid 79/85 fps dips; an
# unworn sample on the new card already showed ~200/210 W (95 %) with ~1 % of frames >11 ms
# late (a full dropped frame at 90 Hz), and a worn session reported a sustained ~75 fps read
# (avg ~4.9 ms late against the 11.11 ms/90 Hz period -- not just occasional spikes).
# Measurements already showed supersampling ABOVE 100 % buys nothing on Dali (it is
# app-render-capped around 60 fps, reprojected to 90 by the compositor) -- this tests the other
# direction, BELOW 100 %, to see if it buys back compositor-side headroom under the new, lower
# power ceiling. Cheap, reversible, zero code. Superseded: scale 85 is now part of Dali's
# approved profile (see the Dali note above); the button is kept as a reference.
ACTIONS["test-591360-scale85"] = {
    "label": "🧪 Dalí 6dof · scale 85% [test]",
    "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
    "cwd": f"{HOME}/vr",
    "env": {"VR_LAUNCH_APPID": "591360", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
            "XRT_COMPOSITOR_SCALE_PERCENTAGE": "85",
            "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof render scale 85% test (docs/113)"},
    "demo": {"title": "Dalí scale 85% (test)", "tracking": "6dof", "status": "testing",
             "note": "Test (docs/113): lowers XRT_COMPOSITOR_SCALE_PERCENTAGE from 100 to 85 to see "
                     "whether it buys GPU margin under the 210 W ceiling of the RTX 3060 Ti LHR after "
                     "the swap. Measure with frame-pacing.sh under real use (headset on, not menu/idle) "
                     "and compare the late-frame % against the approved button at scale 100. If it does "
                     "not reduce late frames, 100 % remains the real floor (the ceiling is elsewhere -- "
                     "thermal, clocks -- not resolution) and this power axis is closed for this card. "
                     "Superseded: scale 85 is now in Dali's approved profile."},
}

# JQ_ENV = the current Aircar profile (docs/80): P2 backend + averaged correction +
# mid-exposure stamp + queues at depth 1, horizon 50, clamp 150, spread 25. Module-level so the
# JQ button below and every "JQ + one lever" button share one dict and cannot drift from each
# other.
JQ_ENV = {
    "SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
    "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
    "SLAM_CORRECTION_AVG_N": "3", "WMR_CAM_TS_MID_EXPOSURE": "1", "VIT_QUEUE_DEPTH": "1",
    # Neck arm 100 (matches vr-launcher.py TITLE_PROFILES["1073390"]; A/B order 0 ~= 100 < 150
    # < 200 in rotation-onset displacement, 0 showed near-field cockpit jitter; docs/80).
    # Keep in step with the profile: this dict IS the profile as far as the buttons are
    # concerned.
    "SLAM_PRED_NECK_ARM_MM": "100",
}

# Aircar 6dof head-tracking VARIANTS (docs/80, "Pose age, queues, and the worn A/B round that
# made Aircar's profile"): one button per candidate so several approaches can be A/B'd back to
# back without editing TITLE_PROFILES between runs. Each sets ONLY the env vars that differ from
# the gold profile; vr-launcher.py lets ambient env override its own profile by design ("an
# operator exporting the var explicitly is doing an experiment and the picker must not fight
# them"), so everything else stays exactly the profile. All record via demo-recorder.py with the
# variant in the comment -- the recordings ARE the A/B log. VIT_COLLAPSE_LOG=1 on all: free
# keypoint-count diagnostic.
AIRCAR_VARIANTS = [
    ("A", "50ms horizon + 1.5 m/s clamp",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150"},
     "MAIN CANDIDATE (full patch 0100). The first horizon test WITHOUT a clamp sent the wearer 1-3 m out of the cockpit: raw SLAM velocity has 0.2% relocalization spikes of up to 127 m/s (= 6 m in ONE 50 ms frame). Clamping at the physical ceiling of a seated head (1.5 m/s) kills those spikes and lets all real motion through (p99 = 1.66 m/s). Expected: the earlier 'less delay' WITHOUT the larger offset."),
    ("B", "25ms horizon + 1.5 m/s clamp",
     {"SLAM_PRED_POSITION_HORIZON_MS": "25", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150"},
     "Same as A with half the horizon. If A still overshoots on fast turns, this gives back some delay in exchange for less drift."),
    ("C", "no horizon (pure 0097 freeze) -- CONTROL",
     {"SLAM_PRED_POSITION_HORIZON_MS": "0"},
     "CONTROL: SLAM_THREADS=6 + looser optical flow, no position horizon (the config rated good earlier in the A/B round). Compare A/B/D/E against this, not against memory."),
    ("D", "50ms horizon + 1.0 m/s clamp",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "100"},
     "A with a tighter clamp (1.0 m/s). For when A feels good overall but still 'jumps' on the FASTEST turns."),
    ("E", "no horizon + 25ms spread",
     {"SLAM_PRED_POSITION_HORIZON_MS": "0", "SLAM_CORRECTION_SPREAD_MS": "25"},
     "DIFFERENT lever (docs/80 investigation): halves the decay window of the correction spread, so a re-anchor during fast motion settles twice as fast. Risk: returning to the hard jitter/snap of T202. Pure freeze otherwise, isolating this single variable."),
    # ---- round 2 (docs/80): A won on latency; E was smoother but slower. F = A + E's spread.
    # G-J attack where the METERS of yaw drift actually live -- Basalt's backend landmark
    # collapse under yaw (p10 = 0 landmarks above 90 deg/s while the frontend still tracks ~2600
    # keypoints) -- via per-variant Basalt configs in ~/vr/basalt-variants/ (SLAM_CONFIG=<toml>
    # is passed straight through by jack-in-wayland.sh). All carry F's Monado-side env so only
    # the backend differs.
    ("F", "A + 25ms spread (less delay + smoother)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25"},
     "A's low delay plus E's smoothness. Only the spread differs from A. If it is >= A, spread 25 becomes the default."),
    ("G", "F + Basalt landmark recall",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/G.toml"},
     "BACKEND. recall_enable=true + vio_marg_lost_landmarks=false: today a landmark that leaves the frame in a turn is DELETED at the next marginalization (almost every frame), and recall only re-finds those still alive -- without turning the deletion off, recall has nothing to recover. Goal: landmarks survive the sweep and come back when the head returns."),
    ("H", "F + 2cm triangulation + 12 keyframes",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/H.toml"},
     "BACKEND. vio_min_triangulation_dist 0.05->0.02 m (a seated yaw has ~0 baseline: keyframes created during the turn add NO landmarks because the 5 cm threshold rejects them) + vio_max_kfs 7->12 (old keyframes are marginalized with their landmarks; a longer window keeps them alive longer). No recall."),
    ("I", "F + recall + triangulation (G+H)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/I.toml"},
     "BACKEND. G and H combined. Main backend candidate if G and H each help on their own."),
    ("J", "I + more permissive recall",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/J.toml"},
     "BACKEND. I + optical_flow_recall_max_patch_norms = Basalt's C++ defaults (our JSON uses values 4x stricter -- an internal Basalt discrepancy). If G/I recover few landmarks, the strict threshold may be rejecting valid recalls."),
    ("K", "F + recall + 12 keyframes (G + kfs, triangulation untouched)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/K.toml"},
     "BACKEND. Added after the soaks: H (2 cm triangulation) DESTABILIZES at rest (21 trips in 4 min vs 7 in 20 min for base) -- ill-conditioned depths. K keeps what works: recall (G, ~6x landmarks) + a 12-keyframe window so landmarks survive longer, with the 5 cm baseline intact. Requires patch 0014 (memory-bounded recall)."),
    # ---- round 3 (docs/80): the yaw recording replayed offline ranked J first by far (yaw
    # drift 2.62 -> 0.28 m) and then confirmed H1: shifting the camera stamps
    # -10 ms against the IMU cut I's yaw drift 0.96 -> 0.24 m (+10 ms: 4.2 m). Basalt patch 0017
    # exposes that shift as VIT_CAM_TIME_OFFSET_NS. JT = J + that shift.
    # The J sweep pinned the value: -5 and -10 ms tie (rot sum 0.53 vs J's 0.63), -15 is
    # already worse (0.70), -20 breaks (1.86). -7 ms = the middle of the plateau; the driver
    # arithmetic (wmr_camera.c stamps at start + 5.55 ms instead of start + exposure/2) puts
    # the true error at 1-5.5 ms depending on auto-exposure, so the midpoint is the safe bet.
    ("JT", "J + cameras -7 ms (IMU-camera offset)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/J.toml",
      "VIT_CAM_TIME_OFFSET_NS": "-7000000"},
     "TIMING. J + camera timestamps advanced 7 ms relative to the IMU (Basalt patch 0017). Offline on the yaw recording, the offset explains more yaw drift than any config: -5 and -10 ms tie (0.53 vs J's 0.63), -15 is already worse, +10 breaks (4.2 m). Cause: wmr_camera.c stamps the frame at start + half a period (5.55 ms) instead of start + half the exposure. If J is already good live, this should leave fast turns almost pinned. Compare against J."),
    # ---- round 4 (docs/80): with J worn the metres are gone (a few cm remain); what is left is
    # delay on fast motion + jitter/latency on slow motion. Three code reads named three levers,
    # each a Monado patch or env knob on top of J (Basalt config unchanged):
    ("JH", "J + 100 ms position horizon",
     {"SLAM_PRED_POSITION_HORIZON_MS": "100", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/J.toml"},
     "PREDICTION. With J the frontend takes ~46 ms (was 28) and the SLAM pose arrives 60-100 ms old; 0100's 50 ms horizon FREEZES the position for the rest of that time (t_tracker_slam.cpp:1672-1691), i.e. a fixed position lag on every anchor. 100 ms covers the real age; the 1.5 m/s clamp still protects against spikes. Kept only if it lowers delay on fast moves without 'drifting away' again. Result: refuted worn (more jitter, larger excursions)."),
    # 0102 measured the age with Aircar running: p50 115 ms, p90 151, max 359. 100 covers the
    # median only; 180 covers p90 with margin, the 1.5 m/s clamp bounds any single frame to
    # 27 cm of extrapolation.
    ("JH2", "J + 180 ms horizon (covers the measured p90)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "180", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml"},
     "PREDICTION, step 2 (on P2). Pose age measured with Aircar running is p50 115 ms / p90 151 / max 359: JH (100) only covers the median. 180 covers p90; the 1.5 m/s clamp bounds extrapolation to 27 cm per frame. Next step if JH helped but still froze on fast turns."),
    # (JA and JM moved from J.toml to P2.toml -- JP is the new base after its worn test, and
    # JH (horizon 100) was refuted worn: more jitter, larger excursions.)
    ("JA", "P2 + averaged correction (3 anchors)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
      "SLAM_CORRECTION_AVG_N": "3"},
     "SLOW JITTER. Patch 0103: the correction step (spread 25 ms) receives the AVERAGE of the last 3 anchor deltas instead of each raw delta. With the head nearly still each delta is mm-level VIO noise, and a 25 ms decay against anchors every 33 ms never settles: it reproduces the noise at 30 Hz (the 'jitter when looking slowly'). Averaging the input rejects that noise at the cost of ~1 anchor of lag in the correction only, not in real motion. Compare against J near the panel."),
    ("JM", "P2 + mid-exposure stamp (driver)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
      "WMR_CAM_TS_MID_EXPOSURE": "1"},
     "TIMING (driver fix, Monado patch 0101). wmr_camera.c stamped the frame at start + half a 90 Hz SLOT (5.55 ms) instead of start + half the EXPOSURE (0.03-4.5 ms, auto): the frame arrived 1-5.5 ms late relative to the IMU. This tracks the exposure frame by frame instead of JT's fixed -7 ms. Without VIT_CAM_TIME_OFFSET_NS. Offline, JT was no longer distinguishable from J in the headset; this is the right version to make the default if nothing gets worse."),
    # ---- round 5 (docs/80): the frontend cost has a config answer.
    # Offline, single stream, same recording: J = 45 ms p50 (matches the 46 measured worn),
    # J + optical_flow_detection_grid_size 30->40 ("P2") = 26.6 ms p50 / 33 p90 -- under the
    # base's 28 and under the 33 ms camera period -- with J's drift (rot sum 0.78 vs 0.70,
    # noise 0.1). Fewer, larger cells = ~1900 keypoints instead of ~3200; the recall keeps
    # doing its job. JP = that config alone; JX = JP + every Monado-side lever from round 4.
    ("JP", "J with grid 40 (frontend 27 ms instead of 45)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml"},
     "COST. Config P2 = J + optical_flow_detection_grid_size 30->40. Offline on the recording: same drift as J (0.78 vs 0.70, noise 0.1) with the frontend at 26.6 ms p50 / 33 p90 instead of 45 / 56 -- under base (28) and under the camera period (33). I.e. J without the 18 ms of extra delay. If it feels like J with less lag, it is Aircar's new config."),
    # (JX: horizon back to 50 after JH was refuted worn -- 100 ms = more jitter, larger excursions.)
    ("JX", "EVERYTHING TOGETHER: grid 40 + averaged correction + exposure stamp",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
      "SLAM_CORRECTION_AVG_N": "3", "WMR_CAM_TS_MID_EXPOSURE": "1"},
     "The full stack: P2 config (cheap J) + 50 ms horizon (JH/100 ms was refuted) + JA (3-anchor averaged correction) + JM (mid-exposure stamp). To try AFTER JP/JH/JA/JM separately: if one of them gets worse on its own, here they are mixed and it is unclear which one it was."),
    # ---- round 6: JA kept (jitter), JM kept (excursions), JH refuted.
    # 0020's age_in/age_out split the pose age: transport 11 ms flat, Basalt in->out p50 59 /
    # p90 170 / p99 265 with the frontend at 29/39/53 -- the 2+2 queue slots are the tail.
    # JQ = JX + both live queues at depth 1 (Basalt patch 0021, VIT_QUEUE_DEPTH).
    ("JQ", "JX + queue depth 1 (less pose age)",
     JQ_ENV,
     "LATERAL LATENCY. JX + VIT_QUEUE_DEPTH=1 (Basalt patch 0021): the two live queues (image->frontend and frontend->backend) go from 2 slots to 1. Measured on JM: transport 11 ms flat, but exposure->pose p50 59 / p90 170 / p99 265 ms with the frontend at 29/39/53 -- the rest is queueing (4 frames x 33 ms after a slow backend frame). With 1 slot the age is bounded to ~2 frames + processing; a frame is dropped only on a real jam (the IMU covers). Kept if it lowers lateral delay without adding jitter."),
    # ---- round 7 (docs/80): JQ is the profile; the residual is the rotation-onset displacement
    # (yaw/pitch first moves the view off the seat, then it settles). Offline the raw VIO does
    # not do it (yaw net 5 cm on the recording), so it is either (a) the prediction layer -- the
    # position freeze + SLAM_PRED_NECK_ARM_MM 150 model during the ~75 ms the anchor is stale (a
    # wrong arm length or centre shows up exactly as "moves then settles") -- or (b) the timing
    # shortfall the sweep left (optimum -5..-10 ms vs the ~2.5 ms the mid-exposure stamp recovers
    # -> start_ts lags exposure start). Cheap to separate: RQ = one recording under JQ's env with
    # R's protocol, replayed offline at 0 / -5 / -10 ms (scripts/euroc-shift.py +
    # replay-basalt-variants.py + replay-phase-slice.py). Raw trajectory clean while the
    # displacement was felt -> (a): JN0/JN100/JN200 A/B the neck arm against the profile's 150
    # (= JQ itself, the control). -5 ms still wins offline -> (b): JQT. All env-only on top of
    # JQ_ENV; the profile itself stays JQ.
    ("RQ", "RECORD yaw protocol (JQ + EuRoC 3 min)",
     {**JQ_ENV, "EUROC_RECORD": "1", "EUROC_RECORD_PATH": "/mnt/vrtmp/euroc-yaw2",
      "VIT_DUMP_CALIB": f"{HOME}/vr/logs/calib-g2-yaw2.json"},
     "RECORDING 2 (under JQ). Same protocol as R (follow the voice of yaw-protocol-voice.py: 30 s still, 10 fast left-right turns, 10 up-down, 10 tilts, 60 s free play), but recorded with the full JQ profile, so the camera stamps are already mid-exposure (0101) and the recording measures what the headset uses today. EuRoC in PNG to /mnt/vrtmp/euroc-yaw2_<date> + calibration dump. Then replay it offline at 0 / -5 / -10 ms with scripts/euroc-shift.py + replay-basalt-variants.py + replay-phase-slice.py, no headset: if the raw trajectory comes out clean while the displacement was felt, it is the prediction (try JN0/JN100/JN200); if -5 ms still wins, it is the timing (try JQT). ~1.4 GB/min on tmpfs (~5 GB per protocol; 14 GB if left running 10 min, docs/80): copy the dataset to ~/vr/logs/euroc/ BEFORE any reboot; close the game when finished. RESULT: recorded (6.8 GB, 0 trips, archived under /mnt/videos/euroc/); replay at 0 ms clean, at -5 ms diverged from t=0 (dataset not trimmed, under diagnosis) -- see docs/80."),
    ("JN0", "JQ + neck arm 0 mm",
     {**JQ_ENV, "SLAM_PRED_NECK_ARM_MM": "0"},
     "PREDICTION (hypothesis a). JQ with SLAM_PRED_NECK_ARM_MM=0: no neck model, the position stays plainly frozen during the ~75 ms the anchor is stale. The profile used 150 (= JQ, this round's control). If the 'moves off the seat, then settles' on turning disappears or clearly changes, the displacement comes from the neck model and not from VIO. RESULT: the displacement is much smaller, but with a little jitter when looking at the cockpit up close; 0 trips. Final order 0 ~= 100 < 150 < 200; the profile moved to 100."),
    ("JN100", "JQ + neck arm 100 mm",
     {**JQ_ENV, "SLAM_PRED_NECK_ARM_MM": "100"},
     "PREDICTION (hypothesis a). JQ with the neck arm at 100 mm instead of 150: the frozen eye sweeps a shorter arc when turning. Compare against JQ (150) and JN0 (0) on the same turn. RESULT: very similar to JN0; 0 trips. THIS IS THE PROFILE VALUE (SLAM_PRED_NECK_ARM_MM=100, reversible)."),
    ("JN200", "JQ + neck arm 200 mm",
     {**JQ_ENV, "SLAM_PRED_NECK_ARM_MM": "200"},
     "PREDICTION (hypothesis a). JQ with the neck arm at 200 mm: longer arc. If 200 feels WORSE than 150 and 100 better, the arc is overestimated; if the reverse, underestimated; if all three feel the same, the neck model is not the cause and hypothesis (b) = JQT remains. RESULT: drift clearly larger (worse than 150); 0 trips. Arc overestimated: hypothesis (a) confirmed, 150 was too much."),
    ("JQT", "JQ + cameras -5 ms on top of the mid-exposure stamp",
     {**JQ_ENV, "VIT_CAM_TIME_OFFSET_NS": "-5000000"},
     "TIMING (hypothesis b). JQ + VIT_CAM_TIME_OFFSET_NS=-5 ms (Basalt patch 0017) ON TOP of the mid-exposure stamp (0101): the offline sweep wanted -5..-10 ms and the mid-exposure stamp recovers only ~2.5, i.e. start_ts arrives late relative to the real exposure start. JT was a fixed -7 on J WITHOUT the mid-exposure stamp and was not felt; this is -5 in addition to the stamp. Only worth trying if the RQ recording replayed at -5 ms still beats 0. Compare against JQ. STATUS: not run -- the RQ replay at -5 ms diverged from t=0 (dataset not trimmed, under diagnosis); decision deferred to a clean replay (docs/80)."),
    # R = the ONE worn session the offline pipeline needs: F's config + EUROC_RECORD (PNG,
    # lossless -- JPG changes the features) + the live calibration dump. ~3 min following
    # yaw-protocol-voice.py's spoken script. Afterwards replay-basalt-variants.py replays the
    # recording through base x2 + G/H/I/J in ~15 min with no headset. EUROC_RECORD_PATH is a
    # PREFIX (the recorder appends _datetime, t_euroc_recorder.cpp:408-414).
    ("R", "RECORD yaw protocol (F + EuRoC 3 min)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "EUROC_RECORD": "1",
      "EUROC_RECORD_PATH": "/mnt/vrtmp/euroc-yaw", "VIT_DUMP_CALIB": f"{HOME}/vr/logs/calib-g2-yaw.json"},
     "THE RECORDING. Config F (A + spread 25) + EuRoC recording in PNG to /mnt/vrtmp/euroc-yaw_<date> + calibration dump. Put the headset on, start Aircar, and follow the voice of yaw-protocol-voice.py (30 s still, 10 fast left-right turns, 10 up-down, 10 tilts, 60 s free play). The recording is then replayed offline against all backend configs, no headset needed. ~1.4 GB/min on tmpfs (~5 GB per protocol; 14 GB if left running 10 min, docs/80); close the game when finished."),
]
for _tag, _label, _env, _note in AIRCAR_VARIANTS:
    ACTIONS[f"variant-1073390-{_tag}"] = {
        "label": f"Aircar · 6dof · variant {_tag}",
        "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": "1073390", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
                # 0102: every 512 predictions log the SLAM anchor age p50/p90/max -- the
                # felt delay as a number, for every variant from here on.
                "SLAM_POSE_AGE_LOG": "512",
                "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": f"Aircar 6dof variant {_tag}: {_label}",
                **_env},
        "demo": {"title": f"Aircar variant {_tag} ({_label})", "tracking": "6dof",
                 "status": "testing", "note": _note},
    }


# Public-tree slimming (2026-11): several helpers these buttons drive (voice-guide.py,
# playlist-runner.py, the Basalt variant configs other than P2, ...) are no longer shipped in
# this repo. A button whose script / SLAM config is missing on this machine is dropped here
# instead of showing up and failing when clicked. Where those files still exist (e.g. a lab
# box with its own ~/vr copies) every button stays exactly as before.
_TARGET_RE = re.compile(r"(?:%s)/[^\s;'\"]+\.(?:py|sh|toml)" % re.escape(HOME))


def _action_targets(action):
    targets = []
    for part in action["cmd"]:
        targets += _TARGET_RE.findall(part)
        if part.endswith((".py", ".sh")) and not part.startswith("-") and " " not in part:
            targets.append(part if os.path.isabs(part) else os.path.join(action["cwd"], part))
    cfg = action.get("env", {}).get("SLAM_CONFIG")
    if cfg:
        targets.append(cfg)
    return targets


for _id in [k for k, v in ACTIONS.items() if not all(os.path.exists(t) for t in _action_targets(v))]:
    del ACTIONS[_id]


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
    if not os.path.exists(PLAYLIST_RUNNER):
        return False, "playlist-runner.py is not installed on this machine"
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
# "headset on the desk" delay: how long the presence-alert helper waits after a
# doff commits before speaking, per active user -- same live-file pattern as
# BRIGHTNESS_FILE/set_brightness_gain, read fresh by the shell script on each doff rather
# than cached, so switching the active user here takes effect on the very next doff with
# no restart needed (unlike PRESENCE_CONF_FILE below, which needs a jack-in down/up).
RESTING_ALERT_DELAY_FILE = f"{HOME}/vr/logs/presence-resting-alert-delay-ms"
RESTING_ALERT_DELAY_MAX_MS = 600000  # 10 min -- the top preset offered in the UI

# Auto-standby opt-in + timeout (2026-09-04) -- read by rig_telemetry.presence_settings(),
# written here. Same per-box conf file jack-in-wayland.sh sources at launch
# (WMR_USER_PRESENCE / WMR_USER_PRESENCE_SCREENOFF_MS), so a change here only takes effect
# on the next 'jack-in down' + 'up', never live -- Monado caches the env var on first read.
PRESENCE_CONF_FILE = f"{HOME}/vr/presence.conf"
PRESENCE_SCREENOFF_MAX_MS = 1800000  # 30 min ceiling

# What CANNOT be changed on this headset -- read-only reference for the operator, so the
# distinction between "fixed" and "adjustable" is explicit.
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
# user -- default "es" for backward compatibility with existing installs, so introducing
# per-user i18n does not change what current operators see.
DEFAULT_USERS = {
    "active": "default",
    "users": {
        "default": {"height_m": 1.70, "dof": "3dof", "brightness": 1.0,
                    "mapping": "Xbox pad; A recentre", "notes": "", "lang": "es",
                    "resting_alert_delay_ms": 0, "voice_gender": "male",
                    "audio_guide_enabled": True},
    },
}

SUPPORTED_LANGS = ("en", "es", "ru")


def load_users():
    try:
        d = json.load(open(USER_PROFILES_FILE))
        assert isinstance(d.get("users"), dict) and d.get("active")
        # Migration: profiles saved before "lang"/"voice_gender" existed default to "es"/
        # "male", same reasoning as DEFAULT_USERS above -- don't silently change an
        # existing operator's language or alert voice. "male" matches what every
        # profile's single-voice-per-language TTS model actually was before this field
        # existed (es_ES-davefx and en_US-lessac are male voices; only ru_RU-irina,
        # female, was the odd one out -- profiles already using ru get "male" here too,
        # a real behavior change for them alone, but there is no way to distinguish "was
        # depending on irina's voice" from "never touched voice at all" after the fact;
        # set voice_gender explicitly if that matters for a given profile).
        for u in d["users"].values():
            u.setdefault("lang", "es")
            u.setdefault("resting_alert_delay_ms", 0)
            u.setdefault("voice_gender", "male")
            u.setdefault("audio_guide_enabled", True)
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


def set_resting_alert_delay_ms(delay_ms):
    """Write the per-user "casco en la mesa" delay the presence-alert helper reads fresh on
    each doff commit. Same live-file pattern as set_brightness_gain/BRIGHTNESS_FILE --
    unlike PRESENCE_CONF_FILE (PRESENCE_ENABLE/PRESENCE_SCREENOFF_MS, jack-in-wide, needs
    a relaunch to apply), this one is picked up by the shell script's next doff event with
    no restart, since the script re-reads the file at the moment it needs the value."""
    try:
        d = max(0, min(RESTING_ALERT_DELAY_MAX_MS, int(delay_ms)))
    except (TypeError, ValueError):
        return False, "resting_alert_delay_ms must be an integer"
    os.makedirs(f"{HOME}/vr/logs", exist_ok=True)
    with open(RESTING_ALERT_DELAY_FILE, "w") as f:
        f.write(f"{d}\n")
    return True, f"aviso 'en la mesa' -> {d} ms"


def save_presence_settings(enable_raw, screenoff_ms_raw):
    """Rewrite ~/vr/presence.conf from the dashboard's /api/presence/save. Full overwrite
    is fine -- these are the only two keys this file holds. Validates screenoff_ms is a
    non-negative integer, clamped to PRESENCE_SCREENOFF_MAX_MS (30 min); anything past
    that (or non-numeric) is rejected rather than silently clamped-and-accepted, so a typo
    doesn't quietly ship a different number than the operator typed."""
    try:
        screenoff_ms = int(screenoff_ms_raw)
    except (TypeError, ValueError):
        return False, "screenoff_ms must be an integer"
    if screenoff_ms < 0:
        return False, "screenoff_ms must not be negative"
    if screenoff_ms > PRESENCE_SCREENOFF_MAX_MS:
        return False, f"screenoff_ms must be <= {PRESENCE_SCREENOFF_MAX_MS} (30 min)"
    enable = str(enable_raw) == "1"
    os.makedirs(f"{HOME}/vr", exist_ok=True)
    tmp = PRESENCE_CONF_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(
            "# ~/vr/presence.conf -- auto-standby opt-in, written by status-dashboard.py's\n"
            "# /api/presence/save (the dashboard's \"Auto-standby\" card). Same KEY=VALUE format\n"
            "# as power.conf/vr-profile.conf. Read by jack-in-wayland.sh at launch AND by\n"
            "# rig_telemetry.presence_settings() for display -- a change here only takes effect\n"
            "# on the NEXT 'jack-in down' + 'up', never live (Monado caches the env var on its\n"
            "# first read). Ships PRESENCE_ENABLE=0 by default: only the blank direction\n"
            "# is validated; the RESTORE/re-donning direction is not, so don't flip this\n"
            "# on for a real session without knowing that.\n"
            f"PRESENCE_ENABLE={1 if enable else 0}\n"
            f"PRESENCE_SCREENOFF_MS={screenoff_ms}\n"
        )
    os.replace(tmp, PRESENCE_CONF_FILE)
    return True, "guardado -- se aplica en el próximo 'jack-in down/up' (no en caliente)"


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


def _safe_telemetry(fn):
    """Extra defensive wrapper for the newer, not-yet-fully-confirmed rig_telemetry
    readers (camera_expgain/perf_metrics/camera_calibration/hmd_status, 2026-09-05):
    those functions already catch their own parse errors and return None, but this
    is a second layer so a surprise bug in one of them (a shape none of us has seen
    live yet) degrades that one card to "no data yet" instead of ever taking down
    build_status() -- and therefore the whole /api/status endpoint -- for everyone."""
    try:
        return fn()
    except Exception:
        return None


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
        "controllers": rig_telemetry.controller_status(),
        "gpu": driver_info(),
        "gpu_power": gpu_power(),
        "power_mode": rig_telemetry.power_mode(),
        "hmd_temperature": rig_telemetry.hmd_temperature(),
        # Driver-exposed data wired in 2026-09-05 for the Vitals section + Tracking
        # cameras / HMD status cards -- all from files a parallel task (different
        # repo, no access here) is adding alongside the one that already existed
        # (camera-expgain.json). Every one of these degrades to None/"no data yet"
        # rather than raising -- see rig_telemetry's own docstrings and _safe_telemetry
        # above for why the extra wrapper layer is worth it here specifically.
        "camera_expgain": _safe_telemetry(rig_telemetry.camera_expgain),
        "perf_metrics": _safe_telemetry(rig_telemetry.perf_metrics),
        "camera_calibration": _safe_telemetry(rig_telemetry.camera_calibration),
        "hmd_status": _safe_telemetry(rig_telemetry.hmd_status),
        "cpu_live": rig_telemetry.cpu_telemetry(),
        "presence": rig_telemetry.presence_settings(),
        "audio": audio_status(),
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
<html><head><meta charset="utf-8"><title>G2 lab status</title>
<style>
  /* ---- Night Panel: this dashboard's own visual system (2026-08-27) -------------------
     Grounded in the rig's actual constraints, not a generic dark-dashboard skin:
     the test room is kept dim on purpose (bright light degrades the G2's own
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
  /* Same specificity gotcha the .fault-dot[hidden] rule below already documents: this
     class sets its own `display:inline-flex`, a normal author rule, which always wins
     over the browser's normal UA `[hidden]{display:none}` regardless of selector
     specificity (author origin beats user-agent origin). Needed for #dot-audio
     (audio UI is hidden -- see AUDIO_UI_HIDDEN below). */
  .status-dot[hidden] { display:none; }

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
  .demo .note-more { margin-top:4px; }
  .demo .note-more summary { cursor:pointer; color:var(--ink-inactive); font-size:11px; user-select:none; }
  .demo .note-more summary:hover { color:var(--ink-dim); }
  .demo .note-more[open] summary { margin-bottom:4px; }
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
  /* The bare `hidden` attribute (instrument-bank tab dots) needs a same-origin rule at
     HIGHER specificity than `.fault-dot` above to actually win -- otherwise this class's
     own `display:inline-block` outranks the browser's default `[hidden]{display:none}`
     UA-stylesheet rule (equal specificity, author stylesheet always wins), and a
     "hidden" fault-dot renders anyway. Caught live via headless-Chrome screenshot,
     2026-09-05 -- exactly the class of bug this file's own verification method exists
     to catch before it ships. */
  .fault-dot[hidden] { display:none; }
  .fault-dot.ok-hidden { background:transparent; }
  .fault-dot.bad { background:var(--bad); box-shadow:0 0 6px var(--bad-glow); }
  .fault-dot.warn { background:var(--warn); }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:10px; }
  .grid .card h2 { font-size:11px; letter-spacing:.07em; color:var(--ink-dim); }
  .grid .row { font-family:var(--font-mono); font-size:12px; }
  @media (max-width:720px) { .grid { grid-template-columns:1fr; } }

  /* ---- Profile strip (2026-09-05): the operator/profile row, the first visible thing
     below #attn -- fast/clean user switching before anything else on the page. The
     per-user height/dof/mapping/notes fields, plus a read-only "fixed spec plate" of
     hardware facts (not user data), collapse behind the same access-panel disclosure
     used everywhere else on the page for "read rarely" content. */
  .profile-strip { display:flex; flex-wrap:wrap; align-items:center; gap:10px 14px;
                    padding:10px 14px; background:var(--surface); border:1px solid var(--line);
                    border-radius:var(--radius); margin-bottom:8px; }
  .profile-strip label { font-family:var(--font-display); text-transform:uppercase; letter-spacing:.05em;
                          font-size:10.5px; color:var(--ink-dim); }
  .profile-strip select, .profile-strip input:not([type=range]) {
    font-family:var(--font-body); background:var(--surface-2); color:var(--ink); border:1px solid var(--line);
    border-radius:6px; padding:5px 8px; font-size:13px; }
  .profile-strip input[type=range] { accent-color:var(--accent); }
  .profile-strip button { background:var(--surface-2); color:var(--ink); border:1px solid var(--line);
                           border-radius:6px; padding:6px 12px; font-size:13px; cursor:pointer; font-family:var(--font-body); }
  .profile-strip button:hover { border-color:var(--accent); }
  .fixed-plate { margin-top:12px; }
  .fixed-plate .row span:first-child { font-family:var(--font-display); text-transform:uppercase;
                                        letter-spacing:.04em; font-size:11px; color:var(--ink-dim); }
  .fixed-plate .row span:last-child { font-family:var(--font-mono); font-size:12px; color:var(--ink); }

  /* ---- Instrument bank (2026-09-05): HEADSET/GPU/CPU subsystem-detail tabs, replacing
     the old single "Diagnostics" access-panel so GPU and CPU can be tuned one at a time.
     Breaker-plate fascia: raised --surface-2 plates in a recessed --bg track, a single
     accent bar as the ONLY selection signal (--accent stays interactive-only everywhere
     else in this bank -- never repurposed as a status color). */
  .instrument-bank { display:flex; gap:3px; background:var(--bg); border:1px solid var(--line);
                      border-bottom:none; border-radius:var(--radius) var(--radius) 0 0; padding:6px 6px 0; margin-top:18px; }
  .tab-plate { position:relative; flex:1 1 0; background:var(--surface-2); color:var(--ink-dim);
               border:1px solid var(--line); border-bottom:none; border-radius:6px 6px 0 0;
               box-shadow: inset 0 -3px 5px rgba(0,0,0,.3);
               font-family:var(--font-display); text-transform:uppercase; letter-spacing:.05em;
               font-size:13px; padding:10px 30px 10px 14px; cursor:pointer; text-align:center; }
  .tab-plate:hover { color:var(--ink); }
  .tab-plate[aria-selected="true"] { color:var(--ink); font-weight:700; background:var(--surface);
                                      border-bottom:3px solid var(--accent); box-shadow:none; }
  .tab-plate .fault-dot { position:absolute; top:8px; right:10px; }
  @media (max-width:720px) {
    .instrument-bank { flex-direction:column; padding:6px; }
    .tab-plate { border-radius:6px; border-bottom:1px solid var(--line); text-align:left; }
    .tab-plate[aria-selected="true"] { border-bottom:3px solid var(--accent); }
  }
  .nameplate-strip { display:flex; flex-wrap:wrap; gap:6px 22px; align-items:center;
                      background:var(--surface); border:1px solid var(--line); border-top:none;
                      padding:8px 14px; font-family:var(--font-mono); font-size:11.5px; color:var(--ink-dim); }
  .nameplate-strip b { font-family:var(--font-display); text-transform:uppercase; letter-spacing:.05em;
                        font-size:10px; font-weight:700; color:var(--ink-inactive); margin-right:5px; }
  .nameplate-strip button { margin-left:6px; padding:2px 8px; font-size:11.5px; font-family:var(--font-body);
                             background:var(--surface-2); color:var(--ink); border:1px solid var(--line);
                             border-radius:5px; cursor:pointer; }
  .nameplate-strip button:hover { border-color:var(--accent); }
  .tab-panel-body { background:var(--surface); border:1px solid var(--line); border-top:none;
                     border-radius:0 0 var(--radius) var(--radius); padding:14px 16px; margin-bottom:14px; }

  .preview-img { max-width:100%; border-radius:6px; background:var(--bg); display:none; }
  #screen-note { font-size:12px; }
  #screen-empty { font-size:13px; padding:22px 0; text-align:center; }
  #pl-msg { font-size:12px; margin-top:6px; }

  .camera-grid { display:grid; grid-template-columns: 1fr 1fr; gap:8px; margin-top:8px; }
  @media (max-width:480px) { .camera-grid { grid-template-columns:1fr; } }
  .camera-thumb { position:relative; aspect-ratio:4/3; background:var(--bg); border-radius:4px; overflow:hidden; }
  .camera-thumb img { width:100%; aspect-ratio:4/3; border-radius:4px; background:var(--bg); display:block; object-fit:cover; }
  .camera-thumb .camera-label { position:absolute; top:2px; left:4px; font-family:var(--font-mono);
    font-size:10px; color:#fff; text-shadow:0 0 3px #000, 0 0 3px #000; }

  /* ---- Vitals (2026-09-05): a technician's TREND view of the live session -- FPS,
     HMD temp, camera dropped-frame rate -- explicitly NOT a log/table
     (a clean flow, not a log). Hand-rolled <canvas> sparklines,
     vanilla JS, no charting library (this dashboard has no guaranteed internet -- same
     reasoning already used elsewhere in this file for zero web fonts). One steel-blue
     --accent line, dim gridlines, mono labels -- consistent with every other numeric
     readout on this page. */
  .vitals-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:8px; }
  @media (max-width:720px) { .vitals-grid { grid-template-columns:1fr; } }
  .vital-label { font-family:var(--font-display); text-transform:uppercase; letter-spacing:.05em;
                 font-size:11px; color:var(--ink-dim); margin-bottom:4px; }
  .vital canvas { width:100%; height:56px; display:block; background:var(--bg); border-radius:4px; }
  .vital-value { font-family:var(--font-mono); font-size:14px; color:var(--ink); margin-top:5px; }

  /* ---- Hairline grid (2026-09-05): the "seamless data grid" technique from
     a hairline-grid admin stylesheet (.live/.usage classes) -- the container paints --line
     as its own background, cells sit with a 1px gap and their own solid background, so
     a crisp hairline appears between cells with no doubled borders. Palette/fonts stay
     Night Panel's own -- only the structural technique was borrowed. */
  .hgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(84px,1fr)); gap:1px;
           background:var(--line); border:1px solid var(--line); border-radius:var(--radius);
           overflow:hidden; margin-top:6px; }
  .hgrid .cell { background:var(--surface-2); padding:7px 9px; }
  .hgrid .cell .k { font-family:var(--font-display); font-size:9px; text-transform:uppercase;
                    letter-spacing:.14em; color:var(--ink-dim); }
  .hgrid .cell .v { font-family:var(--font-mono); font-size:13px; color:var(--ink); margin-top:3px; }
</style></head>
<body>
<div id="attn"></div>
<div class="profile-strip" id="profile-strip-body">loading...</div>
<details class="access-panel" id="profile-edit-panel">
  <summary><span data-i18n="cc_edit_profile">edit profile</span></summary>
  <div id="profile-edit-body">loading...</div>
</details>
<div class="tray-header">
  <h1 class="wordmark"><span data-i18n="h1">VR lab</span><small data-i18n="h1_sub">HP Reverb G2 lab status</small></h1>
  <div class="status-strip" id="status-dots">
    <span class="status-dot" id="dot-session"><span data-i18n="dot_session">SESSION</span></span>
    <!-- Audio UI hidden -- audio_status()/the
         /api/audio-outputs endpoint/hmd-audio.sh are all left working underneath,
         only this dot is not rendered. See AUDIO_UI note near renderAudioDevices(). -->
    <span class="status-dot" id="dot-audio" hidden><span data-i18n="dot_audio">AUDIO</span></span>
    <span class="status-dot" id="dot-hw"><span data-i18n="dot_hw">HARDWARE</span></span>
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
  <div class="stack">
    <div class="card">
      <h2><span data-i18n="preview_h2">Headset preview</span><span class="sub" id="screen-note"></span></h2>
      <img id="screen" class="preview-img" alt="no preview">
      <div id="screen-empty" class="dim" data-i18n="preview_empty">no window to preview (start a game/player)</div>
    </div>
    <!-- Tracking cameras: MOVED here from inside the tabbed #panel-headset (2026-09-05,
         "vista previa dejala siempre, al igual que las vistas en miniatura de las
         camaras") -- both this and the Headset preview card above must stay visible
         regardless of which Headset/GPU/CPU instrument-bank tab is selected, so this
         whole card now lives in the untabbed operator-tray tier instead. -->
    <div class="card" id="camera-card">
      <h2>Tracking cameras</h2>
      <div id="camera-imgs" class="camera-grid"></div>
      <div id="camera-note" class="dim" style="font-size:12px"></div>
      <div id="camera-expgain" class="dim" style="font-size:12px;margin-top:6px"></div>
      <div class="row" style="margin-top:6px">
        <span>brillo (vista web)</span>
        <span><input type="range" id="camera-brightness" min="0.5" max="3" step="0.1" value="1" style="vertical-align:middle"> <span id="camera-brightness-val" class="dim">1.0x</span></span>
      </div>
    </div>
  </div>
  <div class="stack">
    <div class="card session-card">
      <h2 data-i18n="session_h2">Session</h2>
      <div id="session-rows">loading...</div>
    </div>
    <!-- Audio outputs card: HIDDEN -- audio_status(),
         /api/audio-outputs and hmd-audio.sh integration are all left working underneath
         (may be needed again later), only this card is not rendered. tick() still writes
         into #audio-devices every cycle (renderAudioDevices/audioCls etc) -- harmless
         against a hidden card, and simpler than scattering conditionals through tick(). -->
    <div class="card" id="audio-card" hidden>
      <h2 data-i18n="audio_h2">Audio outputs -- check one, another, or several (duplicate); per-device volume</h2>
      <div id="audio-devices">loading audio devices...</div>
    </div>
  </div>
</div>
<div class="card" style="margin-bottom:14px">
  <h2 data-i18n="vitals_h2">Vitals -- live session trend (technician view, not a log)</h2>
  <div class="vitals-grid">
    <div class="vital">
      <div class="vital-label">FPS</div>
      <canvas id="vital-fps"></canvas>
      <div class="vital-value" id="vital-fps-val">no data yet</div>
    </div>
    <div class="vital">
      <div class="vital-label">HMD temp (est.)</div>
      <canvas id="vital-temp"></canvas>
      <div class="vital-value" id="vital-temp-val">no data yet</div>
    </div>
    <div class="vital">
      <div class="vital-label">Camera dropped-frame rate</div>
      <canvas id="vital-drop"></canvas>
      <div class="vital-value" id="vital-drop-val">no data yet</div>
    </div>
  </div>
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
      <!-- Hidden with the rest of the audio UI -- not deleted, the string stays
           in I18N below in case audio surfaces again later. -->
      <li data-i18n="guide_1" hidden><b>Audio</b>: the "audio" toggle above must read <b>headset</b> before handing over (130%). If sound vanishes mid-session the stream got orphaned by a USB re-enumeration -- click "Audio -&gt; headset" again, it re-routes live.</li>
      <li data-i18n="guide_2"><b>Window focus</b>: the game's desktop window must be <b>focused</b> or Wine drops gamepad + audio (only head tracking keeps working). If a guest says "no sound / pad dead", click the game window first, don't debug.</li>
      <li data-i18n="guide_3"><b>Fast head turns (6dof only)</b>: yaw is the weak axis -- a quick side-to-side look drifts the seat. Tell the guest <b>"press A"</b> the moment you see it, don't wait for them to notice.</li>
      <li data-i18n="guide_4"><b>Light</b>: no automated low-light warning exists. Dim room = tracking runaways in the first ~75 s. Check the room before each 6dof session.</li>
      <li data-i18n="guide_5"><b>Between titles</b>: "Stop all games" then wait for the session card to read IDLE before the next demo button. Never launch a second title on top of a live one.</li>
    </ul>
  </div>
</div>
<div class="instrument-bank" role="tablist" aria-label="Subsystem detail">
  <button class="tab-plate" role="tab" id="tab-headset" aria-selected="true"  aria-controls="panel-headset" tabindex="0">
    HEADSET <span class="fault-dot bad" id="dot-headset" hidden></span>
  </button>
  <button class="tab-plate" role="tab" id="tab-gpu" aria-selected="false" aria-controls="panel-gpu" tabindex="-1">
    GPU <span class="fault-dot bad" id="dot-gpu" hidden></span>
  </button>
  <button class="tab-plate" role="tab" id="tab-cpu" aria-selected="false" aria-controls="panel-cpu" tabindex="-1">
    CPU <span class="fault-dot warn" id="dot-cpu" hidden></span>
  </button>
</div>
<div class="nameplate-strip" id="nameplate-strip">loading...</div>
<div id="panel-headset" class="tab-panel-body" role="tabpanel" aria-labelledby="tab-headset">
  <div class="grid" id="grid-headset">loading...</div>
  <!-- Persistent (not rebuilt by the #grid-headset innerHTML replace every tick, so an
       in-progress edit here survives a refresh) -- 2026-09-04, see renderPresenceSettings(). -->
  <div class="grid" style="margin-top:12px">
    <div class="card" id="presence-card">
      <h2>Auto-standby (presence)</h2>
      <div class="row"><span>enabled</span><span><input type="checkbox" id="presence-enable-cb"></span></div>
      <div class="row"><span>screen-off timeout</span><span><input type="number" id="presence-screenoff-min" min="0" max="30" step="0.5" style="width:60px"> min</span></div>
      <div class="row"><span></span><span><button onclick="savePresence()">Guardar</button></span></div>
      <div class="dim" id="presence-msg" style="font-size:12px"></div>
      <div class="dim" style="font-size:12px;margin-top:4px">se aplica en el próximo 'jack-in down/up' -- nunca en caliente, Monado cachea la variable al arrancar (takes effect on the next jack-in down/up, never live)</div>
    </div>
  </div>
  <!-- Camera calibration: static, one-time per-camera intrinsics/pose reference data --
       "does this camera look miscalibrated" for a technician, not something to watch
       live, so this is access-panel (dense/collapsed), not
       the operator-tray tier the live camera preview above was promoted to. -->
  <details class="access-panel" id="camera-calibration-panel">
    <summary><span>Camera calibration (raw reference)</span></summary>
    <pre id="camera-calibration-body">no data yet</pre>
  </details>
</div>
<div id="panel-gpu" class="tab-panel-body" role="tabpanel" aria-labelledby="tab-gpu" hidden>
  <div class="grid" id="grid-gpu">loading...</div>
</div>
<div id="panel-cpu" class="tab-panel-body" role="tabpanel" aria-labelledby="tab-cpu" hidden>
  <div class="grid" id="grid-cpu">loading...</div>
</div>
<div class="ts" id="ts"></div>
<script>
// ---- i18n -------------------------------------------------------------------
// Pattern: an I18N object keyed by
// lang, data-i18n attributes on static elements, a t() helper for JS-built
// strings, localStorage for per-browser persistence, no page reload on switch.
// Scope, deliberately: this covers static chrome (headers, guide, command-centre
// and playlist labels) -- the heavily dynamic per-tick telemetry text in tick()
// and renderAudioDevices() is NOT localized yet, that's a separate future pass.
const I18N = {
  en: {
    h1: "VR lab",
    h1_sub: "HP Reverb G2 lab status",
    dot_session: "SESSION", dot_audio: "AUDIO", dot_hw: "HARDWARE",
    session_h2: "Session", access_h2: "Diagnostics",
    ag_system: "System", ag_voice: "Voice cues",
    demos_approved_label: "Approved for guests", demos_other_label: "In testing -- do not offer to guests",
    preview_h2: "Headset preview",
    preview_empty: "no window to preview (start a game/player)",
    audio_h2: "Audio outputs -- check one, another, or several (duplicate); per-device volume",
    vitals_h2: "Vitals -- live session trend (technician view, not a log)",
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
    cc_resting_delay: "\\"resting\\" alert delay",
    cc_voice_gender: "alert voice", cc_audio_guide: "audio guide",
    cc_save_btn: "Save user", cc_fixed: "Fixed (not changeable on this headset)", cc_lang: "language",
    cc_edit_profile: "edit profile",
    pl_name_label: "Name:", pl_name_default: "Demo round",
    pl_auto_btn: "▶ Auto round (all, recommended)", pl_custom_btn: "▶ Fire selection",
    pl_hint: "\\"Next title\\" voice cue + clean teardown between each. Pausable / stoppable once launched.",
    pl_pause: "⏸ Pause (won't start the next one)", pl_resume: "▶ Resume",
    pl_skip: "⏭ Skip", pl_stop: "⏹ Stop and clear the round",
  },
  es: {
    h1: "VR lab",
    h1_sub: "estado del lab HP Reverb G2",
    dot_session: "SESIÓN", dot_audio: "AUDIO", dot_hw: "HARDWARE",
    session_h2: "Sesión", access_h2: "Diagnóstico",
    ag_system: "Sistema", ag_voice: "Voz",
    demos_approved_label: "Aprobado para invitados", demos_other_label: "En prueba -- no ofrecer a invitados",
    preview_h2: "Vista previa del casco",
    preview_empty: "no hay ventana para previsualizar (arrancá un juego/player)",
    audio_h2: "Salidas de audio -- marcá una, otra, o varias (duplicado); volumen por dispositivo",
    vitals_h2: "Vitales -- tendencia en vivo de la sesión (vista técnica, no un log)",
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
    cc_resting_delay: "demora aviso \\"en la mesa\\"",
    cc_voice_gender: "voz del aviso", cc_audio_guide: "guía de audio",
    cc_save_btn: "Guardar usuario", cc_fixed: "Fijo (no modificable en este casco)", cc_lang: "idioma",
    cc_edit_profile: "editar perfil",
    pl_name_label: "Nombre:", pl_name_default: "Ronda demo",
    pl_auto_btn: "▶ Ronda automática (todo, recomendada)", pl_custom_btn: "▶ Disparar selección",
    pl_hint: "Voz \\"próximo título\\" + teardown limpio entre cada uno. Pausable / detenible una vez lanzada.",
    pl_pause: "⏸ Pausa (no arranca el próximo)", pl_resume: "▶ Reanudar",
    pl_skip: "⏭ Saltear", pl_stop: "⏹ Detener y limpiar la ronda",
  },
  ru: {
    h1: "VR lab",
    h1_sub: "статус лаборатории HP Reverb G2",
    dot_session: "СЕССИЯ", dot_audio: "АУДИО", dot_hw: "ЖЕЛЕЗО",
    session_h2: "Сессия", access_h2: "Диагностика",
    ag_system: "Система", ag_voice: "Голосовые подсказки",
    demos_approved_label: "Одобрено для гостей", demos_other_label: "На тестировании -- не предлагать гостям",
    preview_h2: "Предпросмотр с гарнитуры",
    preview_empty: "нет окна для предпросмотра (запустите игру/плеер)",
    audio_h2: "Аудиовыходы -- отметьте один, другой или несколько (дублирование); громкость по устройству",
    vitals_h2: "Показатели -- тренд сессии в реальном времени (вид для техника, не лог)",
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
    cc_resting_delay: "задержка \\"на столе\\"",
    cc_voice_gender: "голос оповещений", cc_audio_guide: "аудио-гид",
    cc_save_btn: "Сохранить пользователя", cc_fixed: "Фиксировано (нельзя изменить на этой гарнитуре)", cc_lang: "язык",
    cc_edit_profile: "редактировать профиль",
    pl_name_label: "Название:", pl_name_default: "Демо-раунд",
    pl_auto_btn: "▶ Автораунд (всё, рекомендуется)", pl_custom_btn: "▶ Запустить выбранное",
    pl_hint: "Голосовое объявление «следующий тайтл» + чистое завершение между показами. Можно приостановить / остановить после запуска.",
    pl_pause: "⏸ Пауза (следующий не запустится)", pl_resume: "▶ Продолжить",
    pl_skip: "⏭ Пропустить", pl_stop: "⏹ Остановить и очистить раунд",
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
  try { localStorage.setItem('g2-dashboard-lang', lang); } catch(e) {}
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
// Audio UI hidden: these 3 buttons were already
// excluded from loadActions()'s generic render (see the `continue` below) before this
// pass, so no change was needed here to hide them -- kept as its own named set (not
// deleted) since the ACTIONS/audio_status()/hmd-audio.sh backend plumbing underneath
// is intentionally left working in case audio surfaces again later.
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
      // Anything id-prefixed "voz-" (the spoken cues) groups separately
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
function updateCompositorToggle(running) {
  const btn = document.getElementById('compositor-toggle');
  btn.disabled = false;
  btn.className = running ? 'on' : 'off';
  btn.textContent = running ? '● compositor ON -- click to stop' : '○ compositor off -- click to start';
  btn.onclick = () => runAction(running ? 'compositor-down' : 'compositor-up', btn);
}
let audioDragging = false;   // a per-device volume slider is being dragged right now
document.addEventListener('mouseup', () => audioDragging = false);
// Read by refreshCameras() (its own independent poll loop, like refreshScreen()) -- set by
// tick() every /api/status refresh so the camera card doesn't need its own status fetch.
let lastSessionActive = false;
let lastTrackingMode = null; // '3dof' | '6dof' | 'ctrl' | null (no session)

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
      // These notes are internal engineering history (often 100-300+ words per
      // title), too much to dump on the card in full. Show a short first-sentence preview
      // always, hide the rest behind a
      // native <details> disclosure (zero extra JS, keyboard-operable) instead of dropping it.
      const firstSentence = (d.note.match(/^.*?[.!?](?=\\s|$)/) || [d.note.slice(0, 110)])[0];
      const rest = d.note.slice(firstSentence.length).trim();
      info.innerHTML = `<span class="st ${d.status}">${d.status.toUpperCase()}</span>${firstSentence}`
        + (rest ? `<details class="note-more"><summary>+ detalle</summary>${rest}</details>` : '');
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
// Tracking-camera live preview (2026-09-05): up to CAMERA_COUNT thumbnails, one per WMR tracking
// camera (see wmr_camera.c's throttled snapshot dump + status-dashboard.py's
// capture_camera_jpeg()). Its own independent poll loop, same cache-busting + onload/onerror-swap
// technique as refreshScreen() above so a slow/missing frame never flashes a broken-image icon.
// Gated on lastTrackingMode/lastSessionActive (set by tick() from /api/status, not re-fetched
// here): 3dof and "no session" show an explanatory note instead of empty <img> tags, since the
// WMR tracking cameras are only powered on for 6dof/ctrl tracking (jack-in-wayland.sh's
// WMR_SLAM/WMR_CAMERAS env -- 3dof sets neither).
const CAMERA_COUNT = 4; // HP Reverb G2: 4 tracking cameras -- keep in sync with CAMERA_COUNT in status-dashboard.py
let cameraImgsBuilt = false;
// Client-side-only brightness slider (2026-09-05): a CSS filter() multiplier layered on top of
// the server-side autocontrast already baked into capture_camera_jpeg() -- no server round trip,
// instant feedback while dragging. Persisted per-browser in localStorage (this is a shared
// page with no per-user account system for camera preview prefs, unlike the headset brightness
// gain which IS saved per active user profile via /api/brightness -- separate concern: one
// setting for the web view, one for the headset).
let cameraBrightness = 1;
try {
  const _savedCamBrightness = localStorage.getItem("camBrightness");
  if (_savedCamBrightness) cameraBrightness = parseFloat(_savedCamBrightness);
} catch (e) {}
const camBrightnessSlider = document.getElementById("camera-brightness");
const camBrightnessLabel = document.getElementById("camera-brightness-val");
function applyCameraBrightness() {
  camBrightnessLabel.textContent = cameraBrightness.toFixed(1) + "x";
  for (let i = 0; i < CAMERA_COUNT; i++) {
    const img = document.getElementById("cam-img-" + i);
    if (img) img.style.filter = "brightness(" + cameraBrightness + ")";
  }
}
camBrightnessSlider.value = cameraBrightness;
applyCameraBrightness();
camBrightnessSlider.addEventListener("input", () => {
  cameraBrightness = parseFloat(camBrightnessSlider.value);
  try { localStorage.setItem("camBrightness", cameraBrightness); } catch (e) {}
  applyCameraBrightness();
});
function refreshCameras() {
  const wrap = document.getElementById('camera-imgs');
  const note = document.getElementById('camera-note');
  if (!lastSessionActive) {
    wrap.style.display = 'none';
    note.textContent = 'no session running -- start a 6dof or ctrl demo to see live camera frames';
    return;
  }
  if (lastTrackingMode === '3dof') {
    wrap.style.display = 'none';
    note.textContent = '3dof session -- cameras are off (needs 6dof or ctrl tracking mode)';
    return;
  }
  wrap.style.display = 'grid';
  note.textContent = '';
  if (!cameraImgsBuilt) {
    wrap.innerHTML = '';
    for (let i = 0; i < CAMERA_COUNT; i++) {
      const cell = document.createElement('div');
      cell.className = 'camera-thumb';
      cell.innerHTML = `<img id="cam-img-${i}" alt="camera ${i}" style="display:none">` +
        `<span class="camera-label">cam${i}</span>`;
      wrap.appendChild(cell);
    }
    cameraImgsBuilt = true;
  }
  for (let i = 0; i < CAMERA_COUNT; i++) {
    const img = document.getElementById('cam-img-' + i);
    const probe = new Image();
    probe.onload = () => { img.src = probe.src; img.style.display = 'block'; img.style.filter = 'brightness(' + cameraBrightness + ')'; };
    probe.onerror = () => { img.style.display = 'none'; };
    probe.src = '/api/camera' + i + '.jpg?t=' + Date.now();
  }
}
setInterval(refreshCameras, 2000);
refreshCameras();
function cameraExpgainHtml(ce) {
  if (!ce) return '<span class="dim">exposure/gain: no data yet</span>';
  const cells = [];
  for (let i = 0; i < CAMERA_COUNT; i++) {
    const c = (ce.cams || {})['cam' + i];
    const v = (c && c.exposure_us != null && c.gain != null) ? `${c.exposure_us}us / ${c.gain}` : '--';
    cells.push(`<div class="cell"><div class="k">cam${i}</div><div class="v">${v}</div></div>`);
  }
  const staleNote = ce.stale ? ' <span class="warn">(stale)</span>' : '';
  const dropped = ce.dropped_frames != null ? ce.dropped_frames : '?';
  return `<div class="hgrid">${cells.join('')}</div>`
    + `<div class="dim" style="margin-top:4px">dropped frames (total): ${dropped}${staleNote}</div>`;
}
// ---- Vitals: hand-rolled canvas sparklines (2026-09-05) -----------------------------
// FPS / HMD temp / camera dropped-frame rate -- a technician's TREND view of a live
// session, explicitly NOT a raw log/table
// (a clean flow, not a log). No charting library: this dashboard has no guaranteed internet
// (same reasoning as zero web fonts), and 3 scalar time series is
// little enough code that a dependency buys nothing. Each metric keeps a small
// in-memory ring buffer client-side and redraws every tick() (~6s cadence -> ~6 min
// window at VITALS_BUFFER=60).
const VITALS_BUFFER = 60;
const vitals = {
  fps:  { buf: [], canvas: null, ctx: null, valEl: null, opts: { min: 0 } },
  temp: { buf: [], canvas: null, ctx: null, valEl: null, opts: {} },
  drop: { buf: [], canvas: null, ctx: null, valEl: null, opts: { min: 0 } },
};
function initVitals() {
  for (const [key, v] of Object.entries(vitals)) {
    v.canvas = document.getElementById('vital-' + key);
    v.valEl = document.getElementById('vital-' + key + '-val');
    if (v.canvas) v.ctx = v.canvas.getContext('2d');
  }
}
function pushVital(key, value) {
  const v = vitals[key];
  if (!v) return;
  v.buf.push(value);
  if (v.buf.length > VITALS_BUFFER) v.buf.shift();
}
function resizeVitalCanvas(v) {
  if (!v.canvas) return;
  const rect = v.canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(rect.width * dpr));
  const h = Math.max(1, Math.round(rect.height * dpr));
  if (v.canvas.width !== w || v.canvas.height !== h) { v.canvas.width = w; v.canvas.height = h; }
}
function drawSparkline(v) {
  if (!v.ctx || !v.canvas) return;
  const ctx = v.ctx, w = v.canvas.width, h = v.canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = 'rgba(163,167,172,.25)'; // --ink-dim, low alpha -- gridlines only
  ctx.lineWidth = 1;
  for (let i = 1; i < 3; i++) {
    const y = Math.round((h / 3) * i) + 0.5;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  const nums = v.buf.filter(x => x != null);
  if (nums.length < 2) return; // not enough points yet -- gridlines only, no false line
  const min = v.opts.min != null ? v.opts.min : Math.min(...nums);
  const max = v.opts.max != null ? v.opts.max : Math.max(...nums);
  const span = (max - min) || 1;
  ctx.strokeStyle = '#7c93a6'; // --accent -- canvas can't read CSS custom properties directly
  ctx.lineWidth = 1.5 * (window.devicePixelRatio || 1);
  ctx.beginPath();
  let started = false;
  v.buf.forEach((val, i) => {
    const x = (i / (VITALS_BUFFER - 1)) * w;
    if (val == null) { started = false; return; }
    const y = h - ((val - min) / span) * h;
    if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
  });
  ctx.stroke();
}
initVitals();
window.addEventListener('resize', () => {
  for (const v of Object.values(vitals)) { resizeVitalCanvas(v); drawSparkline(v); }
});
// Camera dropped-frames RATE (2026-09-05): camera-expgain.json's dropped_frames is a
// cumulative counter -- the Vitals chart wants a rate, so this diffs consecutive
// samples client-side (frames / elapsed-seconds), same idea as rig_telemetry's own
// cpu_telemetry() diffing two /proc/stat samples server-side. A negative delta (the
// counter reset -- e.g. monado restarted) or the very first sample (nothing to diff
// against yet) both report "no rate yet" rather than a nonsense number.
let _lastDroppedSample = null; // {count, tMs}
function computeDroppedRate(ce) {
  if (!ce || ce.dropped_frames == null) { _lastDroppedSample = null; return null; }
  const nowMs = Date.now(), cur = ce.dropped_frames;
  if (_lastDroppedSample == null) { _lastDroppedSample = { count: cur, tMs: nowMs }; return null; }
  const dCount = cur - _lastDroppedSample.count;
  const dSec = (nowMs - _lastDroppedSample.tMs) / 1000;
  _lastDroppedSample = { count: cur, tMs: nowMs };
  if (dSec <= 0 || dCount < 0) return null;
  return dCount / dSec;
}
function updateVitals(d) {
  const perf = d.perf_metrics;
  if (perf && perf.fps != null && !perf.stale) {
    pushVital('fps', perf.fps);
    vitals.fps.valEl.textContent = perf.fps.toFixed(1) + ' fps';
  } else {
    pushVital('fps', null);
    vitals.fps.valEl.textContent = perf && perf.stale ? 'stale' : 'no data yet';
  }
  const therm = d.hmd_temperature;
  if (therm && !therm.stale && therm.celsius_est && therm.celsius_est.length) {
    const avg = therm.celsius_est.reduce((a, b) => a + b, 0) / therm.celsius_est.length;
    pushVital('temp', avg);
    vitals.temp.valEl.textContent = avg.toFixed(1) + '°C (avg of ' + therm.celsius_est.length + ')';
  } else {
    pushVital('temp', null);
    vitals.temp.valEl.textContent = therm && therm.stale ? 'stale' : 'no data yet';
  }
  const ce = d.camera_expgain;
  const dropRate = computeDroppedRate(ce);
  if (dropRate != null) {
    pushVital('drop', dropRate);
    vitals.drop.valEl.textContent = dropRate.toFixed(2) + ' /s';
  } else {
    pushVital('drop', null);
    vitals.drop.valEl.textContent = ce ? 'collecting...' : 'no data yet';
  }
  for (const v of Object.values(vitals)) { resizeVitalCanvas(v); drawSparkline(v); }
}
function gpuPowerHtml(p) {
  if (!p) return '<div class="pwr-wrap"><span class="dim">power data unavailable</span></div>';
  const pct = Math.max(0, Math.min(100, (p.draw_w / p.max_limit_w) * 100));
  const defaultPct = (p.default_limit_w / p.max_limit_w) * 100;
  // color ramps with draw relative to the FACTORY DEFAULT limit, not the
  // absolute max -- drawing right up to default is normal, past it is the
  // signal worth flagging (wattages are read live from nvidia-smi above -- do not
  // hardcode this card's numbers here, the card has been swapped
  // and its limits changed).
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
function hmdThermalHtml(t) {
  if (!t || t.stale) {
    return '<span class="dim">sin datos recientes -- monado no está corriendo (no recent data -- monado not running)</span>';
  }
  const readings = t.celsius_est.map((c, i) => `T${i} ${c.toFixed(1)}°C`).join('&ensp;');
  return `<div class="row"><span>${readings}</span></div>` +
    '<div class="dim" style="font-size:12px">estimado, sin calibrar -- formula ICM-20602, no confirmada en vivo contra esta unidad (estimate, uncalibrated)</div>';
}
// Persistent presence-settings card (#presence-card, outside #grid's rebuilt innerHTML) --
// same "skip while the user is mid-edit" guard the sink-volume slider already uses
// (document.activeElement check), not a rebuild-on-signature-change like renderAudioDevices,
// since this card's shape never changes.
function renderPresenceSettings(presence) {
  if (!presence) return;
  const cb = document.getElementById('presence-enable-cb');
  const mins = document.getElementById('presence-screenoff-min');
  if (cb && document.activeElement !== cb) cb.checked = !!presence.enable;
  if (mins && document.activeElement !== mins) {
    mins.value = presence.screenoff_ms ? (presence.screenoff_ms / 60000) : 0;
  }
}
async function savePresence() {
  const cb = document.getElementById('presence-enable-cb');
  const mins = document.getElementById('presence-screenoff-min');
  const msgEl = document.getElementById('presence-msg');
  const enable = cb.checked ? 1 : 0;
  const ms = Math.max(0, Math.round(parseFloat(mins.value || '0') * 60000));
  msgEl.textContent = 'guardando...';
  try {
    const r = await fetch(`/api/presence/save?enable=${enable}&screenoff_ms=${ms}`, {method: 'POST'});
    const d = await r.json();
    msgEl.textContent = d.message;
  } catch (e) {
    msgEl.textContent = 'error: ' + e;
  }
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
    // actual session (docs/22; test ids T048/T049 in docs/pruebas.jsonl). Only treat these as alarming
    // when a session IS supposed to be active (monado running).
    const sessionActive = d.monado.running;
    lastSessionActive = sessionActive;
    lastTrackingMode = sessionActive ? d.tracking : null;
    updateCompositorToggle(sessionActive);
    renderAudioDevices(d.audio);
    renderPresenceSettings(d.presence);
    const cameraExpgainEl = document.getElementById('camera-expgain');
    if (cameraExpgainEl) cameraExpgainEl.innerHTML = cameraExpgainHtml(d.camera_expgain);
    const calBody = document.getElementById('camera-calibration-body');
    if (calBody) calBody.textContent = d.camera_calibration
      ? JSON.stringify(d.camera_calibration, null, 2)
      : 'no data yet -- camera-calibration.json not present';
    updateVitals(d);
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
    // Controllers (joysticks): startup-time detection only (Monado has no live hotplug --
    // project_g2_controller_hotplug_gap), so a "off" here after they were just powered on
    // means "jack-in-wayland.sh down/up", not "wait and refresh". See rig_telemetry.controller_status.
    const ctrl = d.controllers || {};
    function ctrlSpan(v) {
      if (v === true) return '<span class="ok">on</span>';
      if (v === false) return '<span class="bad">off</span>';
      return '<span class="dim">?</span>';
    }
    const ctrlNeedsCycle = ctrl.left === false || ctrl.right === false;
    // fw_serial/imu_zeroed (2026-09-05, hmd-status.json -- see rig_telemetry.hmd_status):
    // extends this SAME controllers row rather than a second controller section, per
    // the task's own instruction. left/right presence above still comes from
    // controller_status() (libmonado) -- this is additional per-controller detail from
    // a different, newer source, shown only when that source actually has it.
    const hmdStatus = d.hmd_status || {};
    const hsCtrl = hmdStatus.controllers || {};
    function ctrlExtra(hand) {
      const c = hsCtrl[hand];
      if (!c) return '';
      const bits = [];
      if (c.fw_serial) bits.push('fw ' + c.fw_serial);
      if (c.imu_zeroed != null) bits.push('imu_zeroed ' + (c.imu_zeroed ? 'yes' : 'no'));
      return bits.length ? ` <span class="dim">(${bits.join(', ')})</span>` : '';
    }
    const controllersRow = sessionActive
      ? `<div class="row"><span>controllers (joysticks)</span><span>${ctrl.error ? `<span class="dim">${ctrl.error}</span>` : `L ${ctrlSpan(ctrl.left)}${ctrlExtra('left')} &middot; R ${ctrlSpan(ctrl.right)}${ctrlExtra('right')}`}${ctrlNeedsCycle ? ' <span class="warn">-- power on, then jack-in down/up (no live hotplug)</span>' : ''}</span></div>`
      : `<div class="row"><span>controllers (joysticks)</span><span class="dim">n/a -- no session running</span></div>`;
    const audio = d.audio || {};
    const audioCls = audio.route === 'headset' ? 'ok' : 'warn';
    const audioLabel = `${audio.route || '?'}${audio.muted ? ' (MUTED)' : ''} -- ${audio.volume_pct != null ? audio.volume_pct + '%' : '?'}`;
    const audioRow = `<div class="row"><span>audio output</span><span class="${audioCls}">${audioLabel}</span></div>`;
    const specs = d.specs || {};
    const cpu = specs.cpu || {};
    // ---- Operator-tray tier: session state (always visible, the "2-second glance") ----
    // TRIMMED (2026-09-05): the full DoF/controller/audio explanations moved to the
    // HEADSET tab and power_mode moved to the GPU tab -- this card keeps only the
    // state/DoF-name/controllers-dot/audio-route-dot a glance actually needs.
    const ctrlDotCls = !sessionActive ? 'dim' : (ctrl.error ? 'dim' : (ctrlNeedsCycle ? 'warn' : (ctrl.left && ctrl.right ? 'ok' : 'warn')));
    document.getElementById('session-rows').innerHTML = `
      <div class="row"><span>state</span><span class="${sessionActive?'ok':'dim'}">${sessionActive?'ACTIVE':'IDLE'}</span></div>
      <div class="row"><span>DoF</span><span class="${sessionActive?'ok':'dim'}">${sessionActive ? (d.tracking||'?').toUpperCase() : 'n/a'}</span></div>
      <div class="row"><span>controllers</span><span class="status-dot ${ctrlDotCls}"></span></div>
    `;
    // Master status-strip dots (header row, unchanged): the true at-a-glance read, one
    // level above even the session card -- SESSION mirrors the state row above; AUDIO
    // mirrors audioCls; HARDWARE folds USB/display/coredump faults into one dot so a
    // real problem is visible without opening any tab.
    const usbFault = d.usb.present_count < d.usb.total;
    const drmFault = Object.entries(d.drm).some(([, s]) => s === 'disconnected' && sessionActive);
    const hwFault = usbFault || drmFault || d.coredumps.count > 0;
    document.getElementById('dot-session').className = 'status-dot ' + (sessionActive ? 'ok' : 'dim');
    document.getElementById('dot-audio').className = 'status-dot ' + audioCls;
    document.getElementById('dot-hw').className = 'status-dot ' + (hwFault ? 'bad' : 'ok');

    // ---- Nameplate strip (2026-09-05, always visible, not a tab): repo/uptime/sunshine
    // ----
    document.getElementById('nameplate-strip').innerHTML = `
      <span><b>REPO</b>${(d.repo.head||'?').split(' ')[0]} <span class="${d.repo.dirty?'warn':'ok'}">${d.repo.dirty?'· dirty':'· clean'}</span></span>
      <span><b>UPTIME</b>${d.uptime || '?'}</span>
      <span><b>SUNSHINE</b><span class="${d.sunshine?'ok':'dim'}">${d.sunshine ? 'active' : 'inactive'}</span></span>
    `;

    // ---- Instrument bank tabs: HEADSET/GPU/CPU, tick() writes into all three panels'
    // DOM every cycle regardless of which is visible (same as the old collapsed
    // <details> content always did) -- pure attribute toggling, not a re-fetch, picks
    // which one is actually shown (see selectTab()). ----
    document.getElementById('grid-headset').innerHTML = `
      <div class="card"><h2>Tracking mode</h2>${trackingRow}</div>
      <div class="card"><h2>Controllers</h2>${controllersRow}</div>
      <div class="card"><h2>USB (${d.usb.present_count}/${d.usb.total})</h2>${usbRows}</div>
      <div class="card"><h2>Display connectors</h2>${drmRows}</div>
      <div class="card"><h2>monado-service</h2>
        <div class="row"><span>running</span><span class="${monadoCls}">${monadoLabel}</span></div>
        <div class="row"><span>coredumps (total)</span><span class="${d.coredumps.count>0?'warn':'ok'}">${d.coredumps.count}</span></div>
        <pre>${d.coredumps.last || 'none'}</pre>
      </div>
      <div class="card"><h2>HMD thermal</h2>${hmdThermalHtml(d.hmd_temperature)}</div>
      <div class="card"><h2>vr device</h2><div class="row"><span>present</span><span class="${d.vr_device?'ok':'dim'}">${d.vr_device ? 'yes' : 'no'}</span></div></div>
      <div class="card"><h2>HMD status (raw)</h2>
        <div class="row"><span>device_status_raw</span><span class="dim" style="font-family:var(--font-mono)">${hmdStatus.device_status_raw_hex || 'no data yet'}</span></div>
        <div class="dim" style="font-size:11px;margin-top:4px">undecoded, diagnostic reference only -- no meaning assigned to these bytes (yet)</div>
      </div>
    `;
    const dotHeadset = document.getElementById('dot-headset');
    if (dotHeadset) dotHeadset.hidden = !hwFault;

    // GPU tab: power gauge + power_mode (moved out of the Session card -- same
    // subsystem fact) + driver/name string, all folded into one card.
    const gpuFault = d.gpu_power == null;
    document.getElementById('grid-gpu').innerHTML = `
      <div class="card"><h2>GPU power</h2>${gpuPowerHtml(d.gpu_power)}
        <div class="row"><span>power mode</span>${powerRow}</div>
        <pre>${d.gpu}</pre>
      </div>
    `;
    const dotGpu = document.getElementById('dot-gpu');
    if (dotGpu) dotGpu.hidden = !gpuFault;

    // CPU tab (2026-09-05): the first LIVE cpu data anywhere on this page -- load
    // average + per-core utilisation + temperature, generalized on top of the same
    // .pwr-track/.pwr-fill meter gpuPowerHtml() already uses, plus the static
    // model/cores string and the governor field (fetched all along, never rendered
    // until now), plus RAM (co-located here as the shared host-resource budget).
    const cpuLive = d.cpu_live || {};
    const cores = cpu.cores || 1;
    const loadRatio = cpuLive.load1 != null ? (cpuLive.load1 / cores) : null;
    const loadColor = loadRatio == null ? 'var(--ink-inactive)' : (loadRatio > 0.95 ? 'var(--bad)' : (loadRatio > 0.75 ? 'var(--warn)' : 'var(--ok)'));
    const loadHtml = loadRatio == null ? '<span class="dim">load unavailable</span>' : `
      <div class="pwr-wrap">
        <div class="pwr-nums"><span><b style="color:${loadColor}">${cpuLive.load1.toFixed(2)}</b> load1 / ${cores} cores</span>
          <span class="dim">5m ${cpuLive.load5.toFixed(2)} &middot; 15m ${cpuLive.load15.toFixed(2)}</span></div>
        <div class="pwr-track"><div class="pwr-fill" style="width:${Math.min(100,loadRatio*100)}%; background:${loadColor}"></div></div>
      </div>`;
    const coreRows = cpuLive.per_core_pct == null
      ? '<span class="dim">collecting...</span>'
      : cpuLive.per_core_pct.map((p,i) => {
          const c = p > 95 ? 'var(--bad)' : (p > 80 ? 'var(--warn)' : 'var(--ok)');
          return `<div class="pwr-wrap" style="margin-bottom:4px"><div class="pwr-nums"><span>core ${i}</span><span class="dim">${p.toFixed(0)}%</span></div>
            <div class="pwr-track" style="height:5px"><div class="pwr-fill" style="width:${p}%; background:${c}"></div></div></div>`;
        }).join('');
    let tempHtml, cpuTempFault = false;
    if (cpuLive.temp_c == null) {
      tempHtml = '<span class="dim">temperature unavailable</span>';
    } else {
      cpuTempFault = cpuLive.temp_c >= 75;
      const tCls = cpuLive.temp_c >= 88 ? 'bad' : (cpuLive.temp_c >= 75 ? 'warn' : 'ok');
      tempHtml = `<span class="${tCls}">${cpuLive.temp_c.toFixed(1)}&deg;C</span> <span class="dim">(${cpuLive.temp_source||'?'})</span>`;
    }
    const ramPct = d.ram_pct;
    const ramColor = ramPct == null ? 'var(--ink-inactive)' : (ramPct > 90 ? 'var(--bad)' : (ramPct > 75 ? 'var(--warn)' : 'var(--ok)'));
    const ramHtml = ramPct == null ? '<span class="dim">?</span>' : `
      <div class="pwr-wrap"><div class="pwr-nums"><span><b style="color:${ramColor}">${ramPct}%</b>${specs.ram_gb ? ' of ' + specs.ram_gb + ' GB' : ''}</span></div>
        <div class="pwr-track"><div class="pwr-fill" style="width:${Math.min(100,ramPct)}%; background:${ramColor}"></div></div></div>`;
    document.getElementById('grid-cpu').innerHTML = `
      <div class="card"><h2>CPU load</h2>${loadHtml}</div>
      <div class="card"><h2>Per-core utilisation</h2>${coreRows}</div>
      <div class="card"><h2>Temperature</h2>${tempHtml}
        <div class="dim" style="font-size:11px;margin-top:6px">provisional threshold -- ok &lt;75&deg;C, warn 75-88&deg;C, bad &ge;88&deg;C (Ryzen 5 5600X ~90&deg;C Tjmax) -- not yet validated under a sustained 6dof session</div>
      </div>
      <div class="card"><h2>System</h2>
        <div class="row"><span>cpu</span><span>${cpu.model || '?'}${cpu.cores ? ' (' + cpu.cores + 'c/' + (cpu.threads||'?') + 't)' : ''}</span></div>
        <div class="row"><span>governor</span><span>${cpu.governor || '?'}</span></div>
      </div>
      <div class="card"><h2>RAM</h2>${ramHtml}</div>
    `;
    const dotCpu = document.getElementById('dot-cpu');
    if (dotCpu) dotCpu.hidden = !cpuTempFault;

    document.getElementById('ts').textContent = 'updated ' + d.generated_at;
  } catch(e) {
    const msg = '<div class="card bad">fetch failed: ' + e + '</div>';
    ['grid-headset', 'grid-gpu', 'grid-cpu'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = msg;
    });
  }
  setTimeout(tick, 6000);
}
// ---- Instrument-bank tab switching (2026-09-05): pure attribute toggling, no re-fetch --
// tick() above keeps writing into all three panels regardless of which is visible. ----
const TAB_IDS = ['headset', 'gpu', 'cpu'];
function selectTab(id, opts) {
  opts = opts || {};
  TAB_IDS.forEach(t => {
    const btn = document.getElementById('tab-' + t);
    const panel = document.getElementById('panel-' + t);
    const active = t === id;
    if (btn) { btn.setAttribute('aria-selected', active ? 'true' : 'false'); btn.tabIndex = active ? 0 : -1; }
    if (panel) panel.hidden = !active;
  });
  if (!opts.skipSave) {
    try { localStorage.setItem('g2-dashboard-tab', id); } catch(e) {}
  }
}
function initTabs() {
  let initial = 'headset';
  try { initial = localStorage.getItem('g2-dashboard-tab') || 'headset'; } catch(e) {}
  if (TAB_IDS.indexOf(initial) === -1) initial = 'headset';
  selectTab(initial, {skipSave: true});
  TAB_IDS.forEach((id, i) => {
    const btn = document.getElementById('tab-' + id);
    if (!btn) return;
    btn.addEventListener('click', () => selectTab(id));
    btn.addEventListener('keydown', (e) => {
      let ni = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') ni = (i + 1) % TAB_IDS.length;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ni = (i - 1 + TAB_IDS.length) % TAB_IDS.length;
      else if (e.key === 'Home') ni = 0;
      else if (e.key === 'End') ni = TAB_IDS.length - 1;
      if (ni != null) {
        e.preventDefault();
        selectTab(TAB_IDS[ni]);
        const nb = document.getElementById('tab-' + TAB_IDS[ni]);
        if (nb) nb.focus();
      }
    });
  });
}
initTabs();
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
// ---- Profile strip: per-user settings + fixed headset props -----------------
// Split in two (2026-09-05): the always-visible strip (active user + brightness +
// language -- fast/clean switching, the very top of the page) vs the collapsed
// "edit profile" access-panel (per-user height/dof/mapping/notes, read rarely, plus
// the read-only "fixed spec plate" -- hardware facts, not user data).
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
    const names = Object.keys(d.users || {});
    const opts = names.map(n => `<option value="${n}" ${n===d.active?'selected':''}>${n}</option>`).join('');
    const gain = (+(d.brightness_live!=null?d.brightness_live:(u.brightness!=null?u.brightness:1))).toFixed(2);
    const esc = s => (s||'').replace(/"/g,'&quot;');
    const langOpts = ['en','es','ru'].map(l => `<option value="${l}" ${l===currentLang?'selected':''}>${l.toUpperCase()}</option>`).join('');

    const stripEl = document.getElementById('profile-strip-body');
    stripEl.innerHTML = `
      <label>${t('cc_active_user')}</label>
      <select id="active-user" onchange="userSelect(this.value)">${opts}</select>
      <input id="uc-new" placeholder="${t('cc_new_user_ph')}" style="width:110px">
      <button onclick="userAdd()">${t('cc_add_btn')}</button>
      <label style="margin-left:6px">${t('cc_brightness')}</label>
      <input type="range" min="0.5" max="2.5" step="0.05" value="${gain}" id="uc-bri"
             title="1.0 = clean. Any other value visibly dithers/flickers in bright areas on this headset (docs/112)."
             oninput="document.getElementById('uc-bri-v').textContent=(+this.value).toFixed(2)+'x'; document.getElementById('uc-bri-v').className=(+this.value===1)?'ok':'warn'"
             onchange="setBrightness(this.value)" style="width:150px">
      <span id="uc-bri-v" class="${(+gain===1)?'ok':'warn'}">${gain}x</span>
      <label style="margin-left:6px">${t('cc_lang')}</label>
      <select id="cc-lang" onchange="applyLangAndSave(this.value)">${langOpts}</select>
    `;

    const fixedRows = Object.entries(d.fixed||{}).map(([k,v]) =>
      `<div class="row"><span>${k}</span><span>${v}</span></div>`).join('');
    const editEl = document.getElementById('profile-edit-body');
    editEl.innerHTML = `
      <div style="margin-top:4px"><b>${t('cc_adjustable')}</b></div>
      <div class="row"><span>${t('cc_height')}</span>
        <input id="uc-height" type="number" step="0.01" min="1.0" max="2.2" value="${u.height_m||1.7}" style="width:80px"></div>
      <div class="row"><span>${t('cc_dof')}</span>
        <select id="uc-dof"><option ${u.dof==='3dof'?'selected':''}>3dof</option><option ${u.dof==='6dof'?'selected':''}>6dof</option></select></div>
      <div class="row"><span>${t('cc_mapping')}</span><input id="uc-map" value="${esc(u.mapping)}" style="width:260px"></div>
      <div class="row"><span>${t('cc_notes')}</span><input id="uc-notes" value="${esc(u.notes)}" style="width:260px"></div>
      <div class="row"><span>${t('cc_resting_delay')}</span>
        <select id="uc-resting-delay">${
          [[0,'0 (instantáneo)'],[60000,'1 min'],[120000,'2 min'],[180000,'3 min'],[600000,'10 min']]
            .map(([v,l]) => `<option value="${v}" ${(u.resting_alert_delay_ms||0)===v?'selected':''}>${l}</option>`).join('')
        }</select></div>
      <div class="row"><span>${t('cc_voice_gender')}</span>
        <select id="uc-voice-gender">
          <option value="male" ${(u.voice_gender||'male')==='male'?'selected':''}>M</option>
          <option value="female" ${(u.voice_gender||'male')==='female'?'selected':''}>F</option>
        </select></div>
      <div class="row"><span>${t('cc_audio_guide')}</span>
        <input type="checkbox" id="uc-audio-guide" ${u.audio_guide_enabled!==false?'checked':''}></div>
      <div style="margin-top:6px"><button onclick="userSave()">${t('cc_save_btn')}</button>
        <span id="uc-msg" class="dim" style="font-size:12px"></span></div>
      <div class="fixed-plate">
        <div style="margin-bottom:4px"><b>${t('cc_fixed')}</b></div>${fixedRows}
      </div>`;
  } catch(e) {
    const stripEl = document.getElementById('profile-strip-body');
    if (stripEl) stripEl.textContent = 'error: '+e;
  }
}
async function userSelect(name) { await fetch('/api/user/select?name='+encodeURIComponent(name), {method:'POST'}); refreshUserCenter(); }
function userAdd() {
  const n = (document.getElementById('uc-new').value||'').trim(); if (!n) return;
  fetch('/api/user/save', {method:'POST', body: JSON.stringify({name:n, height_m:1.7, dof:'3dof', brightness:1.0, mapping:'', notes:'', lang:currentLang, resting_alert_delay_ms:0, make_active:true})}).then(()=>refreshUserCenter());
}
async function setBrightness(g) { await fetch('/api/brightness?gain='+encodeURIComponent(g), {method:'POST'}); }
async function userSave() {
  const name = document.getElementById('active-user').value;
  const body = JSON.stringify({ name: name,
    height_m: parseFloat(document.getElementById('uc-height').value)||1.7,
    dof: document.getElementById('uc-dof').value,
    brightness: parseFloat(document.getElementById('uc-bri').value)||1.0,
    mapping: document.getElementById('uc-map').value, notes: document.getElementById('uc-notes').value,
    resting_alert_delay_ms: parseInt(document.getElementById('uc-resting-delay').value)||0,
    voice_gender: document.getElementById('uc-voice-gender').value,
    audio_guide_enabled: document.getElementById('uc-audio-guide').checked,
    lang: currentLang });
  const d = await (await fetch('/api/user/save', {method:'POST', body})).json();
  document.getElementById('uc-msg').textContent = (d.ok?'guardado ':'FALLO ')+d.message;
}
(function() {
  let initial = 'en';
  try { initial = localStorage.getItem('g2-dashboard-lang') || (navigator.language||'en').slice(0,2); } catch(e) {}
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
        elif self.path.startswith("/api/camera") and _CAMERA_JPG_RE.match(self.path):
            # NB: matched with the regex above, not self.path.endswith(".jpg") -- the frontend's
            # refreshCameras() always calls this with a cache-busting "?t=<timestamp>" suffix
            # (same as refreshScreen()/capture_jpeg()), so self.path never literally ends in
            # ".jpg" in real use. That endswith() check used to make this branch fall through to
            # the catch-all handler below, silently serving the full dashboard HTML page as if it
            # were the image response (still HTTP 200, so no visible error) -- the <img>/probe then
            # fails to decode it and the thumbnail just stays hidden, showing through to the dark
            # card background, which reads as "black" rather than a clear placeholder. Found
            # 2026-09-05 by curling the endpoint with and without the "?t=" query string and
            # diffing content-type/size (text/html 91750B vs image/jpeg 27363B for the same frame).
            m = _CAMERA_JPG_RE.match(self.path)
            idx = int(m.group(1)) if m else -1
            img = capture_camera_jpeg(idx) if 0 <= idx < CAMERA_COUNT else None
            if img is None:
                self.send_response(204)  # stale/missing frame, or index out of range
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
        elif self.path.startswith("/api/presence/save"):
            q = parse_qs(urlparse(self.path).query)
            ok, msg = save_presence_settings(
                q.get("enable", ["0"])[0], q.get("screenoff_ms", ["0"])[0])
            self._json_post(ok, msg)
        elif self.path.startswith("/api/user/select"):
            q = parse_qs(urlparse(self.path).query)
            name = q.get("name", [""])[0]
            d = load_users()
            if name in d["users"]:
                d["active"] = name
                save_users(d)
                set_brightness_gain(d["users"][name].get("brightness", 1.0))
                set_resting_alert_delay_ms(d["users"][name].get("resting_alert_delay_ms", 0))
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
                for k in ("height_m", "dof", "brightness", "mapping", "notes", "lang",
                          "resting_alert_delay_ms", "voice_gender", "audio_guide_enabled"):
                    if k in p:
                        u[k] = p[k]
                d["users"][name] = u
                if p.get("make_active"):
                    d["active"] = name
                save_users(d)
                # brightness has its own live slider (oninput -> /api/brightness) that
                # applies before Save is even clicked; resting_alert_delay_ms has no such
                # slider, so apply it here whenever the saved profile is the active one --
                # otherwise Save would silently do nothing until the next user/select.
                if d["active"] == name:
                    set_resting_alert_delay_ms(u.get("resting_alert_delay_ms", 0))
                self._json_post(True, f"usuario '{name}' guardado")
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
    # Mic defaults OFF (muted) on startup -- a lab machine should never come up hot-mic'd.
    try:
        subprocess.run([f"{HOME}/vr/hmd-audio.sh", "mic", "off"], capture_output=True, timeout=5)
    except Exception:
        pass
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("serving on http://127.0.0.1:8765")
    srv.serve_forever()
