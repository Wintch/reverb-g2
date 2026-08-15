#!/usr/bin/env python3
"""Fit the controller-local axis of a calibration roll from Monado CALIB logs."""
import re
import sys
import numpy as np

LINE = re.compile(
    r"CALIB hand=(left|right).*?pos_tracked=(\d).*?q_imu=\(([^)]+)\)"
)

def qmul(a, b):
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return np.array((w1*x2 + x1*w2 + y1*z2 - z1*y2,
                     w1*y2 - x1*z2 + y1*w2 + z1*x2,
                     w1*z2 + x1*y2 - y1*x2 + z1*w2,
                     w1*w2 - x1*x2 - y1*y2 - z1*z2))

def qinv(q):
    return np.array((-q[0], -q[1], -q[2], q[3])) / np.dot(q, q)

path = sys.argv[1] if len(sys.argv) > 1 else "/home/iam/vr/jack-in-wayland.log"
hand = sys.argv[2] if len(sys.argv) > 2 else "left"
samples = []
with open(path, encoding="utf-8", errors="replace") as f:
    for line in f:
        m = LINE.search(line)
        if not m or m.group(1) != hand:
            continue
        q = np.fromstring(m.group(3), sep=",")
        if len(q) == 4 and np.isfinite(q).all():
            q /= np.linalg.norm(q)
            samples.append((int(m.group(2)), q))

# Use only the final continuous run and ignore placeholder-position samples when a
# sufficiently long tracked run exists. The orientation remains useful during gaps,
# but position-tracked samples are the safest anchor for choosing the calibration window.
tracked = [q for tracked, q in samples if tracked]
if len(tracked) >= 20:
    samples = [(t, q) for t, q in samples if t]

axes = []
for (_, a), (_, b) in zip(samples, samples[1:]):
    if np.dot(a, b) < 0:
        b = -b
    d = qmul(qinv(a), b)
    v = d[:3]
    angle = 2.0 * np.arctan2(np.linalg.norm(v), abs(d[3]))
    if angle < np.deg2rad(2.0):
        continue
    v /= np.linalg.norm(v)
    if np.dot(v, axes[-1]) < 0 if axes else False:
        v = -v
    axes.append(v)

if len(axes) < 5:
    raise SystemExit("not enough rotation samples")

cov = np.zeros((3, 3))
for v in axes:
    cov += np.outer(v, v)
vals, vecs = np.linalg.eigh(cov)
axis = vecs[:, np.argmax(vals)]
if np.dot(axis, np.mean(axes, axis=0)) < 0:
    axis = -axis

print(f"hand={hand} samples={len(samples)} rotation_steps={len(axes)}")
print("controller-local roll axis from IMU: " + " ".join(f"{x:+.5f}" for x in axis))
print("This axis should map to the controller's physical longitudinal axis; do not apply it yet without the stationary-pose anchor.")

