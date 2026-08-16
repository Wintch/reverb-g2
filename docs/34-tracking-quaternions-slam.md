# 34 — 6DoF Tracking, Visual-Inertial SLAM, and Quaternion Mathematics in VR

This document provides the complete mathematical, architectural, and operational reference for 6DoF (Six Degrees of Freedom) tracking in VR systems under Linux/OpenXR, contrasting on-device systems (Meta Quest) with host-processed systems (HP Reverb G2 / WMR, Valve Index, Rift S), and detailing the quaternion mathematics and sensor fusion pipelines implemented in Monado and Basalt.

---

## 1. 6DoF Tracking Architectural Comparison

```
+---------------------------------------------------------------------------------------------------+
|                                      VR TRACKING ARCHITECTURES                                    |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [ A. On-Device Autonomous (Meta Quest) ]                                                         |
|  Cameras + IMU ---> [ On-Board DSP / Hexagon NPU ] ---> Solved 6DoF Pose Matrix                   |
|                                                              | (Network / WiVRn / ALVR UDP)       |
|                                                              v                                    |
|                                                      Linux OpenXR Client / Server                 |
|                                                                                                   |
|  [ B. Host-Processed Inside-Out (WMR / G2 / Rift S) ]                                             |
|  Raw UVC Cameras (0x0 SLAM, 0x2 Ctrl) \                                                          |
|  Raw HID IMU (1 kHz) ------------------> [ PC Host (Monado + Basalt SLAM + Constellation) ]       |
|                                                              |                                    |
|                                                              v                                    |
|                                                      Compositor (Vulkan Direct-Mode)              |
|                                                                                                   |
|  [ C. Laser-Swept Outside-In (SteamVR Lighthouse) ]                                               |
|  Fixed Swept Lasers ---> Photodiode Pulse Timings ---> [ libsurvive / OpenXR ]                    |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
```

### A. Meta Quest Ecosystem (Quest 1 / 2 / 3 / Pro)
* **Architecture:** On-device edge processing (*Meta Insight Tracking*). All VIO (Visual Inertial Odometry) and SLAM computations run locally on the headset's DSP/NPU (Qualcomm Snapdragon XR2/Hexagon). Raw camera feeds are locked by firmware.
* **Headset Tracking:** 4x monochrome wide-angle cameras + 1 kHz IMU $\to$ VIO + local keyframe bundle adjustment $\to$ real-time 6DoF pose.
* **Controller Tracking:**
  * *Quest 1 / 2:* Pulsed IR LEDs in constellation rings + 1 kHz controller IMU $\to$ EKF fusion in headset.
  * *Quest 3:* Body IR LEDs + computer vision hand/controller ML tracking model.
  * *Quest Pro (Touch Pro):* Self-tracking controllers. Each controller has its own Snapdragon 662 SoC + 3 cameras + IMU running autonomous onboard SLAM, transmitting 6DoF poses via Wi-Fi.
* **Linux Integration Path:** **WiVRn** (Linux-native OpenXR streaming over UDP) and **ALVR**. The Quest client queries the Android OpenXR runtime (`xrLocateSpace`), serializes the 6DoF poses, and streams them to the Linux host compositor.

### B. Inside-Out PCVR (HP Reverb G2 / WMR)
* **Architecture:** Host-side processing. The headset is a pure sensor bridge delivering raw UVC camera streams and HID IMU packets over DisplayPort/USB.
* **Headset Tracking (SLAM):** Monado captures frame type `0x0` and feeds it along with the IMU stream to **Basalt** (`libbasalt.so`), an external Visual-Inertial Odometry / SLAM library.
* **Controller Tracking (Constellation):** Monado captures frame type `0x2` (short exposure for LED blobs) and feeds detected 2D spots + controller IMU into `libconstellation.a` to solve Perspective-n-Point (PnP) pose estimation.

### C. Laser Lighthouse (Valve Index / HTC Vive / Bigscreen Beyond)
* **Architecture:** External base stations sweep horizontal and vertical laser lines across the room.
* **Tracking Engine:** Photodiodes on the HMD/controllers measure the exact time-of-flight between synchronization flashes and laser sweeps. Fully solved and open-source in Linux via **`libsurvive`** and Monado `steamvr_lh`.

---

## 2. Quaternion Mathematics for VR Tracking & OpenXR

In OpenXR and Monado, orientation is represented by unit quaternions. Quaternions eliminate gimbal lock, provide seamless spherical interpolation, and allow ultra-fast composition of rotations.

### A. Fundamentals
A quaternion $q$ is defined as:
$$q = w + x\mathbf{i} + y\mathbf{j} + z\mathbf{k} = (w, \vec{v})$$
where $\mathbf{i}^2 = \mathbf{j}^2 = \mathbf{k}^2 = \mathbf{ijk} = -1$.

A rotation of angle $\theta$ around a unit axis $\vec{u} = (u_x, u_y, u_z)$ is encoded as:
$$q = \left[ \cos\left(\frac{\theta}{2}\right), \; \vec{u} \sin\left(\frac{\theta}{2}\right) \right] = \left( \cos\frac{\theta}{2}, \; u_x\sin\frac{\theta}{2}, \; u_y\sin\frac{\theta}{2}, \; u_z\sin\frac{\theta}{2} \right)$$

* **Unit Length Constraint:** Every valid spatial rotation must satisfy $\|q\| = 1$:
  $$\|q\| = \sqrt{w^2 + x^2 + y^2 + z^2} = 1.0$$
* **Identity Rotation:** $q_{ident} = (x=0, y=0, z=0, w=1)$.
* **Inverse (Conjugate for unit quaternions):**
  $$q^{-1} = q^* = (-x, -y, -z, w)$$

### B. Coordinate Transform & OpenXR Pose Structure
In Monado and OpenXR, a full 6DoF pose is defined as:
```c
struct xrt_pose {
    struct xrt_quat orientation; // 3DoF angular orientation
    struct xrt_vec3 position;    // 3DoF translational position [x, y, z] in meters
};
```

1. **Rotating a 3D Vector:**
   Transforming a local point $\vec{P}_{local}$ (e.g. controller tip) to world coordinates:
   $$\vec{P}_{world} = q \cdot \vec{P}_{local} \cdot q^{-1} + \vec{T}$$
   Implemented in Monado via `math_quat_rotate_vec3(&q, &p_local, &p_world)`.

2. **Chaining 6DoF Poses ($A \to B$):**
   When transforming pose $B$ by parent pose $A$ (e.g. Controller relative to HMD, and HMD relative to World):
   $$q_{combined} = q_A \cdot q_B$$
   $$\vec{T}_{combined} = q_A \cdot \vec{T}_B \cdot q_A^{-1} + \vec{T}_A$$
   Implemented in `math_pose_transform()` (`monado/src/xrt/auxiliary/math/m_space.cpp`).

---

## 3. IMU Fusion & Gyroscope Integration

The high-frequency tracking loop (typically 1000 Hz) integrates raw angular velocity $\vec{\omega} = (\omega_x, \omega_y, \omega_z)$ from the gyroscope to update orientation between slower camera frames.

```
       Raw Gyro (rad/s) ---> [ Gyro Bias Correction ] ---> Delta Angle / Axis ---> Delta Quat
                                                                                     |
                                                                                     v
  Previous Quat q(t) --------------------------------------------------------> [ Quat Multiply ] ---> Normalize ---> q(t + dt)
                                                                                     ^
       Raw Accel (m/s^2) --> [ Gravity Alignment (Tilt Error) ] ---------------------+
```

### A. Discrete Integration Step (`m_imu_3dof.c`)
Given angular velocity $\vec{\omega}$ and sample time delta $\Delta t$:
1. Unbiased angular speed: $\|\vec{\omega}\| = \sqrt{\omega_x^2 + \omega_y^2 + \omega_z^2}$
2. Instantaneous rotation angle: $\Delta\theta = \|\vec{\omega}\| \cdot \Delta t$
3. Instantaneous rotation axis: $\vec{u} = \frac{\vec{\omega}}{\|\vec{\omega}\|}$
4. Incremental quaternion:
   $$\Delta q = \left[ \cos\left(\frac{\Delta\theta}{2}\right), \; \frac{\vec{\omega}}{\|\vec{\omega}\|} \sin\left(\frac{\Delta\theta}{2}\right) \right]$$
5. Update state and normalize:
   $$q_{t + \Delta t} = \text{normalize}(\Delta q \cdot q_t)$$

### B. Gravity Correction (Tilt Drift Removal)
A resting accelerometer measures the reaction to gravity: $\vec{a} \approx [0, +9.8066, 0] \text{ m/s}^2$ in world coordinates.
1. Rotate measured acceleration to world frame: $\vec{a}_{world} = q \cdot \vec{a}_{meas} \cdot q^{-1}$.
2. Compute tilt error between $\vec{a}_{world}$ and the true vertical vector $[0, 1, 0]$.
3. Apply a small corrective quaternion rotation $q_{corr}$ scaled by filter gain $\alpha$:
   $$q \leftarrow q_{corr} \cdot q$$

---

## 4. Interpolation, Filtering, and Critical Pitfalls

### A. The Double-Cover Property ($q \equiv -q$)
A fundamental property of unit quaternions is that $q$ and $-q$ represent the exact same physical rotation in 3D space.
* **The Pitfall:** When interpolating or filtering between $q_0$ and $q_1$ (e.g. in the **One Euro Filter** in `m_filter_one_euro.c` or SLERP), compute the dot product:
  $$d = q_0 \cdot q_1 = w_0 w_1 + x_0 x_1 + y_0 y_1 + z_0 z_1$$
* **The Rule:** If $d < 0$, invert the target quaternion ($q_1 \leftarrow -q_1$) before interpolating. Failing to do this causes the interpolation to take the 360° "long way around", producing violent 1-frame visual flips.

### B. SLERP (Spherical Linear Interpolation)
To smoothly interpolate orientation at render/photon time $t \in [0, 1]$:
$$\text{SLERP}(q_0, q_1, t) = \frac{\sin((1-t)\Omega)}{\sin\Omega} q_0 + \frac{\sin(t\Omega)}{\sin\Omega} q_1 \quad \text{where } \cos\Omega = q_0 \cdot q_1$$

### C. Exponential Map & Lie Algebra ($\mathfrak{so}(3) \to SO(3)$)
In non-linear visual-inertial bundle adjustment (Basalt):
* Direct unconstrained optimization of 4 quaternion coefficients easily breaks the unit norm condition.
* Instead, optimizations represent rotation increments in the Lie algebra $\mathfrak{so}(3)$ as 3-vectors $\vec{\delta\theta}$.
* The exponential map (`monado/src/xrt/auxiliary/math/m_quatexpmap.cpp`) maps $\vec{\delta\theta} \in \mathbb{R}^3$ onto the Lie group $SO(3)$ (unit quaternion):
  $$\exp(\vec{\delta\theta}) = \left[ \cos\left(\frac{\|\vec{\delta\theta}\|}{2}\right), \; \frac{\vec{\delta\theta}}{\|\vec{\delta\theta}\|} \sin\left(\frac{\|\vec{\delta\theta}\|}{2}\right) \right]$$

---

## 5. Summary Reference for the Linux VR Pipeline

| Component | Source File | Mathematical Function |
|---|---|---|
| Vector Rotation | [`m_api.h`](file:///home/brunduk/Documents/linux_vr_base/monado/src/xrt/auxiliary/math/m_api.h) | `math_quat_rotate_vec3` ($q \vec{v} q^{-1}$) |
| Pose Composition | [`m_space.cpp`](file:///home/brunduk/Documents/linux_vr_base/monado/src/xrt/auxiliary/math/m_space.cpp) | `math_pose_transform` ($T_A + R_A T_B, R_A R_B$) |
| IMU Integration | [`m_imu_3dof.c`](file:///home/brunduk/Documents/linux_vr_base/monado/src/xrt/auxiliary/math/m_imu_3dof.c) | Gyro integration + gravity tilt correction |
| Lie Exp Map | [`m_quatexpmap.cpp`](file:///home/brunduk/Documents/linux_vr_base/monado/src/xrt/auxiliary/math/m_quatexpmap.cpp) | $\mathfrak{so}(3) \to SO(3)$ for SLAM bundle adjustment |
| Jitter Reduction | [`m_filter_one_euro.c`](file:///home/brunduk/Documents/linux_vr_base/monado/src/xrt/auxiliary/math/m_filter_one_euro.c) | Adaptive low-pass filter with double-cover guard |
| WMR $\to$ Basalt Calib | `basalt/data/monado/wmr-tools/` | Extract camera intrinsics/extrinsics from EEPROM JSON |
