# 06 — Problemas conocidos y por qué NO los perseguimos (con evidencia)

## Audio del casco: falla FÍSICA, no de software

El companion board del G2 (`03f0:0580`, lleva el HID de control **y** el audio) se cae del
bus USB y re-enumera constantemente. Evidencia decisiva: **hace exactamente lo mismo en
Windows** (el device de audio aparece, se mutea y desaparece cada 5-10s). No es driver, no
es udev, no es Linux: es cable/conector/placa. En Linux directamente no enumera ningún
device de audio HP/WMR. **No gastar tiempo en software acá.** Prime suspect: el cable del
G2 (punto de falla clásico del modelo). Mitigación actual: audio por el USB sound device
externo; los parches de Monado (patches/monado/0001) hacen que las caídas no maten el
servicio.

## Basalt SLAM diverge (6DoF de cabeza)

~3° de error medio entre frames con el casco INMÓVIL (spam de `det(Q1Jl)==0`). Se usa
`WMR_SLAM=0` (IMU 3DoF, impecable) para todo lo orientation-only. Investigación pendiente:
¿calibración? ¿textura visual del ambiente? ¿exposición? Es el desbloqueo técnico más
valioso después del 90Hz.

## SteamVR no levanta (y no es culpa nuestra)

El driver Monado para SteamVR carga OK (con el RPATH del patch 0002 + bundle de libs),
pero `vrmonitor` de Valve crashea por `libQt5Multimedia.so.5` faltante **dentro del
runtime container de Valve**. Camino recomendado: **OpenComposite** (OpenVR→OpenXR directo
contra Monado, saltea SteamVR entero) — no probado aún.

## 90Hz — en proceso (cap. 04)

Bug del driver NVIDIA (5923212), no de hardware ni de Monado. Sin fix upstream hasta
610.x inclusive. El lab con driver 595-open parcheado es el plan activo.

## Controllers: solo 3DoF

Límite de código del driver WMR upstream (posición hardcodeada). Roadmap constellation en
cap. 03. La confiabilidad de conexión ya la arreglamos (patches/monado/0004-0006).

## Cuelgue total 2026-08-04 (resuelto por diseño)

Disco raíz USB compartiendo xHCI con el casco + autosuspend. Cap. 00 tiene el análisis y
los procedimientos. Los .mp4 truncados de esa mañana (marsa*, sin moov atom) no son
recuperables — re-descargar.

## Hardware roto conocido

- 16GB RAM (upgrade a 32 planeado); zram configurado al 100% con zstd.
- NVMe 1.8TB enteramente NTFS (Windows) — el futuro setup ideal debería darle una
  partición nativa a Linux para media/scratch de Resolve.
