"""rig_telemetry.py -- small telemetry helpers shared between pmadminka-agent.py's
heartbeat and status-dashboard.py's :8765 page (2026-08-23), so the two never drift
into reporting the same fact two different ways. Same sharing pattern this directory
already uses for wmr_usb_ids.py and gui_env.py.

No CLI, no side effects on import -- just functions.
"""
import json
import os
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return f"ERROR: {e}", -1


def machine_specs():
    """CPU/GPU/RAM identity -- static, from machine-specs.sh --json (docs/12-g2-protocol.md's
    sibling for the HOST rather than the headset; see that script's own header, T163)."""
    out, rc = run([os.path.join(SCRIPT_DIR, "machine-specs.sh"), "--json"], timeout=10)
    if rc != 0:
        return {}
    try:
        return json.loads(out)
    except Exception:
        return {}


def gpu_telemetry():
    """Live (util%, watts, temp) -- None triple if nvidia-smi is unavailable."""
    out, rc = run([
        "nvidia-smi",
        "--query-gpu=utilization.gpu,power.draw,temperature.gpu",
        "--format=csv,noheader,nounits",
    ])
    if rc != 0:
        return None, None, None
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
    # --user, not system: Sunshine runs as a systemd --user unit
    # (app-dev.lizardbyte.app.Sunshine.service, aliased to sunshine.service). Without
    # --user this silently queries the wrong systemd instance and always reports
    # inactive regardless of the real state (caught live 2026-08-23, T246 follow-up --
    # status-dashboard.py showed sunshine:false while `systemctl --user status
    # sunshine` showed it running for 8+ minutes).
    out, rc = run(["systemctl", "--user", "is-active", "sunshine"])
    return rc == 0 and out == "active"


def power_mode():
    """vr-power-watchdog.py's last-set mode ("saver"/"performance"). None if that
    service isn't installed/running yet (no file), not an error -- filter it out
    like every other optional field rather than reporting it as a fault."""
    try:
        with open("/run/vr-power-mode") as f:
            return f.read().strip() or None
    except OSError:
        return None


def monado_pid(name="monado-service"):
    """Pid of the running monado-service, or None. `pgrep -x` (exact process name, the
    convention jack-in-wayland.sh's teardown already uses), NOT `-f`: -f scans every
    process's full command line, so a `bash -c '... pgrep -x monado-service ...'` wait-loop,
    an ssh wrapper or a log tail matched too -- that is how demo-recorder.py kept sampling
    for 22.5 h after the 2026-08-27 J/JT sessions, and how a dashboard could show the
    service "running" with no headset session at all (NEXT-STEP.md 2026-08-28 ~19:45 block;
    demo-recorder.py's docstring). -n = newest match: if an orphan from a timed-out launch
    survived, the session just brought up is the newer one. `name` is demo-recorder.py's
    DEMO_RECORDER_WATCH_COMM test seam; comm is 15 chars max."""
    out, rc = run(["pgrep", "-n", "-x", name])
    if rc != 0 or not out:
        return None
    try:
        return int(out.splitlines()[0])
    except ValueError:
        return None


def tracking_mode(pid=None):
    """"3dof" / "6dof" / "ctrl" / None (no live session) -- derived from the same
    WMR_SLAM/WMR_CAMERAS env vars jack-in-wayland.sh sets per mode (see its header:
    6dof -> WMR_SLAM=1, ctrl -> WMR_SLAM=0 WMR_CAMERAS=1, 3dof -> neither set),
    read straight from monado-service's own environ -- the same source of truth
    vr-cockpit.py's gather_calibration() already reads, not a separate guess."""
    if pid is None:
        pid = monado_pid()
    if pid is None:
        return None
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    env = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    if env.get("WMR_SLAM") == "1":
        return "6dof"
    if env.get("WMR_CAMERAS") == "1":
        return "ctrl"
    return "3dof"
