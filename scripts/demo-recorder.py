#!/usr/bin/env python3
"""demo-recorder.py -- capture a live VR demo session for the record.

The demo IS the soak test (docs/80): many wearers cycling through one running title over a
long session -- diverse heads, IPD, HEIGHTS, motion styles -- is better evidence than a solo
30-min soak, but only if it's recorded. Design (agreed 2026-08-26):

  * While `monado-service` is alive, write the live record to RAM (`/mnt/vrtmp`, same tmpfs
    the SLAM CSVs already use -- cheap, no disk I/O jitter during a latency-sensitive demo).
  * When the SESSION ends (monado-service gone, or `stop`), copy the whole thing to permanent
    storage under ~/vr/logs/demo-sessions/<date>/ with a summary (date, eye-height, wearer
    count, operator comments). Nothing is lost to a reboot -- it's persisted at session close.

Each `start` = one run. Do several runs at several eye-heights (taller/shorter guests); each
run's summary records the eye-height it ran at, so the runs are comparable afterward.

"The session ends" means THIS run's monado-service process exits: a run binds to the
(pid, kernel start time) it found at `start`, not to "some monado-service exists". Found
2026-08-28: the 08-27 J/JT runs sampled for 22.5 h because the old `pgrep -f` check also
matched a background `bash -c '... pgrep -x monado-service ...'` wait-loop, and a service
restart inside one 20 s poll was invisible, so every run outlived its session and they all
finalized together when that loop died. A run also ends on `stop`/SIGTERM, or after
DEMO_RECORDER_MAX_H hours (default 8) as a backstop; summary.json's `stop_reason` says which.
The CURRENT pointer and the STOP flag are shared files but belong to ONE run each (STOP names
the run dir it is for): a run finalizes up to one interval after its service died, by when
playlist-runner may already have brought up the next session and its run, so a blind unlink
there orphaned the live run from `status`/`note`/`stop` (hardware-free repro, 2026-08-28).

Reuses rig_telemetry (GPU/power/tracking) and game-stop (active title) -- one source of truth,
same as status-dashboard.py. Both must sit beside this script (~/vr holds COPIES, and 15
launches died on that import 2026-08-26..27 -- scripts/deploy-check.py reports it).

  demo-recorder.py start [comment]  # record until this run's monado-service exits. Run in
                                    # background:
                                    #   nohup ./demo-recorder.py start "run 1, tall guests" \
                                    #     >/tmp/demo-rec.log 2>&1 &
  demo-recorder.py note "<text>"    # append an operator note to the ACTIVE run (a wearer's
                                    #   reaction: "person 3, ~1.9m, slight drift on fast turns")
  demo-recorder.py status           # is it recording? run dir, rows, wearers, eye-height
  demo-recorder.py stop             # finalize now (else it finalizes when monado-service ends)

Environment (all optional; the last three let the stop logic be tested without a headset):
  DEMO_RECORDER_INTERVAL    seconds between samples (20)
  DEMO_RECORDER_MAX_H       backstop: finalize after this many hours even if alive (8)
  DEMO_RECORDER_WATCH_COMM  process name to bind to (monado-service; pgrep -x, <=15 chars)
  DEMO_RECORDER_DIR         permanent storage dir (~/vr/logs/demo-sessions)
  DEMO_RECORDER_RAM_DIR     live working dir, meant to be a tmpfs mount (/mnt/vrtmp)
"""
import json
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import rig_telemetry  # noqa: E402
except ModuleNotFoundError as e:
    sys.exit(f"demo-recorder.py: cannot import '{e.name}' from {HERE} -- the deployed copy needs "
             f"its sibling modules beside it. Run scripts/deploy-check.py, then copy the missing "
             f"module next to this script.")
import importlib.util  # noqa: E402

_GS_PATH = HERE / "game-stop.py"
if not _GS_PATH.exists():
    sys.exit(f"demo-recorder.py: {_GS_PATH} is missing -- same remedy: scripts/deploy-check.py, "
             f"then copy it beside this script.")
_gs = importlib.util.spec_from_file_location("game_stop", _GS_PATH)
game_stop = importlib.util.module_from_spec(_gs)
_gs.loader.exec_module(game_stop)

VR = Path.home() / "vr"
MONADO_LOG = VR / "jack-in-wayland.log"           # monado-service's own stdout (per session)
JACKIN_LOG = VR / "logs" / "jack-in-launcher.log"  # jack-in-wayland.sh's stdout, appended per launch
PERM_DIR = Path(os.environ.get("DEMO_RECORDER_DIR") or VR / "logs" / "demo-sessions")  # survives reboot
RAM_BASE = Path(os.environ.get("DEMO_RECORDER_RAM_DIR", "/mnt/vrtmp"))  # live working dir (RAM); tmpfs
CURRENT = PERM_DIR / "CURRENT"                     # points at the live RAM dir of the active run
STOP_FLAG = PERM_DIR / "STOP"                      # names the run dir it is for (stop_requested)
INTERVAL_S = int(os.environ.get("DEMO_RECORDER_INTERVAL", "20"))
MAX_H = float(os.environ.get("DEMO_RECORDER_MAX_H", "8"))
WATCH_COMM = os.environ.get("DEMO_RECORDER_WATCH_COMM", "monado-service")

# The docs/80 tuning knobs = every variable with these prefixes in the service's environ. A
# fixed key list went stale within two days (JQ's SLAM_CONFIG, SLAM_CORRECTION_AVG_N,
# WMR_CAM_TS_MID_EXPOSURE and VIT_QUEUE_DEPTH were never captured), so record by prefix.
SLAM_PREFIXES = ("SLAM_", "VIT_", "WMR_CAM_")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def log(msg):
    """Timestamped and flushed: vr-launcher.py redirects us to demo-recorder.out, where the
    block-buffered 'recording ->' line used to surface only at exit, next to 'finalized'."""
    print(f"{now_iso()} {msg}", flush=True)


def delivered_frame_count():
    """Total 'Delivered frame' lines in the Monado log (app-fps.sh's honest metric). Needs
    U_PACING_APP_LOG=debug, which the demo launcher already sets. None if not available yet."""
    try:
        n = 0
        with open(MONADO_LOG, "rb") as f:
            for line in f:
                if b"Delivered frame" in line:
                    n += 1
        return n
    except OSError:
        return None


def client_connect_count():
    """How many client_connected lines -- each is one wearer session starting."""
    try:
        n = 0
        with open(MONADO_LOG, "rb") as f:
            for line in f:
                if b"client_connected" in line:
                    n += 1
        return n
    except OSError:
        return 0


def eye_height_m():
    """The eye-height this session was brought up at (jack-in-wayland.sh prints
    'Eye height: 1.70 m (standing) -> origin offset 0.100 m'). Distinguishes the tall/short
    runs. That line is jack-in-wayland.sh's OWN stdout, which vr-launcher.py appends to
    jack-in-launcher.log per launch -- it never reaches the Monado log, so the LAST match in
    the launcher log is this session's; the Monado log stays as a fallback for hand launches."""
    val = None
    for path in (JACKIN_LOG, MONADO_LOG):
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    m = re.search(r"Eye height:\s*([0-9.]+)\s*m", line)
                    if m:
                        val = float(m.group(1))
        except OSError:
            pass
        if val is not None:
            return val
    return val


def active_title():
    try:
        trees = game_stop.scan()
        return sorted(trees.keys())[0] if trees else None
    except Exception:
        return None


def slam_config(pid):
    """The docs/80 tuning knobs actually in effect on the running service, from its environ --
    so the record says exactly which config each wearer experienced."""
    out = {}
    if not pid:
        return out
    try:
        raw = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
        for e in raw:
            k, sep, v = e.partition(b"=")
            key = k.decode(errors="replace")
            if sep and key.startswith(SLAM_PREFIXES):
                out[key] = v.decode(errors="replace")
    except OSError:
        pass
    return dict(sorted(out.items()))


def proc_start_ticks(pid):
    """Kernel start time of `pid` (field 22 of /proc/<pid>/stat); None once it is gone. With
    the pid it identifies ONE process: this box burns ~30 pids/s (pid_max wrapped around
    midday 2026-08-28), so a bare pid can be recycled within a long demo."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def newest_slam_dir():
    try:
        dirs = sorted(RAM_BASE.glob("slam-*"), key=lambda p: p.stat().st_mtime, reverse=True)
        return dirs[0] if dirs else None
    except OSError:
        return None


def append(work_dir, row):
    with open(work_dir / "metrics.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


def stop_requested(work_dir):
    """True when the STOP flag is addressed to THIS run (it holds the run dir `stop` read from
    CURRENT). A flag for another run -- one still finalizing, or one that never did -- is not
    ours to consume or to remove."""
    try:
        return STOP_FLAG.read_text().strip() == str(work_dir)
    except OSError:
        return False


def cmd_start(comment):
    PERM_DIR.mkdir(parents=True, exist_ok=True)
    # A STOP addressed to the run CURRENT names may still be consumed by that run; any other
    # (a run that never finalized, a hand-made empty flag) is stale.
    if STOP_FLAG.exists():
        try:
            live = CURRENT.read_text().strip() if CURRENT.exists() else None
            if not live or STOP_FLAG.read_text().strip() != live:
                STOP_FLAG.unlink()
        except OSError:
            pass
    session_pid = rig_telemetry.monado_pid(WATCH_COMM)
    session_born = proc_start_ticks(session_pid) if session_pid else None
    if session_born is None:
        print(f"{WATCH_COMM} is not running -- start a session first.", file=sys.stderr)
        return 1

    start = time.strftime("%Y%m%d-%H%M%S")
    # Live record in RAM if /mnt/vrtmp is the tmpfs; otherwise degrade to permanent dir.
    if RAM_BASE.is_dir() and os.path.ismount(RAM_BASE):
        work_dir = RAM_BASE / f"demo-rec-{start}"
    else:
        work_dir = PERM_DIR / f"{start}-live"
        print(f"note: {RAM_BASE} not mounted -- recording straight to {work_dir}", file=sys.stderr)
    work_dir.mkdir(parents=True, exist_ok=True)
    CURRENT.write_text(str(work_dir))
    slam_dir = newest_slam_dir()
    append(work_dir, {"t": now_iso(), "type": "run_start", "comment": comment or "",
                      "eye_height_m": eye_height_m(), "slam_dir": str(slam_dir) if slam_dir else None,
                      "monado_pid": session_pid})
    log(f"recording -> {work_dir} (RAM; interval {INTERVAL_S}s; bound to {WATCH_COMM} pid "
        f"{session_pid}; backstop {MAX_H:g} h). Flushes to {PERM_DIR}/{start}/ when the session ends.")

    prev_frames = delivered_frame_count()
    prev_conn = 0
    last_cfg = {}
    t0 = time.monotonic()

    signalled = []  # in-process: a SIGTERM to us must not touch a STOP addressed to another run

    def handle_term(signum, frame):
        signalled.append(signum)
    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)

    ticks = 0
    while True:
        time.sleep(INTERVAL_S)
        # Stop conditions come before the sample, so a dead service never becomes a row.
        if signalled or stop_requested(work_dir):
            reason = "stop requested (demo-recorder.py stop / SIGTERM)"
            break
        if proc_start_ticks(session_pid) != session_born:
            reason = f"{WATCH_COMM} pid {session_pid} exited"
            break
        if time.monotonic() - t0 >= MAX_H * 3600:
            reason = f"backstop: {MAX_H:g} h max duration reached, {WATCH_COMM} pid {session_pid} still alive"
            break
        ticks += 1

        cur_frames = delivered_frame_count()
        fps = None
        if cur_frames is not None and prev_frames is not None:
            fps = round((cur_frames - prev_frames) / INTERVAL_S, 2)
        prev_frames = cur_frames

        conn = client_connect_count()
        for n in range(prev_conn + 1, conn + 1):
            append(work_dir, {"t": now_iso(), "type": "event", "event": "wearer_session_start", "wearer_n": n})
        prev_conn = conn

        cfg = slam_config(session_pid)
        if cfg:
            last_cfg = cfg
        append(work_dir, {
            "t": now_iso(), "type": "metric", "fps": fps,
            "tracking": rig_telemetry.tracking_mode(session_pid),
            "slam_config": cfg,
            "gpu": rig_telemetry.gpu_telemetry(),
            "power_mode": rig_telemetry.power_mode(),
            "active_title": active_title(),
            "wearers": conn,
        })

    return finalize(work_dir, start, comment, ticks, prev_conn, slam_dir, session_pid, last_cfg, reason)


def finalize(work_dir, start, comment, ticks, wearers, slam_dir, session_pid, last_cfg, reason):
    """Copy the RAM record + this run's SLAM CSVs to permanent storage with a summary."""
    dest = PERM_DIR / start
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if (work_dir / "metrics.jsonl").exists():
            shutil.copy2(work_dir / "metrics.jsonl", dest / "metrics.jsonl")
    except OSError:
        pass
    # this run's SLAM CSVs (in RAM) -> permanent
    slam_dir = slam_dir or newest_slam_dir()
    if slam_dir and slam_dir.is_dir():
        (dest / "slam").mkdir(exist_ok=True)
        for csv in slam_dir.glob("*.csv"):
            try:
                shutil.copy2(csv, dest / "slam" / csv.name)
            except OSError:
                pass
    notes = [json.loads(l) for l in open(dest / "metrics.jsonl")] if (dest / "metrics.jsonl").exists() else []
    comments = [r.get("text") for r in notes if r.get("type") == "note"]
    summary = {
        "run": start, "started_comment": comment or "",
        "ended": now_iso(), "ticks": ticks, "wearer_sessions": wearers,
        "eye_height_m": eye_height_m(),
        "operator_notes": comments,
        # the last non-empty sample: by now the service is gone, so re-reading its environ
        # here (what this field did until 2026-08-28) was always {}
        "slam_config_final": last_cfg,
        "monado_pid": session_pid,
        "stop_reason": reason,
    }
    (dest / "summary.json").write_text(json.dumps(summary, indent=2))
    # tidy the RAM working dir; it's already copied
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except OSError:
        pass
    # only THIS run's pointer and stop request: the next session's run may own them by now
    try:
        if CURRENT.read_text().strip() == str(work_dir):
            CURRENT.unlink()
    except OSError:
        pass
    if stop_requested(work_dir):
        STOP_FLAG.unlink(missing_ok=True)
    log(f"run finalized -> {dest}  ({ticks} samples, {wearers} wearer sessions, "
        f"eye-height {summary['eye_height_m']} m, {len(comments)} notes; {reason})")
    return 0


def cmd_note(text):
    if not CURRENT.exists():
        print("no active recording -- start one first.", file=sys.stderr)
        return 1
    append(Path(CURRENT.read_text().strip()), {"t": now_iso(), "type": "note", "text": text})
    print("note added.")
    return 0


def cmd_status():
    if not CURRENT.exists():
        print("not recording.")
        return 0
    work_dir = Path(CURRENT.read_text().strip())
    metrics = work_dir / "metrics.jsonl"
    rows = notes = wearers = 0
    eye = None
    if metrics.exists():
        for line in open(metrics):
            try:
                r = json.loads(line)
            except Exception:
                continue
            rows += 1
            if r.get("type") == "note":
                notes += 1
            if r.get("type") in ("metric", "run_start"):
                wearers = max(wearers, r.get("wearers") or 0)
                eye = r.get("eye_height_m") or eye
    print(f"recording -> {work_dir}")
    print(f"  rows: {rows}  notes: {notes}  wearer sessions: {wearers}  eye-height: {eye} m")
    return 0


def cmd_stop():
    if not CURRENT.exists():
        print("not recording.")
        return 0
    STOP_FLAG.write_text(CURRENT.read_text().strip())  # addressed to the run CURRENT names
    print("stop requested -- finalizes within one interval.")
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "start":
        return cmd_start(argv[2] if len(argv) > 2 else "")
    if cmd == "note":
        if len(argv) < 3:
            print('usage: demo-recorder.py note "<text>"', file=sys.stderr)
            return 2
        return cmd_note(argv[2])
    if cmd == "status":
        return cmd_status()
    if cmd == "stop":
        return cmd_stop()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
