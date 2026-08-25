#!/usr/bin/env python3
"""bench-launcher.py -- one controlled, monitored entry point for benchmarks and games
on this rig, built from today's (2026-08-23/24, T246 follow-ups) hard-won lessons
running Quake II RTX's power sweep and the Unigine Heaven/Superposition install by
hand. Every one of those lessons was a real, live mistake, not a hypothetical:

  - Heaven ended up launched TWICE (two windows at once) because nothing checked
    "is this already running?" first -- this script's lock file exists for that.
  - The first q2rtx-power-sweep.sh run happened in a root `su`/`sudo -i` shell, so
    Steam had no desktop session and every rep silently timed out.
  - A Heaven DX9 run showed Min FPS 9.6 against a 245 average with no way to tell
    "real engine hitch" from "first cold read off NVMe" apart until the Proton
    prefix was cache-warmed and re-measured.
  - Every result so far lived in a one-off CSV or a chat message -- no way to ask
    "did this driver update regress anything" without re-deriving it by hand.

  ./bench-launcher.py quake2
  ./bench-launcher.py heaven --api dx11
  ./bench-launcher.py aircar --tracking 6dof
  ./bench-launcher.py quake2 --gpu-limit 100      # controlled power sweep point
  ./bench-launcher.py heaven --api dx9 --force-kill   # kill a stuck prior instance first

Every run is one appended line in ~/vr/logs/bench-results.jsonl -- see RESULTS_FILE
below for the schema. That file, not this session's chat log, is what a future
"did X regress" question should be answered from.

KNOWN LIMITATION, stated plainly rather than glossed over: Heaven's (and
Superposition's) free edition has no CLI/XML result export -- confirmed live this
session, an XML-driven CLI call on superposition_cli.exe exited 0 with zero log/result
output (looks license-gated, not confirmed which tier unlocks it). So "heaven" is
CLI-driven for launch and API selection (no dropdown-clicking, which is what actually
wasted time this session -- a resolution-dropdown misclick), but still needs one
xdotool click on the fixed "Benchmark" menu position to start the timed run, and ends
in a screenshot of the results dialog for a human (or the agent driving this script)
to read the score off of. It is not unattended end to end. quake2 and aircar are.
"""
import argparse
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import gui_env  # noqa: E402
import rig_telemetry  # noqa: E402

VR = Path.home() / "vr"
if not VR.is_dir():
    VR = SCRIPT_DIR.parent
LOCK_FILE = Path(f"/run/user/{os.getuid()}/bench-launcher.lock")
RESULTS_FILE = VR / "logs" / "bench-results.jsonl"
WATCHDOG_UNIT = "vr-power-watchdog.service"


def _load_game_stop():
    path = SCRIPT_DIR / "game-stop.py"
    spec = importlib.util.spec_from_file_location("game_stop_lib", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


game_stop = _load_game_stop()

TARGETS = {
    "quake2": {
        "kind": "steam",
        "appid": "1089130",
        "launch_args": ["+set", "logfile", "2", "+timedemo", "1", "+demo", "q2demo1"],
        "result": {
            "type": "log",
            "path": "~/.local/share/quake2rtx/baseq2/logs/console.log",
            "pattern": re.compile(r"(\d+) frames, ([\d.]+) seconds: ([\d.]+) fps"),
            "timeout_s": 60,
        },
    },
    "heaven": {
        "kind": "proton-standalone",
        "prefix": "~/vr/proton-prefixes/unigine",
        # relative to the prefix root
        "exe_rel": "pfx/drive_c/Program Files (x86)/Unigine/Heaven Benchmark 4.0/bin/Heaven.exe",
        "fixed_args": [
            "-project_name", "Heaven", "-data_path", "../",
            "-engine_config", "../data/heaven_4.0.cfg",
            "-system_script", "heaven/unigine.cpp", "-sound_app", "openal",
            "-video_multisample", "0", "-video_fullscreen", "1", "-video_mode", "6",  # 1920x1080
            "-extern_define", ",RELEASE,LANGUAGE_EN,QUALITY_HIGH,TESSELLATION_DISABLED",
            "-extern_plugin", ",GPUMonitor",
        ],
        # video_app value per --api choice
        "api_map": {"dx9": "direct3d9", "dx11": "direct3d11", "opengl": "opengl"},
        "process_match": "Heaven.exe",
        "result": {"type": "screenshot", "benchmark_wait_s": 200},
    },
    "aircar": {
        "kind": "vr-game",
        "appid": "1073390",
        "result": {"type": "app-fps", "window_s": 20, "repeats": 3},
    },
    "cyberpilot": {
        # Wolfenstein: Cyberpilot (docs/23: constellation ON, both controllers
        # registered -- run with --tracking ctrl, not the aircar-style default
        # 3dof). ~15G install, added to the catalog 2026-08-25 specifically to
        # A/B vr-prewarm.sh's cache vs ram mode now that the 32G RAM upgrade
        # raised the tmpfs (10G->20G) and the ram-mode cap (12G->16G) enough for
        # this title to be size-eligible for the first time (docs/23:410).
        "kind": "vr-game",
        "appid": "1056970",
        "result": {"type": "app-fps", "window_s": 20, "repeats": 3},
    },
    "metro2033": {
        # Native Linux build (no Proton), same "steam" kind as quake2 -- Steam just
        # launches the bare ELF binary directly. The install has its own
        # benchmark.sh wrapping this exact invocation; -output_file/-close_on_finish
        # write a result file and exit on their own, no polling a growing log needed.
        "kind": "steam",
        "appid": "286690",
        "launch_args": [
            "-benchmark", "benchmarks\\benchmark33", "-bench_runs", "2",
            "-output_file", "~/vr/logs/metro2033-bench-result.log", "-close_on_finish",
        ],
        "result": {
            "type": "file",
            "path": "~/vr/logs/metro2033-bench-result.log",
            "timeout_s": 240,
            # KNOWN GAP, confirmed live 2026-08-24: this file's min_fps/max_fps/frames
            # fields are broken placeholders (0.00 / 1000.00 / equal to total_time,
            # not a real per-frame count) -- only aver_fps and total_time are real.
            # No 1%-low from this path; get that from a separate MangoHud pass
            # (same fix already applied for Cyberpunk, docs/70) if the lows matter.
        },
    },
}


def expand(p):
    return os.path.expanduser(p)


def log(msg):
    print(f"[bench-launcher] {msg}", flush=True)


# ---------------------------------------------------------------- lock / no-duplicate

def read_lock():
    try:
        return json.loads(LOCK_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def lock_is_live(lock):
    return bool(lock) and Path(f"/proc/{lock['pid']}").exists()


def write_lock(target, pid):
    LOCK_FILE.write_text(json.dumps({"target": target, "pid": pid, "started_at": time.time()}))


def release_lock():
    LOCK_FILE.unlink(missing_ok=True)


def check_no_duplicate(target, force_kill):
    """The direct fix for 2026-08-24's "Heaven launched twice" incident: never start
    a new run without first asking whether the lock says one is already live."""
    lock = read_lock()
    if not lock_is_live(lock):
        return
    if not force_kill:
        log(f"'{lock['target']}' looks already running (pid {lock['pid']}, "
            f"started {time.strftime('%H:%M:%S', time.localtime(lock['started_at']))}). "
            f"Pass --force-kill to stop it and proceed.")
        sys.exit(1)
    log(f"--force-kill: stopping the previous '{lock['target']}' run (pid {lock['pid']}) first.")
    # The lock's pid is the PREVIOUS bench-launcher.py process itself (it blocks for
    # the whole run), not the underlying game/benchmark process -- kill that directly
    # first so its own teardown can't race this one, THEN also run the target's normal
    # stop_target() as a fallback in case a SIGKILL below cut its own `finally` off
    # mid-cleanup and left the actual game/benchmark process still running.
    try:
        os.kill(lock["pid"], signal.SIGTERM)
        for _ in range(20):
            if not Path(f"/proc/{lock['pid']}").exists():
                break
            time.sleep(0.5)
        else:
            os.kill(lock["pid"], signal.SIGKILL)
    except ProcessLookupError:
        pass
    stop_target(TARGETS.get(lock["target"], {}))
    release_lock()


# ---------------------------------------------------------------------------- prewarm

def prewarm(spec, use_ram):
    t0 = time.time()
    kind = spec["kind"]
    if kind in ("steam", "vr-game"):
        cmd = [str(SCRIPT_DIR / "vr-prewarm.sh"), spec["appid"]]
        if use_ram:
            cmd += ["--mode", "ram"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        ok = r.returncode == 0
        if not ok:
            log(f"prewarm (vr-prewarm.sh) failed: {r.stderr.strip()[-300:]}")
        method = "ram" if use_ram else "cache"
    elif kind == "proton-standalone":
        prefix = expand(spec["prefix"])
        r = subprocess.run(["vmtouch", "-t", prefix], capture_output=True, text=True, timeout=180)
        ok = r.returncode == 0
        method = "cache"
    else:
        ok, method = True, "none"
    return {"method": method, "seconds": round(time.time() - t0, 1), "ok": ok}


# ------------------------------------------------------------------------ power mode

class PowerControl:
    """Default for `steam`/`vr-game` targets: leave vr-power-watchdog.service alone --
    realistic, "what a real session actually gets" (it correctly sees these and pins
    performance on its own). `proton-standalone` targets are invisible to it (see
    __init__ below) so they're always bracketed with a plain --apply, watchdog-off, by
    default -- not just on an explicit --gpu-limit. Either way, the watchdog is ALWAYS
    restarted on the way out, mirroring q2rtx-power-sweep.sh's trap -- this is the
    piece meant to stop every future sweep script from re-deriving that by hand. Both
    sudo calls are pre-granted, narrow NOPASSWD entries -- see
    /etc/sudoers.d/reverb-g2-power (docs/68)."""

    def __init__(self, gpu_limit_pct, kind):
        self.gpu_limit_pct = gpu_limit_pct
        # proton-standalone is invisible to vr-power-watchdog.py (docs/69's KNOWN GAP --
        # it only recognizes processes carrying Steam's own SteamAppId/
        # STEAM_COMPAT_DATA_PATH env vars), so leaving the watchdog alone would silently
        # cap a Heaven/Superposition run at the idle `saver` floor for its ENTIRE
        # duration -- not a missing nice-to-have, a wrong number. Bracket it with a
        # plain --apply by default (q2rtx-power-sweep.sh's documented workaround, now
        # automatic here) unless a specific --gpu-limit sweep point was requested instead.
        self.needs_bracket = kind == "proton-standalone" or gpu_limit_pct is not None
        self.watchdog_paused = False

    def __enter__(self):
        if self.needs_bracket:
            subprocess.run(["sudo", "systemctl", "stop", WATCHDOG_UNIT], timeout=15)
            self.watchdog_paused = True
            flag_args = ["--gpu-limit", str(self.gpu_limit_pct)] if self.gpu_limit_pct is not None else ["--apply"]
            r = subprocess.run(
                ["sudo", str(SCRIPT_DIR / "vr-power-setup.sh"), *flag_args],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                log(f"{' '.join(flag_args)} failed: {r.stderr.strip()[-300:]}")
        return self

    def __exit__(self, *exc):
        if self.watchdog_paused:
            subprocess.run(["sudo", "systemctl", "start", WATCHDOG_UNIT], timeout=15)
        return False

    def snapshot(self):
        """Never trust the requested value -- record what nvidia-smi actually reports
        right now, and whatever the watchdog's own mode file currently says.

        Caller must call this AFTER the run, not before: vr-power-watchdog.py is
        reactive with a ~10-16s lag (poll every 10s + its own settle time), so a fast
        target like quake2's ~8.5s timedemo can finish entirely inside that lag
        window -- a pre-launch snapshot would then claim `saver`/100W for a run that
        actually played out at `performance`/175W once the watchdog caught up mid- or
        post-run. Caught live 2026-08-24: the first real quake2 run through this
        script logged measured_gpu_power_limit_w=100.0 (the pre-launch value) next to
        a 74.5 fps result -- a number this rig's own power sweep (docs/48) had
        already shown only happens at ~175W+, not 100W. The pre-launch snapshot was
        simply wrong for that row, not a real reading of what the GPU ran at."""
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.limit", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        try:
            watts = float(out)
        except ValueError:
            watts = None
        mode = rig_telemetry.power_mode()
        return {"measured_gpu_power_limit_w": watts, "power_mode_at_launch": mode}


# ------------------------------------------------------------------------------ stop

def stop_target(spec):
    kind = spec.get("kind")
    if kind in ("steam", "vr-game"):
        appid = spec.get("appid")
        if appid:
            subprocess.run([sys.executable, str(SCRIPT_DIR / "game-stop.py"), "stop", appid],
                            capture_output=True, timeout=30)
    elif kind == "proton-standalone":
        match = spec.get("process_match")
        if match:
            r = subprocess.run(["pgrep", "-f", match], capture_output=True, text=True)
            for line in r.stdout.split():
                subprocess.run(["kill", line])
    if kind == "vr-game":
        subprocess.run([str(VR / "jack-in-wayland.sh"), "down"], capture_output=True, timeout=30)


# ---------------------------------------------------------------------------- launch

def launch_steam(spec):
    # `steam -applaunch` hands these argv straight to the game binary, no shell in
    # between -- a literal "~" is never expanded by the engine either. Confirmed live
    # 2026-08-24: metro2033's -output_file ~/vr/... created a real directory named
    # "~" inside the game's own install dir instead of writing under $HOME.
    launch_args = [expand(a) if a.startswith("~/") else a for a in spec.get("launch_args", [])]
    subprocess.Popen(
        ["steam", "-applaunch", spec["appid"], *launch_args],
        env=gui_env.get(), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def launch_proton_standalone(spec, api):
    prefix = Path(expand(spec["prefix"]))
    exe = prefix / spec["exe_rel"]
    proton = Path.home() / ".steam/steam/steamapps/common/Proton - Experimental/proton"
    env = gui_env.get()
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = expand("~/.steam/steam")
    env["STEAM_COMPAT_DATA_PATH"] = str(prefix)
    video_app = spec["api_map"][api]
    args = [str(proton), "run", str(exe), "-video_app", video_app, *spec["fixed_args"]]
    subprocess.Popen(args, env=env, cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def launch_vr_game(spec, tracking, controllers):
    env = gui_env.get()
    env["U_PACING_APP_LOG"] = "debug"  # app-fps.sh needs this on the SERVICE, set before jack-in
    if controllers:
        # jack-in-wayland.sh's TRACKING enum can't express "6dof" (WMR_SLAM=1) and "ctrl"
        # (WMR_CAMERAS=1 + constellation) at once -- both env vars are still individually
        # overridable on top of any tracking mode (its own "for an A/B" comment), which is
        # what a title like Cyberpilot actually needs: SLAM head tracking AND controllers.
        # Found 2026-08-25 investigating a Cyberpilot instant-END_SESSION: it needs
        # controllers REGISTERED (physically powered on before monado-service starts, see
        # docs/03/T051) -- this flag does not power them on, it only stops the "ctrl" vs
        # "6dof" tradeoff from silently leaving constellation off.
        env["WMR_CAMERAS"] = "1"
        env["WMR_CONSTELLATION_CONTROLLERS"] = "1"
    r = subprocess.run([str(VR / "jack-in-wayland.sh"), "up", "1", tracking],
                        env=env, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        log(f"jack-in-wayland.sh failed:\n{r.stdout[-1500:]}\n{r.stderr[-500:]}")
        return False
    launch_steam(spec)
    return True


# --------------------------------------------------------------------------- result

def wait_for_log_result(spec):
    path = Path(expand(spec["path"]))
    pattern, timeout_s = spec["pattern"], spec["timeout_s"]
    before = 0
    if path.exists():
        before = sum(1 for _ in path.open(errors="replace"))
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(2)
        if not path.exists():
            continue
        lines = path.read_text(errors="replace").splitlines()
        for line in lines[before:]:
            m = pattern.search(line)
            if m:
                frames, seconds, fps = m.groups()
                return {"frames": int(frames), "seconds": float(seconds), "fps": float(fps),
                        "min_fps": None, "max_fps": None}  # gap: this log line has no min/max
    log(f"timed out after {timeout_s}s waiting for a result in {path}")
    return None


def wait_for_file_result(spec):
    """For targets whose own -output_file/-close_on_finish-style flags write a
    result file and exit on their own (metro2033) -- unlike wait_for_log_result
    there's no running process left to tell a stale prior file from a fresh one, so
    main() deletes this path before launching and its reappearance IS the
    completion signal, not a line pattern inside a growing log."""
    path = Path(expand(spec["path"]))
    timeout_s = spec["timeout_s"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            values = {}
            for line in path.read_text(errors="replace").splitlines():
                parts = line.split()
                if len(parts) == 2:
                    try:
                        values[parts[0]] = float(parts[1])
                    except ValueError:
                        pass
            return values or None
        time.sleep(2)
    log(f"timed out after {timeout_s}s waiting for {path}")
    return None


def wait_for_screenshot_result(spec, target):
    """Not unattended -- see the module docstring's KNOWN LIMITATION. Clicks the
    fixed 'Benchmark' menu position (top-left, stable across every run this session --
    unlike the settings dropdowns, which reflow based on current selection and are
    why the direct CLI args exist in the first place), waits out a fixed duration
    long enough for Heaven's real fly-through, then captures one screenshot of the
    results dialog. Timing is a known soft spot, not yet solid: this session's
    manual runs measured the fly-through anywhere from ~150s to ~260s depending on
    prior load, and a first automated pass with this fixed 200s wait landed back on
    the interactive free-fly view instead of the results dialog (screenshot showed a
    live FPS counter, no dialog) -- either the wait undershot that run's actual
    duration, or `xdotool search --name Heaven` picked a stale window handle.
    Re-running and comparing screenshots is how to tell which; not resolved yet."""
    time.sleep(8)  # let the window actually appear before searching for it
    out = subprocess.run(["xdotool", "search", "--name", "Heaven"], env=gui_env.get(),
                          capture_output=True, text=True, timeout=10).stdout.split()
    if not out:
        log("no Heaven window found to click Benchmark on")
        return None
    win = out[-1]  # the benchmark render window, not the (already-closed) launcher
    subprocess.run(["xdotool", "mousemove", "--window", win, "60", "17", "click", "1"],
                    env=gui_env.get(), timeout=10)
    log(f"benchmark running, waiting up to {spec['benchmark_wait_s']}s...")
    time.sleep(spec["benchmark_wait_s"])
    shot_dir = VR / "logs" / "bench-screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / f"{target}-{int(time.time())}.png"
    subprocess.run(["import", "-window", win, str(shot_path)], env=gui_env.get(), timeout=15)
    log(f"screenshot saved: {shot_path} -- read the score off it (Save/Close in the dialog if needed)")
    return {"screenshot": str(shot_path)}


def wait_for_app_fps_result(spec):
    r = subprocess.run(
        [str(SCRIPT_DIR / "app-fps.sh"), str(spec["window_s"]), str(spec["repeats"])],
        capture_output=True, text=True, timeout=(spec["window_s"] * spec["repeats"]) + 30,
    )
    fps_values = [float(m) for m in re.findall(r"=\s*([\d.]+)\s*fps", r.stdout)]
    if not fps_values:
        log(f"app-fps.sh produced no parseable fps lines:\n{r.stdout}\n{r.stderr}")
        return None
    return {"fps_windows": fps_values, "min_fps": min(fps_values),
            "max_fps": max(fps_values), "fps": round(sum(fps_values) / len(fps_values), 2)}


# ----------------------------------------------------------------------------- main

def git_commit():
    r = subprocess.run(["git", "-C", str(SCRIPT_DIR.parent), "rev-parse", "--short", "HEAD"],
                        capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else None


def append_result(row):
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_FILE.open("a") as f:
        f.write(json.dumps(row) + "\n")
    log(f"result logged -> {RESULTS_FILE}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", choices=sorted(TARGETS))
    ap.add_argument("--api", choices=["dx9", "dx11", "opengl"], default="dx11",
                     help="proton-standalone targets only (heaven)")
    ap.add_argument("--tracking", choices=["3dof", "6dof", "ctrl"], default="3dof",
                     help="vr-game targets only")
    ap.add_argument("--controllers", action="store_true",
                     help="vr-game targets only: force WMR_CAMERAS=1 WMR_CONSTELLATION_CONTROLLERS=1 "
                          "on top of --tracking (e.g. for --tracking 6dof + controllers together, "
                          "which the tracking enum alone can't express). Controllers must already "
                          "be powered on before the run -- this does not turn them on.")
    ap.add_argument("--gpu-limit", type=int, metavar="PCT",
                     help="pause the watchdog and pin GPU power to this %% of max for the run")
    ap.add_argument("--no-prewarm", action="store_true")
    ap.add_argument("--prewarm-ram", action="store_true", help="steam/vr-game targets only")
    ap.add_argument("--force-kill", action="store_true",
                     help="stop a previous run still holding the lock, instead of refusing")
    args = ap.parse_args()

    spec = TARGETS[args.target]
    check_no_duplicate(args.target, args.force_kill)

    prewarm_info = {"method": "skipped", "seconds": 0.0, "ok": True}
    if not args.no_prewarm:
        log("prewarming...")
        prewarm_info = prewarm(spec, args.prewarm_ram)

    result = None
    power_snapshot = {"measured_gpu_power_limit_w": None, "power_mode_at_launch": None}
    pid_for_lock = os.getpid()
    with PowerControl(args.gpu_limit, spec["kind"]) as power:
        try:
            write_lock(args.target, pid_for_lock)
            if spec["kind"] == "steam":
                log(f"launching {args.target} (steam appid {spec['appid']})...")
                rtype = spec["result"]["type"]
                if rtype == "file":
                    Path(expand(spec["result"]["path"])).unlink(missing_ok=True)
                launch_steam(spec)
                if rtype == "log":
                    result = wait_for_log_result(spec["result"])
                elif rtype == "file":
                    result = wait_for_file_result(spec["result"])
            elif spec["kind"] == "proton-standalone":
                log(f"launching {args.target} (Proton standalone, api={args.api})...")
                launch_proton_standalone(spec, args.api)
                result = wait_for_screenshot_result(spec["result"], args.target)
            elif spec["kind"] == "vr-game":
                log(f"launching {args.target} (VR game, tracking={args.tracking}, "
                    f"controllers={args.controllers})...")
                if launch_vr_game(spec, args.tracking, args.controllers):
                    time.sleep(10)  # let the app actually start rendering before sampling
                    result = wait_for_app_fps_result(spec["result"])
            # Taken after the run, not before -- see PowerControl.snapshot()'s own
            # docstring for why a pre-launch snapshot is actively wrong for fast targets.
            power_snapshot = power.snapshot()
        finally:
            log("tearing down...")
            stop_target(spec)
            release_lock()

    row = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "target": args.target,
        "config": {"api": args.api if spec["kind"] == "proton-standalone" else None,
                   "tracking": args.tracking if spec["kind"] == "vr-game" else None,
                   "controllers": args.controllers if spec["kind"] == "vr-game" else None,
                   "gpu_limit_pct": args.gpu_limit},
        "result": result,
        "prewarm": prewarm_info,
        **power_snapshot,
        "reverb_g2_git_commit": git_commit(),
        "gpu_driver_version": rig_telemetry.machine_specs().get("gpu", {}).get("driver"),
    }
    append_result(row)
    if result is None:
        log("no result captured -- see the warnings above.")
        sys.exit(1)
    log(f"done: {result}")


if __name__ == "__main__":
    main()
