# 01 — Bring-up de Monado + Basalt para el Reverb G2

Resumen operativo del camino ya recorrido (agosto 2026). Sirve igual para el sistema
principal y para reproducir en el lab.

## Dependencias (Debian 13)

```bash
sudo apt install -y git cmake ninja-build meson pkg-config glslang-tools \
    libvulkan-dev vulkan-tools vulkan-validationlayers \
    libeigen3-dev libopencv-dev libusb-1.0-0-dev libudev-dev libsdl2-dev libhidapi-dev \
    libgl-dev libglx-dev libglvnd-dev libxcb-randr0-dev libx11-xcb-dev
```

(`libglvnd-dev` y los `xcb-randr` no son opcionales: sin el primero falla el target
`OpenGL::GLX` de CMake; sin los segundos el direct-mode NVIDIA queda stubbeado.)

## Build

```bash
git clone --recursive https://gitlab.freedesktop.org/monado/monado.git
cd monado && git am ../reverb-g2-linux/patches/monado/*.patch
cmake -B build -GNinja && ninja -C build

git clone --recursive https://gitlab.freedesktop.org/mateosss/basalt.git
cd basalt && cmake --preset library && cmake --build build   # solo libbasalt.so
```

## Permisos

`scripts/70-wmr-reverb.rules` → `/etc/udev/rules.d/` (+ reload + replug). Usuario en
`plugdev`. Sin esto: LIBUSB_ERROR_ACCESS en las cámaras y crash/degradación.

## Levantar todo

`scripts/jack-in.sh [3dof]` hace la secuencia completa y correcta:
X11 check → apagar DP-0 (libera el panel del casco para el lease) → esperar settle →
re-asertar el layout de monitores (el driver rompe la rotación de DP-3 al tocar CRTCs) →
esperar el companion device (03f0:0580) → lanzar monado-service con el entorno correcto.

Variables clave que setea: `VIT_SYSTEM_LIBRARY_PATH` (Basalt), 
`XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="HP Inc."` (allowlist de HMDs no incluye WMR),
`XRT_COMPOSITOR_DESIRED_MODE=2` (60Hz — único modo que anda sin driver parcheado, cap. 04),
`XRT_NO_STDIN=1`, y `WMR_SLAM=0` si se pasó `3dof`.

## Gotchas de proceso (aprendidos a golpes — TODOS reales)

- **Siempre** `rm -f /run/user/$UID/monado_comp_ipc` antes de relanzar (kill -9 no lo borra).
- `pkill` no es confiable acá: matar por PID explícito (`pgrep` → `kill -9 <pid>`, de a
  uno) y **verificar** con `ps`/`nvidia-smi` — un monado-service zombie reteniendo el
  lease de DP-0 nos costó horas.
- Verificar `Using builder wmr` en el log antes de confiar cualquier test: si el companion
  device estaba caído al arrancar, Monado cae a "Simulated HMD" en silencio.
- `monado-service` y `hello_xr` tratan EOF de stdin como quit: `XRT_NO_STDIN=1` para el
  servicio, `sleep N |` para hello_xr.
- Tras apagar DP-0, esperar ≥8s antes del lease (race de `vkAcquireXlibDisplayEXT`).

## Tracking: 3DoF vs SLAM

Medido con el casco quieto en la mesa: Basalt SLAM diverge (~3° de rotación media entre
frames, picos de 30°); IMU-only = 0.0013° (2000x mejor). Para 360/cine: `3dof` siempre.
6DoF real necesita arreglar la divergencia de Basalt (pendiente, alta prioridad después
del 90Hz). Los datos y la instrumentación (`HELLO_XR_POSE_STATS`) están en el cap. 02.
