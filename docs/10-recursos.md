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

- **Puente de display: Analogix `ANX7530`** (DP -> MIPI DSI, especificado para VR hasta
  120 Hz), más un `ANX7688`. Confirmado por el string de versiones del firmware:
  `STM:..;DFU:..;ANX7688:..;ANX7530:..`. Hay además un **STM32** y una ruta **DFU**
  (`bridge_fw_check_update`, `bridge_fw_switch_bank`, `QCI_FEATURE_ERASE_FLASH`,
  `QCI_FEATURE_DFU_NEW`, `SMARTBRIDGE_UNINITIALISED`): el firmware del puente es
  actualizable, en bancos.
- **El Lattice CrossLink `LIF-MD6000-6CSFBGA81` NO es el puente de video**, es el agregador
  de cámaras. Se lo señaló como sospechoso principal y era un error: su datasheet no menciona
  DisplayPort, y en el teardown del WMR de Acer el mismo chip cumple ese rol mientras el
  puente real es un ANX7530.
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

## Datos del usuario (2026-08-04), sin verificar todavía

- **El USB3 tenía que colgar de un puerto conectado al CPU, no al chipset.** Costó hacerlo
  andar incluso estando soportado. Encaja con el cap. 00 y explica por qué el diagnóstico del
  puerto fue tan trabajoso.
- **HAGS** (Hardware Accelerated GPU Scheduling) **activado hacía que en Windows fuera a pocos
  frames.** Es un dato técnico, no una anécdota: HAGS cambia quién programa el trabajo de la
  GPU y toca la ruta de presentación. Que un cambio de scheduler degrade al G2 sugiere que
  este casco es sensible al timing de entrega de frames más que un display común. Pista viva.
- En Windows 11 el soporte WMR duró hasta hace poco y recién ahora lo cortaron; de ahí salen
  los drivers "hack" de Steam (el Oasis de HP es justamente ese).
- El usuario ofrece hacer capturas en Windows si hacen falta. Hoy no hacen falta (cap. 07
  archivado), pero si se necesita ver cómo negocia el link, hay que preparárselo bien.

## Objetivo declarado del proyecto

Sacar un **driver universal + kit de cosas básicas** para que el G2 siga siendo útil en Linux
y la gente pueda desarrollar encima. El casco es barato hoy, tiene buena calidad óptica, y
Microsoft y HP lo abandonaron: hay miles funcionando y nadie lo recicló bien.

## Lo que falta conseguir

1. **Datasheet del Analogix ANX7530.** Límites de pixel clock, requisitos de MIPI, y sobre
   todo si el refresh de salida depende del firmware o se adapta al input.
2. **Driver WMR original de la Microsoft Store** — la otra implementación del panel.
3. `unlock_wmr.exe`, `MROEMFwHost.dll`, `client_utility.exe`, `DriverTracing.wprp`.
4. Un **dump del firmware** del casco, si `MROEMFwHost` deja leerlo
   (`OemFwDevice_ReadDeviceInfo`).

## Expedientes FCC: qué hay y qué no (verificado 2026-08-05)

Grantee **Quanta Computer Inc**, código **HFS**. Los expedientes son públicos:
[HFS-A85Q](https://fccid.io/HFS-A85Q) (G2) y [HFS-A85R](https://fccid.io/HFS-A85R)
(Omnicept). No los guardamos acá — bajálos de ahí y procesálos con `scripts/pdf2md.py`,
que convierte el PDF a markdown y extrae las imágenes sin dependencias.

| documento | A85Q (G2) | A85R (Omnicept) | estado |
|---|---|---|---|
| **Internal photos** | 512 KB | 1 MB | **disponible** — las fotos de PCB |
| Sketch for Reference | 150 KB | 181 KB | disponible |
| External Photos | 578 KB | 682 KB | disponible |
| Test Setup Photos | 443 KB | 600 KB | disponible |
| Test Report | 2.1 MB | 3 MB (x2) | disponible |
| User Manual | 4.9 MB | 3.3 MB | disponible |
| **Block Diagram** | 140 KB | 69 KB | **CONFIDENCIAL, sólo metadata** |
| **Schematics** | 789 KB | 1.1 MB | **CONFIDENCIAL, sólo metadata** |

**Los esquemáticos y el diagrama de bloques del G2 existen y están presentados ante la FCC,
pero Quanta pidió confidencialidad de largo plazo — no son públicos.** Era el premio mayor y
no está al alcance. Las fotos internas sí, y de ahí salen los part numbers.

Datos administrativos útiles: fecha de concesión 2020-06-05 (A85Q) y 2020-09-30 (A85R),
laboratorio SGS Taiwan, TCB Telefication B.V., modelo declarado `A85Q`/`A85R`, banda
2402-2480 MHz (Bluetooth de los controllers), potencia 0.015 W.

### Fotos internas de la FCC: analizadas, y NO dan part numbers (2026-08-05)

Bajadas de fccid.io y procesadas con `scripts/pdf2md.py` (78 imágenes extraídas de los dos
expedientes; los PDFs no están en el repo).
**Las páginas están escaneadas a ~130 DPI**: la placa del G2, de ~100 mm, ocupa unos 680
píxeles, o sea ~7 px/mm. Una serigrafía de chip mide menos que eso. Se amplió hasta 10× y el
integrado principal es un cuadrado negro sin texto.

Lo que sí se obtuvo:

- **Serigrafías legibles en la placa del G2 (`A85Q`)**: `MCU Download` — cabezal de
  programación, presumiblemente del STM32 — y **`DES JTAG`** junto a un conector. `DES` es muy
  probablemente *deserializer*, o sea el chip de video: **hay un JTAG accesible al puente**.
  Dato guardado por si algún día hace falta hablarle directo.
- **El `A85R` es el Omnicept**, y sus fotos son de la placa de **eye-tracking de Tobii** (el
  logo se lee perfecto). Es otro SKU y otra placa: no sirve para la cadena de video.
- Placa principal del G2: ~100 mm de ancho.

**Por qué no vale la pena insistir.** Esta línea existía cuando creíamos que el fallo estaba
en el casco. El A/B de la RX 7800 XT (issue #332 de Monado) muestra que **el mismo casco, con
el mismo puente y los mismos paneles, llega a 90 Hz con AMD**. El hardware del casco está
exonerado, y el part number exacto del driver de backlight ya no cambia ninguna decisión.

Si alguna vez hiciera falta, el camino no es la FCC —su resolución es la que es— sino un
teardown de la comunidad con fotos macro, o abrir el casco. Ninguno vale el riesgo hoy.
