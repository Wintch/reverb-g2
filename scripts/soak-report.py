#!/usr/bin/env python3
"""soak-report.py -- one markdown table from ~/vr/logs/soak/*.json (soak-variant.py output).

Usage: soak-report.py [tag ...]      (default: every json in the soak dir, base first)
"""
import json
import sys
from pathlib import Path

SOAK_DIR = Path.home() / "vr" / "logs" / "soak"
COLS = [
    ("tag", "variant"), ("verdict", "verdict"), ("minutes", "min"),
    ("landmarks_p50", "lm p50"), ("landmarks_p10", "lm p10"), ("keypoints_p50", "kp p50"),
    ("recall_ms_p99", "recall p99 ms"), ("frontend_total_ms_p50", "frontend p50 ms"),
    ("frontend_total_ms_p99", "frontend p99 ms"), ("opt_ms_p99", "opt p99 ms"),
    ("patches_max", "patches"), ("rss_growth_mb_per_h", "RSS MB/h"),
    ("delivered_frames_per_s", "delivered/s"), ("coredumps_new", "cores"), ("diverged_trips", "diverged"),
]


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}"
    return str(v)


def main():
    tags = sys.argv[1:]
    files = [SOAK_DIR / f"{t}.json" for t in tags] if tags else sorted(SOAK_DIR.glob("*.json"),
                                                                        key=lambda p: (p.stem != "base", p.stem))
    rows = [json.load(open(f)) for f in files if f.exists()]
    if not rows:
        sys.exit(f"no soak json in {SOAK_DIR}")
    print("| " + " | ".join(h for _, h in COLS) + " |")
    print("|" + "---|" * len(COLS))
    for r in rows:
        print("| " + " | ".join(fmt(r.get(k)) for k, _ in COLS) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
