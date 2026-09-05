#!/usr/bin/env python3
"""qr-marker-watch.py -- decode which printed wall QR marker (if any) the WMR tracking
cameras currently see, and publish it as a small JSON status file, following this repo's
existing ~/vr/*.json convention (hmd-status.json, perf-metrics.json, camera-calibration.json).

WHY (2026-09-05): docs/105 built physical paper QR markers as a human disorientation aid for
the v0 passthrough viewer -- a person wearing the headset reads the marker like a text
landmark. This script answers a DIFFERENT, narrower question for the orchestrating agent, who
has no way to see the video feed: "which marker (if any) does the camera see right now" -- a
presence/identification check, NOT 6dof pose. Real-time SLAM-grade marker tracking was
already investigated and correctly scoped out in docs/105 as a multi-day project with no
existing runtime detector code anywhere in this stack; this script is not that. It only
decodes a QR payload string from a still frame, at most a few times a second.

INPUT: ~/vr/camera{0,1,2,3}.pgm, 640x480 8-bit grayscale (XRT_FORMAT_L8), written by
wmr_camera_dump_snapshot_pgm() (monado/src/xrt/drivers/wmr/wmr_camera.c) with a paired
camera{N}.pgm.ts sidecar (CLOCK_MONOTONIC nanoseconds of that exact frame). Confirmed live
2026-09-05: the driver only refreshes these dumps roughly once per second (not every
render frame), so this script's own default poll interval (0.75s) already sits close to
the source's real update rate -- there is no benefit to polling faster, and doing so would
just burn CPU re-decoding a frame that has not changed (guarded against below via the .ts
sidecar: a camera whose .ts is unchanged since the last cycle is skipped, not re-decoded).

DECODER CHOICE: pyzbar (a thin ctypes wrapper over libzbar, already present on this box as
libzbar0t64 0.23.93-8 -- only the *Python binding* was missing, not the library itself) was
A/B tested here against cv2.QRCodeDetector (bundled with the system python3-opencv this repo
already relies on elsewhere) on synthetic frames matching real camera noise levels: pyzbar
decoded correctly down to a ~50px marker span in a 640x480 frame, cv2's detector needed
~100px+ -- a real, repeatable ~3x advantage in workable range (27/54 vs 9/54 correct decodes
across a size/noise sweep), consistent with docs/105's own resolvability estimate that a
printed marker may only span 24-36px at 2-3m. Because PEP 668 blocks a system-wide `pip
install pyzbar` on this Debian/trixie box and there is no apt package for the *python*
binding installed (`python3-zbar` is a candidate, not installed, and installing it needs
sudo this project's agent does not have), pyzbar lives in a project-local venv
(`../.venv-qr`, `--system-site-packages` so it can still see the system numpy/cv2/PIL this
repo already depends on -- only pyzbar itself needed a fresh install). cv2.QRCodeDetector is
kept as an automatic runtime fallback (see decode_frame()) if pyzbar/the venv ever breaks --
degraded range, but the script keeps running rather than going dark.

An upscale+CLAHE "enhanced" retry pass was prototyped for the case where a raw decode finds
nothing, on the theory it might recover a marginal-size real photo. Measured live on this
box (2026-09-05): it is the dominant cost by far (~80ms/camera vs ~25ms/camera for the raw
attempt, since it re-scans a 4x-larger image) and the synthetic size/noise sweep showed it
recovering exactly zero additional decodes over the raw pass at any tested size. Given "no
heavy analysis during wearer sessions" is a standing project rule, it was cut from the
default per-cycle path rather than shipped as unproven 3-4x cost for no demonstrated
benefit -- see decode_frame() if a future real-marker test suggests it is worth reviving.

OUTPUT: ~/vr/qr-markers-status.json, written atomically (tmp + os.replace, same pattern
status-dashboard.py already uses for its own JSON files). Schema:

{
  "ts": 1788647466.12,              epoch seconds, when this cycle finished
  "poll_interval_s": 0.75,
  "decoder": "pyzbar" | "cv2.QRCodeDetector",   whichever path actually ran this cycle
  "cameras_checked": [0, 1, 2, 3],   cameras whose .pgm existed this cycle
  "detections": [
    {
      "camera": 0,                  which of the 4 WMR tracking cameras saw it (0-3) --
                                     itself a coarse facing-direction signal independent of
                                     which marker text was decoded, since the 4 cameras point
                                     in different fixed physical directions on the headset
      "payload": "https://github.com/Wintch/reverb-g2#w01-primera",
      "known": true,                false if the decoded text does not match any of the 7
                                     catalogued markers (still reported, never dropped --
                                     could be a new marker or a mis-decode worth seeing)
      "marker_id": "01",            present only when known
      "label": "primera pared",     present only when known
      "frame_age_s": 0.31           seconds between this camera's .pgm.ts and decode time
    }
  ],
  "markers_seen": ["01"],           sorted unique marker_id among KNOWN detections this cycle
  "cameras_with_marker": [0],       sorted unique camera index among ALL detections (known or
                                     not) this cycle -- the coarse facing-direction signal
  "cycle_ms": 8.4                   how long this cycle's decode work took (budget check)
}

An empty "detections" list is a normal, expected, correctly-reported state (no marker
currently in view) -- it is written every cycle just like every other field, never omitted,
so a caller can tell "checked, saw nothing" apart from "this file is stale/dead" (age of
"ts" is the latter check, left to the caller the same way rig_telemetry.py already leaves
staleness math to itself rather than the producer for every other ~/vr/*.json file).

USAGE
  One-shot, prints the result, does not write the status file's normal cadence loop:
    ../.venv-qr/bin/python3 qr-marker-watch.py --once

  Synthetic self-test (NOT a live-camera check -- see --once for that): generates each of
  the 7 real marker payloads as QR codes composited onto noisy 640x480 frames and confirms
  the decode path reads every one back correctly. Useful for confirming the venv/library
  path is healthy without needing a real marker in camera view:
    ../.venv-qr/bin/python3 qr-marker-watch.py --selftest

  Detached background loop (this repo's standard pattern -- never a foreground/attached ssh
  process, see feedback_detached_hardware_runs): start alongside the passthrough viewer,
  runs until killed.
    cd ~/Documents/reverb-g2 && setsid nohup .venv-qr/bin/python3 scripts/qr-marker-watch.py \\
        > ~/vr/qr-marker-watch.log 2>&1 < /dev/null & disown
  Stop:
    pkill -f qr-marker-watch.py
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

VR_DIR = Path.home() / "vr"
STATUS_FILE = VR_DIR / "qr-markers-status.json"
NUM_CAMERAS = 4
DEFAULT_INTERVAL_S = 0.75

# The 7 physical markers printed and hung 2026-09-05 (docs/105). Exact payload text is the
# only thing that identifies a marker -- keep this in sync with whatever is actually printed.
MARKERS = {
    "https://github.com/Wintch/reverb-g2#w01-primera": {
        "id": "01", "label": "primera pared (generic wall)"},
    "https://github.com/Wintch/reverb-g2#w02-frente": {
        "id": "02", "label": "pared de enfrente (generic wall)"},
    "https://github.com/Wintch/reverb-g2#w03-izquierda": {
        "id": "03", "label": "pared a la izquierda (generic wall)"},
    "https://github.com/Wintch/reverb-g2#w04-derecha": {
        "id": "04", "label": "pared a la derecha (generic wall)"},
    "CUIDADO: ESCALERA - zona de riesgo, reverb-g2 VR": {
        "id": "05", "label": "hazard: near the stairs"},
    "PISO - borde escalera, reverb-g2 VR": {
        "id": "06", "label": "floor: near the stairs' first step"},
    "CUIDADO: ESCALON - zona de riesgo, reverb-g2 VR": {
        "id": "07", "label": "hazard: near a separate loose step"},
}

try:
    from pyzbar.pyzbar import decode as _zbar_decode
    from pyzbar.pyzbar import ZBarSymbol as _ZBarSymbol
    _HAVE_ZBAR = True
except Exception:
    _HAVE_ZBAR = False

try:
    import cv2
    _HAVE_CV2 = True
except Exception:
    _HAVE_CV2 = False

try:
    from PIL import Image
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


def _load_gray(path):
    """Load a .pgm as a grayscale array/Image. Returns None on any problem (missing,
    mid-write, corrupt) -- never raises, same "no data yet" contract this repo's other
    ~/vr/*.json readers already use (see rig_telemetry.py)."""
    try:
        if _HAVE_PIL:
            img = Image.open(path)
            img.load()  # force full read now, while the fd is open
            return img
        if _HAVE_CV2:
            return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    except Exception:
        return None
    return None


def _cv2_array(img):
    """Get a numpy array out of whatever _load_gray returned, for the cv2/CLAHE fallback
    path (also used to feed pyzbar a PIL Image directly when available, which is cheaper)."""
    import numpy as np
    if _HAVE_PIL and hasattr(img, "convert"):
        return np.array(img.convert("L"))
    return img


def decode_frame(img):
    """Try pyzbar first (wider working range, see module docstring), fall back to
    cv2.QRCodeDetector if pyzbar is unavailable. Returns (list_of_decoded_strings, which).

    Deliberately single-pass, raw decode only -- see module docstring for the measured
    ~4x cost / zero measured benefit of an upscale+CLAHE retry pass, cut to keep this cheap
    enough to run through a live wearer session."""
    if _HAVE_ZBAR:
        try:
            # QRCODE-only: this project only ever prints QR markers, and restricting the
            # symbology cuts zbar's per-frame cost ~3x (measured live 2026-09-05: ~25ms ->
            # ~8ms per 640x480 frame) by skipping EAN/UPC/Code128/DataBar/etc scan passes --
            # as a side effect it also silences a harmless but noisy upstream zbar assertion
            # warning (decoder/databar.c) that fires when random camera noise looks briefly
            # like a GS1 DataBar candidate.
            results = _zbar_decode(img, symbols=[_ZBarSymbol.QRCODE])
            texts = [r.data.decode("utf-8", "replace") for r in results if r.data]
            return texts, "pyzbar"
        except Exception:
            pass  # fall through to cv2
    if _HAVE_CV2:
        try:
            arr = _cv2_array(img)
            ok, decoded_info, _points, _ = cv2.QRCodeDetector().detectAndDecodeMulti(arr)
            texts = [t for t in (decoded_info or []) if t] if ok else []
            return texts, "cv2.QRCodeDetector"
        except Exception:
            pass
    return [], "none"


def read_ts_ns(cam):
    ts_path = VR_DIR / f"camera{cam}.pgm.ts"
    try:
        return int(ts_path.read_text().strip())
    except Exception:
        return None


def run_cycle(last_ts):
    """One pass over all 4 cameras. `last_ts` is a dict this call mutates in place (camera
    index -> last-seen frame ts_ns), used to skip re-decoding a frame that has not changed
    since the previous cycle -- the dump only refreshes ~1x/s (see module docstring), so
    most 0.75s cycles will find nothing new and should do near-zero work."""
    cycle_start = time.monotonic()
    detections = []
    cameras_checked = []
    decoder_used = None

    for cam in range(NUM_CAMERAS):
        pgm_path = VR_DIR / f"camera{cam}.pgm"
        if not pgm_path.exists():
            continue
        cameras_checked.append(cam)

        ts_ns = read_ts_ns(cam)
        if ts_ns is not None and last_ts.get(cam) == ts_ns:
            continue  # unchanged since last cycle, nothing new to decode
        if ts_ns is not None:
            last_ts[cam] = ts_ns

        img = _load_gray(pgm_path)
        if img is None:
            continue

        texts, which = decode_frame(img)
        if texts:
            decoder_used = which
        now_mono = time.monotonic()
        for text in texts:
            marker = MARKERS.get(text)
            det = {
                "camera": cam,
                "payload": text[:200],
                "known": marker is not None,
            }
            if marker:
                det["marker_id"] = marker["id"]
                det["label"] = marker["label"]
            if ts_ns is not None:
                det["frame_age_s"] = round(now_mono - ts_ns / 1e9, 3)
            detections.append(det)

    result = {
        "ts": round(time.time(), 2),
        "poll_interval_s": None,  # filled in by caller
        "decoder": decoder_used or ("pyzbar" if _HAVE_ZBAR else
                                     "cv2.QRCodeDetector" if _HAVE_CV2 else "none"),
        "cameras_checked": cameras_checked,
        "detections": detections,
        "markers_seen": sorted({d["marker_id"] for d in detections if d.get("known")}),
        "cameras_with_marker": sorted({d["camera"] for d in detections}),
        "cycle_ms": round((time.monotonic() - cycle_start) * 1000, 1),
    }
    return result


def write_status(result, out_path):
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def selftest():
    """Synthetic sanity check -- NOT a live-camera confirmation. Generates each of the 7
    real marker payloads as a QR, composites it onto a noisy 640x480 grayscale frame (same
    size/noise-level ballpark as a real camera{N}.pgm), and confirms decode_frame() reads
    every one back exactly. Exits non-zero if any fail."""
    import numpy as np
    if not _HAVE_CV2:
        print("selftest needs cv2 to synthesize test QR codes (cv2.QRCodeEncoder)", file=sys.stderr)
        return 2
    enc = cv2.QRCodeEncoder.create()
    ok_count = 0
    for payload, meta in MARKERS.items():
        qr = enc.encode(payload)
        span = 110  # comfortably inside both decoders' working range, see module docstring
        rng = np.random.default_rng(hash(payload) % 10000)
        canvas = np.clip(rng.normal(150, 18, (480, 640)), 0, 255).astype(np.uint8)
        qr_resized = cv2.resize(qr, (span, span), interpolation=cv2.INTER_NEAREST)
        border = span // 10
        bordered = np.full((span + 2 * border, span + 2 * border), 255, dtype=np.uint8)
        bordered[border:border + span, border:border + span] = qr_resized
        y0, x0 = (480 - bordered.shape[0]) // 2, (640 - bordered.shape[1]) // 2
        canvas[y0:y0 + bordered.shape[0], x0:x0 + bordered.shape[1]] = bordered
        texts, which = decode_frame(canvas)
        got_ok = payload in texts
        ok_count += got_ok
        print(f"  marker {meta['id']} {'OK  ' if got_ok else 'FAIL'} via={which:20} "
              f"payload={payload[:50]!r}")
    total = len(MARKERS)
    print(f"\n{ok_count}/{total} synthetic decodes correct "
          f"(SYNTHETIC ONLY -- not a live-camera confirmation)")
    return 0 if ok_count == total else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S,
                     help=f"seconds between cycles (default {DEFAULT_INTERVAL_S}, see module "
                          f"docstring for why faster is pointless here)")
    ap.add_argument("--once", action="store_true",
                     help="run a single cycle, print the result, write the status file once, exit")
    ap.add_argument("--selftest", action="store_true",
                     help="synthetic decode-path sanity check, no camera files touched, no status file written")
    ap.add_argument("--out", default=str(STATUS_FILE), help="status file path (default: %(default)s)")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if not _HAVE_ZBAR and not _HAVE_CV2:
        print("neither pyzbar nor cv2 is importable -- nothing to decode with, exiting", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    last_ts = {}

    if args.once:
        result = run_cycle(last_ts)
        result["poll_interval_s"] = args.interval
        write_status(result, out_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"qr-marker-watch: polling every {args.interval}s, writing {out_path} "
          f"(decoder available: pyzbar={_HAVE_ZBAR} cv2={_HAVE_CV2})", flush=True)
    while True:
        loop_start = time.monotonic()
        try:
            result = run_cycle(last_ts)
            result["poll_interval_s"] = args.interval
            write_status(result, out_path)
        except Exception as e:
            # Never let a transient hiccup (camera file disappeared mid-read, etc.) kill the
            # loop -- log and keep going, same "stay up" philosophy as vr-power-watchdog.py.
            print(f"cycle error (continuing): {e}", file=sys.stderr, flush=True)
        elapsed = time.monotonic() - loop_start
        time.sleep(max(0.0, args.interval - elapsed))


if __name__ == "__main__":
    main()
