#!/usr/bin/env python3
"""Compare the LED-ring brightness of two WMR controllers from ONE photograph.

WHY ONE PHOTOGRAPH AND NOT TWO: with both rings in the same frame the comparison is relative,
so ISO, shutter, white balance and the sensor's response curve all cancel. Two separate photos
would need absolute calibration, which a phone camera cannot give.

WHAT IT STILL CANNOT CANCEL, and this is the finding that matters (reverb-g2 T229): GEOMETRY.
The first real capture had the two rings 8% apart in apparent radius -- 8% further away is 16%
dimmer by inverse square -- while the brightness difference being measured was 6%. The
systematic was larger than the signal. The fix costs one more photo: shoot again with the
controllers' POSITIONS SWAPPED. If the brighter ring follows the controller it is real; if it
follows the position it was geometry. This script prints the ring radii precisely so that
comparison can be made instead of assumed.

CHANNEL CHOICE: the script measures whichever channel is not clipped, preferring green. IR
leaking through a phone's Bayer filter saturates blue first -- measured 279 clipped pixels in
blue against zero in green on the first capture -- so blue is usually the wrong channel and
"the photo looks fine" is not evidence that it is.

GAMMA: sRGB values are gamma-encoded, so summing them is not summing light. Values are
linearised (^2.2) before integration; a ratio taken on raw 8-bit sums would be wrong.

  ./scripts/led-ring-photometry.py photo.jpg
  ./scripts/led-ring-photometry.py photo.jpg --split 480   # x that separates the two rings
"""

import argparse
import sys

import numpy as np

try:
    from PIL import Image
    from scipy import ndimage
except ImportError as e:  # pragma: no cover
    sys.exit(f"needs python3-pil and python3-scipy: {e}")


def blobs(rgb, chan, thresh, min_area):
    g = rgb[:, :, chan]
    bg = float(np.median(g))
    lab, _ = ndimage.label(rgb.max(axis=2) > thresh)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        m = lab[sl] == i
        if m.sum() < min_area:
            continue
        ys, xs = np.nonzero(m)
        vals = g[sl][m]
        out.append(
            dict(
                cx=sl[1].start + xs.mean(),
                cy=sl[0].start + ys.mean(),
                area=int(m.sum()),
                peak=float(vals.max()),
                # Linearise before summing: gamma-encoded sums are not proportional to light.
                flux=float((np.clip((vals - bg) / 255.0, 0, None) ** 2.2).sum()),
            )
        )
    return out


def ring_stats(sel):
    cx = np.array([r["cx"] for r in sel])
    cy = np.array([r["cy"] for r in sel])
    radii = np.hypot(cx - cx.mean(), cy - cy.mean())
    return dict(
        n=len(sel),
        radius=float(radii.mean()),
        radius_sd=float(radii.std()),
        area=float(np.mean([r["area"] for r in sel])),
        peak=float(np.mean([r["peak"] for r in sel])),
        flux=float(np.mean([r["flux"] for r in sel])),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--split", type=int, default=None, help="x coordinate separating the rings (default: image centre)")
    ap.add_argument("--threshold", type=int, default=60, help="pixel value that counts as LED (default 60)")
    ap.add_argument("--min-area", type=int, default=3, help="ignore blobs smaller than this (default 3 px)")
    ap.add_argument("--compressed-at", type=int, default=240,
                    help="peak at or above this counts as a compressed core (default 240)")
    args = ap.parse_args()

    rgb = np.asarray(Image.open(args.image).convert("RGB")).astype(np.float64)
    split = args.split if args.split is not None else rgb.shape[1] // 2

    print("== clipping ==")
    chan, best = 1, None
    for i, name in enumerate("RGB"):
        clipped = int((rgb[:, :, i] >= 255).sum())
        print(f"  {name}: max {rgb[:, :, i].max():3.0f}  pixels at 255: {clipped}")
        if best is None or clipped < best:
            best, chan = clipped, i
    print(f"  measuring channel {'RGB'[chan]} (fewest clipped pixels)")
    if best > 0:
        print("  NOTE: even the best channel clips -- lower the exposure and reshoot; peak-based")
        print("        comparisons are not trustworthy above the ceiling.")

    found = blobs(rgb, chan, args.threshold, args.min_area)
    left = [r for r in found if r["cx"] < split]
    right = [r for r in found if r["cx"] >= split]
    if not left or not right:
        sys.exit(f"found {len(left)} blobs left of x={split} and {len(right)} right -- pass --split")

    for name, sel in (("LEFT in frame", left), ("RIGHT in frame", right)):
        s = ring_stats(sel)
        comp = sum(1 for r in sel if r["peak"] >= args.compressed_at)
        print(f"\n== {name} ==")
        print(f"  LEDs {s['n']}   ring radius {s['radius']:.1f} px (sd {s['radius_sd']:.1f} -- higher = more tilt)")
        print(f"  area mean {s['area']:.1f} px   peak mean {s['peak']:.1f}   compressed cores {comp}/{s['n']}")
        print(f"  linearised flux mean {s['flux']:.4f}")

    ls, rs = ring_stats(left), ring_stats(right)
    clean_l = [r for r in left if r["peak"] < args.compressed_at]
    clean_r = [r for r in right if r["peak"] < args.compressed_at]
    dist = (ls["radius"] / rs["radius"]) ** 2

    print("\n== right / left ==")
    print(f"  flux, all LEDs            {rs['flux'] / ls['flux']:.2f}x")
    if clean_l and clean_r:
        cl = float(np.mean([r["flux"] for r in clean_l]))
        cr = float(np.mean([r["flux"] for r in clean_r]))
        print(f"  flux, uncompressed only   {cr / cl:.2f}x   ({len(clean_r)} vs {len(clean_l)} LEDs)")
    print(f"  area                      {rs['area'] / ls['area']:.2f}x")
    print(f"  flux corrected for range  {rs['flux'] / ls['flux'] * dist:.2f}x   "
          f"(right ring is {100 * (ls['radius'] / rs['radius'] - 1):+.0f}% further)")
    print(f"\n  GEOMETRY SYSTEMATIC: {100 * (dist - 1):+.0f}%.  MEASURED DIFFERENCE: "
          f"{100 * (rs['flux'] / ls['flux'] - 1):+.0f}%.")
    if abs(dist - 1) >= abs(rs["flux"] / ls["flux"] - 1):
        print("  The systematic is LARGER than the signal: this photo cannot decide. Reshoot with")
        print("  the controllers' positions swapped -- that cancels range, angle and lens falloff.")


if __name__ == "__main__":
    main()
