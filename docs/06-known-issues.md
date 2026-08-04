# 06 — Problemas conocidos y por qué NO los perseguimos (con evidencia)

## Audio del casco: RESUELTO — era el puerto USB (2026-08-04)

> Esta sección decía que el audio era una falla física incurable del cable. **Era falso.**
> Se deja el error documentado porque costó meses de diagnóstico equivocado.

El cable del G2 lleva una rama SuperSpeed y una rama USB 2.0 por el mismo puerto físico. En
el puerto USB-A que usábamos, la rama SuperSpeed enumeraba bien y **la rama USB 2.0 nunca
entrenaba el link**:

```
usb usb3-port2: Cannot enable. Maybe the USB cable is bad?
usb 3-2: device not accepting address 6, error -71
usb usb3-port2: unable to enumerate USB device
```

Todo lo que vive en esa rama quedaba ausente: el companion `03f0:0580` (HID de control **y**
audio). Por eso Monado caía a Simulated HMD y por eso no aparecía ningún device de audio.
En terminología WMR esto es el **error 7-14**, "required USB2 components not found", una
falla documentada del G2: el cable es extra largo y deja los márgenes de señal USB muy
justos.

**Mover el casco a otro puerto USB-A trasero lo arregló por completo.** Cero `error -71`
desde entonces. Girar el conector USB-C 180° dentro del adaptador C→A también ayudó por su
cuenta (levantó los sensores HoloLens). Probar el puerto primero, la orientación después.

### Enumeración correcta — los cinco tienen que estar

```
3-1    04b4:6506  HP WMR hub (USB2)         480M
3-1.2  0bda:4c15  USB Audio                 480M   <- parlantes + micrófono del casco
3-1.3  03f0:0580  QHMD A85V s/n REDACTED   12M   <- companion, HID de control
4-1    04b4:6504  HP WMR hub (USB3)        5000M
4-1.1  045e:0659  HoloLens Sensors         5000M
```

Si falta `03f0:0580`, **no debuguear Monado** — revisar el puerto.

### El audio, cómo encontrarlo

Enumera como card ALSA `USB-Audio - Generic USB Audio` (`0bda:4c15`, chip Realtek), **sin
ninguna cadena HP/Reverb/WMR**. Por eso los chequeos que grepeaban `hp|reverb|wmr` daban
"no hay audio del casco" aun estando presente. Confirmado audible 2026-08-04, y estable:
30 segundos de reproducción continua sin un solo corte.

Sink `alsa_output.usb-Generic_USB_Audio-00.analog-stereo` + su source (el micrófono). El
device reporta mal su rango de volumen (`Unlikely big volume range (=800)`, PCM en `-25600`)
y PipeWire delega el volumen a esa escala rota, así que **un porcentaje intermedio puede ser
inaudible: probar siempre al 100%**.

Esto explica también el síntoma que el usuario venía sufriendo en Windows desde siempre
(device de audio que aparece, se mutea y desaparece). Nunca fue un problema de sistema
operativo.

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
