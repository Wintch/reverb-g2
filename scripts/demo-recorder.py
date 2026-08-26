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

Reuses rig_telemetry (GPU/power/tracking) and game-stop (active title) -- one source of truth,
same as status-dashboard.py.

  demo-recorder.py start [comment]  # record until monado-service is gone. Run in background:
                                    #   nohup ./demo-recorder.py start "run 1, tall guests" \
                                    #     >/tmp/demo-rec.log 2>&1 &
  demo-recorder.py note "<text>"    # append an operator note to the ACTIVE run (a wearer's
                                    #   reaction: "person 3, ~1.9m, slight drift on fast turns")
  demo-recorder.py status           # is it recording? run dir, rows, wearers, eye-height
  demo-recorder.py stop             # finalize now (else it finalizes when monado-service ends)
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
import rig_telemetry  # noqa: E402
import importlib.util  # noqa: E402

_gs = importlib.util.spec_from_file_location("game_stop", HERE / "game-stop.py")
game_stop = importlib.util.module_from_spec(_gs)
_gs.loader.exec_module(game_stop)

VR = Path.home() / "vr"
MONADO_LOG = VR / "jack-in-wayland.log"
PERM_DIR = VR / "logs" / "demo-sessions"          # permanent storage (survives reboot)
RAM_BASE = Path("/mnt/vrtmp")                     # live working dir (RAM); tmpfs
CURRENT = PERM_DIR / "CURRENT"                     # points at the live RAM dir of the active run
STOP_FLAG = PERM_DIR / "STOP"
INTERVAL_S = int(os.environ.get("DEMO_RECORDER_INTERVAL", "20"))

SLAM_KEYS = ("SLAM_PREDICTION_TYPE", "SLAM_PRED_FREEZE_POSITION", "SLAM_PRED_NECK_ARM_MM",
             "SLAM_CORRECTION_SPREAD_MS", "SLAM_THREADS")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


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
    """The eye-height this session was brought up at (jack-in-wayland.sh logs
    'Eye height: 1.70 m (standing) -> origin offset 0.100 m'). Distinguishes the tall/short
    runs. Reads the LAST such line in the current log."""
    val = None
    try:
        with open(MONADO_LOG, errors="replace") as f:
            for line in f:
                m = re.search(r"Eye height:\s*([0-9.]+)\s*m", line)
                if m:
                    val = float(m.group(1))
    except OSError:
        pass
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
        env = dict(e.split(b"=", 1) for e in raw if b"=" in e)
        for k in SLAM_KEYS:
            v = env.get(k.encode())
            if v is not None:
                out[k] = v.decode(errors="replace")
    except OSError:
        pass
    return out


def newest_slam_dir():
    try:
        dirs = sorted(RAM_BASE.glob("slam-*"), key=lambda p: p.stat().st_mtime, reverse=True)
        return dirs[0] if dirs else None
    except OSError:
        return None


def append(work_dir, row):
    with open(work_dir / "metrics.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


def cmd_start(comment):
    PERM_DIR.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.unlink(missing_ok=True)
    if rig_telemetry.monado_pid() is None:
        print("monado-service is not running -- start a session first.", file=sys.stderr)
        return 1

    start = time.strftime("%Y%m%d-%H%M%S")
    # Live record in RAM if /mnt/vrtmp is the tmpfs; otherwise degrade to permanent dir.
    if RAM_BASE.is_dir() and os.path.ismount(RAM_BASE):
        work_dir = RAM_BASE / f"demo-rec-{start}"
    else:
        work_dir = PERM_DIR / f"{start}-live"
        print(f"note: /mnt/vrtmp not mounted -- recording straight to {work_dir}", file=sys.stderr)
    work_dir.mkdir(parents=True, exist_ok=True)
    CURRENT.write_text(str(work_dir))
    slam_dir = newest_slam_dir()
    append(work_dir, {"t": now_iso(), "type": "run_start", "comment": comment or "",
                      "eye_height_m": eye_height_m(), "slam_dir": str(slam_dir) if slam_dir else None})
    print(f"recording -> {work_dir} (RAM; interval {INTERVAL_S}s). "
          f"Flushes to {PERM_DIR}/{start}/ when the session ends.")

    prev_frames = delivered_frame_count()
    prev_conn = 0

    def handle_term(signum, frame):
        STOP_FLAG.touch()
    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)

    ticks = 0
    while rig_telemetry.monado_pid() is not None and not STOP_FLAG.exists():
        time.sleep(INTERVAL_S)
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

        pid = rig_telemetry.monado_pid()
        append(work_dir, {
            "t": now_iso(), "type": "metric", "fps": fps,
            "tracking": rig_telemetry.tracking_mode(pid) if pid else None,
            "slam_config": slam_config(pid),
            "gpu": rig_telemetry.gpu_telemetry(),
            "power_mode": rig_telemetry.power_mode(),
            "active_title": active_title(),
            "wearers": conn,
        })

    return finalize(work_dir, start, comment, ticks, prev_conn, slam_dir)


def finalize(work_dir, start, comment, ticks, wearers, slam_dir):
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
        "slam_config_final": slam_config(rig_telemetry.monado_pid()),
    }
    (dest / "summary.json").write_text(json.dumps(summary, indent=2))
    # tidy the RAM working dir; it's already copied
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except OSError:
        pass
    CURRENT.unlink(missing_ok=True)
    STOP_FLAG.unlink(missing_ok=True)
    print(f"run finalized -> {dest}  ({ticks} samples, {wearers} wearer sessions, "
          f"eye-height {summary['eye_height_m']} m, {len(comments)} notes)")
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
    STOP_FLAG.touch()
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
