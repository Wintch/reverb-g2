"""rig_telemetry.py -- small telemetry helpers shared between pmadminka-agent.py's
heartbeat and status-dashboard.py's :8765 page (2026-08-23), so the two never drift
into reporting the same fact two different ways. Same sharing pattern this directory
already uses for wmr_usb_ids.py and gui_env.py.

No CLI, no side effects on import -- just functions.
"""
import json
import os
import subprocess
import time
from pathlib import Path

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


def hmd_temperature():
    """WMR driver's HMD IMU temperature snapshot (~/vr/hmd-temperature.json, written by
    wmr_hmd.c's hololens_sensors_decode_packet() roughly once/second -- monado commit
    d1314913f's raw-register decode, plus the dashboard-snapshot follow-up, 2026-09-04).
    None if the file doesn't exist or fails to parse -- most of the time that just means
    no monado session has ever written one yet on this box, not an error.

    celsius_est is a datasheet-formula ESTIMATE (ICM-20602: raw/326.8 + 25), never
    confirmed live against this specific unit -- keep the "_est" name and say so
    wherever this surfaces (see the dashboard card's caption). Stale data is NOT hidden:
    `stale` (age_s > 10) is reported alongside the last-known numbers so a caller can
    show "last seen Ns ago" instead of nothing.
    """
    path = Path.home() / "vr" / "hmd-temperature.json"
    try:
        raw = json.loads(path.read_text())
        regs = [int(raw[f"t{i}"]) for i in range(4)]
        ts = float(raw["ts"])
    except Exception:
        return None
    age_s = time.time() - ts
    return {
        "raw": regs,
        "celsius_est": [round(v / 326.8 + 25, 1) for v in regs],
        "age_s": round(age_s, 1),
        "stale": age_s > 10,
    }


def presence_settings():
    """~/vr/presence.conf -- the auto-standby opt-in + timeout, adjustable from the
    dashboard (status-dashboard.py's /api/presence/save). Same trivial KEY=VALUE parser
    style as vr-power-setup.sh's load_power_conf() (skip blank/# lines, split on the
    first '='), ported to Python so the shell launcher and this dashboard can never
    disagree about the format. Defaults to disabled/0 if the file is missing or
    unparseable -- the same fail-safe default presence.conf itself ships with."""
    result = {"enable": False, "screenoff_ms": 0}
    path = Path.home() / "vr" / "presence.conf"
    try:
        text = path.read_text()
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key == "PRESENCE_ENABLE":
            result["enable"] = val == "1"
        elif key == "PRESENCE_SCREENOFF_MS":
            try:
                result["screenoff_ms"] = int(val)
            except ValueError:
                pass
    return result


_cpu_prev = {"ts": None, "lines": None}


def _read_proc_stat_cpu_lines():
    """{'cpu0': (user,nice,system,idle,iowait,irq,softirq,steal,guest,guest_nice), ...} --
    one tuple per logical core (the aggregate 'cpu' line is skipped, only 'cpuN' lines
    are kept). Plain /proc/stat read, no subprocess."""
    lines = {}
    try:
        with open("/proc/stat") as f:
            for line in f:
                if not line.startswith("cpu"):
                    break
                parts = line.split()
                name = parts[0]
                if name == "cpu":
                    continue  # aggregate line -- per-core only
                try:
                    lines[name] = tuple(int(x) for x in parts[1:])
                except ValueError:
                    continue
    except OSError:
        return {}
    return lines


def cpu_telemetry():
    """Live CPU load, per-core utilisation and package temperature for the dashboard's
    CPU tab (2026-09-05) -- before this, the only CPU fact anywhere was the static
    cpu.model/cpu.cores string from machine_specs(), nothing live to actually "tune
    performance one at a time" against.

    Cheap by construction, safe to poll every tick (wearer session or not, see
    feedback_no_heavy_analysis_during_wearer_sessions -- this is a few-KB text read
    plus O(cores) arithmetic, nowhere near that incident's 609 MB/awk scale):
      - load1/load5/load15: os.getloadavg() (stdlib, zero subprocess).
      - per_core_pct: diffs two /proc/stat samples. One extra module-level cache
        (_cpu_prev), parallel to this file's other per-call caches -- the FIRST call
        this process ever makes has nothing to diff against, so per_core_pct is None
        for that one tick (the caller renders "collecting...", same honesty already
        used for a stale camera-preview frame).
      - temp_c/temp_source: `sensors -j`, first "Tctl" field found under ANY adapter
        (fallback "Tdie" if no Tctl key exists anywhere) -- deliberately NOT hardcoded
        to a specific chip/adapter name. This repo already got burned once hardcoding a
        hardware identifier that later changed (the DP-1->DP-3 connector move after the
        2026-09-03 GPU swap); same generic-lookup discipline here. None/no source if
        lm-sensors isn't installed or nothing recognizable is found.

    Thresholds (applied by the caller, not here): ok <75C, warn 75-88C, bad >=88C --
    grounded in the Ryzen 5 5600X's documented ~90C Tjmax/throttle point. PLACEHOLDER:
    not yet validated against this box under a real sustained 6dof session -- re-check
    before the next demo day.
    """
    global _cpu_prev
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = None

    cur_lines = _read_proc_stat_cpu_lines()
    per_core_pct = None
    prev_lines = _cpu_prev["lines"]
    if prev_lines and cur_lines:
        pct = []
        ok = True
        for name in sorted(cur_lines, key=lambda n: int(n[3:])):
            prev = prev_lines.get(name)
            cur = cur_lines[name]
            if prev is None or len(prev) != len(cur):
                ok = False
                break
            deltas = [c - p for c, p in zip(cur, prev)]
            total = sum(deltas)
            idle = deltas[3] + (deltas[4] if len(deltas) > 4 else 0)  # idle + iowait
            pct.append(round(100.0 * (total - idle) / total, 1) if total > 0 else 0.0)
        if ok:
            per_core_pct = pct
    _cpu_prev = {"ts": time.monotonic(), "lines": cur_lines}

    temp_c, temp_source = None, None
    out, rc = run(["sensors", "-j"])
    if rc == 0 and out:
        try:
            data = json.loads(out)
        except Exception:
            data = {}
        for want in ("Tctl", "Tdie"):
            for adapter, chip in data.items():
                if not isinstance(chip, dict):
                    continue
                fields = chip.get(want)
                if not isinstance(fields, dict):
                    continue
                for fk, fv in fields.items():
                    if fk.endswith("_input"):
                        temp_c, temp_source = fv, f"{adapter}:{want}"
                        break
                if temp_c is not None:
                    break
            if temp_c is not None:
                break

    return {
        "load1": load1, "load5": load5, "load15": load15,
        "per_core_pct": per_core_pct,
        "temp_c": temp_c, "temp_source": temp_source,
    }


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


_LIBMONADO_PATH = None


def _libmonado_path():
    global _LIBMONADO_PATH
    if _LIBMONADO_PATH is None:
        vr_dir = os.path.join(os.path.expanduser("~"), "vr")
        _LIBMONADO_PATH = os.path.join(
            vr_dir, "monado", "build", "src", "xrt", "targets", "libmonado", "libmonado.so"
        )
    return _LIBMONADO_PATH


_controller_status_cache = {"pid": None, "result": None}


def controller_status():
    """{"left": bool, "right": bool} if monado-service answered, or {"error": str} if it
    couldn't be asked at all (not running, or libmonado missing) -- same libmonado
    mnd_root_create/mnd_root_get_device_from_role call controller-battery-check.py already
    uses (see that script's header), just presence instead of battery, so this and that
    script can never disagree about whether a controller is "there".

    NOTE: this is startup-time detection, not live -- Monado's WMR driver only probes
    controllers once at wmr_hmd_create() (see project_g2_controller_hotplug_gap), so a
    controller powered on AFTER the session started still reads False here. That is the
    correct, honest answer (it reflects what Monado itself knows), not a bug in this check:
    the fix for a False here is "power on + jack-in-wayland.sh down/up", not a dashboard
    refresh.

    Cached per monado-service PID (2026-09-04, docs/96 s14.5): since the answer can only
    change on a Monado restart (never mid-session, per the NOTE above), status-dashboard.py
    polling this every few seconds was opening/closing a fresh libmonado IPC client each
    time -- each mnd_root_create/mnd_root_destroy round-trip briefly stalls the compositor,
    felt by a wearer as a periodic ~10s hitch in any live VR session. Reusing the cached
    result for the same PID makes the real IPC call happen at most once per Monado session
    instead of once per poll.
    """
    import ctypes

    lib_path = _libmonado_path()
    if not os.path.exists(lib_path):
        return {"error": "libmonado.so not built"}
    pid = monado_pid()
    if pid is None:
        _controller_status_cache["pid"] = None
        _controller_status_cache["result"] = None
        return {"error": "monado-service not running"}
    if _controller_status_cache["pid"] == pid and _controller_status_cache["result"] is not None:
        return _controller_status_cache["result"]
    try:
        lib = ctypes.CDLL(lib_path)
        lib.mnd_root_create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        lib.mnd_root_create.restype = ctypes.c_int
        lib.mnd_root_destroy.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        lib.mnd_root_destroy.restype = None
        lib.mnd_root_get_device_from_role.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32),
        ]
        lib.mnd_root_get_device_from_role.restype = ctypes.c_int
    except OSError as e:
        return {"error": f"libmonado load failed: {e}"}

    root = ctypes.c_void_p()
    if lib.mnd_root_create(ctypes.byref(root)) != 0:
        return {"error": "couldn't connect to monado-service"}
    try:
        result = {}
        for hand in ("left", "right"):
            idx = ctypes.c_int32(-1)
            rc = lib.mnd_root_get_device_from_role(root, hand.encode(), ctypes.byref(idx))
            result[hand] = bool(rc == 0 and idx.value >= 0)
        # Only successful reads are cached -- a transient connect failure right at Monado
        # startup should be retried on the next poll, not stuck forever as an error.
        _controller_status_cache["pid"] = pid
        _controller_status_cache["result"] = result
        return result
    finally:
        lib.mnd_root_destroy(ctypes.byref(root))
