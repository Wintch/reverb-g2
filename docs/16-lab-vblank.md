# 16 — El experimento del vblank: ¿es el refresh, o la forma del timing?

Preparado 2026-08-05 desde el sistema principal, con el SSD del lab montado. **El EDID de
prueba ya está generado y verificado**: `experiments/vblank/`. Falta correrlo con el casco
puesto.

---

## PREFLIGHT — correr esto antes que nada

Este experimento **sólo vale en el lab**, con el 595-open parcheado. Ya nos pasó una vez de
empezar a medir en el sistema principal, que tiene el `nvidia-current` 550.163.01 de Debian
**sin** el parche del bpc: ahí el clamp a 6 bpc está activo y cualquier resultado sale
confundido con el bug que justamente sacamos del medio.

```bash
# 1. driver correcto
grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' /proc/driver/nvidia/version | head -1
#    tiene que decir 595.71.05   (si dice 550.x estás en el sistema equivocado, rebooteá)

# 2. modulos abiertos, no los propietarios
modinfo nvidia 2>/dev/null | grep -i license
#    tiene que incluir "Dual MIT/GPL"

# 3. el parche del bpc esta adentro del modulo
./scripts/verify-bpc.sh

# 4. el casco enumera completo (los cinco)
lsusb | grep -E '04b4:6506|0bda:4c15|03f0:0580|04b4:6504|045e:0659' | wc -l
#    tiene que dar 5; si falta 03f0:0580 es el puerto USB, no Monado (docs/00)

# 5. y el bpc real en el cable
dmesg | grep 'Notify Attach Begin' | tail -1
#    tiene que decir 24 bpp, no 18
```

Si cualquiera de los cinco falla, **parar**. Medir con el driver equivocado no da un
resultado malo: da un resultado que parece bueno y apunta al lado que no es.

---

## De dónde venimos

El clamp a 6 bpc está cerrado (ver `docs/13`, `docs/14`):

- **PR abierto en NVIDIA:** https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275
- **Hilo del foro:** post 379240, revisión 6
- Con el parche el casco reporta `08` en el byte 18 y su status HID de 33 bytes queda
  idéntico byte a byte al de Windows

Y sin embargo **los dos modos de 90 Hz siguen sin mostrar imagen**: el panel enciende y
parpadea en blanco. El de 60 Hz anda.

---

## La hipótesis

En los tres modos que el EDID del G2 ofrece, el blanking **horizontal** es idéntico
(50/4/46). La única variable estructural es el **vertical**:

| modo | vblank | resultado |
|---|---|---|
| 4320x2160@60 | **514 líneas** | anda |
| 4320x2160@90 | 116 líneas | falla |
| 2880x1440@90 | 158 líneas | falla |

Es decir: **"90 Hz" y "vblank corto" están perfectamente confundidos**. Nunca se observó
un vblank corto a 60 Hz, ni uno largo a 90 Hz. Con estos tres modos es imposible saber
cuál de las dos variables rompe el panel.

El experimento inyecta los dos modos que faltan y completa el factorial.

---

## Diseño

|  | vblank corto (158) | vblank largo (514) |
|---|---|---|
| **60 Hz** | **A** — 285.72 MHz | **CTRL** — 349.38 MHz |
| **90 Hz** | nativo slot 0: **falla** | **B** — 524.06 MHz |

Los tres inyectados quedan muy por debajo de los 709.15 MHz del modo que ya funciona
(6.86 / 8.39 / 12.58 Gbps a 24 bpp), así que ninguno introduce presión de ancho de banda.

**Por qué 2880x1440 y no 4320x2160:** el DTD del bloque base tiene el campo de horizontal
active de **12 bits — máximo 4095 px**. 4320 no entra. Por eso el propio G2 pone
2880x1440 en el bloque base y sus dos modos de 4320 en el bloque DisplayID, cuyos
descriptores Type I usan campos de 16 bits. Usar 2880x1440 además mantiene la resolución
constante contra el modo nativo que falla, que es una comparación más limpia.

**`CTRL` no es opcional y va primero.** Sin él, si A falla no se puede distinguir "el
vblank corto rompe el panel" de "cualquier modo inyectado rompe". Es la línea de base.

---

## El EDID ya está armado

`experiments/vblank/g2-vblank-test.edid` — 384 bytes, partiendo de
`experiments/vblank/hmd.edid`. Los tres modos entran en los slots de DTD que
estaban libres, así que **queda un solo EDID con todo el factorial**: se corre la
experiencia entera en una sesión, sin re-overridear entre test y test.

```
bloque base   slot 0  2880x1440@90  428.58 MHz  vblank 158   nativo, FALLA
              slot 1  2880x1440@60  349.38 MHz  vblank 514   CTRL
              slot 2  2880x1440@60  285.72 MHz  vblank 158   TEST A
              slot 3  2880x1440@90  524.06 MHz  vblank 514   TEST B
DisplayID     desc 1  4320x2160@90  905.40 MHz  vblank 116   nativo, FALLA  (intacto)
              desc 2  4320x2160@60  709.15 MHz  vblank 514   nativo, ANDA   (intacto)
```

Verificado: round-trip de codificación en los tres, checksum del bloque base correcto,
y los dos bloques de extensión sin tocar byte a byte.

Para regenerarlo o variarlo:

```bash
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-test.edid CTRL:1 A:2 B:3

# sin asignaciones lista los presets y qué hay en cada slot
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid
```

Cargarlo con **el mismo mecanismo de override de EDID que se usó para el test de 8 bpc**
(`docs/13`). Ese ya está probado en este lab.

---

## Cómo correrlo

Orden: **CTRL → B → A**. Si B anda, ya está la respuesta y A es sólo confirmación.

### La verificación es física

La API miente: reporta modeset exitoso y 90.0 fps con el panel apagado. **Hay que ponerse
el casco y mirar.** Para cada modo, anotar:

- ¿enciende el panel? (backlight)
- ¿muestra contenido con color, o blanco/parpadeo?
- `dmesg`, línea `Notify Attach Begin`: pclk, raster, bpp — confirmar que dice `24 bpp`
- byte 18 del status report HID (`scripts/decode-status.sh`)

---

## Cómo leer el resultado

| CTRL | B | A | conclusión |
|---|---|---|---|
| falla | — | — | los modos inyectados no encienden este panel. **No concluyente**: falla el override o la vía de inyección, no la hipótesis. Replantear antes de seguir |
| anda | **anda** | — | **90 Hz no es el problema; el vblank corto sí.** El mejor resultado posible: le da a NVIDIA una variable concreta en vez de "miren el GSP" |
| anda | falla | anda | es el refresh, 90 Hz específicamente. Descarta el vblank y cierra esta línea |
| anda | falla | falla | ni el vblank ni el refresh por separado — apunta al pixel clock o a la combinación |

Cualquiera de las tres filas concluyentes es material para un reply al hilo 379240.

---

## Segundo experimento: el barrido de refresh

El factorial dice *si* el vblank importa. No dice *dónde* está el límite en el eje del
refresh. Para eso se mantiene la forma del timing fija y se mueve sólo el refresh:

```bash
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid \
    -o experiments/vblank/sweep-70-75-80.edid  SHORT@70:1 SHORT@75:2 SHORT@80:3
```

`SHORT` es el blanking de los modos que fallan (vblank 158), `LONG` el del que anda
(vblank 514). La forma paramétrica es `BLANKING@RATE` y acepta cualquier refresh entre
24 y 240.

**El bloque base tiene 4 slots y el 0 lleva el modo nativo, así que entran 3 por EDID.**
Por eso el barrido se hace **bisectando**, no de una sola pasada:

| ronda | modos | qué contesta |
|---|---|---|
| 1 | `SHORT@70` `SHORT@75` `SHORT@80` | ¿hay umbral, y en qué tercio cae? |
| 2 | tres valores alrededor del cambio | lo acota a ±1-2 Hz |

Referencia de pixel clocks con `SHORT` (todos muy por debajo de los 709 MHz del modo que
anda, así que ninguno mete presión de ancho de banda):

```
SHORT@65  309.53 MHz     SHORT@75  357.15 MHz
SHORT@70  333.34 MHz     SHORT@80  380.96 MHz
SHORT@72  342.87 MHz     SHORT@85  404.77 MHz
```

Cómo se lee: si el panel anda hasta cierto refresh y falla a partir de ahí **con la forma
de timing constante**, hay un umbral duro y es un dato mucho más accionable que "90 Hz
falla". Si en cambio falla a cualquier refresh distinto de 60 con `SHORT`, no es un umbral
sino la forma del timing — y refuerza lo que diga el factorial.

Correr esto **después** del factorial: si `B` (90 Hz con vblank largo) anda, el eje del
refresh ya quedó descartado y el barrido pierde sentido.

---

## Si hace falta repetirlo a 4320x2160

`edid-tool.py` ya **decodifica** los descriptores Type I de DisplayID (`decode_did_type1`),
pero todavía no los escribe. El encoder se escribió y se validó contra este EDID real: el
decoder reproduce exactamente `905.400 MHz` con vblank 116 y `709.150 MHz` con vblank 514,
así que el layout está confirmado empíricamente y agregar un `inject-did` es directo.

Layout del Type I (20 bytes, todos los campos menos las polaridades guardan `valor - 1`):

```
0-2   pixel clock / 10 kHz, 24 bits LSB primero
3     flags: bit7 preferred, bit4 interlaced
4-5   horizontal active        6-7    horizontal blanking
8-9   horizontal front porch, bit15 = polaridad hsync
10-11 horizontal sync width
12-13 vertical active          14-15  vertical blanking
16-17 vertical front porch, bit15 = polaridad vsync
18-19 vertical sync width
```

Hay que corregir **dos** checksums: el de la sección DisplayID (último byte de la sección,
que arranca en `blk+1` y mide `5 + section_size`) y el del bloque de extensión EDID
(`blk+127`).

Presets sugeridos, todos dentro de HBR3 (25.92 Gbps):

| preset | timing | pclk | Gbps @24bpp |
|---|---|---|---|
| `CTRL4K` | 4320x2160@60 vblank 514 | 709.15 MHz | 17.02 |
| `A4K` | 4320x2160@60 vblank 116 | 603.60 MHz | 14.49 |
| `B4K` | 4320x2160@90 vblank 240 | 954.72 MHz | 22.91 |

Con sólo dos descriptores en el bloque, conviene reemplazar el **desc 1** (el @90 que ya
falla) y dejar el desc 2 (@60) intacto como control.

---

## Correcciones ya aplicadas — no reintroducir

El reporte publicado tuvo errores que se corrigieron sobre la marcha. Si se redacta algo
nuevo para el foro o el PR:

- La extensión del G2 es **DisplayID 1.2** (byte de versión `0x12`), con dos descriptores
  **Type I**. NO es DisplayID 2.0 ni Type VII. *(verificado contra los bytes reales)*
- `input.u.digital.bpc` se asigna en **tres** lugares del árbol, no dos: `nvt_edid.c:932`,
  `nvt_edidext_displayid20.c:314`, y `nvkms-dpy.c:2257` — este último dentro de
  `CreateParsedEdidFromNVT_TIMING()`, que nunca corre para un sink con EDID real.
- Números de línea en el tag 595.71.05: clamp DP en `nvkms-dpy.c:3456`, dispatch DisplayID
  en `nvt_edid.c:1101`. En `main` (610.57.04) son 3468 y 1101.
- DSC se descarta **por aritmética**, no por ausencia de strings en `dmesg`: el modo que
  anda son 17.0 Gbps sin comprimir y el que falla 10.3, así que DSC no puede ser requerido
  para el que falla.
- El `.patch.txt` adjunto en el foro es **viejo**: dice "DisplayID 2.0" y trae el header de
  hunk mal contado. Hay uno regenerado en `patches/nvidia/`.

## Verificado contra los bytes reales del EDID

Todo esto se chequeó contra `experiments/vblank/hmd.edid`, y coincide con lo que
afirma el post del foro:

```
byte 0x14 = 0x80          digital, color bit depth = 000 (undefined)
checksum base block 0xE8  suma del bloque = 0
ManufID 0x220E            = HPN
CTA byte 3 = 0x00         sin YCbCr 4:4:4 ni 4:2:2
DisplayID: 70 12 79 00 00 03   version 1.2, tag 0x03, 40 bytes = 2 descriptores Type I
g2-edid-8bpc-repro.bin    difiere en exactamente 2 bytes: 0x14 y 0x7F, checksum válido
```
