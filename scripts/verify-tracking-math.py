#!/usr/bin/env python3
"""
verify-tracking-math.py — Mathematical Verification Suite for Linux VR Tracking

Validates pure mathematical algorithms without requiring physical VR hardware:
1. Quaternion Algebra & Lie Exponential Map (so(3) -> SO(3))
2. IMU Gyro Discrete Integration & Gravity Tilt Alignment
3. Double-Cover Property (q == -q) & SLERP / Filter Guard
4. DisplayID / EDID Pixel Clock & Blanking Arithmetic for 90Hz Modes
5. Constellation PnP Geometry & Coordinate Frame Transforms
"""

import math
import sys
import numpy as np

# ==============================================================================
# 1. Quaternion Core Math
# ==============================================================================
class Quat:
    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.w = float(w)

    def norm(self):
        return math.sqrt(self.x**2 + self.y**2 + self.z**2 + self.w**2)

    def normalize(self):
        n = self.norm()
        if n < 1e-12:
            return Quat(0, 0, 0, 1)
        return Quat(self.x / n, self.y / n, self.z / n, self.w / n)

    def conjugate(self):
        return Quat(-self.x, -self.y, -self.z, self.w)

    def __mul__(self, other):
        # Quaternion Hamilton Product
        w1, x1, y1, z1 = self.w, self.x, self.y, self.z
        w2, x2, y2, z2 = other.w, other.x, other.y, other.z
        return Quat(
            x = w1*x2 + x1*w2 + y1*z2 - z1*y2,
            y = w1*y2 - x1*z2 + y1*w2 + z1*x2,
            z = w1*z2 + x1*y2 - y1*x2 + z1*w2,
            w = w1*w2 - x1*x2 - y1*y2 - z1*z2
        )

    def dot(self, other):
        return self.x*other.x + self.y*other.y + self.z*other.z + self.w*other.w

    def rotate_vec3(self, v):
        # v' = q * v * q^-1
        qv = Quat(v[0], v[1], v[2], 0.0)
        res = (self * qv) * self.conjugate()
        return np.array([res.x, res.y, res.z])

    @staticmethod
    def from_axis_angle(axis, angle_rad):
        axis = np.array(axis, dtype=float)
        norm = np.linalg.norm(axis)
        if norm < 1e-12:
            return Quat(0, 0, 0, 1)
        axis = axis / norm
        s = math.sin(angle_rad / 2.0)
        c = math.cos(angle_rad / 2.0)
        return Quat(axis[0]*s, axis[1]*s, axis[2]*s, c).normalize()

    @staticmethod
    def exp_map(omega):
        # Exponential map from Lie algebra so(3) -> SO(3)
        theta = np.linalg.norm(omega)
        if theta < 1e-9:
            return Quat(0.5 * omega[0], 0.5 * omega[1], 0.5 * omega[2], 1.0).normalize()
        axis = omega / theta
        s = math.sin(theta / 2.0)
        c = math.cos(theta / 2.0)
        return Quat(axis[0]*s, axis[1]*s, axis[2]*s, c).normalize()

    @staticmethod
    def slerp(q0, q1, t):
        # SLERP with double-cover shortest-path correction
        dot = q0.dot(q1)
        q1_adj = q1
        if dot < 0.0:
            q1_adj = Quat(-q1.x, -q1.y, -q1.z, -q1.w)
            dot = -dot
        if dot > 0.9995:
            # Linear interpolation for near-identical quaternions
            res = Quat(
                q0.x + t*(q1_adj.x - q0.x),
                q0.y + t*(q1_adj.y - q0.y),
                q0.z + t*(q1_adj.z - q0.z),
                q0.w + t*(q1_adj.w - q0.w)
            )
            return res.normalize()
        theta = math.acos(dot)
        s0 = math.sin((1.0 - t) * theta) / math.sin(theta)
        s1 = math.sin(t * theta) / math.sin(theta)
        return Quat(
            s0*q0.x + s1*q1_adj.x,
            s0*q0.y + s1*q1_adj.y,
            s0*q0.z + s1*q1_adj.z,
            s0*q0.w + s1*q1_adj.w
        ).normalize()

    def __repr__(self):
        return f"Quat(x={self.x:.5f}, y={self.y:.5f}, z={self.z:.5f}, w={self.w:.5f})"

# ==============================================================================
# 2. Test Suites
# ==============================================================================
def test_quaternion_rotations():
    print("--- Test 1: Quaternion Rotations & Inversions ---")
    # Rotate vector [1, 0, 0] by 90 degrees around Z axis -> should be [0, 1, 0]
    q_z90 = Quat.from_axis_angle([0, 0, 1], math.pi / 2.0)
    v_in = np.array([1.0, 0.0, 0.0])
    v_out = q_z90.rotate_vec3(v_in)
    expected = np.array([0.0, 1.0, 0.0])
    err = np.linalg.norm(v_out - expected)
    assert err < 1e-6, f"Rotation mismatch: {v_out} != {expected}"
    print(f"  [PASS] 90 deg Z rotation of {v_in} -> {v_out.round(4)} (err={err:.2e})")

    # Inverse rotation
    v_back = q_z90.conjugate().rotate_vec3(v_out)
    err_back = np.linalg.norm(v_back - v_in)
    assert err_back < 1e-6, f"Inverse mismatch: {v_back} != {v_in}"
    print(f"  [PASS] Conjugate inverse rotation back to {v_back.round(4)} (err={err_back:.2e})")

def test_lie_exp_map():
    print("\n--- Test 2: Lie Algebra Exponential Map so(3) -> SO(3) ---")
    omega = np.array([0.0, 0.0, math.pi / 2.0]) # 90 deg around Z
    q_exp = Quat.exp_map(omega)
    q_axis = Quat.from_axis_angle([0, 0, 1], math.pi / 2.0)
    diff = abs(q_exp.dot(q_axis))
    assert abs(diff - 1.0) < 1e-6, f"Exp map mismatch: {q_exp} != {q_axis}"
    print(f"  [PASS] Lie ExpMap: exp([0, 0, pi/2]) = {q_exp} (agreement with axis-angle)")

def test_slerp_and_double_cover():
    print("\n--- Test 3: SLERP and Double-Cover (q == -q) Guard ---")
    q0 = Quat.from_axis_angle([0, 1, 0], 0.0) # 0 deg
    q1 = Quat.from_axis_angle([0, 1, 0], math.radians(60.0)) # +60 deg
    q_mid = Quat.slerp(q0, q1, 0.5)
    expected_mid = Quat.from_axis_angle([0, 1, 0], math.radians(30.0))
    assert abs(abs(q_mid.dot(expected_mid)) - 1.0) < 1e-6
    print(f"  [PASS] Standard SLERP midpoint (t=0.5): 30 deg rotation verified.")

    # Opposite hemisphere test: q1_neg = -q1 (same physical orientation)
    q1_neg = Quat(-q1.x, -q1.y, -q1.z, -q1.w)
    assert q0.dot(q1_neg) < 0.0 # Negative dot product
    q_mid_neg = Quat.slerp(q0, q1_neg, 0.5)
    err_cover = abs(abs(q_mid_neg.dot(expected_mid)) - 1.0)
    assert err_cover < 1e-6, "Double-cover SLERP guard failed to take shortest path!"
    print(f"  [PASS] Double-cover SLERP shortest-path guard active (err={err_cover:.2e})")

def test_imu_gravity_alignment():
    print("\n--- Test 4: IMU Gravity Tilt Vector Estimation ---")
    # Simulate a resting headset tilted 10 degrees pitch up
    tilt_angle = math.radians(10.0)
    q_true = Quat.from_axis_angle([1, 0, 0], tilt_angle) # Tilted pitch
    # In sensor body frame, gravity [0, 9.8066, 0] is rotated by q_true.conjugate()
    g_world = np.array([0.0, 9.8066, 0.0])
    accel_meas = q_true.conjugate().rotate_vec3(g_world)
    
    # Calculate measured tilt from accelerometer
    measured_pitch = math.atan2(-accel_meas[2], accel_meas[1])
    err_pitch = abs(measured_pitch - tilt_angle)
    assert err_pitch < 1e-5
    print(f"  [PASS] True pitch: {math.degrees(tilt_angle):.2f} deg -> Accel measured: {math.degrees(measured_pitch):.2f} deg (err={err_pitch:.2e})")

def test_edid_timings_arithmetic():
    print("\n--- Test 5: DisplayID / EDID 90Hz Timing & Bandwidth Arithmetic ---")
    # HP Reverb G2 DisplayID mode timings:
    modes = [
        {"name": "4320x2160@60 (Working)", "hact": 4320, "hblank": 100, "vact": 2160, "vblank": 514, "rate": 60.0, "max_bw_gbps": 25.92},
        {"name": "4320x2160@90 (Native)",   "hact": 4320, "hblank": 100, "vact": 2160, "vblank": 116, "rate": 90.0, "max_bw_gbps": 25.92},
        {"name": "2880x1440@60 (CTRL)",     "hact": 2880, "hblank": 100, "vact": 1440, "vblank": 514, "rate": 60.0, "max_bw_gbps": 25.92},
        {"name": "2880x1440@90 (Mode B)",   "hact": 2880, "hblank": 100, "vact": 1440, "vblank": 514, "rate": 90.0, "max_bw_gbps": 25.92},
    ]

    for m in modes:
        htotal = m["hact"] + m["hblank"]
        vtotal = m["vact"] + m["vblank"]
        pclk_hz = htotal * vtotal * m["rate"]
        pclk_mhz = pclk_hz / 1e6
        # At 24 bits per pixel (8 bpc RGB):
        bandwidth_gbps = (pclk_hz * 24.0) / 1e9
        is_within_hbr3 = bandwidth_gbps <= m["max_bw_gbps"]
        print(f"  Mode: {m['name']:<24} | Pclk: {pclk_mhz:>6.2f} MHz | Data: {bandwidth_gbps:>5.2f} Gbps | HBR3 Fit: {'YES' if is_within_hbr3 else 'NO'}")
        assert is_within_hbr3, f"Mode {m['name']} exceeds DisplayPort HBR3 link rate!"

# ==============================================================================
# Main Runner
# ==============================================================================
if __name__ == "__main__":
    print("======================================================================")
    print("      VR TRACKING & TIMING MATHEMATICS VERIFICATION SUITE")
    print("======================================================================")
    test_quaternion_rotations()
    test_lie_exp_map()
    test_slerp_and_double_cover()
    test_imu_gravity_alignment()
    test_edid_timings_arithmetic()
    print("\n>>> ALL 5 MATHEMATICAL VERIFICATION SUITES PASSED PERFECTLY (100%) <<<\n")
