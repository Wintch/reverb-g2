# 12 — Protocolo del HP Reverb G2: referencia

Todo lo que sabemos del protocolo del casco, en un solo lugar. Es la base sobre la que se
puede construir un driver o un kit de herramientas.

Lo marcado **[NUESTRO]** se descubrió en este proyecto y no está documentado en ningún otro
lado que conozcamos. Lo marcado **[MONADO]** viene del driver WMR upstream, que a su vez salió
de ingeniería inversa de OpenHMD.

---

## 1. Topología USB

El G2 presenta **cinco** dispositivos. Si falta alguno, el problema es el puerto o el cable —
no el software (cap. 00).

```
3-1    04b4:6506  Cypress   hub USB2 interno              480M
3-1.2  0bda:4c15  Realtek   audio USB (parlantes + mic)   480M
3-1.3  03f0:0580  Quanta    "QHMD A85V" = COMPANION        12M   <- HID de control
4-1    04b4:6504  Cypress   hub SuperSpeed               5000M
4-1.1  045e:0659  Microsoft "HoloLens Sensors"          5000M   <- IMU + cámaras + config
```

Los dos que importan para el protocolo son el **companion** (`03f0:0580`) y el
**HoloLens Sensors** (`045e:0659`). Los dos exponen `hidraw` y son accesibles desde el grupo
`plugdev`.

**[NUESTRO]** El comando de apagado de pantalla puede hacer **re-enumerar al companion**, que
cambia de nodo `hidraw` (visto `hidraw8` → `hidraw7`). Nunca cachear el path: hay que
re-escanear por VID:PID. Esto además explica los "resets aleatorios del hub USB2" que el
proyecto tenía como molestia sin causa: no son aleatorios, los dispara el screen-off.

---

## 2. Tipos de mensaje

**[MONADO]** `wmr_protocol.h`:

```c
#define WMR_MS_HOLOLENS_MSG_SENSORS           0x01  // stream de IMU, ~250 Hz
#define WMR_MS_HOLOLENS_MSG_CONTROL           0x02  // respuestas de lectura de config
#define WMR_MS_HOLOLENS_MSG_DEBUG             0x03  // LOG DE FIRMWARE  <-- ver §6
#define WMR_MS_HOLOLENS_MSG_BT_IFACE          0x05
#define WMR_MS_HOLOLENS_MSG_LEFT_CONTROLLER   0x06
#define WMR_MS_HOLOLENS_MSG_RIGHT_CONTROLLER  0x0E
#define WMR_MS_HOLOLENS_MSG_BT_CONTROL        0x16
#define WMR_MS_HOLOLENS_MSG_CONTROLLER_STATUS 0x17

// del COMPANION:
#define WMR_CONTROL_MSG_IPD_VALUE     0x01  // proximidad + IPD
#define WMR_CONTROL_MSG_UNKNOWN_02    0x02
#define WMR_CONTROL_MSG_DEVICE_STATUS 0x05  // ESTADO DE PANEL  <-- ver §5
```

---

## 3. Encendido del panel

### 3.1 Secuencia de activación (Reverb G1 y G2)

**[MONADO]** `wmr_hmd_activate_reverb()`, `wmr_hmd.c:767`. Va al **companion**:

```
sleep 300 ms                    ("es lo que hace Windows")
x4:  SET_FEATURE {0x50, 0x01}   (64 bytes)   <- "hack" heredado de OpenHMD, del G1
     GET_FEATURE  0x50
     sleep 10 ms
GET_FEATURE 0x09   -> devuelve el NUMERO DE SERIE en ASCII  (ej. "REDACTED")
GET_FEATURE 0x08   -> devuelve el UID en ASCII
GET_FEATURE 0x06   -> ceros
SET_FEATURE {0x04, 0x01}        <- screen enable
```

**[NUESTRO] El `{0x04,0x01}` solo NO alcanza.** Sin la secuencia completa el casco queda
totalmente apagado, ni siquiera muestra el logo de HP. Implementado en `scripts/panel.py
activate`.

**[MONADO]** La activación **NO es igual entre marcas**: el Samsung Odyssey y Odyssey+ hacen
`GET 0x16 / 0x15 / 0x14` en lugar del loop `0x50` y los gets `0x09/0x08/0x06`.

**[MONADO]** De los 12 cascos del `headset_map[]` de Monado, **sólo 4 tienen función de
activación**: Reverb G1, Reverb G2, Odyssey y Odyssey+. Lenovo Explorer, Dell Visor, Acer
AH100/AH101, Medion Erazer y Fujitsu tienen `NULL` — Monado no sabe encenderles el panel. Es
un agujero real para cualquier objetivo de "driver universal".

### 3.2 Encender / apagar

**[MONADO]** `wmr_hmd_screen_enable_reverb()`, `wmr_hmd.c:846`:

```
SET_FEATURE {0x04, 0x01}   encender
SET_FEATURE {0x04, 0x00}   apagar
```

**[NUESTRO, del driver de HP]** Windows manda **exactamente lo mismo**, sólo que expresado por
usages HID en vez de bytes crudos: **Usage Page `0x03` (VR Controls) / Usage `0x21` (Display
Enable)**, ReportType Feature. El driver arma el reporte con `HidP_SetUsageValue` y saca el
report ID del `HIDP_VALUE_CAPS`. El efecto sobre el casco es idéntico. Ver cap. 09.

---

## 4. Lo que NO existe: comando de refresh rate

**[NUESTRO]** Se desensambló el driver **Oasis de HP** completo — los cuatro binarios — que es
el que corre el G2 a 90 Hz en Windows hablándole al casco directo, sin pasar por el runtime
WMR del SO. **Su único comando de panel es Display Enable.** No hay comando de modo, refresh ni
resolución (cap. 09).

Confirmación independiente: **thaytan**, autor del driver WMR de Monado, declara que después
del comando de *enable display* nada del USB influye en el modo — la negociación es toda
DisplayPort a nivel de driver de GPU.

**El panel adopta el timing del video que le llega.** Punto.

---

## 5. `DEVICE_STATUS` (0x05) — el estado del panel  **[NUESTRO]**

El companion emite un reporte de **33 bytes** cuando cambia el estado de pantalla. Es la única
instrumentación del lado del *sink* que existe: todo lo demás (Vulkan, el log de NVIDIA)
reporta éxito con el panel muerto.

### Campos decodificados

| offset | campo | evidencia |
|---|---|---|
| 0 | `0x05` (tipo de mensaje) | — |
| 1 | *backlight encendido* (a veces `1`) | ver la advertencia abajo |
| 2 | pantalla habilitada: `0`→`1` con el screen-enable | aislando la activación HID sin video |
| **5** | **refresh rate en decimal** | `0x3c`=60, `0x5a`=90, en dos resoluciones distintas |
| 9, 10 | desconocidos, cambian por modo | — |
| **11** | acompaña al refresh: `0x1e`(30) a 60Hz, `0x14`(20) a 90Hz | — |
| 12 | desconocido: `02` en dos modos, `04` en `4320x2160@90` | — |
| 14, 15 | desconocidos: `77 00` o `77 77` | — |
| **19-20** | **htotal**, little-endian | `44 11`=4420, `a4 0b`=2980 |
| **21-22** | **vtotal**, little-endian | `72 0a`=2674, `3e 06`=1598, `e4 08`=2276 |
| 24-31 | desconocidos: `00 80` repetido, o `ff ff` | — |

### Mensajes de referencia medidos

```
60Hz  4320x2160 ANDA   05 00 01 01 00 3c 00 00 00 05 2c 1e 02 00 77 00 00 00 06 44 11 72 0a 01 00 80 00 80 ff ff ff ff 02
90Hz  2880x1440 FALLA  05 00 01 01 00 5a 00 00 00 0c 1a 14 02 00 77 00 00 00 06 a4 0b 3e 06 01 00 80 00 80 ff ff ff ff 02
90Hz  4320x2160 FALLA  05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 01 00 80 00 80 00 80 00 80 02
```

Los tres valores de refresh/htotal/vtotal coinciden **exactamente** con los modos del EDID. Y
con la activación HID pero **sin video**, esos campos vienen en cero — o sea que el casco los
rellena **midiendo**, no repitiendo lo que le dijeron.

**Conclusión: el casco recibe y mide el timing correcto también a 90 Hz.**

### Advertencia sobre el byte 1

Se creyó tener un detector automático de éxito: el `byte 1 = 1` apareció en 3 de 3 mensajes
del modo que anda y en 0 de 8 de los que fallan, y coincide con el comentario de Monado para
el G1 (*"once the HMD screen backlight visibly powers on"*). **No resistió la validación**:
probado dos veces contra el modo de 60 conocido-bueno, una dio "FALLA" y la otra no emitió
mensajes. Aparece **sólo a veces**. Sirve como pista, **no como instrumento**.

**La verificación sigue siendo FÍSICA.**

### Cómo capturarlo

`scripts/panel-status.py`. Los mensajes salen **sólo cuando algo cambia**: hay que estar
escuchando *durante* la activación o el cambio de modo, no en régimen.

---

## 6. `0x03 DEBUG` — el log de firmware del casco  **[NUESTRO]**

El G2 emite su propio log de firmware **en ASCII**, por la interfaz HoloLens Sensors. Paquetes
de **509 bytes** con varias entradas concatenadas y rellenadas con ceros.

### Formato de cada entrada

```
magic "Dlo+" | 4 bytes timestamp | 2 bytes secuencia | 1 byte nivel | texto ASCII \0
```

### Entradas capturadas

```
RequestImuDisable forSpi=0
ImuDisable Req=0 Spi=0
RequestImuEnable forSpi=0
ICMStart
ICM start status=0
ERROR: CommandSet st 0, cmd 0, reqCmd 23
```

### Cómo destrabarlo

**El canal está MUDO** hasta que alguien hace la secuencia de configuración del casco (§7).
`hmd-vk` no la hace y no sale nada; `monado-service` sí y el canal empieza a hablar.
Herramienta: `scripts/fwlog.py`.

### Lo que NO dice

**[NUESTRO]** El firmware **no loguea ni un solo error de panel a 90 Hz**. El
`ERROR: CommandSet st 0, cmd 0, reqCmd 23` que aparece cada 5 s está **igual a 60 Hz que a
90 Hz** — es ruido del subsistema de controllers (`reqCmd 23` = `0x17 CONTROLLER_STATUS`), y
el control lo desactiva como pista. El `DMA CMT ERR` que otro usuario reportó en el issue #332
de Monado **no se reproduce acá**.

---

## 7. Lectura de bloques de configuración

**[MONADO]** `wmr_config_command_sync()`. Va al **HoloLens Sensors**: se escribe un reporte de
salida de 64 bytes `{0x02, tipo, 0...}` y se lee hasta recibir un reporte cuyo primer byte sea
`0x02` (`MSG_CONTROL`).

Secuencia completa para leer el bloque de calibración:

```
{0x02, 0x0b}   inicio
{0x02, 0x06}   tipo de bloque
{0x02, 0x08}   repetir; buf[1]==0x01 = hay más, buf[2] = largo, datos en buf[3..]
```

El blob viene ofuscado con un XOR de clave fija (`wmr_config_key` en Monado) y adentro trae un
header con fabricante, dispositivo, serie, UID y revisión, más un JSON.

**[NUESTRO]** Volcado del nuestro:

```
Manufacturer: HP Inc.
Device:       VR3000-0XX          <- coincide con el SKU del expediente FCC HFS-A85R
Serial:       REDACTED
UID:          {EE4482CE-AFE7-5844-820A-73F26905A52F}
Revision:     RevB.N.J   (2020-10-30)
```

**El JSON es puro calibrado de cámaras** — `CalibrationInformation`, `Intrinsics`,
`ModelParameters`, `Rt`, `SensorWidth/Height`, `Shutter`, `ThermalAdjustmentParams`. **Ni una
clave de display, panel o refresh.** Línea cerrada.

---

## 8. Cadena de video

```
GPU ──DisplayPort 1.4── ANX7530 ──2x MIPI-DSI── 2x panel LCD ── backlight (driver ?)
                        (Analogix)                (2160x2160 c/u)
```

- **`ANX7530`** (Analogix): puente DP→MIPI DSI. Dos salidas independientes, una por panel, de
  8 lanes a 1.5 Gbps = **12 Gbps por salida**. Por panel a 90 Hz hacen falta
  2160×2160×90×24bpp = **10.08 Gbps**: entra, con poco margen. Su product brief titula *"hasta
  4K × 2K @ 60Hz"*. **No tiene DSC** en la salida MIPI. Se configura por **I2C desde el
  STM32** del casco, no desde el host. Sin datasheet público de registros.
- **`ANX7688`** (Analogix): también presente. Su datasheet lo ubica del lado host
  (HDMI2.0+USB3.1 → USB-C); **qué hace dentro del casco no lo explica ninguna fuente**.
- **STM32** con ruta **DFU** y bancos de firmware (`bridge_fw_check_update`,
  `bridge_fw_switch_bank`, `QCI_FEATURE_ERASE_FLASH`). `MROEMFwHost.dll` de HP es el
  actualizador. **Puede escribir firmware al casco**: no meterse sin una razón muy buena.
- **Paneles**: parte `AA029M48000 REV.02` rotulada "JDP"; candidato comercial **Sharp
  LS029B3SX06/06A**, 2.9″, 2160×2160, CG-Silicon LTPS, MIPI-DSI de 2 canales × 4 lanes, **sin
  backlight integrado**.
- **Driver de backlight**: **sin dato público**. Las fotos de la FCC no alcanzan a resolverlo
  (cap. 10).
- **`LIF-MD6000`** (Lattice CrossLink): **NO es el puente de video** — es el agregador de las
  4 cámaras. Se lo señaló como puente por error y se corrigió.
- **Serigrafías útiles en la placa** (fotos FCC): `MCU Download` y **`DES JTAG`**. Hay un JTAG
  accesible al chip de video.

### Modos del EDID

| idx | modo | pixel clock | htotal × vtotal | a 24bpp |
|---|---|---|---|---|
| 0 | 4320x2160@90 | 905150 kHz | 4420 × 2276 | 21.73 Gbps |
| 1 | 2880x1440@90 | 428580 kHz | 2980 × 1598 | 10.29 Gbps |
| 2 | 4320x2160@60 | 709150 kHz | 4420 × 2674 | 17.02 Gbps |

EDID de 3 bloques: base + CEA + **DisplayID 2.0** embebido (tag `0x70`) con un bloque Type VII.
ManufID `0x220E` = `HPN`.

**Ojo con el pixel clock de DisplayID 2.0: está en unidades de 10 kHz, no kHz.** Leerlo mal da
"9 Hz" y "6 Hz" — pasó.

---

## 9. Herramientas de este repo

| script | qué hace |
|---|---|
| `panel.py` | `activate` / `on` / `off` / `cycle` del panel por HID, sin Monado |
| `panel-status.py` | escucha el `DEVICE_STATUS` (§5) |
| `fwlog.py` | decodifica el log de firmware (§6) |
| `hmd-vk.c` | modeset y presentación por Vulkan display, sin Monado ni OpenXR |
| `hmd-modeset.c` | modeset por KMS — **no funciona en NVIDIA**, se conserva porque el fallo informa |
| `lease-planes.c` | qué objetos trae el lease de mutter |
| `drmprops.c` | `non-desktop` y modos del conector, desde el kernel |
| `check-lease.sh` | ¿el compositor ofrece el conector para arrendar? |
| `decode-status.sh` | matriz automatizada para decodificar el `DEVICE_STATUS` |
| `hunt-debug.py` | caza mensajes no-sensores en las dos interfaces |
| `testlog.py` | registro de pruebas físicas con veredicto textual |
| `hmd-watch.py` | proximidad + movimiento, para saber si el usuario miró |
| `xref.py` | xrefs de strings en binarios PE, sólo con binutils |
| `pdf2md.py` | PDF → markdown + extracción de imágenes, sin dependencias |
| `collect-nv.sh` | logs del driver NVIDIA en los tres modos (necesita root) |

---

## 10. Reglas de método que este proyecto pagó caro

1. **La verificación del panel es FÍSICA.** Vulkan y OpenXR reportan éxito y 90.0 fps con el
   panel completamente negro. El log de NVIDIA reporta attach exitoso en los tres modos, sin
   un solo error. **Ningún instrumento de software distingue el éxito del fallo.**
2. **Toda medición necesita su control, corrido el mismo día.** Cuatro hallazgos de una sola
   sesión murieron al correrles el control: el `18 bpp`, el detector automático del byte 1, el
   `DMA CMT ERR`, y la lectura de que el fallo era del casco.
3. **Las pruebas no pueden vencer mientras el humano mira.** Por eso `hmd-vk` sostiene la
   imagen indefinidamente y `testlog.py` anota el veredicto textual con un ID.
4. **Al cerrar una línea, actualizar `CLAUDE.md` en el mismo commit.** Una hipótesis ya
   descartada quedó viva ahí unas horas y se la volvió a citar como "la única que explica los
   resultados".
