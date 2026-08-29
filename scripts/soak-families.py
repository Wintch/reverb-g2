#!/usr/bin/env python3
"""soak-families.py -- group the unattended at-rest soaks by config family and summarize.

The single-run table (soak-grade.py) hides the run-to-run variance that bit us on 2026-08-27
(I: span 0.41 m / 0 trips; its replicate I2: 4.52 m / 4 trips). This groups every run whose
Basalt config shares the same recipe and prints n, and min / median / max of the drift metrics,
so a family is judged on all its runs, not its best one.

Usage: soak-families.py            (reads ~/vr/logs/soak/*.json + *-tracking.csv via soak-grade's analyze())
"""
import importlib.util
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("soak_grade", HERE / "soak-grade.py")
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)

VARIANTS = HERE / "basalt-variants"


def recipe(tag):
    """Config recipe of a run, from the variant JSON its tag maps to (I2/I3/I4/I5 -> I, base2 -> base)."""
    tag = re.sub(r"-i\d+$", "", tag)  # interleaved legs (2026-08-29): P2-i2 -> P2, base-i3 -> base
    if tag in ("base", "record"):
        return "base (as shipped)"
    p = VARIANTS / f"{tag}.json"  # exact variant first (P1..P8, N1..N5 are distinct configs)
    if not p.exists():
        stem = "".join(c for c in tag if not c.isdigit()) if tag not in ("G2", "G3") else tag
        p = VARIANTS / f"{stem}.json"
    if not p.exists():
        return f"? ({tag})"
    v = json.load(open(p))["value0"]
    parts = []
    if v.get("config.optical_flow_recall_enable"):
        parts.append("recall")
    if not v.get("config.vio_marg_lost_landmarks", True):
        parts.append("marg-lost off")
    if v.get("config.vio_min_triangulation_dist", 0.05) != 0.05:
        parts.append(f"triang {v['config.vio_min_triangulation_dist']} m")
    if v.get("config.vio_max_kfs", 7) != 7:
        parts.append(f"{v['config.vio_max_kfs']} kfs")
    if v.get("config.vio_new_kf_keypoints_thresh", 0.7) != 0.7:
        parts.append(f"kf thresh {v['config.vio_new_kf_keypoints_thresh']}")
    if v.get("config.optical_flow_recall_max_patch_norms", [0.435])[0] != 0.435:
        parts.append("loose recall norms")
    return " + ".join(parts) or "base (as shipped)"


def main():
    tags = sorted(p.stem for p in sg.SOAK.glob("*.json") if p.stem != "record")
    rows = [r for r in (sg.analyze(t) for t in tags) if r]
    fam = {}
    for r in rows:
        fam.setdefault(recipe(r["tag"]), []).append(r)
    def mmm(vals):
        v = [x for x in vals if x is not None]
        return f"{min(v):.2f} / {statistics.median(v):.2f} / {max(v):.2f}" if v else "—"
    print("| family | runs | trips min/med/max | span m min/med/max | lm p10 min/med/max | frontend p50 ms min/med/max |")
    print("|---|---|---|---|---|---|")
    for name, rs in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        fp50 = []
        for r in rs:
            log = sg.SOAK / f"{r['tag']}-jack-in.log"
            if log.exists():
                import re
                t = sorted(float(m.group(1)) for line in open(log, errors="replace") for m in [re.match(r"vit_of total_ms=([0-9.]+)", line)] if m)
                if t:
                    fp50.append(t[len(t) // 2])
        print(f"| {name} | {len(rs)} ({', '.join(r['tag'] for r in rs)}) | {mmm([r.get('trips') for r in rs])} | "
              f"{mmm([r.get('span_m') for r in rs])} | {mmm([r.get('lm_p10') for r in rs])} | {mmm(fp50)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
