#!/usr/bin/env python3
"""playlist-runner.py -- the demo experience sequencer for the VR booth.

Runs an ordered playlist of mixed experiences (in-house 360/VR180/SBS videos + Steam VR
titles), ONE at a time, with a spoken "proximo titulo" cue and a clean teardown between
each. Built for the commercial-showcase round: only the best go in, and it must "cerrar
todo bien" between experiences.

Web-controllable (the dashboard writes the control file, polls the status file):
  control  ~/vr/logs/playlist-control.json : {"command": "run|pause|stop|skip"}
  status   ~/vr/logs/playlist-status.json  : live state the dashboard renders

Playlist JSON (path as argv[1], or "-" to read stdin):
  {
    "name": "Ronda demo",
    "gap_seconds": 6,               # spoken-cue pause between entries
    "entries": [
      {"type":"video","name":"Sizzle 2D->3D","path":"/…/dav2_demo","seconds":180},
      {"type":"steam","name":"Aircar","appid":"1073390","tracking":"3dof","seconds":300},
      {"type":"steam","name":"Dreams of Dali","appid":"591360","tracking":"6dof","seconds":300}
    ]
  }

Design notes (why it is the way it is):
  * ONE experience alive at a time. Each entry does a full teardown of the previous client
    AND monado-service, then the entry's own launcher brings monado back up with the right
    per-title tracking profile (Aircar MUST be 3dof for guests, Dali 6dof, etc.). That is
    the price of correct per-title tracking; the gap + voice cue cover the bring-up time.
    NOTE: chaining monado restarts is a known USB2-fault trigger (see CLAUDE.md); the gap
    also gives the USB2 branch a moment to settle. Watch the round for drops.
  * The player self-terminates (play360.sh wraps hello_xr in `timeout`); Steam titles do
    not, so we dwell then game-stop them.
  * pause == "don't start the next one" (takes effect at the entry boundary, per the user).
    stop == teardown now and end the round ("limpia la ronda"). skip == end current now.
"""
import json
import os
import signal
import subprocess
import sys
import time

VR = os.path.join(os.path.expanduser("~"), "vr")
LOG_DIR = os.path.join(VR, "logs")
CONTROL = os.path.join(LOG_DIR, "playlist-control.json")
STATUS = os.path.join(LOG_DIR, "playlist-status.json")
JACKIN = os.path.join(VR, "jack-in-wayland.sh")
VR_LAUNCHER = os.path.join(VR, "vr-launcher.py")
PLAY360 = os.path.join(VR, "play360.sh")
GAME_STOP = os.path.join(VR, "game-stop.py")
VOICE = os.path.join(VR, "voice-guide.py")

POLL_S = 1.0          # how often we re-read the control file during a dwell
_state = {"stop": False}


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def write_status(**kw):
    """Merge kw into the status file the dashboard polls. Best-effort."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        base = {}
        if os.path.exists(STATUS):
            try:
                base = json.load(open(STATUS))
            except Exception:
                base = {}
        base.update(kw)
        base["updated_at"] = _now()
        tmp = STATUS + ".tmp"
        json.dump(base, open(tmp, "w"), ensure_ascii=False, indent=2)
        os.replace(tmp, STATUS)
    except Exception as e:
        print(f"[status] {e}", file=sys.stderr)


def read_command():
    """Current web command: run|pause|stop|skip (default run). Best-effort."""
    try:
        return (json.load(open(CONTROL)) or {}).get("command", "run")
    except Exception:
        return "run"


def clear_command():
    try:
        json.dump({"command": "run"}, open(CONTROL, "w"))
    except Exception:
        pass


def voice(text, sink_args=None):
    """Speak a cue through voice-guide.py (best-effort, never fatal)."""
    try:
        cmd = ["python3", VOICE, "say", text]
        if sink_args:
            cmd += sink_args
        subprocess.run(cmd, timeout=25, capture_output=True)
    except Exception as e:
        print(f"[voice] {e}", file=sys.stderr)


def teardown():
    """Close EVERYTHING cleanly: any Steam title, any hello_xr, then monado-service."""
    try:
        subprocess.run(["python3", GAME_STOP, "all"], timeout=60, capture_output=True)
    except Exception as e:
        print(f"[teardown/game-stop] {e}", file=sys.stderr)
    # kill any lingering hello_xr (video player) by argv[0], never matching ourselves
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                argv0 = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0]
            except OSError:
                continue
            if argv0.endswith(b"hello_xr"):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except OSError:
                    pass
    except Exception as e:
        print(f"[teardown/hello_xr] {e}", file=sys.stderr)
    try:
        subprocess.run([JACKIN, "down"], timeout=40, capture_output=True)
    except Exception as e:
        print(f"[teardown/jackin] {e}", file=sys.stderr)


def dwell(seconds, proc=None):
    """Wait `seconds`, polling the control file. Returns the reason we stopped:
    'done' | 'skip' | 'stop'. If `proc` is given (the player), we also stop early
    when it exits on its own, and we kill it on skip/stop."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _state["stop"]:
            _kill(proc)
            return "stop"
        cmd = read_command()
        if cmd == "stop":
            _kill(proc)
            return "stop"
        if cmd == "skip":
            clear_command()
            _kill(proc)
            return "skip"
        if proc is not None and proc.poll() is not None:
            return "done"   # player finished on its own
        remaining = max(0, int(deadline - time.time()))
        write_status(remaining_s=remaining)
        time.sleep(POLL_S)
    _kill(proc)
    return "done"


def _kill(proc):
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
    except Exception:
        pass


def wait_if_paused():
    """Honor a 'pause' before starting the next entry. Returns False if we should stop."""
    announced = False
    while True:
        if _state["stop"]:
            return False
        cmd = read_command()
        if cmd == "stop":
            return False
        if cmd != "pause":
            return True
        if not announced:
            write_status(state="paused")
            print(f"[{_now()}] paused -- waiting for resume/stop", flush=True)
            announced = True
        time.sleep(POLL_S)


def launch_video(entry):
    """Bring monado up (3dof is plenty for a stereo video) and play the file/dir."""
    mode = str(entry.get("mode", "1"))          # 4320x2160@90 for 4K content
    up = subprocess.run([JACKIN, "up", mode, "3dof"], capture_output=True, text=True, timeout=120)
    if up.returncode != 0:
        print(f"[video] jack-in up failed: {up.stderr[-300:]}", file=sys.stderr)
        return None
    env = dict(os.environ, HELLO_XR_AUDIO="1")
    return subprocess.Popen(
        ["bash", PLAY360, "-t", str(int(entry.get("seconds", 180))), entry["path"]],
        env=env, stdin=subprocess.DEVNULL,
    )


def launch_steam(entry):
    """vr-launcher brings monado up with the title's per-profile tracking, then launches it."""
    mode = str(entry.get("mode", "1"))
    tracking = entry.get("tracking", "6dof")
    env = dict(os.environ, VR_LAUNCH_APPID=str(entry["appid"]))
    r = subprocess.run(["python3", VR_LAUNCHER, mode, tracking], env=env,
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"[steam] vr-launcher failed: {r.stderr[-300:]}", file=sys.stderr)
    # vr-launcher returns after firing the title; the title keeps running in the background.
    return None  # nothing to hold a handle to; we dwell then game-stop in run_entry


def run_entry(i, total, entry):
    name = entry.get("name", entry.get("type", "?"))
    write_status(index=i, total=total, current=name, current_type=entry.get("type"),
                 state="announcing", remaining_s=int(entry.get("seconds", 0)))
    print(f"[{_now()}] ({i+1}/{total}) {name}", flush=True)

    voice(f"Proximo titulo: {name}")
    write_status(state="teardown")
    teardown()
    if _state["stop"]:
        return "stop"

    write_status(state="launching")
    proc = launch_video(entry) if entry.get("type") == "video" else launch_steam(entry)

    write_status(state="running")
    reason = dwell(int(entry.get("seconds", 180)), proc=proc)

    # Steam titles have no proc handle -> stop them explicitly.
    if entry.get("type") == "steam":
        try:
            subprocess.run(["python3", GAME_STOP, "stop", str(entry["appid"])],
                           timeout=60, capture_output=True)
        except Exception:
            pass
    return reason


def main(argv):
    if len(argv) < 2:
        print("usage: playlist-runner.py <playlist.json|->", file=sys.stderr)
        return 2
    raw = sys.stdin.read() if argv[1] == "-" else open(argv[1]).read()
    pl = json.loads(raw)
    entries = pl.get("entries", [])
    name = pl.get("name", "Ronda")
    gap = int(pl.get("gap_seconds", 6))
    total = len(entries)
    if not total:
        print("playlist has no entries", file=sys.stderr)
        return 2

    def _sig(*_):
        _state["stop"] = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    clear_command()
    write_status(name=name, total=total, index=-1, state="starting",
                 started_at=_now(), current=None)
    print(f"[{_now()}] === playlist '{name}' ({total} entries) ===", flush=True)

    stopped = False
    for i, entry in enumerate(entries):
        if not wait_if_paused():
            stopped = True
            break
        if i > 0:
            time.sleep(gap)     # breathing room + lets the USB2 branch settle
        reason = run_entry(i, total, entry)
        if reason == "stop":
            stopped = True
            break

    write_status(state="stopping")
    voice("Lista la ronda" if not stopped else "Ronda detenida")
    teardown()
    write_status(state="stopped", current=None, ended_at=_now())
    print(f"[{_now()}] === playlist ended ({'stopped' if stopped else 'complete'}) ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
