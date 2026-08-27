#!/usr/bin/env python3
"""soak-variant.py -- unattended, headset-on, nobody-wearing-it soak of ONE Basalt/Monado config.

What it answers (docs/80, 2026-08-27 night): is a backend variant SAFE to hand to a wearer --
no crash, no divergence trips, no CPU/memory regression at rest? It cannot answer whether the
variant helps under fast yaw (nobody is moving the head); that is replay-basalt-variants.py's
job against a recorded session. Run it for the baseline first, then each variant; the JSON it
writes is what the pass/fail column in docs/80 is built from.

Sequence: preflight (no game trees, compositor down) -> jack-in-wayland.sh up 1 6dof with the
Aircar 6dof profile env (mirrors vr-launcher.py's TITLE_PROFILES so the soak matches the demo
path) + VIT_COLLAPSE_LOG=1 (+ SLAM_CONFIG / EUROC_RECORD / VIT_DUMP_CALIB when asked) -> the
360 player on a static image for N minutes (a real OpenXR client, no Steam; graceful quit via
HELLO_XR_DURATION_S, play360.sh's own -t as the backstop) -> sample monado-service RSS every
60 s -> collect metrics from ~/vr/jack-in-wayland.log -> teardown -> ~/vr/logs/soak/<tag>.json.

'up' mode, not 'quiet': quiet scrubs opt-in debug vars with `env -u` and forces VR_POSE_CSVS=0,
which would silently strip the very instrumentation this script reads.

Usage:
  soak-variant.py --tag base --minutes 20 [--dump-calib ~/vr/logs/calib-g2.json] [--euroc-record /mnt/vrtmp/euroc-static]
  soak-variant.py --tag G --minutes 20 --slam-config ~/vr/basalt-variants/G.toml [--baseline ~/vr/logs/soak/base.json]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gui_env  # noqa: E402  (shared with status-dashboard.py / pmadminka-agent.py)

HOME = Path.home()
VR = HOME / "vr"
JACK_IN = VR / "jack-in-wayland.sh"
PLAY360 = VR / "play360.sh"
MONADO_LOG = VR / "jack-in-wayland.log"
IPC_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "monado_comp_ipc"
OUT_DIR = VR / "logs" / "soak"
GAME_STOP = HERE / "game-stop.py"

# Aircar 6dof gold profile (vr-launcher.py TITLE_PROFILES["1073390"]) + variant F's spread,
# so the soak runs the exact Monado-side config the wearer tests ride on.
PROFILE_ENV = {
    "WMR_CONSTELLATION_CONTROLLERS": "0",
    "SLAM_PREDICTION_TYPE": "2",
    "SLAM_PRED_FREEZE_POSITION": "1",
    "SLAM_PRED_NECK_ARM_MM": "150",
    "SLAM_CORRECTION_SPREAD_MS": "25",
    "XRT_COMPOSITOR_SCALE_PERCENTAGE": "100",
    "SLAM_QUAT_NORM_CHECK": "1",
    "SLAM_SESSION_ANCHOR_RADIUS_CM": "300",
    "SLAM_THREADS": "6",
    "SLAM_PRED_POSITION_HORIZON_MS": "50",
    "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",
    "VIT_COLLAPSE_LOG": "1",
    "U_PACING_APP_LOG": "debug",
}


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def monado_pid():
    r = sh(["pgrep", "-x", "monado-service"])
    return int(r.stdout.split()[0]) if r.returncode == 0 and r.stdout.split() else None


def rss_mb(pid):
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return None


def coredump_count():
    r = sh(["coredumpctl", "list", "monado-service"])
    return sum(1 for l in r.stdout.splitlines() if l.strip() and not l.startswith("TIME"))


def pct(v, p):
    if not v:
        return None
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))]


def parse_vit(path):
    kp, lm, recall, total, opt, marg, patches = [], [], [], [], [], [], []
    for line in open(path, errors="replace"):
        if line.startswith("vit_of"):
            for lst, pat in ((kp, r"keypoints=(\d+)"), (recall, r"recall_ms=([0-9.eE+-]+)"),
                             (total, r"total_ms=([0-9.eE+-]+)"), (patches, r"patches=(\d+)")):
                m = re.search(pat, line)
                if m:
                    lst.append(float(m.group(1)))
        elif line.startswith("vit_vio"):
            for lst, pat in ((lm, r"landmarks=(\d+)"), (opt, r"opt_ms=([0-9.eE+-]+)"), (marg, r"marg_ms=([0-9.eE+-]+)")):
                m = re.search(pat, line)
                if m:
                    lst.append(float(m.group(1)))
    return {
        "frames": len(lm),
        "landmarks_p50": pct(lm, .5), "landmarks_p10": pct(lm, .1), "landmarks_min": min(lm) if lm else None,
        "keypoints_p50": pct(kp, .5),
        "recall_ms_p50": pct(recall, .5), "recall_ms_p99": pct(recall, .99),
        "frontend_total_ms_p50": pct(total, .5), "frontend_total_ms_p99": pct(total, .99),
        "opt_ms_p99": pct(opt, .99), "marg_ms_p99": pct(marg, .99),
        "patches_max": max(patches) if patches else None,
    }


def teardown():
    sh([str(JACK_IN), "down"], env=gui_env.get(), timeout=60)
    for _ in range(20):
        if monado_pid() is None:
            return True
        time.sleep(1)
    pid = monado_pid()
    if pid:
        sh(["kill", "-9", str(pid)])
    IPC_SOCKET.unlink(missing_ok=True)
    return monado_pid() is None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--minutes", type=int, default=20)
    ap.add_argument("--slam-config", type=Path, help="variant TOML for SLAM_CONFIG (omit = current basalt-g2-config.json)")
    ap.add_argument("--euroc-record", type=Path, help="also record an EuRoC dataset to this dir (EUROC_RECORD=1)")
    ap.add_argument("--dump-calib", type=Path, help="VIT_DUMP_CALIB=<path> (needs patches/basalt/0013)")
    ap.add_argument("--baseline", type=Path, help="baseline soak JSON to grade against")
    ap.add_argument("--media", type=Path, default=VR / "media" / "test-equirect.jpg")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VAL",
                    help="extra env for the service (repeatable), e.g. EUROC_RECORDER_USE_JPG=1")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = {"tag": args.tag, "minutes": args.minutes, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "slam_config": str(args.slam_config) if args.slam_config else None}

    # ---- preflight: nothing else may be using the headset ----
    st = sh([sys.executable, str(GAME_STOP), "status"]).stdout.strip()
    if st and "no Proton game trees running" not in st:
        sys.exit(f"refusing: a game is running -- {st}")
    if monado_pid():
        print("compositor already up -- tearing it down first")
        teardown()
    IPC_SOCKET.unlink(missing_ok=True)
    cores_before = coredump_count()

    env = {**gui_env.get(), **PROFILE_ENV}
    if args.slam_config:
        env["SLAM_CONFIG"] = str(args.slam_config)
        env["SLAM_CONFIG_PIPELINE_ONLY"] = "1"
    if args.euroc_record:
        env["EUROC_RECORD"] = "1"
        env["EUROC_RECORD_PATH"] = str(args.euroc_record)
    if args.dump_calib:
        env["VIT_DUMP_CALIB"] = str(args.dump_calib)
    for kv in args.env:
        k, _, v = kv.partition("=")
        env[k] = v

    # ---- bring Monado up ----
    print(f"[{args.tag}] jack-in-wayland.sh up 1 6dof ...", flush=True)
    r = subprocess.run([str(JACK_IN), "up", "1", "6dof"], env=env, capture_output=True, text=True, timeout=180)
    (OUT_DIR / f"{args.tag}-jack-in-stdout.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
    if r.returncode != 0 or not IPC_SOCKET.exists():
        result["error"] = "jack-in-wayland.sh did not leave the socket ready"
        (OUT_DIR / f"{args.tag}.json").write_text(json.dumps(result, indent=2))
        sys.exit(result["error"])
    pid = monado_pid()
    result["monado_pid"] = pid
    # confirm the variant config actually reached the service (the tonight-class bug)
    try:
        environ = open(f"/proc/{pid}/environ", "rb").read().decode(errors="replace").split("\0")
        result["service_env"] = {k: v for k, v in (e.split("=", 1) for e in environ if "=" in e)
                                 if k in ("SLAM_CONFIG", "SLAM_THREADS", "VIT_COLLAPSE_LOG", "EUROC_RECORD", "VIT_DUMP_CALIB")}
    except OSError:
        result["service_env"] = "unreadable"
    print(f"[{args.tag}] monado-service pid {pid}, env {result['service_env']}", flush=True)

    # ---- the client: 360 player on a static image, graceful quit at N minutes ----
    secs = args.minutes * 60
    penv = {**env, "HELLO_XR_DURATION_S": str(secs), "HELLO_XR_PHOTO360": str(args.media)}
    player_log = open(OUT_DIR / f"{args.tag}-player.log", "w")
    keepalive = subprocess.Popen(["sleep", str(secs + 120)], stdout=subprocess.PIPE)  # stdin must stay open (CLAUDE.md trap)
    player = subprocess.Popen([str(PLAY360), "-t", str(secs + 60), str(args.media)], env=penv,
                              stdin=keepalive.stdout, stdout=player_log, stderr=subprocess.STDOUT, start_new_session=True)

    # ---- sample every 60 s ----
    samples = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs + 30:
        time.sleep(60)
        p = monado_pid()
        alive = p is not None
        samples.append({"t_s": round(time.monotonic() - t0), "monado_alive": alive,
                        "rss_mb": rss_mb(p) if alive else None,
                        "diverged": sum(1 for l in open(MONADO_LOG, errors="replace") if "Tracker diverged" in l),
                        "player_alive": player.poll() is None})
        print(f"[{args.tag}] t={samples[-1]['t_s']}s alive={alive} rss={samples[-1]['rss_mb']} diverged={samples[-1]['diverged']}", flush=True)
        if not alive:
            break
        if player.poll() is not None and time.monotonic() - t0 < secs - 60:
            print(f"[{args.tag}] player exited early (rc={player.returncode})", flush=True)
            break
    try:
        player.wait(timeout=90)
    except subprocess.TimeoutExpired:
        player.terminate()
    keepalive.terminate()
    player_log.close()

    # ---- metrics ----
    result["samples"] = samples
    rss = [s["rss_mb"] for s in samples if s["rss_mb"]]
    if len(rss) >= 2 and samples[-1]["t_s"] > 0:
        result["rss_growth_mb_per_h"] = round((rss[-1] - rss[0]) / (samples[-1]["t_s"] - samples[0]["t_s"]) * 3600, 1)
    result["monado_alive_at_end"] = monado_pid() is not None
    result["coredumps_new"] = coredump_count() - cores_before
    result["diverged_trips"] = samples[-1]["diverged"] if samples else None
    result.update(parse_vit(MONADO_LOG))
    delivered = sum(1 for l in open(MONADO_LOG, errors="replace") if "Delivered frame" in l)
    result["delivered_frames_per_s"] = round(delivered / max(1, samples[-1]["t_s"]), 1) if samples else None
    shutil.copy(MONADO_LOG, OUT_DIR / f"{args.tag}-jack-in.log")
    if args.euroc_record:
        # euroc_recorder_start() (t_euroc_recorder.cpp:408-414) ALWAYS appends _YYYYMMDDHHmmss:
        # EUROC_RECORD_PATH is a prefix, the real dataset dir is the newest match.
        dirs = sorted(args.euroc_record.parent.glob(args.euroc_record.name + "_*"))
        if dirs:
            d = dirs[-1]
            cam0 = d / "mav0" / "cam0" / "data"
            imu = d / "mav0" / "imu0" / "data.csv"
            result["euroc"] = {"path": str(d),
                               "cam0_frames": len(list(cam0.iterdir())) if cam0.exists() else 0,
                               "imu_rows": max(0, sum(1 for _ in open(imu)) - 1) if imu.exists() else 0}
        else:
            result["euroc"] = {"path": None, "error": "no <prefix>_<datetime> dir was created"}
    if args.dump_calib:
        result["calib_dumped"] = args.dump_calib.exists() and args.dump_calib.stat().st_size > 100

    # ---- grade (docs/80 plan, Phase 3 pass criteria) ----
    fails = []
    if result["coredumps_new"]:
        fails.append(f"{result['coredumps_new']} new coredump(s)")
    if not result["monado_alive_at_end"]:
        fails.append("monado-service died")
    if result["diverged_trips"]:
        fails.append(f"{result['diverged_trips']} divergence trip(s) at rest")
    if result.get("recall_ms_p99") and result["recall_ms_p99"] > 3.0:
        fails.append(f"recall_ms p99 {result['recall_ms_p99']:.2f} > 3")
    if args.baseline and args.baseline.exists():
        base = json.load(open(args.baseline))
        if base.get("landmarks_p50") and result.get("landmarks_p50") is not None and result["landmarks_p50"] < base["landmarks_p50"]:
            fails.append(f"landmarks p50 {result['landmarks_p50']:.0f} < baseline {base['landmarks_p50']:.0f}")
        if base.get("frontend_total_ms_p99") and result.get("frontend_total_ms_p99") and \
                result["frontend_total_ms_p99"] > base["frontend_total_ms_p99"] * 1.2:
            fails.append(f"frontend p99 {result['frontend_total_ms_p99']:.1f} > baseline+20%")
        if base.get("rss_growth_mb_per_h") is not None and result.get("rss_growth_mb_per_h") is not None and \
                result["rss_growth_mb_per_h"] - base["rss_growth_mb_per_h"] > 10:
            fails.append(f"RSS growth {result['rss_growth_mb_per_h']} MB/h > baseline+10")
    result["verdict"] = "PASS" if not fails else "FAIL: " + "; ".join(fails)

    # ---- teardown ----
    result["teardown_clean"] = teardown()
    result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (OUT_DIR / f"{args.tag}.json").write_text(json.dumps(result, indent=2))
    print(f"[{args.tag}] {result['verdict']} -- landmarks p50/p10 {result.get('landmarks_p50')}/{result.get('landmarks_p10')}, "
          f"recall p99 {result.get('recall_ms_p99')} ms, frontend p99 {result.get('frontend_total_ms_p99')} ms, "
          f"rss {result.get('rss_growth_mb_per_h')} MB/h, delivered {result.get('delivered_frames_per_s')}/s", flush=True)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
