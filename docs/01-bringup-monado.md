# 01 — Monado + Basalt Bring-up for the Reverb G2

Operational summary of the path covered so far (August 2026). Equally useful for the
main system and for reproducing on the lab rig.

## Dependencies (Debian 13)

```bash
sudo apt install -y git cmake ninja-build meson pkg-config glslang-tools \
    libvulkan-dev vulkan-tools vulkan-validationlayers \
    libeigen3-dev libopencv-dev libusb-1.0-0-dev libudev-dev libsdl2-dev libhidapi-dev \
    libgl-dev libglx-dev libglvnd-dev libxcb-randr0-dev libx11-xcb-dev
```

(`libglvnd-dev` and `xcb-randr` are not optional: without the former, CMake's
`OpenGL::GLX` target fails; without the latter, NVIDIA direct-mode ends up stubbed out.)

## Build

```bash
git clone --recursive https://gitlab.freedesktop.org/monado/monado.git
cd monado && git am ../reverb-g2/patches/monado/*.patch
cmake -B build -GNinja && ninja -C build

git clone --recursive https://gitlab.freedesktop.org/mateosss/basalt.git
cd basalt && cmake --preset library && cmake --build build   # libbasalt.so only
```

Basalt's own deps, not covered by the list above (found 2026-08-07, T060: this repo's
`~/vr/basalt` had never actually been built before -- `cmake --preset library` was
failing on these, silently leaving a configured-but-not-built tree that looked done at a
glance):

```bash
sudo apt install -y libbz2-dev liblz4-dev libssl-dev libepoxy-dev libyaml-cpp-dev libsqlite3-dev
```

## Permissions

`scripts/70-wmr-reverb.rules` → `/etc/udev/rules.d/` (+ reload + replug). User in
`plugdev`. Without this: LIBUSB_ERROR_ACCESS on the cameras and crash/degradation.

## Bringing everything up

`scripts/jack-in.sh [3dof]` runs the complete, correct sequence:
X11 check → turn off DP-0 (frees the headset panel for the lease) → wait for settle →
re-assert the monitor layout (the driver breaks DP-3's rotation when touching CRTCs) →
wait for the companion device (03f0:0580) → launch monado-service with the correct
environment.

Key variables it sets: `VIT_SYSTEM_LIBRARY_PATH` (Basalt),
`XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="HP Inc."` (the HMD allowlist doesn't include WMR),
`XRT_COMPOSITOR_DESIRED_MODE=2` (60Hz — the only mode that works without the patched
driver, ch. 04; with the bpc patch 90Hz works, but this script's X11 path hasn't been
retested at 90Hz — the verified 90Hz launcher is `jack-in-wayland.sh`, see CLAUDE.md),
`XRT_NO_STDIN=1`, and `WMR_SLAM=0` if `3dof` was passed.

## Process gotchas (learned the hard way — ALL real)

- **Always** `rm -f /run/user/$UID/monado_comp_ipc` before relaunching (kill -9 doesn't
  remove it).
- `pkill` isn't reliable here: kill by explicit PID (`pgrep` → `kill -9 <pid>`, one at a
  time) and **verify** with `ps`/`nvidia-smi` — a zombie monado-service holding the DP-0
  lease cost us hours.
- Verify `Using builder wmr` in the log before trusting any test: if the companion device
  was down at startup, Monado silently falls back to "Simulated HMD".
- `monado-service` and `hello_xr` treat stdin EOF as quit: `XRT_NO_STDIN=1` for the
  service, `sleep N |` for hello_xr.
- After turning off DP-0, wait ≥8s before the lease (race in `vkAcquireXlibDisplayEXT`).

## Tracking: 3DoF vs SLAM

Measured with the headset stationary on the table: Basalt SLAM diverges (~3° mean
rotation between frames, spikes of 30°); IMU-only = 0.0013° (2000x better). For
360/cinema: always `3dof`. Real 6DoF needs the Basalt divergence fixed (pending, high
priority after 90Hz). The data and instrumentation (`HELLO_XR_POSE_STATS`) are in ch. 02.
