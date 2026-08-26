#!/usr/bin/env python3
"""Look for a periodic frame-timing artifact in a video of the G2 panel.

Filmed with an action camera pointed at the headset's own panel while a human wears it,
this looks for a repeating micro-judder in SLAM (6dof) mode that a wearer described feeling
but that wasn't reported in 3dof mode. Two candidate periods, both already measured
elsewhere in this project and NOT guesses:

  - anchor age 119-189 ms (5.3-8.4 Hz): Monado's `predict_pose` log lines
    ("pred: anchor age 164.9 ms" in ~/vr/jack-in-wayland.log) show the SLAM pose fused into
    the continuous prediction is periodically this stale when it lands.
  - SLAM pose rate ~21-30 Hz (33-48 ms): the underlying camera/SLAM update rate measured
    elsewhere in this project's docs. A different, also-plausible period for the same felt
    effect -- the anchor-age number is how OLD the correction is, not necessarily how OFTEN
    it recurs.

This script doesn't know which one (if either) is real; it just surfaces whatever
periodicity is actually in the footage so it can be compared to both.

METHOD: per-frame mean absolute pixel difference (downscaled grayscale) as a fast, robust
change metric -- optical flow was considered and skipped, a plain screen-recording of a
flickering/redrawing panel doesn't need it and diff is far less prone to needing per-clip
tuning. FFT (numpy) of the detrended diff signal, peak-picked by local maxima so multiple
distinct periods don't collapse into one blob, and each peak's power is compared to the
spectrum's median (the noise floor).

DEPENDENCY: needs `cv2` (opencv-python). Check first with `python3 -c "import cv2"` -- as
of 2026-08-26 this system has the C++ libopencv but NOT the Python bindings installed. This
script does not install anything itself; get them the normal way for this system
(e.g. `apt install python3-opencv`, or a venv with `pip install opencv-python-headless`)
before running it. numpy is already present.

Usage:
    ./video-frame-timing-analysis.py <video_path> [--roi x,y,w,h] [--top N]

--roi crops every frame to x,y,w,h BEFORE measuring, for footage where the camera also
caught the strap/surroundings and not just the panel.

Always writes <video_path>.diff.csv (timestamp_s,diff) next to the input -- the FFT step
can miss a real, non-periodic artifact (a single stutter), so the raw series is there to
eyeball regardless of what the FFT concludes.
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

# (label, period_lo_ms, period_hi_ms)
CANDIDATE_PERIODS_MS = [
    ("anchor age / SLAM fusion staleness (119-189 ms measured in jack-in-wayland.log)",
     119.0, 189.0),
    ("SLAM pose rate (~21-30 Hz measured elsewhere)", 33.0, 48.0),
]

DOWNSCALE_WIDTH = 160  # plenty to catch a panel-wide brightness/redraw event, keeps any clip length fast
MIN_FREQ_HZ = 0.5      # below this is drift/lighting, not the kind of periodicity we're hunting
NOISE_MULTIPLE = 3.0   # a peak must clear this multiple of the median spectrum power to count as "found"


def parse_roi(s):
    parts = s.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--roi expects x,y,w,h")
    return tuple(int(p) for p in parts)


def frame_diff_series(path, roi):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        sys.exit(f"could not open video (unreadable or unsupported codec): {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        sys.exit(f"camera reported an invalid fps ({fps}) -- can't convert bins to periods without it")

    diffs = []
    prev = None
    n_read = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        n_read += 1
        if roi:
            x, y, w, h = roi
            frame = frame[y:y + h, x:x + w]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        scale = DOWNSCALE_WIDTH / gray.shape[1]
        small = cv2.resize(gray, (DOWNSCALE_WIDTH, max(1, round(gray.shape[0] * scale))))
        if prev is not None:
            diffs.append(float(np.mean(np.abs(small - prev))))
        prev = small
    cap.release()
    if n_read < 10:
        sys.exit(f"only read {n_read} frame(s) from {path} -- too short for periodicity analysis")
    return fps, n_read, np.array(diffs)


def find_peaks(power):
    """Local maxima (power[i] > both neighbors), the endpoints included via a synthetic -inf pad.
    Real, distinct periodicities show up as separate bumps, not a top-N slice of one wide lobe."""
    padded = np.concatenate(([-np.inf], power, [-np.inf]))
    is_peak = (padded[1:-1] > padded[:-2]) & (padded[1:-1] > padded[2:])
    return np.nonzero(is_peak)[0]


def dominant_frequencies(diffs, fps, top_n):
    """FFT of the detrended, Hann-windowed diff signal. Returns (peaks, all_power) where
    peaks is a list of (freq_hz, period_ms, power), sorted by power descending, length <= top_n."""
    detrended = diffs - np.mean(diffs)
    n = len(detrended)
    spectrum = np.fft.rfft(detrended * np.hanning(n))
    freqs = np.fft.rfftfreq(n, d=1.0 / fps)
    power = np.abs(spectrum) ** 2

    keep = freqs >= MIN_FREQ_HZ
    freqs, power = freqs[keep], power[keep]
    if len(power) == 0:
        return [], power

    peak_idx = find_peaks(power)
    if len(peak_idx) == 0:
        peak_idx = np.arange(len(power))  # flat/monotonic spectrum: fall back to plain ranking
    peak_idx = peak_idx[np.argsort(power[peak_idx])[::-1][:top_n]]

    peaks = [(float(freqs[i]), 1000.0 / freqs[i], float(power[i])) for i in peak_idx]
    peaks.sort(key=lambda t: t[2], reverse=True)
    return peaks, power


def matching_candidate(period_ms):
    for label, lo, hi in CANDIDATE_PERIODS_MS:
        if lo <= period_ms <= hi:
            return label
    return None


def write_csv(video_path, fps, diffs):
    out_path = Path(str(video_path) + ".diff.csv")
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_s", "diff"])
        for i, d in enumerate(diffs):
            w.writerow([f"{(i + 1) / fps:.4f}", f"{d:.4f}"])
    return out_path


def main():
    if cv2 is None:
        sys.exit("cv2 is not installed -- see the DEPENDENCY note at the top of this script")

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video_path")
    ap.add_argument("--roi", type=parse_roi, default=None,
                     help="crop to x,y,w,h before measuring (e.g. --roi 200,100,800,600)")
    ap.add_argument("--top", type=int, default=5, help="how many FFT peaks to report (default 5)")
    args = ap.parse_args()

    video_path = Path(args.video_path)
    if not video_path.exists():
        sys.exit(f"no such file: {video_path}")

    fps, n_frames, diffs = frame_diff_series(video_path, args.roi)
    duration_s = n_frames / fps
    print(f"{video_path}: {n_frames} frames @ {fps:.3f} fps (camera-reported) = {duration_s:.1f} s")
    if args.roi:
        print(f"ROI: {args.roi}")

    mean, std, mx = float(np.mean(diffs)), float(np.std(diffs)), float(np.max(diffs))
    print(f"\ndiff metric (mean abs pixel diff, downscaled grayscale): "
          f"mean={mean:.3f} stdev={std:.3f} max={mx:.3f}")

    print("\ntop 10 largest frame-to-frame changes:")
    for idx in sorted(np.argsort(diffs)[::-1][:10]):
        print(f"  t={(idx + 1) / fps:8.3f}s  diff={diffs[idx]:.3f}")

    csv_path = write_csv(video_path, fps, diffs)
    print(f"\nraw diff series written to: {csv_path}  (eyeball this even if the FFT below finds nothing)")

    print("\ncandidate periods being checked for:")
    for label, lo, hi in CANDIDATE_PERIODS_MS:
        print(f"  {lo:.0f}-{hi:.0f} ms  ({1000/hi:.1f}-{1000/lo:.1f} Hz)  {label}")

    if len(diffs) < 20:
        print(f"\nonly {len(diffs)} samples -- too few for a meaningful FFT (need >= 20), stopping here")
        return 0

    peaks, power = dominant_frequencies(diffs, fps, args.top)
    if len(peaks) == 0:
        print("\nFFT produced no usable spectrum (clip too short relative to fps)")
        return 0

    noise_floor = float(np.median(power))
    print(f"\nFFT: top {len(peaks)} peak(s) (spectrum median / noise floor = {noise_floor:.3g}):")
    matches = []
    for freq, period_ms, p in peaks:
        ratio = p / noise_floor if noise_floor > 0 else float("inf")
        label = matching_candidate(period_ms)
        flag = f"  <-- matches candidate: {label}" if label else ""
        print(f"  {freq:6.2f} Hz  period {period_ms:7.2f} ms  power {p:.3g} ({ratio:5.1f}x noise floor){flag}")
        if label and ratio >= NOISE_MULTIPLE:
            matches.append((freq, period_ms, label, ratio))

    print("\n--- summary ---")
    top_freq, top_period, top_power = peaks[0]
    top_ratio = top_power / noise_floor if noise_floor > 0 else float("inf")
    if top_ratio < NOISE_MULTIPLE:
        print(f"no strong periodicity found (strongest peak is only {top_ratio:.1f}x the noise floor, "
              f"need >= {NOISE_MULTIPLE:.0f}x)")
    else:
        print(f"dominant period: {top_period:.1f} ms ({top_freq:.2f} Hz), {top_ratio:.1f}x noise floor")
    if matches:
        for freq, period_ms, label, ratio in matches:
            print(f"  MATCH: {period_ms:.1f} ms ({freq:.2f} Hz), {ratio:.1f}x noise floor -- {label}")
    else:
        print("  no peak above the noise floor matches either candidate SLAM-related period")
    return 0


if __name__ == "__main__":
    sys.exit(main())
