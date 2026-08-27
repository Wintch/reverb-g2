#!/usr/bin/env python3
"""soak-grade.py -- re-grade unattended soaks RELATIVE to the base run, from their saved artifacts.

Why (2026-08-27, small hours): soak-variant.py's pass rule assumed "at rest = stable", and the
very first 20-minute baseline refuted that: with the headset lying still, Basalt's backend hit
ZERO landmarks in every 5-minute bucket, the raw position random-walked up to 3 m away
(span 4.75 m), and the 0099 session-anchor guard tripped 7 times. So at rest the same
starvation that yaw accelerates is already there, slower -- which makes the stationary soak a
real A/B instrument (same view for every variant), not just a crash check. Absolute criteria
("0 trips") are meaningless; everything is graded against `base` here.

Reads, per tag, what soak-variant.py saved in ~/vr/logs/soak/: <tag>.json, <tag>-jack-in.log
(the monado log with the vit_* lines) and <tag>-jack-in-stdout.log (for the tmpfs CSV dir,
whose tracking.csv is copied next to them so the numbers survive a reboot).

Usage: soak-grade.py [tag ...]   (default: base + every other json present; base graded vs itself)
"""
import csv
import json
import math
import re
import shutil
import sys
from pathlib import Path

SOAK = Path.home() / "vr" / "logs" / "soak"


def load_csv(p):
    rows = []
    for r in csv.reader(open(p)):
        if len(r) < 4 or r[0].startswith("#"):
            continue
        try:
            rows.append((int(r[0]), float(r[1]), float(r[2]), float(r[3])))
        except ValueError:
            pass
    return rows


def analyze(tag):
    js = SOAK / f"{tag}.json"
    if not js.exists():
        return None
    r = json.load(open(js))
    log = SOAK / f"{tag}-jack-in.log"
    out = {"tag": tag, "verdict_driver": r.get("verdict"), "minutes": r.get("minutes"),
           "cores": r.get("coredumps_new"), "rss_mb_per_h": r.get("rss_growth_mb_per_h"),
           "recall_ms_p99": r.get("recall_ms_p99"), "frontend_p99": r.get("frontend_total_ms_p99"),
           "opt_p99": r.get("opt_ms_p99"), "patches_max": r.get("patches_max"), "kp_p50": r.get("keypoints_p50")}
    if log.exists():
        lm, trips = [], 0
        for line in open(log, errors="replace"):
            m = re.match(r"vit_vio .*landmarks=(\d+)", line)
            if m:
                lm.append(int(m.group(1)))
            elif "Tracker diverged" in line:
                trips += 1
        if lm:
            s = sorted(lm)
            out.update({"frames": len(lm), "lm_p50": s[len(s) // 2], "lm_p10": s[len(s) // 10], "lm_min": s[0],
                        "pct_frames_lm_lt5": round(100 * sum(1 for v in lm if v < 5) / len(lm), 2),
                        "pct_frames_lm_0": round(100 * sum(1 for v in lm if v == 0) / len(lm), 2)})
        out["trips"] = trips
    # raw stationary drift from the live CSV (copied beside the soak artifacts for durability)
    stdout_log = SOAK / f"{tag}-jack-in-stdout.log"
    local_csv = SOAK / f"{tag}-tracking.csv"
    if not local_csv.exists() and stdout_log.exists():
        m = re.search(r"Pose CSVs: (\S+)", stdout_log.read_text(errors="replace"))
        if m and Path(m.group(1), "tracking.csv").exists():
            shutil.copy(Path(m.group(1), "tracking.csv"), local_csv)
    if local_csv.exists():
        rows = load_csv(local_csv)
        if len(rows) > 60:
            t0 = rows[0][0]
            xs, ys, zs = zip(*[x[1:4] for x in rows])
            w = [math.dist(rows[i][1:4], rows[i + 30][1:4]) for i in range(0, len(rows) - 30, 15)]
            out.update({"span_m": round(max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)), 2),
                        "max_from_start_m": round(max(math.dist(rows[0][1:4], x[1:4]) for x in rows), 2),
                        "max_1s_disp_m": round(max(w), 3), "win_gt_0p5m": sum(v > 0.5 for v in w)})
    return out


def grade(v, base):
    if v is None:
        return "no data"
    if v["tag"] == base["tag"]:
        return "reference"
    fails, wins = [], []
    if v.get("cores"):
        fails.append(f"{v['cores']} coredump(s)")
    if v.get("rss_mb_per_h") is not None and base.get("rss_mb_per_h") is not None and v["rss_mb_per_h"] - base["rss_mb_per_h"] > 10:
        fails.append(f"RSS +{v['rss_mb_per_h'] - base['rss_mb_per_h']:.0f} MB/h vs base")
    if v.get("frontend_p99") and base.get("frontend_p99") and v["frontend_p99"] > base["frontend_p99"] * 1.2:
        fails.append(f"frontend p99 {v['frontend_p99']:.1f} > base+20%")
    if v.get("recall_ms_p99") and v["recall_ms_p99"] > 3.0:
        fails.append(f"recall p99 {v['recall_ms_p99']:.2f} ms")
    for key, better_is_lower, label in (("span_m", True, "span"), ("trips", True, "trips"),
                                        ("pct_frames_lm_lt5", True, "% frames lm<5"), ("lm_p10", False, "lm p10")):
        a, b = v.get(key), base.get(key)
        if a is None or b is None:
            continue
        if (a < b) == better_is_lower and a != b:
            wins.append(f"{label} {a} vs {b}")
        elif a != b and ((a > b) == better_is_lower):
            fails.append(f"{label} worse: {a} vs {b}") if key in ("span_m", "trips") and a > b * 1.3 + 0.5 else None
    tag = "SAFE" if not fails else "UNSAFE"
    return f"{tag}" + (" — " + "; ".join(fails) if fails else "") + (" | better: " + "; ".join(wins) if wins else "")


def main():
    tags = sys.argv[1:] or ["base"] + sorted(p.stem for p in SOAK.glob("*.json") if p.stem not in ("base", "record"))
    rows = [analyze(t) for t in tags]
    base = next((r for r in rows if r and r["tag"] == "base"), rows[0])
    cols = ["tag", "minutes", "lm_p50", "lm_p10", "lm_min", "pct_frames_lm_lt5", "trips", "span_m",
            "max_from_start_m", "max_1s_disp_m", "recall_ms_p99", "frontend_p99", "opt_p99", "patches_max", "rss_mb_per_h", "cores"]
    hdr = ["variant", "min", "lm p50", "lm p10", "lm min", "% lm<5", "trips", "span m", "max from start m",
           "max 1 s m", "recall p99 ms", "frontend p99 ms", "opt p99 ms", "patches", "RSS MB/h", "cores"]
    print("| " + " | ".join(hdr) + " | grade vs base |")
    print("|" + "---|" * (len(hdr) + 1))
    for r in rows:
        if r is None:
            continue
        cells = []
        for c in cols:
            v = r.get(c)
            cells.append("—" if v is None else (f"{v:.2f}" if isinstance(v, float) and abs(v) < 10 else (f"{v:.1f}" if isinstance(v, float) else str(v))))
        print("| " + " | ".join(cells) + f" | {grade(r, base)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
