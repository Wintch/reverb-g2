#!/usr/bin/env python3
"""Read-only local status dashboard for the HP Reverb G2 lab rig (iashur).
Binds to 127.0.0.1 only. Never writes to any device (no panel.py calls).
First slice per the 2026-08-21 kiosk gap analysis -- run by hand, not wired
into the boot path yet.
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


def _hmd_connector():
    """DRM connector the HP Reverb G2 panel is on, by EDID fingerprint (HPN + product
    0x36c1 = bytes 8..11 '22 0e c1 36'); None if the panel is asleep. This is the G2
    display MODEL's id, identical on every G2 unit -- NOT rig-specific, and it never
    reads the per-unit serial (bytes 12..15, docs/91). /sys .../edid is world-readable."""
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


# ---- Tracking-camera live preview (2026-09-05) ----
# wmr_camera.c (monado, WMR_CAMERA_SNAPSHOT env, default on) dumps one throttled (~1fps) raw 8-bit
# grayscale PGM per SLAM-tracking camera to ~/vr/cameraN.pgm -- but ONLY while the cameras are
# actually streaming, i.e. 6dof or ctrl tracking mode (rig_telemetry.tracking_mode(); 3dof has no
# cameras at all, see jack-in-wayland.sh's TRACKING_ENV). Same split as the HMD-temperature
# snapshot feature shipped earlier today: cheap raw dump in C, the real JPEG encoding happens
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
    # 2026-08-29 (xrizer patch 0008): recenter the RUNNING title's play space on the current head
    # pose, for titles with no button to hold (Dreams of Dali is headset-only; the A-button cue
    # above is Aircar's own recentre). xrizer polls this file every ~30 frames, removes it and
    # resets the Standing + Seated origins; a touch older than 10 s is discarded, so pressing it
    # with no title running is harmless. Booth flow: guest sits, looks straight ahead, operator
    # presses. docs/80 "the recentre lever".
    "recenter-xrizer": {
        "label": "🎯 Recentrar (visitante mirando al frente)",
        "cmd": ["/usr/bin/touch", f"{HOME}/vr/logs/xrizer-recenter"],
        "cwd": f"{HOME}/vr",
    },
    # 2026-08-29 (xrizer patch 0009, worn-validated 2026-08-29/30, now baked into the booth buttons): Dali test action.
    # WMR_USER_PRESENCE=1 makes Monado surface the G2 proximity sensor as XR_EXT_user_presence
    # (patches 0075/0087, threshold flagged provisional); the flag file (content = delay ms) arms
    # xrizer to recentre 2 s after the PRESENT edge. The plain demo button never creates the flag,
    # so booth behaviour is unchanged. Wearer test: headset on the desk -> title loads -> put it on
    # looking sideways -> the scene should come round by itself ~2 s later (xrizer.txt logs it).
    # Same test for Aircar 6dof (its own profile applies: JQ stack, neck arm 100). 2026-08-29 22:57 the
    # Dali run validated 0009 live: PRESENT edge -> recentre 2.0 s later, scene came round by itself;
    # a 15 s headset adjustment re-armed and fired again (by design: > 15 s since the last fire).
    "test-1073390-autorecenter": {
        "label": "🧪 Aircar auto-recentrar al ponerse (0009)",
        "cmd": ["bash", "-c", f"echo 2000 > {HOME}/vr/logs/xrizer-recenter-on-don; exec python3 {HOME}/vr/vr-launcher.py 1 6dof"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": "1073390", "WMR_USER_PRESENCE": "1", "U_PACING_APP_LOG": "debug",
                "VIT_COLLAPSE_LOG": "1", "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Aircar 6dof autorecenter test (0009)"},
    },
    "test-591360-autorecenter": {
        "label": "🧪 Dalí auto-recentrar al ponerse (0009, sin validar)",
        "cmd": ["bash", "-c", f"echo 2000 > {HOME}/vr/logs/xrizer-recenter-on-don; exec python3 {HOME}/vr/vr-launcher.py 1 6dof"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": "591360", "WMR_USER_PRESENCE": "1", "U_PACING_APP_LOG": "debug",
                "VIT_COLLAPSE_LOG": "1", "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof autorecenter test (0009)"},
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
    ("Aircar", "1073390", "3dof", "approved", "Xbox pad. Recentre: A button (the guest) or 🎯 (the operator). 2026-08-30: the donning auto-recentre (xrizer 0009) is NOT enabled here -- on this 3dof button the cockpit follows a runtime recentre by a few degrees only (game-side re-basing; it works at the logo and in 6dof). docs/80 2026-08-30."),
    ("Aircar", "1073390", "6dof", "gold", "2026-08-26 fix (patch 0097): gyro-pred + freeze + 150mm neck-arc + 50ms spread, auto-applied by the launcher. 2026-08-27 SOAK (several min worn): held 90 (0 pacer stalls), 0 USB/companion drops, 0 SLAM loss -- stability certified. Wearer: still/gamepad-only = very good; STAYS GOLD, not approved. The gold->perfect blocker is a felt ~100-200ms positioning-latency (SLAM anchor-age floor) on FAST full-axis head motion -- A recentres, tolerable but 'rompe todo' when moving fast. NOTE: any fps counter you see is the DESKTOP MIRROR (mutter 60Hz vsync); no in-headset counter works (xrizer overlay whitelist)."),
    ("Dreams of Dali", "591360", "6dof", "approved", "Headset-only gaze-dwell, no controllers. 2026-08-29 15:15 worn on THIS button (scale 100, anchor profile): 89-90 fps in 6/8 20-s windows, dips to 79/85 when the GPU hits the 250 W cap (91-96 %) -- keep the cap at 250 W for the booth; pacer 0.02 % late; SLAM 30 Hz, 0 guard trips, max 1.57 m. Wearer: solido. RULES: lit room (light-preflight.sh); headset still on the desk until the title has loaded (~60 s); then the guest puts it on, sits looking straight ahead and the operator presses the Recentrar button (xrizer 0008, worn-validated 2026-08-29: 90-degree test, 0.2 s). 2026-08-30: recentres by itself ~2 s after donning (xrizer 0009, validated worn 2026-08-29 22:57); 🎯 stays as fallback."),
    ("Wolfenstein: Cyberpilot", "1056970", "6dof", "testing", "2026-08-27: WORKS in-headset (native Bethesda idTech, motion controllers). Launcher auto-applies the Aircar 6dof head recipe (patch 0097 knobs) WITH constellation ON (the game needs 6dof hands). Wearer: hands ~ok, less drift than before, playable; ~2m drift on FAST head turns (bounded). RESET = RIGHT SHIFT held 3s. Perceived ~60fps ('Fake pacer fell behind' spam) -- for 90: minimize the game window (mutter vsyncs any visible window to the 60Hz desktop), lift the GPU 70% power cap, lower graphics/render-scale (docs/23). NOT guest-ready until the 60->90 residual is settled."),
    ("Hellblade", "747350", "6dof", "broken", "2026-08-27 retest: prefix relocated NTFS->ext4 (docs/70), and it's GAMEPAD-played (not motion controllers -- constellation not needed). But it CRASHES in the UE4 render thread on 'start' (LowLevelFatalError RenderingThread.cpp:933, UE4 minidump in the prefix). Worked ONCE 2026-08-21 pre-reinstall ('very promising, steady 45fps' -- docs/75:198); uninstalled+reinstalled 2026-08-26 since. The Aug-21 working prefix still exists at ~/.steam/.../compatdata/747350 but Steam bypasses it (game moved to /mnt/win5). Dedicated retest pending: reuse the Aug-21 prefix / drop SCALE=100 / try another Proton (docs/67 §4 B5)."),
    ("The Night Cafe", "482390", "6dof", "untested", "CORRECTED 2026-08-27: the 2026-08-26 'broken/flat-2D' verdict was WRONG -- that one launch died inside the OpenXR loader because XR_RUNTIME_JSON was unset for that process (the launch-options trap, not a Unity flat-fallback). Never actually reached the runtime. 2026-08-29 17:04 UNWORN RETEST after the Steam env fix (docs/80): reaches a FOCUSED Monado session, 89 fps delivered, 1 harmless unknown-interface line (IVRSettings_001). Root cause was Steam not applying this title's LaunchOptions; XR_RUNTIME_JSON/IPC_IGNORE_VERSION/PRESSURE_VESSEL_FILESYSTEMS_RW now come from the Steam client env (vr-launcher GAME_ENV) + active_runtime.json. NEXT: a worn test (does it need controller point/grab?)."),
    ("Anne Frank House VR", "2877690", "6dof", "broken", "CORRECTED 2026-08-27: DOES reach a real Monado session (BEGIN_SESSION, controllers registered) -- the earlier '0 delivered frames' framing came from the dead-grep metric trap (needs U_PACING_APP_LOG=debug), not a proven flat-fallback. Real cause: engine abandons the session after ONE capability probe and never retries -- matches Valve unity-xr-plugin #97/#111. Engine-side give-up, not a render failure. Parked."),
]
# 2026-08-30: 6dof booth titles (approved / gold) recentre by themselves when the guest puts the
# headset on -- xrizer patch 0009, worn-validated on Dali 6dof (2026-08-29 22:57) and Aircar 6dof
# (2026-08-29 23:26 + 23:34, 2026-08-30 05:28 / 05:38 / 05:42, both 90-degree sides; wearer:
# "vuelve al centro"). WMR_USER_PRESENCE=1 makes Monado surface the G2 proximity sensor as
# XR_EXT_user_presence; the flag file (content = delay in ms) arms xrizer to recentre 2 s after the
# PRESENT edge; a fire < 15 s ago blocks re-arming (sensor flap / headset adjustment). The 🎯 button
# stays as the manual fallback. Every other button REMOVES the flag so the behaviour is explicit
# per launch. docs/80 "2026-08-29 22:50–23:56" + the 2026-08-30 entry.
_DON_FLAG = f"{HOME}/vr/logs/xrizer-recenter-on-don"
for _name, _appid, _tracking, _status, _note in DEMO_LAUNCHES:
    # 2026-08-30 06:25: 6dof only. On Aircar 3dof the fire is correct but the cockpit follows it by
    # "a few degrees" only (the game re-bases the view itself there; docs/80 2026-08-30 entry), so
    # the lineup's 3dof button keeps the A-button / 🎯 flow. One-liner to flip once understood.
    _auto = _status in ("approved", "gold") and _tracking == "6dof"
    _prep = f"echo 2000 > {_DON_FLAG}" if _auto else f"rm -f {_DON_FLAG}"
    ACTIONS[f"demo-{_appid}-{_tracking}"] = {
        "label": f"{_name} · {_tracking} [{_status}]",
        "cmd": ["bash", "-c", f"{_prep}; exec python3 {HOME}/vr/vr-launcher.py 1 {_tracking}"],
        "cwd": f"{HOME}/vr",
        "env": {"VR_LAUNCH_APPID": _appid, "U_PACING_APP_LOG": "debug",
                # Demo buttons auto-record (RAM -> permanent on session end, docs/80). Approved
                # titles record by default; the record is what turns the live demo into the soak.
                "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": f"{_name} {_tracking} [{_status}]",
                **({"WMR_USER_PRESENCE": "1"} if _auto else {})},
        "demo": {"title": _name, "tracking": _tracking, "status": _status, "note": _note},
    }

# 2026-08-29 (docs/80 "the gate run was invalid"): the ONE run that can still promote P2 into the
# global basalt-g2-config.json -- Dali 6dof under the P2 backend in a LIT room (the 05:24 gate run was
# in the dark and said nothing). Same launch as the approved Dali button plus SLAM_CONFIG from the env
# (ambient env wins over the title profile in vr-launcher.py, so Dali's own profile -- scale 100,
# 6 threads, constellation off, no head-prediction knobs -- stays as shipped); records like every demo
# button so worn-grade.py has the CSVs afterwards. If in doubt about the light, run
# scripts/light-preflight.sh first (detached).
ACTIONS["gate-591360-P2"] = {
    "label": "Dreams of Dali · 6dof · compuerta P2 [solo con luz]",
    "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
    "cwd": f"{HOME}/vr",
    "env": {"VR_LAUNCH_APPID": "591360", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
            "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
            "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof P2 gate (lit room)"},
    "demo": {"title": "Dali compuerta P2 (con luz)", "tracking": "6dof", "status": "testing",
             "note": "RESULTADO 2026-08-29 14:40 (con luz, 887 landmarks): saltos de 6.6 m a los 30 s y 38.6 m a "
                     "los 107 s -> compuerta NO pasada, P2 queda solo en Aircar, Dali sigue en base (docs/80). "
                     "El boton queda para repetir la prueba. PROMOCION DE P2 AL GLOBAL, ultima compuerta (docs/80 2026-08-29): Dali 6dof con el "
                     "backend P2 en pieza ILUMINADA, ~10 min, misma rutina que la aprobacion (mirar "
                     "alrededor, inclinarse, giros lentos y rapidos). Si se siente como base con luz "
                     "('solido'), P2 puede ir al basalt-g2-config.json global. Con poca luz no vale: a "
                     "oscuras Dali se fue 161 m con P2 y 80 m con base. Ante la duda, correr "
                     "scripts/light-preflight.sh antes (DARK = no arrancar)."},
}

# 2026-08-29 14:58 (docs/80 "the base control in the same light"): both configs ran ~40 m away in the
# first two minutes of a worn Dali session (VIO scale snap after a rotation-only start), then settled.
# Lever 2: the 0099 session anchor Aircar/Cyberpilot already run, for Dali -- bounds an excursion to a
# 3 m restart. Env-only test button; if the worn check is clean it goes into TITLE_PROFILES["591360"].
ACTIONS["test-591360-anchor"] = {
    "label": "Dreams of Dali · 6dof · base + anchor 3 m [prueba]",
    "cmd": ["python3", f"{HOME}/vr/vr-launcher.py", "1", "6dof"],
    "cwd": f"{HOME}/vr",
    "env": {"VR_LAUNCH_APPID": "591360", "U_PACING_APP_LOG": "debug", "VIT_COLLAPSE_LOG": "1",
            "SLAM_SESSION_ANCHOR_RADIUS_CM": "300", "SLAM_QUAT_NORM_CHECK": "1",
            "VR_DEMO_RECORD": "1", "VR_DEMO_COMMENT": "Dali 6dof base + session anchor 300 cm (test)"},
    "demo": {"title": "Dali base + anchor 3 m (prueba)", "tracking": "6dof", "status": "testing",
             "note": "RESULTADO 2026-08-29 15:02: max 3.45 m (vs 38 m sin anchor), 6 resets de 0.02-0.21 m y yaw <= 0.02 grados, "
                     "'se juega muy similar' -> APLICADO al perfil de Dali (vr-launcher.py); el boton queda como referencia. "
                     "PRUEBA 2026-08-29 (docs/80): Dali con la config base de siempre + el guard de anchor de "
                     "3 m (0099, el mismo que corre Aircar). Motivo: con las dos configs Dali se va ~40 m en "
                     "los primeros 2 min de una sesion con el casco puesto desde el arranque y despues se "
                     "asienta; el anchor acota eso a reinicios de 3 m. Procedimiento a probar junto: casco "
                     "quieto en la mesa hasta que el juego cargo, recien ahi ponerselo. Mirar en el log los "
                     "'Tracker diverged ... from the session anchor' y el yaw delta de cada reset."},
}

# JQ_ENV = the Aircar profile as of 2026-08-28 ~18:45 -03 (docs/80 "JQ", NEXT-STEP's START
# HERE): P2 backend + averaged correction + mid-exposure stamp + queues at depth 1, horizon 50,
# clamp 150, spread 25. Module-level so the JQ button below and every round-7 button that
# reads "JQ + one lever" share one dict and cannot drift from each other.
JQ_ENV = {
    "SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
    "SLAM_CORRECTION_SPREAD_MS": "25", "SLAM_CONFIG": f"{HOME}/vr/basalt-variants/P2.toml",
    "SLAM_CORRECTION_AVG_N": "3", "WMR_CAM_TS_MID_EXPOSURE": "1", "VIT_QUEUE_DEPTH": "1",
    # 2026-08-29 06:14-06:37 (docs/80 "The 10-minute wearer slot"): neck arm 150 -> 100, same
    # edit as vr-launcher.py TITLE_PROFILES["1073390"] (until tonight this dict did not carry
    # the key and the buttons inherited the profile's 150). JN0 / JN100 / JN200 worn in a lit
    # room: order 0 ~= 100 < 150 < 200 ("me mueve de lugar mucho menos" at 0, "igual parece a
    # la vez anterior" at 100, "la deriva es claramente mayor ahora" at 200). Reversible: 0 felt
    # the same, 150/200 worse; 100 keeps 0's gain without its near-field cockpit jitter. The
    # wearer had not chosen between 0 and 100 when this was written. Keep in step with the
    # profile: this dict IS the profile as far as the buttons are concerned.
    "SLAM_PRED_NECK_ARM_MM": "100",
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
    # (2026-08-28 ~18:27 -03: JA and JM moved from J.toml to P2.toml -- JP is the new base after
    # its wearer test, and JH (horizon 100) was refuted worn: more jitter, larger excursions.
    # Time corrected from the session's own file mtimes; the original comment said ~00:50.)
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
     "La pila completa: config P2 (J barato) + horizonte 50 ms (JH/100 ms fue refutado) + JA (correccion promediada 3 anchors) + JM (stamp a mitad de exposicion). Para probar DESPUES de JP/JH/JA/JM por separado: si alguno empeora solo, aca se mezcla y no se sabe cual fue."),
    # ---- round 6 (2026-08-28 ~18:45 -03; time corrected from the session's own file mtimes,
    # the original comment said ~01:30): JA kept (jitter), JM kept (excursions), JH refuted.
    # 0020's age_in/age_out split the pose age: transport 11 ms flat, Basalt in->out p50 59 /
    # p90 170 / p99 265 with the frontend at 29/39/53 -- the 2+2 queue slots are the tail.
    # JQ = JX + both live queues at depth 1 (Basalt patch 0021, VIT_QUEUE_DEPTH).
    ("JQ", "JX + colas de profundidad 1 (menos edad de pose)",
     JQ_ENV,
     "LATENCIA LATERAL. JX + VIT_QUEUE_DEPTH=1 (patch Basalt 0021): las dos colas vivas (imagen->frontend y frontend->backend) pasan de 2 a 1 slot. Medido en JM: transporte 11 ms fijo, pero exposicion->pose p50 59 / p90 170 / p99 265 ms con el frontend en 29/39/53 -- el resto es cola (4 frames x 33 ms tras un frame lento del backend). Con 1 slot la edad queda acotada a ~2 frames + proceso; se descarta un frame solo cuando hay un atasco real (el IMU cubre). Si baja la demora lateral sin sumar jitter, queda."),
    # ---- round 7 (2026-08-28 ~19:40 -03, NEXT-STEP "START HERE" + docs/80 "JQ"): JQ is the
    # profile; the residual is the rotation-onset displacement ("yaw/pitch first moves you off
    # the seat, then it settles"). Offline the raw VIO does not do it (yaw net 5 cm on the
    # recording), so it is either (a) the prediction layer -- the position freeze +
    # SLAM_PRED_NECK_ARM_MM 150 model during the ~75 ms the anchor is stale (a wrong arm length
    # or centre shows up exactly as "moves then settles") -- or (b) the timing shortfall the
    # sweep left (optimum -5..-10 ms vs the ~2.5 ms the mid-exposure stamp recovers -> start_ts
    # lags exposure start). Cheap to separate: RQ = one recording under JQ's env with R's
    # protocol, replayed by the agent at 0 / -5 / -10 ms (scripts/euroc-shift.py, being added
    # in parallel, + replay-basalt-variants.py + replay-phase-slice.py). Raw trajectory clean
    # while the wearer felt the displacement -> (a): JN0/JN100/JN200 A/B the neck arm against
    # the profile's 150 (= JQ itself, the control). -5 ms still wins offline -> (b): JQT. All
    # env-only on top of JQ_ENV; the profile itself stays JQ.
    ("RQ", "GRABAR protocolo yaw (JQ + EuRoC 3 min)",
     {**JQ_ENV, "EUROC_RECORD": "1", "EUROC_RECORD_PATH": "/mnt/vrtmp/euroc-yaw2",
      "VIT_DUMP_CALIB": f"{HOME}/vr/logs/calib-g2-yaw2.json"},
     "LA GRABACION 2 (bajo JQ). Mismo protocolo que R (segui la voz de yaw-protocol-voice.py: 30 s quieto, 10 giros rapidos izq-der, 10 arriba-abajo, 10 inclinaciones, 60 s de juego libre), pero grabada con el perfil JQ completo, asi los stamps de camara ya vienen a mitad de exposicion (0101) y la grabacion mide lo que el casco usa hoy. EuRoC en PNG a /mnt/vrtmp/euroc-yaw2_<fecha> + volcado de calibracion. Despues el agente la replayea a 0 / -5 / -10 ms con scripts/euroc-shift.py + replay-basalt-variants.py + replay-phase-slice.py, sin casco: si la trayectoria cruda sale limpia mientras vos sentiste el 'te saca del asiento', es la prediccion (probar JN0/JN100/JN200); si -5 ms sigue ganando, es el timing (probar JQT). ~1.4 GB/min en tmpfs (~5 GB el protocolo; 14 GB si queda 10 min, docs/80): copiar el dataset a ~/vr/logs/euroc/ ANTES de cualquier reboot; cerrar el juego al terminar. RESULTADO 2026-08-29 06:08: GRABADA (6.8 GB, 0 trips, archivada en /mnt/videos/euroc/euroc-yaw2_20260829060819); replay a 0 ms limpio, a -5 ms divergio desde t=0 (dataset sin recortar, en diagnostico) -- ver docs/80."),
    ("JN0", "JQ + brazo de cuello 0 mm",
     {**JQ_ENV, "SLAM_PRED_NECK_ARM_MM": "0"},
     "PREDICCION (hipotesis a). JQ con SLAM_PRED_NECK_ARM_MM=0: sin modelo de cuello, la posicion queda congelada a secas durante los ~75 ms en que el anchor esta viejo. El perfil usaba 150 (= JQ, el control de esta ronda). Si el 'te saca del asiento y despues se acomoda' al girar desaparece o cambia claramente, el desplazamiento es del modelo de cuello y no del VIO. RESULTADO 2026-08-29 06:14: 'me mueve de lugar mucho menos', pero 'un poco de jittering al mirar la cabina de cerca'; 0 trips. Orden final 0 ~= 100 < 150 < 200; el perfil paso a 100."),
    ("JN100", "JQ + brazo de cuello 100 mm",
     {**JQ_ENV, "SLAM_PRED_NECK_ARM_MM": "100"},
     "PREDICCION (hipotesis a). JQ con el brazo de cuello en 100 mm en vez de 150: el ojo congelado barre un arco mas corto al girar. Comparar contra JQ (150) y JN0 (0) en el mismo giro. RESULTADO 2026-08-29 06:19: 'igual parece a la vez anterior' / 'muy similar, avanza' (= JN0); 0 trips. ES EL PERFIL DESDE 2026-08-29 (SLAM_PRED_NECK_ARM_MM=100, reversible)."),
    ("JN200", "JQ + brazo de cuello 200 mm",
     {**JQ_ENV, "SLAM_PRED_NECK_ARM_MM": "200"},
     "PREDICCION (hipotesis a). JQ con el brazo de cuello en 200 mm: arco mas largo. Si 200 se siente PEOR que 150 y 100 mejor, el arco esta sobreestimado; si al reves, subestimado; si los tres se sienten iguales, el modelo de cuello no es la causa y queda la hipotesis (b) = JQT. RESULTADO 2026-08-29 06:32: 'la deriva es claramente mayor ahora' (peor que 150); 0 trips. Arco sobreestimado: hipotesis (a) confirmada, 150 era demasiado."),
    ("JQT", "JQ + camaras -5 ms encima del stamp mid-exposure",
     {**JQ_ENV, "VIT_CAM_TIME_OFFSET_NS": "-5000000"},
     "TIMING (hipotesis b). JQ + VIT_CAM_TIME_OFFSET_NS=-5 ms (patch Basalt 0017) ENCIMA del stamp a mitad de exposicion (0101): el sweep offline queria -5..-10 ms y el stamp mid-exposure recupera solo ~2.5, o sea que start_ts llega tarde respecto del inicio real de la exposicion. JT era -7 fijo sobre J SIN el stamp mid-exposure y no se sintio; esto es -5 ademas del stamp. Probar solo si la grabacion RQ replayeada a -5 ms sigue ganando contra 0. Comparar contra JQ. ESTADO 2026-08-29: NO se corrio -- el replay de RQ a -5 ms divergio desde t=0 (dataset sin recortar, en diagnostico); decision diferida a un replay limpio (docs/80)."),
    # R = the ONE wearer session the offline pipeline needs: F's config + EUROC_RECORD (PNG,
    # lossless -- JPG changes the features) + the live calibration dump. ~3 min following
    # yaw-protocol-voice.py's spoken script. Afterwards replay-basalt-variants.py replays the
    # recording through base x2 + G/H/I/J in ~15 min with no headset. EUROC_RECORD_PATH is a
    # PREFIX (the recorder appends _datetime, t_euroc_recorder.cpp:408-414).
    ("R", "GRABAR protocolo yaw (F + EuRoC 3 min)",
     {"SLAM_PRED_POSITION_HORIZON_MS": "50", "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
      "SLAM_CORRECTION_SPREAD_MS": "25", "EUROC_RECORD": "1",
      "EUROC_RECORD_PATH": "/mnt/vrtmp/euroc-yaw", "VIT_DUMP_CALIB": f"{HOME}/vr/logs/calib-g2-yaw.json"},
     "LA GRABACION. Config F (A + spread 25) + grabacion EuRoC en PNG a /mnt/vrtmp/euroc-yaw_<fecha> + volcado de calibracion. Ponete el casco, arranca Aircar, y segui la voz de yaw-protocol-voice.py (30 s quieto, 10 giros rapidos izq-der, 10 arriba-abajo, 10 inclinaciones, 60 s de juego libre). Despues el agente replayea la grabacion contra todas las configs de backend sin casco. ~1.4 GB/min en tmpfs (~5 GB el protocolo; 14 GB si queda 10 min, docs/80); cerrar el juego al terminar."),
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

# Auto-standby opt-in + timeout (2026-09-04) -- read by rig_telemetry.presence_settings(),
# written here. Same per-box conf file jack-in-wayland.sh sources at launch
# (WMR_USER_PRESENCE / WMR_USER_PRESENCE_SCREENOFF_MS), so a change here only takes effect
# on the next 'jack-in down' + 'up', never live -- Monado caches the env var on first read.
PRESENCE_CONF_FILE = f"{HOME}/vr/presence.conf"
PRESENCE_SCREENOFF_MAX_MS = 1800000  # 30 min ceiling

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
            "# first read). Ships PRESENCE_ENABLE=0 by default: the RESTORE/re-donning direction\n"
            "# of this feature has not yet been live-validated with a real wearer (only the\n"
            "# blank direction was, 2026-09-04) -- don't flip this on for a real session without\n"
            "# knowing that.\n"
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
  /* Same specificity gotcha the .fault-dot[hidden] rule below already documents: this
     class sets its own `display:inline-flex`, a normal author rule, which always wins
     over the browser's normal UA `[hidden]{display:none}` regardless of selector
     specificity (author origin beats user-agent origin). Needed for #dot-audio
     (2026-09-05, audio UI hidden at the user's request -- see AUDIO_UI_HIDDEN below). */
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
  .camera-thumb { position:relative; }
  .camera-thumb img { width:100%; border-radius:4px; background:var(--bg); display:block; }
  .camera-thumb .camera-label { position:absolute; top:2px; left:4px; font-family:var(--font-mono);
    font-size:10px; color:#fff; text-shadow:0 0 3px #000, 0 0 3px #000; }

  /* ---- Vitals (2026-09-05): a technician's TREND view of the live session -- FPS,
     HMD temp, camera dropped-frame rate -- explicitly NOT a log/table (the user's own
     framing: "no como log, sino como un flow prolijo"). Hand-rolled <canvas> sparklines,
     vanilla JS, no charting library (this kiosk has no guaranteed internet -- same
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
     pmadminka_rework's admin.css (.live/.usage classes) -- the container paints --line
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
  <h1 class="wordmark"><span data-i18n="h1">iashur</span><small data-i18n="h1_sub">HP Reverb G2 lab status</small></h1>
  <div class="status-strip" id="status-dots">
    <span class="status-dot" id="dot-session"><span data-i18n="dot_session">SESSION</span></span>
    <!-- Audio UI hidden at the user's request (2026-09-05) -- audio_status()/the
         /api/audio-outputs endpoint/hmd-audio.sh are all left working underneath,
         only this dot is not rendered. See AUDIO_UI note near renderAudioDevices(). -->
    <span class="status-dot" id="dot-audio" hidden><span data-i18n="dot_audio">AUDIO</span></span>
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
    <!-- Audio outputs card: HIDDEN at the user's request (2026-09-05) -- audio_status(),
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
      <!-- Hidden with the rest of the audio UI (2026-09-05) -- not deleted, the string stays
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
       live, so per docs/87's own tiering this is access-panel (dense/collapsed), not
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
    cc_save_btn: "Save user", cc_fixed: "Fixed (not changeable on this headset)", cc_lang: "language",
    cc_edit_profile: "edit profile",
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
    cc_save_btn: "Guardar usuario", cc_fixed: "Fijo (no modificable en este casco)", cc_lang: "idioma",
    cc_edit_profile: "editar perfil",
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
    cc_save_btn: "Сохранить пользователя", cc_fixed: "Фиксировано (нельзя изменить на этой гарнитуре)", cc_lang: "язык",
    cc_edit_profile: "редактировать профиль",
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
// Audio UI hidden at the user's request (2026-09-05): these 3 buttons were already
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
      // 2026-09-02: these notes are internal engineering history (often 100-300+ words per
      // title) and were being dumped on the card in full -- exactly the "mucha info demas"
      // the user flagged. Show a short first-sentence preview always, hide the rest behind a
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
// instant feedback while dragging. Persisted per-browser in localStorage (this is a shared booth
// page with no per-user account system for camera preview prefs, unlike the headset brightness
// gain which IS saved per active user profile via /api/brightness -- separate concern, see the
// user's own framing: "uno para web, uno para casco proximamente").
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
// session, explicitly NOT a raw log/table (the user's own framing: "no como log, sino
// como un flow prolijo"). No charting library: this kiosk has no guaranteed internet
// (same reasoning docs/87 already used for zero web fonts), and 3 scalar time series is
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
    // actual session (docs/22, T048/T049). Only treat these as alarming
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
    const pm = d.pmadminka || {};
    const pmCls = pm.attached ? 'warn' : 'dim';
    const pmLabel = pm.attached ? t('pm_attached') : t('pm_standalone');
    const pmBtnLabel = pm.attached ? t('pm_detach_btn') : t('pm_attach_btn');
    const pmRow = `<div class="row"><span>${t('pm_row_label')}</span><span class="${pmCls}">${pmLabel}
      <button onclick="pmToggle(${!!pm.attached})" style="margin-left:8px;padding:2px 8px;font-size:12px">${pmBtnLabel}</button></span></div>`;
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
      <div class="row"><span>audio route</span><span class="status-dot ${audioCls}"></span></div>
    `;
    // Master status-strip dots (header row, unchanged): the true at-a-glance read, one
    // level above even the session card -- SESSION mirrors the state row above; AUDIO
    // mirrors audioCls; HARDWARE folds USB/display/coredump faults into one dot so a
    // real problem is visible without opening any tab; HUB mirrors the pmadminka attach
    // state (worth a glance before every demo, per docs/86).
    const usbFault = d.usb.present_count < d.usb.total;
    const drmFault = Object.entries(d.drm).some(([, s]) => s === 'disconnected' && sessionActive);
    const hwFault = usbFault || drmFault || d.coredumps.count > 0;
    document.getElementById('dot-session').className = 'status-dot ' + (sessionActive ? 'ok' : 'dim');
    document.getElementById('dot-audio').className = 'status-dot ' + audioCls;
    document.getElementById('dot-hw').className = 'status-dot ' + (hwFault ? 'bad' : 'ok');
    document.getElementById('dot-hub').className = 'status-dot ' + (pm.attached ? 'warn' : 'dim');

    // ---- Nameplate strip (2026-09-05, always visible, not a tab): repo/uptime/sunshine
    // + the ONE pmadminka attach/detach control on the page. ----
    document.getElementById('nameplate-strip').innerHTML = `
      <span><b>REPO</b>${(d.repo.head||'?').split(' ')[0]} <span class="${d.repo.dirty?'warn':'ok'}">${d.repo.dirty?'· dirty':'· clean'}</span></span>
      <span><b>UPTIME</b>${d.uptime || '?'}</span>
      <span><b>SUNSHINE</b><span class="${d.sunshine?'ok':'dim'}">${d.sunshine ? 'active' : 'inactive'}</span></span>
      <span><b>HUB</b><span class="${pmCls}">${pmLabel}</span>
        <button onclick="pmToggle(${!!pm.attached})">${pmBtnLabel}</button></span>
    `;

    // ---- Instrument bank tabs: HEADSET/GPU/CPU, tick() writes into all three panels'
    // DOM every cycle regardless of which is visible (same as the old collapsed
    // <details> content always did) -- pure attribute toggling, not a re-fetch, picks
    // which one is actually shown (see selectTab()). ----
    document.getElementById('grid-headset').innerHTML = `
      <div class="card"><h2>Tracking mode</h2>${trackingRow}</div>
      <div class="card"><h2>Controllers</h2>${controllersRow}</div>
      <div class="card"><h2>Audio route</h2>${audioRow}</div>
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
        <div class="dim" style="font-size:11px;margin-top:6px">umbral provisional -- ok &lt;75&deg;C, warn 75-88&deg;C, bad &ge;88&deg;C (Ryzen 5 5600X ~90&deg;C Tjmax) -- sin validar bajo una sesión 6dof real, revisar antes del próximo demo day</div>
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
    try { localStorage.setItem('iashur-dashboard-tab', id); } catch(e) {}
  }
}
function initTabs() {
  let initial = 'headset';
  try { initial = localStorage.getItem('iashur-dashboard-tab') || 'headset'; } catch(e) {}
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
             oninput="document.getElementById('uc-bri-v').textContent=(+this.value).toFixed(2)+'x'"
             onchange="setBrightness(this.value)" style="width:150px">
      <span id="uc-bri-v" class="ok">${gain}x</span>
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
  fetch('/api/user/save', {method:'POST', body: JSON.stringify({name:n, height_m:1.7, dof:'3dof', brightness:1.0, mapping:'', notes:'', lang:currentLang, make_active:true})}).then(()=>refreshUserCenter());
}
async function setBrightness(g) { await fetch('/api/brightness?gain='+encodeURIComponent(g), {method:'POST'}); }
async function userSave() {
  const name = document.getElementById('active-user').value;
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
        elif self.path.startswith("/api/camera") and self.path.endswith(".jpg"):
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
