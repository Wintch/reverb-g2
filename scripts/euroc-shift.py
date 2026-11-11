#!/usr/bin/env python3
"""euroc-shift.py -- copy a recorded EuRoC dataset with the camera timestamps shifted by N ms.

Why (2026-08-28): H1 (docs/80, "H1 CONFIRMED offline") was tested by hand -- copies of the yaw
recording with the camN/data.csv stamps moved by -10 / -5 / +5 / +10 ms, PNGs symlinked, IMU
untouched, replayed through basalt_vio. Those copies lived on tmpfs and are gone, and every new
recording (dashboard button RQ) needs the same 0 / -5 / -10 ms sweep, so the recipe is a tool.

What a shifted copy has to look like, read off the two readers that consume it:
  * Basalt (basalt/include/basalt/io/dataset_io_euroc.h): read_image_timestamps() parses ONLY
    mav0/cam0/data.csv as `t_ns , filename`, and get_image_data() opens
    mav0/cam<i>/data/<that filename> for EVERY camera i -- the filename column is what gets
    loaded, cam0's column is used for all cameras, and a missing file silently drops the frame.
    A blank line in data.csv becomes a bogus frame at t=0, so none may be written.
  * Monado (drivers/euroc/euroc_player.cpp): per camera, mav0/cam<i>/data/<filename column>.
So every shifted row is written as `t+delta,<t+delta>.png` and mav0/cam<i>/data/<t+delta>.png
is an absolute symlink to the original image: the recorder's filename == timestamp convention
(t_euroc_recorder.cpp) is kept, so a reader keying on either column sees the same frame. A
cam<i>/exposure.csv (Basalt keys it by t_ns; our recorder never writes one) is rewritten with
the same delta. Everything else under mav0/ (imu0, gt, cameras not listed in --cams) is an
absolute symlink to the source, unchanged; top-level files (phases.json, ...) are copied; a
euroc-shift.json with the provenance is written into DST. The copy is ~1 MB of links:
regenerate, do not archive (the links break if SRC moves).

Sign: negative ms moves the camera frames EARLIER relative to the IMU -- the same sign as
VIT_CAM_TIME_OFFSET_NS (Basalt patch 0017) and as Basalt's own calib cam_time_offset_ns.
--cams only makes sense for Monado's player (per-camera CSVs); Basalt uses cam0's list for all.

Validated 2026-08-28 on euroc-yaw_20260827170436 (4 cams x 6851 frames, 984K of links): --ms -5
replayed with P2 (replay-basalt-variants.py, then replay-phase-slice.py) gives yaw max-far
0.26 m vs 0.43 m unshifted and 0.21 m for J at -5 ms (docs/80 "H1 CONFIRMED offline"); the
still settle phases stay <= 0.015 m (settle-3: 0.0145).

Usage:
  euroc-shift.py --src ~/vr/logs/euroc/euroc-yaw_20260827170436 --dst /mnt/vrtmp/euroc-yaw-shift_m5 --ms -5
  euroc-shift.py --src DIR --dst /mnt/vrtmp/euroc-yaw-shift_0 --ms 0     # unshifted mirror = the sweep's baseline
  then: replay-basalt-variants.py --dataset /mnt/vrtmp/euroc-yaw-shift_m5 --calib ... --config P2=...
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def fail(msg):
    sys.exit(f"euroc-shift: ERROR: {msg}")


def warn(msg):
    print(f"euroc-shift: WARNING: {msg}", file=sys.stderr)


def cam_dirs(mav0):
    """cam<N> subdirs of mav0 in numeric order (Basalt counts cam0, cam1, ... until the first gap)."""
    names = [p.name for p in mav0.iterdir() if p.is_dir() and p.name.startswith("cam") and p.name[3:].isdigit()]
    return sorted(names, key=lambda n: int(n[3:]))


def read_cam(src_cam, delta_ns):
    """Parse SRC/mav0/camN/data.csv and check every listed image exists.

    Returns (entries, errors, warnings, n_unlisted): entries are ("#", line) for comment lines,
    kept verbatim in place, or ("row", t_ns, filename, new_t_ns, new_filename, extra_cols)."""
    csv_path = src_cam / "data.csv"
    data_dir = src_cam / "data"
    entries, errors, warnings = [], [], []
    if not csv_path.is_file():
        return entries, [f"{csv_path}: missing"], warnings, 0
    if not data_dir.is_dir():
        return entries, [f"{data_dir}: missing"], warnings, 0
    seen, prev, listed = set(), None, set()
    with open(csv_path, newline="") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\r\n")
            if not line.strip():
                warnings.append(f"{csv_path}:{lineno}: blank line skipped (Basalt would read it as a frame at t=0)")
                continue
            if line.startswith("#"):
                entries.append(("#", line))
                continue
            cols = [c.strip() for c in line.split(",")]
            if len(cols) < 2 or not cols[1]:
                errors.append(f"{csv_path}:{lineno}: expected 't_ns,filename', got {line!r}")
                continue
            try:
                t = int(cols[0])
            except ValueError:
                errors.append(f"{csv_path}:{lineno}: bad timestamp {cols[0]!r}")
                continue
            fname = cols[1]
            if not (data_dir / fname).is_file():
                errors.append(f"{csv_path}:{lineno}: image listed but missing: {data_dir / fname}")
            if t in seen:
                errors.append(f"{csv_path}:{lineno}: duplicate timestamp {t}")
            seen.add(t)
            listed.add(fname)
            if prev is not None and t <= prev:
                warnings.append(f"{csv_path}:{lineno}: timestamp {t} not after previous {prev}")
            prev = t
            new_t = t + delta_ns
            if new_t < 0:
                errors.append(f"{csv_path}:{lineno}: shifted timestamp would be negative ({new_t})")
            entries.append(("row", t, fname, new_t, f"{new_t}{Path(fname).suffix}", cols[2:]))
    if not seen:
        errors.append(f"{csv_path}: no data rows")
    exp = src_cam / "exposure.csv"
    if exp.is_file():
        with open(exp, newline="") as f:
            for lineno, raw in enumerate(f, 1):
                line = raw.rstrip("\r\n")
                if not line.strip() or line.startswith("#"):
                    continue
                try:
                    int(line.split(",", 1)[0])
                except ValueError:
                    errors.append(f"{exp}:{lineno}: bad timestamp in {line!r}")
    n_unlisted = sum(1 for p in data_dir.iterdir() if p.name not in listed)
    return entries, errors, warnings, n_unlisted


def build_cam(src_cam, dst_cam, entries, delta_ns):
    """Write DST/mav0/camN/data.csv, the data/ symlink farm (absolute targets) and, if the source
    has one, exposure.csv with its t_ns keys shifted."""
    (dst_cam / "data").mkdir(parents=True)
    data_dir = src_cam / "data"
    with open(dst_cam / "data.csv", "w", newline="") as f:
        for e in entries:
            if e[0] == "#":
                f.write(e[1] + "\n")
                continue
            _, _t, fname, new_t, new_name, extra = e
            f.write(",".join([str(new_t), new_name] + extra) + "\n")
            os.symlink(os.path.realpath(data_dir / fname), dst_cam / "data" / new_name)
    exp = src_cam / "exposure.csv"
    if exp.is_file():
        with open(exp, newline="") as fi, open(dst_cam / "exposure.csv", "w", newline="") as fo:
            for raw in fi:
                line = raw.rstrip("\r\n")
                if not line.strip():
                    continue
                if line.startswith("#"):
                    fo.write(line + "\n")
                    continue
                t, rest = line.split(",", 1)
                fo.write(f"{int(t) + delta_ns},{rest}\n")


def link_targets(src, mav0, cams, plan):
    """Every path a copy of SRC would symlink to, resolved -- the shifted cameras' images, the
    other mav0/ entries and the non-file top-level entries (mirrors what main() links)."""
    for c in cams:
        data_dir = mav0 / c / "data"
        for e in plan[c]:
            if e[0] == "row":
                yield Path(os.path.realpath(data_dir / e[2]))
    for p in mav0.iterdir():
        if p.name not in cams:
            yield Path(os.path.realpath(p))
    for p in src.iterdir():
        if p.name != "mav0" and not (p.is_file() and not p.is_symlink()):
            yield Path(os.path.realpath(p))


def verify_cam(dst_cam):
    """Re-read what was written the way the readers will: every row's file must resolve."""
    n, bad = 0, []
    with open(dst_cam / "data.csv", newline="") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                bad.append("blank line written")
                continue
            if line.startswith("#"):
                continue
            t, fname = line.split(",")[:2]
            if fname != f"{int(t)}{Path(fname).suffix}":
                bad.append(f"{t}: filename {fname} does not match the timestamp")
            if not (dst_cam / "data" / fname).is_file():  # follows the symlink
                bad.append(f"{t}: {dst_cam / 'data' / fname} does not resolve")
            n += 1
    return n, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="recorded dataset dir (contains mav0/)")
    ap.add_argument("--dst", type=Path, required=True, help="dir to create (refused if it exists, see --force)")
    ap.add_argument("--ms", type=float, required=True,
                    help="camera timestamp shift in ms; negative = frames earlier vs the IMU (e.g. -5)")
    ap.add_argument("--cams", nargs="+", metavar="camN",
                    help="cameras to shift (default: every mav0/cam<N>); the rest are linked unchanged")
    ap.add_argument("--force", action="store_true",
                    help="remove an existing DST first (only an empty dir or one this tool wrote, i.e. with euroc-shift.json)")
    a = ap.parse_args()

    src = Path(os.path.abspath(os.path.expanduser(a.src)))
    dst = Path(os.path.abspath(os.path.expanduser(a.dst)))
    mav0 = src / "mav0"
    if not mav0.is_dir():
        fail(f"{src}: no mav0/ -- not a EuRoC dataset")
    src_real, dst_real = Path(os.path.realpath(src)), Path(os.path.realpath(dst))
    if src_real == dst_real or src_real in dst_real.parents or dst_real in src_real.parents:
        fail(f"DST {dst} and SRC {src} overlap")
    delta_ns = int(round(a.ms * 1e6))

    all_cams = cam_dirs(mav0)
    if "cam0" not in all_cams:
        fail(f"{mav0}: no cam0/ (Basalt reads cam0/data.csv for every camera)")
    cams = a.cams or all_cams
    for c in cams:
        if c not in all_cams:
            fail(f"--cams {c}: not a cam<N> dir under {mav0} (found: {' '.join(all_cams)})")
    if a.cams and set(cams) != set(all_cams):
        warn(f"shifting only {' '.join(cams)}: Basalt keys every camera off cam0/data.csv, so a "
             f"partial shift only makes sense for Monado's euroc player")

    # pass 1: parse + check everything before touching DST
    plan, errors, n_unlisted, stamps = {}, [], {}, {}
    for c in cams:
        entries, errs, warns, unl = read_cam(mav0 / c, delta_ns)
        for w in warns:
            warn(w)
        errors += errs
        plan[c], n_unlisted[c] = entries, unl
        stamps[c] = [e[1] for e in entries if e[0] == "row"]
    if errors:
        for e in errors[:20]:
            print(f"euroc-shift: ERROR: {e}", file=sys.stderr)
        fail(f"{len(errors)} inconsistencies in {src}, nothing written")
    ref = "cam0" if "cam0" in cams else cams[0]
    for c in cams:
        if c != ref and set(stamps[c]) != set(stamps[ref]):
            only_ref, only_c = len(set(stamps[ref]) - set(stamps[c])), len(set(stamps[c]) - set(stamps[ref]))
            warn(f"{c} rows differ from {ref}: {only_ref} stamps only in {ref}, {only_c} only in {c} "
                 f"(Basalt drops a frame when any camera lacks {ref}'s file)")

    # DST. --force only ever removes what this tool wrote (euroc-shift.json is the marker) or an
    # empty dir: a genuine recording has mav0/ too, and ~3 GB of an irreplaceable wearer session
    # is not a thing to rmtree by a slip of --dst. And nothing SRC links to may live under DST
    # (SRC being an earlier shift copy OF dst, say): removing DST would take the real images.
    if dst.is_symlink() or dst.exists():
        if not a.force:
            fail(f"{dst} exists (use --force to replace it)")
        if dst.is_symlink() or not dst.is_dir():
            fail(f"{dst} is not a directory, refusing --force")
        if any(dst.iterdir()) and not (dst / "euroc-shift.json").is_file():
            fail(f"{dst} is not a euroc-shift copy (no euroc-shift.json), refusing --force")
        inside = [t for t in link_targets(src, mav0, cams, plan) if t == dst_real or dst_real in t.parents]
        if inside:
            fail(f"{len(inside)} of the files the copy would link to resolve inside {dst} (first: "
                 f"{inside[0]}); removing it would destroy them, refusing --force")
        shutil.rmtree(dst)
    (dst / "mav0").mkdir(parents=True)
    linked, copied = [], []
    for p in sorted(mav0.iterdir()):
        if p.name in cams:
            build_cam(p, dst / "mav0" / p.name, plan[p.name], delta_ns)
        else:
            os.symlink(os.path.realpath(p), dst / "mav0" / p.name)
            linked.append(p.name)
    for p in sorted(src.iterdir()):
        if p.name == "mav0":
            continue
        if p.is_file() and not p.is_symlink():
            shutil.copy2(p, dst / p.name)
            copied.append(p.name)
        else:
            os.symlink(os.path.realpath(p), dst / p.name)
            linked.append(p.name)

    # pass 2: verify DST the way the readers will read it
    frames = {}
    for c in cams:
        n, bad = verify_cam(dst / "mav0" / c)
        if bad or n != len(stamps[c]):
            for b in bad[:20]:
                print(f"euroc-shift: ERROR: {c}: {b}", file=sys.stderr)
            fail(f"{dst}/mav0/{c}: verification failed ({len(bad)} bad rows, {n} of {len(stamps[c])} rows) -- "
                 f"DST left in place for inspection")
        frames[c] = n

    prov = {"tool": "euroc-shift.py", "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "src": str(src),
            "dst": str(dst), "ms": a.ms, "delta_ns": delta_ns, "cams_shifted": cams, "frames": frames,
            "unchanged_linked": linked, "copied": copied,
            "note": "images are absolute symlinks into src; regenerate with euroc-shift.py rather than archiving"}
    with open(dst / "euroc-shift.json", "w") as f:
        json.dump(prov, f, indent=1)
        f.write("\n")

    t0, t1 = stamps[ref][0], stamps[ref][-1]
    counts = "/".join(str(frames[c]) for c in cams)
    unl = max(n_unlisted.values())
    print(f"euroc-shift: {len(cams)} cams ({' '.join(cams)}) x {counts} frames, shift {a.ms:g} ms = {delta_ns:+d} ns; "
          f"{ref} t_ns {t0}..{t1} -> {t0 + delta_ns}..{t1 + delta_ns} ({(t1 - t0) / 1e9:.1f} s); "
          f"unchanged (linked): {' '.join(linked) or '-'}; copied: {' '.join(copied) or '-'}"
          + (f"; {unl} image(s) per cam not listed in data.csv, ignored" if unl else "")
          + f" -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
