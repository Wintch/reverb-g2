# 10 — Recursos: todo lo que explica cómo funciona este equipo

Índice de fuentes para entender el G2 a bajo nivel. Lo que ya se leyó está marcado; lo que
no, queda como pendiente explícito para no volver a buscarlo desde cero.

## En este disco, ahora mismo (lo más valioso)

Las NTFS del rig se montan read-only sin bootear Windows:

```bash
sudo mount -t ntfs-3g -o ro,noatime /dev/nvme0n1p4 /mnt/win4
```

### Oasis Driver de HP — `/mnt/win4/SteamLibrary/steamapps/common/Oasis Driver for Windows Mixed Reality/`

**El recurso más importante que tenemos.** Es el driver standalone de HP: le habla al casco
directo por HID/USB, sin pasar por el runtime WMR de Windows. Es *el* driver que corre el G2
a 90 Hz.

| archivo | qué es | estado |
|---|---|---|
| `bin/win64/driver_oasis.dll` | driver SteamVR (importa `HID.DLL` directo) | **leído** (cap. 09) |
| `bin/win64/HololensSensors.dll` | sensores + panel en userspace; trae strings del **firmware** | leído parcial |
| `bin/win64/MRUSBHost.dll` | capa USB/HID cruda (`MrUsbDevice_SendHidCommand`, `CrystalKey*`) | exports leídos |
| `bin/win64/MROEMFwHost.dll` | firmware OEM (`OemFwDevice_ReadDeviceInfo/WriteFirmware`) | **sin mirar** |
| `unlock/unlock_wmr.exe` (611 KB) | herramienta de "unlock" | **sin mirar** |
| `bin/win64/client_utility.exe` | utilidad cliente (el driver la lanza) | **sin mirar** |
| `tracing/DriverTracing.wprp` + `Capture-ETL.bat` | perfil de tracing ETW del driver | **sin mirar** |
| `bin/win64/PassthroughSource.dll` | passthrough de cámaras | **sin mirar** — relevante para cap. 08 |
| `bin/win64/CalibrationAPI.dll` | calibración de cámaras/pantallas | sin mirar |

El `DriverTracing.wprp` es interesante: define los proveedores ETW del driver, o sea que
nombra sus subsistemas internos. Es un índice gratis de cómo está organizado.

`driver_oasis.dll` usa **Microsoft Detours** (secciones `.detourc`/`.detourd`): hookea alguna
API. No se investigó cuál.

### Driver de Microsoft — `/mnt/win5/.../MixedRealityVRDriver/`

El puente de SteamVR al runtime WMR del SO. **Sirve menos**: delega en Windows, no toca el
USB. Útil sólo para comparar.

## Contexto de Windows 11 (dicho por el usuario)

- **Windows 11 ya no trae soporte WMR.** Microsoft lo removió; hace falta el **driver
  intermedio** — que es justamente el Oasis de HP de arriba. Con eso el casco "anduvo re
  bien" a 90 Hz.
- **El driver original de WMR debería seguir estando en la Microsoft Store.** Vale bajarlo:
  es la otra mitad de la historia (el que Microsoft discontinuó) y puede tener la lógica de
  panel que el de HP no tiene.
- **`fpsVR`** (app de Steam, está instalada en `/mnt/win4/.../fpsVR/`) mide performance de
  cada cosa dentro de SteamVR: frametimes, GPU/CPU, reproyección. **Es complejo hacerla andar
  bien**, pero una vez andando es el instrumento de medición que a Linux le falta.
  Bloqueada por lo mismo que todo SteamVR acá (ver cap. 06).

## Herramientas propias de este repo

| script | para qué |
|---|---|
| `scripts/hmd-modeset.c` | modeset arbitrario sobre el casco vía DRM lease, sin Monado |
| `scripts/panel.py` | enciende/apaga el panel por HID, sin Monado |
| `scripts/drmprops.c` | lee `non-desktop` y modos del conector desde el kernel |
| `scripts/check-lease.sh` | ¿el compositor ofrece el conector para arrendar? |
| `scripts/xref.py` | xrefs de strings en binarios PE, sólo con binutils |
| `scripts/capture-hid.sh` + `analyze-hid.py` | captura y diff de HID por usbmon |

## Upstream y comunidad

- **[Project-VR](https://github.com/AshishKumar4/Project-VR)** — de donde salieron los 3
  parches al 595-open. Reporta el G2 a `4320x2160@90` en RTX 4080. Usa GNOME 50 / mutter
  **parcheado**, SteamVR, su fork de WMR dentro de `vrserver`, y su orquestador `g2ctl`.
- **Monado** — `src/xrt/drivers/wmr/`. `wmr_hmd.c:767` `wmr_hmd_activate_reverb()`,
  `wmr_hmd.c:846` `wmr_hmd_screen_enable_reverb()`. El driver WMR salió de reverse
  engineering de OpenHMD.
- **OpenHMD** — origen del "hack" `{0x50,0x01}` que Monado cargo-cultea para el G1.
- Hilos de NVIDIA:
  - [Reverb G2 no pasa de 60Hz](https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744) — bug **5923212**, confirmado por NVIDIA, sigue abierto en 610.43.02 (jul-2026).
  - [DRM lease imposible en cualquier display server](https://forums.developer.nvidia.com/t/nvidia-proprietary-non-open-modules-completely-unable-to-acquire-a-drm-lease-on-any-display-server-all-known-nvidia-drivers-any-hardware/341244) — **ya no aplica a nosotros**: con mutter el lease funciona (cap. 04).
- **HID Usage Tables**, página `0x03` "VR Controls": usage `0x20` Stereo Enable, `0x21`
  **Display Enable**. Es el comando que usan tanto HP como Monado.

## Hardware del casco (medido / leído del firmware)

- **Puente de display: Lattice CrossLink `LIF-MD6000-6CSFBGA81`** (string del firmware). Es
  quien recibe DP y maneja los dos paneles. **El sospechoso número uno hoy.** Vale buscar su
  datasheet: límites de clock del PLL, requisitos de DSC, cómo latchea el timing.
- Paneles: dos, con control de backlight por PWM (`panel_backlight_duty`,
  `[%s] left duty %d, right duty %d, frame timing %d, panel ID %d`).
- Cámaras: 4x **OV7251** 640x480 mono 8 bits (framebuffer 2560x480). El firmware avisa
  `OV7251SetFrameRate: 90hz requested but not USB3.0SS` — ese 90 Hz es de las cámaras.
- Modos del EDID (leídos del kernel, confirmados por `hmd-modeset list`):

  | idx | modo | pixel clock | htotal x vtotal |
  |---|---|---|---|
  | 0 | 4320x2160@90 | 905150 kHz | 4420 x 2276 |
  | 1 | 2880x1440@90 | 428580 kHz | 2980 x 1598 |
  | 2 | 4320x2160@60 | 709150 kHz | 4420 x 2674 |

- USB: 5 dispositivos (cap. 00). El companion es `03f0:0580` (Quanta QHMD A85V).
  **Medido hoy: el screen-off por HID puede hacerlo RE-ENUMERAR** y cambiar de nodo hidraw.

## Lo que falta conseguir

1. **Datasheet del Lattice LIF-MD6000** (CrossLink). Límites de pixel clock y de MIPI.
2. **Driver WMR original de la Microsoft Store** — la otra implementación del panel.
3. `unlock_wmr.exe`, `MROEMFwHost.dll`, `client_utility.exe`, `DriverTracing.wprp`.
4. Un **dump del firmware** del casco, si `MROEMFwHost` deja leerlo
   (`OemFwDevice_ReadDeviceInfo`).
