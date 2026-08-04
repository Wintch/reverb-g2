# reverb-g2-linux

HP Reverb G2 funcionando en Linux (Debian 13, NVIDIA RTX 3060 Ti, Monado) — parches,
scripts y el manual completo de procedimientos. Todo lo que acá se documenta fue medido
y probado en este rig real; donde algo NO funciona, el manual dice por qué y qué se probó.

> Estado: **en desarrollo activo**. Este repo se versiona localmente y se publicará
> cuando el stack completo esté andando y documentado.

## Qué anda hoy (2026-08)

| Área | Estado |
|---|---|
| Display del casco | ✅ 60Hz vía Monado direct-mode (X11) — 90Hz en desarrollo (parches driver) |
| Head tracking 3DoF | ✅ rock-solid (IMU, `WMR_SLAM=0`) |
| Head tracking 6DoF | ⚠️ Basalt SLAM diverge — en investigación |
| Player 360 foto/video | ✅ propio (hello_xr modificado) — NVDEC en desarrollo |
| Controllers | ⚠️ conectan con fallos intermitentes — fixes en desarrollo; solo 3DoF (límite driver) |
| Audio del casco | ❌ falla física (cable/companion board — igual en Windows) |
| SteamVR | ❌ bug de packaging de Valve (vrmonitor/Qt) — OpenComposite es el camino |

## Estructura

- `patches/monado/` — fixes al driver WMR y al bridge SteamVR (descripciones en inglés,
  pensados para upstream).
- `patches/nvidia/` — parches de los open kernel modules para 90Hz (adaptación del trabajo
  de [Project-VR](https://github.com/AshishKumar4/Project-VR) a Debian + DKMS, con atribución).
- `patches/hello_xr-player/` — el viewer 360 (foto + video + decode por hardware) sobre
  OpenXR-SDK-Source.
- `scripts/` — `jack-in.sh` (levantar todo el pipeline en un comando), reglas udev, helpers.
- `docs/` — **el manual**, un capítulo por procedimiento:
  - `00-hardware-usb.md` — topología USB, por qué el disco raíz no puede compartir bus
    con el casco, y cómo dejarlo bien.
  - `01-bringup-monado.md` — build de Monado + Basalt, permisos, jack-in, gotchas.
  - `02-player-360.md` — el player: formatos, env vars, NVDEC.
  - `03-controllers.md` — estado real de los controllers, fixes y roadmap 6DoF.
  - `04-lab-90hz.md` — sistema de laboratorio en disco aparte, driver 595-open parcheado
    vía DKMS, test de 90Hz, rollback.
  - `05-resolve.md` — DaVinci Resolve vía makeresolvedeb y workflow de transcode.
  - `06-known-issues.md` — lo que no anda y por qué (con evidencia).

## Hardware de referencia

Debian 13 trixie · kernel 6.12 · RTX 3060 Ti (GA104) · HP Reverb G2 (RevB) ·
AM4/A520 · sesión X11 (obligatoria hoy — ver `04-lab-90hz.md` para el detalle X11/Wayland).
