# 15 — Triage del feedback al reporte de NVIDIA (2026-08-05)

Hilo publicado:
<https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240>
(al momento de este triage: sin respuestas todavía).

Feedback recibido: seis ítems ordenados "por rendimiento", más una sugerencia de canal.
Abajo, cada uno contrastado contra lo que ya está medido en este repo.

---

## Resumen del triage

| # | ítem del feedback | veredicto |
|---|---|---|
| 1 | Aplicar parches de Project-VR sobre el de bpc y bisecar | **Ya hecho.** Los tres están aplicados desde antes. Y la premisa ("funciona en Ada") nunca se verificó |
| 2 | Capturar HID de Windows en la transición 60→90 | **Parcialmente cerrado por desensamblado, pero es el único que queda abierto de verdad.** La crítica al byte 18 es correcta; no toca el desensamblado |
| 3 | Leer DPCD en los tres modos | **Cerrado a medias, y la parte que falta es cara.** El color space ya lo cierra el propio EDID |
| 4 | Barrer refresh con modelines custom (61/72/75/80) | **El mejor experimento de la lista, y no está corrido.** Pero no son cinco minutos: hace falta un override de EDID |
| 5 | Parsear el DisplayID a mano y comparar el modeline | **Hecho hoy. Negativo — y de paso encontró un error en el reporte publicado** |
| 6 | Adjuntar `nvidia-bug-report.log.gz` y EDID crudo | **Correcto, hacer ya** |
| — | Abrir issue en `NVIDIA/open-gpu-kernel-modules` | **Correcto, hacer ya** |

---

## 1 — Los parches de Project-VR ya están aplicados. No hay nada que bisecar

`dkms.conf` del árbol instalado:

```
PATCH[0]="0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch"
PATCH[1]="0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch"
PATCH[2]="0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch"
```

y el `0004` (bpc) está aplicado directo sobre `/usr/src/nvidia-595.71.05` (ver la nota de
reproducibilidad de `docs/13`). O sea: **el resultado actual — parpadeo blanco a 90 Hz — ya
es el stack completo de Project-VR más el parche de bpc, corriendo en GA104.** No es que
falte combinarlos.

La segunda mitad de la premisa también falla: "que funcione en Ampere también es dato
publicable" asume que funciona en Ada. **No hay caso positivo verificado.** Ver
`docs/06`, sección "CUIDADO: Project-VR NO es un caso positivo verificado": su evidencia de
90 Hz es una sesión Vulkan/OpenXR exitosa con sus logs — exactamente la clase de evidencia
que este proyecto demostró nueve veces que es compatible con el panel muerto.

**Lo publicable acá es el negativo**, y sí vale la pena publicarlo: los tres parches al open
kernel module, más el de bpc, sobre GA104 → 90 Hz sigue fallando.

## 2 — El HID de Windows: la crítica es válida, pero apunta a la evidencia equivocada

El reviewer dice: "tu byte 18 idéntico es de un report de status (IN) — no dice nada sobre
los reports OUT/feature que Windows manda". **Eso es correcto** sobre el byte 18. Pero la
hipótesis no se cerró con el byte 18: se cerró desensamblando el driver Oasis de HP
(`docs/09`), y ese desensamblado es *exactamente* un inventario de reports OUT/feature:

- `driver_oasis.dll` tiene **un solo** call site de `HidD_SetFeature` en todo el binario:
  Usage Page `0x03` / Usage `0x21` = Display Enable. Nada más.
- `HololensSensors.dll` hace lo mismo escrito distinto.
- Los otros cuatro `HidP_SetUsageValue` son Usage Page `0x0E` (Haptics) = rumble de
  controllers.
- `MROEMFwHost.dll` es sólo el actualizador de firmware; `client_utility.exe` es de Steam.

**Dónde el reviewer igual tiene razón:** un desensamblado acota lo que ese binario *puede*
mandar, no lo que pasa por el bus. Quedan dos huecos reales:

1. `driver_oasis.dll` usa **Microsoft Detours** (secciones `.detourc`/`.detourd`) y nunca se
   miró qué hookea.
2. El runtime WMR del SO es otro componente, y `unlock_wmr.exe` toca estado de display por
   `Windows.Devices.Display.Core` — no por HID, pero es superficie no cubierta.

Una captura de bus resuelve las dos de una y no depende de NVIDIA. El kit ya está armado
(`windows-kit/capturar.bat` + `scripts/parse-usbpcap.py` + `scripts/analyze-hid.py`), el
disco de Windows está en la máquina. Cuesta un boot. **Es el único de la lista que puede
resolver el problema sin NVIDIA, así que va primero entre los abiertos** — no porque la
hipótesis esté viva, sino porque convierte "leímos el driver y no había nada" en "miramos el
cable y no pasó nada".

## 3 — DPCD: la mitad ya está contestada, y la otra mitad es cara

Ya cerrado, con dos evidencias independientes:

- **Color space**: el bloque CTA-861 del casco (extensión 1) tiene **byte 3 = `0x00`** — sin
  YCbCr 4:4:4, sin YCbCr 4:2:2. El sink no anuncia YCbCr en absoluto, así que el enlace es
  RGB obligatoriamente en los tres modos. No hay variable de color space que pueda diferir.
  Esto reemplaza la "afirmación floja" con un dato duro sacado del EDID en 30 segundos.
- **DSC**: cero menciones de DSC/compresión en `dmesg` con `nvidia_modeset.debug=1` en los
  tres modos (`docs/13`), más la cuenta de ancho de banda que ya lo descartaba dos veces.

Lo que **no** está: link rate y lane count entrenados leídos del DPCD, y `DSC_ENABLE` (0x160)
leído del sink en vez de inferido del log. Y el costo es alto: `nvidia-drm` no expone DPCD por
debugfs (no hay equivalente de `i915_dpcd` ni de `dp_dpcd_address` de amdgpu), así que habría
que escribir un cliente RM contra `/dev/nvidiactl` usando `NV0073_CTRL_CMD_DP_AUXCH_CTRL`.
Es medio día largo para confirmar algo que el log y el EDID ya sugieren. **Prioridad baja.**

## 4 — El barrido de refresh: el mejor experimento de la lista, y hay una vía para hacerlo

La lógica del reviewer es la correcta: si falla a 61 Hz, no es una historia de timing de alta
frecuencia sino de parsing/selección de modos, y eso cambia todo el diagnóstico.

**Pero no son cinco minutos**, por una razón ya medida (`docs/09`): NVIDIA en Linux **rechaza
todo timing que no esté en el EDID** — `vkCreateDisplayModeKHR` y `drmModeSetCrtc` fallan.
Así que el barrido exige un **override de EDID**, y ahí es donde estaba trabado (`docs/13`,
"otras vías para forzar el bpc"): `drm.edid_firmware` no lo respeta `nvidia-drm`, el
`edid_override` de debugfs no se sabe si NVKMS lo lee, y la sintaxis de
`nvidia_modeset.config_file` no está documentada.

**La vía que quedó descartada por el motivo equivocado: `Option "CustomEDID"` de xorg.conf.**
Se descartó con "sólo X11, y nosotros vamos por Wayland" — o sea por conveniencia, no por
técnica. Y el path X11 Direct-Mode **funciona** en este rig (fue el original; el control de
60 Hz da imagen perfecta por ahí). Para *este* experimento se puede volver a X11 a propósito.

Receta concreta:

1. Partir de `hmd.edid` (384 bytes) y agregar DTDs de 61/72/75/80 Hz manteniendo H total y
   porches, variando sólo el V blanking (el mismo eje que ya usa el EDID real entre sus modos
   de 60 y 90).
2. Corregir checksums de bloque.
3. `Option "CustomEDID" "DP-0:/ruta/g2-sweep.bin"` y correr `hmd-vk` en cada modo, con
   verificación física.

Bonus: la misma vía sirve para un EDID con el byte `0x14` en `0xA0` (8 bpc declarado), que
**reproduce el arreglo del bpc sin parchear el driver**. Eso le baja muchísimo el costo a
NVIDIA para reproducir el bug, y conviene ofrecérselo en el hilo.

## 5 — Hecho hoy. Negativo, y encontró un error en el reporte publicado

Se decodificó el EDID crudo a mano, byte por byte, y se comparó contra lo que programa nvkms.

### El error: no es DisplayID 2.0, es DisplayID 1.2

Bloque 2 del EDID: `70 12 79 00 00 03 00 28 ...`

- `0x70` = tag de extensión DisplayID.
- **`0x12` = versión 1, revisión 2.** DisplayID **1.2**, no 2.0.
- El bloque de datos es tag `0x03`, longitud `0x28` = 40 bytes = **dos descriptores Type I
  Detailed Timing de 20 bytes** (el tag `0x03` es Type VII recién en DisplayID 2.0; de ahí
  salió la confusión).

Y esto **importa**, porque `nvt_edid.c:1101` bifurca por versión:

```c
case NVT_EDID_EXTENSION_DISPLAYID:
    if ((pExt[1] & 0xF0) == 0x20) // displayID2.x as EDID extension
        getDisplayId20EDIDExtInfo(...);
    else                          // displayID13 as EDID extension
        getDisplayIdEDIDExtInfo(...);
```

`0x12 & 0xF0 = 0x10` → el G2 va por el parser **DisplayID 1.3**. Y en todo el árbol,
`input.u.digital.bpc` se escribe en **exactamente dos lugares**:

```
nvt_edid.c:914-932                 <- el switch del bloque base (default: bpc = 0)
nvt_edidext_displayid20.c:314      <- Display Parameters de DisplayID 2.x
```

El parser 1.3 **no lo toca nunca**.

**El reporte publicado dice "its DisplayID 2.0 extension carries only a Type VII timing
block, no Display Parameters block, so nothing overrides this".** La conclusión es correcta
pero el razonamiento no, y la versión correcta es *más fuerte*: no es que a este DisplayID le
falte el bloque 0x21 — es que **para cualquier sink con extensión DisplayID 1.x el único
sitio de override es inalcanzable por construcción**. O sea que el clamp a 6 bpc es
*inevitable* para todo sink DisplayPort que deje la profundidad sin declarar en el bloque
base y no traiga DisplayID 2.x con Display Parameters. Hay que corregirlo en el hilo: un
ingeniero de NVIDIA lo va a ver, y corregido el argumento generaliza mejor.

### Los modelines: coinciden exactamente. Segunda causa raíz, no hay

| fuente | pclk | H act/front/sync/back | V act/front/sync/back | refresh |
|---|---|---|---|---|
| DisplayID desc #1 (preferred) | 905.40 MHz | 4320 / 50 / 4 / 46 | 2160 / 16 / 2 / 98 | 90.00 Hz |
| DisplayID desc #2 | 709.15 MHz | 4320 / 50 / 4 / 46 | 2160 / 14 / 2 / 498 | 60.00 Hz |
| DTD del bloque base | 428.58 MHz | 2880 / 50 / 4 / 46 | 1440 / 18 / 2 / 138 | 90.00 Hz |

Los tres, con polaridad `+H +V` (byte 17 del DTD = `0x1e`; bit 15 de los campos de front
porch en los descriptores DisplayID). **Coinciden byte a byte con lo que reporta
`drmModeGetConnector`** (`docs/13`) y con el raster del log (`raster 2980 x 1598`,
`pclk 428580000`).

Así que el driver programa exactamente el timing que el casco declara. Lo que **queda**
abierto de este ítem es sólo la mitad que necesita Windows: comparar contra el modeline que
programa Windows. Sale gratis junto con la captura del ítem 2.

## 6 y canal — adjuntos armados, listos para subir

Todo en `forum-attachments/`:

| archivo | tamaño | qué es |
|---|---|---|
| `g2-edid.zip` | 2.4 KB | EDID crudo + copia con 8 bpc + decode anotado + README |
| `nvidia-bug-report.log.gz` | 545 KB | capturado con el parche puesto (renombrado al nombre que espera NVIDIA) |
| `0004-nvkms-no-6bpc-clamp.patch.txt` | 2.8 KB | el parche, con `.txt` porque el foro no acepta `.patch` |

Los `.bin` van dentro del `.zip` porque Discourse rechaza esa extensión suelta.

**Ojo con el bug report:** lleva hostname, logs de kernel y rutas del usuario. Es lo normal en
ese foro, pero conviene saberlo antes de subirlo.

El EDID de repro (`g2-edid-8bpc-repro.bin`) sale de `scripts/edid-tool.py set-bpc`: byte 0x14
`0x80`→`0xA0` y checksum `0xE8`→`0xC8`, dos bytes y nada más. Le permite a NVIDIA reproducir
la mitad del bpc **sin compilar el driver**, y es la misma vía que necesita el barrido del
ítem 4.

Y abrir el issue en `NVIDIA/open-gpu-kernel-modules`: `nvkms-dpy.c` y `nvt_edid.c` viven ahí,
y el issue lo mira ingeniería directo. Texto listo en `docs/14`.

---

## Orden propuesto

1. **Editar el post original** (no responder) con la corrección del DisplayID —que lo
   fortalece—, los tres negativos nuevos y los adjuntos. Texto completo listo para pegar en
   `docs/14`. Después abrir el issue en GitHub y linkearlo desde el post.
2. **Barrido de refresh por `CustomEDID` en X11** (61/72/75/80 Hz). Es el que más discrimina
   y no depende de nadie. Sale del mismo trabajo el EDID de repro sin parche para NVIDIA.
3. **Captura USBPcap en Windows** de la transición 60→90, y de paso el modeline que programa
   Windows. Un boot, kit ya armado.
4. DPCD por RM control call. Sólo si 2 y 3 no dan nada.
