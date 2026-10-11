#!/usr/bin/env python3
"""
analyze-panel-judder.py — Rotational Judder Analyzer for the HP Reverb G2 Panel

THE RIG
--------
This script analyzes a high-frame-rate video of the HMD's display panel, filmed
THROUGH THE LENS with a phone or high-speed camera, while:

  1. The headset renders content at a fixed compositor refresh (default 90 Hz).
  2. A tracked controller (or any high-contrast marker) spins at constant speed on
     a turntable in view of the panel/render, so every displayed frame shows the
     marker at a visibly different angle.

Because the camera runs much faster than the panel refresh, each individual
displayed frame is captured by *several* consecutive camera frames before the
panel updates to the next one. Counting how many camera frames each displayed
frame "holds" for — and how that hold length varies — is a direct, physical
measurement of compositor judder: dropped frames, repeated frames, or irregular
reprojection timing. This bypasses the API layer entirely (Vulkan/OpenXR happily
reports a clean 90.0 fps while the panel itself skips frames), which is why this
project's rule is that timing claims must be verified by looking at the panel,
not by trusting driver logs.

EXPOSURE / CAPTURE GUIDANCE
----------------------------
  - Use the FASTEST shutter speed the camera allows. Motion blur smears the
    edges between displayed frames and makes transition detection unreliable.
  - Prefer 960-1080 fps slow-motion modes if the phone supports them. 240 fps is
    a usable floor but only gives ~2.6 camera frames per 90 Hz displayed frame,
    which is a thin margin for detecting single-frame holds.
  - CRITICAL: pick a --camera-fps that is NOT an exact integer multiple of
    --expected-hz. If it is (e.g. 180 fps filming a 90 Hz panel, or 240 fps
    filming a 120 Hz panel), every displayed frame tends to land on the same
    phase of the camera shutter and can alias into a falsely uniform hold-length
    histogram, hiding real single-frame drops. This script prints a WARNING when
    it detects this condition. 240 fps against 90 Hz (240/90 = 2.667) is fine;
    180 fps against 90 Hz (180/90 = 2.0 exactly) is not.
  - Keep the camera and the panel both static relative to each other; only the
    spinning marker should move in frame. Camera shake adds spurious diffs.

WHAT "HOLD LENGTH" MEANS
--------------------------
The script computes an inter-frame difference metric (mean absolute luminance
change) between consecutive camera frames, restricted to the ROI if given. A
sustained low-diff run means the camera is looking at the same displayed frame;
a sharp spike means the panel just updated (a "transition"). The number of
camera frames between two transitions is that displayed frame's hold length.

  - hold_ms ~= ideal period (1000/expected_hz)  -> normal, panel updating on time
  - hold_ms ~= 2x ideal period                  -> a dropped/missed frame
  - hold_ms ~= 0 / far below ideal period        -> spurious transition, likely
                                                    tearing, rolling-shutter
                                                    artifact, or an over-sensitive
                                                    threshold — inspect the plot

EXAMPLE INVOCATIONS
---------------------
  # Basic run, 240fps phone footage, default 90Hz expected refresh:
  ./analyze-panel-judder.py capture.mp4 --camera-fps 240

  # Restrict analysis to a panel sub-region (x,y,w,h in pixels) to avoid bezel
  # reflections, and save a CSV + plot:
  ./analyze-panel-judder.py capture.mp4 --camera-fps 240 --expected-hz 90 \\
      --roi 400,200,800,600 --output-csv holds.csv --output-plot holds.png

  # 960fps high-speed capture:
  ./analyze-panel-judder.py capture_hs.mov --camera-fps 960 --expected-hz 90

Dependencies: opencv-python, numpy (required); matplotlib (only required if
--output-plot is used). Install with:
  pip install opencv-python numpy matplotlib
"""

import argparse
import csv
import sys

try:
    import numpy as np
except ImportError:
    print(
        "ERROR: numpy is required but not installed.\n"
        "Install it with:  pip install opencv-python numpy matplotlib",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import cv2
except ImportError:
    print(
        "ERROR: opencv-python is required but not installed.\n"
        "Install it with:  pip install opencv-python numpy matplotlib",
        file=sys.stderr,
    )
    sys.exit(1)


# ==============================================================================
# CLI
# ==============================================================================
def parse_roi(value):
    """Parse a --roi argument of the form 'x,y,w,h' into a tuple of ints."""
    try:
        parts = [int(p.strip()) for p in value.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid --roi '{value}': expected four integers 'x,y,w,h'"
        )
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"invalid --roi '{value}': expected four integers 'x,y,w,h', got {len(parts)}"
        )
    x, y, w, h = parts
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f"invalid --roi '{value}': width/height must be > 0")
    return (x, y, w, h)


def build_argparser():
    p = argparse.ArgumentParser(
        prog="analyze-panel-judder.py",
        description=(
            "Analyze a high-frame-rate through-the-lens video of an HMD panel to "
            "quantify rotational judder at a given compositor refresh rate, by "
            "measuring how many camera frames each distinct displayed frame holds for."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("video", help="Path to the input video file (e.g. capture.mp4).")
    p.add_argument(
        "--camera-fps",
        type=float,
        required=True,
        help=(
            "Actual capture frame rate of the camera in fps (e.g. 240, 960, 1000). "
            "This is the ground-truth camera rate, not necessarily what the video "
            "container's metadata reports (slow-motion clips are often re-timed "
            "on export) — use the rate the camera actually shot at."
        ),
    )
    p.add_argument(
        "--expected-hz",
        type=float,
        default=90.0,
        help="Expected compositor/panel refresh rate in Hz (default: 90).",
    )
    p.add_argument(
        "--roi",
        type=parse_roi,
        default=None,
        metavar="x,y,w,h",
        help=(
            "Restrict analysis to a rectangular region of interest within the "
            "frame, in pixel coordinates 'x,y,w,h'. Use this to crop out the "
            "lens bezel / hotspot reflections and keep only panel content."
        ),
    )
    p.add_argument(
        "--output-plot",
        default=None,
        metavar="PATH",
        help="Optional path to save a PNG plot (hold-length timeseries + histogram). "
        "Requires matplotlib.",
    )
    p.add_argument(
        "--output-csv",
        default=None,
        metavar="PATH",
        help="Optional path to save a CSV with one row per detected displayed frame.",
    )
    p.add_argument(
        "--threshold-k",
        type=float,
        default=5.0,
        help=(
            "Sensitivity of the adaptive transition threshold, expressed as a "
            "multiple of the robust noise scale (median absolute deviation) above "
            "the median frame-to-frame diff. Lower values detect more transitions "
            "(more sensitive, more prone to false positives from noise/motion blur); "
            "higher values are more conservative. Default: 5.0."
        ),
    )
    p.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional cap on the number of camera frames to read (for quick tests "
        "on long recordings).",
    )
    return p


# ==============================================================================
# Frame reading / signal extraction
# ==============================================================================
def read_roi_signal(video_path, roi, max_frames=None):
    """
    Stream the video and, for each frame, compute:
      - mean luminance of the ROI (float)
      - the mean absolute luminance difference vs. the previous frame (float),
        i.e. the transition-detection signal.

    Returns (luminance: np.ndarray[N], diffs: np.ndarray[N-1], n_frames: int,
    reported_fps: float, frame_size: (w, h)).

    Frames are converted to grayscale before computing both metrics; this is a
    brightness/contrast signature, not a full perceptual similarity metric, but
    it is fast, robust to the small color-fringing artifacts common on
    low-persistence panels, and sufficient to detect a discrete panel update.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: could not open video file: {video_path}", file=sys.stderr)
        sys.exit(1)

    reported_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    luminance = []
    diffs = []
    prev_gray = None
    n = 0

    while True:
        if max_frames is not None and n >= max_frames:
            break
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if roi is not None:
            x, y, w, h = roi
            fh, fw = gray.shape[:2]
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(fw, x + w), min(fh, y + h)
            if x0 >= x1 or y0 >= y1:
                cap.release()
                print(
                    f"ERROR: --roi {x},{y},{w},{h} does not overlap the "
                    f"{fw}x{fh} video frame.",
                    file=sys.stderr,
                )
                sys.exit(1)
            gray = gray[y0:y1, x0:x1]

        gray_f = gray.astype(np.float32)
        luminance.append(float(gray_f.mean()))

        if prev_gray is not None:
            diff = float(np.mean(np.abs(gray_f - prev_gray)))
            diffs.append(diff)

        prev_gray = gray_f
        n += 1

    cap.release()

    if n < 2:
        print(
            f"ERROR: only read {n} frame(s) from '{video_path}'; need at least 2 "
            "to detect any transitions.",
            file=sys.stderr,
        )
        sys.exit(1)

    return (
        np.array(luminance, dtype=np.float64),
        np.array(diffs, dtype=np.float64),
        n,
        reported_fps,
        (frame_w, frame_h),
    )


# ==============================================================================
# Transition detection -> hold lengths
# ==============================================================================
def detect_transitions(diffs, camera_fps, expected_hz, threshold_k):
    """
    Detect displayed-frame transitions in the diff signal using an adaptive
    threshold, then derive hold lengths (in camera frames) between consecutive
    transitions.

    Adaptive threshold: median(diffs) + threshold_k * MAD(diffs), where MAD is
    the median absolute deviation (a robust, outlier-resistant noise-scale
    estimator). This adapts to each clip's own noise floor (compression
    artifacts, sensor noise, ambient flicker) instead of a fixed brightness
    threshold that would need re-tuning per recording.

    A minimum gap between accepted transitions (~30% of the ideal camera-frames-
    per-displayed-frame ratio) prevents a single real transition — which can
    smear across 2 camera frames due to rolling shutter or motion blur — from
    being double-counted as two short holds.

    Returns (transition_frames: list[int], threshold: float).
    transition_frames are camera-frame indices at which a NEW displayed frame
    begins (index 0 is always included as the start of the first held frame).
    """
    if len(diffs) == 0:
        return [0], 0.0

    median = float(np.median(diffs))
    mad = float(np.median(np.abs(diffs - median)))
    # Fallback for near-static/noise-free clips where MAD collapses to ~0:
    # use standard deviation instead so the threshold doesn't degenerate to
    # "any nonzero diff is a transition".
    noise_scale = mad if mad > 1e-6 else float(np.std(diffs))
    if noise_scale <= 1e-6:
        noise_scale = 1e-6  # fully static input; avoid a zero threshold
    threshold = median + threshold_k * noise_scale

    ideal_hold_frames = camera_fps / expected_hz if expected_hz > 0 else 1.0
    min_gap = max(1, int(round(ideal_hold_frames * 0.3)))

    transitions = [0]
    last = 0
    for i, d in enumerate(diffs):
        candidate_frame = i + 1  # diffs[i] is the diff between frame i and i+1
        if d > threshold and (candidate_frame - last) >= min_gap:
            transitions.append(candidate_frame)
            last = candidate_frame

    return transitions, threshold


def hold_lengths_from_transitions(transitions, total_frames):
    """
    Convert a list of transition start-indices into (start_frame, hold_frames,
    is_incomplete) tuples. The final segment is marked incomplete because its
    true end is cut off by the end of the recording, not a detected transition.
    """
    segments = []
    for k in range(len(transitions)):
        start = transitions[k]
        end = transitions[k + 1] if k + 1 < len(transitions) else total_frames
        hold = end - start
        is_incomplete = k + 1 >= len(transitions)
        segments.append((start, hold, is_incomplete))
    return segments


# ==============================================================================
# Analysis / classification
# ==============================================================================
def classify_segments(segments, camera_fps, expected_hz):
    """
    Attach hold_ms and an anomaly classification to each segment.
    Returns a list of dicts, and excludes the final incomplete segment from
    the returned "complete" list used for statistics (it is still included in
    the full list for CSV output, tagged accordingly).

    Classification thresholds:
      - "dropped": hold_ms >= 1.5x the ideal period (a displayed frame held
        roughly 2x as long as it should -> the compositor missed a frame).
      - "short": hold_ms <= 0.5x the ideal period (a suspiciously brief hold ->
        likely tearing, a rolling-shutter artifact, or threshold noise).
      - "normal": everything else.
      - "incomplete": the trailing segment cut off by end-of-video; excluded
        from summary statistics.
    """
    ideal_period_ms = 1000.0 / expected_hz if expected_hz > 0 else float("nan")
    rows = []
    for idx, (start, hold, incomplete) in enumerate(segments):
        hold_ms = hold / camera_fps * 1000.0
        if incomplete:
            status = "incomplete"
        elif hold_ms >= 1.5 * ideal_period_ms:
            status = "dropped"
        elif hold_ms <= 0.5 * ideal_period_ms:
            status = "short"
        else:
            status = "normal"
        rows.append(
            {
                "index": idx,
                "start_camera_frame": start,
                "hold_frames": hold,
                "hold_ms": hold_ms,
                "is_anomaly": status,
            }
        )
    return rows, ideal_period_ms


def print_summary(rows, camera_fps, expected_hz, ideal_period_ms, threshold):
    complete = [r for r in rows if r["is_anomaly"] != "incomplete"]
    n_incomplete = len(rows) - len(complete)

    print("=" * 70)
    print("PANEL JUDDER ANALYSIS SUMMARY")
    print("=" * 70)
    print(f"Camera capture rate      : {camera_fps:.3f} fps")
    print(f"Expected panel refresh   : {expected_hz:.3f} Hz  (ideal period {ideal_period_ms:.3f} ms)")
    print(f"Adaptive diff threshold  : {threshold:.4f}")
    print(f"Total displayed frames   : {len(complete)}  (+{n_incomplete} incomplete trailing segment"
          f"{'s' if n_incomplete != 1 else ''} excluded from stats)")

    if not complete:
        print("\nNo complete displayed-frame segments were detected. Try a lower "
              "--threshold-k, check --roi, or verify the clip actually shows panel "
              "content changing.")
        print("=" * 70)
        return

    holds_ms = np.array([r["hold_ms"] for r in complete])
    holds_frames = np.array([r["hold_frames"] for r in complete])

    mean_ms = float(np.mean(holds_ms))
    median_ms = float(np.median(holds_ms))
    std_ms = float(np.std(holds_ms))
    min_ms = float(np.min(holds_ms))
    max_ms = float(np.max(holds_ms))
    effective_hz = 1000.0 / mean_ms if mean_ms > 0 else float("nan")

    dropped = [r for r in complete if r["is_anomaly"] == "dropped"]
    short = [r for r in complete if r["is_anomaly"] == "short"]

    print(f"\nHold length (camera frames): mean={np.mean(holds_frames):.2f}  "
          f"median={np.median(holds_frames):.1f}  std={np.std(holds_frames):.2f}  "
          f"min={holds_frames.min()}  max={holds_frames.max()}")
    print(f"Hold length (ms)           : mean={mean_ms:.3f}  median={median_ms:.3f}  "
          f"std={std_ms:.3f}  min={min_ms:.3f}  max={max_ms:.3f}")
    print(f"Measured effective refresh : {effective_hz:.3f} Hz  "
          f"(target: {expected_hz:.3f} Hz, {'OK' if abs(effective_hz - expected_hz) < 0.05 * expected_hz else 'DEVIATES'})")

    print(f"\nDropped frames (~2x hold)  : {len(dropped)}  "
          f"({100.0 * len(dropped) / len(complete):.2f}% of displayed frames)")
    print(f"Short/spurious holds       : {len(short)}  "
          f"({100.0 * len(short) / len(complete):.2f}% of displayed frames)")

    if dropped:
        print("\nDropped-frame timestamps (camera-frame index -> time in s):")
        for r in dropped:
            t = r["start_camera_frame"] / camera_fps
            print(f"    frame {r['start_camera_frame']:>7d}  ->  t = {t:8.3f}s  "
                  f"hold = {r['hold_frames']} frames ({r['hold_ms']:.2f} ms)")

    if short:
        print("\nShort/spurious-hold timestamps (camera-frame index -> time in s):")
        for r in short:
            t = r["start_camera_frame"] / camera_fps
            print(f"    frame {r['start_camera_frame']:>7d}  ->  t = {t:8.3f}s  "
                  f"hold = {r['hold_frames']} frames ({r['hold_ms']:.2f} ms)")

    print("=" * 70)


def check_aliasing_risk(camera_fps, expected_hz):
    """
    CRITICAL correctness check: if camera_fps is (near) an exact integer
    multiple of expected_hz, every displayed frame tends to be sampled at the
    same phase of the camera shutter cycle. This can make hold lengths look
    deceptively uniform and HIDE real single-frame drops/repeats — the
    equivalent of stroboscopic aliasing. Always prefer a non-multiple camera
    rate (e.g. 240 fps for a 90 Hz panel: 240/90 = 2.667, not an integer).
    """
    if expected_hz <= 0:
        return
    ratio = camera_fps / expected_hz
    nearest_int = round(ratio)
    if nearest_int > 0 and abs(ratio - nearest_int) < 0.02:
        print(
            f"WARNING: --camera-fps ({camera_fps:g}) is approximately an exact "
            f"integer multiple ({nearest_int}x) of --expected-hz ({expected_hz:g}). "
            "This can alias real dropped/repeated frames into a falsely uniform "
            "hold-length pattern, hiding judder instead of revealing it. Re-film "
            "with a non-multiple camera rate if possible (e.g. 240 fps for a 90 Hz "
            "panel, not 180 fps).",
            file=sys.stderr,
        )


# ==============================================================================
# Output: CSV / plot
# ==============================================================================
def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["index", "start_camera_frame", "hold_frames", "hold_ms", "is_anomaly"]
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "index": r["index"],
                    "start_camera_frame": r["start_camera_frame"],
                    "hold_frames": r["hold_frames"],
                    "hold_ms": f"{r['hold_ms']:.4f}",
                    "is_anomaly": r["is_anomaly"],
                }
            )
    print(f"CSV written to: {path}")


def write_plot(path, rows, ideal_period_ms, expected_hz):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "ERROR: matplotlib is required for --output-plot but is not installed.\n"
            "Install it with:  pip install opencv-python numpy matplotlib",
            file=sys.stderr,
        )
        return

    complete = [r for r in rows if r["is_anomaly"] != "incomplete"]
    if not complete:
        print("No complete segments to plot.", file=sys.stderr)
        return

    indices = [r["index"] for r in complete]
    holds_ms = [r["hold_ms"] for r in complete]
    colors = {"normal": "#3b7dd8", "dropped": "#d84b3b", "short": "#d8a83b"}
    point_colors = [colors[r["is_anomaly"]] for r in complete]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    ax1.scatter(indices, holds_ms, c=point_colors, s=14)
    ax1.axhline(ideal_period_ms, color="gray", linestyle="--", linewidth=1,
                label=f"ideal period ({ideal_period_ms:.2f} ms @ {expected_hz:g} Hz)")
    ax1.axhline(2 * ideal_period_ms, color="#d84b3b", linestyle=":", linewidth=1,
                label="2x ideal (dropped-frame threshold)")
    ax1.set_xlabel("Displayed frame index")
    ax1.set_ylabel("Hold length (ms)")
    ax1.set_title("Hold length per displayed frame")
    ax1.legend(fontsize=8)

    ax2.hist(holds_ms, bins=40, color="#3b7dd8", edgecolor="white")
    ax2.axvline(ideal_period_ms, color="gray", linestyle="--", linewidth=1)
    ax2.set_xlabel("Hold length (ms)")
    ax2.set_ylabel("Count")
    ax2.set_title("Hold length distribution")

    fig.suptitle("Panel Judder Analysis")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Plot written to: {path}")


# ==============================================================================
# Main
# ==============================================================================
def main():
    args = build_argparser().parse_args()

    if args.camera_fps <= 0:
        print("ERROR: --camera-fps must be > 0", file=sys.stderr)
        sys.exit(1)
    if args.expected_hz <= 0:
        print("ERROR: --expected-hz must be > 0", file=sys.stderr)
        sys.exit(1)

    check_aliasing_risk(args.camera_fps, args.expected_hz)

    print(f"Reading video: {args.video}")
    luminance, diffs, n_frames, reported_fps, frame_size = read_roi_signal(
        args.video, args.roi, args.max_frames
    )
    print(f"  frame size            : {frame_size[0]}x{frame_size[1]}")
    print(f"  frames read           : {n_frames}")
    if reported_fps > 0:
        print(f"  container-reported fps: {reported_fps:.3f}  "
              f"(--camera-fps={args.camera_fps:g} is used for all timing math)")
        if abs(reported_fps - args.camera_fps) > 0.5:
            print(
                "  NOTE: container-reported fps differs from --camera-fps. Slow-motion "
                "clips are frequently re-timed on export (e.g. exported as 30fps "
                "playback of 240fps-captured footage) — make sure --camera-fps reflects "
                "the true CAPTURE rate, not the playback rate.",
                file=sys.stderr,
            )

    transitions, threshold = detect_transitions(
        diffs, args.camera_fps, args.expected_hz, args.threshold_k
    )
    segments = hold_lengths_from_transitions(transitions, n_frames)
    rows, ideal_period_ms = classify_segments(segments, args.camera_fps, args.expected_hz)

    print_summary(rows, args.camera_fps, args.expected_hz, ideal_period_ms, threshold)

    if args.output_csv:
        write_csv(args.output_csv, rows)

    if args.output_plot:
        write_plot(args.output_plot, rows, ideal_period_ms, args.expected_hz)


if __name__ == "__main__":
    main()
